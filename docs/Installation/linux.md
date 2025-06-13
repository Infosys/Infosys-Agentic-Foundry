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
- To install Node.js:
    1. Go to [https://nodejs.org/en/download](https://nodejs.org/en/download).
    2. Choose version **22.16.0** or any higher stable version.
    3. Download and install Node.js (NPM comes bundled with Node.js).
- After installation, open your command prompt or terminal.
- Run `node -v` to confirm that it shows version 22 or higher.
 
 
- **JFrog Access for Node Dependencies:**
    - You need JFrog access to download node dependencies for the React UI application.
    - If you already have JFrog access, you can proceed.
    - If not, follow these steps:
        1. Ensure you are connected to the Infosys network or that Zscaler is enabled.
        2. Follow the instructions in the guide: **NPM – Install and Publish with JFrog Artifactory SAAS and ZS**.
        3. (Note: You may skip the 7th step mentioned in that guide.)
 
 
 
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
cd backend
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
cd frontend
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
 
1. **Edit Constants File:**
 
```bash
nano frontend/src/constants.js
```
 
2. **Update BASE_URL:**
 
```javascript
// Replace with your actual backend server IP address and port
export const BASE_URL = "http://your-backend-server-ip:your-backend-port";
 
// Examples:
// export const BASE_URL = "http://192.168.1.100:8000";
// export const BASE_URL = "http://10.0.0.50:8000";
// export const BASE_URL = "http://localhost:8000";  // If frontend and backend are on same machine
```
 
**Configure Backend CORS Settings**
 
Update the backend server file (typically `agentic_workflow_as_service_endpoints.py`):
 
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
nano backend/.env
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
nano frontend/.env
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
cd backend
# Replace port number if using a different backend port
uvicorn agentic_workflow_as_service_endpoints:app --host 0.0.0.0 --port your-backend-port --workers 4
 
# Example:
# uvicorn agentic_workflow_as_service_endpoints:app --host 0.0.0.0 --port 8000 --workers 4
```
 
**Start the Frontend**
 
```bash
cd frontend
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
 
Create systemd service file:
 
```bash
sudo nano /etc/systemd/system/infyagent-backend.service
```
 
Add content (replace placeholders with your actual values):
 
```ini
[Unit]
Description=FastAPI Application with Gunicorn
After=network.target
 
[Service]
# Replace with your actual project path
WorkingDirectory=/home/your-username/your-project-directory/backend
# Replace with your actual paths, username, and port
ExecStart=/home/your-username/your-project-directory/backend/.venv/bin/python -m gunicorn agentic_workflow_as_service_endpoints:app \
  --workers 1 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:your-backend-port
Restart=always
# Replace with your actual username
User=your-username
# Replace with your actual proxy settings (remove if not using proxy)
Environment="http_proxy=http://your-proxy-server:your-proxy-port"
Environment="https_proxy=http://your-proxy-server:your-proxy-port"
StandardOutput=journal
StandardError=journal
 
[Install]
WantedBy=multi-user.target
```
 
**Example configuration:**
```ini
[Unit]
Description=FastAPI Application with Gunicorn
After=network.target
 
[Service]
WorkingDirectory=/home/projadmin/Infyagentframework/backend
ExecStart=/home/projadmin/Infyagentframework/backend/.venv/bin/python -m gunicorn agentic_workflow_as_service_endpoints:app \
  --workers 1 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000
Restart=always
User=projadmin
Environment="http_proxy=http://blrproxy.ad.infosys.com:443"
Environment="https_proxy=http://blrproxy.ad.infosys.com:443"
StandardOutput=journal
StandardError=journal
 
[Install]
WantedBy=multi-user.target
```
 
**Things You Need to Customize:**
 
1. **Project Path**  
   Replace `/home/your-username/your-project-directory/` with your actual project path
 
2. **Username**  
   Replace `your-username` with your actual Linux username
 
3. **Backend Port**  
   Replace `your-backend-port` with your chosen backend port (e.g., 8000)
 
4. **Proxy Settings**  
   Replace `your-proxy-server:your-proxy-port` with actual proxy details, or remove if not using proxy
 
5. **App Module Name**  
   Change `agentic_workflow_as_service_endpoints:app` if your FastAPI app module has a different name
 
Enable and start the service:
 
```bash
sudo systemctl enable infyagent-backend.service
sudo systemctl start infyagent-backend.service
sudo systemctl status infyagent-backend.service
```
 
**Frontend Service (Optional)**
 
Create systemd service file for frontend:
 
```bash
sudo nano /etc/systemd/system/infyagent-frontend.service
```
 
Add content:
 
```ini
[Unit]
Description=React Frontend Application
After=network.target
 
[Service]
# Replace with your actual project path
WorkingDirectory=/home/your-username/your-project-directory/frontend
# Replace with your actual paths and port
ExecStart=/usr/bin/npm start
Restart=always
# Replace with your actual username
User=your-username
# Set environment variables
Environment=NODE_ENV=production
Environment=PORT=your-frontend-port
Environment=HOST=0.0.0.0
# Replace with your actual proxy settings (if needed)
Environment="http_proxy=http://your-proxy-server:your-proxy-port"
Environment="https_proxy=http://your-proxy-server:your-proxy-port"
StandardOutput=journal
StandardError=journal
 
[Install]
WantedBy=multi-user.target
```
 
## Network Configuration
 
**Port Configuration Summary**
 
**Default Ports (customize as needed):**
 
- Frontend: `6002` (replace with `your-frontend-port`)
- Backend: `8000` (replace with `your-backend-port`)
 
**Security Group / Firewall Rules**
 
Ensure the following ports are open in your VM's security group or firewall:
 
```bash
# Replace with your actual port numbers
sudo firewall-cmd --permanent --add-port=your-frontend-port/tcp
sudo firewall-cmd --permanent --add-port=your-backend-port/tcp
sudo firewall-cmd --permanent --add-port=22/tcp  # SSH access
sudo firewall-cmd --reload
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
cd backend
source ./.venv/bin/activate
pip install -r requirements.txt
 
# Update frontend dependencies
cd frontend
npm install
 
# Restart services after updates
sudo systemctl restart infyagent-backend.service
sudo systemctl restart infyagent-frontend.service
```
 
## Project Structure
 
The structure shown below is a sample. The full project includes additional files and directories not listed here.
 
```
Infyagentframework/
├── backend/                  # Backend FastAPI application
│   ├── .venv/                # Python virtual environment (generated)
│   ├── requirements.txt      # Python dependencies
│   ├── .env                  # Environment variables (create this)
│   └── agentic_workflow_as_service_endpoints.py  # Main API file
├── frontend/                 # React frontend application
│   ├── node_modules/         # Node.js dependencies (generated)
│   ├── public/               # Static assets
│   ├── src/                  # React source code
│   │   ├── components/       # React components
│   │   ├── pages/            # Page components
│   │   ├── services/         # API service functions
│   │   ├── constants.js      # Configuration constants (update BASE_URL here)
│   │   ├── App.js            # Main App component
│   │   └── index.js          # Entry point
│   ├── package.json          # Node.js dependencies and scripts (update PORT here)
│   ├── package-lock.json     # Lock file for dependencies
│   └── .env                  # Environment variables (create this)
└── README.md                 # Project documentation
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