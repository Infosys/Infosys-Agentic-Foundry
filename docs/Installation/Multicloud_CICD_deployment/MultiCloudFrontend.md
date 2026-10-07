# Multi-Cloud IAF Frontend CI/CD Pipeline — Setup & Usage Guide

> **Purpose:** This guide helps any team set up and use the GitHub Actions CI/CD pipeline to build a frontend Docker image, push it to a cloud container registry, and deploy the frontend application to a managed Kubernetes cluster — across **Azure (AKS)**, **AWS (EKS)**, and **GCP (GKE)**.
>
> **Scope:** This guide covers the **external (direct)** deployment variant only — where the self-hosted runner pushes the Docker image directly to the cloud container registry (ACR / ECR / GAR).

---

## Table of Contents

1. [What This Pipeline Does](#1-what-this-pipeline-does)
2. [How It Triggers](#2-how-it-triggers)
3. [How the Frontend Pipeline Differs from the Backend](#3-how-the-frontend-pipeline-differs-from-the-backend)
4. [Prerequisites](#4-prerequisites)
5. [Configure Self-Hosted Runner on a VM](#5-configure-self-hosted-runner-on-a-vm)
6. [Customize Branch Name and Runner Labels in Pipeline](#6-customize-branch-name-and-runner-labels-in-pipeline)
7. [GitHub Secrets & Variables Setup](#7-github-secrets-variables-setup)
8. [Pipeline env: Block — How Variables Are Mapped](#8-pipeline-env-block-how-variables-are-mapped)
9. [Dockerfile Setup (Frontend)](#9-dockerfile-setup-frontend)
10. [nginx.conf.template — Reverse Proxy Configuration](#10-nginxconftemplate-reverse-proxy-configuration)
11. [Workflow File Setup](#11-workflow-file-setup)
12. [Full Pipeline YAML — by Hyperscaler](#12-full-pipeline-yaml-by-hyperscaler)
13. [How Each Job Works](#13-how-each-job-works)
14. [Kubernetes Resources Created](#14-kubernetes-resources-created)
15. [First vs Repeated Deployments](#15-first-vs-repeated-deployments)
16. [Troubleshooting](#16-troubleshooting)
17. [Quick Checklist](#17-quick-checklist)

---

## 1. What This Pipeline Does

```
Commit to GitHub  ──────────────────────────────────────────────────────────┐
    ↓                                                                        │
[GitHub Actions Triggered by push / workflow_dispatch]                       │
    ↓                                                                        │
Build Frontend Docker Image (tagged with Git commit SHA)                     │
    ↓                                                                        │
Push Image to Cloud Container Registry                                       │
    │                                                                        │
    ├── Azure  → Azure Container Registry (ACR)                             │
    ├── AWS    → Amazon Elastic Container Registry (ECR)                    │
    └── GCP    → Google Artifact Registry (GAR)                             │
    ↓                                                                        │
Deploy Frontend Application to Kubernetes Cluster                            │
    │                                                                        │
    ├── Azure  → AKS (Azure Kubernetes Service)                             │
    ├── AWS    → EKS (Amazon Elastic Kubernetes Service)                    │
    └── GCP    → GKE (Google Kubernetes Engine)                             │
    │                                                                        │
    ├── First time?       → Create Deployment + LoadBalancer Service        │
    └── Already exists?  → Update image only ───────────────────────────────┘
```

> The frontend pipeline has **2 jobs** — `buildImage` and `deploy`. There is **no** `deployInfra` job because the frontend application does not use Elasticsearch, Redis, Phoenix, OpenTelemetry Collector, or Grafana.

---

## 2. How It Triggers

| Trigger | When |
|---|---|
| **Auto** | Push to your configured branch (e.g., `main`, `main-copy`) |
| **Manual** | GitHub → Actions → Select workflow → Run workflow |

> Update the branch name in the workflow YAML to match your deployment branch before using.

---

## 3. How the Frontend Pipeline Differs from the Backend

| Feature | Backend Pipeline | Frontend Pipeline |
|---|---|---|
| **Jobs** | deployInfra → buildImage → deploy | **buildImage → deploy** |
| **Infrastructure services** | Elasticsearch, OTel, Redis, Phoenix, Grafana | **None** |
| **Container port** | 8000 | **80** (nginx) |
| **Kubernetes Secret name** | `app-env` | **`frontend-env`** |
| **Env file secret** | `APP_ENV_FILE` / `APP_ENV_FILE_GCP` | **`FRONTEND_ENV_FILE`** / **`FRONTEND_ENV_FILE_GCP`** |
| **Infra IPs injected into secret** | Yes | **No** |
| **Build context** | Repository root (`.`) | **`$AGENT_PATH`** (frontend source directory on runner) |
| **Resource requests/limits** | memory: 2Gi, cpu: 1000m | **memory: 512Mi, cpu: 500m** |

---

## 4. Prerequisites

Make sure all of these exist before setting up:

**Common (All Hyperscalers)**

| Requirement | Details |
|---|---|
| GitHub Repository | With Actions enabled |
| Self-hosted Runner | Linux/X64 machine registered in GitHub |
| Runner Tools | `docker`, cloud CLI, `kubectl` |
| Frontend Dockerfile | Present in the frontend source directory (`$AGENT_PATH`) |
| Kubernetes Cluster | Already provisioned and running |
| Container Registry | Already created in your cloud provider |
| `AGENT_PATH` | Environment variable set on the runner VM pointing to frontend source |

**Azure (AKS) Specific**

| Requirement | Details |
|---|---|
| Azure Subscription | With AKS and ACR access |
| Azure Container Registry (ACR) | Already created |
| AKS Cluster | Already provisioned |
| Service Principal | With `AcrPush` + AKS deploy access |
| `kubelogin` | Installed on the runner |
| Corporate CA Bundle | `/etc/ssl/certs/ca-bundle.crt` on the runner (for SSL in corporate networks) |

**AWS (EKS) Specific**

| Requirement | Details |
|---|---|
| AWS Account | With ECR and EKS access permissions |
| ECR Repository | Already created in AWS |
| EKS Cluster | Already provisioned and running |
| IAM User/Role | With `AmazonEC2ContainerRegistryFullAccess` + EKS deploy permissions |
| `envsubst` | Installed on runner (`sudo apt-get install -y gettext`) |

**GCP (GKE) Specific**

| Requirement | Details |
|---|---|
| GCP Project | With GKE and Artifact Registry APIs enabled |
| GKE Cluster | Already provisioned and running |
| Artifact Registry Repository | Already created |
| Service Account | With `roles/container.developer` + `roles/artifactregistry.writer` |
| `gcloud` CLI | Installed and **pre-authenticated** on runner |
| `gke-gcloud-auth-plugin` | Installed (`gcloud components install gke-gcloud-auth-plugin`) |
| `envsubst` | Installed on runner (`sudo apt-get install -y gettext`) |

---

**Install Tools on the Runner (Ubuntu/Debian)**

**Common tools (all hyperscalers):**

```bash
# Docker
sudo apt-get install -y docker.io
sudo usermod -aG docker $USER

# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
```

**Azure-specific tools:**

```bash
# Azure CLI
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# kubelogin
sudo az aks install-cli
```

**AWS-specific tools:**

```bash
# AWS CLI
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
sudo apt-get install -y unzip
unzip awscliv2.zip && sudo ./aws/install

# envsubst
sudo apt-get install -y gettext
```

**GCP-specific tools:**

```bash
# gcloud CLI
curl -O https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-linux-x86_64.tar.gz
tar -xf google-cloud-cli-linux-x86_64.tar.gz
./google-cloud-sdk/install.sh
source ~/.bashrc

# gke-gcloud-auth-plugin
gcloud components install gke-gcloud-auth-plugin

# envsubst
sudo apt-get install -y gettext
```

---

## 5. Configure Self-Hosted Runner on a VM

A self-hosted runner is a machine (VM or physical server) that runs your GitHub Actions jobs. This pipeline requires a runner with the labels `self-hosted`, `Linux`, `X64`, and a custom label of your choice (e.g., `fe-runner`, `frontend-runner`).

**Step 1 — Prepare Your VM**

Use any Linux VM (AWS EC2, Azure VM, GCP Compute Engine, on-prem, etc.). Recommended specs:

| Resource | Minimum |
|---|---|
| OS | Ubuntu 20.04 / 22.04 (64-bit) |
| CPU | 2 vCPUs |
| RAM | 4 GB |
| Disk | 30 GB |

**Step 2 — Register the Runner in GitHub**

1. Go to your **GitHub Repository**.
2. Click **Settings** → **Actions** → **Runners**.
3. Click **New self-hosted runner**.
4. Select **Linux** as the operating system and **X64** as the architecture.
5. Run the commands shown by GitHub on your VM:

```bash
# Create a folder for the runner
mkdir actions-runner && cd actions-runner

# Download the latest runner package (use the exact URL GitHub shows you)
curl -o actions-runner-linux-x64.tar.gz -L https://github.com/actions/runner/releases/download/v<version>/actions-runner-linux-x64-<version>.tar.gz

# Extract the package
tar xzf ./actions-runner-linux-x64.tar.gz

# Configure the runner (use the exact token GitHub shows you)
./config.sh --url https://github.com/<your-org>/<your-repo> --token <YOUR_TOKEN>
```

**Step 3 — Set Runner Labels**

During the `./config.sh` configuration step, GitHub will ask:

```
Enter the name of the runner group to add this runner to: [press Enter for Default]
Enter the name of runner: [your-runner-name]
This runner will have the following labels: 'self-hosted', 'Linux', 'X64'
Enter any additional labels (ex. label-1,label-2): [press Enter to skip]
```

When it asks for **additional labels**, enter a custom label that matches your workflow (e.g., `fe-runner` for the frontend runner):

```
fe-runner
```

This allows the pipeline to target this runner with:

```yaml
runs-on: [self-hosted, Linux, X64, fe-runner]
```

> If you already registered the runner without the custom label, add it from:
> **GitHub → Settings → Actions → Runners → Click your runner → Edit labels**

**Step 4 — Set AGENT_PATH on the Runner**

The frontend pipeline uses `$AGENT_PATH` as the Docker build context. Set it on the runner VM before starting the runner service:

```bash
# Option A — Set in /etc/environment (system-wide, persists after reboot)
echo "AGENT_PATH=/home/runner/frontend-source" | sudo tee -a /etc/environment

# Option B — Set in the runner service's environment file
# Edit: /etc/systemd/system/actions.runner.<org>.<repo>.service
# Add under [Service]:
# Environment="AGENT_PATH=/home/runner/frontend-source"
sudo systemctl daemon-reload
```

> Replace `/home/runner/frontend-source` with the actual path to your frontend application directory on the runner VM. This directory must contain the frontend `Dockerfile`.

**Step 5 — Start the Runner**

**Option A: Run manually (for testing)**

```bash
./run.sh
```

You will see:
```
√ Connected to GitHub
Listening for Jobs
```

**Option B: Run as a system service (recommended for production)**

```bash
# Install as a service
sudo ./svc.sh install

# Start the service
sudo ./svc.sh start

# Check service status
sudo ./svc.sh status
```

> Running as a service ensures the runner starts automatically after a VM reboot.

**Step 6 — Verify Runner is Online**

Go to **GitHub → Settings → Actions → Runners**.

You should see your runner listed with status **Idle** (green dot):

```
✔ my-fe-runner    Idle    self-hosted, Linux, X64, fe-runner
```

---

## 6. Customize Branch Name and Runner Labels in Pipeline

**How to Change the Branch Name**

Open your workflow YAML file and find this section at the top:

```yaml
on:
  push:
    branches:
      - main-copy        # ← CHANGE THIS to your branch name
```

**Example:** Multiple branches:

```yaml
on:
  push:
    branches:
      - main
      - staging
      - production
```

---

**How to Change the Self-Hosted Runner Labels**

The frontend pipeline has **2 jobs**. Update the `runs-on:` field in both:

```yaml
jobs:
  buildImage:
    runs-on: [self-hosted, Linux, X64, fe-runner]   # ← CHANGE to your runner label

  deploy:
    runs-on: [self-hosted, Linux, X64, fe-runner]   # ← CHANGE to your runner label
```

**The labels must exactly match** what is registered on your self-hosted runner.

| Label | Meaning |
|---|---|
| `self-hosted` | Use a self-hosted runner (not GitHub-hosted) |
| `Linux` | Runner OS is Linux |
| `X64` | Runner architecture is 64-bit |
| `fe-runner` | Custom label to target your specific frontend runner |

> Both jobs must use the same `runs-on` value, otherwise they may run on different machines and lose state.

---

## 7. GitHub Secrets & Variables Setup

**What are GitHub Secrets and GitHub Variables?**

GitHub provides two built-in mechanisms to pass configuration and credentials into your pipeline without hardcoding them in YAML files.

---

**GitHub Secrets**

A **GitHub Secret** is an **encrypted, sensitive value** stored securely at the repository (or organization) level. It is designed for credentials, tokens, keys, and any information that must never be exposed publicly.

**How it works:**

- You create a secret once in the GitHub UI.
- GitHub encrypts it immediately — even repository admins cannot read it back after saving.
- The pipeline reads it at runtime using `${{ secrets.SECRET_NAME }}`.
- In logs, GitHub automatically **masks** the value and replaces it with `***`.

**Example use cases:**

- Cloud credentials (`AZURE_CLIENT_SECRET`, `AWS_SECRET_ACCESS_KEY`)
- Full content of `.env` files (`FRONTEND_ENV_FILE`)

```yaml
# How secrets are used inside a pipeline step
- name: Azure Login
  run: |
    az login --service-principal \
      --username ${{ secrets.AZURE_CLIENT_ID }} \
      --password ${{ secrets.AZURE_CLIENT_SECRET }} \
      --tenant   ${{ secrets.AZURE_TENANT_ID }}
```

---

**GitHub Variables**

A **GitHub Variable** is a **plain-text, non-sensitive configuration value** stored at the repository (or organization) level. It is designed for values that can be seen publicly but you still don't want to hardcode inside YAML files.

**How it works:**

- You create a variable once in the GitHub UI.
- The value is stored as plain text — it is **not** encrypted and **not** masked in logs.
- The pipeline reads it at runtime using `${{ vars.VARIABLE_NAME }}`.

**Example use cases:**

- Registry URLs (`AZURE_CONTAINER_REGISTRY`, `ECR_REGISTRY`)
- Cluster names, resource groups, namespaces, deployment names

```yaml
# How variables are used inside the env: block
env:
  CLUSTER_NAME: ${{ vars.CLUSTER_NAME }}
  NAMESPACE:    ${{ vars.NAMESPACE }}
```

---

**Key Differences at a Glance**

| Feature | GitHub Secrets | GitHub Variables |
|---|---|---|
| **Purpose** | Sensitive credentials & keys | Non-sensitive configuration values |
| **Encryption** | Yes — encrypted at rest | No — stored as plain text |
| **Visible in logs** | No — masked as `***` | Yes — appears in plain text |
| **Readable by admins** | No — cannot be read back after saving | Yes — visible in GitHub UI |
| **YAML syntax** | `${{ secrets.NAME }}` | `${{ vars.NAME }}` |
| **GitHub UI location** | Settings → Secrets and variables → **Actions** | Settings → Secrets and variables → **Variables** |
| **Examples** | Client secret, access key, `.env` file | ACR name, cluster name, namespace |

> **Rule of thumb:** If you would be uncomfortable posting the value in a public chat message — use a **Secret**. If it's just a name or a URL — use a **Variable**.

---

**Azure (AKS) — Frontend**

**GitHub Variables (non-sensitive)**

Go to: **Repo → Settings → Secrets and variables → Variables → New repository variable**

| Variable Name | Description | Example Value |
|---|---|---|
| `AZURE_CONTAINER_REGISTRY` | ACR login server URL | `myregistry.azurecr.io` |
| `RESOURCE_GROUP` | Azure Resource Group containing AKS | `my-resource-group` |
| `CLUSTER_NAME` | AKS cluster name | `aks-my-cluster` |
| `NAMESPACE` | Kubernetes namespace for the frontend | `my-frontend-namespace` |
| `DEPLOY_NAME` | Name of the Kubernetes Deployment object | `my-frontend-deployment` |
| `CONTAINER_NAME` | Name of the container inside the pod | `my-frontend-container` |
| `SHORT_NAME` | Short label used for ACR image tagging | `my-frontend` |

**GitHub Secrets (sensitive)**

Go to: **Repo → Settings → Secrets and variables → Actions → New repository secret**

| Secret Name | What to Put | Example |
|---|---|---|
| `AZURE_CLIENT_ID` | Service Principal Application (Client) ID | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `AZURE_CLIENT_SECRET` | Service Principal Client Secret | `your-client-secret` |
| `AZURE_TENANT_ID` | Azure Active Directory Tenant ID | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `AZURE_SUBSCRIPTION_ID` | Azure Subscription ID | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `FRONTEND_ENV_FILE` | Full content of your frontend `.env` file | *(see below)* |

---

**AWS (EKS) — Frontend**

**GitHub Variables (non-sensitive)**

| Variable Name | Description | Example Value |
|---|---|---|
| `ECR_REGISTRY` | ECR registry URL | `123456789012.dkr.ecr.us-east-1.amazonaws.com` |
| `ECR_REPOSITORY` | ECR repository name | `my-frontend-repo` |
| `EKS_CLUSTER_NAME` | EKS cluster name | `eks-my-cluster` |
| `NAMESPACE` | Kubernetes namespace for the frontend | `my-frontend-namespace` |
| `DEPLOY_NAME` | Name of the Kubernetes Deployment object | `my-frontend-deployment` |
| `CONTAINER_NAME` | Name of the container inside the pod | `my-frontend-container` |
| `SHORT_NAME` | Short label used for ECR image tagging | `my-frontend` |

**GitHub Secrets (sensitive)**

| Secret Name | What to Put | Example |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | IAM user Access Key ID | `AKIAIOSFODNN7EXAMPLE` |
| `AWS_SECRET_ACCESS_KEY` | IAM user Secret Access Key | `wJalrXUtnFEMI/K7MDENG/...` |
| `AWS_SESSION_TOKEN` | Session token (only if using temporary/assumed-role credentials) | `AQoDYXdzEJ...` |
| `AWS_REGION` | AWS region where ECR and EKS are hosted | `us-east-1` |
| `FRONTEND_ENV_FILE` | Full content of your frontend `.env` file | *(see below)* |

---

**GCP (GKE) — Frontend**

**GitHub Variables (non-sensitive)**

| Variable Name | Description | Example Value |
|---|---|---|
| `GCP_PROJECT_ID` | GCP Project ID | `my-project-123456` |
| `GKE_CLUSTER_NAME` | GKE cluster name | `gke-my-cluster` |
| `GKE_ZONE` | GKE cluster zone or region | `us-central1-a` |
| `ARTIFACT_REGISTRY` | Artifact Registry path | `us-central1-docker.pkg.dev/my-project/my-repo` |
| `NAMESPACE` | Kubernetes namespace for the frontend | `my-frontend-namespace` |
| `DEPLOY_NAME` | Name of the Kubernetes Deployment object | `my-frontend-deployment` |
| `CONTAINER_NAME` | Name of the container inside the pod | `my-frontend-container` |
| `SHORT_NAME` | Short label used for Artifact Registry image tagging | `my-frontend` |

**GitHub Secrets (sensitive)**

| Secret Name | What to Put | Example |
|---|---|---|
| `FRONTEND_ENV_FILE_GCP` | Full content of your frontend `.env` file | *(see below)* |

> **Note:** GKE pipelines use a pre-authenticated self-hosted runner (gcloud is already authenticated on the runner VM). No `GCP_SA_KEY` is needed unless the runner is not pre-authenticated.

---

**How to set the frontend environment file secret**

Copy the **entire content** of your frontend `.env` file and paste it as the secret value:

```env
REACT_APP_API_URL=http://<backend-service-ip>:8000
REACT_APP_ENV=production
REACT_APP_FEATURE_FLAG_X=true
REACT_APP_TITLE=My Application
```

> The pipeline reads this secret, writes it to a temporary file, deduplicates and sanitizes it, and converts it into a Kubernetes Secret named `frontend-env`. Your frontend pods then receive all these values as environment variables at runtime.

**Rules for the env file content:**

- One `KEY=VALUE` pair per line
- No spaces around `=`
- No surrounding quotes needed (the pipeline strips them automatically)
- No blank lines or comments (they are filtered out automatically)

---

## 8. Pipeline env: Block — How Variables Are Mapped

The `env:` block at the top of each workflow YAML is a **central mapper** — it reads values from GitHub Variables (`vars.*`) and exposes them as environment variables used throughout the pipeline.

> **You do not hardcode any values in the YAML file.** Set them once in GitHub UI (Section 7 above) and the pipeline picks them up automatically.

**How the env: block works**

```
GitHub Variables (vars.*)  ──► env: block (mapper) ──► ${{ env.* }} used everywhere in the pipeline
```

**Azure (AKS) — Frontend env: block**

```yaml
env:
  # Non-sensitive — pulled from GitHub Variables
  AZURE_CONTAINER_REGISTRY: ${{ vars.AZURE_CONTAINER_REGISTRY }}  # e.g. myregistry.azurecr.io
  RESOURCE_GROUP:            ${{ vars.RESOURCE_GROUP }}            # e.g. my-rg-prod
  CLUSTER_NAME:              ${{ vars.CLUSTER_NAME }}              # e.g. aks-my-cluster
  NAMESPACE:                 ${{ vars.NAMESPACE }}                 # K8s namespace for the frontend
  DEPLOY_NAME:               ${{ vars.DEPLOY_NAME }}               # K8s Deployment name
  CONTAINER_NAME:            ${{ vars.CONTAINER_NAME }}            # Container name inside the pod
  SHORT_NAME:                ${{ vars.SHORT_NAME }}                # Short name for ACR image tagging
```

> Sensitive values (`AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `FRONTEND_ENV_FILE`) are referenced directly from `secrets.*` inside individual pipeline steps — they do not appear in the `env:` block.

**AWS (EKS) — Frontend env: block**

```yaml
env:
  # Non-sensitive — pulled from GitHub Variables
  ECR_REGISTRY:     ${{ vars.ECR_REGISTRY }}      # e.g. 123456789012.dkr.ecr.us-east-1.amazonaws.com
  ECR_REPOSITORY:   ${{ vars.ECR_REPOSITORY }}    # e.g. my-frontend-repo
  EKS_CLUSTER_NAME: ${{ vars.EKS_CLUSTER_NAME }}  # e.g. eks-my-cluster
  NAMESPACE:        ${{ vars.NAMESPACE }}          # K8s namespace for the frontend
  DEPLOY_NAME:      ${{ vars.DEPLOY_NAME }}        # K8s Deployment name
  CONTAINER_NAME:   ${{ vars.CONTAINER_NAME }}     # Container name inside the pod
  SHORT_NAME:       ${{ vars.SHORT_NAME }}         # Short name for ECR image tagging
```

> Sensitive values (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_REGION`, `FRONTEND_ENV_FILE`) are referenced directly from `secrets.*` inside individual pipeline steps.

**GCP (GKE) — Frontend env: block**

```yaml
env:
  # Non-sensitive — pulled from GitHub Variables
  GCP_PROJECT_ID:    ${{ vars.GCP_PROJECT_ID }}    # e.g. my-project-123456
  GKE_CLUSTER_NAME:  ${{ vars.GKE_CLUSTER_NAME }}  # e.g. gke-my-cluster
  GKE_ZONE:          ${{ vars.GKE_ZONE }}           # e.g. us-central1-a
  ARTIFACT_REGISTRY: ${{ vars.ARTIFACT_REGISTRY }}  # e.g. us-central1-docker.pkg.dev/my-project/my-repo
  NAMESPACE:         ${{ vars.NAMESPACE }}           # K8s namespace for the frontend
  DEPLOY_NAME:       ${{ vars.DEPLOY_NAME }}         # K8s Deployment name
  CONTAINER_NAME:    ${{ vars.CONTAINER_NAME }}      # Container name inside the pod
  SHORT_NAME:        ${{ vars.SHORT_NAME }}          # Short name for Artifact Registry image tagging
```

> Sensitive values (`FRONTEND_ENV_FILE_GCP`) are referenced directly from `secrets.*` inside individual pipeline steps.

---

## 9. Dockerfile Setup (Frontend)

Your frontend source directory (`$AGENT_PATH`) **must** have a `Dockerfile`.

**Recommended: Multi-stage Dockerfile with nginx Reverse Proxy**

This is the production pattern used by the IAF frontend. It builds the SPA and serves it with nginx, while also reverse-proxying all backend API calls through nginx — so the browser only ever talks to port 80 and there are **no CORS issues**.

```dockerfile
# ── Stage 1: Build ────────────────────────────────────────────
FROM node:18-alpine AS builder

WORKDIR /app

# Install dependencies
COPY package.json package-lock.json ./
RUN npm ci --silent

# Copy source and build
COPY . .
RUN npm run build

# ── Stage 2: Serve with nginx + reverse proxy ─────────────────
FROM nginx:alpine

# Install envsubst (part of gettext) for runtime config substitution
RUN apk add --no-cache gettext

# Copy built static files from build stage
COPY --from=builder /app/build /usr/share/nginx/html

# Copy the nginx config template (backend IP injected at startup)
COPY nginx.conf.template /etc/nginx/nginx.conf.template

EXPOSE 80

# At container startup:
#   1. envsubst replaces ${BACKEND_HOST} and ${BACKEND_PORT} in the
#      template with actual values from the frontend-env K8s secret.
#   2. The result is written to /etc/nginx/nginx.conf.
#   3. nginx starts with the finalized config.
CMD ["/bin/sh", "-c", \
     "envsubst '${BACKEND_HOST} ${BACKEND_PORT}' \
       < /etc/nginx/nginx.conf.template \
       > /etc/nginx/nginx.conf \
     && nginx -g 'daemon off;'"]
```

> **Why `nginx.conf.template` and not a plain `nginx.conf`?**

> The backend LoadBalancer IP changes per environment (dev, staging, prod) and per cloud deployment. Hardcoding it in the image would require a rebuild every time the IP changes. By using `nginx.conf.template` with `envsubst`, the same Docker image works in any environment — the backend IP is injected at container startup from the Kubernetes secret.

> **Port 80:** The pipeline creates a Kubernetes Service on port 80. Make sure your Dockerfile `EXPOSE`s port 80.

---

**Required: Add BACKEND_HOST and BACKEND_PORT to your env file**

The `nginx.conf.template` uses two variables that **must** be in your `FRONTEND_ENV_FILE` GitHub Secret:

```env
BACKEND_HOST=<backend-loadbalancer-ip>   # e.g. 192.0.2.25  (the backend K8s LB IP)
BACKEND_PORT=8000                         # the port the backend listens on
```

> **How to find the backend LB IP:** After deploying the backend pipeline, run:
> ```bash
> kubectl get svc <backend-deploy-name> -n <backend-namespace> \
>   -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
> ```
> Use that IP as `BACKEND_HOST` in your frontend env file secret.

---

**Simple: Node.js Express Server (alternative)**

If your frontend runs a Node.js server (e.g., Next.js SSR) without nginx:

```dockerfile
FROM node:18-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --only=production

COPY . .
RUN npm run build

EXPOSE 80

CMD ["node", "server.js"]
```

> **Note:** This pattern does not include the nginx reverse proxy. Your Node.js app must handle CORS and backend proxying itself.

---

**Environment Variables in Frontend**

> **Important:** In most frontend frameworks (React, Vue, Angular), environment variables are **baked in at build time** (not runtime). If your app uses `REACT_APP_*` or `VITE_*` variables, they must be present during `npm run build`.
>
> Two options:

> 1. **Build-time injection:** Pass variables as Docker `--build-arg` and use `ARG` in the Dockerfile (values are fixed at image build time).
> 2. **Runtime injection (recommended with nginx):** Use the `nginx.conf.template` approach — the backend IP is injected at runtime via `envsubst`, so the same image works across environments without rebuilding.

See **[Section 10 — nginx.conf.template](#10-nginxconftemplate-reverse-proxy-configuration)** for the full nginx configuration, all proxied routes, and how `envsubst` works.

---

## 10. nginx.conf.template — Reverse Proxy Configuration

**Why nginx.conf.template is needed**

The IAF frontend container is **not just a static file server** — it is also a **reverse proxy** for the backend API. This is the most important piece of the frontend deployment.

```
Browser
  │
  │  All requests go to port 80 (the frontend LB IP)
  ▼
nginx (inside the frontend pod — port 80)
  │
  ├── /auth/*         ──► backend:8000/auth/*
  ├── /roles/*        ──► backend:8000/roles/*
  ├── /tools/*        ──► backend:8000/tools/*
  ├── /agents/*       ──► backend:8000/agents/*
  ├── /chat/*         ──► backend:8000/chat/*
  ├── /agentos/*      ──► backend:8000/agentos/*
  └── /               ──► serves React/Vue/Angular static files
                           (with try_files fallback for SPA routing)
```

**Without the nginx reverse proxy**, the browser would need to call the backend directly using the backend's LB IP and port 8000. This causes:

- **CORS errors** — the browser blocks cross-origin API calls
- **Security exposure** — the backend IP is visible to end users
- **Two separate URLs** to manage and document

**With the nginx reverse proxy**, the browser only ever sees one URL (the frontend LB IP on port 80). All API calls are proxied invisibly through nginx to the backend, eliminating CORS issues entirely.

---

**Why a template instead of a plain nginx.conf?**

The backend LoadBalancer IP changes per environment and per deployment:

- Dev environment: `192.0.2.10:8000`
- Staging environment: `192.0.2.25:8000`
- Production environment: `192.0.2.50:8000`

If the backend IP was hardcoded in `nginx.conf`, you would need to rebuild the Docker image every time the IP changes. By using `nginx.conf.template` with placeholder variables (`${BACKEND_HOST}` and `${BACKEND_PORT}`), **the same Docker image works in any environment** — the backend IP is injected at container startup from the Kubernetes secret without rebuilding.

```
Build time (docker build):
  nginx.conf.template is copied into the image as-is
  → BACKEND_HOST and BACKEND_PORT are still placeholders

Container startup (Pod starts in K8s):
  envsubst reads BACKEND_HOST and BACKEND_PORT from the
  frontend-env Kubernetes secret (set by FRONTEND_ENV_FILE)
  → Generates /etc/nginx/nginx.conf with real values
  → nginx starts with the finalized config
```

---

**Where to place nginx.conf.template**

Place `nginx.conf.template` in the **same directory as your Dockerfile** (the frontend source root at `$AGENT_PATH`):

```
$AGENT_PATH/                     ← Frontend source on the runner VM
├── Dockerfile                   ← Copies nginx.conf.template into the image
├── nginx.conf.template          ← This file (reverse proxy + SPA config)
├── package.json
├── src/
└── public/
```

> **The file must be present at build time** so the Dockerfile's `COPY` instruction can include it in the image. It is committed alongside your frontend source code.

---

**Full nginx.conf.template content**

Copy this file and place it at `$AGENT_PATH/nginx.conf.template`:

```nginx
worker_processes 1;

events {
    worker_connections 1024;
}

http {
    include       mime.types;
    default_type  application/octet-stream;

    sendfile        on;
    keepalive_timeout 65;

    # ── Backend Upstream ─────────────────────────────────────────
    # BACKEND_HOST and BACKEND_PORT are substituted at container
    # startup via envsubst from the frontend-env Kubernetes secret.
    # Add BACKEND_HOST=<backend-lb-ip> and BACKEND_PORT=8000
    # to your FRONTEND_ENV_FILE GitHub Secret.
    upstream backend {
        server ${BACKEND_HOST}:${BACKEND_PORT};
    }

    server {
        listen       80;
        server_name  localhost;

        # ── Auth routes ──────────────────────────────────────────

        location /openapi.json {
            proxy_pass http://backend/openapi.json;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/ {
            proxy_pass http://backend/auth/;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/login {
            proxy_pass http://backend/auth/login;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/logout {
            proxy_pass http://backend/auth/logout;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/register {
            proxy_pass http://backend/auth/register;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/register-superadmin {
            proxy_pass http://backend/auth/register-superadmin;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/assign-role-department {
            proxy_pass http://backend/auth/assign-role-department;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/request-department-access {
            proxy_pass http://backend/auth/request-department-access;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/my-requests {
            proxy_pass http://backend/auth/my-requests;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/registration-requests {
            proxy_pass http://backend/auth/registration-requests;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/registration-requests/approve {
            proxy_pass http://backend/auth/registration-requests/approve;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/registration-requests/reject {
            proxy_pass http://backend/auth/registration-requests/reject;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/guest-login {
            proxy_pass http://backend/auth/guest-login;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/refresh-token {
            proxy_pass http://backend/auth/refresh-token;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/reset-password {
            proxy_pass http://backend/auth/reset-password;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/change-password {
            proxy_pass http://backend/auth/change-password;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/users {
            proxy_pass http://backend/auth/users;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/users/update-role {
            proxy_pass http://backend/auth/users/update-role;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/get/search-paginated/users {
            proxy_pass http://backend/auth/get/search-paginated/users;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/admin-contacts {
            proxy_pass http://backend/auth/admin-contacts;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/me/departments-with-roles {
            proxy_pass http://backend/auth/me/departments-with-roles;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/superadmin/exists {
            proxy_pass http://backend/auth/superadmin/exists;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /auth/users/set-active-status {
            proxy_pass http://backend/auth/users/set-active-status;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        # ── Resource API routes (short-form proxy) ───────────────
        location /roles/              { proxy_pass http://backend/roles/; }
        location /departments/        { proxy_pass http://backend/departments/; }
        location /tools/              { proxy_pass http://backend/tools/; }
        location /agents/             { proxy_pass http://backend/agents/; }
        location /chat/               { proxy_pass http://backend/chat/; }
        location /evaluation/         { proxy_pass http://backend/evaluation/; }
        location /feedback-learning/  { proxy_pass http://backend/feedback-learning/; }
        location /secrets/            { proxy_pass http://backend/secrets/; }
        location /tags/               { proxy_pass http://backend/tags/; }
        location /utility/            { proxy_pass http://backend/utility/; }
        location /data-connector/     { proxy_pass http://backend/data-connector/; }

        # ── Code Executor ─────────────────────────────────────────

        location /agentos/code-executor/execute {
            proxy_pass http://backend/agentos/code-executor/execute;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /agentos/code-executor/execute-code {
            proxy_pass http://backend/agentos/code-executor/execute-code;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /agentos/code-executor/tasks {
            proxy_pass http://backend/agentos/code-executor/tasks;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /agentos/code-executor/health {
            proxy_pass http://backend/agentos/code-executor/health;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /agentos/code-executor/capabilities {
            proxy_pass http://backend/agentos/code-executor/capabilities;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /agentos/code-executor/cache/stats {
            proxy_pass http://backend/agentos/code-executor/cache/stats;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /agentos/code-executor/cache/clear {
            proxy_pass http://backend/agentos/code-executor/cache/clear;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /agentos/code-executor/config {
            proxy_pass http://backend/agentos/code-executor/config;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        # Dynamic: /agentos/code-executor/task/{task_id}
        location ~ ^/agentos/code-executor/task/([^/]+)$ {
            proxy_pass http://backend/agentos/code-executor/task/$1;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        # ── Agents ───────────────────────────────────────────────

        location = /agentos/agents {
            proxy_pass http://backend/agentos/agents;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /agentos/agents/from-folder {
            proxy_pass http://backend/agentos/agents/from-folder;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /agentos/agents/recycle-bin {
            proxy_pass http://backend/agentos/agents/recycle-bin;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        # Dynamic: /agentos/agents/recycle-bin/restore/{agent_id}
        location ~ ^/agentos/agents/recycle-bin/restore/([^/]+)$ {
            proxy_pass http://backend/agentos/agents/recycle-bin/restore/$1;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        # Dynamic: /agentos/agents/recycle-bin/permanent/{agent_id}
        location ~ ^/agentos/agents/recycle-bin/permanent/([^/]+)$ {
            proxy_pass http://backend/agentos/agents/recycle-bin/permanent/$1;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        # Dynamic: /agentos/agents/{agent_id}
        location ~ ^/agentos/agents/([^/]+)$ {
            proxy_pass http://backend/agentos/agents/$1;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        # Dynamic: /agentos/agents/{agent_id}/skills
        location ~ ^/agentos/agents/([^/]+)/skills$ {
            proxy_pass http://backend/agentos/agents/$1/skills;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        # Dynamic: /agentos/agents/{agent_id}/skills/upload
        location ~ ^/agentos/agents/([^/]+)/skills/upload$ {
            proxy_pass http://backend/agentos/agents/$1/skills/upload;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        # Dynamic: /agentos/agents/{agent_id}/skills/{skill_name}
        location ~ ^/agentos/agents/([^/]+)/skills/([^/]+)$ {
            proxy_pass http://backend/agentos/agents/$1/skills/$2;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        # Dynamic: /agentos/agents/{agent_id}/skills/{skill_name}/files
        location ~ ^/agentos/agents/([^/]+)/skills/([^/]+)/files$ {
            proxy_pass http://backend/agentos/agents/$1/skills/$2/files;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        # Dynamic: /agentos/agents/{agent_id}/skills/{skill_name}/files/{filename}
        location ~ ^/agentos/agents/([^/]+)/skills/([^/]+)/files/([^/]+)$ {
            proxy_pass http://backend/agentos/agents/$1/skills/$2/files/$3;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        # Dynamic: /agentos/agents/{agent_id}/context
        location ~ ^/agentos/agents/([^/]+)/context$ {
            proxy_pass http://backend/agentos/agents/$1/context;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        # ── Approvals ─────────────────────────────────────────────

        location = /agentos/approvals {
            proxy_pass http://backend/agentos/approvals;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        # Dynamic: /agentos/approvals/{request_id}
        location ~ ^/agentos/approvals/([^/]+)$ {
            proxy_pass http://backend/agentos/approvals/$1;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        # ── Audit ─────────────────────────────────────────────────

        location /agentos/audit/shell {
            proxy_pass http://backend/agentos/audit/shell;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location /agentos/audit/approvals {
            proxy_pass http://backend/agentos/audit/approvals;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        # ── Frontend SPA (catch-all) ──────────────────────────────
        # Serves the built React/Vue/Angular app.
        # try_files falls back to index.html for client-side routing.
        location / {
            root   /usr/share/nginx/html;
            index  index.html index.htm;
            try_files $uri $uri/ /index.html;
        }

        # ── Health check ──────────────────────────────────────────
        location /health {
            access_log off;
            add_header 'Content-Type' 'text/plain';
            return 200 "healthy";
        }

        # ── Error pages ───────────────────────────────────────────
        error_page 500 502 503 504 /50x.html;

        location = /50x.html {
            root /usr/share/nginx/html;
        }
    }
}
```

> **Only `${BACKEND_HOST}` and `${BACKEND_PORT}` are placeholders** — every other `$variable` (like `$host`, `$remote_addr`, `$scheme`, `$proxy_add_x_forwarded_for`, `$uri`) is a standard nginx variable and must be left as-is. The `envsubst '${BACKEND_HOST} ${BACKEND_PORT}'` command in the Dockerfile `CMD` ensures only these two are substituted.

---

**How envsubst works at container startup**

When the frontend pod starts in Kubernetes:

1. The `frontend-env` Kubernetes Secret (built from `FRONTEND_ENV_FILE`) is mounted as environment variables into the container.
2. The `CMD` in the Dockerfile runs `envsubst` to substitute `${BACKEND_HOST}` and `${BACKEND_PORT}` from those environment variables.
3. The result is written to `/etc/nginx/nginx.conf` (the real config file nginx reads).
4. nginx starts using the finalized config.

```bash
# What happens inside the container on every pod start:
envsubst '${BACKEND_HOST} ${BACKEND_PORT}' \
  < /etc/nginx/nginx.conf.template \
  > /etc/nginx/nginx.conf
nginx -g 'daemon off;'
```

> **`envsubst '${BACKEND_HOST} ${BACKEND_PORT}'`** — The quoted variable list tells `envsubst` to substitute **only** these two variables and leave all other `$` signs (like `$host`, `$remote_addr`, `$scheme`, `$proxy_add_x_forwarded_for`) in the nginx config **unchanged**. Without the variable list, `envsubst` would try to substitute all nginx `$variable` references and break the config.

---

**Required entries in FRONTEND_ENV_FILE**

Add these two keys to your `FRONTEND_ENV_FILE` GitHub Secret (in addition to your app config):

```env
BACKEND_HOST=<backend-loadbalancer-ip>
BACKEND_PORT=8000
```

| Key | Value | How to find it |
|---|---|---|
| `BACKEND_HOST` | IP address of the backend K8s LoadBalancer service | `kubectl get svc <backend-svc> -n <backend-ns> -o jsonpath='{.status.loadBalancer.ingress[0].ip}'` |
| `BACKEND_PORT` | Port the backend listens on | Always `8000` for IAF backend |

**Complete example FRONTEND_ENV_FILE:**

```env
BACKEND_HOST=192.0.2.25
BACKEND_PORT=8000
REACT_APP_ENV=production
REACT_APP_TITLE=My Application
```

---

**Proxied API Routes Reference**

The `nginx.conf.template` proxies the following backend routes:

**Auth routes (with full proxy headers)**

| Location | Proxied To |
|---|---|
| `/openapi.json` | `backend/openapi.json` |
| `/auth/` | `backend/auth/` |
| `/auth/login` | `backend/auth/login` |
| `/auth/logout` | `backend/auth/logout` |
| `/auth/register` | `backend/auth/register` |
| `/auth/register-superadmin` | `backend/auth/register-superadmin` |
| `/auth/assign-role-department` | `backend/auth/assign-role-department` |
| `/auth/request-department-access` | `backend/auth/request-department-access` |
| `/auth/my-requests` | `backend/auth/my-requests` |
| `/auth/registration-requests` | `backend/auth/registration-requests` |
| `/auth/registration-requests/approve` | `backend/auth/registration-requests/approve` |
| `/auth/registration-requests/reject` | `backend/auth/registration-requests/reject` |
| `/auth/guest-login` | `backend/auth/guest-login` |
| `/auth/refresh-token` | `backend/auth/refresh-token` |
| `/auth/reset-password` | `backend/auth/reset-password` |
| `/auth/change-password` | `backend/auth/change-password` |
| `/auth/users` | `backend/auth/users` |
| `/auth/users/update-role` | `backend/auth/users/update-role` |
| `/auth/get/search-paginated/users` | `backend/auth/get/search-paginated/users` |
| `/auth/admin-contacts` | `backend/auth/admin-contacts` |
| `/auth/me/departments-with-roles` | `backend/auth/me/departments-with-roles` |
| `/auth/superadmin/exists` | `backend/auth/superadmin/exists` |
| `/auth/users/set-active-status` | `backend/auth/users/set-active-status` |

**Resource routes (short-form proxy)**

| Location | Proxied To |
|---|---|
| `/roles/` | `backend/roles/` |
| `/departments/` | `backend/departments/` |
| `/tools/` | `backend/tools/` |
| `/agents/` | `backend/agents/` |
| `/chat/` | `backend/chat/` |
| `/evaluation/` | `backend/evaluation/` |
| `/feedback-learning/` | `backend/feedback-learning/` |
| `/secrets/` | `backend/secrets/` |
| `/tags/` | `backend/tags/` |
| `/utility/` | `backend/utility/` |
| `/data-connector/` | `backend/data-connector/` |

**AgentOS — Code Executor routes**

| Location | Proxied To |
|---|---|
| `/agentos/code-executor/execute` | `backend/agentos/code-executor/execute` |
| `/agentos/code-executor/execute-code` | `backend/agentos/code-executor/execute-code` |
| `/agentos/code-executor/tasks` | `backend/agentos/code-executor/tasks` |
| `/agentos/code-executor/health` | `backend/agentos/code-executor/health` |
| `/agentos/code-executor/capabilities` | `backend/agentos/code-executor/capabilities` |
| `/agentos/code-executor/cache/stats` | `backend/agentos/code-executor/cache/stats` |
| `/agentos/code-executor/cache/clear` | `backend/agentos/code-executor/cache/clear` |
| `/agentos/code-executor/config` | `backend/agentos/code-executor/config` |
| `/agentos/code-executor/task/{task_id}` | `backend/agentos/code-executor/task/$1` (regex) |


**Frontend catch-all and health**

| Location | What It Does |
|---|---|
| `/` | Serves static SPA files; falls back to `index.html` for client-side routing |
| `/health` | Returns `200 healthy` — used by K8s liveness/readiness probes |

---

**Adding a new backend route to nginx**

> **IMPORTANT — Frontend and Backend must stay in sync**
>
> Every time a **new API endpoint is added to the backend**, it **must also be added to `nginx.conf.template`** on the frontend.
>
> **Why?** The frontend nginx acts as the sole gateway between the browser and the backend. The browser never calls the backend directly — every API request goes through nginx first. If a new backend endpoint is not listed as a `location` block in `nginx.conf.template`, nginx has no rule for it and will serve the frontend's `index.html` instead of proxying the request. This breaks the new feature silently — the browser gets an HTML page instead of an API response, leading to errors like `Unexpected token '<'` or `404 Not Found` in the browser console.
>
> **Consequence of missing this step:**

> - Backend team adds `/new-feature/` → backend works fine
> - Frontend team does NOT update `nginx.conf.template` → browser calls `/new-feature/` → nginx catches it under `location /` → returns `index.html` → frontend JS crashes trying to parse HTML as JSON
>
> **Rule:** Backend endpoint added = `nginx.conf.template` location block added = frontend image rebuilt and redeployed.

If a new backend endpoint is added, add the corresponding location block to `nginx.conf.template`:

**Simple route (no dynamic segments):**
```nginx
location /new-feature/ {
    proxy_pass http://backend/new-feature/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

**Dynamic route (with path variable):**
```nginx
# /new-feature/{item_id}
location ~ ^/new-feature/([^/]+)$ {
    proxy_pass http://backend/new-feature/$1;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

After updating `nginx.conf.template`, rebuild and redeploy the frontend image via the pipeline — the new route will be active on the next deployment.

---

## 11. Workflow File Setup

1. In your repository, create the folder `.github/workflows/` if it doesn't exist.
2. Inside it, create a workflow YAML file matching your target cloud:
   - Azure: `.github/workflows/deploy-aks-frontend.yml`
   - AWS: `.github/workflows/deploy-eks-frontend.yml`
   - GCP: `.github/workflows/deploy-gke-frontend.yml`
3. Copy the relevant template from `deploy-aks-frontend-template.yml`, `deploy-eks-frontend-template.yml`, or `deploy-gke-frontend-template.yml`.
4. Replace all `<YOUR_BRANCH_NAME>` and `<YOUR_RUNNER_LABEL>` placeholders.
5. Set GitHub Variables and Secrets as described in Section 7.
6. Commit and push — the pipeline will trigger automatically.

**Folder structure:**

```
your-repo/
├── .github/
│   └── workflows/
│       ├── deploy-aks-frontend.yml    ← Azure frontend pipeline
│       ├── deploy-eks-frontend.yml    ← AWS frontend pipeline
│       └── deploy-gke-frontend.yml    ← GCP frontend pipeline
│
└── (backend repo or separate frontend repo)

Runner VM:
$AGENT_PATH/                           ← Frontend source (set on runner)
├── Dockerfile                         ← Must exist here
├── nginx.conf.template                ← Must exist here (reverse proxy config)
├── package.json
├── src/
└── public/
```

> **Both `Dockerfile` and `nginx.conf.template` must be present** in `$AGENT_PATH` on the runner VM before the pipeline can run. The Dockerfile `COPY`s `nginx.conf.template` into the image.

---

## 12. Full Pipeline YAML — by Hyperscaler

**12a. Azure — AKS Frontend**

```yaml
name: Build and Deploy Frontend to AKS

on:
  push:
    branches:
      - main-copy            # ← Change to your branch
  workflow_dispatch:
    inputs:
      image_version:
        description: 'Manual version input (informational only)'
        required: false
        default: 'latest'

env:
  AZURE_CONTAINER_REGISTRY: ${{ vars.AZURE_CONTAINER_REGISTRY }}  # e.g. myregistry.azurecr.io
  RESOURCE_GROUP:            ${{ vars.RESOURCE_GROUP }}
  CLUSTER_NAME:              ${{ vars.CLUSTER_NAME }}
  NAMESPACE:                 ${{ vars.NAMESPACE }}
  DEPLOY_NAME:               ${{ vars.DEPLOY_NAME }}
  CONTAINER_NAME:            ${{ vars.CONTAINER_NAME }}
  SHORT_NAME:                ${{ vars.SHORT_NAME }}

jobs:

  buildImage:
    name: Build and Push Docker Image
    runs-on: [self-hosted, Linux, X64, your-fe-runner]    # ← Update runner label
    permissions:
      contents: read
      id-token: write
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Azure login
        shell: bash
        env:
          REQUESTS_CA_BUNDLE: /etc/ssl/certs/ca-bundle.crt
          SSL_CERT_FILE:      /etc/ssl/certs/ca-bundle.crt
        run: |
          az login --service-principal \
            --username "${{ secrets.AZURE_CLIENT_ID }}" \
            --password "${{ secrets.AZURE_CLIENT_SECRET }}" \
            --tenant   "${{ secrets.AZURE_TENANT_ID }}"
          az account set --subscription "${{ secrets.AZURE_SUBSCRIPTION_ID }}"

      - name: Build and Push Docker Image to ACR
        run: |
          ACR_NAME=$(echo "${{ env.AZURE_CONTAINER_REGISTRY }}" | cut -d'.' -f1)
          ACR_IMG="${{ env.AZURE_CONTAINER_REGISTRY }}/${{ env.SHORT_NAME }}:${{ github.sha }}"
          unset HTTP_PROXY
          unset HTTPS_PROXY
          az acr login --name "$ACR_NAME"
          cd "$AGENT_PATH"
          docker build --shm-size=8g -t "$ACR_IMG" .
          docker push "$ACR_IMG"

  deploy:
    name: Deploy Frontend to AKS
    needs: buildImage
    runs-on: [self-hosted, Linux, X64, your-fe-runner]    # ← Update runner label
    permissions:
      actions:  read
      contents: read
    steps:
      - name: Checkout source code
        uses: actions/checkout@v4

      - name: Azure login
        shell: bash
        env:
          REQUESTS_CA_BUNDLE: /etc/ssl/certs/ca-bundle.crt
          SSL_CERT_FILE:      /etc/ssl/certs/ca-bundle.crt
        run: |
          az login --service-principal \
            --username "${{ secrets.AZURE_CLIENT_ID }}" \
            --password "${{ secrets.AZURE_CLIENT_SECRET }}" \
            --tenant   "${{ secrets.AZURE_TENANT_ID }}"
          az account set --subscription "${{ secrets.AZURE_SUBSCRIPTION_ID }}"

      - name: Set up kubelogin
        env:
          NODE_EXTRA_CA_CERTS: /etc/ssl/certs/ca-bundle.crt
        uses: azure/use-kubelogin@v1
        with:
          kubelogin-version: 'v0.0.25'

      - name: Get Kubernetes context
        uses: azure/aks-set-context@v3
        with:
          resource-group: ${{ env.RESOURCE_GROUP }}
          cluster-name:   ${{ env.CLUSTER_NAME }}
          admin:          'false'
          use-kubelogin:  'true'

      - name: Ensure Namespace Exists
        run: |
          kubectl create namespace ${{ env.NAMESPACE }} --dry-run=client -o yaml | kubectl apply -f -

      - name: Create / Update Kubernetes Secret
        env:
          ENV_FILE_CONTENT: ${{ secrets.FRONTEND_ENV_FILE }}
        run: |
          if [ -z "$ENV_FILE_CONTENT" ]; then
            echo "ERROR: FRONTEND_ENV_FILE secret is empty."; exit 1
          fi
          printf "%s" "$ENV_FILE_CONTENT" > .env.temp
          awk -F= '!seen[$1]++' .env.temp > .env.cleaned
          sed 's/^[[:space:]]*//; s/[[:space:]]*=[[:space:]]*/=/; s/="\(.*\)"$/=\1/; s/='\''\(.*\)'\''$/=\1/; /^$/d; /^#/d' \
            .env.cleaned > .env.k8s
          kubectl create secret generic frontend-env \
            --from-env-file=.env.k8s \
            -n ${{ env.NAMESPACE }} --dry-run=client -o yaml | kubectl apply -f -
          rm -f .env.temp .env.cleaned .env.k8s

      - name: Check if Deployment Exists and Deploy
        run: |
          VAR_IMAGE="${{ env.AZURE_CONTAINER_REGISTRY }}/${{ env.SHORT_NAME }}:${{ github.sha }}"
          if kubectl get deployment ${{ env.DEPLOY_NAME }} -n ${{ env.NAMESPACE }} > /dev/null 2>&1; then
            echo "=== Deployment exists. Updating image ==="
            kubectl set image deployment/${{ env.DEPLOY_NAME }} \
              ${{ env.CONTAINER_NAME }}="$VAR_IMAGE" -n ${{ env.NAMESPACE }}
          else
            echo "=== First-time deployment ==="
            cat <<EOF | kubectl apply -f -
          apiVersion: apps/v1
          kind: Deployment
          metadata:
            name: ${{ env.DEPLOY_NAME }}
            namespace: ${{ env.NAMESPACE }}
          spec:
            replicas: 1
            selector:
              matchLabels:
                app: ${{ env.DEPLOY_NAME }}
            template:
              metadata:
                labels:
                  app: ${{ env.DEPLOY_NAME }}
              spec:
                containers:
                  - name: ${{ env.CONTAINER_NAME }}
                    image: ${VAR_IMAGE}
                    ports:
                      - containerPort: 80
                    envFrom:
                      - secretRef:
                          name: frontend-env
                    resources:
                      requests:
                        memory: "256Mi"
                        cpu: "125m"
                      limits:
                        memory: "512Mi"
                        cpu: "500m"
          ---
          apiVersion: v1
          kind: Service
          metadata:
            name: ${{ env.DEPLOY_NAME }}
            namespace: ${{ env.NAMESPACE }}
            annotations:
              service.beta.kubernetes.io/azure-load-balancer-internal: "true"
          spec:
            selector:
              app: ${{ env.DEPLOY_NAME }}
            ports:
              - protocol: TCP
                port: 80
                targetPort: 80
            type: LoadBalancer
          EOF
          fi

      - name: Wait and Check Deployment
        run: |
          kubectl rollout status deployment/${{ env.DEPLOY_NAME }} \
            -n ${{ env.NAMESPACE }} --timeout=5m
          kubectl get deployment -n ${{ env.NAMESPACE }} -l app=${{ env.DEPLOY_NAME }}
          kubectl get pods -n ${{ env.NAMESPACE }} -l app=${{ env.DEPLOY_NAME }}
          kubectl get svc -n ${{ env.NAMESPACE }} ${{ env.DEPLOY_NAME }}
          POD_NAME=$(kubectl get pods -n ${{ env.NAMESPACE }} -l app=${{ env.DEPLOY_NAME }} \
                      -o jsonpath="{.items[0].metadata.name}")
          [ -n "$POD_NAME" ] && kubectl logs "$POD_NAME" -n ${{ env.NAMESPACE }} --tail=100 || true

      - name: Get Service Endpoint
        run: |
          kubectl get svc ${{ env.DEPLOY_NAME }} -n ${{ env.NAMESPACE }} \
            -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
          echo ""

      - name: Debug Deployment Failure
        if: failure()
        run: |
          kubectl get pods -n ${{ env.NAMESPACE }} -o wide
          kubectl get events -n ${{ env.NAMESPACE }} --sort-by='.lastTimestamp' | tail -n 30
          POD_NAME=$(kubectl get pods -n ${{ env.NAMESPACE }} -l app=${{ env.DEPLOY_NAME }} \
                      -o jsonpath="{.items[0].metadata.name}")
          [ -n "$POD_NAME" ] && kubectl describe pod "$POD_NAME" -n ${{ env.NAMESPACE }} || true
          [ -n "$POD_NAME" ] && kubectl logs "$POD_NAME" -n ${{ env.NAMESPACE }} --tail=100 || true
          [ -n "$POD_NAME" ] && kubectl logs "$POD_NAME" -n ${{ env.NAMESPACE }} --previous --tail=100 || true
```

---

**12b. AWS — EKS Frontend**

```yaml
name: Build and Deploy Frontend to EKS

on:
  push:
    branches:
      - main-copy            # ← Change to your branch
  workflow_dispatch:
    inputs:
      image_version:
        description: 'Manual version input (informational only)'
        required: false
        default: 'latest'

env:
  ECR_REGISTRY:     ${{ vars.ECR_REGISTRY }}
  ECR_REPOSITORY:   ${{ vars.ECR_REPOSITORY }}
  EKS_CLUSTER_NAME: ${{ vars.EKS_CLUSTER_NAME }}
  NAMESPACE:        ${{ vars.NAMESPACE }}
  DEPLOY_NAME:      ${{ vars.DEPLOY_NAME }}
  CONTAINER_NAME:   ${{ vars.CONTAINER_NAME }}
  SHORT_NAME:       ${{ vars.SHORT_NAME }}

jobs:

  buildImage:
    name: Build and Push Docker Image
    runs-on: [self-hosted, Linux, X64, your-fe-runner]    # ← Update runner label
    permissions:
      contents: read
      id-token: write
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v3
        with:
          aws-access-key-id:     ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-session-token:     ${{ secrets.AWS_SESSION_TOKEN }}
          aws-region:            ${{ secrets.AWS_REGION }}

      - name: Build and Push Docker Image to ECR
        run: |
          ECR_IMG="${{ env.ECR_REGISTRY }}/${{ env.ECR_REPOSITORY }}/${{ env.SHORT_NAME }}:${{ github.sha }}"
          aws ecr get-login-password --region ${{ secrets.AWS_REGION }} | \
            sudo docker login --username AWS --password-stdin "${{ env.ECR_REGISTRY }}"
          cd "$AGENT_PATH"
          sudo docker build --shm-size=8g -t "$ECR_IMG" .
          sudo docker push "$ECR_IMG"

  deploy:
    name: Deploy Frontend to EKS
    needs: buildImage
    runs-on: [self-hosted, Linux, X64, your-fe-runner]    # ← Update runner label
    permissions:
      actions:  read
      contents: read
    steps:
      - name: Checkout source code
        uses: actions/checkout@v4

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v3
        with:
          aws-access-key-id:     ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-session-token:     ${{ secrets.AWS_SESSION_TOKEN }}
          aws-region:            ${{ secrets.AWS_REGION }}

      - name: Update kubeconfig for EKS
        run: |
          sudo aws eks update-kubeconfig \
            --name   ${{ env.EKS_CLUSTER_NAME }} \
            --region ${{ secrets.AWS_REGION }}

      - name: Ensure Namespace Exists
        run: |
          sudo kubectl create namespace ${{ env.NAMESPACE }} --dry-run=client -o yaml | sudo kubectl apply -f -

      - name: Create / Update Kubernetes Secret
        env:
          ENV_FILE_CONTENT: ${{ secrets.FRONTEND_ENV_FILE }}
        run: |
          if [ -z "$ENV_FILE_CONTENT" ]; then
            echo "ERROR: FRONTEND_ENV_FILE secret is empty."; exit 1
          fi
          printf "%s" "$ENV_FILE_CONTENT" > .env.temp
          awk -F= '!seen[$1]++' .env.temp > .env.cleaned
          sed 's/^[[:space:]]*//; s/[[:space:]]*=[[:space:]]*/=/; s/="\(.*\)"$/=\1/; s/='\''\(.*\)'\''$/=\1/; /^$/d; /^#/d' \
            .env.cleaned > .env.k8s
          sudo kubectl create secret generic frontend-env \
            --from-env-file=.env.k8s \
            -n ${{ env.NAMESPACE }} --dry-run=client -o yaml | sudo kubectl apply -f -
          rm -f .env.temp .env.cleaned .env.k8s

      - name: Check if Deployment Exists and Deploy
        run: |
          ECR_IMG="${{ env.ECR_REGISTRY }}/${{ env.ECR_REPOSITORY }}/${{ env.SHORT_NAME }}:${{ github.sha }}"
          export IMAGE_NAME="$ECR_IMG"
          if sudo kubectl get deployment ${{ env.DEPLOY_NAME }} -n ${{ env.NAMESPACE }} > /dev/null 2>&1; then
            echo "=== Deployment exists. Updating image ==="
            sudo kubectl set image deployment/${{ env.DEPLOY_NAME }} \
              ${{ env.CONTAINER_NAME }}="$ECR_IMG" -n ${{ env.NAMESPACE }}
          else
            echo "=== First-time deployment ==="
            envsubst <<'EOF' | sudo kubectl apply -f -
          apiVersion: apps/v1
          kind: Deployment
          metadata:
            name: ${{ env.DEPLOY_NAME }}
            namespace: ${{ env.NAMESPACE }}
          spec:
            replicas: 1
            selector:
              matchLabels:
                app: ${{ env.DEPLOY_NAME }}
            template:
              metadata:
                labels:
                  app: ${{ env.DEPLOY_NAME }}
              spec:
                containers:
                  - name: ${{ env.CONTAINER_NAME }}
                    image: ${IMAGE_NAME}
                    ports:
                      - containerPort: 80
                    envFrom:
                      - secretRef:
                          name: frontend-env
                    resources:
                      requests:
                        memory: "256Mi"
                        cpu: "125m"
                      limits:
                        memory: "512Mi"
                        cpu: "500m"
          ---
          apiVersion: v1
          kind: Service
          metadata:
            name: ${{ env.DEPLOY_NAME }}
            namespace: ${{ env.NAMESPACE }}
            annotations:
              service.beta.kubernetes.io/aws-load-balancer-internal: "true"
              service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
          spec:
            selector:
              app: ${{ env.DEPLOY_NAME }}
            ports:
              - protocol: TCP
                port: 80
                targetPort: 80
            type: LoadBalancer
          EOF
          fi

      - name: Wait and Check Deployment
        run: |
          sudo kubectl rollout status deployment/${{ env.DEPLOY_NAME }} \
            -n ${{ env.NAMESPACE }} --timeout=5m
          sudo kubectl get deployment -n ${{ env.NAMESPACE }} -l app=${{ env.DEPLOY_NAME }}
          sudo kubectl get pods -n ${{ env.NAMESPACE }} -l app=${{ env.DEPLOY_NAME }}
          sudo kubectl get svc -n ${{ env.NAMESPACE }} ${{ env.DEPLOY_NAME }}

      - name: Get Service Endpoint
        run: |
          sudo kubectl get svc ${{ env.DEPLOY_NAME }} -n ${{ env.NAMESPACE }} \
            -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
          echo ""

      - name: Debug Deployment Failure
        if: failure()
        run: |
          sudo kubectl get pods -n ${{ env.NAMESPACE }} -o wide
          sudo kubectl get events -n ${{ env.NAMESPACE }} --sort-by='.lastTimestamp' | tail -n 30
          POD_NAME=$(sudo kubectl get pods -n ${{ env.NAMESPACE }} -l app=${{ env.DEPLOY_NAME }} \
                      -o jsonpath="{.items[0].metadata.name}")
          [ -n "$POD_NAME" ] && sudo kubectl describe pod "$POD_NAME" -n ${{ env.NAMESPACE }} || true
          [ -n "$POD_NAME" ] && sudo kubectl logs "$POD_NAME" -n ${{ env.NAMESPACE }} --tail=100 || true
          [ -n "$POD_NAME" ] && sudo kubectl logs "$POD_NAME" -n ${{ env.NAMESPACE }} --previous --tail=100 || true
```

---

**12c. GCP — GKE Frontend**

```yaml
name: Build and Deploy Frontend to GKE

on:
  push:
    branches:
      - main-copy            # ← Change to your branch
  workflow_dispatch:
    inputs:
      image_version:
        description: 'Manual version input (informational only)'
        required: false
        default: 'latest'

env:
  GCP_PROJECT_ID:    ${{ vars.GCP_PROJECT_ID }}
  GKE_CLUSTER_NAME:  ${{ vars.GKE_CLUSTER_NAME }}
  GKE_ZONE:          ${{ vars.GKE_ZONE }}
  ARTIFACT_REGISTRY: ${{ vars.ARTIFACT_REGISTRY }}
  NAMESPACE:         ${{ vars.NAMESPACE }}
  DEPLOY_NAME:       ${{ vars.DEPLOY_NAME }}
  CONTAINER_NAME:    ${{ vars.CONTAINER_NAME }}
  SHORT_NAME:        ${{ vars.SHORT_NAME }}

jobs:

  buildImage:
    name: Build and Push Docker Image
    runs-on: [self-hosted, your-fe-runner]    # ← Update runner label
    permissions:
      contents: read
      id-token: write
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Authenticate Docker with Artifact Registry
        run: |
          REGISTRY_HOST=$(echo "${{ env.ARTIFACT_REGISTRY }}" | cut -d'/' -f1)
          sudo gcloud auth configure-docker "$REGISTRY_HOST" --quiet

      - name: Build Docker Image
        run: |
          IMAGE="${{ env.ARTIFACT_REGISTRY }}/${{ env.SHORT_NAME }}:${{ github.sha }}"
          cd "$AGENT_PATH"
          sudo docker build --shm-size=8g -t "$IMAGE" .

      - name: Push Docker Image to Artifact Registry
        run: |
          IMAGE="${{ env.ARTIFACT_REGISTRY }}/${{ env.SHORT_NAME }}:${{ github.sha }}"
          sudo docker push "$IMAGE"

  deploy:
    name: Deploy Frontend to GKE
    needs: buildImage
    runs-on: [self-hosted, your-fe-runner]    # ← Update runner label
    permissions:
      actions:  read
      contents: read
    steps:
      - name: Checkout source code
        uses: actions/checkout@v4

      - name: Fix kubectl Permissions
        run: |
          sudo chmod +x /usr/local/bin/kubectl
          sudo chmod 755 /usr/local/bin/kubectl

      - name: Authenticate with GKE and get cluster credentials
        run: |
          sudo gcloud container clusters get-credentials ${{ env.GKE_CLUSTER_NAME }} \
            --zone    ${{ env.GKE_ZONE }} \
            --project ${{ env.GCP_PROJECT_ID }}

      - name: Ensure Namespace Exists
        run: |
          sudo kubectl create namespace ${{ env.NAMESPACE }} --dry-run=client -o yaml | sudo kubectl apply -f -

      - name: Create / Update Kubernetes Secret
        env:
          ENV_FILE_CONTENT: ${{ secrets.FRONTEND_ENV_FILE_GCP }}
        run: |
          if [ -z "$ENV_FILE_CONTENT" ]; then
            echo "ERROR: FRONTEND_ENV_FILE_GCP secret is empty."; exit 1
          fi
          printf "%s" "$ENV_FILE_CONTENT" > .env.temp
          awk -F= '!seen[$1]++' .env.temp > .env.cleaned
          sed 's/^[[:space:]]*//; s/[[:space:]]*=[[:space:]]*/=/; s/="\(.*\)"$/=\1/; s/='\''\(.*\)'\''$/=\1/; /^$/d; /^#/d' \
            .env.cleaned > .env.k8s
          sudo kubectl create secret generic frontend-env \
            --from-env-file=.env.k8s \
            -n ${{ env.NAMESPACE }} --dry-run=client -o yaml | sudo kubectl apply --validate=false -f -
          rm -f .env.temp .env.cleaned .env.k8s

      - name: Check if Deployment Exists and Deploy
        run: |
          IMAGE_NAME="${{ env.ARTIFACT_REGISTRY }}/${{ env.SHORT_NAME }}:${{ github.sha }}"
          export IMAGE_NAME
          if sudo kubectl get deployment ${{ env.DEPLOY_NAME }} -n ${{ env.NAMESPACE }} > /dev/null 2>&1; then
            echo "=== Deployment exists. Updating image ==="
            sudo kubectl set image deployment/${{ env.DEPLOY_NAME }} \
              ${{ env.CONTAINER_NAME }}="$IMAGE_NAME" -n ${{ env.NAMESPACE }}
          else
            echo "=== First-time deployment ==="
            envsubst <<'EOF' | sudo kubectl apply -f -
          apiVersion: apps/v1
          kind: Deployment
          metadata:
            name: ${{ env.DEPLOY_NAME }}
            namespace: ${{ env.NAMESPACE }}
          spec:
            replicas: 1
            selector:
              matchLabels:
                app: ${{ env.DEPLOY_NAME }}
            template:
              metadata:
                labels:
                  app: ${{ env.DEPLOY_NAME }}
              spec:
                containers:
                  - name: ${{ env.CONTAINER_NAME }}
                    image: ${IMAGE_NAME}
                    ports:
                      - containerPort: 80
                    envFrom:
                      - secretRef:
                          name: frontend-env
                    resources:
                      requests:
                        memory: "256Mi"
                        cpu: "125m"
                      limits:
                        memory: "512Mi"
                        cpu: "500m"
          ---
          apiVersion: v1
          kind: Service
          metadata:
            name: ${{ env.DEPLOY_NAME }}
            namespace: ${{ env.NAMESPACE }}
            annotations:
              cloud.google.com/load-balancer-type: "Internal"
          spec:
            selector:
              app: ${{ env.DEPLOY_NAME }}
            ports:
              - protocol: TCP
                port: 80
                targetPort: 80
            type: LoadBalancer
          EOF
          fi

      - name: Wait and Check Deployment
        run: |
          sudo kubectl rollout status deployment/${{ env.DEPLOY_NAME }} \
            -n ${{ env.NAMESPACE }} --timeout=5m
          sudo kubectl get deployment -n ${{ env.NAMESPACE }} -l app=${{ env.DEPLOY_NAME }}
          sudo kubectl get pods -n ${{ env.NAMESPACE }} -l app=${{ env.DEPLOY_NAME }}
          sudo kubectl get svc -n ${{ env.NAMESPACE }} ${{ env.DEPLOY_NAME }}

      - name: Get Service Endpoint
        run: |
          sudo kubectl get svc ${{ env.DEPLOY_NAME }} -n ${{ env.NAMESPACE }} \
            -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
          echo ""

      - name: Debug Deployment Failure
        if: failure()
        run: |
          sudo kubectl get pods -n ${{ env.NAMESPACE }} -o wide
          sudo kubectl get events -n ${{ env.NAMESPACE }} --sort-by='.lastTimestamp' | tail -n 30
          POD_NAME=$(sudo kubectl get pods -n ${{ env.NAMESPACE }} -l app=${{ env.DEPLOY_NAME }} \
                      -o jsonpath="{.items[0].metadata.name}")
          [ -n "$POD_NAME" ] && sudo kubectl describe pod "$POD_NAME" -n ${{ env.NAMESPACE }} || true
          [ -n "$POD_NAME" ] && sudo kubectl logs "$POD_NAME" -n ${{ env.NAMESPACE }} --tail=100 || true
          [ -n "$POD_NAME" ] && sudo kubectl logs "$POD_NAME" -n ${{ env.NAMESPACE }} --previous --tail=100 || true
```

---

## 13. How Each Job Works

**Job 1: `buildImage`**

| Step | AKS | EKS | GKE |
|---|---|---|---|
| **Checkout** | `actions/checkout@v4` | `actions/checkout@v4` | `actions/checkout@v4` |
| **Auth** | `az login` (Service Principal) | `configure-aws-credentials@v3` | `gcloud auth configure-docker` |
| **Build** | `cd $AGENT_PATH` → `docker build` | `cd $AGENT_PATH` → `docker build` | `cd $AGENT_PATH` → `docker build` |
| **Push** | `docker push` → ACR | `docker push` → ECR | `docker push` → GAR |
| **Image tag** | `<ACR>/<SHORT_NAME>:<git-sha>` | `<ECR>/<REPO>/<SHORT_NAME>:<git-sha>` | `<GAR>/<SHORT_NAME>:<git-sha>` |

> **`$AGENT_PATH`** must be set on the runner VM as an environment variable pointing to the directory containing the frontend `Dockerfile`. See Section 5, Step 4.

**Job 2: `deploy`**

| Step | What It Does |
|---|---|
| **Checkout** | Checks out the repository for any manifest files |
| **Auth** | Re-authenticates with the cloud provider |
| **K8s Context** | Configures `kubectl` to point at the target cluster |
| **Namespace** | Creates the frontend namespace if it does not already exist |
| **Secret** | Reads `FRONTEND_ENV_FILE`, deduplicates, sanitizes, creates/updates `frontend-env` K8s Secret |
| **Deploy** | If deployment exists → updates image only. If first run → creates Deployment + Service |
| **Wait** | Polls `kubectl rollout status` with a 5-minute timeout |
| **Endpoint** | Prints the LoadBalancer IP (AKS/GKE) or hostname (EKS) |
| **Debug** | Only runs on failure — prints pods, events, pod description, and logs |

**How the secret is built**

```
FRONTEND_ENV_FILE secret (GitHub)
    ↓
Write to .env.temp
    ↓
awk: deduplicate (first occurrence of each KEY wins)
    ↓
sed: strip leading spaces, normalize =, strip surrounding quotes, remove blank lines and comments
    ↓
kubectl create secret generic frontend-env --from-env-file=.env.k8s
    ↓
Pod reads frontend-env secret as environment variables
```

---

## 14. Kubernetes Resources Created

On the **first deployment**, the pipeline creates two resources:

**Deployment**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: <DEPLOY_NAME>
  namespace: <NAMESPACE>
spec:
  replicas: 1
  selector:
    matchLabels:
      app: <DEPLOY_NAME>
  template:
    metadata:
      labels:
        app: <DEPLOY_NAME>
    spec:
      containers:
        - name: <CONTAINER_NAME>
          image: <registry>/<SHORT_NAME>:<git-sha>
          ports:
            - containerPort: 80          # ← nginx port
          envFrom:
            - secretRef:
                name: frontend-env       # ← from FRONTEND_ENV_FILE secret
          resources:
            requests:
              memory: "256Mi"
              cpu: "125m"
            limits:
              memory: "512Mi"
              cpu: "500m"
```

### Service (Internal LoadBalancer)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: <DEPLOY_NAME>
  namespace: <NAMESPACE>
  annotations:
    # AKS — Azure internal LB:
    service.beta.kubernetes.io/azure-load-balancer-internal: "true"

    # EKS — AWS internal NLB:
    # service.beta.kubernetes.io/aws-load-balancer-internal: "true"
    # service.beta.kubernetes.io/aws-load-balancer-type: "nlb"

    # GKE — GCP internal LB:
    # cloud.google.com/load-balancer-type: "Internal"
spec:
  selector:
    app: <DEPLOY_NAME>
  ports:
    - protocol: TCP
      port: 80
      targetPort: 80
  type: LoadBalancer
```

> **Internal vs Public:** The pipeline creates an **internal** LoadBalancer by default (accessible only within the cloud VPC/VNet). To make the frontend publicly accessible, **remove** the `annotations:` block from the Service manifest.

### Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: frontend-env
  namespace: <NAMESPACE>
type: Opaque
# Keys automatically populated from FRONTEND_ENV_FILE GitHub Secret
# Required keys for nginx.conf.template substitution:
#   BACKEND_HOST:           <backend-loadbalancer-ip>   ← used by envsubst in nginx
#   BACKEND_PORT:           8000                         ← used by envsubst in nginx
# Optional app config (baked in at build time or used by entrypoint):
#   REACT_APP_ENV:          production
#   REACT_APP_TITLE:        My Application
```

---

## 15. First vs Repeated Deployments

| Scenario | What the Pipeline Does |
|---|---|
| **First deployment** | Creates `frontend-env` Secret + `Deployment` + `LoadBalancer Service` |
| **Subsequent deployments** | Updates only the container image (`kubectl set image`) — Service and IP stay the same |
| **Secret update** | `frontend-env` Secret is always recreated/updated (`--dry-run=client \| kubectl apply`) — takes effect on next pod restart |
| **Rollback** | Re-run an older workflow run to redeploy that commit's image |

> On repeated runs, only the image is updated — the Service and its LoadBalancer IP remain stable. This means the frontend URL does not change between deployments.

---

## 16. Troubleshooting

**Pipeline fails at "Build and Push Docker Image"**

| Symptom | Likely Cause | Fix |
|---|---|---|
| `AGENT_PATH: No such file or directory` | `$AGENT_PATH` not set on runner VM | Set `AGENT_PATH` in `/etc/environment` or replace with explicit path in the pipeline YAML |
| `Dockerfile: not found` | Wrong build context | Verify `$AGENT_PATH` points to the directory containing the `Dockerfile` |
| `denied: unauthorized` (ACR) | Docker not authenticated to ACR | Check `az acr login` step; verify `AZURE_CLIENT_ID/SECRET/TENANT_ID` secrets |
| `no basic auth credentials` (ECR) | ECR login failed | Check `aws ecr get-login-password` step; verify IAM secrets |
| `denied: Permission "artifactregistry.repositories.uploadArtifacts" denied` (GAR) | gcloud not authenticated | Ensure runner has gcloud pre-authenticated with the correct service account |
| Proxy error during `docker build` | Corporate proxy blocking npm/yarn/pip | Add `--build-arg http_proxy=...` to `docker build` command |
| SSL certificate error during `az login` | Corporate CA not trusted | Ensure `REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-bundle.crt` is set in the step's `env:` block |

---

**Pipeline fails at "Create / Update Kubernetes Secret"**

| Symptom | Likely Cause | Fix |
|---|---|---|
| `FRONTEND_ENV_FILE secret is empty` | Secret not added to GitHub | Go to Settings → Actions secrets → add `FRONTEND_ENV_FILE` (or `FRONTEND_ENV_FILE_GCP` for GKE) |
| `does not contain valid KEY=VALUE pairs` | Wrong format | Ensure each line is `KEY=value` with no spaces around `=`, no empty file |
| `kubectl: command not found` | kubectl not installed on runner | Install kubectl (see Section 4) |
| `Unauthorized` / kubeconfig error | Wrong K8s context | Re-run the auth/context step; check cluster name and resource group |

---

**Pod fails to start after deployment**

| Symptom | Likely Cause | Fix |
|---|---|---|
| `CrashLoopBackOff` | App crashes on startup | Check `kubectl logs <pod> -n <namespace>` for the error |
| `ImagePullBackOff` | Image not found in registry | Verify the image was pushed; check registry URL and SHORT_NAME in GitHub Variables |
| `ErrImagePull` | Registry auth issue from K8s cluster | Check if the cluster has pull access to the registry (imagePullSecrets or managed identity) |
| Pod stuck in `Pending` | Insufficient node resources | Scale up the node pool or reduce resource requests |
| Port mismatch (502 / connection refused) | App not listening on port 80 | Update `containerPort`, `port`, `targetPort` to match your app's actual port |

---

**Frontend app loads but API calls fail (CORS / 502)**

| Cause | Fix |
|---|---|
| `REACT_APP_API_URL` (or equivalent) is wrong | Update `FRONTEND_ENV_FILE` to set the correct backend LB IP/hostname |
| Backend not deployed yet | Deploy the backend pipeline first; note the backend LB IP; set it in the frontend env file |
| Backend internal LB not reachable | Ensure frontend pod is in the same VPC/VNet as the backend LB; or switch backend LB to public |
| CORS not configured on backend | Add the frontend origin to the backend's CORS allowed origins list |

---

**nginx / nginx.conf.template issues**

| Symptom | Likely Cause | Fix |
|---|---|---|
| Pod crashes immediately — `nginx: [emerg] unknown directive` | `envsubst` substituted nginx variables like `$host` or `$remote_addr` | Ensure `CMD` in Dockerfile lists **only** `'${BACKEND_HOST} ${BACKEND_PORT}'` — the variable list restricts what envsubst replaces |
| `502 Bad Gateway` on all API calls | `BACKEND_HOST` or `BACKEND_PORT` is wrong or not set | Check `kubectl exec <pod> -- cat /etc/nginx/nginx.conf` and verify the `upstream backend` line has the correct IP and port |
| `502 Bad Gateway` on all API calls | Backend pod is down or LB IP changed | Verify backend is running; get the new backend LB IP via `kubectl get svc`; update `FRONTEND_ENV_FILE` and redeploy |
| `nginx: [emerg] host not found in upstream` | `BACKEND_HOST` placeholder was not substituted (empty value) | Confirm `BACKEND_HOST` is in `FRONTEND_ENV_FILE` secret; check `kubectl describe secret frontend-env -n <namespace>` |
| `gettext` / `envsubst: not found` | `apk add gettext` was not added to Dockerfile | Add `RUN apk add --no-cache gettext` to the nginx stage of the Dockerfile (see Section 9) |
| SPA client-side routes return 404 | `nginx.conf.template` not copied into image | Verify `COPY nginx.conf.template /etc/nginx/nginx.conf.template` is in the Dockerfile; confirm file is present at `$AGENT_PATH` |
| Static assets return 404 | Build output is not in `/app/build` | Check where your framework (`react-scripts`, `vite`, etc.) puts the build output; update the `COPY --from=builder` path accordingly |
| API proxy route not found (404) | Route missing from `nginx.conf.template` | Add the missing `location` block to `nginx.conf.template` (see "Adding a new backend route" in Section 10), rebuild, and redeploy |

**Verify the resolved nginx config inside the running pod:**
```bash
kubectl exec -n <namespace> <pod-name> -- cat /etc/nginx/nginx.conf
```
This shows the final config after `envsubst` ran — confirm `upstream backend` shows the correct IP and port.

**Check nginx error logs:**
```bash
kubectl logs -n <namespace> <pod-name>
```

---

**Cannot reach the frontend after deployment**

| Cause | Fix |
|---|---|
| LB still provisioning | Wait 2–5 minutes; re-run `kubectl get svc -n <namespace>` until `EXTERNAL-IP` is shown |
| Internal LB, wrong network | Ensure you are accessing it from within the cluster's VPC/VNet (or via VPN) |
| Port 80 blocked by firewall | Open port 80 inbound in the NSG (Azure) / Security Group (AWS) / VPC Firewall (GCP) |
| Wrong runner label | Check that both jobs use the same `runs-on` label matching your registered runner |

---

## 17. Quick Checklist

**Azure / AKS — Frontend**

```
INFRASTRUCTURE
[ ] AKS cluster running and reachable
[ ] Azure Container Registry (ACR) created
[ ] Service Principal created with AcrPush + AKS deploy roles

RUNNER SETUP (VM)
[ ] Linux VM provisioned (Ubuntu 20.04/22.04, 2 vCPU, 4 GB RAM, 30 GB disk)
[ ] docker installed on VM
[ ] az CLI installed on VM
[ ] kubelogin installed on VM
[ ] kubectl installed on VM
[ ] AGENT_PATH set on the runner VM (pointing to frontend source with Dockerfile)
[ ] Corporate CA bundle present at /etc/ssl/certs/ca-bundle.crt (if on corporate network)
[ ] Runner registered in GitHub → Settings → Actions → Runners
[ ] Runner labels set to: self-hosted, Linux, X64, <your-label>
[ ] Runner running as a system service
[ ] Runner shows as Idle (green)

GITHUB SECRETS
[ ] AZURE_CLIENT_ID added
[ ] AZURE_CLIENT_SECRET added
[ ] AZURE_TENANT_ID added
[ ] AZURE_SUBSCRIPTION_ID added
[ ] FRONTEND_ENV_FILE added (KEY=VALUE pairs, one per line)

GITHUB VARIABLES
[ ] AZURE_CONTAINER_REGISTRY set (e.g. myregistry.azurecr.io)
[ ] RESOURCE_GROUP set
[ ] CLUSTER_NAME set
[ ] NAMESPACE set
[ ] DEPLOY_NAME set
[ ] CONTAINER_NAME set
[ ] SHORT_NAME set

REPOSITORY SETUP
[ ] Frontend Dockerfile present at $AGENT_PATH on the runner VM
[ ] nginx.conf.template present at $AGENT_PATH on the runner VM
[ ] BACKEND_HOST and BACKEND_PORT added to FRONTEND_ENV_FILE secret
[ ] .github/workflows/deploy-aks-frontend.yml created from template
[ ] Branch name updated in the workflow trigger (on: push: branches:)
[ ] Runner label updated in both job runs-on: fields
[ ] Code committed and pushed to trigger the pipeline
```

---

**AWS / EKS — Frontend**

```
INFRASTRUCTURE
[ ] EKS cluster running and reachable
[ ] ECR repository created
[ ] IAM user/role with ECR push + EKS deploy permissions

RUNNER SETUP (VM)
[ ] Linux VM provisioned (Ubuntu 20.04/22.04, 2 vCPU, 4 GB RAM, 30 GB disk)
[ ] docker installed on VM
[ ] aws CLI installed on VM
[ ] kubectl installed on VM
[ ] envsubst installed (sudo apt-get install -y gettext)
[ ] AGENT_PATH set on the runner VM (pointing to frontend source with Dockerfile)
[ ] Runner registered in GitHub → Settings → Actions → Runners
[ ] Runner labels set to: self-hosted, Linux, X64, <your-label>
[ ] Runner running as a system service
[ ] Runner shows as Idle (green)

GITHUB SECRETS
[ ] AWS_ACCESS_KEY_ID added
[ ] AWS_SECRET_ACCESS_KEY added
[ ] AWS_SESSION_TOKEN added (if using temporary/assumed-role credentials)
[ ] AWS_REGION added (e.g. us-east-1)
[ ] FRONTEND_ENV_FILE added (KEY=VALUE pairs, one per line)

GITHUB VARIABLES
[ ] ECR_REGISTRY set (e.g. 123456789012.dkr.ecr.us-east-1.amazonaws.com)
[ ] ECR_REPOSITORY set
[ ] EKS_CLUSTER_NAME set
[ ] NAMESPACE set
[ ] DEPLOY_NAME set
[ ] CONTAINER_NAME set
[ ] SHORT_NAME set

REPOSITORY SETUP
[ ] Frontend Dockerfile present at $AGENT_PATH on the runner VM
[ ] nginx.conf.template present at $AGENT_PATH on the runner VM
[ ] BACKEND_HOST and BACKEND_PORT added to FRONTEND_ENV_FILE secret
[ ] .github/workflows/deploy-eks-frontend.yml created from template
[ ] Branch name updated in the workflow trigger
[ ] Runner label updated in both job runs-on: fields
[ ] Code committed and pushed to trigger the pipeline
```

---

**GCP / GKE — Frontend**

```
INFRASTRUCTURE
[ ] GCP project with GKE and Artifact Registry APIs enabled
[ ] Artifact Registry repository created
[ ] GKE cluster running and reachable
[ ] Service Account created with container.developer + artifactregistry.writer roles

RUNNER SETUP (VM)
[ ] Linux VM provisioned (Ubuntu 20.04/22.04, 2 vCPU, 4 GB RAM, 30 GB disk)
[ ] docker installed on VM
[ ] gcloud CLI installed on VM and pre-authenticated
[ ] gke-gcloud-auth-plugin installed (gcloud components install gke-gcloud-auth-plugin)
[ ] kubectl installed on VM
[ ] envsubst installed (sudo apt-get install -y gettext)
[ ] AGENT_PATH set on the runner VM (pointing to frontend source with Dockerfile)
[ ] Runner registered in GitHub → Settings → Actions → Runners
[ ] Runner labels set to: self-hosted, <your-label>
[ ] Runner running as a system service
[ ] Runner shows as Idle (green)

GITHUB SECRETS
[ ] FRONTEND_ENV_FILE_GCP added (KEY=VALUE pairs, one per line)

GITHUB VARIABLES
[ ] GCP_PROJECT_ID set
[ ] GKE_CLUSTER_NAME set
[ ] GKE_ZONE set (e.g. us-central1-a)
[ ] ARTIFACT_REGISTRY set (e.g. us-central1-docker.pkg.dev/my-project/my-repo)
[ ] NAMESPACE set
[ ] DEPLOY_NAME set
[ ] CONTAINER_NAME set
[ ] SHORT_NAME set

REPOSITORY SETUP
[ ] Frontend Dockerfile present at $AGENT_PATH on the runner VM
[ ] nginx.conf.template present at $AGENT_PATH on the runner VM
[ ] BACKEND_HOST and BACKEND_PORT added to FRONTEND_ENV_FILE secret
[ ] .github/workflows/deploy-gke-frontend.yml created from template
[ ] Branch name updated in the workflow trigger
[ ] Runner label updated in both job runs-on: fields
[ ] Code committed and pushed to trigger the pipeline
```

---
