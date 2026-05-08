# Deployment of IAF with Autoscaling in VM using Docker

## Prerequisites

Ensure you have access to the following:

**GitHub Repositories**

- [Frontend](https://github.com/Infosys-Generative-AI/Agentic-Pro-UI)
- [Backend](https://github.com/Infosys-Generative-AI/Infyagentframework)

**Infrastructure**

- Access to Linux VMs
- Docker CLI installed on all VMs

!!! info "Before Deploying IAF"
    Before deploying IAF in VMs, you need to have **Kafka** and **LiteLLM** set up.

---

## Kafka Setup in VM

1. Pull the Docker image for Kafka:

    ```bash
    docker pull bitnamilegacy/kafka:4.0.0-debian-12-r10
    ```

2. Run Kafka using `docker run`.

    The command should run a single-node Kafka broker in KRaft (ZooKeeper-less) mode using the Bitnami Kafka image. It configures the broker to act as both controller and broker, sets up internal and external listeners, and defines advertised endpoints for client connectivity. Persistent storage is enabled to retain Kafka data across restarts, and replication settings are configured for a single broker.

3. Check the Kafka container status:

    ```bash
    docker ps -a
    ```

4. After the Kafka container is created, manually create the `__consumer_offsets` topic — it will not be created automatically.

5. Access Kafka using:

    ```
    <VM-IP>:9092
    ```

---

## LiteLLM Server Setup

The LiteLLM setup for your VM follows the same process as the Linux VM installation guide.

[:octicons-arrow-right-24: LiteLLM Proxy Setup — Linux Installation](../linux.md)

---

## Building Docker Images

### Backend

1. Configure all variables in the backend `.env` file correctly.
2. Download the backend code from the GitHub Main branch.
3. Copy the Dockerfile into the same folder.
4. Update `main.py` to set CORS origins (if `*` is not already present):
    - Update origins
    - For testing, update CORS (optional)
5. Build the Docker image:

    ```bash
    docker build -f <docker filename with path> -t <image name>:<image tag>
    ```

    You will get an image like: `localhost/<image name>:<image tag>`

### Agent Worker

1. Configure all variables in the backend `.env` file correctly.
2. Download the backend code from the GitHub Main branch.
3. Copy the Dockerfile into the same folder.
4. In the Dockerfile, use the command to run `run_agent_worker.py` — **do not** run `main.py` for the agent worker image.
5. Update `main.py` CORS origins if needed.
6. Build the Docker image:

    ```bash
    docker build -f <docker filename with path> -t <image name>:<image tag>
    ```

    You will get an image like: `localhost/<image name>:<image tag>`

### Tool Worker

1. Configure all variables in the backend `.env` file correctly.
2. Download the backend code from the GitHub Main branch.
3. Copy the Dockerfile into the same folder.
4. In the Dockerfile, use the command to run `tool_worker/main.py` — **do not** run `main.py` from the root directory for the tool worker image.
5. Update `main.py` CORS origins if needed.
6. Build the Docker image:

    ```bash
    docker build -f <docker filename with path> -t <image name>:<image tag>
    ```

    You will get an image like: `localhost/<image name>:<image tag>`

### Frontend

1. Configure all variables in the frontend `.env` file correctly (Backend URL, MkDocs, Arize Phoenix, Grafana, etc.).
2. Download the frontend code from the GitHub Main branch.
3. Copy the Dockerfile into the same folder.
4. Build the Docker image:

    ```bash
    docker build -f <Dockerfile> -t <imagename>:<imagetag>
    ```

    You will get an image like: `localhost/<image name>:<image tag>`

---

## Deploying Containers in VMs

### VM — Backend and Frontend

Build the backend and frontend images on this VM, then deploy:

```bash
# Run backend
docker run -d --name <container name> localhost/<image name>:<image tag> python main.py --host 0.0.0.0 --port <port number>

# Run frontend
docker run -d --name <container name> localhost/<image name>:<image tag> python main.py --host 0.0.0.0 --port <port number>

# Check containers
docker ps -a
```

Access the services at:

```
<VM IP>:<Backend port>
<VM IP>:<Frontend port>
```

### VM — Agent Workers

Build the agent worker image on this VM, then deploy. Run **at least 5 containers**, each on a different port:

```bash
docker run -d --name <container name> localhost/<image name>:<image tag> python run_agent_worker.py --host 0.0.0.0 --port <port number>

# Repeat with different port numbers for additional containers

docker ps -a
```

### VM — Tool Workers

Build the tool worker image on this VM, then deploy. Run **at least 3 containers**, each on a different port:

```bash
docker run -d --name <container name> localhost/<image name>:<image tag> python tool_worker/main.py --host 0.0.0.0 --port <port number>

# Repeat with different port numbers for additional containers

docker ps -a
```

!!! success "All Containers Running"
    All containers are now up and running. You can start using the platform by triggering batches.

---

## Notes

- Set the proxies in all VMs to establish connections between them.
- If you are unable to access URLs outside the VM, allow the required ports through the firewall.
- It is not mandatory to host all services on one VM. You can distribute across multiple VMs:
    - **VM 1** — Backend, Frontend, Kafka, LiteLLM
    - **VM 2** — Agent Workers
    - **VM 3** — Tool Workers

    When using this approach, ensure the same database and Kafka credentials are used across all VMs.

---

## Sample Multi-VM Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                      VM 1 — Core Services                               │
│                                                                                         │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │
│   │  IAF Backend │  │  IAF Frontend│  │ Kafka Server │  │   LiteLLM    │               │
│   │  (FastAPI)   │  │  (UI)        │  │ (Broker)     │  │  (LLM Proxy) │               │
│   │  Port: 8000  │  │  Port: 3000  │  │  Port: 9092  │  │  Port: 4000  │               │
│   └──────────────┘  └──────────────┘  └──────┬───────┘  └──────────────┘               │
│                                              │                                          │
│   ┌──────────────────┐                       │   Kafka Broker                           │
│   │  PostgreSQL DB   │                       │   (all workers connect here)             │
│   │  Port: 5432      │                       │                                          │
│   │  (shared across  │                       │                                          │
│   │   all 3 VMs)     │                       │                                          │
│   └──────────────────┘                       │                                          │
└──────────────────────────────────────────────┼──────────────────────────────────────────┘
                                               │
                    ┌──────────────────────────┴──────────────────────────┐
                    │                                                      │
                    ▼                                                      ▼
┌───────────────────────────────────────┐       ┌───────────────────────────────────────┐
│         VM 2 — Agent Workers          │       │         VM 3 — Tool Workers           │
│                                       │       │                                       │
│  ┌────────────┐  ┌────────────┐       │       │  ┌────────────┐  ┌────────────┐       │
│  │  Worker 1  │  │  Worker 2  │       │       │  │  Worker 1  │  │  Worker 2  │       │
│  │  Port: 8102│  │  Port: 8103│       │       │  │  Port: 8101│  │  Port: 8111│       │
│  └────────────┘  └────────────┘       │       │  └────────────┘  └────────────┘       │
│                                       │       │                                       │
│  ┌────────────┐  ┌────────────┐       │       │  ┌────────────┐                       │
│  │  Worker 3  │  │  Worker 4  │       │       │  │  Worker 3  │                       │
│  │  Port: 8104│  │  Port: 8105│       │       │  │  Port: 8121│                       │
│  └────────────┘  └────────────┘       │       │  └────────────┘                       │
│                                       │       │                                       │
│  ┌────────────┐                       │       │  Consumer Group:                      │
│  │  Worker 5  │                       │       │  "tool-executor-workers"              │
│  │  Port: 8106│                       │       │                                       │
│  └────────────┘                       │       └───────────────────────────────────────┘
│                                       │
│  Consumer Group:                      │
│  "agent-executor-workers"             │
│                                       │
└───────────────────────────────────────┘

           All VMs connect to PostgreSQL on VM 1 (Port 5432)
           ┌────────────────────────────────────────────────┐
           │  Shared PostgreSQL Database (hosted on VM 1)   │
           │                                                │
           │  • Task Registry (status tracking)             │
           │  • Chat History                                │
           │  • Agent/Tool configuration                    │
           │  • Token usage logs                            │
           │                                                │
           │  VM 1 (Backend)       ──▶ localhost:5432       │
           │  VM 2 (Agent Workers) ──▶ VM1_IP:5432          │
           │  VM 3 (Tool Workers)  ──▶ VM1_IP:5432          │
           └────────────────────────────────────────────────┘
```
