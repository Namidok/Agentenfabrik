"""App-wide settings, read from settings.yaml in the project folder. The file is optional.

default_model: the model an agent uses when its spec does not name one (model.name).
max_parallel:  how many agents may think at the same time (1 to 3, default 2). More than 1 only helps
               when Ollama is started with OLLAMA_NUM_PARALLEL set to at least the same number.
               The environment variable AGENTFACTORY_MAX_PARALLEL overrides the file.
keep_alive:    how long Ollama keeps a model in memory after its last request ("30m", "2h", "-1" = forever)."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import Field, ValidationError

from factory.schema import ModelConfig, Strict


ENV_PARALLEL = "AGENTFACTORY_MAX_PARALLEL"
# Context tokens (num_ctx x parallel slots) above which a 16 GB Mac is likely to swap with an 8B model.
CONTEXT_WARN_TOKENS = 16384


class Settings(Strict):
    default_model: str = Field("qwen3:8b", min_length=1)
    max_parallel: int = Field(2, ge=1, le=3)
    keep_alive: str = Field("30m", pattern=r"^-?\d+(\.\d+)?[smh]?$")


def load_settings(path: Path, env: dict[str, str] | None = None) -> tuple[Settings, str]:
    """The settings and an error message ("" when fine). A broken file or variable falls back to the defaults."""
    env = os.environ if env is None else env
    data: dict = {}
    try:
        if path.is_file():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if env.get(ENV_PARALLEL, "").strip():
            raw = env[ENV_PARALLEL].strip()
            data = {**data, "max_parallel": int(raw) if raw.isdigit() else raw}
        return Settings.model_validate(data), ""
    except ValidationError as e:
        err = e.errors()[0]
        where = ".".join(str(x) for x in err["loc"]) or "settings"
        return Settings(), f"{path.name}: {where}: {err['msg']}. Using the defaults."
    except (OSError, UnicodeDecodeError, yaml.YAMLError, AttributeError) as e:
        return Settings(), f"{path.name} could not be read ({type(e).__name__}). Using the defaults."


def memory_warnings(settings: Settings, contexts: dict[str, int]) -> list[str]:
    """contexts: model name -> the largest num_ctx an agent asks for. Ollama keeps num_ctx tokens per slot."""
    out = []
    for model, num_ctx in sorted(contexts.items()):
        total = num_ctx * settings.max_parallel
        if settings.max_parallel > 1 and total > CONTEXT_WARN_TOKENS:
            out.append(f"{model}: {settings.max_parallel} parallel slots x num_ctx {num_ctx} = {total:,} context tokens. "
                       "On a 16 GB Mac this may swap and make every agent slower. Lower max_parallel or num_ctx.")
    return out


# Most tokens one reply may have: chat replies are short, a task agent may write a long answer or file.
NUM_PREDICT = {"conversational": 768, "task": 2048}


def apply_options(provider, mode: str, settings: Settings) -> None:
    """Request options the spec format does not carry: how long the model stays loaded, and a cap on
    reply length per kind of agent (it stops a runaway reply, it does not shorten normal ones)."""
    if hasattr(provider, "keep_alive"):
        provider.keep_alive = settings.keep_alive
    if hasattr(provider, "num_predict"):
        provider.num_predict = NUM_PREDICT.get(mode, NUM_PREDICT["task"])


def model_for(spec_model: ModelConfig, settings: Settings) -> tuple[ModelConfig, str]:
    """The model an agent really runs on, and where that name came from: "spec" or "default"."""
    if "name" in spec_model.model_fields_set:
        return spec_model, "spec"
    return spec_model.model_copy(update={"name": settings.default_model}), "default"
