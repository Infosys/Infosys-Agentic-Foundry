# IAF Agent Studio

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)

**Zero-build web UI for IAF Agent Skills.**

A lightweight FastAPI server with WebSocket streaming that provides a modern chat interface for interacting with AI agents. No npm, no React, no build step - just HTML + TailwindCSS (CDN) + Alpine.js.

## 🎯 Features

- **WebSocket Streaming** - Real-time chat with reasoning trace
- **Skill Routing** - Automatic routing to the right skill based on query
- **File Browser** - Explore agent's sandboxed filesystem
- **Tool Visibility** - See every shell command the agent runs
- **Zero Build** - Single HTML file with CDN dependencies
- **Mobile Friendly** - Responsive design works on all devices

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp config.env.example config.env
# Edit config.env with your Azure OpenAI credentials
```

### 3. Run the Server

```bash
python server.py
```

Open http://localhost:8080 in your browser.

## 📁 Project Structure

```
IAF-Agent-Studio/
├── server.py           # FastAPI server + WebSocket; mounts all routers
├── routers/            # FastAPI routers (chat, files, agents, skills, auth, ...)
├── services/           # Business/service layer
├── auth/               # Authentication backends (local, Microsoft/OAuth, sqlite/postgres/redis)
├── security/           # Security console (entitlement policies, simulator, audit)
├── shared/             # Shared config + helpers (shared/config.py defines DATA_ROOT etc.)
├── static/             # Zero-build web UI (index.html + dashboards)
├── privacy/            # Data-privacy gate
├── scripts/            # Helper scripts
├── tests/              # Test suite
├── config.env.example  # Environment template
├── requirements.txt    # Python dependencies
└── README.md
```

The server also ships standalone worker processes at the top level
(`queue_worker.py`, `scheduler_worker.py`, `kernel_worker.py`, `trace_emitter.py`, etc.).

## 🔗 Dependencies

This project requires:
- **agent_os** - SafeKernel for sandboxed filesystem operations
- **IAF-Agent-Skills** - SkillAgent, SkillRouter, and skill definitions

Ensure both are available in the parent directory or adjust `sys.path` in `server.py`.

## 🛠️ API Endpoints

### REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Serve web UI |
| GET | `/api/files?path=/&user_id=demo` | List files in sandbox |
| GET | `/api/files/content?path=/me/file.md` | Read file content |
| POST | `/api/files` | Write file |
| GET | `/api/skills` | List available skills |
| POST | `/api/chat` | HTTP chat (fallback) |

### WebSocket

| Endpoint | Description |
|----------|-------------|
| `/ws/chat` | Streaming chat with real-time tool calls |

**WebSocket Message Format:**
```json
{
  "content": "show me my dilo",
  "tenant_id": "company",
  "agent_id": "enterprise_agent",
  "user_id": "demo"
}
```

**Response Events:**
- `routing` - Which skill was matched
- `tool_call` - Shell command being executed
- `tool_result` - Command output
- `response` - Final agent response

## ⚙️ Configuration

Environment variables in `config.env`:

```bash
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-12-01-preview

# Server
HOST=127.0.0.1
PORT=8080

# Paths
DATA_ROOT=../enterprise_root
SKILLS_PATH=../enterprise_root/tenants/company/skills
```

## 🎨 Customization

The UI is a single HTML file using:
- **TailwindCSS** (CDN) - Styling
- **Alpine.js** (CDN) - Reactivity
- **Marked.js** (CDN) - Markdown rendering

Edit `static/index.html` to customize the look and feel.

## 🔒 Security Notes

- The server runs locally by default (`127.0.0.1`)
- File operations are sandboxed to `DATA_ROOT`
- Each user gets isolated storage under `/me/`
- Never expose to internet without authentication

## 📄 License

Apache License 2.0 - See [LICENSE](LICENSE) file.
