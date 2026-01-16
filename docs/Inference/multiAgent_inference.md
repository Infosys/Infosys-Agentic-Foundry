# Multi Agent Inference

In the Multi Agent Inference setup, we offer a **Human-in-the-Loop** option. This feature allows users to review and approve each step the agent plans to execute before it proceeds. It ensures greater control, transparency and safety during the agent's decision-making process.

## Inference with Human in the Loop

The **Human-in-the-Loop** functionality provides an interactive approach to multi-agent inference, where users maintain oversight throughout the execution process. This collaborative model bridges the gap between automated agent capabilities and human judgment.

## Activation and Planning Process

Toggling on the `Human-in-the-Loop` button invokes the agent to provide a detailed plan about the steps it will perform to execute the tasks. This planning phase includes:

- **Task decomposition**: Breaking down complex queries into manageable steps
- **Resource allocation**: Identifying which agents or tools will be used for each step
- **Execution sequence**: Determining the optimal order of operations
- **Risk assessment**: Highlighting potential issues or dependencies

After the agent provides the comprehensive plan, it will ask for your approval or feedback before proceeding with execution.

## User Interaction Controls

The interface provides intuitive controls for managing the agent's execution:

**Approval Mechanism**

The `thumbs-up` button serves as the approval mechanism. Clicking this button:
- Approves the plan proposed by the agent
- Signals the agent to proceed with executing your query
- Initiates the execution phase with the current plan

**Feedback and Iteration**

The `thumbs-down` button enables the feedback loop. Clicking this button:

- Prompts you to provide specific feedback on the generated plan
- Allows you to highlight concerns, suggest modifications, or request clarifications
- Triggers the agent to regenerate the plan incorporating your feedback
- Maintains an iterative improvement cycle until approval is granted

**Monitoring and Evaluation**

You can view the critic score of the response by clicking the "Steps" dropdown. This feature provides:

- **Quality metrics**: Numerical scores indicating the confidence level of each step
- **Performance indicators**: Success probability assessments for different components
- **Transparency insights**: Detailed breakdowns of the agent's reasoning process
- **Decision rationale**: Explanations for why specific approaches were chosen

This comprehensive monitoring system ensures that users have full visibility into the agent's decision-making process and can make informed decisions about proceeding with the proposed plan.
