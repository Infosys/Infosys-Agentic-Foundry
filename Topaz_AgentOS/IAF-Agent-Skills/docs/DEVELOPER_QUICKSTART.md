# Developer Quickstart - IAF Agent Skills

> **For LLM-Assisted Development:** Copy this entire document and paste it to GitHub Copilot, ChatGPT, or Claude when asking them to create new skills or agents for you.

---

## TL;DR

| I want to... | Create a... | Location |
|--------------|-------------|----------|
| **Build a skill without writing YAML** | **Chat with the Skill Builder** | Type *"create a skill for..."* in chat |
| Add new domain expertise (HR, Procurement, IT) | **Skill** | `skills/{skill_name}/SKILL.md` |
| Keep a skill private until it's ready | **Personal skill** | Saved to `/me/skills/` — only you see it |
| Share a skill with all users | **Submit for review** | Personal Skills panel → Submit, admin approves |
| Restrict team access to specific skills | **Agent** | `enterprise_root/tenants/{tenant}/agents/{agent_id}/config.yaml` |
| Run multiple skills at once | **Parallel skill** | `execution_mode: parallel` in SKILL.md |
| Orchestrate domain specialists | **Supervisor skill** | `execution_mode: supervisor` in SKILL.md |
| Inject domain policies/terminology | **Context file** | `enterprise_root/tenants/company/shared/contexts/*.md` |
| Schedule a skill to run automatically | **Cron job** | Skill Builder UI → Cron Jobs, or `POST /api/cron` |
| Run code around tool calls | **Hook** | `hooks:` section in agent `config.yaml` |
| Have one skill call another | **invoke_skill tool** | Add `invoke_skill` to `tools:` in SKILL.md |
| Require human sign-off before an action | **HITL approval** | Approval toggle in UI or `request_human_approval` tool |

**Fastest path: just say "create a skill for [your domain]" in chat.** The Skill Builder does the rest.

---

## Contents

- [Part 1: Creating a New Skill](#part-1-creating-a-new-skill)
- [Part 2: Registering a Skill](#part-2-registering-a-skill-_indexyaml)
- [Part 3: Creating an Agent](#part-3-creating-an-agent)
- [Part 4: LLM-Assisted Development](#part-4-llm-assisted-development)
- [Part 5: Execution Modes — Parallel and Supervisor](#part-5-execution-modes--parallel-and-supervisor)
- [Part 6: Context Files — Giving Skills Domain Knowledge](#part-6-context-files--giving-skills-domain-knowledge)
- [Part 7: Cron Jobs — Scheduling Skills to Run Automatically](#part-7-cron-jobs--scheduling-skills-to-run-automatically)
- [Part 8: Hook System — Running Scripts Around Tool Calls](#part-8-hook-system--running-scripts-around-tool-calls)
- [Part 9: invoke_skill — One Skill Calling Another](#part-9-invoke_skill--one-skill-calling-another)
- [Part 10: Human-in-the-Loop — Approval Flows](#part-10-human-in-the-loop--approval-flows)
- [Part 11: Building Skills Through Conversation — The Easiest Path](#part-11-building-skills-through-conversation--the-easiest-path)

---

## Architecture Overview

```
IAF Agent Platform
├── IAF-Agent-Skills/           # Agent framework + skills
│   └── skills/
│       ├── _index.yaml         # Skill registry (LLM routing)
│       ├── general/SKILL.md    # Fallback skill
│       ├── ar_ops/SKILL.md     # Accounts Receivable
│       ├── invoice/SKILL.md    # Invoice processing
│       └── {your_skill}/SKILL.md  # YOUR NEW SKILL
│
└── enterprise_root/            # Runtime data
    └── tenants/{tenant}/
        └── agents/
            ├── enterprise_agent/config.yaml  # All skills (default)
            ├── finance_agent/config.yaml     # Invoice skills only
            └── {your_agent}/config.yaml      # YOUR NEW AGENT
```

---

## Part 1: Creating a New Skill

### Step 1: Create the folder

```bash
mkdir -p skills/procurement
```

### Step 2: Create SKILL.md

Use this template:

```markdown
---
name: procurement
version: "1.0"
description: "Purchase order processing, vendor management, procurement workflows"
tools:
  - shell           # Shell commands (ls, cat, echo, mkdir, rm, grep, etc.)
  - run_sql_query   # Database queries
business_context:
  domain: "Procurement"
  process: "Purchase Order Management"
  activities:
    - CreatePurchaseOrder
    - ApprovePO
    - VendorLookup
    - TrackDelivery
---

# Procurement Agent

You are a Procurement Operations Agent responsible for purchase order processing and vendor management.

## ⚠️ CRITICAL: Query Classification

**SIMPLE QUERIES → Execute Immediately:**
- "show me...", "get...", "what is...", "list..."
- Just run the query and return results directly

**COMPLEX WORKFLOWS → Use Plan File:**
- "run daily procurement activities", "process all pending POs"
- Multi-step operations with tracking

## Your Capabilities

1. **Database Access**: Query procurement data from `/shared/databases/procurement.db`
2. **Policy Access**: Read approval rules from `/shared/policies/procurement_policy.md`
3. **Report Generation**: Create reports in `/me/reports/`
4. **Task Tracking**: Log progress in `/me/tasks/`

## IMPORTANT: File Writing Rules

Use ONLY these patterns:

**Single command with \n for newlines (PREFERRED):**
```bash
echo "# PO Report\n\n## Summary\nTotal POs: 15\nPending: 3" > /me/reports/po_summary.md
```

**Append mode for building files:**
```bash
echo "# Title" > /me/reports/file.md
echo "Line 2" >> /me/reports/file.md
```

**Unicode - use actual characters:**
```bash
echo "✓ Approved" >> /me/tasks/log.md
echo "• Item one" >> /me/tasks/list.md
```

**DO NOT USE:**
- Heredoc (`<< EOF`) - not supported
- `printf` with complex formats
- Unicode escapes (`\u2714`) - won't work

## Available Commands

| Command | Purpose | Example |
|---------|---------|---------|
| `ls` | List files | `ls /shared/databases/` |
| `cat` | Read file | `cat /shared/policies/procurement_policy.md` |
| `grep` | Search text | `grep "approved" /me/reports/*.md` |
| `echo > file` | Write file | `echo "content" > /me/notes.md` |
| `mkdir -p` | Create folder | `mkdir -p /me/reports/2024/` |
| `run_sql_query` | Query DB | See SQL section below |

## SQL Query Examples

When using `run_sql_query`, format as:

```sql
-- Get pending POs
SELECT po_number, vendor, amount, status
FROM purchase_orders
WHERE status = 'pending'
ORDER BY amount DESC
LIMIT 10;
```

## Example Interactions

**User:** "Show me pending POs over $10,000"
**You:** Run SQL query, format results as table, highlight high-value items.

**User:** "Run daily procurement activities"
**You:** 
1. Create plan file in `/me/tasks/`
2. Fetch pending POs
3. Check approval thresholds
4. Generate dashboard
5. Mark complete

## Response Format

- Use markdown tables for data
- Use bullet points for lists
- Always show counts/totals
- Highlight items needing attention with ⚠️
```

### Step 3: Register in _index.yaml

Add to `skills/_index.yaml`:

```yaml
skills:
  procurement:
    description: "Purchase order processing, vendor management, PO approval, delivery tracking. Keywords: PO, purchase order, vendor, procurement, supplier"
    keywords:
      - po
      - purchase order
      - vendor
      - procurement
      - supplier
      - delivery
```

### Step 4: Test

```bash
# Start server
cd IAF-Agent-Studio && python server.py

# Open browser to http://localhost:8080
# Type: "show me pending purchase orders"
# Should route to procurement skill
```

---

## Part 2: Creating a New Agent

Agents are **permission wrappers** that control which skills a team can access.

### When to Create an Agent

| Scenario | Create Agent? |
|----------|---------------|
| New domain, anyone can use | No (use enterprise_agent) |
| Team needs restricted access | **Yes** |
| Different tools per team | **Yes** |
| Audit requirements | **Yes** |

### Agent Config Template

Create `enterprise_root/tenants/company/agents/{agent_id}/config.yaml`:

```yaml
# Procurement Agent Configuration
# Restricted agent for procurement team

agent:
  name: "Procurement Assistant"
  description: "Specialized agent for PO processing and vendor management"
  version: "1.0"

# Skill access control
# mode: "all" | "allowlist" | "denylist"
skills:
  mode: "allowlist"
  allowed:
    - procurement
    - general  # Fallback for unmatched queries

# Tool access control
tools:
  allowed:
    - shell         # File system access
    - run_sql_query # Database queries
    # - execute_code  # Uncomment if code execution needed

# Audit settings
audit:
  log_queries: true
  log_responses: true
  log_tool_calls: true
```

### Using the Agent

In the UI or API, specify `agent_id`:

```json
{
  "content": "show me pending POs",
  "tenant_id": "company",
  "agent_id": "procurement_agent",
  "user_id": "john"
}
```

---

## Part 3: Complete Example - HR Domain

### 1. Create HR Skill

`skills/hr_ops/SKILL.md`:

```markdown
---
name: hr_ops
version: "1.0"
description: "HR operations - employee data, leave management, onboarding"
tools:
  - shell
  - run_sql_query
business_context:
  domain: "Human Resources"
  process: "Employee Management"
---

# HR Operations Agent

You are an HR Operations Agent responsible for employee data management.

## Your Capabilities

1. **Employee Data**: Query from `/shared/databases/employees.db`
2. **Leave Management**: Track in `/me/leave_requests/`
3. **Onboarding**: Checklist at `/shared/policies/onboarding_checklist.md`

## Common Queries

- "Show employees on leave this week"
- "Onboarding status for new hires"
- "Department headcount summary"

## Response Format

Use tables for employee lists. Include:
- Employee ID
- Name
- Department
- Status/Notes
```

### 2. Register in _index.yaml

```yaml
  hr_ops:
    description: "HR operations - employee data, leave management, onboarding, headcount. Keywords: HR, employee, leave, onboarding, headcount"
    keywords:
      - hr
      - employee
      - leave
      - onboarding
      - headcount
      - pto
```

### 3. Create HR Agent (Optional - for restricted access)

`enterprise_root/tenants/company/agents/hr_agent/config.yaml`:

```yaml
agent:
  name: "HR Assistant"
  description: "Employee management and HR operations"
  version: "1.0"

skills:
  mode: "allowlist"
  allowed:
    - hr_ops
    - general

tools:
  allowed:
    - shell
    - run_sql_query
```

---

## Quick Reference

### Skill File Structure

```
skills/{skill_name}/
├── SKILL.md           # Required - main prompt
├── INSTRUCTIONS.md    # Optional - detailed procedures
├── EXAMPLES.md        # Optional - example interactions
└── data/              # Optional - skill-specific data
```

### _index.yaml Entry Format

```yaml
  skill_name:
    description: "Brief description. Keywords: word1, word2, word3"
    keywords:
      - word1
      - word2
      - word3
```

### Agent Config Fields

```yaml
agent:
  name: "Display Name"
  description: "What this agent does"
  version: "1.0"

skills:
  mode: "all" | "allowlist" | "denylist"
  allowed: [skill1, skill2]  # If allowlist
  denied: [skill3]           # If denylist

tools:
  allowed:
    - shell
    - run_sql_query
    - execute_code

audit:
  log_queries: true
  log_responses: true
  log_tool_calls: true
```

---

## Troubleshooting

### Skill not being routed

1. Check `_index.yaml` has the skill registered
2. Verify keywords match user query
3. Test with explicit: "use procurement skill to show POs"

### Agent not loading skill

1. Check `config.yaml` has skill in `allowed` list
2. Verify skill exists in `skills/` folder
3. Check server logs for errors

### File writes failing

1. Use `echo "content" > file` not heredoc
2. Use actual Unicode chars, not escape codes
3. Check path exists: `mkdir -p /me/folder/` first

### ⚠️ CRITICAL: Path "File Not Found" Errors

**The #1 Mistake:** Including `enterprise_root` or the tenant path in SKILL.md

```markdown
# WRONG ❌ - This will fail!
cat /enterprise_root/standards/config.yaml
cat /tenants/company/agents/my_agent/data/file.md

# CORRECT ✅ - Always start paths with just /
cat /standards/config.yaml
cat /data/file.md
```

**Why this happens:**

The SafeKernel creates a **sandboxed virtual filesystem** where `/` maps to:
```
enterprise_root/tenants/{tenant}/agents/{agent}/
```

So when you write `/enterprise_root/...` in SKILL.md:
```
Your path:    /enterprise_root/standards/file.md
              ↓ SafeKernel strips /
              enterprise_root/standards/file.md
              ↓ Joins with sandbox root
Physical:     enterprise_root/tenants/company/agents/my_agent/enterprise_root/standards/file.md
              ↑ DOESN'T EXIST!
```

**The Rule:**
> In SKILL.md, `/` = the agent's workspace root.
> Never include `enterprise_root`, `tenants`, `company`, or `agents` in paths.

**Path Mapping Reference:**

| In SKILL.md | Physical Location |
|-------------|-------------------|
| `/` | `enterprise_root/tenants/{tenant}/agents/{agent}/` |
| `/data/` | `enterprise_root/tenants/{tenant}/agents/{agent}/data/` |
| `/standards/` | `enterprise_root/tenants/{tenant}/agents/{agent}/standards/` |
| `/me/` | `enterprise_root/tenants/{tenant}/agents/{agent}/users/{user}/` |
| `/shared/` | `enterprise_root/tenants/{tenant}/shared/` (read-only) |

---

## Prompt for LLMs

When asking an LLM to create a skill, use this prompt:

```
I need to create a new skill for the IAF Agent platform.

Domain: [YOUR DOMAIN]
Purpose: [WHAT IT DOES]
Data sources: [DATABASES, FILES]
Key activities: [LIST MAIN TASKS]

Please generate:
1. SKILL.md file with YAML frontmatter
2. _index.yaml entry with keywords
3. Optionally, agent config.yaml if access control needed

Follow the IAF Agent patterns:
- Query classification (simple vs workflow)
- File writing with echo (no heredoc)
- Actual Unicode characters
- SQL query examples
```

---

## Live Examples

See these existing skills as references:

| Skill | Good For Learning |
|-------|-------------------|
| `ar_ops/SKILL.md` | Complex skill with SQL, workflows |
| `invoice/SKILL.md` | Approval workflows |
| `general/SKILL.md` | Simple fallback pattern |
| `weather/SKILL.md` | External API pattern |
| `dilo/SKILL.md` | Time logging, user data |
| `parallel_report/SKILL.md` | Parallel execution with dependencies |
| `supervisor_report/SKILL.md` | Supervisor orchestration pattern |
| `p2p_consultant/SKILL.md` | Full enterprise skill with context_file |
| `ccdops/SKILL.md` | Live API calls via context file |

---

## Part 5: Execution Modes — Parallel and Supervisor

By default every skill runs as a single ReAct agent (`execution_mode: react`). For tasks that need multiple sub-agents working together, two additional modes are available.

### Parallel Mode

Runs multiple skills concurrently in waves. Steps without `depends_on` run at the same time. Steps with `depends_on` wait for their dependencies and receive their output via `{{step_name.output}}`.

```yaml
---
name: weekly_finance_report
version: "1.0"
description: "Runs AR and Invoice analysis in parallel then writes combined report"
keywords:
  - weekly report
  - finance report
execution_mode: parallel
steps:
  # Wave 1 — these two run at the same time
  - name: ar_summary
    action: skill
    skill: ar_ops
    task: "Summarise total receivables, DSO, and top 3 aging buckets"

  - name: invoice_summary
    action: skill
    skill: invoice_processing_ap
    task: "List the top 5 pending invoices by amount with vendor names"

  # Wave 2 — waits for both above, receives their output
  - name: combined_report
    action: skill
    depends_on: [ar_summary, invoice_summary]
    skill: general
    task: |
      Write an executive summary combining:
      AR Data: {{ar_summary.output}}
      Invoice Data: {{invoice_summary.output}}
---
```

**When to use:** Any report or analysis that pulls from multiple independent data sources. Wave 1 cuts total runtime vs sequential execution.

---

### Supervisor Mode

A supervisor agent orchestrates a set of worker skills. Each worker runs the full ReAct loop with its own LLM calls, then returns results to the supervisor which writes the final output.

```yaml
---
name: ops_health_check
version: "1.0"
description: "Supervisor that gathers data from multiple domain agents and writes a report"
keywords:
  - ops report
  - health check
execution_mode: supervisor
worker_skills:
  - name: ar_ops
    task: "Generate a concise AR summary with total receivables and top overdue customers. Output directly without asking questions."
  - name: it_helpdesk
    task: "List the top 3 open IT issues by severity. Output directly."
  - name: general
    task: "Provide a brief operational status and any recommended actions. Output directly."
---
```

**When to use:** Complex reports where each section requires domain-specific reasoning, not just data retrieval. Each worker agent has its own skill context and tool access.

**Parallel vs Supervisor:**

| | Parallel | Supervisor |
|---|---|---|
| LLM at each step | No — deterministic routing | Yes — each worker is a full ReAct agent |
| Inter-step data | Via `{{step.output}}` template | Supervisor agent synthesises |
| Best for | Speed — independent data collection | Quality — reasoning at every step |

---

## Part 6: Context Files — Giving Skills Domain Knowledge

A context file is a markdown document loaded into the skill's system prompt at runtime. It's how you inject your organisation's policies, procedures, terminology, and reference data without touching the model or the code.

### Creating a context file

```bash
# Place it in the shared contexts folder
touch enterprise_root/tenants/company/shared/contexts/procurement_context.md
```

```markdown
# Procurement Domain Context

## Approval Thresholds
- Under £5,000: Line manager approval
- £5,000–£50,000: Finance Director approval
- Over £50,000: Board approval required

## Approved Vendor List
- Office supplies: Acme Supplies (VND-001), Northwind Stationery (VND-002)
- IT hardware: TechParts International (VND-010), Lenora Systems (VND-011)

## Key Contacts
- Procurement lead: Sarah Chen (sarah.chen@company.com)
- Finance sign-off: James Okafor (j.okafor@company.com)

## Standard Payment Terms
Net 30 for all UK vendors. Net 45 for international.
```

### Wiring the context file to a skill

In your `SKILL.md` frontmatter, add the `context_file` field:

```yaml
---
name: procurement
version: "1.0"
description: "Purchase order and vendor management"
keywords:
  - purchase order
  - vendor
  - procurement
context_file: shared/contexts/procurement_context.md   # ← loaded into every prompt
tools:
  - shell
  - write_file
---
```

The full file content is prepended to the agent's system prompt every time this skill is active. **Update the file → the next load picks up the change** (mtime cache in `SkillLoader`). No server restart is required for edits to an already registered skill's `SKILL.md`.

### Context file vs /local/ documents

| Context file | /local/ documents |
|---|---|
| Injected into every prompt automatically | Agent searches on demand (grep / file_explorer) |
| Best for: policies, thresholds, key contacts, terminology | Best for: large process docs, SAP exports, reference libraries |
| Keep under ~2,000 words | No size limit |

---

## Part 7: Cron Jobs — Scheduling Skills to Run Automatically

Any skill can be scheduled to run on a timetable with no user present. Output is written to files under the scheduler user's `/me/` folder.

### Via the UI

1. Open `http://localhost:8080` → **Skill Builder** tab → **Cron Jobs** section
2. Click **New Job**
3. Fill in: skill name, task description, cron schedule
4. Enable → Save

### Via the API

```bash
curl -X POST http://localhost:8080/api/cron \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Daily AR Aging Report",
    "skill_name": "ar_ops",
    "task": "Generate the daily AR aging report and save to /me/reports/ar_aging_$(date +%Y-%m-%d).md",
    "cron": "0 8 * * 1-5",
    "description": "Runs weekdays at 8am",
    "enabled": true,
    "tags": ["reports", "daily"],
    "max_runtime_seconds": 300
  }'
```

### Common cron expressions

| Schedule | Expression |
|---|---|
| Every day at 8am | `0 8 * * *` |
| Weekdays at 9am | `0 9 * * 1-5` |
| Every Monday at 6am | `0 6 * * 1` |
| Every 4 hours | `0 */4 * * *` |
| Every 30 minutes | `*/30 * * * *` |

### Where output goes

Cron jobs run as the `scheduler` user. Output files appear at:
```
enterprise_root/tenants/company/agents/enterprise_agent/users/scheduler/
├── reports/
│   └── ar_aging_2026-04-13.md
└── tasks/
    └── writeoff_batch_2026-04-13.md
```

Retrieve them via the File Explorer tab in the UI or `GET /api/files`.

---

## Part 8: Hook System — Running Scripts Around Tool Calls

Hooks let you run shell scripts before or after tool calls without touching agent code. Configured in the agent's `config.yaml`.

### Hook types

| Hook | When it fires | Can block? |
|---|---|---|
| `PreToolUse` | Before every tool call | Yes — exit 1 blocks the call |
| `PostToolUse` | After every tool call completes | No |
| `PostTurn` | After the full agent response is sent | No |

### Example: audit every shell command for a skill

```yaml
# enterprise_root/tenants/company/agents/enterprise_agent/config.yaml

hooks:
  PreToolUse:
    - command: python3 /shared/hooks/audit_tool.py
      matcher: shell          # only fires on shell tool calls
      skills:
        - ccdops              # only fires when ccdops skill is active
      timeout_seconds: 5
      block_on_nonzero: false # log but don't block

  PostToolUse:
    - command: python3 /shared/hooks/alert_on_oom.py
      matcher: shell
      skills:
        - ccdops
      timeout_seconds: 5

  PostTurn:
    - command: bash /shared/hooks/add_disclaimer.sh
      skills:
        - ccdops
      timeout_seconds: 5
      block_on_nonzero: false
```

### Example: block dangerous kubectl commands

```yaml
hooks:
  PreToolUse:
    - command: >
        echo "$IAF_TOOL_INPUT" | grep -qiE
        'kubectl (delete|drain|cordon|scale|patch)' && exit 1 || exit 0
      matcher: shell
      skills:
        - ccdops
      timeout_seconds: 5
      block_on_nonzero: true    # exit 1 = block the tool call entirely
```

### Environment variables available in hook scripts

| Variable | Value |
|---|---|
| `IAF_TOOL_NAME` | Name of the tool being called (`shell`, `run_sql_query`, etc.) |
| `IAF_TOOL_INPUT` | The full tool input as JSON string |
| `IAF_TOOL_OUTPUT` | Tool output (PostToolUse and PostTurn only) |
| `IAF_SKILL_NAME` | Currently active skill name |
| `IAF_USER_ID` | User ID of the session |
| `IAF_AGENT_ROOT` | Absolute path to the agent's root folder |

---

## Part 9: invoke_skill — One Skill Calling Another

Any skill can delegate work to another skill using the `invoke_skill` tool. This is how complex workflows compose simpler specialists without duplicating logic.

### Enable it in your skill

```yaml
---
name: finance_overview
tools:
  - shell
  - invoke_skill     # ← add this
  - write_file
---
```

### Using it in your skill's system prompt

```
When asked for a complete finance overview:
1. Use invoke_skill with target_skill="ar_ops" to get the AR summary
2. Use invoke_skill with target_skill="invoice_processing_ap" to get the invoice summary
3. Combine both results into a single report and write to /me/reports/finance_overview_<date>.md
```

### The tool call itself (what the agent does at runtime)

```python
invoke_skill(
    target_skill="ar_ops",
    task="Summarise total receivables by region for Q1 2026",
    context="Called from finance_overview skill"
)
```

**Depth limit:** Skills can call sub-skills which call sub-skills, but the chain is capped at 3 levels deep to prevent infinite loops.

**vs parallel mode:** Use `invoke_skill` inside a ReAct skill when you need conditional logic ("if AR balance > threshold, also call the dispute skill"). Use `execution_mode: parallel` when you always want the same fixed set of skills to run together.

---

## Part 10: Human-in-the-Loop — Approval Flows

For actions that need human sign-off before executing (writing files, sending data, executing destructive operations), the agent can pause and wait for approval.

### Enabling HITL for an agent

In `config.yaml`, set `require_confirmation: true` at the kernel level, or configure specific shell patterns that trigger a pause:

```yaml
# enterprise_root/tenants/company/agents/enterprise_agent/config.yaml

# Option A: UI toggle (user controls per session via the Approval toggle in chat)
# Nothing to configure — user flips the switch in the UI

# Option B: Block specific dangerous patterns always
hooks:
  PreToolUse:
    - command: >
        echo "$IAF_TOOL_INPUT" | grep -qiE
        'rm -rf|DROP TABLE|DELETE FROM' && exit 1 || exit 0
      matcher: shell
      block_on_nonzero: true
      timeout_seconds: 3
```

### What happens at runtime

```
Agent decides to write a file
        ↓
HITL gate checks: is human_approval on?
        ↓ Yes
Agent pauses — sends "awaiting approval" message
        ↓
UI shows Approve / Reject panel with the proposed command
        ↓
User clicks Approve → command executes, agent continues
User clicks Reject → command cancelled, agent notified
```

### Using the `request_human_approval` tool in a skill prompt

For explicit approval checkpoints inside a skill (not just tool-level gates):

```
When about to execute a payment batch:
1. Summarise what you are about to do
2. Call request_human_approval with reason="About to release payment batch of £X to Y vendors"
3. Wait for approval before proceeding
```

---

## Part 11: Building Skills Through Conversation — The Easiest Path

You don't have to write SKILL.md files by hand. The platform includes a built-in **Skill Builder agent** (`create_skill`) that builds skills for you through conversation. It accepts natural language descriptions, pasted meeting transcripts, uploaded documents, and existing process files — and produces a complete, working skill ready to go live.

This is the recommended path for anyone new to skill authoring, and for domain experts who know their process but don't want to write YAML.

---

### Starting the Skill Builder

Just type any of these in the chat:

```
"create a skill for AP invoice processing"
"build an agent for IT helpdesk queries"
"new skill — I want an agent that handles vendor disputes"
"create a skill from this meeting transcript: [paste text]"
"build a skill from the process docs in /local/HR Process Flows/"
"make a skill like p2p_consultant but for procurement"
```

The `create_skill` skill activates automatically on these triggers.

---

### What it can build from

| You provide | What happens |
|---|---|
| **A description in chat** | Agent asks 2–3 targeted questions, then drafts the full skill |
| **A pasted meeting transcript** | Agent extracts domain, actors, capabilities, and outputs from the text |
| **An uploaded document** (PDF, DOCX, XLSX, PPTX) | Agent converts it to markdown, reads it, builds skill around the content |
| **A folder of process files** | Agent runs the docs converter, reads Visio diagrams, Excel tables, Word docs |
| **An existing skill name** | Agent reads it and creates an enhanced or forked version |

---

### The conversation flow

```
You: "create a skill for weekly AR aging reports"
        ↓
Skill Builder asks up to 3 questions:
  - "Should it query the AR database directly, or read exported files?"
  - "Should it save the report as a file, or just display it?"
  - "Any specific aging buckets or thresholds to include?"
        ↓
Drafts complete SKILL.md — shows it in chat
        ↓
You: "looks good" / "add a capability for dispute tracking" / "make it parallel"
        ↓
[iterate as many times as needed]
        ↓
You: "save it"
        ↓
Saved to your personal workspace — live immediately for you only
        ↓
You: "submit for review"
        ↓
Sent to admin review queue — goes live for all users when approved
```

---

### Personal Skills — Your Private Workspace

Every user has a personal skills folder at `/me/skills/`. Skills saved here are:
- **Live immediately** — you can use them in chat right away
- **Private** — only you can see and use them
- **Iteratable** — keep refining through conversation before sharing

```
enterprise_root/tenants/company/agents/enterprise_agent/users/{your_user_id}/
└── skills/
    ├── _index.yaml             ← your personal skill registry
    └── weekly_ar_report/
        └── SKILL.md            ← your skill, visible only to you
```

When a personal skill is active in the router, the scope badge shows `personal` in the skills panel.

---

### Submitting for Review — Getting a Skill Published Globally

When you're happy with a personal skill and want everyone to use it:

**Option A — via the Skill Builder agent:**
```
"submit weekly_ar_report for review"
```
The agent copies it to the review queue and confirms submission.

**Option B — via the API:**
```bash
curl -X POST http://localhost:8080/api/personal-skills/{your_user_id}/weekly_ar_report/submit \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "company"}'
```

**Option C — via the Skill Builder UI tab:**
Open the Skills panel → My Skills → click **Submit for Review** next to the skill.

---

### The Three Scope States

Every skill has a scope that tracks where it is in the lifecycle:

```
personal   →   submitted   →   approved (live globally)
   │               │                    │
Only you     In admin review     All users can use it
can use it   queue               Router picks it up
```

The scope badge is visible in the Skills panel in the UI.

---

### Admin Review — Approving Submitted Skills

Admins see a review queue in the Skill Builder UI tab. For each submission they can:
- Read the full SKILL.md
- Approve → skill is copied to `IAF-Agent-Skills/skills/` and registered in the global `_index.yaml`. The registry file updates immediately, but **cached `SkillAgent` instances may still hold a stale router index** until the server restarts or those agents are evicted — plan for a restart (or new deployment) before telling all users the skill is routable everywhere.
- Reject with feedback → submitter is notified, can revise and resubmit

**Via API (admin):**
```bash
# Approve
curl -X POST http://localhost:8080/api/skill-submissions/{submission_id}/review \
  -H "Content-Type: application/json" \
  -d '{"action": "approve", "tenant_id": "company"}'

# Reject with feedback
curl -X POST http://localhost:8080/api/skill-submissions/{submission_id}/review \
  -H "Content-Type: application/json" \
  -d '{"action": "reject", "feedback": "Add more specific keywords for AP routing", "tenant_id": "company"}'
```

---

### Full Lifecycle at a Glance

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Skill Lifecycle                                       │
├──────────────────┬──────────────────┬──────────────────┬────────────────────┤
│   AUTHORING      │    PERSONAL      │    IN REVIEW     │   GLOBAL (LIVE)    │
│                  │                  │                  │                    │
│  Chat with       │  /me/skills/     │  shared/         │  IAF-Agent-Skills/ │
│  create_skill    │  {skill}/        │  skill_          │  skills/{skill}/   │
│  skill           │  SKILL.md        │  submissions/    │  SKILL.md          │
│                  │                  │                  │                    │
│  → iterate       │  scope:          │  scope:          │  scope:            │
│  → refine        │  "personal"      │  "submitted"     │  "approved"        │
│                  │                  │                  │                    │
│  Works from:     │  Only you        │  Admin reviews   │  All users,        │
│  chat / docs /   │  can use it      │  approve/reject  │  all agents        │
│  transcripts /   │                  │                  │                    │
│  existing skills │                  │                  │                    │
└──────────────────┴──────────────────┴──────────────────┴────────────────────┘
```

---

### Personal Skills API Reference

| Endpoint | Method | What it does |
|---|---|---|
| `/api/personal-skills/{username}` | GET | List all your personal skills with scope status |
| `/api/personal-skills/{username}/save` | POST | Save (create or update) a personal skill |
| `/api/personal-skills/{username}/{skill_name}/submit` | POST | Submit for admin review |
| `/api/personal-skills/{username}/{skill_name}` | DELETE | Delete a personal skill |
| `/api/skill-submissions` | GET | List all pending submissions (admin) |
| `/api/skill-submissions/{id}/review` | POST | Approve or reject a submission (admin) |

---

*Last updated: April 2026*
