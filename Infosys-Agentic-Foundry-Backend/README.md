
1. Project Description 

    -Infosys Agentic Foundry is a part of Infosys Topaz and is a suite of components that helps Enterprises build reliable AI agents. It allows AI agents to be created using multiple design patterns and enables deployment either through conversational Interface or through custom UX, depending on the use cases. Infosys Agentic Foundry has been built with enterprise grade reliability as its core principle, so businesses can rely on the agents to run their reimagined processes.



2. Installation 

    # To run the project locally
    ## In command prompt run the following commands


    ### 1. To create virtual environment
        python -m venv .venv

    ### 2. To activate virtual environment
        ./.venv/Scripts/activate

    ### 3. To install all the requirements (first activate the virtual environment)
        - pip install uv
        - uv pip install -r requirements.txt



3. Usage

    -This application supports two powerful agent-based interaction templates: React Agent and Multi-Agent System. Both templates allow users to interact with agents powered by modular and extensible Python tools (functions) designed to execute specific logic.

    🤖 React Agent Mode
        -In this mode, users interact with a single intelligent agent that utilizes bound Python tools to process and respond to queries.

        🛠️ Steps:
            1.Create an Agent using the React template.

            2.Bind Tools (Python functions with custom logic) to the agent.

            3.Onboard the Agent, making it ready for interaction.

            4.Start Chatting:

                a.The user sends a query.

                b.The agent invokes the appropriate tool(s).

                c.The response is returned based on the tool’s output.

        💡 Ideal For: Simple task execution, single-function interactions, or cases where a single agent is sufficient.

    🧠 Multi-Agent System Mode
        -This mode features a collaborative agent framework with multiple specialized agents:

            🧭 Planner

            🔧 Executor

            🧪 Critic

            ♻️ Replanner (optional, for iterative refinement)

        -It also supports a Human-in-the-Loop (HITL) system for plan approval and user feedback.

        🛠️ Steps:
            1.Create a Multi-Agent Agent using the Multi-Agent template.

            2.Bind Multiple Tools across the agents:

                📌 Planner determines a step-by-step plan.

                🛠️ Executor executes steps using bound tools.

                🧠 Critic evaluates the outcome (e.g., correctness, confidence).

                🔁 Replanner (if needed) improves the plan.

            3.Enable Human-in-the-Loop (Optional):

                1.The Planner proposes a plan.

                2.The user can Like (approve) or Dislike (reject) the plan.

                3.On Dislike, the user provides feedback.

                4.The Replanner uses feedback to refine and resubmit.

                5.This loop continues until a plan is approved.

            4.Generate Final Response after successful execution or human approval.

        💡 Ideal For: Complex workflows, multi-step reasoning, decision validation, and use cases requiring human oversight and fine-tuning.

    🔄 Note: Each tool is a self-contained Python function, reusable across agents and templates — promoting modular, scalable, and flexible design.



4. Environment Variables Setup

    - Before running the application, create a `.env` file in the project root directory and add your API keys, endpoints, and database credentials as shown below:

        ```env
        AZURE_OPENAI_API_KEY=your_azure_openai_api_key
        GOOGLE_API_KEY=your_google_api_key
        AZURE_ENDPOINT=your_azure_endpoint
        ENDPOINT_URL_PREFIX=your_endpoint_url_prefix
        utility_endpoint_URL_prefix=your_utility_endpoint_url_prefix

        DATABASE_URL=your_postgres_connection_string
        POSTGRESQL_HOST=your_postgres_host
        POSTGRESQL_USER=your_postgres_user
        POSTGRESQL_PASSWORD=your_postgres_password
        DATABASE=your_database_name
        POSTGRESQL_DATABASE_URL=your_postgres_database_url

        PHOENIX_SQL_DATABASE_URL=your_phoenix_sql_database_url
        PHOENIX_COLLECTOR_ENDPOINT=your_phoenix_collector_endpoint
        PHOENIX_GRPC_PORT=your_phoenix_grpc_port
        ```

    - Replace the placeholder values with your actual credentials and endpoints.
    - **Note:** Never commit your `.env` file or sensitive credentials to version control.

    - **CORS Configuration:**  
        In `agentic_workflow_as_service_endpoints.py`, update the `origins` list to include the URL(s) and port(s) of your frontend/UI. For example, if your UI is hosted at `http://your-frontend-domain.com:3000`, add it to the list:

            ```python
            origins = [
                "http://your-frontend-domain.com" # Add your deployed frontend URL
                "http://your-frontend-domain.com:3000",  # Add your deployed frontend URL and port
                "http://127.0.0.1",
                "http://127.0.0.1:3000",
                "http://localhost",
                "http://localhost:3000"
            ]
            ```

        Replace `"http://your-frontend-domain.com:3000"` with your actual frontend address and port. This ensures the backend allows requests from your UI.



5. How to set up the dev environment

    # To run the project locally
    ## In command prompt run the following commands


    ### 1. To create virtual environment
        python -m venv .venv
    ### 2. To activate virtual environment
        ./.venv/Scripts/activate
    ### 3. To install all the requirements (first activate the virtual environment)
        pip install uv
        uv pip install -r requirements.txt


    ### 4. To run backend-server (first activate the virtual environment)
        uvicorn agentic_workflow_as_service_endpoints:app --reload
    ### 5. To run the interface (first activate the virtual environment)
        streamlit run user_interface.py

    # --------------------------------------------------------------------------------------
        
    # To run the project as server in VM
    ## In command prompt run the following commands


    ### 1. To create virtual environment
        python -m venv .venv

    ### 2. To activate virtual environment
        ./.venv/Scripts/activate

    ### 3. To install all the requirements (first activate the virtual environment)
        pip install uv
        uv pip install -r requirements.txt

    ### 4. To run backend-server (first activate the virtual environment)
        uvicorn agentic_workflow_as_service_endpoints:app --host 0.0.0.0 --port 8000 --workers 4
        
    ### 5. To run the basic user interface (first activate the virtual environment)
        streamlit run user_interface.py --server.port 8501 --server.address 0.0.0.0



6. Change Log

    [View Change Log](CHANGELOG.md)



7. License Info

    -The Open Source License the software has been released is under MIT LICENCE,
    [View LICENSE](LICENSE.md)



8. Author Info

    -Infosys
    


# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved. Infosys believes the information in this document is accurate as of its publication date; such information is subject to change without notice. Infosys acknowledges the proprietary rights of other companies to the trademarks, product names and such other intellectual property rights mentioned in this document. Except as expressly permitted, neither this documentation nor any part of it may be reproduced, stored in a retrieval system, or transmitted in any form or by any means, electronic, mechanical, printing, photocopying, recording or otherwise, without the prior permission of Infosys Limited and/or any named intellectual property rights holders under this document.
