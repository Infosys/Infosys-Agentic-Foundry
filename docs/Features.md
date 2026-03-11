# Features

Agentic Foundry provides comprehensive capabilities for building and managing intelligent agents with minimal coding effort.

---

## Features Overview

<style>
.af-section {
  margin: 32px 0 18px 0;
}
.af-section-title {
  font-size: 0.78em;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1.8px;
  margin-bottom: 14px;
  padding-bottom: 6px;
  border-bottom: 2px solid var(--md-default-fg-color--lightest);
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--md-default-fg-color--light);
}
.af-section-title .dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}
.af-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}
.af-card {
  background: var(--md-code-bg-color);
  border: 1px solid var(--md-default-fg-color--lightest);
  border-radius: 10px;
  padding: 18px 16px 14px 16px;
  transition: box-shadow 0.2s, border-color 0.2s;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.af-card:hover {
  box-shadow: 0 2px 12px rgba(0,0,0,0.12);
  border-color: var(--md-default-fg-color--lighter);
}
.af-card .icon {
  font-size: 1.35em;
  line-height: 1;
}
.af-card .title {
  font-weight: 700;
  font-size: 0.9em;
  color: var(--md-default-fg-color);
  line-height: 1.3;
}
.af-card .desc {
  font-size: 0.78em;
  color: var(--md-default-fg-color--light);
  line-height: 1.45;
}
/* Accent colors per section */
.af-core .dot { background: #3b82f6; }
.af-core .af-card { border-left: 3px solid #3b82f6; }
.af-workflow .dot { background: #8b5cf6; }
.af-workflow .af-card { border-left: 3px solid #8b5cf6; }
.af-intel .dot { background: #10b981; }
.af-intel .af-card { border-left: 3px solid #10b981; }
.af-data .dot { background: #f59e0b; }
.af-data .af-card { border-left: 3px solid #f59e0b; }
.af-security .dot { background: #ef4444; }
.af-security .af-card { border-left: 3px solid #ef4444; }
.af-eval .dot { background: #06b6d4; }
.af-eval .af-card { border-left: 3px solid #06b6d4; }
</style>

<!-- Core Development -->
<div class="af-section af-core">
<div class="af-section-title"><span class="dot"></span> Core Development</div>
<div class="af-cards">
<div class="af-card">
  <div class="icon">⚡</div>
  <div class="title">Low-Code Agent Creation</div>
  <div class="desc">Provide tool logic and workflow definitions — the framework handles the rest.</div>
</div>
<div class="af-card">
  <div class="icon">🛠️</div>
  <div class="title">Agent & Tool Management</div>
  <div class="desc">Onboard, update, or remove agents and tools through an intuitive interface.</div>
</div>
<div class="af-card">
  <div class="icon">🎨</div>
  <div class="title">In-Platform Customization</div>
  <div class="desc">Customize tools, workflows, and control logic directly — no external IDEs required.</div>
</div>
<div class="af-card">
  <div class="icon">🧩</div>
  <div class="title">Reusable Components</div>
  <div class="desc">Modular agents and tools reusable across workflows and projects.</div>
</div>
</div>
</div>

<!-- Workflow & Control -->
<div class="af-section af-workflow">
<div class="af-section-title"><span class="dot"></span> Workflow & Control</div>
<div class="af-cards">
<div class="af-card">
  <div class="icon">🧑‍💼</div>
  <div class="title">Human-in-the-Loop</div>
  <div class="desc">Manual checkpoints for human review and intervention at critical steps.</div>
</div>
<div class="af-card">
  <div class="icon">🔗</div>
  <div class="title">Agent Pipelines</div>
  <div class="desc">Visual drag-and-drop builder for multi-agent workflows with conditional branching.</div>
</div>
<div class="af-card">
  <div class="icon">🎯</div>
  <div class="title">Orchestrator Agent</div>
  <div class="desc">Central coordinating agent that manages tasks across distributed agents.</div>
</div>
<div class="af-card">
  <div class="icon">✋</div>
  <div class="title">Tool Interrupt</div>
  <div class="desc">Review and approve tool executions step-by-step before processing.</div>
</div>
<div class="af-card">
  <div class="icon">⚙️</div>
  <div class="title">Dynamic Workflow Automation</div>
  <div class="desc">Adaptive workflows with dynamic branching and conditional task handling.</div>
</div>
<div class="af-card">
  <div class="icon">📡</div>
  <div class="title">SSE Streaming</div>
  <div class="desc">Real-time streaming of each agent execution step to the UI as it happens.</div>
</div>
<div class="af-card">
  <div class="icon">🖼️</div>
  <div class="title">Canvas Screen</div>
  <div class="desc">Rich visualization of tables, charts, graphs, and images in chat inference.</div>
</div>
<div class="af-card">
  <div class="icon">✨</div>
  <div class="title">Prompt Optimization</div>
  <div class="desc">Automated prompt evolution using Pareto sampling and LLM-as-judge scoring.</div>
</div>
<div class="af-card">
  <div class="icon">✅</div>
  <div class="title">Validators</div>
  <div class="desc">Custom response validation logic mapped to agents — scoring, verifying, and improving outputs in real time.</div>
</div>
</div>
</div>

<!-- Intelligence & Learning -->
<div class="af-section af-intel">
<div class="af-section-title"><span class="dot"></span> Intelligence & Learning</div>
<div class="af-cards">
<div class="af-card">
  <div class="icon">🧠</div>
  <div class="title">Semantic Memory</div>
  <div class="desc">Persistent cross-session fact storage and retrieval via Redis and PostgreSQL.</div>
</div>
<div class="af-card">
  <div class="icon">💡</div>
  <div class="title">Episodic Memory</div>
  <div class="desc">Few-shot learning from past conversations using similarity scoring.</div>
</div>
<div class="af-card">
  <div class="icon">📚</div>
  <div class="title">Custom Knowledge Bases</div>
  <div class="desc">Upload documents (PDF, TXT) for domain-specific agent intelligence.</div>
</div>
<div class="af-card">
  <div class="icon">🔄</div>
  <div class="title">Feedback-Driven Learning</div>
  <div class="desc">Continuous improvement through structured user feedback loops.</div>
</div>
</div>
</div>

<!-- Data & Integrations -->
<div class="af-section af-data">
<div class="af-section-title"><span class="dot"></span> Data & Integrations</div>
<div class="af-cards">
<div class="af-card">
  <div class="icon">🗄️</div>
  <div class="title">Data Connectors</div>
  <div class="desc">Connect to PostgreSQL, SQLite, MySQL, and MongoDB from agent workflows.</div>
</div>
<div class="af-card">
  <div class="icon">🔌</div>
  <div class="title">MCP Registry</div>
  <div class="desc">Model Context Protocol integration with real-time tool discovery and audit logging.</div>
</div>
<div class="af-card">
  <div class="icon">🤖</div>
  <div class="title">Flexible Model Support</div>
  <div class="desc">Plug in Azure OpenAI, OpenAI, or custom LLM providers seamlessly.</div>
</div>
<div class="af-card">
  <div class="icon">🖥️</div>
  <div class="title">Model Server Integration</div>
  <div class="desc">Centralized hosting of bi-encoder and cross-encoder models via FastAPI.</div>
</div>
</div>
</div>

<!-- Security & Access -->
<div class="af-section af-security">
<div class="af-section-title"><span class="dot"></span> Security & Access</div>
<div class="af-cards">
<div class="af-card">
  <div class="icon">🛡️</div>
  <div class="title">Role-Based Access Control</div>
  <div class="desc">Admin, Developer, and User roles with granular platform permissions.</div>
</div>
<div class="af-card">
  <div class="icon">🔑</div>
  <div class="title">JWT Authentication</div>
  <div class="desc">Secure API authentication using Bearer tokens for all endpoints.</div>
</div>
<div class="af-card">
  <div class="icon">🔒</div>
  <div class="title">Vault (Secrets Management)</div>
  <div class="desc">Private and public vaults for API keys, URLs, and credentials.</div>
</div>
<div class="af-card">
  <div class="icon">📦</div>
  <div class="title">Agent Export</div>
  <div class="desc">Export complete agent packages for backup, migration, or redeployment.</div>
</div>
</div>
</div>

<!-- Evaluation & Monitoring -->
<div class="af-section af-eval">
<div class="af-section-title"><span class="dot"></span> Evaluation & Monitoring</div>
<div class="af-cards">
<div class="af-card">
  <div class="icon">⚖️</div>
  <div class="title">LLM-Based Evaluation</div>
  <div class="desc">LLM-as-a-judge scoring with side-by-side model comparison.</div>
</div>
<div class="af-card">
  <div class="icon">🎯</div>
  <div class="title">GroundTruth Evaluation</div>
  <div class="desc">Compare agent responses against expected outputs via CSV/XLSX upload.</div>
</div>
<div class="af-card">
  <div class="icon">📊</div>
  <div class="title">Consistency & Robustness</div>
  <div class="desc">Temporal consistency and adversarial robustness testing for agents.</div>
</div>
<div class="af-card">
  <div class="icon">📈</div>
  <div class="title">Telemetry & Monitoring</div>
  <div class="desc">OpenTelemetry, Arize Phoenix, and Grafana for observability and alerts.</div>
</div>
</div>
</div>

---

## Feature Descriptions

### Core Development Features

**1. Low-Code Agent Creation**

Reduced development time with a low-code approach. Simply provide the tool logic and workflow definitions — the framework automatically handles the rest.

**2. Agent & Tool Management**

Seamlessly onboard, update, or remove agents and tools through an intuitive interface.

**3. In-Platform Customization**

Customize tools, workflows, and control logic directly within the framework — no external IDEs or redeployment required.

**4. Reusable Components**

Design agents and tools as modular, self-contained components. These can be reused across multiple workflows and projects, promoting consistency and accelerating development.

---

### Workflow & Control Features

**5. Human-in-the-Loop**

Integrate manual checkpoints into automated workflows to enable human review and intervention during critical decision-making steps. Maintain oversight and control where it matters most, especially in sensitive or high-risk operations.

**6. Agent Pipelines**

Visually design multi-agent workflows using a drag-and-drop canvas. Connect multiple agents in sequence or parallel with conditional branching, input/output management, and reusable pipeline configurations.

**7. Orchestrator Agent**

Manage complex multi-agent systems through a central coordinating agent. The Orchestrator assigns tasks, handles inter-agent communication, resolves conflicts, and ensures that distributed agents work toward a unified goal.

**8. Tool Interrupt**

Review, modify, and approve tool executions before they are processed. This interactive mode provides step-by-step control over tool calls, allowing parameter editing and approval at each stage.

**9. Dynamic Workflow Automation**

Automate workflows that can adapt to real-time inputs, system feedback, or environmental changes. The platform supports dynamic branching, state-aware execution, and conditional task handling.

**10. SSE Streaming**

Server-Sent Events stream each step of the agent's internal processing to the UI in real-time — providing complete visibility into tool calls, reasoning steps, and execution progress as they happen.

**11. Canvas Screen**

An advanced visualization feature in chat inference that automatically renders structured data as tables, charts, graphs, or images — providing rich, context-aware output directly in the chat interface.

**12. Prompt Optimization**

An automated system that generates, tests, and evolves multiple prompt versions using Pareto sampling and LLM-as-judge scoring to find the most accurate and efficient system prompt for your agent.

**13. Validators**

Create custom validation logic — similar to tools — and map them to agents during onboarding. When enabled via the Validator toggle in chat, validators automatically check agent responses against expected patterns, returning a validation score, status, and feedback. Supported across React, React Critic, Planner Executor, Meta, and Planner Meta templates. Validators help ensure response accuracy, format compliance, and overall quality in real time.

---

### Intelligence & Learning Features

**14. Semantic Memory**

Persistent cross-session memory that stores and retrieves user-provided facts, preferences, and contextual information using Redis and PostgreSQL — enabling personalized, context-aware interactions.

**15. Episodic Memory**

Agents learn from past conversational experiences by storing query-response examples. Using bi-encoder and cross-encoder similarity scoring, agents apply few-shot learning to improve future responses based on positive and negative feedback.

**16. Custom Knowledge Bases**

Equip agents with domain-specific intelligence by uploading documents (PDF, TXT) as knowledge bases. Agents reference these during inference for accurate, context-aware answers.

**17. Feedback-Driven Learning**

Continuously improve agent performance through direct user feedback. The system supports structured and unstructured feedback loops that fine-tune decision-making, language understanding, and tool usage over time.

---

### Data & Integrations

**18. Data Connectors**

Connect to and interact with PostgreSQL, SQLite, MySQL, and MongoDB databases directly from agent workflows through a simple connection interface.

**19. MCP Registry**

Model Context Protocol integration for connecting agents to external tools and services. Supports local, remote, and file-based MCP servers with real-time tool discovery, enterprise security, and audit logging.

**20. Flexible Model Support**

Plug in different LLMs or SLMs as per task needs. Supports Azure OpenAI, OpenAI, and custom LLM providers through a straightforward configuration process.

**21. Model Server Integration**

Centralized hosting of bi-encoder and cross-encoder models via a FastAPI-based model server — eliminating redundant downloads and local storage across multiple environments.

---

### Security & Access

**22. Role-Based Access Control (RBAC)**

Three distinct user roles — Admin, Developer, and User — each with specific access levels and permissions across the platform including tools, agents, vault, data connectors, and inference features.

**23. JWT Authentication**

Secure API endpoint authentication using JSON Web Tokens. All API requests are authorized via Bearer tokens, ensuring integrity and controlled access to platform endpoints.

**24. Vault (Secrets Management)**

A secure storage system for API keys, URLs, and credentials with private (user-only) and public (organization-wide) vaults. Tools retrieve secrets by reference — no hardcoded values required.

**25. Agent Export**

Export complete agent configurations including tools, dependencies, static files, validators, and SSE configurations as a self-contained package for backup, migration, or redeployment across environments.

---

### Evaluation & Monitoring

**26. LLM-Based Evaluation**

Assess agent quality using the LLM-as-a-judge methodology. Compare two models side-by-side across predefined metrics with real-time progress updates via SSE.

**27. GroundTruth Evaluation**

Measure agent performance by comparing generated responses against expected outputs provided via CSV or XLSX upload. Produces comprehensive accuracy and quality metrics.

**28. Consistency & Robustness Evaluation**

Evaluate response stability across identical queries over time (consistency) and resilience against edge cases, malformed inputs, and adversarial scenarios (robustness).

**29. Telemetry & Monitoring**

Monitor system performance and behavior using OpenTelemetry for distributed tracing, Arize Phoenix for model observability, and Grafana for real-time dashboards and alerts.
