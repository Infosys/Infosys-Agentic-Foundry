# File Mode Regression Runner

The file-mode regression runner verifies the P0/P1 features described in `docs/KEY_FEATURES.md` without touching the checked-in tenant data.

## Location

```bash
IAF-Agent-Studio/tests/run_file_mode_regression.py
```

## Profiles

```bash
cd IAF-Agent-Studio
python3 tests/run_file_mode_regression.py --profile fast
python3 tests/run_file_mode_regression.py --profile full --no-prompt
python3 tests/run_file_mode_regression.py --profile real-llm --no-prompt
```

- `fast` creates a temporary file-mode tenant and runs deterministic checks without starting the server.
- `full` also starts a temporary server on a free port, starts a fake OpenAI-compatible chat endpoint, runs REST/WebSocket/queue/cron/telemetry checks, and verifies files and SQLite artifacts.
- `real-llm` starts a temporary server on a free port using the configured real LLM provider and verifies that a dedicated smoke skill returns `REAL_LLM_SMOKE_OK`.

The runner is non-interactive. If a dependency is missing, it fails or skips the dependent check with a clear reason.

## Isolation

Each run creates a temporary `enterprise_root` with:

- `context_loading_mode: file`
- `/shared/Enterprise_Context.md`
- linked `/shared/contexts/*.md` files
- entity notes
- a tiny SQLite business database
- probe skills for `react`, `workflow`, `parallel`, and `supervisor`
- hook scripts that write marker events

The full profile uses a fake OpenAI-compatible server so regular regression does not require a real LLM. Azure embedding credentials are unset in the child server process so knowledge search falls back to deterministic FTS5 behavior.

The `real-llm` profile does not override `OPENAI_BASE_URL`, `OPENAI_MODEL_NAME`, `LLM_PRIMARY_*`, or Azure OpenAI settings. It reads the same environment/config files as the server and skips cleanly if no real LLM configuration is present.

The full regression sets `CC_QUEUE_DB_PATH` so the Command Center queue writes to the temporary run folder instead of `IAF-Agent-Studio/command_center.db`.

## Coverage

P0 coverage:

- File-mode context block and `/shared/Enterprise_Context.md`
- SafeKernel read/write/audit behavior, including `python3` heredoc execution
- `/api/chat`
- `/ws/chat` when the `websockets` package is available
- Command Center queue item lifecycle
- Enterprise Evidence bundle persistence, conversation reload rehydration, local content/text retrieval, tenant `/local` mount resolution for evidence originals, and remote source provider routing stubs for SharePoint/Azure Blob/S3/URL integrations
- Legacy `documents`-only evidence bundles normalize into `evidence_items` with item URLs
- Failed evidence read attempts, including binary `cat` errors and raw PDF object/font dumps, are marked in provenance and do not display tool errors as `Text Seen`
- Large document extraction truncation is parsed so the original document keeps a clean `Text Seen` preview, and `/workspace/tmp/iaf_result_*.txt` extraction reads are linked back to the source document
- Office document evidence is classified as a `document` artifact so the chat UI can render a converted preview rather than falling back to binary metadata
- Deterministic evidence highlighting captures proper nouns/business tokens such as `Topaz` from derived extraction reads and propagates those highlight terms back to the source document item
- SKILL.md `evidence_highlights` frontmatter is parsed and applied to evidence text through configured terms and regex patterns
- Highlight filtering avoids incidental single title-case nouns from response prose unless they came from the query, an explicit search term, quotes, or code-like patterns
- Chat UI highlight rendering uses exact character offsets first, with term fallback only when offsets do not match the displayed text
- Cron creation/manual trigger when Redis is reachable via `REDIS_URL`
- Authenticated cron create/trigger/run-history flow using a Bearer token
- Memory history, knowledge index, learning artifacts
- Trace and Twin database creation

P1 coverage:

- Router keyword fallback and routing detail shape
- Execution mode parsing for `react`, `workflow`, `parallel`, and `supervisor`
- Hook execution markers
- REST and WebSocket evidence traces, queue evidence metadata, and `/api/evidence` retrieval
- Auth-disabled and auth-enabled missing-JWT behavior
- Tenant isolation smoke check
- FinOps and Twin endpoint non-error checks

Real LLM smoke coverage (13 scenarios + artifact checks):

| Scenario | What is verified |
|---|---|
| S1 — Marker probe | LLM endpoint reachable, no fake-model leakage, `REAL_LLM_SMOKE_OK` returned |
| S2 — Context read-through | `REGRESSION_POLICY_ALPHA` from `regression_context.md` appears in response — proves context injection |
| S3 — Entity notes injection | `REGRESSION_ENTITY_BETA` from `CUST_REGRESSION.md` appears — proves entity file wiring |
| S4 — SQL tool invocation | `REGRESSION_DB_GAMMA` from SQLite appears — proves real `run_sql_query` tool call |
| S5 — Workflow all-steps | All 4 workflow steps execute and all 4 markers appear in response |
| S6 — Taxonomy routing | Semantic query routes to `regression_workflow` via `TaxonomySignalIndex` cosine scoring |
| S7 — Multi-turn memory | Reference code set in turn 1 is recalled in turn 2 of the same session |
| S8 — Parallel execution | Both `REGRESSION_PARALLEL_ALPHA` and `REGRESSION_PARALLEL_BETA` branches complete |
| S9 — Supervisor delegation | Supervisor skill invokes worker and surfaces workflow output |
| S10 — Knowledge confirm + file append | Two facts taught via `/api/learn`; one confirmed with `target_file` → marker physically appended to `regression_context.md`; other rejected → absent from confirmed list |
| S11 — Knowledge edit | Confirmed record edited to new summary marker; edit persists in API list and is appended to context file |
| S12 — query_memory recall | Agent asked to call `query_memory` explicitly — confirmed marker returned; rejected marker absent |
| S13 — Context-file reflects append | Fresh agent reads `regression_context.md` via shell — confirmed-append marker present; rejected marker absent |

Artifact checks (23 checks, run after all scenarios):

- Memory JSONL history files created with `trace_id` and `outcome` fields
- `knowledge_index.db` — `episode_vectors` table has rows; `taxonomy_signal_index` table has indexed nodes
- `traces.db` — `traces` and `spans` tables have rows; at least one `status=success` trace
- `twin_telemetry.db` — `task_events` and `skill_usage` tables have rows
- Audit log (`commands_*.jsonl`) written with `command` field entries
- Hook log has `PreStep`, `PostStep`, `PreToolUse`, `PostToolUse` events from real execution
- Knowledge JSONL files (`memory/knowledge/*.jsonl`) contain both `confirmed` and `archived` status records
- Knowledge API confirmed list contains the confirmed fact and excludes the rejected fact

P2 features such as Doc-to-Skill, Skill Builder UI save/export, self-evolution, credential backend matrix, MCP matrix, `/local` deep checks, OS-level Python sandbox behavior, and real provider fallback matrices are intentionally left for later specialized suites.

## Automation

For unattended runs, use:

```bash
cd IAF-Agent-Studio
python3 tests/run_file_mode_regression.py --profile full --no-prompt
```

The command returns exit code `0` on success and non-zero on failure. On failure, the temporary run folder is preserved and printed so logs, generated tenant files, and SQLite databases can be inspected.
