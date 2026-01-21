# Server-Sent Events (SSE) Streaming

Server-Sent Events (SSE) is a web technology that enables real-time, one-way communication from the server to the client. In the context of the Infy Agent Framework, SSE streams each step of the agent's internal processing to the user interface as it happens, providing complete visibility into the agent's execution pipeline.

## The Importance of SSE in Agent Frameworks

Traditional agent interactions create a `black box` experience where users submit a query and wait for the final response with no insight into the agent's progress. This approach has several limitations:

- Users cannot determine if the agent is actively working, stuck, or encountering errors
- Debugging becomes difficult without visibility into the processing steps
- Long-running queries feel unresponsive and may cause users to assume the system has failed
- There's no way to monitor which tools are being executed or validate their usage

SSE streaming addresses these challenges by providing continuous updates throughout the agent's execution lifecycle. Users receive real-time information about which processing stage the agent is currently in, what tools are being called with their specific parameters, the output returned by each node, and confirmation when the agent completes each step.

This transparency significantly improves user trust by making the agent's decision-making process visible, enables faster debugging by showing exactly where issues occur, and creates a more responsive experience even for complex, multi-step workflows.

## Benefits of SSE Implementation

The implementation of SSE streaming transforms the user experience in several key ways:

- **Enhanced User Experience**: Instead of waiting for a final response with no feedback, users see each processing step unfold in real-time, creating an interactive and engaging experience.

- **Complete Visibility**: The entire agent execution pipeline becomes transparent, allowing users to understand how their query is being processed and what decisions the agent is making.

- **Improved Debugging**: When issues arise, developers and users can immediately identify where in the process the failure occurred, dramatically reducing troubleshooting time.

- **Better Perceived Performance**: Even though the actual processing time may be the same, users perceive the system as faster and more responsive because they can see continuous progress.

## Agent Templates Supporting SSE

SSE streaming has been implemented across all major agent templates in the framework, each with specific streaming nodes tailored to their execution patterns:

- **React Agent** provides streaming for Generating Context, Thinking..., Tool Call, Evaluating Response, Validating Response, and Memory Updation nodes. This template focuses on reactive decision-making with real-time tool execution visibility.

- **React-Critic Agent** extends the React template by adding a Reviewing Response node, allowing users to see both the initial agent reasoning and the subsequent critical review process.

- **Planner-Executor Agent** streams Generating Context, Generating Plan, Processing..., Replanning, Generating Response, and Memory Updation. This template emphasizes planning visibility, showing users how the agent creates and executes multi-step plans.

- **Planner-Executor-Critic Agent** combines planning with critical review, adding a Reviewing Response node to provide oversight of the planned execution.

- **Meta Agent** focuses on agent orchestration with streaming for Generating Context, Thinking..., Agent Call, Evaluating Response, and Memory Updation, allowing users to see how the meta-agent delegates tasks to sub-agents.

- **Planner-Meta Agent** merges planning with meta-agent capabilities, streaming Generating Context, Generating Plan, Agent Call, Generating Final Response, and Memory Updation to show both the planning and delegation processes.

- **Hybrid Agent** supports SSE streaming with nodes for Generating Context, Generating Plan, Processing..., Replanning, Generating Response, and Memory Updation. This pure Python-based template provides real-time visibility into both planning and execution phases within a single agent.

!!! info "SSE Event Structure and Content"
    Each SSE event transmitted to the client contains structured information designed to provide meaningful insights into the agent's current state. The events include the node name identifying the current processing stage, a status indicator showing whether the node has started, completed, or failed, and relevant content such as tool arguments, execution results, or context summaries.

## Detailed Node Descriptions

The streaming nodes represent different stages of agent processing, each serving a specific purpose in the execution pipeline:

- **Generating Context** handles the loading and summarization of conversation history, ensuring the agent has proper context for decision-making. Users can see how previous interactions influence current processing.

- **Thinking...** represents the agent's reasoning and decision-making process, showing users the internal logic and considerations that drive the agent's actions.

- **Tool Call** streams the execution of external tools or APIs, including the parameters being passed and the results returned, providing complete visibility into external system interactions.

- **Evaluating Response** occurs when response evaluation is enabled, showing users how the agent assesses the quality and appropriateness of generated responses.

- **Validating Response** provides insight into the validation process when response validation is configured, ensuring outputs meet specified criteria.

- **Reviewing Response** appears in critic-enabled agents, streaming the critical review process that evaluates and potentially improves the initial response.

- **Generating Plan** is specific to planner-based agents, showing users how multi-step plans are created and structured.

- **Processing...** streams the step-by-step execution of plans, allowing users to track progress through complex workflows.

- **Replanning** shows when and how agents revise their plans based on execution feedback, providing insight into adaptive behavior.

- **Agent Call** occurs in meta-agents when sub-agents are invoked, showing the delegation and coordination between different agent instances.

- **Generating Response** streams the final response formatting process, showing how raw outputs are refined into user-friendly responses.

- **Generating Final Response** is specific to Planner-Meta agents, combining outputs from multiple sources into a cohesive final response.

- **Memory Updation** shows when conversation history is being saved to memory, ensuring users understand when their interactions are being preserved.

## Practical Applications and Use Cases

SSE streaming proves particularly valuable in several scenarios:

- For `long-running queries`, SSE eliminates the anxiety of waiting by showing continuous progress instead of a static loading screen. Users remain engaged and confident that processing is occurring.

- In `multi-tool workflows`, SSE provides visibility into tool execution order and dependencies, helping users understand complex processing chains and identify optimization opportunities.

- For `debugging agent behavior`, SSE enables precise identification of failure points, dramatically reducing the time needed to diagnose and resolve issues.

- In `production monitoring`, SSE offers real-time visibility into agent performance, allowing administrators to detect and address issues before they impact user experience.

- For `human-in-the-loop workflows`, particularly when Tool Interrupt is enabled, SSE shows tool arguments before execution, allowing human operators to review and approve actions before they occur.

## Implementation Benefits

- The SSE implementation in the Infy Agent Framework represents a significant advancement in agent transparency and user experience. By providing real-time visibility into agent execution across all six supported templates, users gain unprecedented insight into how their queries are processed, what decisions are made, and how results are generated.

- This transparency not only improves user confidence and satisfaction but also enables more effective debugging, monitoring, and optimization of agent workflows. The consistent implementation across different agent types ensures that users can expect the same level of visibility regardless of which template best suits their needs.

- The result is a more interactive, transparent, and trustworthy agent framework that bridges the gap between complex AI processing and human understanding, making sophisticated agent capabilities accessible and comprehensible to users at all technical levels.