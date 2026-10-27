# IAF-Agent-Skills

**Skill-based routing and generic agent framework built on IAF-Agent-OS.**

This project provides a generic ReAct agent that routes user queries to specialized skills defined as markdown files. It follows Anthropic's "Skills Pattern" and the principle of progressive context disclosure.

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                        User Query                               │
│                    "log my day please"                          │
└──────────────────────────┬─────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                     SkillRouter                               │
│           _index.yaml → match triggers → "dilo"               │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                     SkillLoader                               │
│        Load SKILL.md + INSTRUCTIONS.md + EXAMPLES.md          │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                     SkillAgent                                │
│       LangGraph ReAct + Skill Prompt + Kernel Tools           │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                    IAF-Agent-OS                               │
│              SafeKernel + RBAC + VectorStore                  │
└──────────────────────────────────────────────────────────────┘
```

## Installation

```bash
# Clone the repository
git clone https://github.com/Infosys-Generative-AI/IAF_Agent_Skills.git
cd IAF-Agent-Skills

# Install dependencies
pip install -r requirements.txt

```

## Quick Start

```python
from iaf_agent_skills import SkillAgent
from agent_os import SafeKernel

# Create kernel for data persistence
kernel = SafeKernel(
    data_root="./data",
    tenant_id="company",
    agent_id="assistant"
)

# Create skill agent
agent = SkillAgent(
    kernel=kernel,
    skills_path="./skills",
    user_id="john_smith"
)

# Run a query (auto-routes to best skill)
response = agent.run("log my day")
print(response)

# List available skills
for skill in agent.list_skills():
    print(f"- {skill['name']}: {skill['description']}")
```

## Configuration

Set environment variables for the LLM:

```bash
# Azure OpenAI
export AZURE_OPENAI_API_KEY="your-key"
export AZURE_OPENAI_ENDPOINT="https://your-endpoint.openai.azure.com"
export AZURE_OPENAI_DEPLOYMENT="gpt-4o"

# OR OpenAI
export OPENAI_API_KEY="your-key"
```

Or pass your own LLM:

```python
from langchain_openai import AzureChatOpenAI

llm = AzureChatOpenAI(
    api_key="...",
    azure_endpoint="...",
    azure_deployment="gpt-4o",
    temperature=0
)

agent = SkillAgent(kernel=kernel, skills_path="./skills", llm=llm)
```

## Creating Skills

Skills are defined as folders with markdown files:

```
skills/
├── _index.yaml           # Master index with triggers
├── dilo/
│   ├── SKILL.md          # Main skill definition
│   ├── INSTRUCTIONS.md   # Detailed instructions
│   └── EXAMPLES.md       # Example conversations
└── general/
    └── SKILL.md
```

### _index.yaml

```yaml
version: "1.0"
default_skill: general

skills:
  dilo:
    description: "Day in Life Of activity logger"
    triggers:
      - "log my day"
      - "DILO"
      - "time tracking"
  
  general:
    description: "General assistant"
    triggers: []
```

### SKILL.md

```markdown
---
name: dilo
version: "1.0"
description: "Activity logger for employees"

files:
  instructions: "INSTRUCTIONS.md"
  examples: "EXAMPLES.md"

user_data:
  daily_log: "/me/dilo/{date}.md"

mcp_tools: []
---

# DILO Agent

You help employees log their daily activities...
```

## API Reference

### SkillAgent

```python
agent = SkillAgent(
    kernel=SafeKernel(...),    # Required: IAF-Agent-OS kernel
    skills_path="./skills",     # Path to skills folder
    llm=None,                   # Optional: custom LLM
    user_id="john",             # Optional: user ID for RBAC
    verbose=False               # Optional: enable logging
)

# Run a single query
response = agent.run("log my day")

# Force a specific skill
response = agent.run("help me", skill_name="dilo")

# Multi-turn continuity is automatic: consecutive run() calls on the same
# SkillAgent instance share agent.session_id, so prior turns are loaded from
# the conversation store. (session_id is generated in __init__, not a run() arg.)
response = agent.run("meetings all morning")

# List skills
skills = agent.list_skills()
```

### SkillRouter

```python
router = SkillRouter("./skills")

# Match query to skill
skill_name = router.match("I want to log my day")  # → "dilo"

# List all skills
skills = router.list_skills()

# Check if skill exists
exists = router.skill_exists("dilo")  # → True

# Reload index (for hot-reloading)
router.reload()
```

### SkillLoader

```python
loader = SkillLoader("./skills")

# Load a skill
skill = loader.load("dilo")

# Access skill properties
print(skill.name)         # "dilo"
print(skill.description)  # "Activity logger..."
print(skill.body)         # Markdown body content
print(skill.files)        # {"instructions": "INSTRUCTIONS.md", ...}
print(skill.mcp_tools)    # [{"server": "slack", "tools": [...]}]

# Get related file content
instructions = loader.get_file_content(skill, "instructions")

# Build complete prompt
prompt = loader.get_prompt(skill, include_files=True)
```

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python tests/test_router.py
python tests/test_loader.py
```

## License

MIT License - See [LICENSE](LICENSE) for details.

## Related Projects

- [IAF-Agent-OS](https://github.com/Infosys-Generative-AI/IAF_Agent_OS) - Secure filesystem kernel with RBAC
- [LangGraph](https://github.com/langchain-ai/langgraph) - Agent framework
