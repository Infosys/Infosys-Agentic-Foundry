# Linux VM Deployment Guide

This guide provides detailed instructions for setting up and running the FastAPI backend and React frontend project on Linux Virtual Machines.

## Project Overview

This project consists of a backend server built with FastAPI and a frontend interface using React, designed for deployment on Linux VMs.

## Prerequisites

Ensure you have the following installed on your Linux system:

**System Requirements**

- **sudo privileges** (for installing system packages)
- **Python 3.11 or higher** (for backend)
- **NodeJS version 22 or higher**  
- **NPM version 10.9.2 or higher** ( comes bundled with NodeJs) 
- **Git** (optional, for cloning the repository)
- **Redis 8.2.1**
- **Postgres 17**

## Python Version Setup

**Check Your Python Version**

First, verify your current Python version:

```bash
python --version
# or
python3 --version
```

Make sure it is **3.11 or higher**. If it's not, you'll need to update your Python version.

**Python Installation Options**

There are 2 ways to install the required Python version:

1. **Install** - Install a required greenlisted Python version
2. **Use pyenv** - Update the Python version using pyenv (recommended)

## Installing Python with pyenv on RHEL

To install pyenv on Red Hat Enterprise Linux (RHEL), follow these steps. pyenv lets you easily install and switch between multiple Python versions.

**Step 1: Install Required Dependencies**

You'll need development tools and libraries for building Python:

```bash
sudo dnf groupinstall "Development Tools" -y
sudo dnf install -y \
    gcc zlib-devel bzip2 bzip2-devel readline-devel sqlite sqlite-devel \
    openssl-devel libffi-devel wget make xz-devel \
    git curl patch
```

**Step 2: Install pyenv**

Clone the pyenv repository into your home directory:

```bash
git clone https://github.com/pyenv/pyenv.git ~/.pyenv
```

**Step 3: Set Up Shell Environment**

Add the following to your shell config file (e.g., `~/.bashrc`, `~/.bash_profile`, or `~/.zshrc`):

```bash
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init --path)"
eval "$(pyenv init -)"
```

Then apply the changes:

```bash
source ~/.bashrc
# or
exec "$SHELL"
```

**Step 4: Verify Installation**

Run the following command to verify pyenv is installed correctly:

```bash
pyenv --version
```

**Step 5: Install Python Version**

Install the required Python version (example with Python >=3.11.8 or <3.13):

```bash
pyenv install 3.11.8
```

You can also install other versions as needed:

```bash
# List available Python versions
pyenv install --list

# Install specific version
pyenv install 3.12.0
```

**Step 6: Set Global Python Version**

Set the installed Python version as your global default:

```bash
pyenv global 3.11.8
```

Verify the installation:

```bash
python --version
```

**Verify Node.js and npm**

To verify your Node.js and npm installations, open Terminal and run:

```bash
node -v
npm -v
```

- If Node.js is installed, running the version command will display the installed version.
- If Node.js is not installed, you will see an error in the terminal such as `"node" is not recognized as an internal or external command`.

**Installation Guidance**

- **For Local Linux Setup:**  
   Install Node.js (version 22 or higher). Npm comes bundled with Node.js. For downloading Node dependencies—see below for details.

- **Linux RHEL VM Setup:**  
   On RHEL VMs, you can install Node.js and npm using the following commands:

   ```bash
   sudo dnf module enable nodejs:22
   sudo dnf install nodejs npm
   node --version
   ```

   If you are behind a proxy, configure npm as follows:

   ```bash
   npm config set proxy <your_proxy>
   npm config set https-proxy <your_proxy>
   ```

---


## Setting Up Proxy in Linux Environment (If Required)

If your network requires a proxy to access the internet, follow these steps to set proxy values as environment variables:

**Steps:**

 **Set proxy environment variables temporarily:**

```bash
# Replace with your actual proxy server and port
export http_proxy=http://your-proxy-server:your-proxy-port
export https_proxy=http://your-proxy-server:your-proxy-port
```

 **To make proxy settings permanent, add to your shell profile:**

```bash
# Replace with your actual proxy server and port
echo 'export http_proxy=http://your-proxy-server:your-proxy-port' >> ~/.bashrc
echo 'export https_proxy=http://your-proxy-server:your-proxy-port' >> ~/.bashrc
source ~/.bashrc
```

!!! note
    💡 Always verify proxy details with your administrator and replace the example values with your actual proxy configuration.

## Download the Backend Project Code


You can obtain the project files using one of the following methods:

**Option 1: Clone Using Git**

```bash
git clone https://github.com/Infosys/Infosys-Agentic-Foundry
cd Infosys-Agentic-Foundry
```

**Option 2: Download Zip from GitHub**

1. Navigate to: [https://github.com/Infosys/Infosys-Agentic-Foundry](https://github.com/Infosys/Infosys-Agentic-Foundry)
2. Click "Code" → "Download Zip"
3. Extract to your preferred location

**Transferring Files to Linux VM (if needed)**

If transferring from another machine, use SCP:
```bash
# Replace with your actual username, VM IP address, and file paths
scp -r /path/to/your/local/project your-username@your-vm-ip-address:/home/your-username/
```

## Backend Setup

**Setting Up the Backend Environment**

1. **Navigate to Backend Directory:**

```bash
cd Infosys-Agentic-Foundry-Backend
```

2. **Create a Virtual Environment:**

```bash
python3 -m venv .venv
```

3. **Activate the Virtual Environment:**

```bash
source ./.venv/bin/activate
```

4. **Install Backend Dependencies:**

```bash
pip install -r requirements.txt
```

If you face any SSL error issue, use the below command:

```bash
pip install -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org
```

## Frontend Setup

**Setup on Linux VM**

1. **Navigate to Frontend Directory:**

```bash
cd Infosys-Agentic-Foundry-Frontend
```

2. **Remove Existing Lock File (if present):**

```bash
rm -f package-lock.json
```

3. **Install Node Modules:**

```bash
npm install
```

If you encounter proxy issues during npm install, configure npm proxy:

```bash
# Replace with your actual proxy server and port
npm config set proxy http://your-proxy-server:your-proxy-port
npm config set https-proxy http://your-proxy-server:your-proxy-port

# Then run npm install
npm install
```

4. **Open Firewall Ports (RHEL):**

```bash
# Replace with your actual frontend and backend port numbers
sudo firewall-cmd --permanent --add-port=your-frontend-port/tcp
sudo firewall-cmd --permanent --add-port=your-backend-port/tcp


# Reload firewall
sudo firewall-cmd --reload

# Verify ports are open
sudo firewall-cmd --list-ports
```

## Configuration Setup

**Frontend-Backend Connection Configuration**:
Configure Frontend to Connect to Backend

**1. Edit Constants File:**

```bash
nano Infosys-Agentic-Foundry-Frontend/.env
```

**2. Update Base URL for the API server:**

```javascript
// Replace with your actual backend server IP address and port
REACT_APP_BASE_URL = "http://your-backend-server-ip:your-backend-port";

```

**Configure Backend CORS Settings**

In the backend `.env` file (`Infosys-Agentic-Foundry-Backend/.env`), set the allowed frontend origins:

```env
# Add your frontend IP address
UI_CORS_IP="<your-frontend-server-ip>"

# Add your frontend IP with port number
UI_CORS_IP_WITH_PORT="<your-frontend-server-ip:your-frontend-port>"
```

If you want to let other UI connect to the backend, Update the backend server file (typically `run_server.py` or `main.py`):

```python
origins = [
    # Replace with your actual frontend server IP and port
    "http://your-frontend-server-ip:your-frontend-port",
    "http://localhost:3000",
    "http://localhost:6002",
    # Add additional origins as needed
]

```

## Environment Configuration

**Backend Environment Variables**

Create `.env` file in backend directory:

```bash
nano Infosys-Agentic-Foundry-Backend/.env
```

Add the following content (replace with your actual values):

```bash
DEBUG=False
# Replace with your actual API keys and configuration
API_KEY=your_actual_api_key_here
DATABASE_URL=your_database_url_here
SECRET_KEY=your_secret_key_here

```

**Frontend Environment Variables**

Create `.env` file in frontend directory:

```bash
nano Infosys-Agentic-Foundry-Frontend/.env
```

Add the following content:

```bash
# Replace with your actual backend IP address and port
REACT_APP_API_URL=http://your-backend-ip:your-backend-port

```

## Model Server Setup

For detailed instructions on deploying and configuring your model server, refer to the [Model Server Deployment](../Model_server.md#model-server-setup-localvm-deployment) guide.


## Running the Applications

**Start the Backend Server**

With the virtual environment activated:

```bash
cd Infosys-Agentic-Foundry-Backend

python run_server.py --host 0.0.0.0 --port your-backend-port `or`
python main.py --host 0.0.0.0 --port your-backend-port

```

**Start the Frontend**

```bash
cd Infosys-Agentic-Foundry-Frontend
npm start
```

The React UI will be accessible at:

- `http://your-vm-ip:your-frontend-port`

## Accessing the Applications

**Frontend Access URLs:**

- Local access: `http://localhost:your-frontend-port`
- Network access: `http://your-vm-ip:your-frontend-port`

**Backend API Access URLs:**

- Local access: `http://localhost:your-backend-port`
- Network access: `http://your-vm-ip:your-backend-port`
- API Documentation: `http://your-vm-ip:your-backend-port/docs`

## Service Deployment

- Running as System Services

**Backend Service**

Create a systemd service file:

```bash
sudo nano /etc/systemd/system/infyagent-backend.service
```

Add the following content (replace placeholders with your actual values):

```ini
[Unit]
Description=FastAPI Application
After=network.target

[Service]
WorkingDirectory=/home/your-username/your-project-directory/Infosys-Agentic-Foundry-Backend
Environment="NO_PROXY=localhost,127.0.0.1,::1,model_server_ip,ip_of_this_VM"
Environment="HTTP_PROXY=<your_proxy>"
Environment="HTTPS_PROXY=<your_proxy>"
Environment="PYTHONUNBUFFERED=1"
Environment=VIRTUAL_ENV=/home/your-username/your-project-directory/Infosys-Agentic-Foundry-Backend/venv
Environment=PATH=/home/your-username/your-project-directory/Infosys-Agentic-Foundry-Backend/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin/:/sbin:/bin
ExecStart=/home/your-username/your-project-directory/Infosys-Agentic-Foundry-Backend/venv/bin/python main.py --host 0.0.0.0 --port your-backend-port
Restart=always
User=your-username
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```


**Things You Need to Customize:**

1. **Project Path:** Replace `/home/your-username/your-project-directory/` with your actual project path.
2. **Username:** Replace `your-username` with your actual Linux username.
3. **Backend Port:** Replace `your-backend-port` with your chosen backend port (e.g., 8000).
4. **NO_PROXY:** Update with your model server IP and VM IP as needed.
5. **ExecStart:** Ensure the Python path and script name (`main.py` or `run_server.py`) match your project.
6. **Proxy Settings:** Adjust or remove proxy environment variables if not required.

Enable and start the service:

```bash
sudo systemctl enable infyagent-backend.service
sudo systemctl start infyagent-backend.service
sudo systemctl status infyagent-backend.service
```

**Frontend Service**

Create a systemd service file for the frontend:

```bash
sudo nano /etc/systemd/system/infyagent-frontend.service
```

Add the following content:

```ini
[Unit]
Description=My Node.js Application
After=network.target

[Service]
WorkingDirectory=/home/your-username/your-project-directory/Infosys-Agentic-Foundry-Frontend
ExecStart=/usr/bin/npm start
Restart=always
User=your-username
Environment=NODE_ENV=production
Environment=PORT=<your_port>

[Install]
WantedBy=multi-user.target

```

**Customize the following:**

- **WorkingDirectory:** Set to your actual frontend project path.
- **User:** Set to your Linux username.
- **PORT:** Set to your desired frontend port.

Enable and start the frontend service:

```bash
sudo systemctl enable infyagent-frontend.service
sudo systemctl start infyagent-frontend.service
sudo systemctl status infyagent-frontend.service
```
**Start Phoenix server using systemctl**

```ini
[Unit]
Description=Phoenix Logging Server
After=network.target

[Service]
User=your-username
WorkingDirectory=/home/your-username/your-project-directory/Infosys-Agentic-Foundry-Backend
ExecStart=/home/your-username/your-project-directory/Infosys-Agentic-Foundry-Backend/venv/bin/python -m phoenix.server.main serve
Restart=always
RestartSec=5
Environment=HTTP_PROXY=
Environment=NO_PROXY=localhost,127.0.0.1
Environment=PHOENIX_GRPC_PORT=50051
Environment=PHOENIX_SQL_DATABASE_URL=postgresql://postgres:<your-password>@localhost:5432/arize_traces

[Install]
WantedBy=multi-user.target
```

## Network Testing

Test connectivity between frontend and backend:

```bash
# Test backend API from frontend server
curl http://your-backend-server-ip:your-backend-port/health

# Test frontend access
curl http://your-frontend-server-ip:your-frontend-port
```

## Git Installation

Install Git using your OS package manager:

- **RHEL/CentOS/Fedora:**
    ```bash
    sudo dnf install git -y
    ```
- **Debian/Ubuntu:**
    ```bash
    sudo apt update
    sudo apt install git -y
    ```
- **SUSE/OpenSUSE:**
    ```bash
    sudo zypper install git -y
    ```

---

## Grafana Installation

1. Download and install Grafana Enterprise:
    ```bash
    wget https://dl.grafana.com/enterprise/release/grafana-enterprise-12.0.2-1.x86_64.rpm
    sudo dnf install grafana-enterprise-12.0.2-1.x86_64.rpm -y
    ```

2. Start and enable Grafana service:
    ```bash
    sudo systemctl daemon-reload
    sudo systemctl start grafana-server
    sudo systemctl enable grafana-server
    ```

---

## OpenTelemetry Collector Installation

1. Download and extract the OpenTelemetry Collector Contrib binary:
    ```bash
    wget https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v0.127.0/otelcol-contrib_0.127.0_linux_amd64.tar.gz
    tar -xvzf otelcol-contrib_0.127.0_linux_amd64.tar.gz
    sudo mv otelcol-contrib /usr/local/bin/
    sudo chmod +x /usr/local/bin/otelcol-contrib
    ```

2. Create the configuration file:
    ```bash
    sudo nano /usr/local/bin/otelcol-contrib.yaml
    ```
    Sample config:
    ```
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
        endpoints: ["http://localhost:9200"]
        logs_index: "agentic-foundry-tool-logs"
        sending_queue:
          enabled: true

    processors:
      batch:

    service:
      pipelines:
        traces:
          receivers: [otlp]
          processors: [batch]
          exporters: [debug]
        metrics:
          receivers: [otlp]
          processors: [batch]
          exporters: [debug]
        logs:
          receivers: [otlp]
          processors: [batch]
          exporters: [debug, elasticsearch]

      telemetry:
        logs:
          level: info
        metrics:
          level: basic
          address: localhost:8889
    ```

**Systemd Service Setup for OpenTelemetry Collector**

1. Create a systemd unit file:
    ```bash
    sudo nano /etc/systemd/system/otelcol-contrib.service
    ```
    Content:
    ```
    [Unit]
    Description=OpenTelemetry Collector Contrib
    After=network.target

    [Service]
    Type=simple
    ExecStart=/usr/local/bin/otelcol-contrib --config /usr/local/bin/otelcol-contrib.yaml
    Restart=on-failure

    [Install]
    WantedBy=multi-user.target
    ```
2. Enable and start the service:
    ```bash
    sudo systemctl enable otelcol-contrib.service
    sudo systemctl start otelcol-contrib.service
    sudo systemctl status otelcol-contrib.service
    ```

**Firewall Example for RHEL9**

To allow external access to OpenTelemetry ports (replace as needed):
```bash
# Example: RHEL9 firewall commands for OpenTelemetry Collector (if using firewalld)
sudo firewall-cmd --permanent --add-port=4318/tcp
sudo firewall-cmd --permanent --add-port=4319/tcp
sudo firewall-cmd --permanent --add-port=4320/tcp
sudo firewall-cmd --reload
```

---

## Elasticsearch Installation

1. Download and extract Elasticsearch:
    ```bash
    wget https://artifacts.elastic.co/downloads/elasticsearch/elasticsearch-8.17.3-linux-x86_64.tar.gz
    tar -xzf elasticsearch-8.17.3-linux-x86_64.tar.gz
    sudo mv elasticsearch-8.17.3 /opt/
    cd /opt/elasticsearch-8.17.3/config/
    ```

**Elasticsearch Configuration (elasticsearch.yml)**

1. Edit or create `elasticsearch.yml` (location: `/opt/elasticsearch-8.17.3/config/elasticsearch.yml`):
    ```bash
    sudo nano elasticsearch.yml
    ```
    Sample local development configuration:
    ```
    # ======================== Elasticsearch Configuration =========================

    cluster.name: my-local-dev-cluster
    node.name: node-1

    # Security & network settings for local dev ONLY:
    network.host: 0.0.0.0
    http.port: 9200
    discovery.type: single-node

    xpack.security.enabled: false
    xpack.security.enrollment.enabled: false
    xpack.security.http.ssl.enabled: false
    xpack.security.transport.ssl.enabled: false
    ```

    > Leave other default settings as-is or commented. For true single-node development, set `discovery.type: single-node`, disable all security as above, and bind only to `127.0.0.1`.

**Systemd Service Setup for Elasticsearch**

1. Create a systemd unit file:
    ```bash
    sudo nano /etc/systemd/system/elasticsearch.service
    ```
    Content:
    ```
    [Unit]
    Description=Elasticsearch
    Documentation=https://www.elastic.co
    After=network.target

    [Service]
    Type=simple
    User=projadmin
    Group=projadmin
    ExecStart=/opt/elasticsearch-8.17.3/bin/elasticsearch
    Environment="ES_JAVA_OPTS=-Xms4g -Xmx4g"
    WorkingDirectory=/opt/elasticsearch-8.17.3
    Restart=on-failure
    LimitNOFILE=65535

    [Install]
    WantedBy=multi-user.target
    ```

2. Enable and start Elasticsearch:
    ```bash
    sudo systemctl enable elasticsearch.service
    sudo systemctl start elasticsearch.service
    sudo systemctl status elasticsearch.service
    ```

**Elasticsearch Firewall Example for RHEL9**

To allow HTTP access (default port 9200, for local development only):

```bash
# Example: RHEL9 firewall commands for Elasticsearch (if using firewalld)
sudo firewall-cmd --permanent --add-port=9200/tcp
sudo firewall-cmd --reload
```

## Troubleshooting


**Connection Issues**

**1. Frontend cannot connect to Backend:**

   - Verify `REACT_APP_BASE_URL` in `Infosys-Agentic-Foundry-Frontend/.env`
   - Check CORS settings in backend
   - Ensure backend server is running and accessible
   - Test: `curl http://your-backend-ip:your-backend-port/health`

**2. Cannot access applications from external network:**

   - Check firewall rules: `sudo firewall-cmd --list-ports`
   - Verify HOST is set to `0.0.0.0` (not `localhost`)
   - Check VM security group settings

**Service Issues**

**3. Service fails to start:**

   - Check service logs: `sudo journalctl -u infyagent-backend.service -f`
   - Verify file paths in service configuration
   - Check user permissions
   - Ensure virtual environment is properly configured

**Proxy Issues**

**4. Cannot install packages or clone repositories:**

   - Verify proxy settings: `echo $http_proxy`
   - Check proxy configuration with your administrator
   - Test proxy: `curl -I http://google.com`

**Log Locations**

- **Backend service logs:** `sudo journalctl -u infyagent-backend.service`
- **Frontend service logs:** `sudo journalctl -u infyagent-frontend.service`
- **System logs:** `/var/log/messages`

**Maintenance**

Keep your deployment updated:

```bash
# Update project (if using Git)
git pull origin main

# Update backend dependencies
cd Infosys-Agentic-Foundry-Backend
source ./.venv/bin/activate
pip install -r requirements.txt

# Update frontend dependencies
cd Infosys-Agentic-Foundry-Frontend
npm install

# Restart services after updates
sudo systemctl restart infyagent-backend.service
sudo systemctl restart infyagent-frontend.service
```

## Project Structure

The structure shown below is a sample. The full project includes additional files and directories not listed here.

Backend project structure:

```
Infosys-Agentic-Foundry-Backend/
├── src/                  # Source code
│   ├── agent_templates/  # Agent onboarding templates and configurations   
│   ├── api/              # REST API endpoints and route handlers
│   ├── auth/             # Authentication and authorization services
│   ├── config/           # Database connectivity and cache configurations
│   ├── database/         # Database models, repositories, and services
│   ├── file_templates/   # Template files for various operations
│   ├── inference/        # AI model inference and agent execution logic
│   ├── models/           # Data models and business logic
│   ├── prompts/          # Prompt templates for AI interactions
│   ├── schemas/          # Pydantic schemas for data validation
│   ├── tools/            # Utility tools and helper functions
│   └── utils/            # Common utilities and shared functions
├── .venv/                # Python virtual environment (auto-generated)
├── requirements.txt      # Python dependencies specification
├── main.py               # Application entry point
├── run_server.py         # Development server runner with additional options
├── .env                  # Environment variables (create from .env.example)
├── .env.example          # Template for environment configuration
└── README.md             # Project documentation
```

Frontend project structure:

```
Infosys-Agentic-Foundry-Frontend/  # React frontend application
├── .github/                       # GitHub configuration
├── node_modules/                  # Node.js dependencies (generated)
├── public/                        # Static assets
├── src/                           # React source code
│   ├── Assets/                    # Image and media assets
│   ├── components/                # React components
│   ├── context/                   # React context providers
│   ├── css_modules/               # CSS module files
│   ├── Hooks/                     # Custom React hooks
│   ├── Icons/                     # SVG icons and graphics
│   ├── services/                  # API service functions
│   ├── App.js                     # Main App component with routing
│   ├── constant.js                # Configuration constants (BASE_URL, APIs)
│   ├── index.js                   # Entry point
│   ├── index.css                  # Global styles
│   └── ProtectedRoute.js          # Route protection component
├── package.json                   # Node.js dependencies and scripts
├── package-lock.json             # Lock file for dependencies
├── README.md                      # Project documentation
└── .env.example                          # Environment variables (not shown but referenced)
```


**Default Commands with Placeholders:**

```bash
# Backend startup
python run_server.py --host 0.0.0.0 --port your-backend-port `or`
python main.py --host 0.0.0.0 --port your-backend-port

# Frontend access
http://your-vm-ip:your-frontend-port

# Backend API access
http://your-vm-ip:your-backend-port/docs
```

Remember to replace all placeholder values with your actual IP addresses, ports, usernames, and paths before deployment!