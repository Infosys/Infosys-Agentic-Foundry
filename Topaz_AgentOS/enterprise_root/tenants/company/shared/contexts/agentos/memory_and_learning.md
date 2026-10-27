# Memory + Learning

AgentOS keeps three kinds of memory and a learning loop that grows
knowledge over time.

## The three layers

| Layer | What | Where |
|---|---|---|
| **Episodic** | Full conversation transcripts, JSONL append-only | `enterprise_root/.../memory/sessions/*.jsonl` |
| **Knowledge** | Extracted facts, indexed (SQLite FTS5) | `enterprise_root/.../memory/knowledge_index.db` |
| **Session** | Short-term state (current turn, scratch) | Redis |

## How a request reads memory

1. `query_memory` tool (or auto-recall) hits the knowledge index for
   facts relevant to the query.
2. The episodic JSONL provides last-N turns of conversation history.
3. Redis provides per-session ephemeral state (entity bindings, flags).

## Learning loop — how knowledge grows

After each session:

1. `post_turn` / session-end hook fires.
2. The knowledge extractor scans the conversation for **user-confirmed
   facts** (e.g., "yes, ACME's account number is 12345").
3. Extracted facts are written to `knowledge_index.db` with provenance:
   trace_id, user_id, timestamp, source turn.
4. Next session, those facts surface via `query_memory` automatically.

## Light mode

`light_mode: true` in user settings skips heavy learning extraction for
follow-up turns (saves tokens + latency). The episodic JSONL is still
written so history isn't lost — that fix was made in the recent
`light_mode silently dropping history` patch.

## Privacy and isolation

- Memory is **per-tenant** (tenant root isolates everything).
- A user's recall is scoped to their `user_id` + tenant.
- The entitlement layer can further restrict `query_memory` per role.

Read more: IAF-Agent-Skills/docs/memory_schema.md
