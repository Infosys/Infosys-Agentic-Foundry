# IAF AgentOS — Authoring Guide
## Taxonomy Files · Enterprise_Context.md · SKILL.md

**Infosys Agentic Foundry** | Agentic Harness Platform

---

## How to use this guide with an AI assistant

Copy the block below and paste it as your **system prompt** (or first message) in Claude, GitHub Copilot, or any AI assistant before asking it to help you write or edit these files. The assistant will then generate output that is guaranteed to pass the IAF parser.

```
You are an expert author for the IAF AgentOS platform. You help users create and
edit three types of files: taxonomy markdown files, Enterprise_Context.md, and
SKILL.md skill definitions.

You know the exact format rules for each file type — described below. You enforce
these rules on every output. You never deviate from the heading depths, tag
placements, or field names. When something is optional you say so.

=== TAXONOMY FILE RULES ===

A taxonomy file defines a process hierarchy (L1→L5). It is the source of truth
for the TaxonomySignalIndex — the engine that routes queries to the right skill.

STRUCTURE:
  YAML frontmatter       — required
  # H1 heading           — document title (informational only)
  ## L1: <name>          — L1 level (matches frontmatter name field)
  ### L2: <domain>       — L2 process area (### = exactly 3 hashes)
  #### L3: <subprocess> [APQC x.x.x]  — L3 section boundary (#### = exactly 4 hashes)
  <!-- skill: <name> --> — REQUIRED on the line IMMEDIATELY after the #### heading
  > blockquotes          — context_files pointers (read by LLM extractor)
  ##### L4: <group>      — L4 activity group (optional but recommended)
  | L5 Activity | Description |  — activity table (L5 leaf nodes)

FRONTMATTER (required fields):
  ---
  name: <L1 name — exactly as it will appear in the hierarchy>
  type: taxonomy
  description: <one line>
  status: active
  skills: [skill_a, skill_b]   # all skills referenced in this file
  ---

CRITICAL PARSER RULES (violations silently drop your content):
  1. ### = L2 heading. #### = L3 heading. NEVER use the wrong depth.
  2. <!-- skill: fa_ap --> MUST be on the very next line after ####. No blank
     line between them. No other content on that line. Omitting the tag causes
     the section to be skipped with a WARNING but no error.
  3. Skill names must exactly match a registered skill in _index.yaml.
  4. L1 name is taken from frontmatter `name:` field — the ## heading is ignored.
  5. Taxonomy files are discovered from Enterprise_Context.md via:
     (a) frontmatter `taxonomy:` list, OR
     (b) body references matching `contexts/taxonomy/<file>.md`
     A file not referenced in EC.md will never be indexed.
  6. context_files are extracted by the LLM from blockquote lines in the form:
     > _Label:_ `filename.md` → Section Name
     Use backticks around filenames. The LLM reads these and populates the
     `context_files` column in the taxonomy_signal_index table.

APQC TAG FORMAT:
  #### L3: Invoice Processing `[APQC 9.6.1]`
  The APQC tag is inside backticks at the end of the L3 heading. It is stripped
  by the parser before storing the L3 name — it is informational only.

CORRECT L3 SECTION TEMPLATE:
  #### L3: <Subprocess Name> `[APQC x.x.x]`
  <!-- skill: fa_ap -->

  > _Exceptions:_ `fa_exceptions.md` → <Section Name>
  > _Benchmarks:_ `fa_benchmarks.md` → <Section Name>
  > _Judgment:_ `fa_judgment.md` → <Section Name>

  ##### L4: <Activity Group Name>
  | L5 Activity | Description |
  |---|---|
  | <Activity name> | <One-sentence description> |
  | <Activity name> | <One-sentence description> |

  ---

=== ENTERPRISE_CONTEXT.MD RULES ===

Enterprise_Context.md is the master routing index. The agent reads it first on
every query and follows its pointers. It also tells TaxonomySignalIndex which
taxonomy files to index.

STRUCTURE:
  YAML frontmatter  — required; `skills` list must name all active skills
  # Enterprise Context  — document title
  ## L1: <domain group>   — top-level domain grouping (e.g. Finance & Accounting)
  ### L2 Process Map      — table mapping L2 domains to aliases and context files
  ### <Domain> Routing Instructions  — step-by-step agent instructions
  ### <Domain> Context File Inventory  — table listing all context files

FRONTMATTER:
  ---
  name: Enterprise Context
  type: root
  description: <one line>
  status: active
  skills:
    - fa_ap
    - fa_ar
    - <all active skills>
  ---

L2 PROCESS MAP TABLE (required columns):
  | Process | Aliases | Skill | Environment | Taxonomy | Exceptions | Benchmarks | Judgment | Framework |

  - Aliases: comma-separated keywords the agent uses for routing — MORE IS BETTER.
    Include abbreviations, error codes, ERP terms, user slang.
  - Taxonomy: MUST use the path pattern `contexts/taxonomy/<file>.md` (no leading
    slash, no /shared/ prefix) — this is what TaxonomySignalIndex greps for.
  - All file references use virtual paths relative to /shared/ — written as
    `contexts/<subfolder>/<file>.md` in tables and `> contexts/...` in blockquotes.

VIRTUAL PATH RULES:
  - In EC.md and context files: use `contexts/subfolder/file.md` (no /shared/ prefix)
  - In SKILL.md context_files: use `/shared/contexts/subfolder/file.md` (with prefix)
  - In agent config.yaml: use `/shared/Enterprise_Context.md` (with prefix)
  - NEVER use absolute filesystem paths (/Users/...) — SafeKernel will reject them.

=== KNOWLEDGE BUNDLE RULES ===

A knowledge bundle is a tenant-owned, domain-specific wiki under
`/shared/knowledge/{bundle_id}/`. The platform discovers bundles by convention:
any folder with both `manifest.yaml` and `index.md` is a bundle. Do not add a
central registry file.

REQUIRED STRUCTURE:
  /shared/knowledge/{bundle_id}/
    manifest.yaml   # required, kind: knowledge_bundle
    index.md        # required, entry point used by skills
    log.md          # append-only changelog
    MAINTAINER.md   # agent maintenance rules
    policies/ runbooks/ tables/ metrics/ apis/ notes/ ...

MANIFEST:
  kind: knowledge_bundle
  bundle_id: finance_ap
  domain: Finance & Accounting
  skills: [invoice_processing_ap, fa_ap, fa_ar]
  tags: [ap, invoice, three-way-match, vendor, payment]
  write_targets:
    rule: policies/
    runbook: runbooks/
    table: tables/
    metric: metrics/
    default: notes/

WRITE FLOW:
  1. Runtime learning writes `pending_review` records to knowledge.jsonl.
  2. A human chooses Confirm & Write, record-only confirm, or Bulk Confirm &
     Route in the Knowledge Dashboard.
  3. Confirm & Write publishes to the selected target; `written_to` is recorded
     only after the file write succeeds. Publication failures are visible as
     partial results instead of successful file writes.
  4. If the confirmed record matches a bundle by skill or tags, it can be
     appended to the bundle page selected by `write_targets`.
  5. The bundle's `log.md` receives one dated changelog line.
  6. Reviewers may explicitly override to `skills/<skill>/SKILL.md` as an
     advanced target only when the record skill exactly matches the target
     skill. This appends to `## Confirmed Operating Notes`; do not use it for
     ordinary facts that belong in memory topics or knowledge bundles.
  7. Bulk routing auto-publishes entity, source-context, and bundle matches.
     LLM-only/unmatched records are confirmed record-only and reported as such.

MAINTAINER.md RULES:
  - State which pages to update for rules, runbooks, schemas, metrics, APIs, and
    exceptions.
  - Require additive changes only unless the user explicitly asks to rewrite a
    page.
  - Require `log.md` updates for every maintained page change.
  - Require provenance: source query, source file, database/API, or approval id.
  - Do not duplicate `Enterprise_Context.md`; link back to it only for routing.

SKILL LINKAGE:
  Skills that depend on a bundle should point at its entry point:
  `context_file: /shared/knowledge/{bundle_id}/index.md`.

ADDING A NEW L1 DOMAIN:
  1. Add a new ## L1: section to EC.md
  2. Add its taxonomy file reference in the L2 Process Map table:
     `contexts/taxonomy/<new_taxonomy>.md`
  3. The taxonomy file will be auto-discovered on the next server restart.

=== SKILL.md RULES ===

SKILL.md is a markdown file that tells the agent who it is, what tools to use,
and how to behave. No Python required.

FRONTMATTER (required fields):
  ---
  name: <unique_identifier>        # used for routing — lowercase, underscores
  description: <one sentence>      # used by the LLM router — be specific
  version: "1.0"
  execution_mode: react            # react | workflow | parallel | supervisor | orchestrator | rlm | graph
  tools:
    - read_file
    - query_memory
  keywords:
    - invoice                      # routing keywords — more is better
    - vendor
  ---

EXECUTION MODE GUIDE:
  react        — open-ended Q&A, investigation, ReAct loop. Default.
  workflow     — fixed ordered steps, no branching.
  parallel     — steps that can run concurrently (DAG).
  supervisor   — this skill orchestrates other skills.
  orchestrator — auto-selected by router for multi-step queries; do not set manually.
  planned      — auto-selected by router for multi-domain queries; do not set manually.

CONTEXT FILES IN SKILL.md:
  context_files:
    - /shared/contexts/fa_environment.md
    - /shared/contexts/judgment/fa_judgment.md
  These use the /shared/ prefix (unlike EC.md table references).
  These are loaded at runtime and injected into the agent prompt.

SKILL BODY CHECKLIST:
  ✓ One-line persona statement ("You are an expert in...")
  ✓ ## Your job section — what queries this skill handles
  ✓ ## How to answer — step-by-step tool usage instructions
  ✓ ## Rules — hard constraints (never guess, always validate, etc.)
  ✓ ## Data sources — which DB/tool for each data type
  ✓ Tell the agent when to call query_memory first
  ✓ Specify output format (table, prose, JSON, markdown)

=== VALIDATION CHECKLIST ===

Before saving any taxonomy file:
  [ ] frontmatter has name, type: taxonomy, status: active, skills list
  [ ] Each L3 section uses #### (4 hashes exactly)
  [ ] Each L3 section has <!-- skill: <name> --> on the very next line
  [ ] Skill name matches a name in enterprise_root/tenants/company/skills/_index.yaml
  [ ] Taxonomy file is referenced in Enterprise_Context.md as `contexts/taxonomy/<file>.md`
  [ ] L5 activities are in | Activity | Description | table rows (not bullets)
  [ ] context_files blockquotes use backtick-wrapped filenames

Before saving Enterprise_Context.md:
  [ ] frontmatter skills list includes all active skills
  [ ] Taxonomy column uses `contexts/taxonomy/<file>.md` (no /shared/ prefix)
  [ ] All virtual paths use contexts/ not /shared/contexts/
  [ ] Each L2 domain has comprehensive aliases (50+ keywords is good)

Before saving SKILL.md:
  [ ] name is unique across all skills in _index.yaml
  [ ] keywords list has 10+ terms
  [ ] execution_mode is one of the four manual values (not orchestrator/planned)
  [ ] context_files paths use /shared/ prefix
  [ ] Skill is registered in enterprise_root/tenants/company/skills/_index.yaml
```

---

## Part 1 — Taxonomy File Reference

### File location

```
enterprise_root/tenants/company/shared/contexts/taxonomy/
└── <domain>_taxonomy.md
```

### Minimum viable taxonomy file

```markdown
---
name: Procurement Taxonomy
type: taxonomy
description: L1-L5 process hierarchy for Procurement — Purchase to Pay
status: active
skills: [procurement]
---

# Procurement — Process Taxonomy (L1→L5)
_Last updated: 2026-05-01_

---

## L1: Procurement

### L2: Purchase to Pay (PtP)

> **PtP Domain Policies**
> _Approval Policy:_ `proc_judgment.md` → L2: Purchase Approval
> _Vendor Policy:_ `proc_judgment.md` → L2: Vendor Management

---

#### L3: Purchase Requisition `[APQC 9.1.1]`
<!-- skill: procurement -->

> _Exceptions:_ `proc_exceptions.md` → Purchase Requisition Exceptions
> _Benchmarks:_ `proc_benchmarks.md` → Requisition SLAs
> _Judgment:_ `proc_judgment.md` → Approval Authority

##### L4: Requisition Creation
| L5 Activity | Description |
|---|---|
| Raise purchase requisition | Create PR in ERP with cost centre, GL account, and quantity |
| Attach supporting documentation | Upload quotes, SoW, or business case to PR |
| Submit for approval | Route PR to budget owner per DOA matrix |

---
```

### Heading depth rules

| Level | Markdown | Parser reads as | Example |
|---|---|---|---|
| L1 | YAML `name:` | hierarchy root | `Finance & Accounting Taxonomy` |
| L2 | `###` (3 hashes) | domain grouping | `### L2: Accounts Payable (PtP)` |
| L3 | `####` (4 hashes) | section boundary + skill assignment | `#### L3: Invoice Processing \`[APQC 9.6.1]\`` |
| L4 | `#####` (5 hashes) | activity group label (optional) | `##### L4: Invoice Approval` |
| L5 | Table row | leaf activity — indexed + embedded | `\| Approve invoice \| ... \|` |

### Skill tag placement

```
#### L3: Invoice Processing `[APQC 9.6.1]`   ← L3 heading
<!-- skill: fa_ap -->                           ← MUST be next line, no blank line
                                                ← blank line OK here
> _Exceptions:_ `fa_exceptions.md` ...
```

**Common mistake — blank line before skill tag (WRONG):**
```
#### L3: Invoice Processing `[APQC 9.6.1]`

<!-- skill: fa_ap -->    ← parser will NOT read this
```

### context_files blockquote format

The LLM extractor reads blockquote lines in this L3 section and populates `context_files`. These are surfaced in the Taxonomy Graph UI and fed to the agent as hints.

```markdown
> _Exceptions:_ `fa_exceptions.md` → Invoice Processing Exceptions
> _Benchmarks:_ `fa_benchmarks.md` → Invoice Processing SLAs
> _Judgment:_ `fa_judgment.md` → Invoice Approval Thresholds
```

Rules:
- Use backticks around filenames — `fa_exceptions.md` not fa_exceptions.md
- One file reference per line
- Label before the colon is for human readability — the LLM extracts the filename

### Adding a new L3 section to an existing taxonomy

1. Add under the correct `### L2` heading (order within L2 is informational only)
2. Use `####` heading with APQC tag if known
3. Add `<!-- skill: <name> -->` immediately on the next line
4. Add blockquote context_file pointers if this section needs specific files
5. Add L4/L5 content as `##### L4` headers + `| Activity | Description |` tables
6. Save file — re-indexing is automatic on next query (mtime check)

---

## Part 2 — Enterprise_Context.md Reference

### File location

```
enterprise_root/tenants/company/shared/Enterprise_Context.md
```

### How TaxonomySignalIndex discovers taxonomy files

The indexer looks in two places (in order):

1. **YAML frontmatter `taxonomy:` list** (preferred):
   ```yaml
   ---
   taxonomy:
     - contexts/taxonomy/fa_taxonomy.md
     - contexts/taxonomy/it_ops_taxonomy.md
   ---
   ```

2. **Body grep fallback** — any occurrence of `` `contexts/taxonomy/<file>.md` `` in the document body.

If your taxonomy file is not referenced in EC.md via one of these patterns, it will never be indexed regardless of its location on disk.

### Adding a new L2 domain to an existing L1

Add a row to the L2 Process Map table:

```markdown
| Procurement | PR, purchase requisition, vendor, PO, GR/IR, three-way match | procurement | `contexts/proc_environment.md` | `contexts/taxonomy/proc_taxonomy.md` | `contexts/exceptions/proc_exceptions.md` | `contexts/benchmarks/proc_benchmarks.md` | `contexts/judgment/proc_judgment.md` | — |
```

Then add routing instructions:

```markdown
### Procurement Routing Instructions

#### Step 1: Identify the procurement subprocess
| If the query mentions… | Subprocess | Start with… |
|---|---|---|
| purchase requisition, PR, approval, DOA | Purchase Requisition | `contexts/proc_environment.md` |

#### Step 2: Load context files in order
1. **Environment** → `contexts/proc_environment.md`
2. **Taxonomy** → `contexts/taxonomy/proc_taxonomy.md`
3. **Exceptions** → `contexts/exceptions/proc_exceptions.md`
```

### Adding a new L1 domain (a whole new business area)

1. Add a `## L1: <Domain>` section to EC.md
2. Create `contexts/taxonomy/<domain>_taxonomy.md` (see Part 1)
3. Reference the taxonomy file in EC.md (table column or frontmatter list)
4. Add the new skill(s) to the frontmatter `skills:` list in EC.md
5. Restart the server — the indexer will pick up the new file

### Virtual path conventions

| Where | Path format | Example |
|---|---|---|
| EC.md table references | `contexts/subfolder/file.md` | `contexts/taxonomy/fa_taxonomy.md` |
| EC.md body blockquotes | `contexts/subfolder/file.md` | `> \`contexts/judgment/fa_judgment.md\`` |
| SKILL.md `context_files:` | `/shared/contexts/subfolder/file.md` | `/shared/contexts/fa_environment.md` |
| Agent `config.yaml` | `/shared/Enterprise_Context.md` | `/shared/Enterprise_Context.md` |
| Agent shell calls at runtime | `/shared/contexts/...` | `cat /shared/contexts/fa_environment.md` |

---

## Part 3 — SKILL.md Reference

### File location and registration

```
enterprise_root/tenants/company/skills/
└── <skill_name>/
    └── SKILL.md

enterprise_root/tenants/company/skills/_index.yaml   ← must add entry here
```

### _index.yaml registration

```yaml
skills:
  procurement:                    # key is the skill name (folder name)
    description: "Handles purchase requisitions, vendor onboarding, PO matching, and approval workflows"
    category: operations          # optional — used for routing group / UI label
    keywords:
      - purchase requisition
      - vendor
    status: active                # active | draft | deprecated
```

### Complete SKILL.md field reference

| Field | Required | Values | Description |
|---|---|---|---|
| `name` | Yes | `snake_case` | Unique identifier — used for routing |
| `description` | Yes | One sentence | Used by LLM router — be specific about the domain |
| `version` | No | `"1.0"` | Semver string |
| `execution_mode` | Yes | `react` / `workflow` / `parallel` / `supervisor` | How the agent loops |
| `tools` | Yes | list of tool names | Which tools the agent may call |
| `keywords` | Yes | list of strings | Routing keywords — 10+ recommended |
| `context_file` | No | `/shared/...` path | Single context markdown auto-injected into the prompt at runtime (this is the field the runtime loads) |
| `context_files` | No | `/shared/...` paths | Reference list read by the Skill Builder for display; the runtime injects only the singular `context_file` |
| `sql_mode` | No | `read_only` / `read_write` | Whether `run_sql_query` may issue writes (default: `read_only`) |
| `max_steps` | No | integer | Hard cap on loop iterations / orchestrator steps (default: 10) |
| `business_context` | No | mapping | Structured domain/process/rules metadata |
| `approval_rules` | No | mapping | HITL approval gates (thresholds, always/never require) |
| `evidence_highlights` | No | mapping | Optional Evidence Viewer terms/regex rules |

### Optional evidence_highlights

```yaml
evidence_highlights:
  enabled: true
  terms:
    - "AI Led Value Delivered"
  patterns:
    - name: amount
      regex: '\$\s?\d+(?:\.\d+)?\s?[KMB]?'
      reason: configured_amount
  llm_suggestions:
    enabled: false
```

Use this only for domain terms that should be highlighted whenever they appear in captured evidence text. The backend ignores the block when missing, ignores invalid regex patterns with a warning, and does not make an LLM call unless a future implementation explicitly enables `llm_suggestions`.

### Minimal SKILL.md

```markdown
---
name: procurement
description: Handles purchase requisitions, vendor onboarding, PO matching, and approval workflows
version: "1.0"
execution_mode: react
tools:
  - read_file
  - query_memory
  - run_sql
keywords:
  - purchase requisition
  - PR
  - vendor
  - PO
  - three-way match
  - approval
  - DOA
context_files:
  - /shared/contexts/proc_environment.md
  - /shared/contexts/judgment/proc_judgment.md
---

You are an expert in Procurement and Purchase-to-Pay operations.

## Your job
Answer questions about purchase requisitions, vendor management, PO matching,
and approval workflows.

## How to answer
1. Call `query_memory` first — the user may have asked about this vendor before.
2. Read `/shared/contexts/proc_environment.md` for ERP config and active vendors.
3. Use `run_sql` on the procurement database for live PO and invoice data.
4. For approval authority, read `/shared/contexts/judgment/proc_judgment.md`.

## Rules
- Never guess approval amounts — always look up the DOA matrix.
- If a PO number is missing, ask the user before querying.
- Format currency as the region convention from proc_environment.md.

## Data sources
Use `run_sql` with database `procurement` for all live queries.
Key tables: purchase_orders(id, vendor_id, status, amount), vendors(id, name, status)
```

---

## Part 4 — Common Mistakes and Fixes

### Taxonomy section silently missing from the graph

**Symptom:** You added an L3 section but it doesn't appear in the Taxonomy Graph UI.

**Causes and fixes:**

| Cause | Fix |
|---|---|
| Wrong heading depth (`###` instead of `####`) | Change to exactly 4 hashes |
| Blank line between `####` and `<!-- skill: -->` | Remove the blank line |
| Skill name not in `_index.yaml` | Add skill to `_index.yaml` and restart |
| Taxonomy file not referenced in EC.md | Add `contexts/taxonomy/<file>.md` to EC.md |
| File changed but index not refreshed | Touch the file or restart server (mtime check runs on next query) |

### Routing goes to the wrong skill

**Symptom:** A query routes to `fa_ap` when it should go to `fa_ar`.

**Fixes:**
1. Open Taxonomy Graph → run the query in the Route Simulator (Zone C)
2. Look at which L3 sections score highest
3. Add more specific L5 activities to the correct L3 section
4. Add more aliases to the L2 Process Map row in EC.md

### context_files chips not showing in Taxonomy Graph

**Symptom:** L3 section card shows no context file chips.

**Causes:** The blockquote filenames are not in backticks, or the section was indexed before you added the blockquotes.

**Fix:** Add/fix the backtick-wrapped filenames in the blockquote, then delete the stale rows from `taxonomy_signal_index` and restart to re-index:
```bash
sqlite3 knowledge_index.db "DELETE FROM taxonomy_signal_index WHERE src_file LIKE '%your_taxonomy%';"
```

---

## Part 5 — Re-indexing and Validation

### How re-indexing works

- On every server startup, `TaxonomySignalIndex` checks each taxonomy file's `mtime`
- If the file changed since last indexing, it re-parses and re-embeds that file
- If the file is unchanged, it loads from SQLite cache (fast)
- Re-indexing a 20-section file takes ~15–30 seconds (LLM + embedding calls)

### Checking index status

Open [Taxonomy Graph](http://localhost:8081/skill-builder/v2) → click the Taxonomy Graph nav tab. The stats strip shows total indexed activities, skills, and taxonomies. If your new section isn't there, check the server log for `TaxonomySignalIndex:` lines.

### Validating routing with the simulator

1. Open the Taxonomy Graph tab
2. Click "Taxonomy Graph" toggle (top right of the page)
3. In Zone C (right panel), type a sample query
4. Press Ctrl+Enter or click ⚡ Simulate Route
5. The winner badge shows the top-matched L3 section and skill
6. A margin < 0.05 means ambiguous routing — add more specific L5 activities

---

## Part 6 — Files Changed in CODE_DOC_MAP

When you modify any of these files, update the docs listed in [CODE_DOC_MAP.yaml](CODE_DOC_MAP.yaml):

| File you changed | Docs to update |
|---|---|
| `taxonomy_signal_index.py` | `docs/TAXONOMY_AUTHORING.md`, `docs/KEY_FEATURES.md`, `docs/03_architecture.md` |
| `Enterprise_Context.md` | `IAF-Agent-Studio/docs/context_loading_architecture.md` |
| Any `*_taxonomy.md` | This file — add new domains/sections to Part 1 examples |
| `_index.yaml` | `docs/DEVELOPER_GUIDE.md` Part 1 Step 3 |
| Any `SKILL.md` | `docs/DEVELOPER_GUIDE.md` SKILL.md field reference |
