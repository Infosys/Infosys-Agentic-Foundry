# Human Involvement in Agentic Frameworks

Human-in-the-loop (HITL) is a system design approach where human input, oversight, or decision-making is integrated into an automated or AI-driven process to improve accuracy, safety, or control.

In the Agentic Foundry Framework, HITL is included as a core element of the **Multi Agent**, ensuring that humans can guide or intervene in agent behavior when necessary.

---

## Overview: Human Intervention in AI Systems

Human intervention refers to the active or passive role a human plays during the lifecycle of an AI or agent system. In our framework, this intervention is integrated at multiple stages:

- **Design phase**: Humans select and configure tools that the agent will use, establishing the foundational parameters and capabilities that guide agent behavior.
- **Execution phase**: Humans monitor outputs and provide real-time feedback, ensuring quality control and appropriate responses to dynamic situations.
- **Learning phase**: Humans review performance metrics and provide training examples to continuously refine agent capabilities and improve future performance.

The goal is to combine the speed and efficiency of automation with the contextual understanding, judgment, and oversight that only humans can provide, creating a collaborative intelligence system.

---

## Human-in-the-Loop (HITL)

In this mode, humans are an essential part of the decision-making process. The agent does not proceed without human input at critical steps. This ensures high accuracy and safety, especially in sensitive or high-stakes domains where automated decisions could have significant consequences.

**Application in the Framework**

- During inference, the agent generates draft responses that undergo human review before finalization, ensuring quality and appropriateness of outputs.
- During tool onboarding, users manually select and curate data sources, tools, and prompts, establishing the operational parameters for agent functionality.
- Continuous monitoring allows for real-time adjustments and intervention when agent behavior deviates from expected parameters.

**Typical Use Cases**

- Domains requiring high precision and regulatory compliance, such as healthcare diagnostics, legal document review, or financial analysis.
- Tasks where incorrect or biased outputs could have serious consequences, including content generation for public consumption or automated decision-making systems.
- Content moderation or generation workflows where human approval is mandatory due to organizational policies or legal requirements.

**Workflow**

1. The user submits a query or task to the agent system, initiating the collaborative process.
2. The agent processes the input and generates a preliminary output, such as a detailed step-by-step plan or draft response based on the user query and available tools.
3. The human reviewer evaluates the preliminary output and makes a decision:
    - **Approve**: If the user approves the plan, the agent finalizes the output, applies any necessary formatting, and returns the completed response.
    - **Reject**: If the user rejects the plan, they provide specific feedback detailing issues, concerns, or required modifications. The agent utilizes a replanner mechanism to regenerate a revised plan that addresses the feedback.
4. This review cycle continues until the human approves the output, ensuring the final response meets quality standards and user expectations before delivery.

