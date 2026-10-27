# AgentOS - Filesystem Agent Framework from Infosys Agentic Foundry

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-36%20passed-green.svg)]()

**Give your AI agents a filesystem instead of dozens of tools.**

AgentOS provides a secure, sandboxed environment where AI agents interact through familiar Unix commands (`ls`, `cat`, `grep`, `echo`) plus semantic search (`semgrep`). Instead of building custom memory APIs, just describe folder structures in your prompt - the LLM figures out the rest.

## 🎯 Philosophy

> "The best memory system is one the LLM already knows how to use."

Traditional agent architectures require:
- Custom tools for every operation
- Complex memory retrieval systems  
- Constant code changes as requirements evolve

AgentOS provides:
- **One tool** (`run_shell_command`) that handles everything
- **Filesystem-based memory** that persists naturally
- **Prompt-defined schemas** - change folder structure, not code

## 🚀 Quick Start

```bash
pip install agentos-kernel
```

For credential-file backends, install the optional extra:

```bash
pip install "agentos-kernel[credentials]"
```

The distribution is `agentos-kernel`; the import package remains `agent_os`.
Agent frameworks such as LangGraph/LangChain are optional consumers of the
kernel, not kernel dependencies.

```python
from agent_os import SafeKernel
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

# 1. Initialize the kernel
kernel = SafeKernel(
    data_root="./agent_data",
    tenant_id="my_company",
    agent_id="support_bot"
)

# 2. Create the tool
@tool
def run_shell_command(command: str) -> str:
    """Execute command in secure shell."""
    return kernel.run_shell_command(command)

# 3. Create your agent with a filesystem prompt
agent = create_react_agent(llm, [run_shell_command], prompt="""
You have a filesystem-based memory:
- /shared/ - Company docs (read-only)
- /memory/ - Your persistent brain
- /workspace/ - Current task scratchpad

Use: ls, cat, grep, echo, semgrep
""")

# 4. The agent explores and remembers naturally
result = agent.invoke({"messages": [("user", "What's our refund policy?")]})
```

## 📁 How It Works

### Virtual Filesystem
```
agent_data/
└── tenants/my_company/
    ├── shared/              ← Company knowledge (READ-ONLY)
    │   ├── policies/
    │   └── knowledge/
    └── agents/support_bot/
        ├── workspace/       ← Scratchpad (cleared between tasks)
        ├── memory/          ← Persistent memory (auto-indexed)
        │   ├── current/     ← Active session context
        │   ├── recent/      ← Recent conversations (by date)
        │   └── entities/    ← Users, companies, etc.
        └── .index/          ← Vector store for semantic search
```

### Available Commands
| Command | Example | Description |
|---------|---------|-------------|
| `ls` | `ls -la /shared/` | List directory |
| `cat` | `cat /shared/policy.md` | Read file |
| `grep` | `grep -r "refund" /shared/` | Text search |
| `find` | `find /memory -name "*.md"` | Find files |
| `echo` | `echo "note" > /memory/note.md` | Write file |
| `semgrep` | `semgrep "customer preferences"` | Semantic search |
| `head/tail` | `head -n 20 file.txt` | Partial read |
| `tree` | `tree /memory` | Directory tree |

### Security (Built-in)
- ✅ Path traversal blocked (`..` not allowed)
- ✅ Dangerous commands blocked (`rm`, `sudo`, `wget`, `python`)
- ✅ Command chaining blocked (`&&`, `||`, `;`, `|`)
- ✅ Read-only enforcement for `/shared/`
- ✅ Sandboxed to agent's directory
- ✅ Audit logging of all commands

## 💡 Prompt-Defined Schemas

The magic: **just describe folder structure in your prompt** and the LLM organizes data naturally.

```python
system_prompt = """
Your memory structure:
/memory/
├── customers/{customer_id}.md   # One file per customer
├── tickets/{date}_{id}.md       # Support tickets by date
└── learnings/                   # Patterns you've discovered
"""
```

The agent automatically:
- Creates `/memory/customers/john_doe.md` when learning about John
- Saves tickets like `/memory/tickets/2026-01-12_T001.md`
- Uses `semgrep "shipping complaints"` to find patterns

## 📋 Examples

### DILO Agent (Day in Life Of)
```bash
python agent_os/dilo_agent.py
```
Captures employee daily activities with user-specific memory.

### Customer Service Agent
```bash
python agent_os/example_langgraph_azure.py
```
Answers questions using company knowledge base.

## 🔧 Configuration

### Azure OpenAI
Create `agent_os/config.env`:
```env
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-08-01-preview
```

### OpenAI
```python
import os
os.environ["OPENAI_API_KEY"] = "your-key"
```

## 📦 Project Structure

```
agent_os/
├── __init__.py          # Package exports
├── kernel.py            # Core SafeKernel - the "Smart Shell"
├── safe_path.py         # Security layer for path resolution
├── vector_store.py      # Local vector DB for semantic search
├── prompts.py           # Pre-built prompt patterns
├── tools.py             # LangChain/OpenAI tool wrappers
├── tests/               # 36 unit tests
├── DEVELOPER_GUIDE.md   # Integration guide
└── examples/
    ├── dilo_agent.py
    └── example_langgraph_azure.py
```

## 🧪 Testing

```bash
pytest agent_os/tests/ -v
```

All 36 tests should pass.


## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

## 🏢 About

Built by the Topaz Agentic AI COE team

---

**Key Insight**: *Don't build memory APIs. Give agents a filesystem and describe the structure in your prompt. The LLM already knows how to use `ls`, `cat`, and `grep`.*
