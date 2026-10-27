# invoke_skill & invoke_plan — Change Registry

> **Feature:** Cross-skill delegation tools (invoke_skill + invoke_plan)
> **Date added:** 2026-03-16
> **Purpose:** Allow the ReAct agent to delegate sub-tasks to other skills (sequential or parallel DAG)

---

## How to Fully Revert

Remove/revert the items below **in order** (bottom-up is safest):

---

### 1. tool_factory.py
**File:** `iaf_agent_skills/tool_factory.py`

| What | Action | Lines (approx) |
|------|--------|-----------------|
| Constants: `MAX_INVOKE_DEPTH`, `MAX_PLAN_STEPS`, `MAX_RESULT_CHARS` | **DELETE** 3 constants + their comments | Lines 26-33 |
| `create_invoke_skill_tool()` function + section comment | **DELETE** entire function (~90 lines) | Lines 605-698 |
| `create_invoke_plan_tool()` function + section comment | **DELETE** entire function (~200 lines) | Lines 700-end of file |

**Nothing else in this file was modified.** All existing functions (shell, sql, write_file, memory) are untouched.

---

### 2. agent.py
**File:** `iaf_agent_skills/agent.py`

| What | Action | Location |
|------|--------|----------|
| Import: `create_invoke_skill_tool, create_invoke_plan_tool, MAX_INVOKE_DEPTH` | **DELETE** 3 lines from the `from .tool_factory import (...)` block | ~Lines 53-55 |
| `__init__`: `self._invoke_depth = 0` | **DELETE** 1 line + its comment | ~Line 159 |
| `_get_allowed_tools()`: `"invoke_skill", "invoke_plan"` in default list | **DELETE** these 2 strings from the list | ~Line 279 |
| `SYSTEM_PROMPT`: "Cross-Skill Delegation" section | **DELETE** the block from `## Cross-Skill Delegation` to just before `"""` closing the prompt (16 lines) | ~Lines 614-631 |
| `_create_agent()`: invoke tool registration block | **DELETE** entire `# --- Cross-skill delegation tools ---` block (~35 lines) from `_depth = getattr(...)` through the `else: logger.info("Delegation tools skipped...")` | ~Lines 1305-1345 |
| `_run_parallel()`: asyncio loop detection | **REVERT** to original single-line `results = asyncio.run(engine.run(...))` — remove the `try/get_running_loop/ThreadPoolExecutor` wrapper | ~Lines 1758-1772 |

**Revert for `_run_parallel` — restore this exact code:**
```python
        # Execute parallel workflow
        try:
            results = asyncio.run(engine.run(steps, status_callback=emit_status))
        except ValueError as e:
```
> ⚠️ **Warning:** This reverts the pre-existing asyncio bug fix too. All parallel-mode skills
> (parallel_fetch, parallel_report, supervisor_report) will crash under uvicorn again.
> Consider keeping just the asyncio fix even if you remove invoke_skill/invoke_plan.

---

### 3. config.yaml
**File:** `enterprise_root/tenants/company/agents/enterprise_agent/config.yaml`

| What | Action | Lines |
|------|--------|-------|
| `- invoke_skill` | **DELETE** 1 line | Line 24 |
| `- invoke_plan` | **DELETE** 1 line | Line 25 |

---

### 4. chat.py (optional — independent improvement)
**File:** `IAF-Agent-Studio/routers/chat.py`

| What | Action | Lines |
|------|--------|-------|
| Traceback logging in except block | **REVERT** to `return {"error": str(e)}` (remove `import traceback` + `logger.error(...)` lines) | ~Lines 161-164 |

> This is a standalone logging improvement, not required for invoke_skill/invoke_plan.
> **Recommendation:** Keep it regardless — it helps debug all server errors, not just ours.

---

### 5. Test file
**File:** `tests/test_invoke_tools.py`

| What | Action |
|------|--------|
| Entire file | **DELETE** |

---

### 6. This file
**File:** `IAF-Agent-Skills/INVOKE_TOOLS_CHANGESET.md`

| What | Action |
|------|--------|
| This registry doc | **DELETE** after revert is complete |

---

## Files NOT modified (no revert needed)

| File | Status |
|------|--------|
| `iaf_agent_skills/execution.py` | Untouched — Step, ParallelEngine, WorkflowEngine reused as-is |
| `iaf_agent_skills/router.py` | Untouched — match(), skill_exists() reused as-is |
| `iaf_agent_skills/loader.py` | Untouched — Skill dataclass reused as-is |
| All skill SKILL.md files | Untouched |
| All database files | Untouched |

---

## Quick Revert Checklist

```
[ ] 1. Delete constants from tool_factory.py (lines 26-33)
[ ] 2. Delete create_invoke_skill_tool() from tool_factory.py
[ ] 3. Delete create_invoke_plan_tool() from tool_factory.py
[ ] 4. Remove 3 imports from agent.py import block
[ ] 5. Remove self._invoke_depth = 0 from agent.py __init__
[ ] 6. Remove "invoke_skill","invoke_plan" from _get_allowed_tools() default list
[ ] 7. Remove "Cross-Skill Delegation" from SYSTEM_PROMPT
[ ] 8. Remove invoke tool registration block from _create_agent()
[ ] 9. Revert _run_parallel() asyncio fix (or keep it — see warning)
[ ] 10. Remove invoke_skill + invoke_plan from config.yaml
[ ] 11. (Optional) Revert chat.py traceback logging
[ ] 12. Delete tests/test_invoke_tools.py
[ ] 13. Delete this file (INVOKE_TOOLS_CHANGESET.md)
[ ] 14. Restart server
```
