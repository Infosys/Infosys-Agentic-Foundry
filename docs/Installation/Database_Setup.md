# PostgreSQL Setup Guide

## Installation on VM

1. Download the PostgreSQL installation wizard and start it up.
![postgres1](../images/postgres1.png)
2. Choose the default directory or customize as required.
![postgres2](../images/postgres2.png)
3. All the components will be selected by default and will be useful, 
so keep them as it is and Next to continue. 

    ![postgres3](../images/postgres3.png)

4. Choose the default Data directory or change as required.
![postgres4](../images/postgres4.png)
5. Create a password for postgres (superuser) - This password will be used in the connection string for connecting to the database: `postgresql://postgres:password@localhost:port/database`.

    ![postgres5](../images/postgres5.png)

6. Set the port number (default: 5432) or change if required.
![postgres6](../images/postgres6.png)

7. Use the Locale field to specify the locale that will be used by the new database cluster. The Default locale is the operating system locale. You can leave this as is and click next to continue.

    ![postgres7](../images/postgres7.png)

8. Click Next to continue.

    ![postgres8](../images/postgres8.png)

9. Click Next to start the installation.
![postgres9](../images/postgres9.png)
10. After installation is complete, there will be a checked check box which asks if additional tools should be installed to complement your postgres installation using Stack Builder.
11. You should uncheck this as it is not necessary, and it is also not possible as the url gets blocked by the VM.

    ![postgres10](../images/postgres10.png)

## Installation on local

1. Install PostgreSQL from company portal
2. Verify installation:
    - Open SQL Shell (psql)
    - Default username, password, database: `postgres`
    - Default port: `5432` 

        ![postgres12](../images/postgres12.png)

    - Default connection string: `postgresql://postgres:postgres@localhost:5432/postgres`
    - Connection String Format

    ```
    postgresql://username:password@host:port/database
    ```

    **Example:**

    ```
    postgresql://postgres:postgres@localhost:5432/postgres
    ```

3. Run `\l` command to check list of databases, username, and password status

    ![postgres11](../images/postgres11.png)

## Database Setup

**Environment Configuration**

Create a `.env` file with the following variables:

```
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres

# PostgreSQL Configuration
POSTGRESQL_HOST=localhost
POSTGRESQL_USER=postgres
POSTGRESQL_PASSWORD=postgres
DATABASE=your_database_name
POSTGRESQL_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/your_database_name?sslmode=disable
```

**Database Creation**

**1. Define required databases in a list variable in `database_manager.py` file:**

```python
REQUIRED_DATABASES = [
    "feedback_learning",
    "telemetry_logs", 
    "agentic_workflow_as_service_database",
    "login",
    "logs",
    "arize_traces"
]
```

**2. Load environment variables in `database_manager.py` file:**

```python
Postgre_string = os.getenv("DATABASE_URL")
POSTGRESQL_HOST = os.getenv("POSTGRESQL_HOST", "")
POSTGRESQL_USER = os.getenv("POSTGRESQL_USER", "")
POSTGRESQL_PASSWORD = os.getenv("POSTGRESQL_PASSWORD", "")
DATABASE = os.getenv("DATABASE", "")
DATABASE_URL = os.getenv("POSTGRESQL_DATABASE_URL", "")
```

**3. Create function to connect to postgres database in `database_manager.py` file:**

```python
def get_postgres_url():
    url = urlparse(Postgre_string)
    # Replace path with '/postgres'
    new_url = url._replace(path="/postgres")
    return urlunparse(new_url)
```

**4. Create Databases function**

- The system will connect to the 'postgres' database under postgres user and create the required databases listed in `REQUIRED_DATABASES` using following code in `database_manager.py` file.

```python
async def check_and_create_databases():
    conn = await asyncpg.connect(get_postgres_url())
    try:
        for db_name in REQUIRED_DATABASES:
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", db_name
            )
            if not exists:
                print(f"Database '{db_name}' not found. Creating...")
                await conn.execute(f'CREATE DATABASE "{db_name}"')
            else:
                print(f"Database '{db_name}' already exists.")
    finally:
        await conn.close()
```
