"""AgentSpec: the single contract between interview, generator, tester and runtime."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Tools the factory knows about. We add more as we build them.
KNOWN_TOOLS = {
    "fs.read", "fs.list", "fs.write", "fs.move",
    "http.fetch",
    "notes.read", "notes.append",
    "srs.add", "srs.due", "srs.review",
    "code.run", "code.check_name",
    "script.run",
}

# Which permission each tool needs. Empty/False permission = tool not allowed.
TOOL_REQUIRES = {
    "fs.read": "fs_read", "fs.list": "fs_read",
    "fs.write": "fs_write", "fs.move": "fs_write",
    "http.fetch": "network",
    "code.run": "shell", "code.check_name": "shell",
    "script.run": "shell",
}

# Small local models get confused with many tools.
MAX_TOOLS = 6


class Strict(BaseModel):
    """Reject unknown fields so typos in a spec fail loudly."""
    model_config = ConfigDict(extra="forbid")


class ModelConfig(Strict):
    provider: Literal["ollama"] = "ollama"
    name: str = "qwen3:8b"
    num_ctx: int = Field(8192, ge=2048, le=32768)
    temperature: float = Field(0.2, ge=0, le=1.5)
    think: bool = False  # let the model reason before answering (slower, uses more memory)


class Trigger(Strict):
    type: Literal["manual", "schedule", "file_watch"] = "manual"
    cron: str | None = None   # for type=schedule
    path: str | None = None   # for type=file_watch

    @model_validator(mode="after")
    def _check(self) -> "Trigger":
        if self.type == "schedule" and not self.cron:
            raise ValueError("trigger type 'schedule' needs a cron expression")
        if self.type == "file_watch" and not self.path:
            raise ValueError("trigger type 'file_watch' needs a path")
        return self


class Permissions(Strict):
    fs_read: list[str] = Field(default_factory=list)
    fs_write: list[str] = Field(default_factory=list)
    network: list[str] = Field(default_factory=list)  # allowed domains
    shell: bool = False
    allow_overwrite: bool = False  # may fs.write replace files that already exist?

    @field_validator("network")
    @classmethod
    def _domains_only(cls, v: list[str]) -> list[str]:
        for d in v:
            if not d.strip() or "*" in d or " " in d:
                raise ValueError(
                    f"network entries must be plain domains like example.com, got '{d}'"
                )
        return v


class Limits(Strict):
    max_steps: int = Field(20, ge=1, le=100)
    max_tokens: int = Field(50_000, ge=1000)
    max_runtime_s: int = Field(120, ge=5)


class Memory(Strict):
    notes: bool = False   # free-form notes file per agent
    srs: bool = False     # spaced-repetition database


class Appearance(Strict):
    """How the agent looks in the office. Everything is optional."""
    display_name: str | None = Field(None, max_length=30)
    color: str | None = None  # shirt and accent colour, "#rrggbb"
    hair: str | None = None   # hair colour, "#rrggbb"

    @field_validator("color", "hair")
    @classmethod
    def _hex(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
            raise ValueError("colours must look like #8c7cf6")
        return v


class AgentSpec(Strict):
    name: str
    version: int = Field(1, ge=1)
    mode: Literal["task", "conversational"] = "task"
    goal: str = Field(min_length=10)
    system_prompt: str = ""
    model: ModelConfig = Field(default_factory=ModelConfig)
    trigger: Trigger = Field(default_factory=Trigger)
    tools: list[str] = Field(default_factory=list)
    permissions: Permissions = Field(default_factory=Permissions)
    limits: Limits = Field(default_factory=Limits)
    memory: Memory = Field(default_factory=Memory)
    success_criteria: list[str] = Field(default_factory=list)
    appearance: Appearance = Field(default_factory=Appearance)
    read_before_answer: bool = False  # nudge once to read a file before answering file questions
    verify_code_blocks: bool = False  # nudge once to run code before showing it (needs code.run)

    @field_validator("name")
    @classmethod
    def _name_is_slug(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9-]{2,40}", v):
            raise ValueError(
                "name must be a lowercase slug (3-41 chars, letters/digits/hyphens, "
                "starting with a letter)"
            )
        return v

    @model_validator(mode="after")
    def _check_tools(self) -> "AgentSpec":
        if len(self.tools) > MAX_TOOLS:
            raise ValueError(f"at most {MAX_TOOLS} tools allowed, got {len(self.tools)}")
        if len(set(self.tools)) != len(self.tools):
            raise ValueError("duplicate tools in list")

        for tool in self.tools:
            if tool not in KNOWN_TOOLS:
                raise ValueError(f"unknown tool: {tool}")

            needed = TOOL_REQUIRES.get(tool)
            if needed and not getattr(self.permissions, needed):
                raise ValueError(f"tool '{tool}' needs permissions.{needed} to be set")

            if tool.startswith("notes.") and not self.memory.notes:
                raise ValueError(f"tool '{tool}' needs memory.notes: true")
            if tool.startswith("srs.") and not self.memory.srs:
                raise ValueError(f"tool '{tool}' needs memory.srs: true")
        return self


def load_spec(path: str | Path) -> AgentSpec:
    """Read a YAML file and return a validated AgentSpec."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return AgentSpec.model_validate(data)
