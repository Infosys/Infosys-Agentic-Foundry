# Prompt Version History

Backups of system prompts and skill prompts before each significant change.
Format: `<name>_v<version>_<YYYYMMDD>.md`

---

## AGENTIC_PROMPT (agent.py — system prompt for all agents)

| Version | Date | File | Change Summary |
|---|---|---|---|
| v3 | 2026-03-29 | [AGENTIC_PROMPT_v3_20260329.md](AGENTIC_PROMPT_v3_20260329.md) | Pre-backup before: parallel grep + dynamic query expansion + RRF scoring. Removed P2P-specific domain keywords from Steps 2/3. |
| v4 | 2026-03-29 | [AGENTIC_PROMPT_v4_20260329.md](AGENTIC_PROMPT_v4_20260329.md) | Step 2: parallel grep in one turn + generic query expansion. Step 3: RRF scoring. ThreadPoolExecutor mention only (no script). |
| v5 | 2026-03-29 | [AGENTIC_PROMPT_v5_20260329.md](AGENTIC_PROMPT_v5_20260329.md) | Option D applied. ThreadPoolExecutor in system prompt with placeholders. "For broad searches" qualifier still present. |
| v6 | 2026-03-29 | *(current in agent.py)* | Multi-variant search made MANDATORY. Removed "broad searches" qualifier. Script must always run — single-keyword grep not allowed. |

---

## p2p_consultant SKILL.md

| Version | Date | File | Change Summary |
|---|---|---|---|
| v2.1 | 2026-03-29 | [p2p_SKILL_v2.1_20260329.md](p2p_SKILL_v2.1_20260329.md) | Pre-backup before: Step 0 query expansion + parallel grep instruction + script template + RRF note. |
| v2.2 | 2026-03-29 | [p2p_SKILL_v2.2_20260329.md](p2p_SKILL_v2.2_20260329.md) | Added Step 0 (query expansion), parallel grep in Step 1, ThreadPoolExecutor script with P2P folders hardcoded, RRF scoring in Step 2. |
| v2.3 | 2026-03-29 | [p2p_SKILL_v2.3_20260329.md](p2p_SKILL_v2.3_20260329.md) | Option D applied. Script removed from SKILL.md, folder list only. "For broad searches" qualifier still present. |
| v2.4 | 2026-03-29 | [p2p_SKILL_v2.4_20260329.md](p2p_SKILL_v2.4_20260329.md) | Step 0 MANDATORY. Individual grep examples still shown first in Step 1 — LLM defaulted to those instead of parallel script. |
| v2.5 | 2026-03-29 | [p2p_SKILL_v2.5_20260329.md](p2p_SKILL_v2.5_20260329.md) | Step 1: "Do NOT write individual grep calls" — removed greps entirely. Too aggressive, agent lost fallback. |
| v2.6 | 2026-03-29 | [p2p_SKILL_v2.6_20260329.md](p2p_SKILL_v2.6_20260329.md) | Hybrid Step 1. Parallel script still not firing reliably from mid-prompt placement. |
| v2.7 | 2026-03-29 | [p2p_SKILL_v2.7_20260329.md](p2p_SKILL_v2.7_20260329.md) | MANDATORY START SEQUENCE working. But agent generated its own folder list instead of using hardcoded one — searched wrong folders, script returned empty. |
| v2.8 | 2026-03-29 | [p2p_SKILL_v2.8_20260329.md](p2p_SKILL_v2.8_20260329.md) | Replaced all hardcoded folder lists with `['/local/']` — searches entire mount recursively. No maintenance needed when folders change. Applies to mandatory sequence + Step 1 Option A + Option B. |
| v2.9 | 2026-03-29 | [p2p_SKILL_v2.9_20260329.md](p2p_SKILL_v2.9_20260329.md) | MANDATORY Step B replaced: Python parallel script → `invoke_skill → file_explorer`. File Discovery Step 1 Option A now delegates to file_explorer. invoke_skill removed from Step 4 (no longer last resort — it's the primary path). |
| v2.10 | 2026-03-29 | *(current in skills/p2p_consultant/SKILL.md)* | Added `target_skill="file_explorer"` to both invoke_skill call sites (MANDATORY Step B + File Discovery Option A). Fixes router sending file search tasks to p2p_consultant instead of file_explorer. |

---

## file_explorer SKILL.md

| Version | Date | File | Change Summary |
|---|---|---|---|
| v1.0 | 2026-03-29 | [file_explorer_SKILL_v1.0_20260329.md](file_explorer_SKILL_v1.0_20260329.md) | Original — sequential single grep per variant. |
| v1.1 | 2026-03-29 | *(current in skills/file_explorer/SKILL.md)* | Step 2 upgraded: single grep → ThreadPoolExecutor parallel search across all variants at once. Step 3 is now semgrep fallback (removed synonym table — variants cover this). Steps renumbered. |

---

## itops_rca SKILL.md

| Version | Date | File | Change Summary |
|---|---|---|---|
| v1.0 | 2026-03-29 | [itops_rca_SKILL_v1.0_20260329.md](itops_rca_SKILL_v1.0_20260329.md) | Original — no execution rules, hardcoded hostname. |
| v1.1 | 2026-03-29 | *(current in skills/itops_rca/SKILL.md)* | Added Execution Rules: never use session memory, never ask confirmation during investigation, never abandon on source failure, never produce partial RCA. Fixed hostname hardcoding in all CMDB queries → `<HOSTNAME>` placeholder. |

---

## How to restore a version

```bash
cp prompt_versions/AGENTIC_PROMPT_v3_20260329.md /tmp/restore_check.md
# then manually paste content back into agent.py AGENTIC_PROMPT string
```

For SKILL.md:
```bash
cp prompt_versions/p2p_SKILL_v2.1_20260329.md skills/p2p_consultant/SKILL.md
```
