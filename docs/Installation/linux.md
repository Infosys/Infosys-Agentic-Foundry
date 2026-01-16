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

1. **Install from CCD** - Install a required greenlisted Python version
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

Install the required Python version (example with Python 3.11.8):

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
   You can use your system's Software Center or Company Portal to install Node.js (version 22 or higher). Npm comes bundled with Node.js. JFrog access is required for downloading Node dependencies—see below for details.

- **For Akaash VM or Production VM:**  
   Software Center, Company Portal, and public internet access may not be available. In such cases, you must request all required software installation files (including Node.js and npm) from CCD.

- **Linux Node.js Exception:**  
   On Linux VMs (including Akaash/Production), you can install Node.js and npm using the following commands:

   ```bash
   sudo dnf module enable nodejs:22
   sudo dnf install nodejs npm
   node --version
   ```

   If you are behind a proxy, configure npm as follows:

   ```bash
   npm config set proxy http://blrproxy.ad.infosys.com:443
   npm config set https-proxy http://blrproxy.ad.infosys.com:443
   ```

---

## JFrog Access for Node Dependencies

To download Node dependencies for the React UI, you need JFrog access.

- If you already have JFrog access, you can proceed with `npm install`.
- If not, follow these steps:
    1. Ensure you are connected to the Infosys network or that Zscaler is enabled.
    2. Refer to the guide: **NPM – Install and Publish with JFrog Artifactory SAAS and ZS**.

Contact your administrator if you need help with JFrog access.



## Setting Up Proxy in Linux Environment (If Required)

If your network requires a proxy to access the internet, follow these steps to set proxy values as environment variables:

**Steps:**

 **Set proxy environment variables temporarily:**

```bash
# Replace with your actual proxy server and port
export http_proxy=http://your-proxy-server:your-proxy-port
export https_proxy=http://your-proxy-server:your-proxy-port

# Example (replace with your actual proxy details):
# export http_proxy=http://blrproxy.ad.infosys.com:443
# export https_proxy=http://blrproxy.ad.infosys.com:443
```

 **To make proxy settings permanent, add to your shell profile:**

```bash
# Replace with your actual proxy server and port
echo 'export http_proxy=http://your-proxy-server:your-proxy-port' >> ~/.bashrc
echo 'export https_proxy=http://your-proxy-server:your-proxy-port' >> ~/.bashrc
source ~/.bashrc
```

!!! note
    💡 Always verify proxy details with your CCD or VM administrator and replace the example values with your actual proxy configuration.

## Download the Backend Project Code

- To access the Agentic Foundry GitHub repository, you must have access to InfyGit.

- If you already have InfyGit access, click the link below and authenticate to gain access to the Agentic Foundry GitHub repository.  [https://github.com/enterprises/infosys/sso](https://github.com/enterprises/infosys/sso)

You can obtain the project files using one of the following methods:

**Option 1: Clone Using Git**

```bash
git clone https://github.com/Infosys-Generative-AI/Infyagentframework
cd Infyagentframework
```

**Option 2: Download Zip from GitHub**

1. Navigate to: [https://github.com/Infosys-Generative-AI/Infyagentframework](https://github.com/Infosys-Generative-AI/Infyagentframework)
2. Click "Code" → "Download Zip"
3. Extract to your preferred location

**Transferring Files to Linux VM (if needed)**

If transferring from another machine, use SCP:
```bash
# Replace with your actual username, VM IP address, and file paths
scp -r /path/to/your/local/project your-username@your-vm-ip-address:/home/your-username/

# Example:
# scp -r /Users/john/Infyagentframework projadmin@192.168.1.100:/home/projadmin/
```

## Backend Setup

**Setting Up the Backend Environment**

1. **Navigate to Backend Directory:**

```bash
cd Infyagentframework
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
cd Agentic-Pro-UI
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

4. **Configure Port and Host in `package.json`:**

Edit `package.json` to configure the development server:

```json
"scripts": {
  "start": "PORT=your-frontend-port HOST=0.0.0.0 react-scripts start",
  "build": "PORT=your-frontend-port HOST=0.0.0.0 react-scripts build"
}
```

**Example configuration:**
```json
"scripts": {
  "start": "PORT=6002 HOST=0.0.0.0 react-scripts start",
  "build": "PORT=6002 HOST=0.0.0.0 react-scripts build"
}
```

5. **Open Firewall Ports:**

```bash
# Replace with your actual frontend and backend port numbers
sudo firewall-cmd --permanent --add-port=your-frontend-port/tcp
sudo firewall-cmd --permanent --add-port=your-backend-port/tcp

# Example with default ports:
# sudo firewall-cmd --permanent --add-port=6002/tcp  # Frontend
# sudo firewall-cmd --permanent --add-port=8000/tcp  # Backend

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
nano frontend/src/constants.js
```

**2. Update Base URL for the API server:**

```javascript
// Replace with your actual backend server IP address and port
REACT_APP_BASE_URL = "http://your-backend-server-ip:your-backend-port";

// Examples:
// REACT_APP_BASE_URL = "http://192.168.1.100:8000";
// REACT_APP_BASE_URL = "http://10.0.0.50:8000";
// REACT_APP_BASE_URL = "http://localhost:8000";  // If frontend and backend are on same machine
```

**Configure Backend CORS Settings**

In the backend `.env` file (`Infyagentframework/.env`), set the allowed frontend origins:

```env
# Add your frontend IP address
UI_CORS_IP="<your-frontend-server-ip>"

# Add your frontend IP with port number
UI_CORS_IP_WITH_PORT="<your-frontend-server-ip:your-frontend-port>"
```

Update the backend server file (typically `run_server.py`):

```python
origins = [
    # Replace with your actual frontend server IP and port
    "http://your-frontend-server-ip:your-frontend-port",
    "http://localhost:3000",
    "http://localhost:6002",
    # Add additional origins as needed
]

# Examples:
# origins = [
#     "http://192.168.1.101:6002",
#     "http://10.0.0.51:6002",
#     "http://localhost:3000",
#     "http://localhost:6002",
# ]
```

## Environment Configuration

**Backend Environment Variables**

Create `.env` file in backend directory:

```bash
nano Infyagentframework/.env
```

Add the following content (replace with your actual values):

```bash
DEBUG=False
# Replace with your actual API keys and configuration
API_KEY=your_actual_api_key_here
DATABASE_URL=your_database_url_here
SECRET_KEY=your_secret_key_here

# Example:
# API_KEY=sk-1234567890abcdef
# DATABASE_URL=postgresql://user:password@localhost/dbname
# SECRET_KEY=your-super-secret-key-here
```

**Frontend Environment Variables**

Create `.env` file in frontend directory:

```bash
nano Agentic-Pro-UI/.env
```

Add the following content:

```bash
# Replace with your actual backend IP address and port
REACT_APP_API_URL=http://your-backend-ip:your-backend-port
REACT_APP_API_TIMEOUT=30000

# Examples:
# REACT_APP_API_URL=http://192.168.1.100:8000
# REACT_APP_API_URL=http://10.0.0.50:8000
# REACT_APP_API_URL=http://localhost:8000
```

## Running the Applications

**Start the Backend Server**

With the virtual environment activated:

```bash
cd Infyagentframework
# Replace port number if using a different backend port
uvicorn agentic_workflow_as_service_endpoints:app --host 0.0.0.0 --port your-backend-port --workers 4

# Example:
# uvicorn agentic_workflow_as_service_endpoints:app --host 0.0.0.0 --port 8000 --workers 4
```

**Start the Frontend**

```bash
cd Agentic-Pro-UI
npm start
```

The React UI will be accessible at:
- `http://your-vm-ip:your-frontend-port`
- Example: `http://192.168.1.101:6002`

## Accessing the Applications

**Frontend Access URLs:**

- Local access: `http://localhost:your-frontend-port`
- Network access: `http://your-vm-ip:your-frontend-port`
- Example: `http://192.168.1.101:6002`

**Backend API Access URLs:**

- Local access: `http://localhost:your-backend-port`
- Network access: `http://your-vm-ip:your-backend-port`
- Example: `http://192.168.1.100:8000`
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
WorkingDirectory=/home/your-username/your-project-directory/
Environment="NO_PROXY=localhost,127.0.0.1,::1,model_server_ip,ip_of_this_VM"
Environment="HTTP_PROXY=http://blrproxy.ad.infosys.com:443"
Environment="HTTPS_PROXY=http://blrproxy.ad.infosys.com:443"
Environment=VIRTUAL_ENV=/home/your-username/your-project-directory/venv
Environment=PATH=/home/your-username/your-project-directory/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin/:/sbin:/bin
ExecStart=/home/your-username/your-project-directory/venv/bin/python main.py --host 0.0.0.0 --port your-backend-port
Restart=always
User=your-username
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Example backend configuration:**

```ini
[Unit]
Description=FastAPI Application
After=network.target

[Service]
WorkingDirectory=/home/projadmin/Infyagentframework
Environment="NO_PROXY=localhost,127.0.0.1,::1,10.212.121.151,10.208.85.72"
Environment="HTTP_PROXY=http://blrproxy.ad.infosys.com:443"
Environment="HTTPS_PROXY=http://blrproxy.ad.infosys.com:443"
Environment=VIRTUAL_ENV=/home/projadmin/Infyagentframework/venv
Environment=PATH=/home/projadmin/Infyagentframework/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin/:/sbin:/bin
ExecStart=/home/projadmin/Infyagentframework/venv/bin/python main.py --host 0.0.0.0 --port 5001
Restart=always
User=projadmin
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
5. **ExecStart:** Ensure the Python path and script name (`main.py`) match your project.
6. **Proxy Settings:** Adjust or remove proxy environment variables if not required.

Enable and start the service:

```bash
sudo systemctl enable infyagent-backend.service
sudo systemctl start infyagent-backend.service
sudo systemctl status infyagent-backend.service
```

**Frontend Service (Optional)**

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
WorkingDirectory=/home/your-username/your-project-directory/
ExecStart=/usr/bin/npm start
Restart=always
User=your-username
Environment=NODE_ENV=production
Environment=PORT=3003

[Install]
WantedBy=multi-user.target
```

**Example frontend configuration:**

```ini
[Unit]
Description=My Node.js Application
After=network.target

[Service]
WorkingDirectory=/home/projadmin/Agentic-Pro-UI1
ExecStart=/usr/bin/npm start
Restart=always
User=projadmin
Environment=NODE_ENV=production
Environment=PORT=3003

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

## Network Testing

Test connectivity between frontend and backend:

```bash
# Test backend API from frontend server
curl http://your-backend-server-ip:your-backend-port/health

# Test frontend access
curl http://your-frontend-server-ip:your-frontend-port
```

## Troubleshooting


**Connection Issues**

**1. Frontend cannot connect to Backend:**

   - Verify `BASE_URL` in `frontend/src/constants.js`
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
cd Infyagentframework
source ./.venv/bin/activate
pip install -r requirements.txt

# Update frontend dependencies
cd Agentic-Pro-UI
npm install

# Restart services after updates
sudo systemctl restart infyagent-backend.service
sudo systemctl restart infyagent-frontend.service
```

## Project Structure

The structure shown below is a sample. The full project includes additional files and directories not listed here.

Backend project structure:

```
Infyagentframework/
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
Agentic-Pro-UI/                    # React frontend application
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
uvicorn agentic_workflow_as_service_endpoints:app --host 0.0.0.0 --port your-backend-port

# Frontend access
http://your-vm-ip:your-frontend-port

# Backend API access
http://your-vm-ip:your-backend-port/docs
```

Remember to replace all placeholder values with your actual IP addresses, ports, usernames, and paths before deployment!