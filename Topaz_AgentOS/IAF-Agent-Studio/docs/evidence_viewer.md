# Enterprise Evidence Viewer

The Enterprise Evidence Viewer is the normalized audit layer for documents and artifacts read during agent execution. Chat, REST API, cron, and queue runs can all produce the same evidence bundle shape.

## Core Model

Each captured read becomes an `evidence_item`.

```json
{
  "evidence_id": "uuid-generated-per-read",
  "source_uri": "/shared/invoices/ACC-0031.pdf",
  "source_fingerprint": "sha256(source_uri)",
  "content_hash": "sha256(content seen by agent)",
  "capture_seq": 1,
  "source_type": "local",
  "artifact_type": "pdf|text|table|json|image|memory|binary",
  "content_strategy": "resolve_on_demand|stored_payload|not_available",
  "content_url": "/api/evidence/{trace_id}/items/{evidence_id}/content",
  "text_url": "/api/evidence/{trace_id}/items/{evidence_id}/text"
}
```

`evidence_id` is a UUID generated at capture time. It is not derived from the source URI, because the same URI can return different content across API, DB, email, or repeated file reads.

## Content Strategy

| Strategy | Used For | Behavior |
|---|---|---|
| `resolve_on_demand` | Local files and durable stores such as SharePoint/S3/Azure Blob | Store metadata and extracted text; stream original bytes later through a source resolver |
| `stored_payload` | Ephemeral API responses, DB rows, email bodies | Store payload bytes at capture time so the evidence remains reproducible |
| `not_available` | Redacted or intentionally unavailable sources | Store provenance and extracted metadata only |

`LocalSource` resolves SafeKernel-style paths such as `/shared/...`, `/local/...`, and `/me/...`. `/local/...` checks the user's configured mount first, then the tenant default mount, and uses the first candidate that contains the requested evidence path.

`shared/document_source.py` also registers source-provider extension classes for `SharePointSource`, `AzureBlobSource`, `S3Source`, and `URLSource`. They are deliberately explicit stubs: the evidence API can route `sharepoint://...`, `azblob://...`, `s3://...`, and `https://...` evidence items today, but each provider raises `501` until a deployment supplies tenant-specific credentials and download logic. A provider may return either:

- `DocumentContent(path=...)` for tenant-scoped local files.
- `DocumentContent(payload=...)` for remote bytes downloaded from SharePoint, Azure Blob, S3, or HTTP(S).

The evidence content endpoint streams either shape, so new sources do not require chat UI changes.

Document/image previews that use `/api/files/serve` receive a short-lived HMAC
URL when `FILE_URL_SIGNING_SECRET` is configured. Its signature binds tenant,
agent, user, virtual path, and expiry; changing any field or using an expired
link returns 401. Enterprise strict mode disables unsigned file URLs.

## Storage

Evidence is persisted to:

```text
enterprise_root/tenants/{tenant_id}/shared/databases/evidence.db
```

Persistence goes through `EvidenceCollectorAdapter`, which now routes storage and reads through the audit/evidence sink fanout. The local SQLite sink remains mandatory and authoritative for retrieval. Optional JSONL mirror sinks emit bounded, redacted summaries for enterprise log forwarders; they do not store full payload blobs and mirror failures do not block local evidence persistence.

Tables:

- `evidence_bundles` stores one row per trace and the API-safe bundle JSON.
- `evidence_items` stores normalized item metadata.
- `evidence_blobs` stores payload bytes for `stored_payload` items.

## APIs

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/evidence` | Store an evidence bundle |
| `GET` | `/api/evidence/{trace_id}` | Retrieve a full bundle |
| `GET` | `/api/evidence/{trace_id}/items/{evidence_id}` | Retrieve one item |
| `GET` | `/api/evidence/{trace_id}/items/{evidence_id}/text` | Retrieve text seen by the agent |
| `GET` | `/api/evidence/{trace_id}/items/{evidence_id}/content` | Stream stored payload bytes, local files, or bytes returned by a configured source provider |

## Execution Paths

`SkillAgent` captures evidence at the tool boundary before downstream truncation. React tool calls pass through the shared structured tool-governance firewall before execution; the default LangGraph runtime and optional native React runtime both call this same boundary. Native React runtime also records `run_sql_query` result payloads as SQL evidence items at the tool-result boundary. Deterministic workflow/parallel tool steps also flow through the collector. The current collector detects tenant context/business file reads from shell tools, records SQL results as ephemeral table evidence, filters true infrastructure files such as `SKILL.md`, taxonomy, memory, logs, and config files, and emits both:

- `evidence_items`: normalized framework schema.
- `documents`: backward-compatible source-card schema for the current chat UI.

When entitlements are enabled, the same request-bound principal used for chat execution is evaluated before a skill, tool, or file-mode context path is exposed to the agent. Denied context files are not injected into the prompt, so the Evidence Viewer only records artifacts reached through permitted execution. External access governance extends this request context into SafeKernel; credentials remain masked, governed DB access is checked before SQL evidence is produced, and external access decisions are recorded in the security audit stream rather than as visible evidence payloads.

REST `/api/chat` and WebSocket `/ws/chat` include `source_documents`, `evidence_trace_id`, and an immediate `reasoning_context.reasoning_summary` in their response payloads, then persist the bundle through `EvidenceCollectorAdapter` and the selected evidence sinks. Conversation replay keeps evidence per turn: hot in-memory session switches retain the live bundle, while cold conversation reloads use the turn `trace_id`/`evidence_trace_id` to rehydrate the persisted bundle through the same adapter boundary.

Post-response memory writes remain separate from evidence capture. `MemoryCapability` can route staged memory write call sites through the same underlying `AgentMemory` JSONL/SQLite paths when `IAF_MEMORY_CAPABILITY_ENABLED=true`, but it does not create evidence items or change evidence bundle persistence.

Cron, queue, and mission jobs set `execution_source` to `cron`, `queue`, or `mission` and persist the bundle without requiring a browser. Cron jobs that use the `queue_ingest` skill are bridged internally into a real queued Command Center item rather than relying on an agent-generated shell/curl call; the queued item then owns the trace, action steps, and any downstream evidence bundle. Queue-ingest dedup only reuses active queue items; if the dedup key points at a terminal `done`/`dlq` item, a fresh queue item is created for the new cron fire so operators do not see a completed historical item as the current run. Because the real queued item is already visible, `queue_ingest` cron jobs skip the separate `[CRON] ...` done-stage audit row that normal non-queue cron jobs post to Queue Monitor. Queue executions also store `evidence_trace_id` and `evidence_count` in `job_executions`; the queue completion lifecycle hook receives the same trace/count metadata for audit correlation. Queue HITL exact replays persist shell/curl HTTP responses as `api` evidence items, so post-approval tool results remain visible even when the resumed action is an API call rather than a document read.

Dashboard V2 Queue Monitor uses this queue metadata to show a `Traceability & evidence` panel on expanded items. It first resolves the execution `evidence_trace_id`, then falls back to the queue item `trace_id`, and fetches `/api/evidence/{trace_id}` just like Workstream Detail. When artifact evidence exists, the panel shows source URI, source type, content strategy/hash, and provenance fields such as tool and input. When no artifact bundle exists for the trace, the panel still exposes the recorded queue action trail from `job_steps` so operators can distinguish action traceability from captured source artifacts.

Telemetry provider fanout remains separate from evidence capture. `TraceEmitter` and `TwinEmitter` keep their local SQLite stores as the durable default and may mirror bounded redacted copies to external observability providers, but those mirrors do not create evidence items or change evidence trace IDs. Audit/evidence mirrors are a separate compliance/log-forwarding path: they emit bounded summaries and health counters, while local `evidence.db` remains the source for evidence APIs.

## Chat UI Viewer

The chat UI renders `source_documents.evidence_items` as a generic Evidence panel below assistant messages. If a legacy response only has `source_documents.documents`, the UI normalizes those documents into item-like objects so older responses still render. Evidence is still scoped to the turn that captured it; follow-up turns do not inherit prior evidence unless they read/capture evidence again. The collapsible Reasoning panel seeds its `Why` row from `reasoning_summary` immediately, then may replace that text when `/api/reasoning/{trace_id}` later returns deeper episode reasoning.

The chat header links to AgentPro Studio (`/studio`) for broader skill lifecycle work such as browsing skills, scheduling runs, and attaching knowledge. The business-polished chat shell keeps the existing layout, with a refined executive header, an empty-state executive briefing panel, and an `Execution Trace` side panel label for routing, tools, checks, and timing. The Evidence panel remains scoped to chat messages and persisted evidence bundles.

The panel groups repeated reads by `source_fingerprint` or `source_uri`, so the user sees one chip per source while the Provenance tab still shows every read attempt. When a large document extraction is truncated and the full output is saved to `/workspace/tmp/iaf_result_*.txt`, later reads of that temp extraction are linked back to the original source through `metadata.derived_from_source_uri` and grouped under the same chip. The active key is the grouped source key, with `evidence_id` preserved for individual read records.

- `Text Seen`: shows `extracted_text.excerpt`; if the excerpt is missing and `text_url` exists, the UI lazily fetches it. Highlight rendering uses `char_start`/`char_end` offsets first, then falls back to exact term matching only when offsets do not line up with the displayed text. For large Office/PDF conversions, the evidence collector strips the tool truncation wrapper and keeps the preview text as the source excerpt while recording the saved temp path in provenance. Failed tool output, including generic `Error:` responses, binary `cat` failures, and raw PDF object/font dumps, is not shown as text; the panel points users to Provenance instead.
- `Rendered`: best-effort renderer for PDF, Office-style documents, text, JSON, and table-like artifacts. PDF items fetch the protected `content_url` once as a blob and render it in a native inline PDF frame by default. A separate on-demand `Highlight View` loads PDF.js against the same blob, renders the selected page with PDF.js, overlays deterministic evidence matches, and progressively scans the remaining pages in small batches. DOC/DOCX/PPT-style document items render the converted text/Markdown excerpt in a document-like preview with the same offset-aware evidence highlights used by `Text Seen`, plus match chips that jump to highlighted text. Table parsing falls back to text silently when the content is ambiguous.
- `Provenance`: shows source URI, source type, artifact type, content strategy, hashes/fingerprints, and generic tool provenance (`tool` + `input`). Shell evidence labels the input as `Command`.
- `Original`: opens `content_url` for on-demand files or stored payloads through authenticated `fetch()` and a temporary browser blob URL, so protected evidence endpoints do not require a raw token in the link.

Highlight terms are generated deterministically from optional `SKILL.md` `evidence_highlights` rules, the user query, explicit tool search terms, the agent response, and the evidence text; no extra LLM call is made by default. Skill-configured terms and regex patterns are applied first when present, followed by query/search terms, quoted/backticked terms, numeric amounts, business reference codes, mixed alphanumeric tokens, camel-case product names, and multi-word proper names. Single title-case nouns from the agent response are intentionally ignored unless they came from the query/search/quote/code paths, which avoids noisy highlighting of ordinary nouns. Candidates are filtered through stopwords, length checks, document-frequency checks, and a per-item cap. Invalid skill regex patterns are ignored with a warning rather than failing the run. `llm_suggestions` is reserved as an opt-in placeholder and currently makes no LLM call. When a large extraction writes full text to `/workspace/tmp/iaf_result_*.txt`, highlights found in that derived extraction text are also copied back to the original source item so the visible document chip carries the evidence match.

For PDFs, `Text Seen` remains the audit text the agent used, while `Rendered` opens with the original PDF inline using the browser's native PDF viewer. `Highlight View` is opt-in so complex or scanned PDFs still have the stable native preview as the default/fallback. When enabled, PDF.js renders one page at a time inside a dedicated scrollable canvas area, the UI builds a lightweight invisible text layer from `getTextContent()`, groups match data by page number for cheap page rendering, and updates match chips as background page scans complete. PDF.js runtime objects are kept in a non-reactive browser cache keyed by evidence item/content URL so framework reactivity does not proxy PDF.js private-field classes and repeated follow-up reads of the same source do not collide with older preview panels. The scanner works across adjacent PDF text runs and tolerates common split forms such as `$106` versus `$ 106` and `FY27` versus `FY 27`. PDF blob URLs and PDF.js documents are cleaned up when the chat switches conversations, starts a new conversation, or switches agents. `Original` remains the fallback for opening the full PDF in a new tab.

For Office-style documents, `Rendered` is a converted preview, not a native Word/PowerPoint renderer. The preview uses the extracted text captured from MarkItDown or another shell conversion and applies highlight offsets to that converted text. This gives users a readable verification surface today and gives the framework a stable text-coordinate layer for future page/section anchoring. Precise native "jump to page and highlight text" for Office/PPT/spreadsheet formats still requires a converter-provided location map, such as slide number, sheet/row/column, or heading/paragraph anchors. Image and binary items show metadata/provenance plus original-content access when available. Annotations and side-by-side compare remain later phases.

Agent-side PDF text extraction uses SafeKernel `python3`. On macOS, the prompt steers PDF reads through Quartz/PDFKit when available. For portable Office/PDF conversion, the Studio file parsing dependencies in `IAF-Agent-Studio/requirements.txt` (`markitdown`, `pdfminer.six`, `pdfplumber`) provide a MarkItDown fallback when installed in the system Python runtime. If extraction fails, `Text Seen` correctly reports the failure while `Rendered` and `Original` still provide visual verification.
