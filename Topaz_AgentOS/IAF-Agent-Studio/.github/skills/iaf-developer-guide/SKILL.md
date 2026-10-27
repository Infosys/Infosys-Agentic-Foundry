# IAF Developer Guide

> **Purpose**: This skill enables LLM assistants (GitHub Copilot, Claude, etc.) to help developers create skills, agents, and all required configurations for the IAF Agent Platform.

## When to Use This Skill

Use this skill when the user asks to:
- Create a new skill for IAF
- Create a new agent
- Add a workflow or parallel skill
- Set up a supervisor agent
- Register skills or agents
- Configure database connections for skills

---

## Repository Structure

The IAF platform consists of three repositories:

```
IAF-Agent-Skills/           # Skills library (SKILL.md files)
├── skills/
│   ├── _index.yaml         # Skill registry
│   ├── {skill_name}/
│   │   └── SKILL.md        # Skill definition
│   └── ...
├── iaf_agent_skills/       # Core engine (don't modify)
└── DEVELOPER_QUICKSTART.md # Additional reference

IAF-Agent-Studio/           # Web UI & API server
├── server.py               # FastAPI backend
└── static/                 # Web interface

agent_os/                   # Kernel (rarely modified)
└── ...

enterprise_data/            # Runtime data (auto-created)
└── tenants/{tenant}/agents/{agent}/
    └── agent.yaml          # Agent configuration
```

---

## Part 1: Creating Skills

### Skill Types

| Type | Mode | Use Case |
|------|------|----------|
| **REACT** | `react` | General purpose, tool-using agent (default) |
| **WORKFLOW** | `workflow` | Sequential multi-step processes |
| **PARALLEL** | `parallel` | Fan-out/fan-in parallel execution |
| **SUPERVISOR** | `supervisor` | Orchestrate sub-skills with routing |

### Available Tools

Skills can use these tools (specify in `tools:` section):

| Tool | Purpose |
|------|---------|
| `shell` | File system operations (ls, cat, echo, mkdir, rm, grep, etc.) |
| `run_sql_query` | Execute SQL queries on configured databases |
| `execute_code` | Run Python/JavaScript code for calculations |

---

### Template: REACT Skill (Default)

Create file: `IAF-Agent-Skills/skills/{skill_name}/SKILL.md`

```markdown
---
name: {skill_name}
version: "1.0"
description: "{One-line description of what this skill does}"
triggers:
  - {keyword1}
  - {keyword2}
  - {phrase that should route to this skill}
tools:
  - shell
  - run_sql_query
business_context:
  domain: "{Domain like Finance, HR, Procurement}"
  process: "{Process like Invoice Processing, Payroll}"
  activities:
    - {Activity1}
    - {Activity2}
---

# {Skill Name} Agent

You are a {role description} responsible for {primary responsibility}.

## Your Capabilities

1. **{Capability 1}**: {Description}
2. **{Capability 2}**: {Description}
3. **{Capability 3}**: {Description}

## Business Rules

- {Rule 1}
- {Rule 2}
- {Rule 3}

## Response Format

Always structure your responses as:
1. **Understanding**: Confirm what the user is asking
2. **Action**: What you did or will do
3. **Result**: The outcome or findings
4. **Next Steps**: Recommended follow-up actions (if any)

## Examples

**User**: {Example query 1}
**You**: {Example response showing proper format}

**User**: {Example query 2}
**You**: {Example response}
```

---

### Template: WORKFLOW Skill

For sequential multi-step processes:

```markdown
---
name: {workflow_name}
version: "1.0"
description: "{Multi-step workflow description}"
mode: workflow
triggers:
  - {trigger1}
  - {trigger2}
tools:
  - shell
  - run_sql_query

workflow:
  steps:
    - name: step_1_name
      prompt: |
        {Instructions for step 1}
        Input: {{input}}
      output_key: step1_result
      
    - name: step_2_name  
      prompt: |
        {Instructions for step 2}
        Previous result: {{step1_result}}
      output_key: step2_result
      
    - name: final_step
      prompt: |
        {Instructions for final step}
        Data from step 1: {{step1_result}}
        Data from step 2: {{step2_result}}
      output_key: final_output
---

# {Workflow Name}

This workflow executes a {N}-step process for {purpose}.

## Steps Overview

1. **{Step 1}**: {What it does}
2. **{Step 2}**: {What it does}
3. **{Final Step}**: {What it produces}
```

---

### Template: PARALLEL Skill

For fan-out/fan-in parallel execution:

```markdown
---
name: {parallel_name}
version: "1.0"
description: "{Parallel execution description}"
mode: parallel
triggers:
  - {trigger1}
  - parallel {something}
  - concurrent {something}
tools:
  - shell
  - run_sql_query

parallel:
  fan_out:
    - name: task_a
      prompt: |
        {Instructions for parallel task A}
        Input: {{input}}
      output_key: result_a
      
    - name: task_b
      prompt: |
        {Instructions for parallel task B}
        Input: {{input}}
      output_key: result_b
      
    - name: task_c
      prompt: |
        {Instructions for parallel task C}
        Input: {{input}}
      output_key: result_c
      
  fan_in:
    prompt: |
      Combine and synthesize these parallel results:
      
      Task A Result: {{result_a}}
      Task B Result: {{result_b}}
      Task C Result: {{result_c}}
      
      Provide a unified summary.
    output_key: combined_result
---

# {Parallel Skill Name}

Executes {N} tasks in parallel and combines results.

## Parallel Tasks

| Task | Purpose |
|------|---------|
| task_a | {Description} |
| task_b | {Description} |
| task_c | {Description} |
```

---

### Template: SUPERVISOR Skill

For orchestrating multiple sub-skills:

```markdown
---
name: {supervisor_name}
version: "1.0"
description: "{Supervisor description}"
mode: supervisor
triggers:
  - {trigger1}
  - {trigger2}

supervisor:
  sub_skills:
    - skill_name_1
    - skill_name_2
    - skill_name_3
  
  routing_prompt: |
    You are a supervisor that routes requests to the appropriate sub-skill.
    
    Available sub-skills:
    - **skill_name_1**: {When to use}
    - **skill_name_2**: {When to use}
    - **skill_name_3**: {When to use}
    
    Analyze the user's request and determine which sub-skill should handle it.
    You may call multiple sub-skills if the request requires it.
    
  synthesis_prompt: |
    Combine the results from sub-skills into a coherent response.
    Ensure the response directly addresses the user's original question.
---

# {Supervisor Name}

Orchestrates requests across multiple specialized skills.

## Sub-Skills

| Skill | Responsibility |
|-------|---------------|
| skill_name_1 | {What it handles} |
| skill_name_2 | {What it handles} |
| skill_name_3 | {What it handles} |
```

---

## Part 2: Registering Skills

After creating a SKILL.md file, register it in `IAF-Agent-Skills/skills/_index.yaml`:

```yaml
# Add your skill to this file
skills:
  - name: existing_skill_1
    path: existing_skill_1/SKILL.md
    
  - name: your_new_skill        # Add this entry
    path: your_new_skill/SKILL.md
```

**Important**: The `name` must match the `name:` field in your SKILL.md frontmatter.

---

## Part 3: Creating Agents

Agents are configurations that bundle skills together for a specific use case.

### Agent Configuration Location

```
enterprise_data/tenants/{tenant}/agents/{agent_name}/agent.yaml
```

Default tenant: `company`

### Template: Agent Configuration

Create file: `enterprise_data/tenants/company/agents/{agent_name}/agent.yaml`

```yaml
name: {agent_name}
display_name: "{Human-Readable Agent Name}"
description: "{What this agent does}"
version: "1.0"

# Skills this agent can use (must exist in skills/_index.yaml)
skills:
  - skill_name_1
  - skill_name_2
  - skill_name_3

# Tool permissions (which tools skills can use)
tools:
  allowed:
    - shell
    - run_sql_query
    - execute_code

# LLM configuration
llm:
  provider: azure_openai  # or openai, anthropic
  model: gpt-4o
  temperature: 0.7
  max_tokens: 4096

# Memory settings
memory:
  enabled: true
  history_depth: 10
  
# Business context
context:
  tenant: company
  department: "{Department}"
  role: "{Agent's role}"
```

---

## Part 4: Database Configuration (for run_sql_query)

If your skill uses `run_sql_query`, configure database connections:

### Location

```
enterprise_data/tenants/{tenant}/databases/
├── {db_name}.yaml
└── ...
```

### Template: Database Config

```yaml
name: {db_name}
type: sqlite  # or postgresql, mysql, mssql
description: "{What data this database contains}"

# For SQLite
connection:
  path: "path/to/database.db"

# For PostgreSQL/MySQL
# connection:
#   host: localhost
#   port: 5432
#   database: mydb
#   username: user
#   password_env: DB_PASSWORD  # Use env var for secrets

# Table descriptions (helps LLM understand schema)
tables:
  - name: table_name
    description: "{What this table contains}"
    columns:
      - name: column1
        type: TEXT
        description: "{Column purpose}"
      - name: column2
        type: INTEGER
        description: "{Column purpose}"
```

---

## Part 5: Complete Example

### Creating an HR Operations Skill + Agent

**Step 1**: Create skill file

`IAF-Agent-Skills/skills/hr_ops/SKILL.md`:

```markdown
---
name: hr_ops
version: "1.0"
description: "HR operations - employee data, leave management, onboarding"
triggers:
  - employee
  - leave
  - vacation
  - onboarding
  - hr
  - benefits
tools:
  - shell
  - run_sql_query
business_context:
  domain: "Human Resources"
  process: "Employee Management"
  activities:
    - EmployeeLookup
    - LeaveManagement
    - OnboardingTracking
---

# HR Operations Agent

You are an HR Operations specialist responsible for employee data management, leave tracking, and onboarding assistance.

## Your Capabilities

1. **Employee Lookup**: Find employee information by name, ID, or department
2. **Leave Management**: Check leave balances, pending requests, approve/deny workflow
3. **Onboarding Status**: Track new hire onboarding progress
4. **Benefits Queries**: Answer questions about benefits enrollment

## Business Rules

- Never expose salary information without manager approval
- Leave requests over 5 days require manager + HR approval
- All employee data access is logged for compliance

## Response Format

1. **Understanding**: Confirm the HR request
2. **Action**: Query performed or action taken
3. **Result**: Findings with relevant data
4. **Next Steps**: Required approvals or follow-up actions
```

**Step 2**: Register skill

Add to `IAF-Agent-Skills/skills/_index.yaml`:

```yaml
skills:
  - name: hr_ops
    path: hr_ops/SKILL.md
```

**Step 3**: Create agent

`enterprise_data/tenants/company/agents/hr_assistant/agent.yaml`:

```yaml
name: hr_assistant
display_name: "HR Assistant"
description: "AI assistant for HR operations and employee queries"
version: "1.0"

skills:
  - hr_ops
  - general  # Include general skill as fallback

tools:
  allowed:
    - shell
    - run_sql_query

llm:
  provider: azure_openai
  model: gpt-4o
  temperature: 0.3  # Lower for more consistent HR responses

memory:
  enabled: true
  history_depth: 5

context:
  tenant: company
  department: "Human Resources"
  role: "HR Operations Assistant"
```

**Step 4**: (Optional) Create database config

`enterprise_data/tenants/company/databases/hr_db.yaml`:

```yaml
name: hr_db
type: sqlite
description: "HR database with employee and leave data"
connection:
  path: "enterprise_data/tenants/company/data/hr.db"
tables:
  - name: employees
    description: "Employee master data"
    columns:
      - name: emp_id
        type: TEXT
        description: "Unique employee ID"
      - name: name
        type: TEXT
        description: "Full name"
      - name: department
        type: TEXT
        description: "Department name"
      - name: hire_date
        type: DATE
        description: "Date of joining"
  - name: leave_requests
    description: "Leave request records"
    columns:
      - name: request_id
        type: TEXT
        description: "Unique request ID"
      - name: emp_id
        type: TEXT
        description: "Employee who requested"
      - name: start_date
        type: DATE
        description: "Leave start date"
      - name: end_date
        type: DATE
        description: "Leave end date"
      - name: status
        type: TEXT
        description: "pending/approved/denied"
```

---

## Part 6: Testing Your Skill

### Via API (Recommended)

```bash
# Start the server
cd IAF-Agent-Studio && python3 server.py

# Test skill invocation
curl -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Show me employee John Smith details",
    "agent_id": "hr_assistant",
    "user_id": "developer"
  }'
```

### Via Web UI

1. Open http://localhost:8080
2. Select your agent from the dropdown
3. Type a query that matches your skill's triggers
4. Verify the correct skill is invoked

---

## Part 7: Git Workflow

After creating skills and agents:

```bash
# For skills (IAF-Agent-Skills repo)
cd IAF-Agent-Skills
git add skills/{skill_name}/SKILL.md skills/_index.yaml
git commit -m "Add {skill_name} skill"
git push origin main

# For agents (enterprise_data is typically gitignored)
# But you can version agent configs if needed:
git add enterprise_data/tenants/company/agents/{agent_name}/agent.yaml
git commit -m "Add {agent_name} agent configuration"
```

---

## Quick Reference

### Skill Creation Checklist

- [ ] Create `skills/{name}/SKILL.md` with proper frontmatter
- [ ] Set `name:` field matching folder name
- [ ] Define `triggers:` for skill routing
- [ ] Specify `tools:` (shell, run_sql_query, execute_code)
- [ ] Add `business_context:` for domain info
- [ ] Write clear instructions in markdown body
- [ ] Register in `_index.yaml`
- [ ] Test with matching query

### Agent Creation Checklist

- [ ] Create agent folder in `enterprise_data/tenants/{tenant}/agents/{name}/`
- [ ] Create `agent.yaml` with required fields
- [ ] List skills (must exist in _index.yaml)
- [ ] Configure tool permissions
- [ ] Set LLM parameters
- [ ] Test via API or UI

### Tool Name Reference

| Tool | Alias | Function |
|------|-------|----------|
| `shell` | ❌ no alias | Execute shell commands (ls, cat, grep, etc.) |
| `run_sql_query` | ❌ no alias | Query configured databases |
| `execute_code` | ❌ no alias | Run Python/JS code |

**Note**: Do not use `fs` - it's not a valid tool name. Use `shell` instead.

---

## Troubleshooting

### Skill Not Found
- Check `_index.yaml` has the skill registered
- Verify `name:` in SKILL.md matches _index.yaml entry
- Ensure SKILL.md frontmatter is valid YAML (use `---` delimiters)

### Skill Not Routing
- Add more specific triggers
- Check query contains trigger words
- Test with exact trigger phrase

### Tool Errors
- Verify tool name is exact (`shell` not `fs`)
- Check tool is in skill's `tools:` list
- Ensure agent's `tools.allowed:` includes the tool

### Database Query Fails
- Verify database config exists in `databases/` folder
- Check connection path is correct
- Ensure tables/columns match actual schema
