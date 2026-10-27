# Taxonomy Signal Index — Authoring Guide

> **Audience:** Platform administrators and domain experts who create or maintain taxonomy files and the `Enterprise_Context.md` file. No Python required — all authoring is plain markdown.

---

## What Is the Taxonomy Signal Index?

When a user sends a query, the agent needs to decide which **skill** handles it (e.g. `fa_ap`, `ccdops`, `fa_gl`). It does this through three signals that fire before the LLM router:

| Signal | Source | What it answers |
|---|---|---|
| Entity signal | `_index.yaml` entity registry | **WHO** — which customer/vendor/system is involved? |
| Taxonomy signal | Taxonomy markdown files | **WHAT** — which business process is being asked about? |
| LLM router | Combined prompt | Final decision with conflict resolution |

The **Taxonomy Signal Index** reads your taxonomy files, extracts every L5 activity using an LLM, embeds each one as a vector, and stores the result in SQLite. At query time it performs cosine similarity between the user's query and all indexed activities. If the score exceeds the threshold it injects a `process_hint` into the router — so the LLM router already knows the target skill before it even starts reasoning.

At runtime, `SkillAgent` calls this index through `TaxonomyRoutingCapability`. The default mode is `current`, which delegates to the existing `TaxonomySignalIndex` path and preserves current routing behavior. Operators can set `TAXONOMY_ROUTING_MODE=shadow` to compare an alternate taxonomy provider asynchronously while still returning the current result to the request path. Shadow comparisons record only bounded in-memory drift diagnostics: operation name, current/shadow skill, scores, method, a SHA-256 query hash, and a redacted 120-character query preview. Full prompts and raw queries are not persisted by the shadow boundary. Capability metadata marks taxonomy swaps as `deferred_quality_parity_required`: shadow mode can measure drift, but it cannot make the alternate result authoritative until routing-quality parity is proven.

**Benefits:**
- Routes correctly even when the user uses informal language ("vendors not being paid" → AP taxonomy hit → `fa_ap`)
- Handles cross-domain queries: a query that spans two L3 sections returns multiple hits → agent upgrades to orchestrator mode automatically
- Zero config: indexing runs in a background thread at startup; no manual step required
- Mtime-guarded: only re-indexes a file when it has changed on disk

---

## EC.md — Linking Taxonomy Files

Each process row in `Enterprise_Context.md` has a **Taxonomy** column that points to a taxonomy file:

```markdown
| Accounts Payable | AP, invoice ... | fa_ap | contexts/fa_environment.md | contexts/taxonomy/fa_taxonomy.md | ...
```

The value in that column (`contexts/taxonomy/fa_taxonomy.md`) is a **path relative to the tenant's `shared/contexts/` directory**. The indexer resolves it against the enterprise root automatically.

**Rules for the Taxonomy column:**
- One file per cell (current limit). If a process spans two files, pick the primary one.
- The path must exist — the indexer logs a warning and skips missing files.
- The file must follow the 4-rule structure below.

---

## The 4 Rules for Taxonomy Files

Every taxonomy file must follow these structural rules. The indexer uses them as anchors; the LLM handles all content inside sections.

### Rule 1 — YAML frontmatter with `name:` and `skills:`

```yaml
---
name: Finance & Accounting Taxonomy
type: taxonomy
description: L1-L5 F&A process hierarchy for AP, AR, GL
status: active
skills:
  - fa_ap
  - fa_ar
  - fa_gl
---
```

- `name:` — human label, used in log messages
- `skills:` — list of **all** skill IDs that appear anywhere in this file. The indexer validates extracted skill names against both this list AND `_index.yaml` to prevent hallucination.
- `type: taxonomy` — required; tells the indexer this is a taxonomy file (not a context or exception file)

### Rule 2 — `###` for L2 sections

```markdown
### L2: Accounts Payable
```

The `###` heading marks a major domain boundary. The L2 name is inherited by all L3 sections below it until the next `###` heading.

### Rule 3 — `####` for L3 sections

```markdown
#### L3: Invoice Processing `[APQC 9.6.1]`
```

The `####` heading marks the smallest unit the indexer processes. One LLM call is made per L3 section to extract all L5 activities inside it. Everything between this heading and the next `####` or `###` is passed to the LLM as a single block.

### Rule 4 — `<!-- skill: SKILL_ID -->` immediately after each L3 heading

```markdown
#### L3: Invoice Processing `[APQC 9.6.1]`
<!-- skill: fa_ap -->
```

This HTML comment on the line directly after the `####` heading binds the entire L3 section to a skill. It must:
- Be on its own line
- Be the **first** non-blank content after the heading
- Use a skill ID that exists in `_index.yaml`

If the tag is missing the section is skipped with a warning.

---

## Content Rules (Inside L3 Sections)

The indexer passes everything inside an L3 section to an LLM for extraction. You are **not** constrained to a specific table format — the LLM handles prose, tables, bullets, and nested headings. However, richer content produces better embeddings:

| What to include | Why it helps |
|---|---|
| L5 activity names (verb + noun) | Becomes the embed text |
| Short descriptions (1–2 sentences) | Semantic signal for matching informal queries |
| Severity / MTTR / risk labels | Useful for the LLM router's context injection |
| ITIL/APQC tags | Cross-reference matching for compliance queries |
| Exception file references | Injected as context files when skill routes |

**What the indexer extracts per L5 activity:**

```
embed_text: "IT Operations > Container Orchestration (K8s) > Pod Lifecycle Management > Restart CrashLoopBackOff pod — Container keeps crashing and restarting"
skill:       "ccdops"
```

The full L1→L2→L3→L5 path is always prepended to the description. This means embedding "Restart CrashLoopBackOff pod" lands near other K8s operations, not near unrelated activities that happen to use similar words.

---

## Minimal Working Example

```markdown
---
name: My Domain Taxonomy
type: taxonomy
description: Example taxonomy for widget operations
status: active
skills:
  - widget_ops
---

# Widget Operations — Process Taxonomy

### L2: Widget Lifecycle

#### L3: Widget Provisioning
<!-- skill: widget_ops -->

| L5 Activity | Description | Severity |
|---|---|---|
| Allocate widget pool | Reserve widgets from the shared pool for a project team | P3 |
| Decommission expired widget | Remove end-of-life widgets and release quota | P4 |
| Rotate widget credentials | Refresh access keys for widget API integration | P2 |
```

On next server start (or after the file's mtime changes), the indexer calls the LLM on this section, extracts the 3 L5 activities, builds embed_text strings like:

```
Widget Operations > Widget Lifecycle > Widget Provisioning > Allocate widget pool — Reserve widgets from the shared pool for a project team
```

...and stores vectors for all three. A user asking "how do I get widgets for my project?" will now score against "Allocate widget pool" and route to `widget_ops`.

---

## Linking to EC.md

Add a row to `Enterprise_Context.md` for the new domain:

```markdown
| Widget Operations | widget, widget pool, widget lifecycle, widget credential | widget_ops | contexts/widget_context.md | contexts/taxonomy/widget_taxonomy.md | ... |
```

The `Taxonomy` column points to your new file. That's all — the indexer picks it up from the EC.md table on next start.

---

## Monitoring Indexing Progress

The indexer logs to the server's stdout. Look for these lines:

```
[TaxonomySignalIndex] Starting index refresh for fa_taxonomy.md
[TaxonomySignalIndex] Extracted 19 nodes from L3: Invoice Processing (skill=fa_ap)
[TaxonomySignalIndex]   ✓ 231 nodes indexed, index ready
```

The index becomes active when the `✓ N nodes indexed, index ready` line appears. Queries before that line receive no taxonomy signal (router falls back to LLM-only routing, which still works).

### Routing Boundary Modes

| Environment variable | Default | Meaning |
|---|---|---|
| `TAXONOMY_ROUTING_MODE` | `current` | `current` delegates directly to `TaxonomySignalIndex`; `shadow` returns the current result and compares the shadow provider asynchronously |
| `TAXONOMY_SHADOW_SAMPLE_RATE` | `1.0` | Fraction of shadow-mode queries to compare, clamped from `0.0` to `1.0` |

Shadow mode is audit-only. It does not change `process_hint`, `process_matches`, selected skill, execution mode, or router input. It is intended for validating future taxonomy-routing providers under production traffic before any behavior-changing rollout.

### Reindexing

The indexer checks the file's **modification time (mtime)**. A file is re-indexed only when it has changed. To force a full re-index, `touch` the taxonomy file:

```bash
touch enterprise_root/tenants/company/shared/contexts/taxonomy/fa_taxonomy.md
```

Then restart the server.

---

## Scoring Thresholds

| Threshold | Value | Meaning |
|---|---|---|
| `COSINE_CLEAR` | 0.65 | Single strong match — return immediately, no term boost needed |
| `COSINE_FUZZY_LO` | 0.45 | Fuzzy zone — apply term boost for domain-specific keywords |
| `TERM_BOOST_PER` | 0.12 | Score added per shared token (≥4 chars) |
| `TERM_BOOST_CAP` | 3 | Max tokens boosted (caps boost at +0.36) |
| `find_skills min_score` | 0.55 | Minimum score for multi-domain hits |

You generally don't need to change these. If a domain-specific query is consistently missing, check that the L3 section has a `<!-- skill: -->` tag and that descriptions are descriptive enough for semantic matching.

---

## Multi-Domain Queries

If a query spans two domains (e.g. "CrashLoopBackOff pod on the payment service AND 50 invoices stuck in approval"), `find_skills()` returns hits for both `ccdops` and `fa_ap`. The agent detects multiple distinct skills and upgrades automatically to **orchestrator mode** — it dispatches both skills as child workers and synthesises their results.

No taxonomy file change is needed to support multi-domain queries. The behaviour is automatic when:
1. Both domains have taxonomy files indexed
2. Both domains' L5 activities embed at a score ≥ 0.55 for the query

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Wrong skill routed | L3 section missing `<!-- skill: -->` tag | Add tag, touch file, restart |
| Skill ID in log shows `UNKNOWN` | Skill not in `_index.yaml` | Add skill to `_index.yaml` first |
| Section not indexed | LLM returned 0 activities | Check that L3 section has L5 content — empty sections are skipped |
| File not picked up | Path in EC.md is wrong | Verify path resolves relative to `shared/contexts/` |
| No taxonomy signal firing | Index still loading | Wait for `index ready` log line; retry query |
| Multi-domain query routes to general | Correct — general skill runs orchestrator | Verify both domain scores appear in debug log |
