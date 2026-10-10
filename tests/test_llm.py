import json

import httpx
import pytest

from factory.llm import (
    LLMResponse,
    MockProvider,
    OllamaProvider,
    ProviderError,
    make_provider,
)
from factory.schema import ModelConfig


def provider_with(handler, **kwargs) -> OllamaProvider:
    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://localhost:11434"
    )
    return OllamaProvider(client=client, **kwargs)


def reply(message: dict, **extra) -> httpx.Response:
    return httpx.Response(200, json={"message": message, **extra})


def test_plain_reply_and_token_counts():
    def handler(request):
        return reply(
            {"role": "assistant", "content": "Hi there"},
            prompt_eval_count=12,
            eval_count=3,
        )

    r = provider_with(handler).chat([{"role": "user", "content": "hi"}])
    assert r.content == "Hi there"
    assert r.tool_calls == []
    assert (r.prompt_tokens, r.completion_tokens, r.total_tokens) == (12, 3, 15)
    assert r.near_context_limit is False


def test_request_payload_has_options_tools_and_schema():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return reply({"role": "assistant", "content": "{}"})

    tools = [{"type": "function", "function": {"name": "x", "parameters": {}}}]
    schema = {"type": "object"}
    provider_with(handler, num_ctx=4096, temperature=0.5).chat(
        [{"role": "user", "content": "hi"}], tools=tools, schema=schema
    )
    assert seen["options"] == {"num_ctx": 4096, "temperature": 0.5}
    assert seen["tools"] == tools
    assert seen["format"] == schema
    assert seen["stream"] is False
    assert seen["think"] is False


def test_tool_calls_are_parsed():
    def handler(request):
        return reply(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "fs_list", "arguments": {"path": "./sandbox"}}}
                ],
            }
        )

    r = provider_with(handler).chat([{"role": "user", "content": "list"}])
    assert len(r.tool_calls) == 1
    assert r.tool_calls[0].name == "fs_list"
    assert r.tool_calls[0].arguments == {"path": "./sandbox"}


def test_string_arguments_are_decoded():
    def handler(request):
        return reply(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "t", "arguments": '{"a": 1}'}}],
            }
        )

    r = provider_with(handler).chat([{"role": "user", "content": "x"}])
    assert r.tool_calls[0].arguments == {"a": 1}


def test_think_tags_are_stripped():
    def handler(request):
        return reply({"role": "assistant", "content": "<think>hmm...</think>Answer"})

    r = provider_with(handler).chat([{"role": "user", "content": "x"}])
    assert r.content == "Answer"


def test_near_context_limit_flag():
    def handler(request):
        return reply({"role": "assistant", "content": "ok"}, prompt_eval_count=8190)

    r = provider_with(handler, num_ctx=8192).chat([{"role": "user", "content": "x"}])
    assert r.near_context_limit is True


def test_connection_error_has_helpful_message():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(ProviderError, match="Cannot reach Ollama"):
        provider_with(handler).chat([{"role": "user", "content": "x"}])


def test_missing_model_says_how_to_pull():
    def handler(request):
        return httpx.Response(404, json={"error": "model not found"})

    with pytest.raises(ProviderError, match="ollama pull qwen3:8b"):
        provider_with(handler).chat([{"role": "user", "content": "x"}])


def test_server_error_is_reported():
    def handler(request):
        return httpx.Response(500, text="boom")

    with pytest.raises(ProviderError, match="500"):
        provider_with(handler).chat([{"role": "user", "content": "x"}])


def test_mock_provider_replays_in_order_then_runs_out():
    mock = MockProvider([LLMResponse(content="one"), LLMResponse(content="two")])
    assert mock.chat([{"role": "user", "content": "a"}]).content == "one"
    assert mock.chat([{"role": "user", "content": "b"}]).content == "two"
    assert len(mock.calls) == 2
    with pytest.raises(ProviderError, match="ran out"):
        mock.chat([])


def test_make_provider_uses_spec_values():
    p = make_provider(ModelConfig(name="llama3.2:3b", num_ctx=4096, temperature=0.1))
    assert isinstance(p, OllamaProvider)
    assert (p.model, p.num_ctx, p.temperature) == ("llama3.2:3b", 4096, 0.1)


def test_make_provider_passes_the_think_setting():
    assert make_provider(ModelConfig(think=True)).think is True
    assert make_provider(ModelConfig()).think is False
