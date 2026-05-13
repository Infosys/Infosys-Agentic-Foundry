<div align="center">

# 🚀 Infosys Agentic Foundry (IAF)

### Enterprise-Grade AI Agent Operating System

[![Version](https://img.shields.io/badge/Version-1.9.0-blue?style=for-the-badge)](release_notes.md)
[![License](https://img.shields.io/badge/License-Apache%202.0-green?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Infosys%20Topaz-orange?style=for-the-badge)](#)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](#)

**Your Foundation to Create Enterprise Agentic Platforms and Agents**

[📖 Documentation](https://Infosys.github.io/Infosys-Agentic-Foundry/) · [🚀 Quick Start](#-quick-start) · [🏗️ Architecture](#%EF%B8%8F-platform-architecture) · [📋 Features](#-key-capabilities) · [📝 Release Notes](release_notes.md)

</div>

---

## 🌟 What is Infosys Agentic Foundry?

**Infosys Agentic Foundry (IAF)** is a comprehensive, open-source framework designed to empower developers to **create, configure, and deploy** customizable AI agents with minimal coding effort. It serves as a complete AI Agent Operating System — providing everything from visual agent design to production-grade deployment across multiple cloud providers.

The platform supports the full agent lifecycle:

- **Design Time** — Create, configure, and perfect AI agents with visual builders, 8 templates, workflow orchestration, and evaluation frameworks
- **Runtime** — Execute agents at scale with multi-LLM gateway, Kafka message queues, hyper-scale storage, and full observability

> IAF is successfully deployed on **Azure Kubernetes Service (AKS)**, **AWS**, and **GCP**, ensuring enterprise-grade scalability and reliability.

---

## 📊 Platform at a Glance

| Metric | Value |
|--------|-------|
| 🤖 Agent Templates | **8** (React, React-Critic, Planner-Executor, Planner-Executor-Critic, Planner-Meta, Meta, Hybrid, Skill) |
| 🏗️ Architecture Layers | **8** (Experience → Orchestration → Context → Reasoning → Tools + Cross-cutting) |
| ☁️ Cloud Providers | **3** (AWS, Azure, GCP) |
| ⚡ Inference Engines | **3** (LangGraph, Google ADK, Python-based) |
| 🔐 User Roles | **5** (Super Admin, Admin, Developer, User, Auditor) |
| 🔌 API Endpoints | **22+** |
| 🎯 Total Features | **97** (46 Functional + 51 Non-Functional) |

---

## 🏗️ Platform Architecture

```
┌───────────────────────────────────────────────────────────────────────────────────────┐
│                    INFOSYS AGENTIC FOUNDRY (IAF) PLATFORM ARCHITECTURE                │
├───────────────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────────────────────────┐  │
│  │  Layer 0: EXPERIENCE — Agent Studio │ Chat UI │ MCP Console │ Ambient Inbox     │  │
│  └─────────────────────────────────────────────────────────────────────────────────┘  │
│                                         ▼                                             │
│  ╔═════════════════════════════════════════════════════════════════════════════════╗  │
│  ║  Layer 1: AGENT ORCHESTRATION ★ THE HEART ★                                    ║  │
│  ║  React │ React-Critic │ Planner-Exec │ Plan-Exec-Critic │ Meta │ Hybrid │ Skill ║  │
│  ╚═════════════════════════════════════════════════════════════════════════════════╝  │
│           ▼                                              ▼                            │
│  ┌────────────────────────────┐    ┌────────────────────────────────────────────┐     │
│  │ Layer 2: CONTEXT & MEMORY  │    │ Layer 3: DECISION & REASONING (LiteLLM)    │     │
│  │ SafeKernel │ /shared/      │    │ Azure │ OpenAI │ Ollama │ Google ADK       │     │
│  │ /memory/ │ /workspace/     │    │ SBERT │ BGE │ CoT │ ReAct │ ToT            │     │
│  └────────────────────────────┘    └────────────────────────────────────────────┘     │
│                                         ▼                                             │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐  │
│  │  Layer 4: TOOL EXECUTION — Code Executor │ MCP Registry │ Python Tools │ APIs   │  │
│  │  Backends: Subprocess │ Docker │ nsjail │ Async + Cache                         │  │
│  └─────────────────────────────────────────────────────────────────────────────────┘  │
├───────────────────────────────────────────────────────────────────────────────────────┤
│  Cross-cutting: Evaluation │ Feedback Learning │ Export │ Kafka MQ │ Observability    │
│  Security: RBAC (5 Roles) │ Dept Isolation │ VAULT │ SANDBOX │ AUDIT LOGGING          │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

**Core Architectural Concept — The Controller Pattern:**

> Request → Orchestrator (L1) → Queries Context (L2) → Invokes Reasoning (L3) → Executes Tools (L4) → Response

---

## 🎯 Key Capabilities

### 🤖 8 Agent Templates

| Template | Pattern | Description |
|----------|---------|-------------|
| **React** | Reason → Act | Single agent with step-by-step reasoning and tool execution |
| **React-Critic** | Reason → Act → Validate | React + built-in self-critique for higher accuracy |
| **Planner-Executor** | Plan → Execute | Separates planning from execution with replanning support |
| **Planner-Executor-Critic** | Plan → Execute → Validate | Three-stage cycle with quality validation |
| **Planner-Meta** | Plan → Orchestrate | Advanced orchestrator with multi-prompt planning and delegation |
| **Meta** | Orchestrate → Delegate | Supervisor agent coordinating multiple worker agents |
| **Hybrid** | Pure Python | Framework-free agent with native planning and execution |
| **Skill** | Declarative | SKILL.md-based declarative agents with zero-code creation |

### 🔄 Workflow Orchestration

- **Visual DAG Builder** — Drag-and-drop workflow designer for agent chaining
- **Sequential & Parallel Execution** — Run agents in series or concurrently
- **Conditional Branching** — Route data based on agent outputs
- **Human-in-the-Loop (HITL)** — Plan approval with feedback at critical decision points
- **Agent Pipelines** — Chain multiple agents into deterministic, reusable workflows

### 🔌 MCP Protocol (Model Context Protocol)

- Python-to-MCP server conversion automation
- MCP server CRUD with registry management
- External MCP URL support with custom headers
- Real-time tool discovery with enterprise security and audit logging
- Tool & MCP export/import across environments

### 🧠 Multi-LLM Gateway

- **LiteLLM Proxy** — Unified interface for Azure OpenAI, OpenAI, Ollama, and Google ADK (Gemini)
- **Token Tracking** — Per-request token usage analytics
- **Cost Calculation** — Model-based cost tracking per user, agent, and department
- **Load Balancing & Fallback** — Automatic failover between LLM providers
- **Custom Model Support** — Bring your own models with configurable endpoints

### 📊 Evaluation Framework

| Method | Description |
|--------|-------------|
| **Ground Truth** | Automated comparison against golden datasets (SBERT, ROUGE, BLEU, Jaccard, TF-IDF, Exact/Fuzzy Match) |
| **LLM-as-a-Judge** | Multi-dimensional scoring without predefined answers |
| **Consistency Testing** | Temporal consistency across repeated queries |
| **Robustness Testing** | Adversarial input evaluation |
| **Phoenix Integration** | Trace visualization and debugging |

### 💡 Intelligence & Memory

- **Semantic Memory** — Persistent cross-session fact storage via Redis and PostgreSQL
- **Episodic Memory** — Few-shot learning from past conversations using similarity scoring
- **Custom Knowledge Bases** — Upload documents (PDF, TXT) for domain-specific intelligence
- **Feedback-Driven Learning** — Continuous improvement loop: User Feedback → Lesson Extraction → Admin Approval → Knowledge Update → Agent Improvement

### 🔐 Enterprise Security

- **5-Role RBAC** — Super Admin, Admin, Developer, User, Auditor with department-based isolation
- **Secrets Vault** — Master key management for API keys, URLs, and credentials
- **Rate Limiting** — Per-user sliding window protection
- **Audit Logging** — Complete operation tracking
- **Sandboxed Execution** — Isolated tool execution via Docker/nsjail
- **JWT Authentication** — Secure Bearer token authentication for all endpoints

### 📈 Observability & Telemetry

- **OpenTelemetry** — Full distributed tracing integration
- **Arize Phoenix** — LLM observability with trace visualization
- **Token Usage Reports** — Per-user, per-agent, per-model analytics
- **Response Metrics** — Per-agent response time and performance tracking
- **Grafana Dashboards** — Real-time monitoring and alerts

### 📤 Export & Deployment

- **Standalone Agent Export** — Export agents as independent Python packages with all dependencies
- **GitHub Push** — Direct repository push with tool versioning
- **Blob Storage** — Cloud storage for export artifacts (AWS S3, Azure Blob, GCP)
- **Docker & Kubernetes** — Production-ready containerization with AKS/EKS/GKE deployment
- **Multi-Cloud Support** — Deploy on AWS, Azure, or GCP with unified abstractions

---

## ⚡ Additional Highlights

| Feature | Description |
|---------|-------------|
| **Viber Agent** | Conversational AI assistant that creates agents from plain descriptions — zero technical knowledge required |
| **SSE Streaming** | Real-time streaming of agent execution steps to the UI |
| **Canvas Screen** | Rich visualization of tables, charts, graphs, and images in chat |
| **Prompt Optimization** | Automated prompt evolution using Pareto sampling and LLM-as-judge scoring |
| **Validators** | Custom response validation logic with scoring and real-time feedback |
| **Tool Interrupt** | Review, modify, and approve tool calls step-by-step before execution |
| **Data Connectors** | Connect to PostgreSQL, SQLite, MySQL, and MongoDB |
| **Kafka Message Queue** | Async tool/agent execution, batch processing, M2M communication |
| **GZIP Compression** | Optimized response payloads for performance |
| **Google ADK Support** | Full Google Agent Development Kit as an inference backend alongside LangGraph |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- PostgreSQL & Redis
- Docker (optional, for containerized deployment)

### Installation

IAF supports multiple deployment options:

| Platform | Guide |
|----------|-------|
| 🪟 Windows | [Windows Setup](docs/Installation/windows.md) |
| 🐧 Linux | [Linux Setup](docs/Installation/linux.md) |
| 🐳 Docker Compose | [VM Docker-Compose](docs/Installation/VM_Docker-Compose.md) |
| ☁️ Azure (AKS) | [Azure Deployment](docs/Installation/Azure.md) |
| ☁️ AWS (EKS) | [AWS Deployment](docs/Installation/AWS.md) |
| ☁️ GCP (GKE) | [GCP Deployment](docs/Installation/GCP.md) |

---

## 🗂️ Repository Structure

```
Infosys-Agentic-Foundry/
├── Infosys-Agentic-Foundry-Backend/    # FastAPI backend (Port 8080)
│   ├── src/                            # Core source code
│   ├── agent_worker/                   # Kafka agent worker
│   ├── tool_worker/                    # Kafka tool worker
│   ├── knowledgebase_server/           # Knowledge base service
│   └── Export_Agent/                   # Agent export module
├── Infosys-Agentic-Foundry-Frontend/   # React frontend (Port 3000)
│   └── src/                            # React components & pages
├── IAF-Litellm-Server/                 # LiteLLM proxy server
├── docs/                               # MkDocs documentation
├── manifest_file/                      # Kubernetes manifests
└── site/                               # Built documentation site
```

---

## 📚 Documentation

Full documentation is available at **[https://Infosys.github.io/Infosys-Agentic-Foundry/](https://Infosys.github.io/Infosys-Agentic-Foundry/)**

- [Getting Started](docs/index.md)
- [Architecture Overview](docs/Architecture.md)
- [Agent Design Patterns](docs/Agents_Design/overview.md)
- [Agent Configuration](docs/agent_config/Overview.md)
- [Tool Configuration](docs/tools_config/tools.md)
- [MCP Registry](docs/MCP_Registry.md)
- [Evaluation Framework](docs/Evaluation/)
- [Admin Screen](docs/Admin_Screen.md)
- [RBAC & Security](docs/RBAC.md)
- [Telemetry & Monitoring](docs/Telemetry/)
- [Installation Guides](docs/Installation/)

---

## 🔄 Feedback Learning Loop

```
💬 User Feedback → 🧠 Lesson Extraction → ✅ Admin Approval → 📚 Knowledge Update → 🚀 Agent Improvement
```

The platform continuously improves agent performance through structured feedback collection, automated lesson extraction, admin-controlled approval workflows, and knowledge base updates that feed back into agent behavior.

---

## 🤝 Contributing

We welcome contributions! Please see our contribution guidelines and ensure your code follows the project's standards.

---

## 📄 License

This project is licensed under the [Apache License 2.0](LICENSE).

---

<div align="center">

**Infosys Agentic Foundry (IAF)** — Part of **Infosys Topaz**

Enterprise-Grade AI Agent Operating System • V1.9.0 • May 2026

</div>
