# Database Setup Guide

## PostgreSQL Installation on Windows VM

1. Go to the [PostgreSQL Windows download page](https://www.postgresql.org/download/windows/).
2. Select PostgreSQL version 17.
3. Download the PostgreSQL installation wizard and start it up.  
   ![postgres1](../images/postgres1.png)
4. Choose the default directory or customize as required.  
   ![postgres2](../images/postgres2.png)
5. All the components will be selected by default; keep them as is and click "Next" to continue.  
   ![postgres3](../images/postgres3.png)
6. Choose the default Data directory or change as required.  
   ![postgres4](../images/postgres4.png)
7. Create a password for postgres (superuser) – This password will be used in the connection string for connecting to the database:  
   `postgresql://postgres:password@localhost:port/database`  
   ![postgres5](../images/postgres5.png)
8. Set the port number (default: 5432) or change if required.  
   ![postgres6](../images/postgres6.png)
9. Use the Locale field as desired (default is OS locale). Leave this as is and click next to continue.  
   ![postgres7](../images/postgres7.png)
10. Click Next to continue.  
    ![postgres8](../images/postgres8.png)
11. Click Next to start the installation.  
    ![postgres9](../images/postgres9.png)
12. After installation, a checkbox will ask if you wish to install additional tools with Stack Builder.
13. (Optional) You can download additional tools for this PostgreSQL installation but it is not necessary.  
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

**Environment Configuration**

Create a `.env` file by copying the content from `.env.example` and set the following variables such as host, username, and password to connect to the required PostgreSQL DB:

```
# GIVE YOUR POSTGRESQL CONFIG
POSTGRESQL_HOST=localhost
POSTGRESQL_PORT=5432
POSTGRESQL_USER=postgres
POSTGRESQL_PASSWORD=postgres
# Disables ssl in postgres connection string for inference
DISABLE_SSL_FOR_CHAT_CONNECTIONS=True

# Database name to be used
DATABASE=agentic_workflow_as_service_database
FEEDBACK_LEARNING_DB_NAME=feedback_learning
EVALUATION_LOGS_DB_NAME=evaluation_logs
RECYCLE_DB_NAME=recycle
LOGIN_DB_NAME=login
ARIZE_TRACES_DB_NAME=arize_traces
# keep it 'low' for local devices, change it to 'medium' or 'high' for Server/VM
CONNECTION_POOL_SIZE="low"
```

> **Note:** For connecting to Azure PostgreSQL Database, set the SSL variable as `False`:
> `DISABLE_SSL_FOR_CHAT_CONNECTIONS=False`

> **Note:** The required PostgreSQL databases are automatically created according to the names given in the `.env` file. Hence, different database instances can be created by changing the names in the `.env`.

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
7. **Allow connection to Redis through the firewall:**
    ```powershell
    netsh advfirewall firewall add rule name="Redis" dir=in action=allow protocol=TCP localport=6379
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
    dir /var/lib/redis
    ```
    Find `pidfile` in `redis.conf` and edit it like below:
    ```
    pidfile /var/run/redis/redis.pid
    ```
2. Copy the config and set permissions:
    ```bash
    sudo mkdir -p /etc/redis /var/run/redis /var/lib/redis
    sudo chmod 700 /var/lib/redis
    sudo cp /home/projadmin/setup/redis-8.2.1/redis.conf /etc/redis/redis.conf
    sudo chown -R projadmin:projadmin /etc/redis/ /var/run/redis /var/lib/redis
    ```

> **Note:** `projadmin` is the Linux VM username for RHEL9 VM and it differs according to the type of Linux OS.

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
    Group=projadmin

    # Create /run/redis at service start, owned by the service user
    RuntimeDirectory=redis
    RuntimeDirectoryMode=0755

    # Tell systemd where the PID file will be (under /run)
    PIDFile=/run/redis/redis.pid

    # Ensure Redis uses systemd supervision and stays in foreground

    WorkingDirectory=/var/lib/redis
    ExecStart=/usr/local/bin/redis-server /etc/redis/redis.conf
    ExecStop=/usr/local/bin/redis-cli -a <password> shutdown
    Restart=always

    [Install]
    WantedBy=multi-user.target
    ```

> **Note:** `User` and `Group` values depend on the username of the Linux VM.

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

> **Note:** The firewall command differs based on the type of Linux OS.

> **Note:** Update `User` and `<password>` in your redis configuration and service file to match your security and environment needs.