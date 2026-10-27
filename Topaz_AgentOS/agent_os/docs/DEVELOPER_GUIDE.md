# AgentOS Framework - Developer Guide

## Quick Start (5 minutes)

### Step 1: Install or copy the kernel

Preferred install:

```bash
pip install agentos-kernel
```

For local source-tree development you can still copy the `agent_os` folder:

```
your_project/
├── agent_os/           ← Copy this folder
│   ├── __init__.py
│   ├── kernel.py
│   ├── safe_path.py
│   ├── vector_store.py
│   ├── prompts.py
│   └── tools.py
└── your_agent.py
```

### Step 2: Install dependencies

```bash
pip install langgraph langchain-openai
```

LangGraph/LangChain are agent-framework dependencies for this example, not
kernel dependencies. The core `agentos-kernel` package is stdlib-only; use
`agentos-kernel[credentials]` for YAML/Fernet credential-store backends and
`agentos-kernel[self-auth]` for service JWT minting.

### Step 3: Create your agent (minimal example)

```python
from pathlib import Path
from langchain_openai import AzureChatOpenAI
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

# Import AgentOS
from agent_os import SafeKernel
from agent_os.prompts import SYSTEM_PROMPT_TEMPORAL

# 1. Initialize the kernel (creates folder structure)
kernel = SafeKernel(
    data_root="./agent_data",      # Where to store files
    tenant_id="my_company",         # Organization ID
    agent_id="support_agent"        # This agent's ID
)

# 2. Create the tool that wraps the kernel
@tool
def run_shell_command(command: str) -> str:
    """Execute a command in the agent's secure shell environment.
    
    Commands: ls, cat, grep, find, echo, semgrep (semantic search)
    Directories:
    - /shared/ : READ-ONLY company knowledge
    - /workspace/ : Scratchpad for current task
    - /memory/ : Persistent memory (auto-indexed)
    """
    return kernel.run_shell_command(command)

# 3. Create your LLM
llm = AzureChatOpenAI(
    azure_endpoint="https://your-resource.openai.azure.com/",
    api_key="your-api-key",
    azure_deployment="gpt-4o",
    api_version="2024-08-01-preview"
)

# 4. Create the agent with filesystem prompt
from datetime import datetime
today = datetime.now().strftime("%Y-%m-%d")

system_prompt = SYSTEM_PROMPT_TEMPORAL + f"""
## Today's Context
- Current date: {today}
- Session folder: /memory/recent/{today}/
"""

agent = create_react_agent(llm, [run_shell_command], prompt=system_prompt)

# 5. Use the agent
result = agent.invoke({"messages": [("user", "What is our refund policy?")]})
print(result["messages"][-1].content)
```

---

## What You Get

### Folder Structure (auto-created)
```
agent_data/
├── tenants/my_company/
│   ├── shared/              ← Put company docs here (READ-ONLY for agent)
│   │   ├── policies/
│   │   └── knowledge/
│   └── agents/support_agent/
│       ├── workspace/       ← Agent's scratchpad
│       ├── memory/          ← Persistent memory
│       │   ├── current/     ← Active session context
│       │   ├── recent/      ← Last 7 days (by date)
│       │   └── entities/    ← Users, companies
│       └── .index/          ← Vector store for semgrep
└── global_shared/           ← Cross-tenant docs
```

### Security Features (built-in)
- ✅ Path traversal blocked (`..` not allowed)
- ✅ Dangerous commands blocked (`rm`, `sudo`, `wget`, `python`)
- ✅ Command chaining blocked (`&&`, `||`, `;`, `|`)
- ✅ Read-only enforcement for `/shared/`
- ✅ Sandboxed to agent's folder

### Available Commands
| Command | Example | Description |
|---------|---------|-------------|
| `ls` | `ls -la /shared/` | List directory |
| `cat` | `cat /shared/policies/refund.md` | Read file |
| `grep` | `grep -r "discount" /shared/` | Text search |
| `find` | `find /memory -name "*.md"` | Find files |
| `echo` | `echo "note" > /memory/facts/note.md` | Write file |
| `semgrep` | `semgrep "customer preferences"` | Semantic search |
| `head/tail` | `head -n 20 /shared/log.txt` | Read partial |
| `tree` | `tree /memory` | Directory tree |

---

## Customization

### Option A: Use built-in prompts

```python
from agent_os.prompts import (
    SYSTEM_PROMPT_MINIMAL,         # Basic agent
    SYSTEM_PROMPT_WITH_USER_MEMORY, # User data + preferences
    SYSTEM_PROMPT_TEMPORAL,         # Multi-session with dates
    SYSTEM_PROMPT_CUSTOMER_SERVICE  # Support agent pattern
)

system_prompt = SYSTEM_PROMPT_CUSTOMER_SERVICE
```

### Option B: Define your own folder schema

```python
system_prompt = """You have a filesystem-based memory.

## Your Directories
/shared/           - Company knowledge (READ-ONLY)
/workspace/        - Current task scratchpad
/memory/
├── customers/     - Customer profiles (one file per customer)
├── tickets/       - Support ticket history
├── templates/     - Response templates you've learned
└── insights/      - Patterns you've discovered

## Key behaviors
- When a customer contacts you, check /memory/customers/{customer_id}.md
- Log tickets to /memory/tickets/{date}_{ticket_id}.md
- Use semgrep to find similar past issues
"""
```

The LLM will naturally organize data based on your folder schema.

### Option C: Pre-populate shared data

```python
# Before creating the agent, add company docs
from pathlib import Path

shared = Path("./agent_data/tenants/my_company/shared")
(shared / "policies").mkdir(parents=True, exist_ok=True)
(shared / "policies" / "refund.md").write_text("""
# Refund Policy
- 30 days for physical products
- 14 days for digital products
""")
```

---

## Multi-Agent Setup

Each agent gets its own isolated memory:

```python
# Support agent
support_kernel = SafeKernel(
    data_root="./agent_data",
    tenant_id="my_company",
    agent_id="support_agent"
)

# Sales agent (separate memory, same shared docs)
sales_kernel = SafeKernel(
    data_root="./agent_data",
    tenant_id="my_company",
    agent_id="sales_agent"
)
```

Both agents can read `/shared/` but have separate `/memory/` and `/workspace/`.

---

## Best Practices

### 1. Let the LLM explore first
Don't pre-load context. Let the agent use `ls` and `cat` to discover what's available.

### 2. Use semgrep for retrieval
```python
# In your prompt, guide the agent:
"Before answering questions about past interactions, use: semgrep 'customer complaint about shipping'"
```

### 3. Temporal organization
For multi-session agents, use date-based folders:
```
/memory/recent/2026-01-12/session_summary.md
/memory/recent/2026-01-11/decisions.md
```

### 4. Entity-based organization
For customer-facing agents:
```
/memory/entities/customers/john_smith.md
/memory/entities/companies/acme_corp.md
```

---

## Semantic Layer Pattern (SQL Agents, Analytics)

AgentOS natively supports the "filesystem as semantic layer" pattern popularized by Vercel's analytics agents. **No additional code needed** - just organize your documentation as files.

### The Insight

> "We were building tools to summarize what was already legible. Claude just needed access to read it directly."
> — Vercel Engineering

Instead of building custom tools to summarize schemas, search columns, or generate queries, **let the LLM read your documentation directly** using standard commands.

### How It Works

```
/shared/semantic/                    ← Your semantic layer (read-only)
  ├── dimensions/                    ← Table/column definitions
  │   ├── users.yaml                 
  │   ├── products.yaml              
  │   └── events.yaml                
  ├── measures/                      ← Calculated metrics
  │   ├── revenue.yaml               # SUM(price * qty)
  │   ├── dau.yaml                   # COUNT(DISTINCT user_id)
  │   └── retention.yaml             
  ├── joins/                         ← Relationship definitions
  │   └── relationships.yaml         
  └── examples/                      ← Example queries
      ├── query_dau.sql              
      └── query_revenue.sql          
```

### Agent Workflow (Automatic)

```bash
# 1. Agent explores available concepts
ls /shared/semantic/
# → dimensions/  measures/  joins/  examples/

# 2. Agent reads definitions
cat /shared/semantic/measures/revenue.yaml
# → name: total_revenue
#   formula: SUM(orders.amount)
#   dimensions: [date, product_category]

# 3. Agent searches for relevant concepts
grep -r "user" /shared/semantic/dimensions/
# → users.yaml: user_id, email, plan_type...

# 4. Agent learns from examples
cat /shared/semantic/examples/query_dau.sql
# → SELECT date, COUNT(DISTINCT user_id) FROM events...

# 5. Agent writes correct SQL based on understanding
```

### Example: Analytics Agent

```python
from agent_os import SafeKernel

kernel = SafeKernel(
    data_root="./analytics_data",
    tenant_id="company",
    agent_id="sql_agent"
)

@tool
def run_shell_command(command: str) -> str:
    """Browse semantic layer with ls, cat, grep, find, semgrep."""
    return kernel.run_shell_command(command)

@tool
def execute_sql(query: str) -> str:
    """Execute SQL against data warehouse."""
    return your_db.execute(query).to_markdown()

system_prompt = """You are a data analyst.

## Knowledge Base
/shared/semantic/dimensions/  - Table definitions
/shared/semantic/measures/    - Metric formulas  
/shared/semantic/joins/       - Table relationships
/shared/semantic/examples/    - Example SQL queries

## Workflow
1. FIRST explore semantic layer with ls, cat, grep
2. Read relevant dimension/measure definitions
3. Check examples/ for query patterns
4. Write and execute SQL

Never guess column names - always verify by reading definitions first.
"""
```

### Why This Works

| Traditional Approach | AgentOS Approach |
|---------------------|------------------|
| Build schema summarizer tool | `cat /shared/semantic/dimensions/users.yaml` |
| Build column search tool | `grep -r "revenue" /shared/semantic/` |
| Build query generator | Let LLM write SQL after reading docs |
| Maintain tool documentation | Files ARE the documentation |

### File Format Recommendations

**dimensions/users.yaml** (example):
```yaml
table: users
description: User accounts and profile data
primary_key: user_id
columns:
  - name: user_id
    type: UUID
    description: Unique user identifier
  - name: created_at
    type: TIMESTAMP
    description: Account creation time
  - name: plan_type
    type: ENUM(free, pro, enterprise)
    description: Current subscription tier
```

**measures/dau.yaml** (example):
```yaml
name: daily_active_users
abbreviation: DAU
description: Count of unique users with at least one event per day
formula: COUNT(DISTINCT user_id)
source_table: events
dimensions:
  - date
  - platform
example_query: |
  SELECT date, COUNT(DISTINCT user_id) as dau
  FROM events
  WHERE date = CURRENT_DATE
  GROUP BY date
```

### Key Principle

> **Don't build tools to summarize your data model. If your documentation is good, just give the LLM filesystem access.**

The LLM will:
1. **Explore** with `ls`
2. **Read** with `cat`
3. **Search** with `grep` / `semgrep`
4. **Build mental models** from documentation
5. **Execute** accurate SQL/queries

---

## Role-Based Access Control (RBAC)

AgentOS supports multi-user scenarios with role-based access control. Use this when:
- Multiple users interact with the same agent
- Managers need to review team members' data
- Auditors need read-only access for compliance

### User Roles

| Role | Own Folder | Team Folders | All Users | Write Access |
|------|------------|--------------|-----------|--------------|
| `user` | ✅ RW | ❌ | ❌ | Own folder only |
| `manager` | ✅ RW | ✅ RW | ❌ | Own + team |
| `admin` | ✅ RW | ✅ RW | ✅ RW | Everywhere |
| `auditor` | ✅ R | ✅ R | ✅ R | None (read-only) |

### Basic Usage

```python
from agent_os import SafeKernel, UserRole

# Simple user - can only access their own folder
kernel = SafeKernel(
    data_root="./data",
    tenant_id="company",
    agent_id="dilo_agent",
    user_id="john_smith",       # Logged-in user
    user_role=UserRole.USER     # Their role
)

# This works - own folder
kernel.run_shell_command('echo "my data" > /me/notes.md')

# This fails - other user's folder
kernel.run_shell_command('cat /users/jane_doe/notes.md')
# Error: ACCESS_DENIED
```

### Path Shortcuts

| Shortcut | Expands To | Example |
|----------|-----------|---------|
| `/me/` | `/users/{user_id}/` | `/me/profile.md` → `/users/john_smith/profile.md` |
| `/team/` | `/teams/{team_id}/` | `/team/goals.md` → `/teams/engineering/goals.md` |

### Team Resolution Options

#### Option A: Static List (Simple)

```python
# Pass list of team members directly
kernel = SafeKernel(
    data_root="./data",
    tenant_id="company",
    agent_id="dilo_agent",
    user_id="john_manager",
    user_role=UserRole.MANAGER,
    managed_users=["jane_doe", "bob_wilson", "alice_chen"]
)

# Manager can now access team folders
kernel.run_shell_command("cat /users/jane_doe/dilo.md")  # ✅ Works
```

#### Option B: JSON File (Self-Service)

Create a `teams.json` file:
```json
{
  "teams": {
    "engineering": {
      "manager": "john_manager",
      "members": ["jane_doe", "bob_wilson"]
    },
    "sales": {
      "manager": "mary_sales",
      "members": ["tom_rep", "lisa_rep"]
    }
  }
}
```

Then use it:
```python
kernel = SafeKernel(
    data_root="./data",
    tenant_id="company",
    agent_id="dilo_agent",
    user_id="john_manager",
    user_role=UserRole.MANAGER,
    team_file_path="./teams.json"
)
```

The file is cached for 5 minutes and auto-reloaded on changes.

#### Option C: External Callback (Enterprise Integration)

For LDAP/Active Directory/custom DB integration:
```python
def ldap_team_resolver(user_id: str, team_id: str) -> list:
    """Query LDAP for user's direct reports."""
    import ldap
    # Your LDAP query here...
    return ["jane_doe", "bob_wilson"]

kernel = SafeKernel(
    data_root="./data",
    tenant_id="company",
    agent_id="dilo_agent",
    user_id="john_manager",
    user_role=UserRole.MANAGER,
    team_resolver_callback=ldap_team_resolver
)
```

### Complete RBAC Example: DILO Agent

```python
from datetime import datetime
from langchain_openai import AzureChatOpenAI
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from agent_os import SafeKernel, UserRole

def create_dilo_agent(user_id: str, user_role: str, team_id: str = None, managed_users: list = None):
    """Create a DILO agent for a specific user."""
    
    # Convert role string to UserRole
    role_map = {
        "user": UserRole.USER,
        "manager": UserRole.MANAGER,
        "admin": UserRole.ADMIN,
        "auditor": UserRole.AUDITOR
    }
    
    kernel = SafeKernel(
        data_root="./dilo_data",
        tenant_id="company",
        agent_id="dilo_agent",
        user_id=user_id,
        user_role=role_map.get(user_role, UserRole.USER),
        team_id=team_id,
        managed_users=managed_users or []
    )
    
    @tool
    def run_shell_command(command: str) -> str:
        """Execute command in user's secure environment."""
        return kernel.run_shell_command(command)
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    system_prompt = f"""You are a DILO (Day in Life Of) assistant.

## User Context
- User ID: {user_id}
- Role: {user_role}
- Today: {today}

## Directories
- /me/          - Your personal folder (profile, preferences, DILO logs)
- /me/dilo/     - Your daily activity logs
- /team/        - Team shared folder (if team_id set)
- /workspace/   - Scratchpad
- /memory/      - Agent-wide memory

## As {user_role}:
{"- You can view your team members' /users/{{member}}/ folders" if user_role == "manager" else ""}
{"- You can view all /users/ folders" if user_role in ("admin", "auditor") else ""}
{"- You have READ-ONLY access everywhere" if user_role == "auditor" else ""}

## DILO Format
Save activities to: /me/dilo/{today}.md
Format:
| Time | Category | Activity |
|------|----------|----------|
| 2.0h | Meeting  | Sprint planning |
"""
    
    llm = AzureChatOpenAI(...)  # Your config
    return create_react_agent(llm, [run_shell_command], prompt=system_prompt)

# Usage - simulate user login
user_info = get_user_from_login()  # Your auth system

agent = create_dilo_agent(
    user_id=user_info["id"],           # "john_smith"
    user_role=user_info["role"],       # "manager"
    team_id=user_info["team"],         # "engineering"
    managed_users=user_info["reports"] # ["jane", "bob"]
)

result = agent.invoke({"messages": [("user", "Log 3 hours of coding today")]})
```

### Folder Structure with RBAC

```
agent_data/
├── tenants/company/agents/dilo_agent/
│   ├── users/                      ← Per-user folders (RBAC controlled)
│   │   ├── john_smith/
│   │   │   ├── profile.md          ← Auto-created
│   │   │   ├── preferences.md
│   │   │   └── dilo/
│   │   │       └── 2026-01-12.md
│   │   ├── jane_doe/
│   │   └── bob_wilson/
│   ├── teams/                      ← Team folders
│   │   └── engineering/
│   │       └── goals.md
│   ├── workspace/                  ← Shared agent workspace
│   └── memory/                     ← Shared agent memory
└── global_shared/
```

---

## Troubleshooting

### "Command chaining not allowed"
The agent tried `ls && cat` or `ls || true`. This is blocked for security.
**Solution**: Run commands one at a time.

### "Permission denied" on /shared/
The agent tried to write to a read-only directory.
**Solution**: Write to `/memory/` or `/workspace/` instead.

### Semgrep returns no results
The vector store is empty or no relevant content indexed.
**Solution**: Write more content to `/memory/` - it auto-indexes.

---

## Full Example: Customer Service Agent

```python
from datetime import datetime
from pathlib import Path
from langchain_openai import AzureChatOpenAI
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from agent_os import SafeKernel
from agent_os.prompts import SYSTEM_PROMPT_CUSTOMER_SERVICE

# Setup
kernel = SafeKernel(
    data_root="./cs_agent_data",
    tenant_id="acme_corp",
    agent_id="cs_agent_01"
)

# Pre-populate company knowledge
shared = Path("./cs_agent_data/tenants/acme_corp/shared")
(shared / "policies" / "refund.md").write_text("30-day refund policy...")
(shared / "products" / "catalog.md").write_text("Product list...")

@tool
def run_shell_command(command: str) -> str:
    """Execute shell command in secure environment."""
    return kernel.run_shell_command(command)

llm = AzureChatOpenAI(...)  # Your config

today = datetime.now().strftime("%Y-%m-%d")
prompt = SYSTEM_PROMPT_CUSTOMER_SERVICE + f"\nToday: {today}"

agent = create_react_agent(llm, [run_shell_command], prompt=prompt)

# Interactive loop
while True:
    user_input = input("Customer: ")
    if user_input.lower() == 'quit':
        break
    result = agent.invoke({"messages": [("user", user_input)]})
    print(f"Agent: {result['messages'][-1].content}")
```

---

## Summary

| What you do | How |
|-------------|-----|
| Initialize kernel | `SafeKernel(data_root, tenant_id, agent_id)` |
| Create tool | `@tool` wrapper around `kernel.run_shell_command()` |
| Pick a prompt | Import from `agent_os.prompts` or write your own |
| Create agent | `create_react_agent(llm, [tool], prompt=prompt)` |
| Add company docs | Write to `shared/` folder before agent runs |

**That's it!** The LLM handles the rest - exploring, reading, writing, and remembering.
