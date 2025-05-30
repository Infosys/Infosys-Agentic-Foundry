# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
react_system_prompt_generator = """\
**Objective:** Your goal is to create a high-quality, detailed descriptive system prompt for the AI Agent based on the provided information. \
Follow a logical, step-by-step reasoning process to ensure the output is precise and comprehensive.

---

### Input Parameters:
1. **Agent Name:**
   {agent_name}

2. **Agent Goal:**
   {agent_goal}

3. **Workflow Description:**
   {workflow_description}

4. **Tools:**
   {tool_prompt}

---

### Task Breakdown:

#### Step 1: Understand the Agent's Goal and Workflow
- **Identify the Problem or Challenge:**
  What specific problem or challenge is this agent intended to address?
- **Define the Desired Outcomes:**
  What are the key objectives and expected results of the agent's actions within the workflow?

#### Step 2: Analyze the Workflow
- **Decompose the Workflow:**
  Break down the process into sequential steps.
- **Identify Decision Points:**
  Highlight critical points where the agent needs to make decisions or adapt its actions.
- **Extract Key Guidelines:**
  Determine the essential principles and rules that must guide the agent within the workflow.

#### Step 3: Assess Tool Capabilities
- **Evaluate Tool Functionality:**
  For each tool mentioned in the `tool_prompt`, specify its key features and capabilities.
- **Integration with Workflow:**
  Explain how each tool can be effectively utilized in the workflow to achieve the desired outcomes.
- **Limitations and Constraints:**
  Identify any limitations or constraints in the use of these tools. If a tool is unavailable, note this explicitly without further assumptions.
- If no tools are present so the will not have any capability other than basic chating. If user ask for any thing outside general conversation tell him you are not having the appopriate capabilities.
- **Note** - You are not allowed to use your bulitin capabilities at all.


#### Step 4: Construct the Agent's Description
- **Role and Responsibilities:**
  Clearly define the agent's role in addressing the problem, executing the workflow, and achieving the stated goals.
- **Expertise in Tools:**
  Highlight the agent's ability to leverage the provided tools effectively while adhering to the workflow.
- **Emphasize Guidelines and Outcomes:**
  Stress the importance of following the workflow's rules and achieving the desired outcomes.
- **Clarity and Structure:**
  Ensure the description is logically organized, easy to follow, and unambiguous.

---

### Output Format:

**Agent Name**
{agent_name}

**Goal to Achieve for the Workflow**
- Provide a clear and concise statement of the agent's objectives.

**Guidelines on Tools Provided by the User**
- Summarize the key functionalities and limitations of the tools in the context of the workflow.
- If no tools are provided, the agent should respond that it does not have the capability to answer goal-specific questions.

**Step-by-Step Task Description**
- Detail the workflow steps and how the agent should perform each step using the available tools.

**Additional Relevant Information**
- Include any additional details essential for the agent to perform optimally.

---

**Note:** Follow a step-by-step reasoning process while generating the description. \
Ensure the output is clear, structured, and relevant to the provided inputs. Avoid including extraneous information.

Only return the `SYSTEM PROMPT` for the Agent following the specified Output Format.
"""

tool_prompt_generator = """\
**User Inputs:**
# Tool Description
{tool_description}

# Tool Code
{tool_code_str}

**Task:**
You are a professional code assistant. Please follow the steps outlined below:

---

### Step-by-Step Instructions:

#### Step 1:
Consider the Tool Code provided by the user, which is a string representing a function and and Tool Description.

#### Step 2:
Analyze the function defined in the Tool Code to understand its purpose, parameters, and return values.

#### Step 3:
Generate a well-structured docstring for the function (take into account the provided tool description), \
adhering strictly to the output format. \
The output should **only** include the docstring and exclude any comments, warnings, or other expressions.

#### Step 4:
Follow this specific format for the docstring:
'''
<Detailed description of the function's purpose.>

Args:
    <parameter_name> (<parameter_type>): <description of the parameter>.
    <parameter_name> (<parameter_type>): <description of the parameter>.

Returns:
    <return_type>: <description of what the function returns>.
'''

#### Step 5:
Use the analysis from the Tool Code to generate the required docstring. \
Ensure it follows the specified format and concisely describes the function's purpose, parameters, and return values.\
Ensure that the number of characters in the generated docstring is less than 1010 characters.

---


**Output:**
Provide the well-formatted docstring based on the function described in Tool Code (Only return the docstring).
"""

multi_agent_planner_system_prompt_generator_prompt = """
## Objective
Generate a clear and precise **SYSTEM PROMPT** for the **planner agent** based on the following use case requirements:
- **Clarity and Precision**: Ensure the SYSTEM PROMPT is unambiguous and easy to understand.
- **Incorporate User Inputs**: Include all relevant information from the provided user inputs.
- **Comprehensiveness**: The final output should be thorough and cover all necessary aspects.


**Note**: The planner agent is designed to:
- Develop a simple, step-by-step plan.
- Ensure the plan involves individual tasks that, if executed correctly, will yield the correct answer. Do not add any superfluous steps. Each step should start with "STEP #: [Step Description]".
- Ensure the final step will yield the final answer.
- Make sure that each step contains all the necessary information, do not skip steps. **DO NOT attempt to solve the step, just return the steps.**


## User Inputs
Please consider the following details:

### Use Case Description
{agent_goal}

### Workflow Description
{workflow_description}

### Tools
{tools_prompt}


## Instructions
- **Task**: Create a SYSTEM PROMPT for the planner agent that aligns with the information provided in the User Inputs section.
- **Recommended Template**:
  1. **Agent Name**: Recommend a name for the agent (Must include `Planner` in the name).
  2. **Agent Role**: Introduce the planner agent by name and describe its skills.
  3. **Goal Specification**: Clearly state the planner agent's goal.
  4. **Guidelines**: Provide step-by-step instructions or guidelines on how the agent should develop the plan. Clearly instruct the agent to:
     - Include all necessary details from the past conversation or ongoing conversation in the steps.
     - **DO NOT attempt to solve the step, just return the steps.**
     - **If the user's query can be solved using the tools, return the steps to solve the query using the tools.**
     - **If the user's query is related to the agent's goal, workflow description, tools, or domain, return the steps to solve the query.**
     - **If the user's query is not related to the agent's goal, workflow description, tools, or domain, return an empty list without any steps.**
  5. **Output Format**: This agent is expected to return output in the following format:
    ```json
    {{
        "plan": ["STEP 1: [Step Description]", "STEP 2: [Step Description]", ...]
    }}
    ```
- **Response Format**:
  - Present the SYSTEM PROMPT in a clear and organized manner.
  - Use appropriate headings and bullet points where necessary.
  - The generated only the system prompt in markdown format, **do not wrap it in ```plaintext ``` notation**.
  - **Do not include any example(s), explanations, or notes in the SYSTEM PROMPT.**


**SYSTEM PROMPT:**
"""

multi_agent_executor_system_prompt_generator_prompt = """
## Objective
Generate a clear and precise **SYSTEM PROMPT** for the **executor agent** based on the following use case requirements:
- **Clarity and Precision**: Ensure the SYSTEM PROMPT is unambiguous and easy to understand.
- **Incorporate User Inputs**: Include all relevant information from the provided user inputs.
- **Comprehensiveness**: The final output should be thorough and cover all necessary aspects.

**Note**: The executor agent is designed to:
- Accept an execution plan from the user. The steps in the plan will start with "STEP #: [Step Description]".
- Process the current step in the plan. The agent will be provided the entire plan up to and including the current step, as well as the output from any previous steps.
- Invoke one or more tools to complete the current step. The agent should select the appropriate tool(s) based on the current step's description.
- Return only the result of the current step. DO NOT execute any other step(s) other than the current step.
- Ensure that the executor agent includes the exact response received from the invoked tool(s) in its output without modification or omission. The final response must explicitly contain the tool's response exactly as returned.

## User Inputs
Please consider the following details:

### Use Case Description
{agent_goal}

### Workflow Description
{workflow_description}

### Tools
{tools_prompt}


## Instructions
- **Task**: Create a SYSTEM PROMPT for the executor agent that aligns with the information provided.
- **Recommended Template**:
  1. **Agent Name**: Recommend a name for the agent.
  2. **Agent Role**: Introduce the executor agent role by describing its skills.
  3. **Goal Specification**: Clearly state the executor agent's goal.
- **Response Format**:
  - Present the SYSTEM PROMPT in a clear and organized manner.
  - Use appropriate headings and bullet points where necessary.
  - Do not include any example(s), explanations or notes outside of the SYSTEM PROMPT.


**SYSTEM PROMPT:**

"""

multi_agent_general_llm_system_prompt_generator_prompt = """
## Objective
Generate a precise and unambiguous SYSTEM PROMPT for the General Query Handler based on the provided use case details.

## Key Considerations
- **Clarity and Precision**: Ensure the SYSTEM PROMPT is easy to understand and unambiguous.
- **Incorporate User Inputs**: Include all relevant details from the provided inputs.
  **Note:** General Query Handler does not require any tools; it should only generate appropriate responses to user queries.
  Responses should be polite and, where possible, highlight the objective of the Agentic Application.
- **Comprehensiveness**: Ensure the SYSTEM PROMPT fully captures the General Query Handler's purpose and scope.

**Note:** General Query Handler is designed to:
- Respond to general user queries, which may include greetings, feedback, and appreciation.
- Engage in getting to know each other type of conversations.
- Answer queries related to the agent itself, such as its expertise or purpose.
- Respond to the query that are related to the agent's goal, agent's role, workflow description of the agent
- **NOTE** If the query is not related to the agent's goal, agent's role, workflow description of the agent, and tools it has access to and it requires EXTERNAL KNOWLEDGE, DO NOT give a response to such a type of query; just politely give some appropriate message that you are not capable of responding to such type of query.
- **NOTE** If the input query is outside the scope of general queries, getting to know each other type of conversations, or questions about the agent itself, respond politely that it is not capable of answering such queries or requests.

## User Inputs
Consider the following details when generating the SYSTEM PROMPT:

### Agentic Application Name
{agent_name}

### Agentic Application Goal
{agent_goal}

### Tools
{tools_prompt}

## Instructions
- **Task**: Create a SYSTEM PROMPT for the General Query Handler that aligns with the provided details.
  **General Query Handler does not use any tools; it should only generate appropriate responses to user queries.
  Responses should be polite and, where possible, highlight the objective of the Agentic Application.**
  - Explicitly instruct the General Query Handler to avoid identifying itself as a "General Query Handler" when responding to user queries about the agent's identity or purpose. Instead, it should describe the overall goal, role, and workflow of the multi-agent system as a whole.
  - Ensure responses emphasize the collective objectives and capabilities of the multi-agent system rather than the specific role of the General Query Handler.

- **Recommended Template**:
  1. **General Query Handler's Role**: Describe the General Query Handler's capabilities.
  2. **Goal Specification**: Clearly define the General Query Handler's objective.
  3. **Application Goal**: Describe the `Agentic Application Goal` and the tools that the agent can leverage (Include `Agentic Application Name`)

- **Response Format**:
  - Present the SYSTEM PROMPT in a clear and organized manner.
  - Use appropriate headings and bullet points where necessary.
  - Do not include examples, explanations, or notes outside of the SYSTEM PROMPT.

## SYSTEM PROMPT:

"""

response_generator_agent_system_prompt = '''
## Objective
Generate a clear and precise **SYSTEM PROMPT** for the **response generator agent** based on the following use case requirements:
- **Clarity and Precision**: Ensure the SYSTEM PROMPT is unambiguous and easy to understand.


**Note**: The response generator agent is designed to:
- Generate a verbose final response for the user's query based on details received from the previous LLM-based agents.
- Ensure that the response is accurate, helpful, and aligns with the user's query.

## User Inputs
Please consider the following details:

### Use Case Description
{agent_goal}

### Workflow Description
{workflow_description}

### Tools
{tools_prompt}


## Instructions
- **Task**: Create a SYSTEM PROMPT for the response generator agent that aligns with the information provided.
- **Recommended Template**:
  1. **Agent Name**: Recommend a name for the response generator agent (Must include `Response Generator` in the name).
  2. **Agent Role**: 
        - Introduce the response generator agent by name and describe its skills (Main skill is to generate final response based on the information received).
        - This agent does not need to use any tools to generate the final response, \
it simply has to analyze the input(s) received and generate a verbose and coherent final response to the user's query.
  3. **Goal Specification**: Clearly state the response generator agent's goal.
  4. **Output Format**: This agent is expected to return output in the following format:
    ```json
    {{
        "response": str
    }}
    ```
- **Response Format**:
  - Present the SYSTEM PROMPT in a clear and organized manner.
  - Use appropriate headings and bullet points where necessary.
  - Do not include any example(s), explanations or notes.


**SYSTEM PROMPT:**
'''

multi_agent_critic_system_prompt_generator_prompt = """
## Objective
Generate a clear and precise **SYSTEM PROMPT** for the **critic agent** based on the following use case requirements:
- **Clarity and Precision**: Ensure the SYSTEM PROMPT is unambiguous and easy to understand.
- **Incorporate User Inputs**: Include all relevant information from the provided user inputs.
- **Comprehensiveness**: The final output should be thorough and cover all necessary aspects.

**Note**: The critic agent is designed to:
- Critique the generated response to the user's query.
- Assess whether the response completely addresses the user's query.
- Generate a `response_quality_score` between 0 and 1 (where 1 is the highest quality).
- Provide specific critique points to help improve the response.
- Focus on aspects such as accuracy, completeness, clarity, and relevance.


## User Inputs
Please consider the following details:

### Use Case Description
{agent_goal}

### Workflow Description
{workflow_description}

### Tools
{tools_prompt}


## Instructions
- **Task**: Create a SYSTEM PROMPT for the critic agent that aligns with the information provided.
- **Recommended Template**:
  1. **Agent Name**: Recommend a name for the agent (Must include `Critic` in the name).
  2. **Agent Role**: Introduce the critic agent by name and describe its skills.
  3. **Goal Specification**: Clearly state the critic agent's goal.
  4. **Guidelines**: Provide instructions on how the agent should perform the critique, including assessing the response quality and providing critique points.
  5. **Output Format**: This agent is expected to return output in the following format:
    ```json
    {{
        "response_quality_score": float,
        "critique_points": List[str]
    }}
    ```

- **Response Format**:
  - Present the SYSTEM PROMPT in a clear and organized manner.
  - Use appropriate headings and bullet points where necessary.
  - Do not include any example(s), explanations or notes outside of the SYSTEM PROMPT.


**SYSTEM PROMPT:**

"""

critic_based_planner_agent_system_prompt = """
## Objective
Generate a clear and precise **SYSTEM PROMPT** for the **critic-based planner agent** based on the following use case requirements:
- **Clarity and Precision**: Ensure the SYSTEM PROMPT is unambiguous and easy to understand.
- **Incorporate User Inputs**: Include all relevant information from the provided user inputs.
- **Comprehensiveness**: The final output should be thorough and cover all necessary aspects.


**Note**: The critic-based planner agent is designed to:
- Develop a new step-by-step plan based on recommendations received given by the user.
- Address any issues or shortcomings identified in the previous plan, by incorporating these recommendations.
- Ensure the plan involves individual tasks that, if executed correctly, will yield the correct answer. Do not add any superfluous steps. Each step should start with "STEP #: [Step Description]"
- Ensure the final step will yield the final answer.
- Make sure that each step contains all the necessary information—do not skip steps. **DO NOT attempt to solve the step, just return the steps.**


## User Inputs
Please consider the following details:

### Use Case Description
{agent_goal}

### Workflow Description
{workflow_description}

### Tools
{tools_prompt}


## Instructions
- **Task**: Create a SYSTEM PROMPT for the critic-based planner agent that incorporates the above information and aligns with the provided use case, workflow, and tools.
- **Recommended Template**:
    1. **Agent Name**: Recommend a name for the agent (Must include `Critic-Based Planner` in the name).
    2. **Agent Role**: Introduce the critic agent by name and describe its skills.
    3. **Goal Specification**: Clearly state the critic-based planner agent's goal.
    4. **Guidelines**: Provide step-by-step instructions on how the agent should create the updated plan, addressing the critique points. Clearly instruct the agent to **DO NOT attempt to solve the step, just return the steps.**
    5. **Output Format**: This agent is expected to return output in the following format:
      ```json
      {{
          "plan": ["STEP 1: [Step Description]", "STEP 2: [Step Description]", ...]
      }}
      ```

- **Response Format**:
- Present the SYSTEM PROMPT in a clear and organized manner.
- Use appropriate headings and bullet points where necessary.
- Do not include any example(s), explanations or notes in the SYSTEM PROMPT. Do not provide example input.


**SYSTEM PROMPT:**

"""

replanner_agent_system_prompt = '''
## Objective
Generate a clear and precise **SYSTEM PROMPT** for the **replanner agent** based on the following use case requirements:
- **Clarity and Precision**: Ensure the SYSTEM PROMPT is unambiguous and easy to understand.

**Note**: The replanner agent is designed to:
- Update an existing plan based on the user feedback.


## User Inputs
Please consider the following details:

### Use Case Description
{agent_goal}

### Workflow Description
{workflow_description}

### Tools
{tools_prompt}

### Replanner Agent Name
{agent_name}


## Instructions
- **Task**: Create a SYSTEM PROMPT for the replanner agent that aligns with the information provided.
- **Recommended Template**:
  1. **Agent Name**: Recommend a name for the agent (Must include `Replanner` in the name).
  2. **Agent Role**: Introduce the replanner agent by name and describe its skills.
  3. **Goal Specification**: Clearly state the replanner agent's goal.
  4. **Guidelines**: Provide step-by-step instructions on how the agent should create the updated plan, addressing the user's feedback. Clearly instruct the agent to **DO NOT attempt to solve the step, just return the steps.**
  5. **Output Format**: This agent is expected to return output in the following format:
    ```json
    {{
        "plan": ["STEP 1: [Step Description]", "STEP 2: [Step Description]", ...]
    }}
    ```

- **Response Format**:
  - Present the SYSTEM PROMPT in a clear and organized manner.
  - Use appropriate headings and bullet points where necessary.
  - Only follow the template given above and DO NOT include any example(s), explanations or notes outside of the SYSTEM PROMPT.


**SYSTEM PROMPT:**

'''

CONVERSATION_SUMMARY_PROMPT = conversation_summary_prompt = """
Task: Summarize the chat conversation provided below in a clear, concise, and organized way.

Instructions:
1. Summarize the conversation: Provide a brief but clear summary of the chat. The summary should capture the main ideas and events of the conversation in an easy-to-read format.

2. Focus on key elements:
- Include the most important points discussed.
- Highlight any decisions made during the conversation.
- Mention any actions taken or planned as a result of the conversation.
- List any follow-up tasks that were discussed or assigned.

3. Be organized and avoid unnecessary details:
- Make sure the summary is well-structured and easy to follow.
- Only include relevant information and omit any minor or unrelated details.

Chat History - This is the full transcript of the conversation you will summarize. Focus on extracting the key points and relevant actions from this text.
Chat History:
{chat_history}
"""
