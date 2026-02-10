# Database Setup Guide

## PostgreSQL Installation on Windows VM

1. Download the PostgreSQL installation wizard and start it up.  
   ![postgres1](../images/postgres1.png)
2. Choose the default directory or customize as required.  
   ![postgres2](../images/postgres2.png)
3. All the components will be selected by default; keep them as is and click "Next" to continue.  
   ![postgres3](../images/postgres3.png)
4. Choose the default Data directory or change as required.  
   ![postgres4](../images/postgres4.png)
5. Create a password for postgres (superuser) – This password will be used in the connection string for connecting to the database:  
   `postgresql://postgres:password@localhost:port/database`  
   ![postgres5](../images/postgres5.png)
6. Set the port number (default: 5432) or change if required.  
   ![postgres6](../images/postgres6.png)
7. Use the Locale field as desired (default is OS locale). Leave this as is and click next to continue.  
   ![postgres7](../images/postgres7.png)
8. Click Next to continue.  
   ![postgres8](../images/postgres8.png)
9. Click Next to start the installation.  
   ![postgres9](../images/postgres9.png)
10. After installation, a checkbox will ask if you wish to install additional tools with Stack Builder.
11. Uncheck this as it is not necessary and likely not supported inside a VM.  
    ![postgres10](../images/postgres10.png)

---

## PostgreSQL Installation on Linux

**Installation using PostgreSQL Official Packages**

1. Go to the [PostgreSQL Linux download page](https://www.postgresql.org/download/linux/).
2. Select your OS distribution and follow the instructions to get the appropriate installation script.
3. **Choose PostgreSQL version 17**.
4. **Example for RHEL9/CentOS9:**
    ```bash
    sudo dnf install -y https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm
    sudo dnf install -y postgresql17-server
    sudo /usr/pgsql-17/bin/postgresql-17-setup initdb
    sudo systemctl enable postgresql-17
    sudo systemctl start postgresql-17
    ```

**Installation from Source**

1. **Download and extract source:**
    ```bash
    wget https://ftp.postgresql.org/pub/source/v17.3/postgresql-17.3.tar.gz
    tar -xzf postgresql-17.3.tar.gz
    cd postgresql-17.3
    ```
2. **Install required build dependencies:**
    ```bash
    sudo dnf install libicu-devel readline-devel perl-FindBin
    ```
3. **Compile and install:**
    ```bash
    ./configure
    make
    sudo make install
    ```
4. **Initialize data directory and configure permissions:**
    ```bash
    sudo mkdir /usr/local/pgsql/data
    sudo useradd -r -s /bin/bash postgres
    sudo chown -R postgres:postgres /usr/local/pgsql/

    sudo mkdir -p /home/postgres
    sudo chown postgres:postgres /home/postgres
    sudo -u postgres /usr/local/pgsql/bin/initdb -D /usr/local/pgsql/data
    ```
5. **Start PostgreSQL server and verify installation:**
    ```bash
    sudo -u postgres /usr/local/pgsql/bin/pg_ctl -D /usr/local/pgsql/data start
    psql --version
    ```

**Recommended: Set Up PostgreSQL as a systemd Service**

1. **Create the systemd service file:**
    ```bash
    sudo nano /etc/systemd/system/postgresql.service
    ```
    Paste the following:
    ```
    [Unit]
    Description=PostgreSQL database server
    After=network.target

    [Service]
    Type=forking

    User=postgres
    Group=postgres

    ExecStart=/usr/local/pgsql/bin/pg_ctl start -D /usr/local/pgsql/data -s -l /usr/local/pgsql/data/serverlog -o "-p 5432"
    ExecStop=/usr/local/pgsql/bin/pg_ctl stop -D /usr/local/pgsql/data -s -m fast
    ExecReload=/usr/local/pgsql/bin/pg_ctl reload -D /usr/local/pgsql/data -s
    Environment=PGDATA=/usr/local/pgsql/data

    [Install]
    WantedBy=multi-user.target
    ```
2. **Enable and start the service:**
    ```bash
    sudo systemctl enable postgresql.service
    sudo systemctl restart postgresql.service
    journalctl -u postgresql.service -f  # (to view logs)
    ```

**Additional Configuration (Remote Access, Password Setup)**

1. **Allow connections from other hosts:**
    - Edit `postgresql.conf`:
        ```bash
        sudo nano /usr/local/pgsql/data/postgresql.conf
        ```
        Set the following values:
        ```
        listen_addresses = '*'
        max_connections = 500
        ```
2. **Set postgres user password:**
    ```bash
    sudo -u postgres /usr/local/pgsql/bin/psql
    ```
    In psql prompt:
    ```
    alter user postgres password '<yourpassword>';
    ```
3. **Enable password authentication for remote access:**
    - Edit `pg_hba.conf`:
        ```bash
        sudo nano /usr/local/pgsql/data/pg_hba.conf
        ```
        Add this line:
        ```
        host  all  all  0.0.0.0/0  md5
        ```
4. **Restart PostgreSQL to apply changes:**
    ```bash
    sudo systemctl restart postgresql.service
    journalctl -u postgresql.service -f
    ```
5. **If firewall is active, open port 5432:**
    ```bash
    sudo firewall-cmd --permanent --add-port=5432/tcp #Example for RHEL
    sudo firewall-cmd --reload
    ```

> **Note**: Adjust paths and version numbers as needed for your environment.

---

## PostgreSQL Database Setup

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

1. **Define required databases in a list variable in `database_manager.py`:**

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

2. **Load environment variables in `database_manager.py`:**

```python
Postgre_string = os.getenv("DATABASE_URL")
POSTGRESQL_HOST = os.getenv("POSTGRESQL_HOST", "")
POSTGRESQL_USER = os.getenv("POSTGRESQL_USER", "")
POSTGRESQL_PASSWORD = os.getenv("POSTGRESQL_PASSWORD", "")
DATABASE = os.getenv("DATABASE", "")
DATABASE_URL = os.getenv("POSTGRESQL_DATABASE_URL", "")
```

3. **Function to connect to postgres database in `database_manager.py`:**

```python
def get_postgres_url():
    url = urlparse(Postgre_string)
    # Replace path with '/postgres'
    new_url = url._replace(path="/postgres")
    return urlunparse(new_url)
```

4. **Create Databases function**

- The system will connect to the 'postgres' database under postgres user and create the required databases listed in `REQUIRED_DATABASES`:

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

---

## Redis Installation on Windows

1. Go to the [redis-windows GitHub releases page](https://github.com/redis-windows/redis-windows/releases).
2. Download the ZIP build for Redis 8.2.1:  
   `Redis-8.2.1-Windows-x64-msys2.zip`
3. Extract the ZIP file to a folder of your choice.
4. Open `redis.conf` in the same folder and set the following parameters:
    ```
    bind 0.0.0.0
    requirepass <password>
    ```
5. Open PowerShell or CMD **inside that folder**.
6. Start Redis server:
    ```
    redis-server.exe redis.conf
    ```

---

## Redis Installation on Linux

**Install dependencies (per OS)**

Use the command for your distribution:

- **Red Hat/CentOS/Fedora:**
    ```bash
    sudo dnf install gcc make openssl-devel tcl libtool autoconf automake -y
    ```
- **Debian/Ubuntu:**
    ```bash
    sudo apt install build-essential libssl-dev tcl-dev libtool autoconf automake -y
    ```
- **SUSE/OpenSUSE:**
    ```bash
    sudo zypper install gcc make libopenssl-devel tcl libtool autoconf automake -y
    ```

**Build and install from source**

1. **Download Redis 8.2.1:**
    ```bash
    wget https://github.com/redis/redis/archive/refs/tags/8.2.1.tar.gz
    ```
2. **Extract and build:**
    ```bash
    tar xvf 8.2.1.tar.gz
    cd redis-8.2.1
    make
    sudo make install
    ```

**Configuration (redis.conf)**

1. Edit `redis.conf` to set the following values:
    ```
    bind 0.0.0.0
    requirepass <password>
    pidfile /var/run/redis/
    ```
2. Copy the config and set permissions:
    ```bash
    sudo mkdir -p /etc/redis
    sudo cp /path/to/redis-8.2.1/redis.conf /etc/redis/redis.conf
    sudo chown -R projadmin:projadmin /etc/redis/

    sudo mkdir -p /var/run/redis
    sudo chown -R projadmin:projadmin /var/run/redis
    ```

**Optional: Set Up Redis as a systemd Service**

1. Create a systemd service file:
    ```bash
    sudo nano /etc/systemd/system/redis.service
    ```
    Paste in the following:
    ```
    [Unit]
    Description=Redis In-Memory Data Store
    After=network.target

    [Service]
    User=projadmin
    ExecStart=/usr/local/bin/redis-server /etc/redis/redis.conf
    ExecStop=/usr/local/bin/redis-cli -a <password> shutdown
    Restart=always

    [Install]
    WantedBy=multi-user.target
    ```

2. Start and enable Redis service:
    ```bash
    sudo systemctl start redis.service
    sudo systemctl enable redis.service
    ```
3. **If firewall is active, open port 6379:**
    ```bash
    sudo firewall-cmd --permanent --add-port=6379/tcp #Example for RHEL
    sudo firewall-cmd --reload
    ```
> **Note:** Update `User` and `<password>` in your redis configuration and service file to match your security and environment needs.