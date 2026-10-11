# Performance work: where it stands (paused 2026-10-11)

Task: faster agent replies and agents running in parallel (items 0-6 of the performance brief).
Nothing is committed. All tests pass: `python -m pytest -q` gives 342 passed, 2 skipped (the opt-in live tests).

## Done

- **0. Benchmark:** `scripts/bench.py` runs a fixed 5-turn chat with the German teacher, a file task agent and a
  plain chat agent, in temporary folders. Results so far are in `docs/benchmarks/`.
- **2. Request options:** `keep_alive` from settings.yaml (30m) on every request; reply caps per mode
  (`factory/settings.py` NUM_PREDICT: chat 768, task 2048); pre-warm of the default model at server start and of a
  new hire's model (`warm_up` in server.py); a separate `loading` event when the model is not in memory with the
  right context size (`is_loaded`, `loaded_models` in llm.py).
- **3. Streaming:** `OllamaProvider.chat(on_token, should_stop, on_call)`; the runtime sends `delta` events (kept out
  of the trace), Stop works while the model is writing, and partial replies are never saved. UI: a live reply
  bubble with tool chips as they happen (app.js `liveReply`).
- **4. Concurrency:** `factory/scheduler.py` (a FIFO line, max_parallel slots, one model setup at a time, positions,
  Stop while waiting leaves the line, a failure always frees its slot). `max_parallel` defaults to 2; the env var
  AGENTFACTORY_MAX_PARALLEL overrides it; above 3 is refused; there is a memory warning when num_ctx x parallel > 16384.
  The UI shows queue positions and the reason for waiting.
- **1. Smaller prompts, partly done:** history folding (keep the last 6 turns, fold older ones into a summary after
  10; `_fold_history` in runtime.py; the meter shows "summarized"); flashcard agents get only the last 8 lines of
  their notes at chat start and no notes in the system prompt (so it stays byte-stable).
- **Early stop (extra):** the model is stopped after the 3rd new card in a reply (`on_call`), because qwen3
  sometimes writes 20+ card calls (about 2 minutes at 6 tok/s).
- **5. Per-agent model** was already in place from the previous round (model chip, staff file, missing-model warning).

## Measured so far (this Mac was short on memory: ~100 MB free, ~3 GB swap, so every model is slow)

| agent | before: visible / total | after streaming: visible / total | qwen3:4b-instruct: visible / total |
|---|---|---|---|
| chat | 8.2 s / 8.2 s | 1.4 s / 7.7 s | 0.7 s / 3.2 s |
| task | 12.2 s / 12.2 s | 6.6 s / 9.6 s | 3.5 s / 5.2 s |
| german | 17.7 s / 17.7 s | 29.8 s / 36.8 s | (stays on 8B) |

- German total varies 17.7 to 36.8 s between runs of the same code (qwen3 takes a different path each run, and the
  Mac swaps), so no claim can be made about it from single runs.
- Pre-warm: the first message after a model unload took 12.4 s cold (2.9 s when the files were still cached);
  pre-warmed, 1.2 to 1.4 s.
- Writing speed: qwen3:8b about 6 tok/s here (memory-bound), qwen3:4b-instruct 12 to 13 tok/s. Our own overhead per
  turn is 0 to 12 ms.
- Prompt cache: Ollama 0.32 reuses it (0.6 s against 7.9 s for a cold re-read) but reports the full token count.
- The 4B model skipped reading a file once ("Summarize notes.txt"); fine for plain chat agents, keep 8B for tool-heavy ones.
- Changing num_ctx between requests to the same model forces a reload (1.9 s seen).

## Still to do

1. Measure the notes-trimming saving in tokens (40-line notes; the script was about to run).
2. Decide on trimming the German system prompt (1147 tokens) and the tool schemas (434): cached after the first call,
   so they only cost time on a cold start or an agent switch. Measure before keeping anything.
3. Reconsider the chat reply cap (768): it only stops runaways, and early stop now covers the card dumps.
4. Live check: `AGENTFACTORY_LIVE=1 python -m pytest -q tests/test_german_teacher.py -k live -s`.
5. Parallel gain needs Ollama restarted with OLLAMA_NUM_PARALLEL=2. Right now the running `ollama serve` has
   OLLAMA_FLASH_ATTENTION=1 and OLLAMA_KV_CACHE_TYPE=q8_0, but its llama-server runs with `-np 1`. Ask before restarting it.
6. Final full benchmark (`python scripts/bench.py --label after --json docs/benchmarks/4-after.json`) and the
   before/after table.
7. Write docs/PERFORMANCE.md: env vars (OLLAMA_NUM_PARALLEL, OLLAMA_FLASH_ATTENTION, OLLAMA_KV_CACHE_TYPE,
   OLLAMA_KEEP_ALIVE, OLLAMA_MAX_LOADED_MODELS), the 16 GB trade-offs, the one-liner to pull a small model, the commands
   to restart Ollama, and the biggest win: free RAM (close heavy apps).
8. Final report: changelog, test count, what was left out and why. UI changes beyond items 4 and 5 (streaming
   bubble, loading state, "summarized" marker) must be called out.

## Files changed in this round

factory/llm.py, factory/runtime.py, factory/server.py, factory/settings.py, factory/study.py, factory/scheduler.py (new),
scripts/bench.py (new), settings.yaml, static/app.js, static/style.css, tests/test_llm.py, tests/test_runtime.py,
tests/test_server.py, tests/test_settings.py, tests/test_scheduler.py (new), tests/test_german_teacher.py,
tests/test_hire.py, tests/test_remove.py, tests/test_staff.py, docs/benchmarks/ (new).
