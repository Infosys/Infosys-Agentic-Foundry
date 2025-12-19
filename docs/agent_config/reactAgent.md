The **ReAct(Reasoning and Acting)** agent combines reasoning traces with action execution. It uses a step by step thought process to determine what tool to use, executes it, observe the result, and continues until it can return a final answer.

---

### **React Agent Onboarding**

To create a React agent, you'll begin by selecting the REACT AGENT template from the available options. 

Next, you'll choose the specific tools your agent needs from the provided list to effectively perform its intended tasks. You'll then assign a descriptive name that clearly represents your agent's purpose and function. 

After naming your agent, you'll define its primary goal and objective, explaining what the agent is designed to accomplish. 

Finally, you'll provide comprehensive workflow instructions that detail how the agent should handle requests and execute its tasks, giving it clear guidelines for processing and responding to user interactions.

!!! info "Sample Workflow description"
        Understand the user intent and perform following steps:

        1. Retrieve Weather Data - Make an API call to fetch real-time weather data.
        2. Analyze Weather Conditions - Evaluate the weather data to determine current conditions.
        3. Generate Recommendations - Based on the analysis, provide personalized suggestions to the user. 
    
        For example:
        If the weather is pleasant, suggest outdoor activities.
        If the weather is rainy or stormy, advise the user to carry an umbrella or avoid traveling.
        If extreme weather conditions are detected, recommend staying indoors and taking necessary precautions.

Select the model name - which is used to create `system prompt` based on provided Agent goal and Workflow description.

**System Prompt**:

Final guidelines for the agent - created by LLM based on provided Agent goal and Workflow description for the agent.

!!! info "Sample Generated System Prompt"

    **Agent Name**  
    Weather Agent

    **Goal to Achieve for the Workflow**  
    - The Weather Agent aims to provide personalized suggestions to users based on real-time weather data, enhancing their daily decision-making regarding activities and safety precautions.

    **Guidelines on Tools Provided by the User**  
    - **Tool Name:** get_weather_new  
    - **Key Functionalities:** This tool retrieves real-time weather data for a specified city using the OpenWeatherMap API. It provides details such as temperature, humidity, pressure, and a brief weather description.
    - **Limitations:** The tool requires a valid API key and city name to function. It returns an error message if the HTTP request fails, indicating potential issues with network connectivity or incorrect parameters.


    **Step-by-Step Task Description**  
    1. **Retrieve Weather Data:**  
    - Use the `get_weather_new` tool to make an API call with the provided API key and city name.
    - Ensure the tool successfully fetches the weather data, including temperature, humidity, pressure, and weather description.

    2. **Analyze Weather Conditions:**  
    - Evaluate the retrieved weather data to determine current conditions.
    - Identify key weather attributes such as temperature range, humidity levels, and specific weather phenomena (e.g., rain, storm).

    3. **Generate Recommendations:**  
    - Based on the analysis, provide personalized suggestions to the user:
        - If the weather is pleasant, suggest outdoor activities.
        - If the weather is rainy or stormy, advise the user to carry an umbrella or avoid traveling.
        - If extreme weather conditions are detected, recommend staying indoors and taking necessary precautions.

    **Additional Relevant Information**  
    - The agent should ensure the recommendations are timely and relevant to the user's location and current weather conditions.
    - In case of tool failure or unavailability, the agent should inform the user of the inability to provide weather-based suggestions and recommend checking weather updates through other means.

---
### **Agent Updation**

After creating your React agent, you can modify its configuration as needed:

**1. Add Tools**

- Navigate to agent configuration
- Select "Add Tools" and choose from available tools
- System automatically updates capabilities and regenerates system prompt

**2. Remove Tools**

- Access current tool configuration
- Select "Remove Tools" and choose tools to remove
- Confirm removal - system prompt updates automatically

**3. Update Workflow Description**

- Select "Update Workflow" 
- Edit workflow description with new instructions
- System regenerates system prompt based on changes

!!! warning "Update Permissions"
    Only the original creator can update the agent configuration.


### **Agent Deletion**

To delete an agent:

1. Go to agent dashboard
2. Select the agent you want to delete
3. Enter the creator's email address
4. Click "Delete Agent"

To delete an agent, you need to provide the creator's email address.

!!! warning "Important"
    Only the original creator can delete the agent.









