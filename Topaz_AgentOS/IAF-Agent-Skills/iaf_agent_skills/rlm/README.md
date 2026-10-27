# RLM context mode — Phase 0-1 (analytical, read-only)

Keeps a large context **out of the model's window**: the context is offloaded to a per-session
store and queried on demand by a recursive, read-only RLM exposed as the **`context_query`** tool.
Additive and **opt-in** — with the flag off, agent behaviour is byte-for-byte unchanged.

- `engine.py` — read-only recursive RLM (`llm_query`/`rlm_query`/`FINAL`, restricted executor, caps).
- `context_store.py` — per-session offloaded-context store (LRU-bounded).
- `shadow.py` — Phase-0 comparison record builder + JSONL writer.
- Wiring in `agent.py`: `context_loading_mode == 'rlm'` branch, `context_query` tool,
  `_rlm_model_call`, `_rlm_mode_active`, `_rlm_shadow_maybe`.

---

## 1. Enable it on an agent

In the agent's `config.yaml`:
```yaml
context:
  context_loading_mode: rlm                 # opt-in (default is "table")
  context_file_path: <abs/path/to/Enterprise_Context.md>   # the doc to offload
  rlm:
    max_iters: 6         # root reasoning turns per context_query call
    max_depth: 2         # recursion depth (rlm_query sub-RLMs)
    max_leaf_calls: 30   # sub-LLM call budget per context_query call
tools:
  allowed: [shell, write_file, run_sql_query, query_memory, invoke_skill,
            invoke_plan, create_plan, context_query]   # context_query is in the default list too
```
Environment:
```bash
export RLM_ENABLED=true     # default true; set false to globally disable rlm mode
```

## 2. Validate live (runbook)

Prereqs: the cloned tree's venv installed and a model provider configured (Azure/OpenAI/local),
exactly as for a normal AgentOS run.

1. Point an agent at a **large** context file and set `context_loading_mode: rlm` (§1).
2. Start AgentOS (or use your usual chat/API path) and ask a question that requires the context,
   e.g. *"From the enterprise context, what is the approval threshold for high-value AP payments?"*
3. **Confirm the mechanism** in the server log:
   - `RLM mode: offloaded N chars (session=…)` — the context was offloaded, not inlined.
   - `Added context_query tool (RLM context handle)` — the tool is available.
   - a `context_query` tool call in the trajectory (the agent pulled context on demand).
4. **Confirm the answer** is correct and that the prompt stayed small (no giant context blob in the
   system prompt — check the `_sys_prompt_preview` log line / RL trajectory).

## 3. Phase-0 shadow mode (prove it before serving)

Shadow runs the RLM analytical path **in addition to** the normal turn and logs a comparison —
it does **not** change what is served. Turn it on WITHOUT switching the agent to rlm mode:
```bash
export RLM_SHADOW=true
# optional: export RLM_SHADOW_LOG=/abs/path/rlm_shadow.jsonl   (default: <agent_root>/rlm_shadow.jsonl)
```
Requirements: the agent must have `context.context_file_path` set (shadow reads it to offload).

Run normal turns as usual. Each turn appends a JSON line:
```json
{"ts":..., "session_id":"...", "query":"...", "normal_answer":"...", "rlm_answer":"...",
 "normal_len":..., "rlm_len":..., "overlap":0.78, "context_chars":523110,
 "rlm_root_iters":2, "rlm_leaf_calls":3, "rlm_elapsed_ms":1840}
```
Inspect it:
```bash
tail -f "<agent_root>/rlm_shadow.jsonl"
# quick agreement summary:
python3 -c "import json,sys; rows=[json.loads(l) for l in open('<path>')]; \
print('turns',len(rows),'mean_overlap',round(sum(r['overlap'] for r in rows)/len(rows),3))"
```
- **`overlap`** = word-set agreement between the served answer and the RLM answer (rough signal).
  High overlap on real turns = the RLM path is producing comparable answers → safe to promote to
  serving (flip the agent to `context_loading_mode: rlm`).
- **`context_chars` vs prompt size** = how much data stayed out of the window.

## 4. Offline tests (no model / network)
```bash
python3 tests/test_rlm_engine.py       # engine loop, recursion, budget, executor safety, store, shadow
```

## 5. Limitations / deferred (Phase 3)
- **Read-only.** `context_query` never takes actions. Side-effecting, code-action execution is the
  Phase-3 `rlm` execution_mode (propose-then-apply) — not this package.
- **Single-file offload.** v1 offloads `context_file_path`'s text; linked-file-graph offloading is a
  follow-up.
- **In-process restricted executor.** Trusted-internal posture; a real sandbox is Phase-3 scope.
- **Governance.** When the ReAct agent calls `context_query`, it passes through the normal
  Pre/PostToolUse hooks; the RLM's internal sub-LLM calls route through the light LLM +
  `model_call_context` (audit/RL/policy). No side effects are possible from this package.
