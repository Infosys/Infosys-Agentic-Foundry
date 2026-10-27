# Copilot Instructions for IAF-Agent-Studio

## Skills Available

When users ask about creating skills, agents, or configurations for the IAF platform, use the **iaf-developer-guide** skill:

- **Skill Location**: `.github/skills/iaf-developer-guide/SKILL.md`
- **Use When**: User wants to create skills, agents, database configs, or workflows
- **Contains**: Templates for REACT, WORKFLOW, PARALLEL, SUPERVISOR modes

## Quick Commands

```bash
# Start IAF Server
cd IAF-Agent-Studio && python3 server.py

# Kill process on port 8080 if needed  
lsof -ti:8080 | xargs kill -9 2>/dev/null
```

## Project Structure

```
IAF-Agent-Studio/
├── server.py           # FastAPI backend (main entry point)
├── static/             # Web UI (Alpine.js + TailwindCSS)
│   ├── index.html      # Main chat interface
│   └── components/     # Reusable components
└── .github/
    └── skills/
        └── iaf-developer-guide/  # Skill creation guide
```

## Key Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/chat` | POST | Main chat endpoint |
| `/api/agents` | GET/POST | List/create agents |
| `/api/skills` | GET/POST | List/create skills |
| `/api/tools` | GET | List available tools |

## Tool Names (IMPORTANT)

Valid tools are: `shell`, `run_sql_query`, `execute_code`

**Do NOT use** `fs` - it's not a valid tool name.
