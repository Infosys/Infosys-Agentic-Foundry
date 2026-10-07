# Linux Server Deploy CI/CD Pipeline — Setup & Usage Guide

> **Purpose:** This guide helps any team set up and use the GitHub Actions CI/CD pipeline to automatically deploy a backend or frontend Python application to a **self-hosted Linux server** on every push. The pipeline handles proxy and SSL configuration for corporate networks (e.g., Infosys), copies code to the server, installs Python dependencies inside a virtual environment, and restarts the application service.

---

## 1. What This Pipeline Does

```
Commit to GitHub  ─────────────────────────────────────────────────────────┐
    ↓                                                                       │
[GitHub Actions Triggered by push / workflow_dispatch]                      │
    ↓                                                                       │
Checkout Code from GitHub                                                   │
    ↓                                                                       │
Setup Proxy & SSL                                                           │
   (For corporate networks — e.g., Infosys)                                 │
    ↓                                                                       │
Copy Code to Deployment Folder on Server                                    │
   + Write .env file from GitHub Secret                                     │
    ↓                                                                       │
Install Python Requirements                                                 │
   (Inside a virtual environment using uv)                                  │
    ↓                                                                       │
Restart Application Service via systemctl                                   │
    ↓                                                                       │
App is Live with New Code ──────────────────────────────────────────────────┘
```

> If any step fails, the pipeline automatically prints the last 50 lines of your service logs so you can diagnose the issue without manually SSH-ing into the server.

**The Core Concept: Runner = Server**

This is **not** a traditional remote deployment (no SSH, no SCP, no Docker push). The GitHub Actions **self-hosted runner is installed directly on the Linux server** where your app runs. So when the pipeline executes shell commands, they run **locally on that server** — the runner's workspace folder and your app's deployment folder are on the **same machine**.

```
┌─────────────────────────────────────────────────────────┐
│                  Your Linux Server (VM)                 │
│                                                         │
│  ┌──────────────────────┐   ┌────────────────────────┐  │
│  │  GitHub Actions      │   │  Your App              │  │
│  │  Runner Process      │   │  (systemd service)     │  │
│  │                      │   │                        │  │
│  │  /home/runner/work/  │──►│  /home/projadmin/      │  │
│  │  repo/  (workspace)  │cp │  CICD/MyApp/  (deploy) │  │
│  └──────────────────────┘   └────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

> Because the runner **is** the server, `cp` copies files locally and `sudo systemctl restart` picks them up immediately — no network transfer, no container registry, no Kubernetes involved.

---

## 2. How It Triggers

| Trigger | When |
|---|---|
| **Auto** | Push to your configured branch (e.g., `dev`, `test-env`) |
| **Manual** | GitHub → Actions → Select workflow → Run workflow |

> Update the branch name in the workflow YAML to match your deployment branch before using.

---

## 3. Prerequisites

Make sure all of the following exist before setting up:

| Requirement | Details |
|---|---|
| GitHub Repository | With Actions enabled |
| Self-hosted Runner | Linux/X64 machine registered in GitHub |
| Python | Installed on the server (Python 3.8+) |
| systemctl service | A `systemd` service file configured to run your app |
| SSL Certificate | Required if behind a corporate proxy with SSL inspection |
| Deployment Folder | Target directory on the server (created automatically by the pipeline) |
| `requirements.txt` | Present at the root of your repository |
| `sudo` access | Runner user must be able to run `systemctl restart` and `status` via `sudo` |

**Install Python on the Runner (Ubuntu/Debian)**

```bash
# Update package list
sudo apt-get update

# Install Python 3 and pip
sudo apt-get install -y python3 python3-pip python3-venv

# Verify installation
python3 --version
```

**Grant sudo access for systemctl (without password prompt)**

Add the following line to `/etc/sudoers` using `visudo` — replace `your-runner-user` with the actual user running the GitHub Actions runner:

```
your-runner-user ALL=(ALL) NOPASSWD: /bin/systemctl restart your-service.service, /bin/systemctl status your-service.service
```

> This ensures the pipeline can restart and check the service without requiring a password.

---

## 4. Configure Self-Hosted Runner on a VM

A self-hosted runner is a machine (VM or physical server) that runs your GitHub Actions jobs. This pipeline requires a runner with the labels `self-hosted`, `linux`, `x64`, and a custom label of your choice (e.g., `my-linux-runner`).

**Step 1 — Prepare Your VM**

Use any Linux VM (on-prem, AWS EC2, Azure VM, GCP Compute Engine, etc.). Recommended specs:

| Resource | Minimum |
|---|---|
| OS | Ubuntu 20.04 / 22.04 (64-bit) |
| CPU | 2 vCPUs |
| RAM | 4 GB |
| Disk | 20 GB |

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

When it asks for **additional labels**, enter a custom label that matches your workflow (e.g., `my-linux-runner`):

```
my-linux-runner
```

This allows the pipeline to target this runner with:

```yaml
runs-on: [self-hosted, linux, x64, my-linux-runner]
```

> If you already registered the runner without the custom label, add it from:
> **GitHub → Settings → Actions → Runners → Click your runner → Edit labels**

**Step 4 — Start the Runner**

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

**Step 5 — Verify Runner is Online
**
Go to **GitHub → Settings → Actions → Runners**.

You should see your runner listed with status **Idle** (green dot):

```
✔ my-runner    Idle    self-hosted, Linux, X64, <your-label>
```

---

## 5. Customize Branch Name and Runner Labels in Pipeline

**How to Change the Branch Name**

Open your workflow YAML file and find this section at the top:

```yaml
on:
  push:
    branches:
      - "your-branch"   # ← CHANGE THIS to your branch name e.g. dev, test-env
```

**Example — Multiple branches:**

```yaml
on:
  push:
    branches:
      - dev
      - test-env
      - staging
```

---

**How to Change the Self-Hosted Runner Labels**

The runner labels are defined in the `runs-on:` field of the deploy job:

```yaml
jobs:
  deploy:
    runs-on: [self-hosted, linux, x64, your-label-name]   # ← CHANGE to your runner label
```

**The labels must exactly match** what is registered on your self-hosted runner.

| Label | Meaning |
|---|---|
| `self-hosted` | Use a self-hosted runner (not GitHub-hosted) |
| `linux` | Runner OS is Linux |
| `x64` | Runner architecture is 64-bit |
| `your-label-name` | Custom label to target your specific runner |

---

## 6. GitHub Secrets & Variables Setup

**What are GitHub Secrets and GitHub Variables?**

GitHub provides two built-in mechanisms to pass configuration and credentials into your pipeline without hardcoding them in YAML files.

---

**GitHub Secrets**

A **GitHub Secret** is an **encrypted, sensitive value** stored securely at the repository level. It is designed for credentials, tokens, keys, and any information that must never be exposed publicly.

**How it works:**

- You create a secret once in the GitHub UI.
- GitHub encrypts it immediately — even repository admins cannot read it back after saving.
- The pipeline reads it at runtime using `${{ secrets.SECRET_NAME }}`.
- In logs, GitHub automatically **masks** the value and replaces it with `***`.

```yaml
# Example: writing the .env secret to a file
- name: Copy files to server
  env:
    ENV_FILE_CONTENT: ${{ secrets.APP_ENV_FILE_TEST_VM }}
  run: |
    printf "%s" "$ENV_FILE_CONTENT" > ${{ env.DEPLOY_PATH }}/.env
```

---

**GitHub Variables**

A **GitHub Variable** is a **plain-text, non-sensitive configuration value** stored at the repository level. It is designed for values that are safe to see in logs but you still don't want to hardcode in YAML files.

**How it works:**
- You create a variable once in the GitHub UI.
- The value is stored as plain text — it is **not** encrypted and **not** masked in logs.
- The pipeline reads it at runtime using `${{ vars.VARIABLE_NAME }}`.

```yaml
# Example: using a variable in env: block
env:
  DEPLOY_PATH: ${{ vars.DEPLOY_PATH || '/home/projadmin/CICD/ABC' }}
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

---

**How this pipeline uses both**

```
┌─────────────────────────────────────────────────────────────────┐
│                      GitHub Repository                          │
│                                                                 │
│  ┌───────────────────────┐   ┌──────────────────────────────┐  │
│  │   GitHub Variables    │   │    GitHub Secrets            │  │
│  │   (non-sensitive)     │   │    (sensitive)               │  │
│  │                       │   │                              │  │
│  │  DEPLOY_PATH          │   │  APP_ENV_FILE_TEST_VM        │  │
│  │  SERVICE_NAME         │   │  (full .env file content)    │  │
│  │  SSL_CERT_PATH        │   │                              │  │
│  │  HTTP_PROXY  ...      │   │                              │  │
│  └──────────┬────────────┘   └─────────────┬────────────────┘  │
│             │                              │                    │
│             └──────────────┬───────────────┘                    │
│                            ▼                                   │
│                  ┌──────────────────────┐                      │
│                  │  env: block in       │                      │
│                  │  workflow YAML       │                      │
│                  │  (central mapper)    │                      │
│                  └────────┬─────────────┘                      │
│                           ▼                                    │
│              ${{ env.* }} used throughout pipeline             │
└─────────────────────────────────────────────────────────────────┘
```

> **Rule of thumb:** If you would be uncomfortable posting the value in a public chat message — use a **Secret**. If it's just a path or a name — use a **Variable**.

---

**Required GitHub Secrets**

Go to: **Repo → Settings → Secrets and variables → Actions → New repository secret**

| Secret Name | What to Put | Example |
|---|---|---|
| `APP_ENV_FILE_TEST_VM` | Full content of your application `.env` file | *(see below)* |

> You can rename this secret to match your project (e.g., `APP_ENV_FILE_PROD`, `MY_APP_ENV`). If you rename it, update the reference in the YAML `Copy files to server` step accordingly.

**How to set the environment file secret**

Copy the **entire content** of your application `.env` file and paste it as the secret value:

```env
DATABASE_URL=postgres://user:password@host:5432/dbname
SECRET_KEY=your-secret-key
DEBUG=False
APP_PORT=8000
REDIS_URL=redis://localhost:6379
```

> The pipeline reads this secret and writes it directly to `<DEPLOY_PATH>/.env` on the server before restarting the service.

---

**Required GitHub Variables**

Go to: **Repo → Settings → Secrets and variables → Variables → New repository variable**

| Variable Name | Description | Example Value |
|---|---|---|
| `DEPLOY_PATH` | Folder on server where app will be deployed | `/home/projadmin/CICD/MyApp` |
| `SERVICE_NAME` | The `systemctl` service that runs your app | `my-fastapi.service` |
| `SSL_CERT_PATH` | Path to the SSL certificate file on the server | `/home/projadmin/cerifi.crt` |

**Optional GitHub Variables (corporate/proxy networks only)**

| Variable Name | Description | Example Value |
|---|---|---|
| `HTTP_PROXY` | Corporate proxy URL | `http://proxy.ad.corporate.com:123` |
| `NO_PROXY` | Hosts that should bypass the proxy | `.corporate.com,localhost,123.0.0.1` |

> If you are **not** behind a corporate proxy, you can leave `HTTP_PROXY` and `NO_PROXY` unset. The pipeline's proxy setup step will do nothing when these variables are empty.

---

## 7. Pipeline env: Block — How Variables Are Mapped

The `env:` block at the top of the workflow YAML is a **central mapper** — it reads values from GitHub Variables (`vars.*`) and exposes them as environment variables used throughout the pipeline. Default fallback values are provided in case the variables are not set.

> **You do not hardcode any values in the YAML file.** Set them once in GitHub UI (Section 6 above) and the pipeline picks them up automatically.

**How the env: block works**

```
GitHub Variables (vars.*)  ──►  env: block (mapper)  ──►  ${{ env.* }} used everywhere
```

**This pipeline's env: block**

```yaml
env:
  DEPLOY_PATH:         ${{ vars.DEPLOY_PATH      || '/home/projadmin/CICD/ABC' }}
  SERVICE_NAME:        ${{ vars.SERVICE_NAME      || 'CICD-fastapi.service' }}
  SSL_CERT:            ${{ vars.SSL_CERT_PATH     || '/home/projadmin/cerifi.crt' }}
  NODE_EXTRA_CA_CERTS: ${{ vars.SSL_CERT_PATH     || '/home/projadmin/cerifi.crt' }}
```

**What each variable does**

| Variable | Used In Step | Purpose |
|---|---|---|
| `DEPLOY_PATH` | Copy files, Install requirements, Restart service | Root folder where your app code is deployed on the server |
| `SERVICE_NAME` | Restart service, Debug on Failure | Name of the `systemd` service that runs your app |
| `SSL_CERT` | Setup Proxy and SSL, Install requirements | Path to the SSL certificate for HTTPS calls through corporate proxy |
| `NODE_EXTRA_CA_CERTS` | Node.js steps (if any) | Tells Node.js to trust the custom SSL certificate |

**Fallback defaults**

The `||` operator in the `env:` block provides a **fallback default** if the GitHub Variable is not set:

| Variable | Default fallback value |
|---|---|
| `DEPLOY_PATH` | `/home/projadmin/CICD/ABC` |
| `SERVICE_NAME` | `CICD-fastapi.service` |
| `SSL_CERT` | `/home/projadmin/cerifi.crt` |

> Always set these as GitHub Variables in your repository — the defaults are just safety nets to prevent pipeline failures on misconfigured repos.

---

## 9. Workflow File Setup

1. In your repository, create the folder `.github/workflows/` if it doesn't exist.
2. Inside it, create a file named `deploy-linux.yml` (or any name you prefer).
3. Paste the YAML from [Section 10](#10-full-pipeline-yaml) into that file.
4. Update the `branches` trigger and `runs-on` runner label to match your setup.
5. Set all required GitHub Secrets and Variables (Section 6).
6. Commit and push — the pipeline will trigger automatically.

**Folder structure:**

```
your-repo/
├── .github/
│   └── workflows/
│       └── deploy-linux.yml    ← Pipeline file
├── requirements.txt             ← Required: Python dependencies
├── main.py                      ← Your app entry point
├── .env                         ← NOT committed — written by pipeline from secret
└── ...
```

> The `.env` file is **never committed to the repository**. The pipeline creates it at deploy time from the `APP_ENV_FILE_TEST_VM` secret.

---

## 10. Full Pipeline YAML

```yaml
# =====================================================================
# Build and Deploy to Self-Hosted Linux Server
# =====================================================================
name: Backend/Frontend Deploy

on:
  push:
    branches:
      - "your-branch"   # Change this to your branch name e.g. dev, test-env

  workflow_dispatch:

env:
  DEPLOY_PATH:         ${{ vars.DEPLOY_PATH      || '/home/projadmin/CICD/ABC' }}
  SERVICE_NAME:        ${{ vars.SERVICE_NAME      || 'CICD-fastapi.service' }}
  SSL_CERT:            ${{ vars.SSL_CERT_PATH     || '/home/projadmin/cerifi.crt' }}
  NODE_EXTRA_CA_CERTS: ${{ vars.SSL_CERT_PATH     || '/home/projadmin/cerifi.crt' }}

jobs:
  deploy:
    name: Deploy to Linux Server
    runs-on: [self-hosted, linux, x64, your-label-name]   # ← Replace with your runner label

    steps:

      - name: Checkout code
        uses: actions/checkout@v4
        with:
          ref: main   # Change if you want to deploy from a different branch

      - name: Setup Proxy and SSL
        run: |
          export http_proxy=${{ vars.HTTP_PROXY }}
          export https_proxy=${{ vars.HTTP_PROXY }}
          export no_proxy=${{ vars.NO_PROXY }}
          export SSL_CERT_FILE=${{ env.SSL_CERT }}

      - name: Copy files to server
        env:
          ENV_FILE_CONTENT: ${{ secrets.APP_ENV_FILE_TEST_VM }}
        run: |
          echo "Deploying to ${{ env.DEPLOY_PATH }}..."
          mkdir -p ${{ env.DEPLOY_PATH }}
          cp -rfv ./* ${{ env.DEPLOY_PATH }}
          printf "%s" "$ENV_FILE_CONTENT" > ${{ env.DEPLOY_PATH }}/.env

      - name: Install Python Requirements
        run: |
          VENV_PATH="${{ env.DEPLOY_PATH }}/venv"

          if [ ! -d "$VENV_PATH" ]; then
            echo "Creating virtual environment..."
            python -m venv "$VENV_PATH"
          fi

          source "$VENV_PATH/bin/activate"

          pip install uv

          export PIP_CERT="${{ env.SSL_CERT }}"

          REQ_FILE="${{ env.DEPLOY_PATH }}/requirements.txt"
          if [ -f "$REQ_FILE" ]; then
            uv pip install -r "$REQ_FILE"
          else
            echo "WARNING: requirements.txt not found at $REQ_FILE"
            exit 1
          fi

      - name: Restart service
        run: |
          echo "Restarting ${{ env.SERVICE_NAME }}..."
          sudo systemctl restart ${{ env.SERVICE_NAME }}
          sudo systemctl status  ${{ env.SERVICE_NAME }} --no-pager

      - name: Debug on Failure
        if: failure()
        run: |
          echo "=== Something went wrong. Printing service logs... ==="
          sudo journalctl -u ${{ env.SERVICE_NAME }} --no-pager --tail=50
```

---

## 11. How Each Step Works

**Step 1 — Checkout Code**

```yaml
- name: Checkout code
  uses: actions/checkout@v4
  with:
    ref: main
```

**What it does:**

Downloads the repository code onto the runner machine using the official GitHub `actions/checkout` action.

!!! note "Key note"
    The `ref: main` setting means the pipeline always deploys from the `main` branch, even if the pipeline was triggered by a push to a different branch (e.g., a `dev` branch can trigger the pipeline, but the code deployed will always be from `main`). Change `ref: main` to `ref: ${{ github.ref }}` if you want to deploy the branch that triggered the pipeline.

---

**Step 2 — Setup Proxy and SSL**

```yaml
- name: Setup Proxy and SSL
  run: |
    export http_proxy=${{ vars.HTTP_PROXY }}
    export https_proxy=${{ vars.HTTP_PROXY }}
    export no_proxy=${{ vars.NO_PROXY  }}
    export SSL_CERT_FILE=${{ env.SSL_CERT }}
```

**What it does:**

Configures the HTTP/HTTPS proxy and SSL certificate for the current shell session. This is required in corporate networks (e.g., Infosys) where all internet traffic is routed through a proxy with SSL inspection.

| Variable | Purpose |
|---|---|
| `http_proxy` / `https_proxy` | Routes outbound HTTP/HTTPS traffic through the corporate proxy |
| `no_proxy` | Hosts that should **skip** the proxy (internal servers, localhost) |
| `SSL_CERT_FILE` | Points tools to the custom SSL certificate for HTTPS verification |

> **If you are not behind a proxy:** Leave `HTTP_PROXY` and `NO_PROXY` variables unset. The exported values will be empty and have no effect.

---

**Step 3 — Copy Files to Server**

```yaml
- name: Copy files to server
  env:
    ENV_FILE_CONTENT: ${{ secrets.APP_ENV_FILE_TEST_VM }}
  run: |
    echo "Deploying to ${{ env.DEPLOY_PATH }}..."
    mkdir -p ${{ env.DEPLOY_PATH }}
    cp -rfv ./* ${{ env.DEPLOY_PATH }}
    printf "%s" "$ENV_FILE_CONTENT" > ${{ env.DEPLOY_PATH }}/.env
```

**What it does:**

1. Creates the deployment folder if it does not already exist (`mkdir -p`).
2. Copies all files from the GitHub Actions workspace (checked-out repo) to the deployment folder on the server.
3. Writes the `.env` file from the `APP_ENV_FILE_TEST_VM` secret so the application gets its configuration at runtime.

**Why `printf` instead of `echo` for the .env file?**

`printf "%s"` writes the content exactly as-is, preserving all newlines and special characters correctly. Using `echo` can add an extra newline or mishandle certain characters.

---

**Step 4 — Install Python Requirements**

```yaml
- name: Install Python Requirements
  run: |
    VENV_PATH="${{ env.DEPLOY_PATH }}/venv"

    if [ ! -d "$VENV_PATH" ]; then
      echo "Creating virtual environment..."
      python -m venv "$VENV_PATH"
    fi

    source "$VENV_PATH/bin/activate"
    pip install uv
    export PIP_CERT="${{ env.SSL_CERT }}"

    REQ_FILE="${{ env.DEPLOY_PATH }}/requirements.txt"
    if [ -f "$REQ_FILE" ]; then
      uv pip install -r "$REQ_FILE"
    else
      echo "WARNING: requirements.txt not found at $REQ_FILE"
      exit 1
    fi
```

**What it does:**

1. **Creates a virtual environment** (`venv`) inside the deployment folder — only if one does not already exist. This avoids re-creating it on every deployment, saving time.
2. **Activates the virtual environment** so all subsequent `pip`/`uv` commands install into the isolated environment.
3. **Installs `uv`** — a fast Python package installer written in Rust (much faster than plain `pip`).
4. **Sets `PIP_CERT`** — points pip/uv to the corporate SSL certificate so package downloads succeed through the proxy.
5. **Installs packages** from `requirements.txt` using `uv pip install`.
6. **Fails the pipeline** (`exit 1`) if `requirements.txt` is not found, to prevent a silent partial deployment.

---

**Step 5 — Restart Service**

```yaml
- name: Restart service
  run: |
    echo "Restarting ${{ env.SERVICE_NAME }}..."
    sudo systemctl restart ${{ env.SERVICE_NAME }}
    sudo systemctl status  ${{ env.SERVICE_NAME }} --no-pager
```

**What it does:**

1. Restarts your application's `systemd` service so the newly deployed code goes live.
2. Immediately prints the service status in the pipeline logs so you can confirm the service started correctly without SSH-ing into the server.

**Prerequisite:** 

The runner user must have `sudo` access to run `systemctl restart` and `systemctl status` without a password prompt (see [Prerequisites](#3-prerequisites)).

---

**Step 6 — Debug on Failure**

```yaml
- name: Debug on Failure
  if: failure()
  run: |
    echo "=== Something went wrong. Printing service logs... ==="
    sudo journalctl -u ${{ env.SERVICE_NAME }} --no-pager --tail=50
```

**What it does:**

This step runs **only if any previous step fails** (`if: failure()`). It automatically prints the last 50 lines of your service's `journald` logs, giving you immediate visibility into what went wrong — without needing to manually SSH into the server.

---

**Full Deployment Flow**

```
Developer pushes code to GitHub
           │
           ▼
GitHub notifies the self-hosted runner on your server
           │
           ▼
Runner clones repo → /home/runner/work/your-repo/   (new code, not live yet)
           │
           ▼
Proxy & SSL configured for the shell session
           │
           ▼
cp -rfv → files copied to /home/projadmin/CICD/MyApp/  (new code on disk)
printf  → .env written from GitHub Secret              (config on disk)
           │
           ▼
pip/uv installs any new packages into venv             (dependencies ready)
           │
           ▼
sudo systemctl restart → old process killed, new process starts
                       → new process reads updated files from DEPLOY_PATH
           │
           ▼
App is live with new code  ✔
```

---

**Key Design Decisions**

| Decision | Why |
|---|---|
| Runner installed on the app server | Eliminates need for SSH keys, SCP, or remote agents — `cp` is enough |
| `venv` only created if missing | Avoids re-creating the entire virtual environment on every deploy (saves 30–60s) |
| `uv` instead of `pip` | 10–100x faster package installation |
| `printf "%s"` for .env | Preserves exact content — `echo` can corrupt special characters or add trailing newlines |
| `ref: main` in checkout | Ensures only tested/reviewed code from `main` is deployed, even if a feature branch triggered the pipeline |
| Secrets for `.env` content | The `.env` file never touches the git repository — it's injected at deploy time only |
| `if: failure()` on debug step | Automatic log collection on failure without any manual intervention |

---

## 15. Troubleshooting

**Common Errors**

| Error / Problem | Cause | Fix |
|---|---|---|
| `APP_ENV_FILE_TEST_VM secret is empty` | Secret not added in GitHub | Go to Settings → Secrets → Actions → add `APP_ENV_FILE_TEST_VM` |
| `.env file is malformed` | Special characters in secret value | Ensure the .env content is plain text with `KEY=VALUE` pairs, no extra quotes |
| `requirements.txt not found` | File missing from repo or wrong deploy path | Confirm `requirements.txt` is committed to the repo root |
| `pip install fails with SSL error` | Corporate proxy SSL inspection | Set `SSL_CERT_PATH` variable to the correct cert path on the server |
| `uv: command not found` | `pip install uv` failed due to proxy/SSL issue | Fix proxy/SSL settings; verify `pip` can reach PyPI |
| `systemctl: command not found` | Not a systemd-based Linux system | Confirm the server uses systemd (Ubuntu 18.04+ / CentOS 7+) |
| `sudo: systemctl: command not found` | Incorrect sudo PATH | Use full path: `sudo /bin/systemctl restart ...` |
| `Permission denied on systemctl` | Runner user lacks sudo for systemctl | Add the sudoers entry from the [Prerequisites](#3-prerequisites) section |
| `Service failed to start` | App error — missing env variable or port conflict | Check service logs: `sudo journalctl -u <SERVICE_NAME> --no-pager --tail=100` |
| `Runner offline / no jobs picked up` | Runner service stopped | SSH into the server and run `sudo ./svc.sh status` then `sudo ./svc.sh start` |
| `cp: cannot stat './*'` | Empty checkout or wrong working directory | Confirm the checkout step ran successfully; check workspace path |
| `venv already exists but broken` | Corrupted virtual environment from a past run | Delete the venv folder manually on the server: `rm -rf $DEPLOY_PATH/venv` |

**How to check service logs manually**

```bash
# Last 50 lines of service logs
sudo journalctl -u your-service.service --no-pager --tail=50

# Follow live logs
sudo journalctl -u your-service.service -f

# Check service status
sudo systemctl status your-service.service
```

**How to test the pipeline manually (without a code push)**

1. Go to your GitHub repository.
2. Click **Actions** → select the workflow → click **Run workflow**.
3. Choose your branch and click **Run workflow**.

---

## 16. Quick Checklist

Use this checklist when setting up the pipeline for a new repository.

```
SERVER SETUP
[ ] Linux server running (Ubuntu 20.04/22.04 recommended)
[ ] Python 3.8+ installed on the server (python3 --version)
[ ] systemd service file created for your app (/etc/systemd/system/<SERVICE_NAME>)
[ ] Service enabled: sudo systemctl enable <SERVICE_NAME>
[ ] SSL certificate placed at the path you will set in SSL_CERT_PATH
[ ] Deployment folder parent directory is writable by the runner user

RUNNER SETUP
[ ] Linux/X64 runner provisioned
[ ] Runner registered in GitHub → Settings → Actions → Runners
[ ] Runner labels set to: self-hosted, linux, x64, <your-custom-label>
[ ] Runner running as a system service (sudo ./svc.sh install && sudo ./svc.sh start)
[ ] Runner shows as Idle (green) in GitHub → Settings → Actions → Runners
[ ] Runner user has sudo access for systemctl (sudoers entry added)

GITHUB SECRETS
[ ] APP_ENV_FILE_TEST_VM added (full .env file content pasted as secret value)

GITHUB VARIABLES
[ ] DEPLOY_PATH set (e.g. /home/projadmin/CICD/MyApp)
[ ] SERVICE_NAME set (e.g. my-fastapi.service)
[ ] SSL_CERT_PATH set (e.g. /home/projadmin/cerifi.crt)


REPOSITORY SETUP
[ ] requirements.txt present at root of repository
[ ] .github/workflows/deploy-linux.yml created with pipeline YAML
[ ] Branch name updated in the workflow trigger (branches: section)
[ ] Runner label updated in jobs.deploy.runs-on
[ ] ref: main updated if deploying from a different branch
[ ] Code committed and pushed to trigger the pipeline

VERIFY DEPLOYMENT
[ ] Pipeline run shows green in GitHub → Actions
[ ] All 5 steps completed successfully (Checkout, Proxy, Copy, Install, Restart)
[ ] Service status shows "active (running)" in step 5 logs
[ ] Application is reachable on the expected port/URL
```

---
