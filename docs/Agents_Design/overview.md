Agentic Foundry supports a variety of agent templates:

**React Agent**:

Designed for single-task operations, React Agents use a step-by-step reasoning process to determine and execute the appropriate actions. They are ideal for scenarios requiring precise and efficient task execution. Learn more in the [React Agent Design](React Agent Design.md) document.

**React Critic Agent**:

An extension of the React Agent, the React Critic Agent introduces a dual system prompt mechanism for self-critique and improved output quality. See [React Critic Agent Design](ReactCriticAgent_Design.md) for details.

**Multi Agent**:

Multi Agents enable collaboration between specialized agents to achieve complex objectives. They follow the **Planner-Executor-Critic** paradigm, ensuring tasks are planned, executed, and evaluated effectively. Detailed information is available in the [Multi Agent Design](Multi Agent Design.md) document.

**Planner Executor Agent**:

This agent type implements the Planner-Executor-Critic workflow with enhanced system prompt structure for more granular control. See [Planner Executor Agent Design](Planner_executor_agent_design.md).

**Meta Agent**:

Acting as orchestrators, Meta Agents manage and coordinate other agents to achieve high-level goals. They dynamically adapt to context and task requirements, ensuring seamless execution. Explore their design in the [Meta Agent Design](Orchestration_Meta_Agent_Design.md) document.

**Planner Meta Agent**:

An advanced orchestrator, the Planner Meta Agent uses multiple system prompts to provide robust, adaptive, and transparent orchestration of agent-based workflows. Learn more in [Planner Meta Agent Design](Planner_meta_agent_design.md).

Each agent template is highly customizable, allowing developers to tailor them to specific use cases, making Agentic Foundry a robust platform for building intelligent systems.

**Hybrid Agent**:

Hybrid Agents combine features from multiple agent types, enabling flexible workflows that leverage both step-by-step reasoning and collaborative planning. They are suited for scenarios requiring dynamic adaptation between individual and multi-agent strategies. For more details, refer to the [Hybrid Agent Design](Hybrid_Agent_Design.md) document.