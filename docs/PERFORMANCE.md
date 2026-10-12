# Performance on a 16 GB MacBook Air M4

What makes AgentFactory fast or slow, measured with `scripts/bench.py` on this machine with qwen3:8b.
Raw results are in `docs/benchmarks/`.

## The three biggest wins are outside the app

| What | Measured effect | Trade-off |
|---|---|---|
| **Turn Low Power Mode off** (System Settings > Battery) | Writing 6 → 19.5 tok/s, reading prompts 65 → 158 tok/s: about **3x faster** | More battery drain. Plugging in also helps. |
| **Free memory** (close heavy apps: browsers with many tabs, VS Code, Docker) | With ~100 MB free and 3 GB swapped, qwen3:8b ran at 4 to 6 tok/s and loads took up to 12 s | None |
| **A small model for light agents** (`model: name: qwen3:4b-instruct`) | Chat agent 7.7 → 3.2 s per turn, task agent 9.6 → 5.2 s (Low Power Mode on) | It skipped reading a file once in the task benchmark. Keep qwen3:8b for agents with tools that must be used right (the German teacher). |

Check them:

```bash
pmset -g | grep lowpowermode            # 1 = on (slow), 0 = off
memory_pressure | tail -1               # "System-wide memory free percentage"
sysctl vm.swapusage                     # swap in use means the model is being paged
```

## Ollama settings

Ollama reads these when it starts. Your Homebrew service already sets the first two.

| Variable | What it does | Memory on 16 GB |
|---|---|---|
| `OLLAMA_FLASH_ATTENTION=1` | Faster attention that uses less memory; needed for a quantized KV cache. | Saves memory |
| `OLLAMA_KV_CACHE_TYPE=q8_0` | Stores the context cache in 8 bits instead of 16; quality loss is negligible. | Halves the cache: about 0.6 GB instead of 1.2 GB per 8k-token slot for qwen3:8b |
| `OLLAMA_NUM_PARALLEL=2` | Lets Ollama answer two requests at once. AgentFactory's `max_parallel` only helps up to this number. Measured: two chats at once took **44 s instead of 68 s** (1.54x), two task agents **63 s instead of 78 s** (1.25x). | One more context slot: the loaded model grew from 5.6 GB to 6.3 GB. 3 slots is about 6.9 GB and risks swapping with other apps open. |
| `OLLAMA_KEEP_ALIVE=30m` | How long a model stays loaded after the last request (default 5 minutes). AgentFactory also sends `keep_alive` from settings.yaml with every request. | The model's memory stays taken while loaded. `-1` keeps it forever. |
| `OLLAMA_MAX_LOADED_MODELS=1` | How many different models may be loaded at once. | On 16 GB keep 1 (the default picks by available memory). AgentFactory never mixes models in flight anyway: a different model waits instead of swapping. |

### Setting them for the Homebrew service

`brew services restart ollama` (and `brew upgrade`) rewrites the service file from the formula and drops your own
additions, so add the variable and reload with launchctl:

```bash
PL=~/Library/LaunchAgents/homebrew.mxcl.ollama.plist
cp "$PL" "$PL.backup"
/usr/libexec/PlistBuddy -c "Add :EnvironmentVariables:OLLAMA_NUM_PARALLEL string 2" "$PL"
launchctl bootout gui/$(id -u)/homebrew.mxcl.ollama; launchctl bootstrap gui/$(id -u) "$PL"
ps eww -p $(pgrep -f "ollama serve") | tr ' ' '\n' | grep OLLAMA_    # check
```

To undo: `cp "$PL.backup" "$PL"` and run the bootout/bootstrap line again. After a `brew upgrade ollama`, add the
variable again.

## A small model for light agents

```bash
ollama pull qwen3:4b-instruct     # 2.5 GB; already installed here. Alternative: ollama pull llama3.2 (3B, 2.0 GB)
```

Then in that agent's spec:

```yaml
model:
  name: qwen3:4b-instruct
```

Agents without `model.name` use `default_model` from `settings.yaml`. Note that two models cannot be in memory
together comfortably on 16 GB: when agents on different models are used at the same time, AgentFactory lets one
model finish before the other starts, so Ollama does not keep swapping them.

## What the app does

- **Streaming:** reply text appears as it is written. Chat agent: first text after 1.4 s instead of 8.2 s (Low Power Mode on).
- **Pre-warm:** the default model is loaded when the server starts and a new hire's model when it is hired.
  First message after a model unload: 12.4 s cold, 1.2 s warmed.
- **Prefill:** when a chat opens and a model slot is free, Ollama reads the agent's system prompt and tools ahead.
  German teacher, first turn: 12.5 s → 2.7 s (first text 11.0 s → 1.2 s).
- **One context size per model:** a request with another `num_ctx` makes Ollama reload the model (1.9 s seen),
  so prefill and warm-up use the agents' own `num_ctx`.
- **Parallel agents:** `max_parallel` in settings.yaml (default 2, at most 3, or `AGENTFACTORY_MAX_PARALLEL`).
  Agents beyond the limit wait in line and see their position. A warning appears when `num_ctx` × `max_parallel`
  passes 16,384 tokens.
- **Request options:** `keep_alive` from settings.yaml; a reply cap of 1,024 tokens for chat agents and 2,048 for task
  agents. The caps only stop runaway replies.
- **Early stop:** qwen3 sometimes writes 20 or more flashcards in one reply (minutes of writing). The reply is ended as
  soon as the 3rd new card arrives, because only 3 per reply are accepted.
- **Smaller prompts:** flashcard agents get only the last 8 lines of their notes when a chat starts, and the notes are
  no longer also in the system prompt. With 40 lines of notes, the German teacher's first request went from 3,378 to
  1,819 tokens (46% fewer). Long chats keep the last 6 turns word for word and fold older ones into a short summary
  (after 10 turns); the token meter in the chat header then says "summarized".
- **Stable prompt prefix:** the system prompt and the tool list stay byte-identical for the whole chat (the summary
  and the notes go after them), so Ollama's prompt cache can reuse them. A cached re-read took 0.6 s against 7.9 s cold.

Our own code (tools, files, serialization) takes 0 to 12 ms per turn; everything else is the model.

## Final before/after (Low Power Mode off, back to back)

Average per turn over 5 turns, qwen3:8b. "Before" is the old request path (`--legacy`: no streaming, no request
options, no prefill). Both runs started with the model loaded and prompts cached, so the cold-start wins above
(pre-warm, prefill) are not in these numbers.

| Agent | First text on screen | Whole turn | Writing speed |
|---|---|---|---|
| chat | 2.63 s → **0.70 s** | 2.63 s → 2.67 s | 19.4 → 18.5 tok/s |
| task (reads files) | 3.78 s → **2.57 s** | 3.78 s → 3.64 s | 19.8 → 19.2 tok/s |
| German teacher (tools) | 8.71 s → **5.91 s** | 8.71 s → 7.95 s | 18.3 → 17.8 tok/s |

Streaming makes replies appear sooner; it does not make the model finish sooner. The German teacher's total varies
by run (it wrote 104 tokens per turn before and 88 after), so its total is not a real difference.

## Running the benchmark

```bash
python scripts/bench.py                         # German teacher, a task agent and a chat agent, 5 turns each
python scripts/bench.py --legacy                # the old request path, for comparison
python scripts/bench.py --agents chat,task --model qwen3:4b-instruct
python scripts/bench.py --agents chat --parallel 2
```

Numbers vary between runs: qwen3 does not take the same path every time (more tool calls, longer replies), and memory
pressure and power mode change everything. Compare runs made back to back.
