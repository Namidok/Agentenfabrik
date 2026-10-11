"""LLM provider interface, Ollama client, and a scripted mock for tests."""
from __future__ import annotations

import copy
import dataclasses
import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

from factory.schema import ModelConfig

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class ProviderError(RuntimeError):
    """Anything that goes wrong while talking to a model."""


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    near_context_limit: bool = False  # True = prompt may have been silently truncated
    # Timings reported by Ollama, in seconds (0 when unknown): loading the model, reading the prompt,
    # writing the answer. load + prompt_eval is the wait before the first token.
    load_s: float = 0.0
    prompt_eval_s: float = 0.0
    eval_s: float = 0.0
    done_reason: str = ""
    first_token_s: float = 0.0  # measured when streaming: request start to the first piece of output

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMProvider(ABC):
    """Every model backend implements this one method."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """messages: [{"role": "system|user|assistant|tool", "content": "..."}]
        tools:  Ollama/OpenAI-style function definitions
        schema: JSON schema to constrain the reply (structured output)"""


class ProviderCancelled(ProviderError):
    """The request was stopped on purpose (the Stop button) while the model was still writing."""


def _parse_calls(raw: list[dict[str, Any]] | None) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for tc in raw or []:
        fn = tc.get("function") or {}
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        calls.append(ToolCall(name=fn.get("name", ""), arguments=args))
    return calls


class OllamaProvider(LLMProvider):
    streams = True  # chat() accepts on_token and should_stop

    def __init__(
        self,
        model: str = "qwen3:8b",
        num_ctx: int = 8192,
        temperature: float = 0.2,
        host: str = "http://localhost:11434",
        timeout: float = 300.0,
        think: bool | None = False,
        client: httpx.Client | None = None,
        keep_alive: str | None = None,
        num_predict: int | None = None,
    ) -> None:
        self.model = model
        self.num_ctx = num_ctx
        self.temperature = temperature
        self.host = host
        self.think = think
        self.keep_alive = keep_alive  # how long Ollama keeps the model loaded after this request
        self.num_predict = num_predict  # most tokens one reply may have (None = no cap)
        self._client = client or httpx.Client(base_url=host, timeout=timeout)

    def _payload(self, messages, tools, schema, stream: bool) -> dict[str, Any]:
        options: dict[str, Any] = {"num_ctx": self.num_ctx, "temperature": self.temperature}
        if self.num_predict:
            options["num_predict"] = self.num_predict
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "stream": stream, "options": options}
        if tools:
            payload["tools"] = tools
        if schema:
            payload["format"] = schema
        if self.think is not None:
            payload["think"] = self.think
        if self.keep_alive:
            payload["keep_alive"] = self.keep_alive
        return payload

    def _status_error(self, status: int, text: str) -> ProviderError:
        if status == 404:
            return ProviderError(f"Model '{self.model}' not found. Run: ollama pull {self.model}")
        return ProviderError(f"Ollama returned {status}: {text[:300]}")

    def _response(self, data: dict[str, Any], content: str, calls: list[ToolCall], first_token_s: float) -> LLMResponse:
        prompt_tokens = int(data.get("prompt_eval_count") or 0)
        ns = lambda key: int(data.get(key) or 0) / 1e9  # noqa: E731
        return LLMResponse(
            content=_THINK_RE.sub("", content).strip(),
            tool_calls=calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=int(data.get("eval_count") or 0),
            near_context_limit=prompt_tokens >= self.num_ctx - 16,
            load_s=ns("load_duration"),
            prompt_eval_s=ns("prompt_eval_duration"),
            eval_s=ns("eval_duration"),
            done_reason=str(data.get("done_reason") or ""),
            first_token_s=first_token_s,
        )

    def chat(self, messages, tools=None, schema=None, on_token=None, should_stop=None, on_call=None) -> LLMResponse:
        """on_token(text) gets every piece of the reply as it is written; should_stop() is asked between
        pieces and ends the request early (ProviderCancelled); on_call(call) sees each tool call as soon as
        it is complete and may return False to end the reply there, keeping the calls so far.
        Without any of them, one plain request."""
        streaming = on_token is not None or should_stop is not None or on_call is not None
        started = time.monotonic()
        try:
            if not streaming:
                resp = self._client.post("/api/chat", json=self._payload(messages, tools, schema, False))
                if resp.status_code != 200:
                    raise self._status_error(resp.status_code, resp.text)
                data = resp.json()
                msg = data.get("message") or {}
                return self._response(data, msg.get("content") or "", _parse_calls(msg.get("tool_calls")), 0.0)

            parts: list[str] = []
            calls: list[ToolCall] = []
            first = 0.0
            data: dict[str, Any] = {}
            with self._client.stream("POST", "/api/chat", json=self._payload(messages, tools, schema, True)) as resp:
                if resp.status_code != 200:
                    resp.read()
                    raise self._status_error(resp.status_code, resp.text)
                for line in resp.iter_lines():
                    if should_stop and should_stop():
                        raise ProviderCancelled("Stopped while the model was writing.")
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if data.get("error"):
                        raise ProviderError(f"Ollama: {data['error']}")
                    msg = data.get("message") or {}
                    piece = msg.get("content") or ""
                    new_calls = _parse_calls(msg.get("tool_calls"))
                    if (piece or new_calls) and not first:
                        first = time.monotonic() - started
                    if piece:
                        parts.append(piece)
                        if on_token:
                            on_token(piece)
                    enough = False
                    for call in new_calls:
                        calls.append(call)
                        if on_call and on_call(call) is False:
                            enough = True  # the caller has what it needs: stop writing, save the time
                            break
                    if enough:
                        data = {**data, "done_reason": "early"}
                        break
                    if data.get("done"):
                        break
            return self._response(data, "".join(parts), calls, first)
        except httpx.ConnectError as e:
            raise ProviderError(
                f"Cannot reach Ollama at {self.host}. "
                "Open the Ollama app (or run `ollama serve`) and try again."
            ) from e
        except httpx.TimeoutException as e:
            raise ProviderError(
                "Ollama timed out. The model may still be loading; try again in a minute."
            ) from e


def loaded_models(host: str = "http://localhost:11434", client: httpx.Client | None = None) -> dict[str, int] | None:
    """Models Ollama has in memory right now, with their context size; None when Ollama is not reachable."""
    try:
        r = (client or httpx).get(f"{host}/api/ps", timeout=1.5)
        r.raise_for_status()
        return {m.get("name", ""): int(m.get("context_length") or 0) for m in r.json().get("models", [])}
    except (httpx.HTTPError, ValueError, AttributeError):
        return None


def is_loaded(cfg: ModelConfig, loaded: dict[str, int] | None) -> bool | None:
    """True when the model is in memory with this context size (anything else means a load first)."""
    if loaded is None:
        return None
    name = cfg.name if ":" in cfg.name else f"{cfg.name}:latest"
    return loaded.get(name) == cfg.num_ctx or loaded.get(cfg.name) == cfg.num_ctx


def warm(cfg: ModelConfig, keep_alive: str | None = None, host: str = "http://localhost:11434",
         client: httpx.Client | None = None) -> bool:
    """Load the model with the context size agents will use, so the first message is not a cold start.
    An empty prompt makes Ollama load the model and answer nothing."""
    payload: dict[str, Any] = {"model": cfg.name, "prompt": "", "stream": False, "options": {"num_ctx": cfg.num_ctx}}
    if keep_alive:
        payload["keep_alive"] = keep_alive
    try:
        r = (client or httpx).post(f"{host}/api/generate", json=payload, timeout=300)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


class MockProvider(LLMProvider):
    """Returns pre-scripted responses in order. For tests, no model needed. When the runtime streams,
    the content arrives in small pieces, and should_stop is asked between them, like the real thing."""

    streams = True

    def __init__(self, responses: list[LLMResponse], piece: int = 8) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.piece = piece

    def chat(self, messages, tools=None, schema=None, on_token=None, should_stop=None, on_call=None) -> LLMResponse:
        self.calls.append({"messages": copy.deepcopy(messages), "tools": tools, "schema": schema})
        if not self._responses:
            raise ProviderError("MockProvider ran out of scripted responses")
        resp = self._responses.pop(0)
        if on_call:
            for i, call in enumerate(resp.tool_calls):
                if on_call(call) is False:
                    resp = dataclasses.replace(resp, tool_calls=resp.tool_calls[: i + 1], done_reason="early")
                    break
        if on_token or should_stop:
            for i in range(0, len(resp.content), self.piece):
                if should_stop and should_stop():
                    raise ProviderCancelled("Stopped while the model was writing.")
                if on_token:
                    on_token(resp.content[i:i + self.piece])
        return resp


def make_provider(cfg: ModelConfig) -> LLMProvider:
    """Build the right provider from a spec's model section."""
    if cfg.provider == "ollama":
        return OllamaProvider(
            model=cfg.name, num_ctx=cfg.num_ctx, temperature=cfg.temperature, think=cfg.think
        )
    raise ProviderError(f"Unknown provider: {cfg.provider}")
