1. Installation 

    # To run the project locally
    ## In command prompt run the following commands


    ### 1. To create virtual environment
        python -m venv .venv

    ### 2. To activate virtual environment
        ./.venv/Scripts/activate

    ### 3. To install all the requirements (first activate the virtual environment)
        - pip install uv
        - uv pip install -r requirements.txt

2. Environment Variables Setup

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
        EMBEDDING_MODEL_PATH = path_to_your_local_e5-base-v2
        CROSS_ENCODER_PATH = path_to_your_local_stsb-roberta-base

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


3. How to set up the environment

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
        uvicorn exportagent.agent_endpoints:app --reload

     ### 4. Setup SBERT Model (`all-MiniLM-L6-v2`)

    > If you face SSL issues while connecting to the model from Hugging Face, follow the manual setup below:

    #### Steps:

    1. Download the **`all-MiniLM-L6-v2`** model manually : [[all-MiniLM-L6-v2](https://infosystechnologies.sharepoint.com/:u:/s/AgenticAI104/EZ6FQn8GaQFEs8NVuRPcl1sBkWzuH0-imLBjMzkXAIdpDw?e=JjK7nJ)]

    2. Extract the downloaded folder to a local directory.

    3. Update your `.env` file with the local model path:

    ```env
    SBERT_MODEL_PATH=path/to/your/local/all-MiniLM-L6-v2
    ```

    > ✅ Replace `path/to/your/local/all-MiniLM-L6-v2` with the actual folder path where you extracted the model.

    ### 5. Setup e5-base-v2 Model (`e5-base-v2`)

    > If you face SSL issues while connecting to the model from Hugging Face, follow the manual setup below:

    #### Steps:

    1. Download the **`e5-base-v2`** model manually : [[e5-base-v2](https://infosystechnologies.sharepoint.com/:u:/r/sites/AgenticAI104/Shared%20Documents/Agentic%20AI/e5-base-v2.zip?csf=1&web=1&e=syB8fl)]

    2. Extract the downloaded folder to a local directory.

    3. Update your `.env` file with the local model path:

    ```env
    EMBEDDING_MODEL_PATH=path/to/your/local/e5-base-v2
    ```

    > ✅ Replace `path/to/your/local/e5-base-v2` with the actual folder path where you extracted the model.

    ### 6. Setup stsb-roberta-base Model (`stsb-roberta-base`)

    > If you face SSL issues while connecting to the model from Hugging Face, follow the manual setup below:

    #### Steps:

    1. Download the **`stsb-roberta-base`** model manually : [[stsb-roberta-base](https://infosystechnologies.sharepoint.com/:u:/r/sites/AgenticAI104/Shared%20Documents/Agentic%20AI/stsb-roberta-base.zip?csf=1&web=1&e=wSubQp)]

    2. Extract the downloaded folder to a local directory.

    3. Update your `.env` file with the local model path:

    ```env
    CROSS_ENCODER_PATH=path/to/your/local/stsb-roberta-base
    ```

    > ✅ Replace `path/to/your/local/stsb-roberta-base` with the actual folder path where you extracted the model.


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
        uvicorn exportagent.agent_endpoints:app --host 0.0.0.0 --port 8000 --workers 4
        






# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved. Infosys believes the information in this document is accurate as of its publication date; such information is subject to change without notice. Infosys acknowledges the proprietary rights of other companies to the trademarks, product names and such other intellectual property rights mentioned in this document. Except as expressly permitted, neither this documentation nor any part of it may be reproduced, stored in a retrieval system, or transmitted in any form or by any means, electronic, mechanical, printing, photocopying, recording or otherwise, without the prior permission of Infosys Limited and/or any named intellectual property rights holders under this document.