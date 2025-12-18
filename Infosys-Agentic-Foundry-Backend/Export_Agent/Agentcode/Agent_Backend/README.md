
1. Project Description 

    -Infosys Agentic Foundry is a part of Infosys Topaz and is a suite of components that helps Enterprises build reliable AI agents. It allows AI agents to be created using multiple design patterns and enables deployment either through conversational Interface or through custom UX, depending on the use cases. Infosys Agentic Foundry has been built with enterprise grade reliability as its core principle, so businesses can rely on the agents to run their reimagined processes.



2. Installation and Setup

    # To run the project locally
    ## In command prompt run the following commands


    ### 1. To create virtual environment
        python -m venv .venv

    ### 2. To activate virtual environment
        ./.venv/Scripts/activate

    ### 3. To install all the requirements (first activate the virtual environment)
        - pip install uv
        - uv pip install -r requirements.txt

    ### 4. Create and Configure the `.env` File

    Before running the application, create a `.env` file in the project root directory. You can do this easily by copying the provided `.env.example` file:

    ```sh
    cp .env.example .env
    ```

    Then, open the `.env` file and fill in the values for the keys as required for your environment.

    ### 5. Setup SBERT Model (`all-MiniLM-L6-v2`)

    > If you face SSL issues while connecting to the model from Hugging Face, follow the manual setup below:

    #### Steps:

    1. Download the **`all-MiniLM-L6-v2`** model manually : [[all-MiniLM-L6-v2](https://infosystechnologies.sharepoint.com/:u:/s/AgenticAI104/EZ6FQn8GaQFEs8NVuRPcl1sBkWzuH0-imLBjMzkXAIdpDw?e=JjK7nJ)]

    2. Extract the downloaded folder to a local directory.

    3. Update your `.env` file with the local model path:

    ```env
    SBERT_MODEL_PATH=path/to/your/local/all-MiniLM-L6-v2
    ```

    > ✅ Replace `path/to/your/local/all-MiniLM-L6-v2` with the actual folder path where you extracted the model.

    ### 6. Setup bge-reranker-large Model (`bge-reranker-large`)

    > If you face SSL issues while connecting to the model from Hugging Face, follow the manual setup below:

    #### Steps:

    1. Download the **`bge-reranker-large`** model manually : [[bge-reranker-large](https://infosystechnologies.sharepoint.com/:u:/s/AgenticAI104/EZKCs4u0KxNOrtxxvGvWM_MBBnpxXyc72NsptreEPOyiCQ?e=bde1xJ)]

    2. Extract the downloaded folder to a local directory.

    3. Update your `.env` file with the local model path:

    ```env
    CROSS_ENCODER_PATH=path/to/your/local/bge-reranker-large
    ```

    > ✅ Replace `path/to/your/local/bge-reranker-large` with the actual folder path where you extracted the model.


    ### 7. Setup Vault secret
    >  Fill the SECRETS_MASTER_KEY with the any Alfanumeric value of length more then 10 characters.



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
        SBERT_MODEL_PATH=path_to_your_local_all-MiniLM-L6-v2
        CROSS_ENCODER_PATH = path_to_your_local_bge-reranker-large

        # Redis Cache Configuration
        REDIS_HOST=your_redis_host
        REDIS_PORT=6379
        REDIS_DB=0
        REDIS_PASSWORD=your_redis_password
        CACHE_EXPIRY_TIME=600
        ENABLE_CACHING=false  # Set to 'true' to enable Redis caching, 'false' to disable
        ```

    - Replace the placeholder values with your actual credentials and endpoints.
    - **Note:** Never commit your `.env` file or sensitive credentials to version control.

5. Password Setup
    The application uses a default password for initial authentication, which is defined in the 
    .env file as:

    ```env
    IAF_PASSWORD= Default@123
    ``
    
    If you wish to change this password, you can do so by modifying the value of IAF_PASSWORD in the .env file


6. How to set up the dev environment

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
        python main.py

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
        python main.py --host 0.0.0.0 --port 8000


    > **Note:** The `--reload` and `--workers` options are only supported when starting the server with `run_server.py`. If you use `main.py`, you can only configure the `--host` and `--port` options.



7. Change Log

    [View Change Log](CHANGELOG.md)



8. License Info

    -The Open Source License the software has been released is under MIT LICENCE,
    [View LICENSE](LICENSE.md)



9. Author Info

    -Infosys
    


# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved. Infosys believes the information in this document is accurate as of its publication date; such information is subject to change without notice. Infosys acknowledges the proprietary rights of other companies to the trademarks, product names and such other intellectual property rights mentioned in this document. Except as expressly permitted, neither this documentation nor any part of it may be reproduced, stored in a retrieval system, or transmitted in any form or by any means, electronic, mechanical, printing, photocopying, recording or otherwise, without the prior permission of Infosys Limited and/or any named intellectual property rights holders under this document.
