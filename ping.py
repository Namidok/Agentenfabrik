"""Quick live check: plain chat, structured output, tool calling."""
import json

from factory.llm import OllamaProvider, ProviderError

p = OllamaProvider()  # qwen3:8b on localhost

try:
    print("1) Plain chat")
    r = p.chat([{"role": "user", "content": "Say hi in one short sentence."}])
    print("  ", r.content, f"[{r.prompt_tokens} in / {r.completion_tokens} out]")

    print("2) Structured output")
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
        "required": ["name", "age"],
    }
    r = p.chat(
        [{"role": "user", "content": "Invent a fictional person."}], schema=schema
    )
    print("  ", json.loads(r.content))

    print("3) Tool calling")
    tools = [{
        "type": "function",
        "function": {
            "name": "fs_list",
            "description": "List files in a folder",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }]
    r = p.chat(
        [{"role": "user", "content": "What files are in ./sandbox? Use the tool."}],
        tools=tools,
    )
    print("  ", r.tool_calls or f"NO TOOL CALL, model said: {r.content}")
except ProviderError as e:
    print("ERROR:", e)
