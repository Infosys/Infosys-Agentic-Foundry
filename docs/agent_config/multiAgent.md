# Multi Agent Configuration

The **Multi Agent** operates on the **Planner-Executor-Critic** paradigm. It begins with a **Planner Agent** that generates a step-by-step plan based on the user query. The **Executor Agent** then executes each step of the plan. The **Critic** evaluates the outputs by scoring the results of each step.

<!-- #### **Multi AI Agent**

<div style="display: flex; justify-content: space-around; align-items: center;">

  <div style="text-align: center; margin-right: 10px;">
    <img src="../images/Multi_without_feedback.png" alt="Without Feedback" width="300"/>
    <p><strong>Multi Agent Without Feedback</strong></p>
  </div>

  <div style="text-align: center; margin-right: 10px;">
    <img src="../images/Multi_with_feedback.png" alt="With Feedback" width="300"/>
    <p><strong>Multi Agent With Feedback</strong></p>
  </div>

</div> -->


### **Multi Agent Onboarding**

The following are the steps for onboarding a Multi Agent with an example:

1. **Select Template**: Select agent template.

    * `Agent Template`  MULTI AGENT
![Agents Template1](../images/Agent_types1.png)

2. **Select Tools**: from the listed tools - select the tool/s using which we want to create the agent.

    * `Tools`   get_weather

3. **Agent Name**:  Provide a suitable agent name. 

    * `Agent Name`  Weather Agent1

4. **Agent Goal**:  Provide goal of the agent - objective of the agent.

    * `Agent Goal` This agent provides personalized suggestions based on real-time weather data.

5. **Workflow description**: Provide detailed instructions to the LLM - Guidelines to the agent. 

     * `Sample Workflow description`:

        > Understand the user intent and perform following steps:
        >
        > 1. Retrieve Weather Data - Make an API call to fetch real-time weather data.
        > 2. Analyze Weather Conditions - Evaluate the weather data to determine current conditions.
        > 3. Generate Recommendations - Based on the analysis, provide personalized suggestions to the user. 
        >
        >  For example:
        >  If the weather is pleasant, suggest outdoor activities.
        >  If the weather is rainy or stormy, advise the user to carry an umbrella or avoid traveling.
        >  If extreme weather conditions are detected, recommend staying indoors and taking necessary precautions.


6. **Model Name**: Select the model name from the dropdown - which is used to create **system prompt** based on provided Agent goal and Workflow description. 
![Multi Agent Creation](../images/Multi_agent.png)


**System Prompt**:

Using the provided agent goal and workflow description, LLM generates system prompts for the planner, executor, and critic agents within a multi-agent template.

![Multi Agent System Prompt](../images/Multi_agent_system_prompts.png)


---

### **Agent Updation**

Agent Updation is similar to [React Agent Updation](reactAgent.md#agent-updation)


### **Agent Deletion**

Agent Deletion is similar to [React Agent Deletion](reactAgent.md#agent-deletion)



