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

        DATABASE_URL=your_postgres_connection_string
        POSTGRESQL_HOST=your_postgres_host
        POSTGRESQL_USER=your_postgres_user
        POSTGRESQL_PASSWORD=your_postgres_password
        DATABASE=your_database_name
        POSTGRESQL_DATABASE_URL=your_postgres_database_url
        POSTGRES_DB_URL_PREFIX=your_postgres_db_url_prefix

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
        uvicorn agent_endpoints:app --reload

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
        uvicorn agent_endpoints:app --host 0.0.0.0 --port 8000 --workers 4
        






# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved. Infosys believes the information in this document is accurate as of its publication date; such information is subject to change without notice. Infosys acknowledges the proprietary rights of other companies to the trademarks, product names and such other intellectual property rights mentioned in this document. Except as expressly permitted, neither this documentation nor any part of it may be reproduced, stored in a retrieval system, or transmitted in any form or by any means, electronic, mechanical, printing, photocopying, recording or otherwise, without the prior permission of Infosys Limited and/or any named intellectual property rights holders under this document.