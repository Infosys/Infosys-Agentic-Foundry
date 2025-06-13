# Project Setup Guide

This document provides comprehensive step-by-step instructions to set up and run the project on your local machine and deploy it to Azure VM.

## Prerequisites

Before proceeding, ensure you have the following installed on your system:

1. **Python** (version 3.8 or higher)
2. **pip** (Python package manager)
3. **Virtual Environment Support** (comes pre-installed with Python 3.3+)
4. **Streamlit and Uvicorn dependencies** (will be installed during setup)

## Local Development Setup

**Step 1: Create a Virtual Environment**

A virtual environment is used to isolate project dependencies. Run the following command in the terminal or command prompt:

```bash
python -m venv .venv
```

This will create a virtual environment named `.venv` in the project directory.

**Step 2: Activate the Virtual Environment**

To activate the virtual environment, use the appropriate command for your operating system:

For Windows :
```bash
.\.venv\Scripts\activate
```

For macOS/Linux
```bash
source .venv/bin/activate
```

!!! note
    Once activated, your terminal prompt will change to indicate the virtual environment is active.

**Step 3: Install Project Dependencies**

After activating the virtual environment, install the required dependencies:

```bash
pip install -r requirements.txt
```

This will install all the libraries and packages listed in the `requirements.txt` file.

**Step 4: Run the Backend Server**

To start the backend server, ensure the virtual environment is active and run:

```bash
uvicorn agentic_workflow_as_service_endpoints:app --host 0.0.0.0 --port 8000 --workers 4
```

**Command Explanation:**

- `uvicorn`: A lightweight ASGI server
- `agentic_workflow_as_service_endpoints:app`: Refers to the Python module and the FastAPI app instance
- `--host 0.0.0.0`: Makes the server accessible from any network interface
- `--port 8000`: Specifies the port on which the server will run
- `--workers 4`: Specifies the number of worker processes to handle requests

!!! success
    The backend server will start and be accessible at:
    - `http://0.0.0.0:8000` (local access)
    - `http://<your-local-ip>:8000` (network access)

**Step 5: Run the User Interface**

To launch the user interface, ensure the virtual environment is active and execute:

```bash
streamlit run user_interface.py --server.port 8501 --server.address 0.0.0.0
```

**Command Explanation:**

- `streamlit`: A Python library for building web-based user interfaces
- `user_interface.py`: The script containing the Streamlit application
- `--server.port 8501`: Specifies the port for the Streamlit app
- `--server.address 0.0.0.0`: Makes the app accessible from any network interface

!!! info
    The Streamlit app will open in your default web browser automatically. If not, access it at:
    - `http://0.0.0.0:8501` (local access)
    - `http://<your-local-ip>:8501` (network access)

## Azure VM Deployment

**Prerequisites for Azure Deployment**

1. **Valid Azure Subscription**
2. **CCD Request** for Azure Windows VM resource
3. **Required Software(to be installed on Azure VM)**:
    - Python 3.12 or above (avoid latest unstable versions)
    - VS Code
    - GitBash (if required)
    - NSSM (for service management)

**Deployment Steps**

**Step 1: Azure VM Setup**

1. Request a valid Azure Subscription
2. Raise a CCD request to add an Azure Windows VM resource
3. Wait for CCD team to create the VM resource and share credentials
4. Install required software on Azure VM:
   - Use CCD team assistance, or
   - Install locally and transfer via "infydrive"

**Step 2: Application Deployment**

1. Move your application folder to Azure VM
2. Follow Steps 1-5 from the [Local Development Setup](#local-development-setup) section
3. Verify application accessibility from outside the VM by sharing network URL with external users

!!! warning
    At this stage, the application will only remain active while the Azure VM is running. VM shutdown will cause application downtime.

## How to Make the Server Run 24/7 on Windows Using NSSM

**Step 1: Create a Batch File**

Create a new file named `servers.bat` (you can choose any name).

Paste the following content into the file:

```bat
@echo off
REM Activate Python virtual environment
cd /d "C:\Code\Infyagentframework-main\Infyagentframework-main\.venv\Scripts"
call activate.bat

REM Change to project directory
cd /d "C:\Code\Infyagentframework-main\Infyagentframework-main\backend"

REM Start FastAPI backend
start cmd /k "uvicorn agentic_workflow_as_service_endpoints:app --host 0.0.0.0 --port 8000 --workers 4"

REM Start Node.js frontend
cd /d "C:\Code\Agentic-Pro-UI\frontend"
start cmd /k "npm start"

pause
```

!!! warning "Important"
    Make sure the file paths match your system's folder structure.

!!! tip
    Save the file somewhere accessible, like your desktop or project root.

**Step 2: Install and Configure NSSM**

1. **Download NSSM** if not already installed: [https://nssm.cc/download](https://nssm.cc/download)
2. Open **Command Prompt as Administrator**.
3. Run this command to open the NSSM setup:

```bash
nssm install infy_agent.service
```

!!! note "Custom Service Name"
    You can replace `infy_agent.service` with any name you prefer, such as `my_server_service`, `webstack_service`, or `custom_backend`. Just make sure to use the same name consistently in all subsequent commands.

4. In the NSSM GUI:
   - For **Application path**, browse and select your `servers.bat` file.
   - Click **Install Service**.

**Step 3: Manage the Service**

Use these commands from the terminal (as Administrator):

**Start the service:**
```bash
nssm start infy_agent.service
```

**Stop the service:**
```bash
nssm stop infy_agent.service
```

**Edit the service:**
```bash
nssm edit infy_agent.service
```

You can also go to **Windows Services** (press `Win + R`, type `services.msc`) to start, stop, or set the service to run automatically on startup.


## Troubleshooting

**Virtual Environment Activation Fails**

- **Windows**: Ensure you're using the correct command for your OS
- **Permissions Error**: Try running command prompt as administrator

**Dependency Installation Errors**

Update pip to the latest version:
```bash
python -m pip install --upgrade pip
```

**Server or UI Not Starting**

1. Verify the virtual environment is active
2. Check for typos in commands or file names
3. Ensure all dependencies are properly installed

## Additional Notes

!!! tip "Best Practices"
    - Always activate the virtual environment before running project commands
    - Verify all dependencies are installed correctly by checking `requirements.txt`
    - To deactivate the virtual environment, simply run: `deactivate`

