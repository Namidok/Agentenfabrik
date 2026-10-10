"""LLM provider interface, Ollama client, and a scripted mock for tests."""
from __future__ import annotations

import copy
import json
import re
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


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        model: str = "qwen3:8b",
        num_ctx: int = 8192,
        temperature: float = 0.2,
        host: str = "http://localhost:11434",
        timeout: float = 300.0,
        think: bool | None = False,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self.num_ctx = num_ctx
        self.temperature = temperature
        self.host = host
        self.think = think
        self._client = client or httpx.Client(base_url=host, timeout=timeout)

    def chat(self, messages, tools=None, schema=None) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"num_ctx": self.num_ctx, "temperature": self.temperature},
        }
        if tools:
            payload["tools"] = tools
        if schema:
            payload["format"] = schema
        if self.think is not None:
            payload["think"] = self.think

        try:
            resp = self._client.post("/api/chat", json=payload)
        except httpx.ConnectError as e:
            raise ProviderError(
                f"Cannot reach Ollama at {self.host}. "
                "Open the Ollama app (or run `ollama serve`) and try again."
            ) from e
        except httpx.TimeoutException as e:
            raise ProviderError(
                f"Ollama timed out. The model may still be loading; try again in a minute."
            ) from e

        if resp.status_code == 404:
            raise ProviderError(
                f"Model '{self.model}' not found. Run: ollama pull {self.model}"
            )
        if resp.status_code != 200:
            raise ProviderError(f"Ollama returned {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        msg = data.get("message") or {}
        content = _THINK_RE.sub("", msg.get("content") or "").strip()

        calls: list[ToolCall] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append(ToolCall(name=fn.get("name", ""), arguments=args))

        prompt_tokens = int(data.get("prompt_eval_count") or 0)
        return LLMResponse(
            content=content,
            tool_calls=calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=int(data.get("eval_count") or 0),
            near_context_limit=prompt_tokens >= self.num_ctx - 16,
        )


class MockProvider(LLMProvider):
    """Returns pre-scripted responses in order. For tests, no model needed."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, tools=None, schema=None) -> LLMResponse:
        self.calls.append({"messages": copy.deepcopy(messages), "tools": tools, "schema": schema})
        if not self._responses:
            raise ProviderError("MockProvider ran out of scripted responses")
        return self._responses.pop(0)


def make_provider(cfg: ModelConfig) -> LLMProvider:
    """Build the right provider from a spec's model section."""
    if cfg.provider == "ollama":
        return OllamaProvider(
            model=cfg.name, num_ctx=cfg.num_ctx, temperature=cfg.temperature, think=cfg.think
        )
    raise ProviderError(f"Unknown provider: {cfg.provider}")
