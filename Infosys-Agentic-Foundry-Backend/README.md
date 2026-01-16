
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
    

    ### 5. Setup SBERT and BGE-Reranker Models

    > This section guides you through setting up the required models.

    You have two primary deployment options:

    **Local/VM Model Server Setup:** For hosting models on a dedicated machine (your local environment or a Virtual Machine).

    **Remote Client Setup:** For connecting to an already operational model server hosted elsewhere.

    #### Model Server Setup (Local/VM Deployment)

    Use this approach when you want to host the embedding and reranker models on a dedicated server (localhost or VM).

    ##### Steps:

    1. **Setup Model Server Environment**

       - Configure a model server (either on `localhost` or a dedicated VM) Ensure it runs on a distinct port from your primary application server.
       - Verify the server machine possesses adequate RAM resources for efficient model inference.

    2. **Download Required Models Manually**
       
       Download both models manually to avoid SSL connectivity issues:
       
       - **`all-MiniLM-L6-v2`** model: [[Download Link](https://infosystechnologies.sharepoint.com/:u:/s/AgenticAI104/EZ6FQn8GaQFEs8NVuRPcl1sBkWzuH0-imLBjMzkXAIdpDw?e=JjK7nJ)]
       - **`bge-reranker-large`** model: [[Download Link](https://infosystechnologies.sharepoint.com/:u:/s/AgenticAI104/EZKCs4u0KxNOrtxxvGvWM_MBBnpxXyc72NsptreEPOyiCQ?e=bde1xJ)]
       
       After downloading, **extract both `.zip` archives** into a chosen directory on your server machine.

    3. **Configure Environment Variables (`.env`)**
       
       Update your `.env` file to point to the local paths of your extracted models:

       ```env
       SBERT_MODEL_PATH=path/to/your/folder/all-MiniLM-L6-v2
       CROSS_ENCODER_PATH=path/to/your/folder/bge-reranker-large
       ```

       > ⚠️ **Important:** Replace the placeholder paths with the actual folder paths where you extracted the models.

    4. **Start Model Server**
       
        Execute the `model_server.py` script to launch your model server. This will load the models into memory and expose them via API endpoints
       
       **`model_server.py` file:** [Link to model_server.py (https://infosystechnologies.sharepoint.com/:u:/s/AgenticAI104/EW7g9SeUS7lNjUhmCX5NUo8BQ8FeAvY6Tc8WigIESEY3sQ?e=ZkCnm7)]
       
       ```bash
       python model_server.py
       ```
       Keep this process running for the models to remain available.

    #### Remote Client Setup

    Use this approach when connecting to an existing model server hosted elsewhere.

    ##### Steps:

    1. **Configure Remote Model Server Connection**
       
       Update your `.env` file with the remote model server details:

    ```env
    MODEL_SERVER_URL="http://your-model-server-ip:port"
    MODEL_SERVER_HOST="your-model-server-ip"   # Often derived from MODEL_SERVER_URL
    MODEL_SERVER_PORT="port_number"           # Often derived from MODEL_SERVER_URL
    ```

    ### 6. Setup Vault / Master Secret
    You need a cryptographically strong master secret used for encryption / signing (variable: `SECRETS_MASTER_KEY`).

    Recommended: use the helper script instead of typing a manual value.

    #### Option A: Generate with helper script (preferred)
    A minimal script `generate_master_secret_key.py` (at repository root) outputs a 256‑bit random base64 string.

    PowerShell (Windows):
    ```powershell
    # Run the generator
    python .\generate_master_secret_key.py
    ```
    Copy the printed value.

    Then open your freshly copied `.env` file and set:
    ```env
    SECRETS_MASTER_KEY=PASTE_VALUE_HERE
    ```

    (Keep it on a single line, no quotes, no trailing spaces.)

    #### Rotation
    To rotate, regenerate a new key, update `.env`, then restart any running services. Ensure any previously encrypted data is either re-encrypted or still accessible via a key management / versioning strategy if applicable.

    >  Legacy note: If you already manually set `SECRETS_MASTER_KEY` to an alphanumeric string > 10 chars, you may keep it, but regenerating with the script improves entropy.



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

    # Master Secret (required for encryption / signing operations)
    SECRETS_MASTER_KEY=your_generated_base64_secret_key  # Generate: python generate_master_secret_key.py

        # Redis Cache Configuration
        REDIS_HOST=your_redis_host
        REDIS_PORT=6379
        REDIS_DB=0
        REDIS_PASSWORD=your_redis_password
        CACHE_EXPIRY_TIME=600
        ENABLE_CACHING=false  # Set to 'true' to enable Redis caching, 'false' to disable
        ```
        
    - **Note:** Never commit your `.env` file or sensitive credentials to version control.



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
        python main.py
                OR
        python run_server.py
                OR
        python run_server.py --reload

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
                OR
        python run_server.py --host 0.0.0.0 --port 8000
                OR
        python run_server.py --host 0.0.0.0 --port 8000 --workers 2


    > **Note:** The `--reload` and `--workers` options are only supported when starting the server with `run_server.py`. If you use `main.py`, you can only configure the `--host` and `--port` options.



6. Change Log

    [View Change Log](CHANGELOG.md)



7. License Info

    -The Open Source License the software has been released is under MIT LICENCE,
    [View LICENSE](LICENSE.md)



8. Author Info

    -Infosys
    


# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved. Infosys believes the information in this document is accurate as of its publication date; such information is subject to change without notice. Infosys acknowledges the proprietary rights of other companies to the trademarks, product names and such other intellectual property rights mentioned in this document. Except as expressly permitted, neither this documentation nor any part of it may be reproduced, stored in a retrieval system, or transmitted in any form or by any means, electronic, mechanical, printing, photocopying, recording or otherwise, without the prior permission of Infosys Limited and/or any named intellectual property rights holders under this document.
