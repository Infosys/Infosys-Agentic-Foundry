# Infosys Agentic Foundry (IAF) — VM Deployment Guide

This document provides step-by-step instructions to deploy **Infosys Agentic Foundry** (Frontend + Backend) on a Virtual Machine (VM) using Docker-compose, including configuration of OpenTelemetry, Grafana, Elasticsearch,Redis,Arize Phoenix , & Postgres(optional).

---

## Prerequisites

- **Docker** and **Docker-compose** installed on the VM
- **Git** installed
- **Python 3.12** (for backend)
- Sufficient resources: recommended **8 GB+ RAM**, **30 GB+ disk**
- Network access to pull images and clone repositories

---

## Step 1: Download Code from Public GitHub

Clone the Frontend and Backend repositories. This will create two `Infosys-Agentic-Foundry-Frontend` and `Infosys-Agentic-Foundry-Backend` folders.

```bash
# Create a parent directory
mkdir -p ~/agentic-foundry
cd ~/agentic-foundry

# Clone Backend
git clone https://github.com/Infosys/Infosys-Agentic-Foundry-Backend.git

# Clone Frontend
git clone https://github.com/Infosys/Infosys-Agentic-Foundry-Frontend.git
```

**Expected structure after download:**
```
agentic-foundry/
├── Infosys-Agentic-Foundry-Backend/
├── Infosys-Agentic-Foundry-Frontend/
└── (docker-compose.yml will go here)
└── otel-collector-config.yaml
```

---

## Step 2: Create Docker Compose File

Create a `docker-compose.yml` file in the parent directory (same level as both frontend and backend folders). Use the template below.

### Docker Compose Template

Create a file named `docker-compose.yml` in your project root (e.g., `~/agentic-foundry/docker-compose.yml`):

```yaml
services:
  # 1. The Database (Persistence)
  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: postgres
    ports:
      - "5432:5432"

  # 2. Task Queue (Asynchronous Agent Thinking)
  redis:
    image: redis:alpine
    ports:
      - "6379:6379"


  # 1. Grafana
  grafana:
    image: grafana/grafana:latest
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin
    ports:
      - "3000:3000"

  # 1. Arize Phoenix
  arphx:
    image: arizephoenix/phoenix:latest
    environment:
      PHOENIX_SQL_DATABASE_URL: postgresql://userid:password@<IP>:5432/arize_traces
      PHOENIX_PORT: 6006
      PHOENIX_GRPC_PORT: 4317
      PHOENIX_GRPC_HOST: 0.0.0.0
    ports:
      - "6006:6006"
      - "4317:4317"

  # ELASTICSEARCH
  elasticsearch:
    image: elasticsearch:9.0.3
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
      - ES_JAVA_OPTS=-Xms2g -Xmx2g
    ports:
      - "9200:9200"
      - "9300:9300"

  # OPENTELEMETRY
  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.130.1
    container_name: otel-collector
    command: [ "--config=/etc/otel-collector-config.yaml" ]
    ports:
      - "4318:4318"   # OTLP HTTP default (common)
      - "4319:4319"   # Your custom gRPC port (optional)
      - "4320:4320"   # Your custom HTTP port (optional)
    volumes:
      - ./otel-collector-config.yaml:/etc/otel-collector-config.yaml:ro
    depends_on:
      - elasticsearch

  # 4. The Brain (Backend Orchestrator)
  backend:
    build: ./Infosys-Agentic-Foundry-Backend
    ports:
      - "8000:8000"
    env_file: ./.env
    depends_on:
      - db
      - redis
      - arphx
      - otel-collector

  # 5. The User Interface (Frontend)
  frontend:
    build: ./Infosys-Agentic-Foundry-Frontend
    ports:
      - "3003:3003"
    environment:
      REACT_APP_BASE_URL: http://<IP>:8000
      REACT_APP_LIVE_TRACKING_URL: http://<IP>:6006
      REACT_APP_GRAFANA_DASHBOARD_URL: http://<IP>:3000
    env_file: ./Infosys-Agentic-Foundry-Frontend/.env
    depends_on:
      - backend
      - arphx
      - grafana
```

> **Note:** Replace `<IP>` with your VM IP address or hostname. For Arize Phoenix, replace `userid` and `password` in `PHOENIX_SQL_DATABASE_URL` with your PostgreSQL credentials.

---

## Step 3: Configure OpenTelemetry, Grafana, Elasticsearch

### 3.1 OpenTelemetry Collector Configuration

Create `otel-collector-config.yaml` in the same directory as `docker-compose.yml`.

> **Important:** Replace `<IP>`address with your VM IP address or `localhost` in 'otel-collector-config.yaml' when Elasticsearch runs on the host. If all services run in the same Docker Compose network, you may use `http://elasticsearch:9200` instead of `http://<IP>:9200`.

### Below is the otel-collector-config.yaml file 

**File: `otel-collector-config.yaml`** 

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4319
      http:
        endpoint: 0.0.0.0:4320

exporters:
  debug:
    verbosity: detailed
  elasticsearch:
    endpoints: ["http://<IP>:9200"]  #replace <IP> with elastice search ip
    sending_queue:
      enabled: true

processors:
  batch: {}

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [debug]           # add elasticsearch here if you want traces in ES
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [debug]           # add elasticsearch here if you want metrics in ES
    logs:
      receivers: [otlp]
      processors: [batch]
      exporters: [debug, elasticsearch]
  telemetry:
    logs:
      level: info
    metrics:
      level: basic
```

**Configuration notes:**

| Pipeline | Purpose | Elasticsearch |
|----------|---------|---------------|
| **traces** | Distributed tracing data | Add `elasticsearch` to exporters list if you want traces stored in Elasticsearch |
| **metrics** | Performance metrics | Add `elasticsearch` to exporters list if you want metrics stored in Elasticsearch |
| **logs** | Application logs | Already exports to both `debug` and `elasticsearch` |

### 3.2 Grafana

- **URL:** `http://<VM_IP>:3000`
- **Default login:** `admin` / `admin` (change on first login)
- Configure data sources (Elasticsearch) as needed from the Grafana UI.

### 3.3 Elasticsearch

- **URL:** `http://<VM_IP>:9200`
- **Health check:** `curl http://localhost:9200`
- Stores logs (and optionally traces/metrics) exported by OpenTelemetry Collector.

---

## Step 4: Rename `.env-example` to `.env` and Update Configuration

### 4.1 Backend Environment

```bash
cd Infosys-Agentic-Foundry-Backend
cp .env.example .env
# Edit .env with your values
```

**Key variables to update in `Infosys-Agentic-Foundry-Backend/.env`:**

| Variable | Description |
|----------|-------------|
| `ENDPOINT_URL_PREFIX` | Backend URL (e.g., `http://<VM_IP>:8000`) |
| `UI_CORS_IP` | Frontend IP for CORS |
| `UI_CORS_IP_WITH_PORT` | Frontend IP with port (e.g., `http://<VM_IP>:3003`) |
| `SECRETS_MASTER_KEY` | Run `python generate_master_secret_key.py` to generate |
| `USE_OTEL_LOGGING` | Set to `True` for VM deployment with OpenTelemetry, Elasticsearch and Grafana |
| `POSTGRESQL_HOST` | `db` (Docker service name) or `localhost` if DB is on host |
| `POSTGRESQL_PASSWORD` | `postgres` as defined in docker-compose |
| `DATABASE_URL` | `postgresql://postgres:postgres@db:5432/postgres` |
| `POSTGRESQL_DB_URL_PREFIX` | `postgresql://postgres:postgres@db:5432/` |
| `POSTGRESQL_DATABASE_URL` | `postgresql://postgres:postgres@db:5432/agentic_workflow_as_service_database` |
| `PHOENIX_SQL_DATABASE_URL` | `postgresql://postgres:postgres@db:5432/arize_traces` |
| `ENABLE_CACHING` | Set to `True` if Redis is setup |
| `REDIS_HOST` | `redis` (Docker service name) |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | `http://otel-collector:4318/v1/traces` |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT_HTTP` | `http://otel-collector:4320/v1/logs` |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT_GRPC` | `otel-collector:4319` |
| `AUTH_JWT_SECRET` | Run `python generate_master_secret_key.py` to generate |
| `MODEL_SERVER_URL` | `http://<VM_IP>:5500` |
| `MODEL_SERVER_HOST` | `<VM_IP>` |
| `MODEL_SERVER_PORT` | Port of hosted model server (e.g., `5500`) |
| `ENVIRONMENT` | Enable Swagger UI with `development` or disable it with `production` |

### 4.2 Frontend Environment

```bash
cd Infosys-Agentic-Foundry-Frontend
cp .env-example .env
```

**Update `Infosys-Agentic-Foundry-Frontend/.env`:**

| Variable | Description |
|----------|-------------|
| `REACT_APP_BASE_URL` | Backend API URL (e.g., `http://<VM_IP>:8000`) |
| `REACT_APP_GRAFANA_DASHBOARD_URL` | Grafana URL (e.g., `http://<VM_IP>:3000`) |
| `REACT_APP_MKDOCS_BASE_URL` | MkDocs URL if hosted |
| `REACT_APP_LIVE_TRACKING_URL` | Phoenix/tracking URL (e.g., `http://<VM_IP>:6006`) |

---

## Step 5: Dockerfile in Frontend and Backend

### Backend Dockerfile

Location: `Infosys-Agentic-Foundry-Backend/Dockerfile`

The backend already includes a Dockerfile. Ensure it exists with content similar to:

```dockerfile
FROM python:3.12-slim as builder
WORKDIR /app
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN pip install uv
COPY requirements.txt .
RUN uv pip install --no-cache --system -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Frontend Dockerfile

Location: `Infosys-Agentic-Foundry-Frontend/DockerFile` (note: capital `F` in `DockerFile`)

The frontend Dockerfile uses Node.js:

```dockerfile
FROM node:22-alpine as build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
ENV PORT=3003
EXPOSE 3003
CMD ["npm", "start"]
```

---

## Step 6: Rebuild Images After Changes

**Whenever you modify:**

- Any service configuration
- Frontend or Backend application code
- `.env` file

**You must remove existing images and rebuild:**

```bash
# Stop and remove containers
docker compose down

# Remove old images (optional but recommended)
docker rmi $(docker images -q 'infosys-agentic*') 2>/dev/null || true

# Rebuild and start fresh
docker compose build --no-cache
docker compose up -d
```

---

## Step 7: Execute Docker Compose

From the directory containing `docker-compose.yml`:

```bash
# Build all images
docker compose build

# Start all services in detached mode
docker compose up -d

# Or build and start in one command
docker compose up -d --build
```

**Useful commands:**

| Command | Description |
|---------|-------------|
| `docker compose up -d` | Start all services in background |
| `docker compose up -d --build` | Build and start |
| `docker compose down` | Stop and remove containers |
| `docker compose logs -f` | Follow logs from all services |
| `docker compose logs -f backend` | Follow backend logs only |

---

## Step 8: Verify Deployed Services

Check the status of all containers:

```bash
docker ps -a
```

**Expected output:** All services should show `Up` status:

| Service | Port | Status |
|---------|------|--------|
| db | 5432 | Up |
| redis | 6379 | Up |
| grafana | 3000 | Up |
| arphx | 6006, 4317 | Up |
| elasticsearch | 9200, 9300 | Up |
| otel-collector | 4318, 4319, 4320 | Up |
| backend | 8000 | Up |
| frontend | 3003 | Up |

---

## Step 9: Model Server Setup

For detailed instructions on deploying and configuring your model server, refer to the [Model Server Deployment](../Model_server.md#model-server-setup-localvm-deployment) guide.

---

## Port Summary

| Service | Port(s) | Purpose |
|---------|---------|---------|
| Frontend | 3003 | Web UI |
| Backend | 8000 | API |
| PostgreSQL | 5432 | Database |
| Redis | 6379 | Cache/Queue |
| Grafana | 3000 | Dashboards |
| Arize Phoenix | 6006, 4317 | LLM observability |
| Elasticsearch | 9200, 9300 | Log storage/search |
| OTLP Collector | 4318, 4319, 4320 | Telemetry ingestion |

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Container keeps restarting | Check `docker compose logs <service>` |
| Connection refused | Ensure services use Docker network names (`db`, `redis`) not `localhost` in `.env` |
| Out of memory | Increase `ES_JAVA_OPTS` or VM RAM; reduce Elasticsearch heap |
| Port already in use | Change port mapping in `docker-compose.yml` or stop conflicting process |
| `.env` not loaded | Ensure file is at correct path: `./Infosys-Agentic-Foundry-Backend/.env` |
| Phoenix DB connection error | Use `postgresql://postgres:postgres@db:5432/arize_traces` and ensure DB password matches |
| OpenTelemetry not sending | Set `USE_OTEL_LOGGING=True` in backend `.env`; verify `otel-collector` is reachable |
| OTEL Collector ES connection failed | For same-network deployment, use `http://elasticsearch:9200`. For host ES, use `http://<VM_IP>:9200` |

---

## Appendix: Database Initialization

Arize Phoenix and the application may require databases to exist. To create `arize_traces` and other DBs:

```bash
# Connect to PostgreSQL container
docker exec -it <db_container_id> psql -U postgres -c "CREATE DATABASE arize_traces;"
docker exec -it <db_container_id> psql -U postgres -c "CREATE DATABASE agentic_workflow_as_service_database;"
# Add other DBs as per .env (feedback_learning, evaluation_logs, recycle, login)
```

Or run the backend once; it may auto-create schemas on startup.
