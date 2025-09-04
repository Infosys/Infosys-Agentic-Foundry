# Infosys Agentic Foundry: An Open-Source Solution for Customizable Pro-Code AI Agents

**Agentic Foundry** is a comprehensive, open-source framework designed to empower developers to **create, configure, and deploy** customizable AI agents with minimal coding effort. It provides a robust platform for building intelligent systems by offering customizable templates and a powerful set of tools, streamlining the entire agentic workflow development process. The platform facilitates the export of agents as standalone code or groups of agents, allowing them to be embedded into other workflows or hosted as separate applications with their own UI. The Infosys Agentic Service is successfully deployed on Azure Kubernetes services, ensuring enterprise-grade scalability and reliability.

## Key Features & Capabilities:

## 1. Simplified Agent & Tool Management

- **Easy Pro-Code Agent Creation**: Significantly reduces development time by automating the setup based on provided tool logic and workflow definitions.

- **Easy Agent & Tool Management**: Offers seamless onboarding, updating, and removal of agent components and tools directly within the framework.

- **In-Platform Customization**: Allows customization of tools, workflows, and control logic without requiring external IDEs or redeployments.

- **Reusable Components**: Agents and tools are designed as modular, self-contained units, promoting consistency and accelerating development across projects.

- **Tools Configuration**: Agents leverage **external functions or actions (tools)** to perform tasks beyond language generation, such as searching the web, performing calculations, or querying databases. The framework includes a secure connection management system for adapters and databases, eliminating the need to embed sensitive credentials directly within the tool's code. Tools can also be created using natural language queries, accelerating development.

## 2. Advanced Agent Templates

Agentic Foundry supports three primary agent templates, each tailored for specific use cases:

- **React Agent**: Combines reasoning traces with action execution, following a step-by-step thought process to determine what tool to use, execute it, observe the result, and iteratively refine its decisions until a final answer is achieved. This design is ideal for scenarios requiring precise and efficient single-task operations.

- **Multi Agent**: Operates on a **Planner-Executor-Critic paradigm**, where a Planner Agent generates a detailed step-by-step plan, an Executor Agent carries out each step of the plan, and a Critic Agent evaluates the outputs by scoring the results of each step. This enables collaboration between specialized agents to achieve complex objectives. It supports both fully automated and Human-in-the-Loop (HITL) modes, offering flexibility based on user requirements.

- **Meta Agent**: Acts as a central **Supervisor Agent** that orchestrates and coordinates worker agents (which can be ReAct agents, Multi-Agents, or hybrids of both). It dynamically analyzes the user query to select the most appropriate worker agent(s) to invoke and then aggregates their responses to deliver a final, consolidated answer.
- With more additional patterns....

## 3. Human-in-the-Loop (HITL) & Feedback Mechanisms

- **Human-in-the-Loop (HITL)**: Integrates manual checkpoints for human input, oversight, or decision-making into automated workflows, enabling review and intervention during critical decision-making steps. This is a core element of the Multi Agent, ensuring users can review and approve each planned step before execution.

- **Feedback-Driven Learning**: Facilitates continuous improvement of agent performance through direct user feedback. The system supports structured and unstructured feedback loops that fine-tune decision-making, language understanding, and tool usage over time. Admins can manage this feedback through a dedicated interface.

- **Tool Interrupt**: Provides users with **enhanced control** over tool execution by allowing them to review, modify, and approve tool calls step-by-step before they are processed. This feature offers greater transparency and control over the agent's behavior, especially when debugging or working with sensitive operations.

## 4. Robust Evaluation Frameworks

The platform offers a powerful, dual-system for evaluating agent performance:

- **Ground Truth-Based Evaluation**: A rigorous, quantitative method that automates the performance assessment of an AI agent by comparing its generated answers against a predefined, correct "golden data set". It calculates comprehensive metrics like **SBERT Similarity**, **TF-IDF Cosine Similarity**, **Jaccard Similarity**, **ROUGE Score** (**ROUGE-1**, **ROUGE-L**), **BLEU Score**, **Sequence Match Ratio**, **Exact Match**, **Fuzzy Match**, and an optional **LLM Score**. The framework also provides an LLM-based diagnostic summary and a downloadable detailed report for in-depth analysis.

- **LLM-as-a-Judge Evaluation**: A sophisticated, qualitative method that uses a powerful Large Language Model (LLM) to analyze and score an agent's performance on multiple dimensions, from its reasoning process to the quality of its final response, without needing a predefined "correct" answer. Key metrics include:

  - **Tool Utilization Efficiency**: Measures tool selection accuracy, usage efficiency, tool call precision, and tool call success rate.

  - **Agent Efficiency Score**: Assesses task decomposition efficiency, reasoning relevancy and coherence, agent robustness and consistency, answer relevance, groundedness, and response fluency and coherence. Evaluation results are visualized through a **dashboard in the Admin Screen** with various filters (agent name, type, models used by agent/evaluating model, threshold score) for detailed monitoring and analysis.

## 5. Enterprise-Grade Observability & Deployment

- **Telemetry & Monitoring**: Integrates best-in-class tools like OpenTelemetry for distributed tracing, Arize Phoenix for model observability, and Grafana for real-time dashboards and alerts. It captures LLM inputs/outputs, prompts, responses, errors, and tracks agent decisions and state to provide real-time insights and faster debugging.

- **CI/CD Pipeline**: Features a robust CI/CD pipeline to automate the creation of Docker images and their deployment in containerized environments and Kubernetes clusters. This automation streamlines deployment across various cloud providers (Hyperscalers), ensuring consistency and reducing manual effort.

- **Azure Kubernetes Deployment**: The Agentic Foundry has been successfully containerized using Docker and deployed on Azure Kubernetes Service (AKS). This deployment strategy ensures scalability, elasticity for agent execution workloads, rapid and isolated deployment of modular agents as microservices, and seamless integration with Azure-native DevSecOps tools and identity management.

## 6. Versatile Agent Offerings & Management

- **Agent-as-a-Service**: Provides an open-source framework-based solution for quickly configuring agents and tools, enabling end-users to interact via a conversational interface.

- **Vertical Agents**: Offers a suite of agents tailored for various industry personas across domains like Finance, Healthcare, Insurance, Retail, Communication, and Manufacturing, addressing specific workflows and use cases.

- **Horizontal Agents**: Provides common functionalities across industries, such as Email sending, File search, **Agentic RAG** (Retrieval-Augmented Generation), and SDLC.

- **User & Admin Management**: Features an Admin Screen that serves as a central hub for managing and monitoring key system components. It includes **Role-Based Access Control (RBAC)** with distinct user roles (Admin, Developer, User), each having specific access levels for user registration, agent onboarding, feedback approval, and system evaluation.
