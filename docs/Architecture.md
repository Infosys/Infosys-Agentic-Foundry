# Arcitecture
Agentic Foundry architecture includes a comprehensive orchestration system that integrates agents, tools, and memory components to create intelligent, scalable, and personalized AI-driven workflows.

## Agents

- **Reusable Templates**: Developers can utilize predefined, reusable templates to streamline the creation of agents. These templates allow for the rapid definition of agents with specific roles or persona attributes, ensuring consistency and reducing development time.
- **Customizable Roles**: Agents can be tailored to meet the unique requirements of an application by defining their behaviors, objectives, and interaction styles. This flexibility enables developers to create agents that align with specific use cases or business goals.

We mainly have three types of templates: `React`, `React Critic`, `Multi`, `Planner Executor`,`Meta`, `Planner Meta`.

**React Template**: 

The ReAct(Reasoning and Acting) agent combines reasoning traces with action execution. It uses a step by step thought process to determine what tool to use, executes it, observe the result, and continues until it can return a final answer.

!!! Info "ReAct Use Case"
    When the task requires step-by-step reasoning and immediate action execution.

    Examples:

    1. Answering user queries by reasoning through available data and tools.
    2. Performing calculations or data lookups with a clear sequence of steps.
    3. Interactive troubleshooting or debugging tasks where the agent needs to reason and act iteratively.

**React Critic Template**: 

Extends the React agent by introducing a Critic module that reviews and refines each reasoning-action step. The Critic evaluates intermediate outputs, provides feedback, and enables the agent to self-correct before finalizing a response. This results in higher accuracy and reliability, especially for complex, multi-step queries.

!!! Info "React Critic Use Case"

    When the task requires step-by-step reasoning and immediate action execution, with an added need for refining and validating each step.

    Examples:

    1. Answering complex user queries that involve multiple steps and require validation of each step.
    2. Performing calculations or data lookups where intermediate results need to be evaluated and possibly corrected.
    3. Interactive troubleshooting or debugging tasks where the agent needs to reason, act, and iteratively refine its actions based on feedback.


**Multi Template**: 

The Multi Agent operates on the Planner-Executor-Critic paradigm. It begins with a Planner Agent that generates a step-by-step plan based on the user query. The Executor Agent then executes each step of the plan. The Critic evaluates the outputs by scoring the results of each step.

!!! Info "Multi Agent Use Case"
    When the task involves a complex workflow that requires planning, execution, and evaluation.

    Examples:

    1. Multi-step project management tasks where a detailed plan is needed.
    2. Executing a sequence of dependent tasks, such as data processing pipelines.
    3. Scenarios where outputs need to be evaluated and scored for quality or correctness.

**Planner Executor Template**: 

Separates planning and execution into distinct agents. The Planner Agent generates a detailed step-by-step plan, while the Executor Agent carries out each step, handling tool invocations and intermediate results. This modular approach improves adaptability and transparency in structured problem-solving.

!!! Info "Planner Executor Agent Use Case"
    When the task requires a clear separation between planning and execution, allowing for independent optimization and management of each phase.

    Examples

    1. Complex data analysis tasks where planning the analysis steps separately from execution provides clearer insights and easier debugging.
    2. Software development processes where planning the development tasks and executing them are handled by different agents, allowing for specialized optimization.
    3. Any scenario where a detailed plan is beneficial, and the execution can be carried out independently, possibly in a different environment or context.

**Meta Template**: 

Meta templates are used for agents that require higher-level reasoning or orchestration capabilities. These agents can manage other agents, coordinate tasks, or oversee complex processes, making them suitable for supervisory or managerial roles within the system.

!!! Info "Meta Agent Use Case"
    When the task requires higher-level orchestration, coordination of multiple agents, or managing complex processes.

    Examples:
    
    1. Supervising multiple agents working on different parts of a large project.
    2. Overseeing workflows that involve dynamic task allocation and coordination.
    3. Managing and optimizing resource allocation across multiple agents or tools.

**Planner Meta Template**: 

Acts as a high-level orchestrator, combining advanced planning with dynamic agent management. The Planner Meta Agent coordinates multiple specialized worker agents, delegates sub-tasks, supervises execution, and aggregates results to deliver robust solutions for complex queries.

!!! Info "Planner Meta Agent Use Case"
    When the task requires advanced planning and the coordination of multiple agents, possibly with different specializations, to achieve a complex goal.

    Examples

    1. Managing a team of agents where some are specialized in data gathering, others in analysis, and some in reporting, all working together to complete a comprehensive business intelligence task.
    2. Orchestrating a multi-agent system where agents need to collaborate, share results, and build upon each other's work in a dynamic and possibly unpredictable environment.
    3. Any scenario where complex problem-solving requires the integration of multiple specialized agents, with a need for high-level oversight and coordination.

---

## Tools

- **Tool Management**: A centralized interface is provided to manage all supported tools. This interface simplifies the process of enabling, disabling, or configuring tools, ensuring that developers have full control over the orchestration environment.
- **Custom Tool Integration**: The framework supports seamless integration of custom tools, allowing developers to onboard new tools without disrupting existing workflows. This ensures scalability and adaptability as new tools or technologies emerge.
---


### Memory

Agentic Foundry features a dual-layered memory architecture to support both short-term and long-term context retention for agents.

- **Session Memory**: Retains context-specific data during the current session, ensuring coherent and contextually relevant interactions. This is essential for multi-turn conversations and complex workflows.

- **Persistent (Long-Term) Memory**: Goes beyond the session, storing user behaviors, preferences, and historical data over time. This enables the system to provide personalized experiences, maintain long-term context, and adapt to user needs dynamically. Persistent memory is further divided into:
    - **Semantic Memory**: Stores facts, preferences, and contextual information for future reference and retrieval. Agents use semantic memory to remember user-provided details and reference past interactions. 
    - **Episodic Memory**: Captures specific query-response examples from real conversations, supporting few-shot learning and dynamic adaptation based on user feedback. Episodic memory enables agents to learn from both positive and negative conversational experiences. 

This architecture ensures that agents can leverage both immediate context and accumulated knowledge, resulting in more adaptive, user-aligned, and effective responses across all agent templates.

---

## Architecture Design 

The orchestration system architecture demonstrates seamless integration between agents, tools, and memory components. This design emphasizes modularity, scalability, and efficient data flow across all system elements.

**Key Components**

1. **Agents**: Modular entities that leverage tools and memory to execute tasks and deliver intelligent responses
2. **Tools**: Integrated utilities that extend agent capabilities and enable specialized functionality
3. **Memory**: Dual-layered system supporting both session-based context retention and persistent long-term personalization
4. **Workflow**: Streamlined data flow ensuring cohesive interactions between all components

**Design Principles**

The architecture prioritizes:

- **Modularity**: Independent components that can be developed and maintained separately
- **Scalability**: System design that adapts to growing requirements and complexity
- **Extensibility**: Framework that supports easy integration of new tools and capabilities

This design enables developers to efficiently understand, implement, and extend the orchestration framework while maintaining system coherence and performance.

---