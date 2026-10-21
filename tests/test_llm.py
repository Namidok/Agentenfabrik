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


# ---------- streaming, Stop while writing, options ----------

from factory.llm import ProviderCancelled, is_loaded, warm  # noqa: E402


def ndjson(*chunks) -> httpx.Response:
    return httpx.Response(200, content="\n".join(json.dumps(c) for c in chunks).encode())


def test_streaming_hands_out_pieces_and_collects_tool_calls_and_timings():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return ndjson(
            {"message": {"content": "Hal"}},
            {"message": {"content": "lo"}},
            {"message": {"content": "", "tool_calls": [{"function": {"name": "srs_add", "arguments": {"front": "hello"}}}]}},
            {"message": {"content": ""}, "done": True, "done_reason": "stop", "prompt_eval_count": 40, "eval_count": 5,
             "load_duration": 2e8, "prompt_eval_duration": 1e8, "eval_duration": 5e8},
        )

    pieces = []
    r = provider_with(handler, keep_alive="30m", num_predict=300).chat([{"role": "user", "content": "hi"}], on_token=pieces.append)
    assert pieces == ["Hal", "lo"] and r.content == "Hallo"
    assert r.tool_calls[0].name == "srs_add" and r.tool_calls[0].arguments == {"front": "hello"}
    assert (r.prompt_tokens, r.completion_tokens, r.load_s, r.eval_s, r.done_reason) == (40, 5, 0.2, 0.5, "stop")
    assert r.first_token_s >= 0
    assert seen["stream"] is True and seen["keep_alive"] == "30m" and seen["options"]["num_predict"] == 300


def test_stop_while_streaming_ends_the_request():
    def handler(request):
        return ndjson(*[{"message": {"content": f"w{i} "}} for i in range(50)], {"done": True})

    pieces = []
    with pytest.raises(ProviderCancelled):
        provider_with(handler).chat([{"role": "user", "content": "hi"}], on_token=pieces.append,
                                    should_stop=lambda: len(pieces) >= 3)
    assert len(pieces) == 3


def test_streaming_errors_are_reported():
    with pytest.raises(ProviderError, match="ollama pull"):
        provider_with(lambda r: httpx.Response(404, text="nope"), model="tiny").chat([{"role": "user", "content": "x"}], on_token=print)
    with pytest.raises(ProviderError, match="out of memory"):
        provider_with(lambda r: ndjson({"error": "out of memory"})).chat([{"role": "user", "content": "x"}], on_token=print)


def test_no_options_are_sent_unless_set():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return reply({"content": "ok"})
    provider_with(handler).chat([{"role": "user", "content": "hi"}])
    assert "keep_alive" not in seen and "num_predict" not in seen["options"] and seen["stream"] is False


def test_loaded_means_the_same_name_and_context_size():
    cfg = ModelConfig(name="qwen3:8b", num_ctx=8192)
    assert is_loaded(cfg, {"qwen3:8b": 8192}) is True
    assert is_loaded(cfg, {"qwen3:8b": 4096}) is False  # another context size means a reload
    assert is_loaded(cfg, {}) is False and is_loaded(cfg, None) is None
    assert is_loaded(ModelConfig(name="llama3.2", num_ctx=4096), {"llama3.2:latest": 4096}) is True


def test_warming_loads_the_model_with_the_agents_context_size():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"done": True})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert warm(ModelConfig(name="qwen3:8b", num_ctx=8192), "30m", client=client) is True
    assert seen == {"model": "qwen3:8b", "prompt": "", "stream": False, "options": {"num_ctx": 8192}, "keep_alive": "30m"}


def test_prefill_reads_the_prompt_and_writes_one_token():
    from factory.llm import prefill
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return reply({"content": "x"})
    p = provider_with(handler, num_predict=768)
    tools = [{"type": "function", "function": {"name": "srs_due", "parameters": {"type": "object", "properties": {}}}}]
    assert prefill(p, [{"role": "system", "content": "You teach German."}], tools) is True
    assert seen["options"]["num_predict"] == 1 and seen["tools"] == tools and seen["messages"][0]["content"] == "You teach German."
    assert p.num_predict == 768  # untouched for the real requests
    assert prefill(MockProvider([]), [], None) is False  # only for Ollama


def test_a_message_sent_during_prefill_keeps_its_reply_cap():
    """The first message of a chat can run while the prefill is still going (2 slots): it must not get 1 token."""
    from factory.llm import prefill
    caps = []

    def handler(request):
        body = json.loads(request.content)
        caps.append(body["options"]["num_predict"])
        if body["messages"][-1]["content"] == ".":  # the prefill: the user's message arrives meanwhile
            p.chat([{"role": "user", "content": "Which step are we on?"}])
        return reply({"content": "x"})
    p = provider_with(handler, num_predict=1024)
    assert prefill(p, [{"role": "system", "content": "You are Job Desk."}], None) is True
    assert caps == [1, 1024]


# ---------- tools as text (Ollama's own tool parsing cuts some calls off) ----------

from factory.llm import ToolCall  # noqa: E402

TOOLS = [{"type": "function", "function": {"name": "script_run", "parameters": {"type": "object", "properties": {"script": {"type": "string"}}}}}]
CALL = '<tool_call>\n{"name": "script_run", "arguments": {"script": "run_now", "args": {}}}\n</tool_call>'


def test_tools_as_text_go_into_the_system_prompt_and_calls_come_back_from_the_text():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return reply({"content": CALL})
    p = provider_with(handler, tools_as_text=True)
    r = p.chat([{"role": "system", "content": "You are Job Desk."}, {"role": "user", "content": "search for jobs"}], tools=TOOLS)
    assert "tools" not in seen
    system = seen["messages"][0]["content"]
    assert system.startswith("You are Job Desk.\n\n# Tools") and '"name": "script_run"' in system and "<tool_call>" in system
    assert r.content == "" and r.tool_calls == [ToolCall("script_run", {"script": "run_now", "args": {}})]


def test_tools_as_text_without_a_system_message_and_with_plain_replies():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return reply({"content": "Hello, I run your job search."})
    r = provider_with(handler, tools_as_text=True).chat([{"role": "user", "content": "hi"}], tools=TOOLS)
    assert seen["messages"][0]["role"] == "system" and seen["messages"][0]["content"].startswith("# Tools")
    assert r.content == "Hello, I run your job search." and r.tool_calls == []


def test_calls_from_text_reads_several_calls_and_an_unfinished_one():
    from factory.llm import calls_from_text
    text = ('Starting.\n<tool_call>\n{"name": "a", "arguments": {"x": 1}}\n{"name": "b", "arguments": "{\\"y\\": 2}"}\n</tool_call>'
            '<tool_call>\n{"name": "c", "arguments": {}}')
    content, calls = calls_from_text(text)
    assert content == "Starting." and [(c.name, c.arguments) for c in calls] == [("a", {"x": 1}), ("b", {"y": 2}), ("c", {})]
    assert calls_from_text("<tool_call>\nnot json\n</tool_call>") == ("", [])


def test_streamed_tool_call_text_is_never_shown_and_the_call_is_found():
    pieces = ["I will ", "start it.", "\n<tool", "_call>\n{\"name\": \"script_run\", ", "\"arguments\": {\"script\": \"run_now\"}}\n</tool_call>"]

    def handler(request):
        lines = [json.dumps({"message": {"content": x}, "done": False}) for x in pieces]
        lines.append(json.dumps({"message": {"content": ""}, "done": True, "done_reason": "stop"}))
        return httpx.Response(200, text="\n".join(lines))
    shown, seen_calls = [], []
    r = provider_with(handler, tools_as_text=True).chat([{"role": "user", "content": "go"}], tools=TOOLS,
                                                       on_token=shown.append, on_call=seen_calls.append)
    assert "".join(shown) == "I will start it.\n" and "<" not in "".join(shown)
    assert r.content == "I will start it." and [c.name for c in r.tool_calls] == ["script_run"] == [c.name for c in seen_calls]


def test_a_streamed_reply_that_only_looks_like_a_tool_call_is_shown_in_full():
    def handler(request):
        lines = [json.dumps({"message": {"content": x}, "done": False}) for x in ("Use a <t", "able> tag")]
        lines.append(json.dumps({"message": {"content": ""}, "done": True}))
        return httpx.Response(200, text="\n".join(lines))
    shown = []
    r = provider_with(handler, tools_as_text=True).chat([{"role": "user", "content": "go"}], tools=TOOLS, on_token=shown.append)
    assert "".join(shown) == "Use a <table> tag" == r.content


def test_on_call_can_end_a_text_tool_reply_early():
    pieces = ['<tool_call>\n{"name": "a", "arguments": {}}\n</tool_call>', '<tool_call>\n{"name": "b", "arguments": {}}\n</tool_call>']

    def handler(request):
        return httpx.Response(200, text="\n".join(json.dumps({"message": {"content": x}, "done": False}) for x in pieces))
    r = provider_with(handler, tools_as_text=True).chat([{"role": "user", "content": "go"}], tools=TOOLS, on_call=lambda c: False)
    assert [c.name for c in r.tool_calls] == ["a"] and r.done_reason == "early"


def test_make_provider_uses_tools_as_text():
    from factory.llm import make_provider
    assert make_provider(ModelConfig(name="qwen3:8b")).tools_as_text is True
