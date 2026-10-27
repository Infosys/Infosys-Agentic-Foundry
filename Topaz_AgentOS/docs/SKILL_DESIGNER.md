# Skill Designer — NL Authoring (Dev Mode)

> **Audience:** developers/admins. **Status:** shipped on `feat/rlm-integration`.
> Verify against `routers/designer.py`, `routers/designer_core.py`, and
> `enterprise_root/tenants/company/skills/skill_designer/SKILL.md`.

## What it is
The **Skill Designer** lets a developer describe a capability in plain English and have the platform
**draft** it — a skill (any execution mode), a **graph_skill**, a **workstream**, or a **cron** — then
review it in an editable pane and save it through the *existing governed creators*. It is
**draft-only and isolated**: it never executes business actions and never reaches the runtime router.

## Where to use it
- **Main chat, Dev Mode** (`index.html`): a role-gated **🛠 Dev Mode** pill (admins/developers/owners
  only). ON → an "authoring, not executing" banner + a right-column **artifact canvas** (editable
  spec/YAML + live diagram + **Validate** / **Save**). Chat turns route to `/api/designer/chat`.
- **Graph Studio** ([PROCESS_GRAPHS_AND_GRAPH_STUDIO.md](PROCESS_GRAPHS_AND_GRAPH_STUDIO.md)):
  the **Draft with AI** box calls the same endpoint with `artifact_hint: graph_skill`.

## How it works (isolation + governance by reuse)
- The authoring "brain" is a **draft-only skill** `skill_designer` (`execution_mode: react`,
  **`tools: []`** — it cannot write or execute). `POST /api/designer/chat` forces
  `skill_name="skill_designer"` server-side, so the business router (`router.match`) is never called.
- It returns a strict **JSON envelope**: `{artifact_type, name, summary, reply, questions, warnings,
  skill{…}, graph_yaml, workstream{…}, cron{…}, mermaid}`. When the type/mode is unspecified it first
  returns an `artifact_type: "clarify"` turn (recommendation + questions) instead of guessing.
- `POST /api/designer/validate` runs the **real** validators by type: `validate_graph`+`compile_to_plan`
  (graph), `validate_workstream` (workstream), croniter (cron), snake_case + mode checks (skill).
- **Persistence** reuses existing governed creators — no duplicated logic:
  - `POST /api/designer/submit` (skills/graph_skills) → writes the draft to the author's **personal**
    workspace and submits to the **Command Center review queue**; an **admin approve** promotes it to
    the global skills (graph.yaml rides through submit → approve). This is the governed path.
  - `POST /api/designer/save` (workstream/cron, or admin direct-publish of a skill) → `WorkstreamStore`
    / `cron_scheduler` / `SKILL.md`+`_update_index_yaml`.
- All endpoints require a **developer/admin/owner** role (`_require_dev`) plus the same
  `enforce_entitlement` checks as the underlying creators.

## Governance flow (skills/graphs)
```
describe (NL) → draft (clarify?) → Validate → Submit
   → personal workspace + pending submission
   → Command Center ▸ Skill Review ▸ Review Queue
   → admin Approve → promoted to global (now @mention-able)   [Reject → back to author]
```
See the review UI in `dashboard_v2.html` (My Skills · Team Skills · Submission Status · Review Queue)
and [HITL_DESIGN_GUIDE.md](HITL_DESIGN_GUIDE.md).

## Example
> "create a read-only skill that summarises overdue AP invoices" → the designer asks which mode
> (react vs workflow vs graph), you answer, it drafts the `SKILL.md`, you **Validate** → **Submit**,
> an admin approves it in Command Center.

## Related
- Router: `routers/designer.py`; pure helpers/validation: `routers/designer_core.py`
- Tests: `IAF-Agent-Studio/tests/test_designer_core.py`
- Review-queue creators: `routers/personal_skills.py`
