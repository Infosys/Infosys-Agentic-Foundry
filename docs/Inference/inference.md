# Inference

## What is Inference?

Inference is the section where you can interact with the agents you have created through a chat interface. It allows you to select and model, initiate a conversation, and observe how the agent responds bsed on its reasoning.

## Steps to onboard Agent in Inference
This guide walks you through the steps required to run an inference using our framework.

<h2 style="color: black;">Step 1: Select an Agent Type</h2>

From the dropdown menu, choose the agent type.

Available Agent Types:

- **React Agent**
- **React Critic Agent**
- **Multi Agent**
- **Planner Executor Agent**
- **Meta Agent**
- **Meta Planner Agent**

<h2 style="color: black;">Step 2: Select a Model Type</h2>

After selecting the agent type, pick a model type that the agent will use.

Available Model Types:

- **GPT4-8k**
- **GPT-4o-mini**
- **GPT-4o**
- **GPT-4o-2**
- **GPT-4o-3**
- **Gemini-1.5-Flash**

<h2 style="color: black;">Step 3: Select the Agent</h2>

Finally, choose the specific agent from the dropdown.

## Chat Interface Features

The inference interface offers several features to enhance your interaction experience:

**Interface Options**

The main interface includes interactive elements for improved usability:

- **Prompt Suggestions**: Provides intelligent recommendations for queries to streamline interactions.
- **Toggle Settings**: Allows customization of the chat experience, including options for canvas view, context flag, and other preferences.
- **Temperature Settings**: Lets you adjust the model's temperature (from 0 to 1) to control the creativity and randomness of responses.
- **Knowledge Base**: Enables access to integrated knowledge resources to support agent responses.
- **Chat Options**: Includes controls for starting new chats, viewing chat history, and managing sessions.
- **Live Tracking**: Offers real-time monitoring of agent activities with Phoenix integration.

**1. Prompt Suggestions**

Smart prompt suggestions help you interact more efficiently by providing contextual recommendations for queries.

**2. Toggle Settings**

You can configure your chat experience with toggle options for canvas view, context flag, and other interface preferences.

- **Tool Verifier:**

    The Tool Interrupt feature allows you to verify and control tool executions during agent interactions.

- **Validators:**

    The Validator feature allows you to validate agent responses using custom logic. You can enable the validator toggle in the chat interface to activate this feature for supported agent templates.

    Supported Agent Templates:

    `React`, `React Critic`, `Planner Executor Critic`, `Planner Executor`, `Meta`, `Planner Meta`

    **Onboarding a Validator**

    - Go to the Tools page and select the `Validator` option.
    - Provide a code snippet for the validator. The code must include functions with the arguments `query` and `response`, and should return a `validation score`, `validation status`, and `feedback` regarding the response's compliance with expected formats.

    **Adding Validation Patterns to Agents**

    To add validation patterns, click the `plus (+) icon` in the agent onboarding interface. 
    For each pattern:

    - Provide a sample query and a generic expected response.
    - Select a validator for the pattern, or choose "None" if not required.
    - You can add one or more validation patterns per agent.

    **Using the Validator in Chat Inference**

    - Enable the `Validator` toggle in the chat interface.

    **How it works**:

    - When a user submits a query, the system checks for semantic similarity with existing validation patterns.
    - If a matching pattern is found and a validator is assigned, the validator runs and returns a validation score, status, and feedback.
    - If no validator is assigned to the matched pattern, the system performs a standard LLM call and returns a validation score, status, and feedback.
    - For Planner Executor Critic and Planner Executor templates, validation results are sent to the replanner agent, which generates the response.
    - For React and React Critic templates, the agent receives the validation results and regenerates its response based on the feedback.

    This workflow ensures agent responses are evaluated and improved in real time, enhancing reliability and interaction quality.

- **Canvas View:**

    Provides a comprehensive visual overview of agent interactions and workflows.

- **Context Flag:**

    When disabled, the agent operates without memory retention, treating each query as an independent interaction without access to past conversations or memory data.

- **Online Evaluator:**

    The Online Evaluator assesses the quality of agent responses in real time:

    1. When you submit a query, the agent's response is evaluated for quality.
    2. If the score is below 0.75, feedback is provided and the response is regenerated.
    3. This process repeats until the response achieves a score of 0.75 or higher.
    4. Only then is the final response presented to you.

**3. Temperature Settings**

The temperature setting controls the randomness and creativity of responses. Lower values make replies more focused and deterministic, while higher values increase creativity and variability. Adjust the temperature slider to fine-tune agent behavior.

**4. Knowledge Base Integration**

Integrated knowledge base resources are available to enhance agent responses and provide additional information.

**5. Chat Options and Chat History**

You can manage chat sessions with options for starting new chats, accessing chat history, and controlling session settings.

**6. Context Agent**

The Context Agent feature allows you to add an additional agent to your chat session using the "@" button in the chat interface. This enables you to train the context agent on the main agent’s queries and responses, enhancing its ability to understand and respond based on ongoing conversation data.

**How to Use the Context Agent**

1. **Activate Context Agent**  
    - Click the "@" icon in the chat screen to open the context agent selection menu.
    - Select the desired agent type and agent name. The context agent supports all available agent templates.

2. **Session Awareness**  
    - When you activate a context agent during an ongoing chat, it inherits the current session's conversation data. This means the context agent is aware of previous queries and responses, allowing it to respond appropriately.

3. **Interact with Context Agent**  
    - Once activated, all subsequent queries will be handled by the selected context agent until you disable it by clicking the "@" icon again.
    - The context agent becomes active within the chat interface, indicated by visual confirmation in the interface.
    - The context agent responds to queries that reference the ongoing session, using previous conversation history to generate context-aware and relevant responses.
    - This demonstrates the agent's ability to maintain continuity and provide informed answers based on prior interactions from the current chat session.
        
This feature enables seamless switching between agents and ensures that the context agent maintains awareness of the conversation, providing relevant and informed responses.

## React Agent Inference

**[React Agent](reactAgent_inference.md)**
The React Agent inference is a simple chat window where you can chat with the agent you have onboarded and can see the steps taken by the agent to answer your queries.

## React Critic Agent Inference

**[React Critic Agent](ReactCriticAgent_inference.md)**
The React Critic Agent inference provides a chat interface with enhanced transparency, showing both the agent's reasoning and the critic's evaluation at each step.

## Multi Agent Inference

**[Multi Agent](multiAgent_inference.md)**
In the Multi Agent Inference setup, we offer a **Human-in-the-Loop** option. This feature allows users to review and approve each step the agent plans to execute before it proceeds.

## Planner Executor Agent Inference

**[Planner Executor Agent](PlannerExecutorAgent_inference.md)**
This inference mode displays the planner, executor, and critic steps, providing detailed insight into each stage of the workflow.

## Meta Agent Inference

**[Meta Agent](metaAgent_inference.md)**
The Meta Agent inference offers a chat interface similar to the React Agent. It allows you to interact with the onboarded agent and view the steps it takes to process your queries, providing transparency into its decision-making process.

## Meta Planner Agent Inference

**[Meta Planner Agent](metaAgent_inference.md)**
The Meta Planner Agent inference showcases multi-level orchestration, displaying the planner, supervisor, and response generation steps for advanced agent workflows.

## Hybrid Agent Inference

**[Hybrid Agent](HybridAgent_inference.md)**
The Hybrid Agent inference combines features from multiple agent types, enabling flexible reasoning and decision-making. It provides a chat interface where you can observe both collaborative and independent agent actions, offering a comprehensive view of hybrid workflows.
