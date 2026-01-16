# Windows Setup Guide

This guide provides step-by-step instructions for setting up and running the project with React UI on a Windows VM (Virtual Machine).

## Project Overview

This project consists of a backend server built with FastAPI and a frontend interface using React. Follow the instructions below to get it up and running on your VM.

## Prerequisites

Before proceeding, ensure you have the following installed:

## Required Software

- Python 3.11 or higher
- pip (Python package manager)
- Git (optional, for cloning the repository)
- A code editor (e.g., VS Code is recommended, but any editor of your choice will work)
- NodeJS version 22 or above  
- NPM version 10.9.2 or above ( comes bundled with NodeJs) 

To verify your Node.js and npm installations, open Terminal and run:

```bash
node -v
npm -v
```

- If Node.js is installed, running the version command will display the installed version.
- If Node.js is not installed, you will see an error in the terminal such as `"node" is not recognized as an internal or external command`.

**For Local Windows Setup**

- To install Node.js:
    - Go to Software Center / Company Portal on your laptop  
    - Search for NodeJs  
    - Choose version **22** or any higher stable version.
    - Install Node.js (NPM comes bundled with Node.js).
- After installation, open your command prompt or terminal.
- Run `node -v` to confirm that it shows version 22 or higher.

**JFrog Access for Node Dependencies:**

- You need JFrog access to download node dependencies for the React UI application.
- If you already have JFrog access, you can proceed.
- If not, follow these steps:
    - Ensure you are connected to the Infosys network or that Zscaler is enabled.
    - Follow the instructions in the guide: **NPM – Install and Publish with JFrog Artifactory SAAS and ZS**.

**For Akaash VM or Production VM Setup**

- **Important:** In Akaash VMs or Production VMs, public internet access and access to Software Center or Company Portal may not be available.
- In such cases, you must request all required software installation files (such as Node.js, Python, Git, etc.) from your CCD (Cloud/Compute/Desktop support) team.
- CCD will provide the necessary installers and instructions for offline installation.
- Ensure you have JFrog access configured, as node dependencies will still be downloaded from internal repositories.
- If you face any issues with installations or access, contact your CCD or VM administrator for support.

##  Setting Up Proxy in System Environment Variables (If Required)

If your network requires a proxy to access the internet, follow these steps to set proxy values as system environment variables:

**Steps:**

1. Open the **Start Menu** and search for **Environment Variables**.
2. Click on **"Edit the system environment variables"**.
3. In the **System Properties** window, click on the **"Environment Variables"** button.
4. Under the **System variables** section, click **New**.
5. Create the following two variables (ask your VM creator or CCD):

```bash
   Variable name: http_proxy
   Variable value: http://blrproxy.ad.infosys.com:443
   
   Variable name: https_proxy
   Variable value: http://blrproxy.ad.infosys.com:443
```

6. Click **OK** to save and close all windows.
7. Restart your Command Prompt or system (if needed) for the changes to take effect.

!!! note
    💡 These values are just examples. Always verify proxy details with your CCD or VM administrator.

## Download the Backend Project Code

- To access the Agentic Foundry GitHub repository, you must have access to InfyGit.

- If you already have InfyGit access, click the link below and authenticate to gain access to the Agentic Foundry GitHub repository.  [https://github.com/enterprises/infosys/sso](https://github.com/enterprises/infosys/sso)

You can obtain the project files using one of the following methods:

**Option 1: Clone Using Git**

If you have Git installed, open Terminal and run:

```bash
git clone https://github.com/Infosys-Generative-AI/Infyagentframework
cd Infyagentframework
```

- The git clone command will create a new folder named "Infyagentframework" in your current directory and download all repository files into it.
- The cd command navigates into the newly created folder.

**Option 2: Download Zip from GitHub**

1. Navigate to the repository in your web browser: [https://github.com/Infosys-Generative-AI/Infyagentframework](https://github.com/Infosys-Generative-AI/Infyagentframework)
2. Click the green "Code" button
3. Select "Download Zip"
4. Extract the Zip file to your preferred location on your machine

!!!Note 
     ZIP file will be difficult have track of development from other developers, so avoid this option unless necessary

## Branching Mechanism

The project uses a two-branch workflow to manage code stability and development:

- **main**:  
    - Contains stable, production-ready code.
    - Deployments to the production (Linux) server are made from this branch.
    - QA testing and client demos are conducted using code from `main`.

- **development**:  
    - Used for ongoing development and testing.
    - All new features and defect fixes are first implemented here.
    - Developers create separate feature or fix branches from `development` for their work.
    - After completing their task and unit testing, developers merge their feature/fix branch back into `development` to keep it up to date.

**Release Process:**

- Once QA verifies that the application is working as expected in the `development` branch, the code is merged into `main`.
- The updated `main` branch is then deployed to production for demos and further testing.

This workflow ensures that only tested and approved code reaches production, while active development happens separately.

## Download the Frontend Project Code

You can obtain the project files using one of the following methods:

**Option 1: Clone Using Git**

If you have Git installed, open Terminal and run:

```bash
git clone https://github.com/Infosys-Generative-AI/Agentic-Pro-UI.git
cd Agentic-Pro-UI
```

- The git clone command will create a new folder named "Agentic-Pro-UI" in your current directory and download all repository files into it.
- The cd command navigates into the newly created folder.

**Option 2: Download Zip from GitHub**

1. Navigate to the repository in your web browser: [https://github.com/Infosys-Generative-AI/Agentic-Pro-UI.git](https://github.com/Infosys-Generative-AI/Agentic-Pro-UI.git)
2. Click the green "Code" button
3. Select "Download Zip"
4. Extract the Zip file to your preferred location on your machine



## Setup and Installation

**Open in Code Editor**

1. Open Visual Studio Code or your preferred code editor
2. Select File > Open Folder
3. Navigate to and select the project directory

## Setting Up the Backend Environment

Follow these steps in Terminal (opened in the project directory):

**1. Create a Virtual Environment for the Backend:**

```bash
cd Infyagentframework
python -m venv .venv
```

This creates a virtual environment named `.venv` in the Infyagentframework directory.

**2. Activate the Virtual Environment:**

```bash
.\.venv\Scripts\activate
```

When activated successfully, you'll see `(.venv)` at the beginning of your command prompt.

**3. Install Backend Dependencies:**

With the virtual environment activated:

```bash
pip install uv
uv pip install -r requirements.txt
```

This will install all the necessary Python packages listed in the `requirements.txt` file.

If you face any SSL error issue, use the below command:

```bash
pip install -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org
```


## Setting Up the Frontend Environment

In a new Terminal window, navigate to the project's frontend directory:

```bash
cd Agentic-Pro-UI
```

**Install Frontend Dependencies**

After cloning or pulling the UI code from GitHub, delete the `package-lock.json` file (if present) before installing dependencies. This helps avoid potential conflicts.

- Open a terminal in the `Agentic-Pro-UI` directory.
- Delete the `package-lock.json` file if it exists:
    ```bash
    del package-lock.json
    ```
- Run the following command to install all required packages:
    ```bash
    npm install
    ```
- You can also use the shorthand:
    ```bash
    npm i
    ```
- To see detailed progress during installation, use:
    ```bash
    npm install --verbose
    ```
- Wait for the installation to complete. This may take a few minutes.

!!! note
    If you see only a blinking cursor or a loader for more than 3 minutes and no progress, check your Zscaler or JFrog access settings. This usually indicates a network or authentication issue.


## Configuration Setup

**Frontend Configuration (.env file)**

Open the `.env` file in your frontend project (`Agentic-Pro-UI/.env`) and set the base URL for the API server:

```env
# Base URL for the API server
REACT_APP_BASE_URL="http://10.77.18.62:8000"
```

- Replace `10.77.18.62` with your VM's IP address.
- `8000` is the port where the FastAPI backend runs.

**Backend Configuration (.env file)**

Open the `.env` file in your backend project (`Infyagentframework/.env`) and set the allowed frontend origins:

```env
# Add your frontend IP address
UI_CORS_IP="http://10.77.18.62"

# Add your frontend IP with port number
UI_CORS_IP_WITH_PORT="http://10.77.18.62:3000"
```

- Replace `10.77.18.62` and `3000` with your frontend's actual IP and port.

**CORS Origins List**

In `run_server.py` (or `agentic_workflow_as_service_endpoints.py`), you will find an `origins` list:

```python
origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://10.77.18.62",
    "http://10.77.18.62:3000",
    "null",
    # Add other origins as needed, such as your deployed frontend URL
]
```

- If you want to allow connections to the backend from other hosts, add their IP and port numbers to this `origins` list.

Make sure to update the `.env` files with your API keys and other required configuration values.

## Running the Project

**1. Start the Backend Server**

Set the environment variables to enable telemetry:

```bash
set HTTP_PROXY=
set NO_PROXY=localhost,127.0.0.1
```
In the Terminal with the active virtual environment:

```bash
cd Infyagentframework  # If not already in the backend directory
python run_server.py --host 0.0.0.0 --port 5001
```

!!! info "Backend Server Details"
    - **Server**: FastAPI (run via Python)
    - **Module**: `run_server.py`
    - **Host**: 0.0.0.0 (accessible from any network interface)
    - **Port**: 5001

Once running, you can access the backend API at [http://localhost:5001](http://localhost:5001)

**2. Start the React Frontend**

In a new Terminal window:

```bash
cd Agentic-Pro-UI  # If not already in the frontend directory
npm start
```

!!! info "Frontend Server Details"
    - **Development Server**: The React development server is used for local development and testing.
        - **Default Port**: Runs on port `3000` by default.
        - **Hot Reloading**: Automatically reloads the page when you make changes to the source code.
        - **Custom Port**: To run the frontend on a different port (e.g., `3003`), open PowerShell and run:
          ```
          $env:PORT=3003; npm start
          ```
        - This command starts the React development server on port `3003` instead of the default `3000`.




The React development server will start and automatically open [http://localhost:3000](http://localhost:3000) in your default web browser.

## How to Make the Server Run 24/7 on Windows Using NSSM

**Step 1: Create a Batch File**

Create a new file named `servers.bat` (you can choose any name).

Paste the following content into the file:

```bat
@echo off
REM Activate Python virtual environment
cd /d "C:\Code\Infyagentframework-main\Infyagentframework-main\.venv\Scripts"
call activate.bat

REM Change to backend project directory
cd /d "C:\Code\Infyagentframework-main\Infyagentframework-main\backend"

REM Ensure logs directory exists
if not exist logs mkdir logs

REM Get today's date in YYYY-MM-DD format
for /f %%i in ('powershell -Command "Get-Date -Format yyyy-MM-dd"') do set datetime=%%i

REM Start FastAPI backend and log to logs\server_YYYY-MM-DD.log
start cmd /k "python run_server.py --host 0.0.0.0 --port 5001 >> logs\server_%datetime%.log 2>&1"

REM Start Node.js frontend on port 3003
cd /d "C:\Code\Agentic-Pro-UI"
start cmd /k "set PORT=3003 && npm start"

pause
```

!!! warning "Important"
    Make sure the file paths match your system's folder structure.

!!! tip
    Save the file somewhere accessible, like your desktop or project root.

**Step 2: Install and Configure NSSM** 

1. **Download NSSM** if not already installed: [https://nssm.cc/download](https://nssm.cc/download)
2. Open **Command Prompt as Administrator**. 

!!! note 
    If you have access to an Aakash VM and can connect to it using the Remote Desktop Connection application, you will be able to run NSSM commands with administrative privileges.

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
├── package-lock.json              # Lock file for dependencies
├── README.md                      # Project documentation
└── .env.example                   # Environment variables (not shown but referenced)
```

## Troubleshooting

**Connection Issues Between Frontend and Backend**

If your React UI cannot connect to the backend:

**1. Verify BASE_URL Configuration**: 

- Check that `src/constants.js` has the correct backend URL
- Ensure the IP address and port match your backend server

**2. Check Backend CORS Settings**: 

   - Confirm your frontend URL is included in the origins list
   - Restart the backend server after making CORS changes

**3. Network Connectivity**: 

   - Test if you can access the backend URL directly in your browser
   - Verify both services are running on the expected ports

**4. Browser Console Errors**:

   - Open browser developer tools and check for CORS or network errors
   - Look for specific error messages that can guide troubleshooting

**Common Issues**

- **Port Already in Use**: If you get a port error, either stop the conflicting service or use a different port
- **CORS Errors**: Ensure the frontend URL is properly added to the backend's origins list
- **Module Not Found**: Verify all dependencies are installed and virtual environments are activated