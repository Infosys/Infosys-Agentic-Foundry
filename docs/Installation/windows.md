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
cd backend
python -m venv .venv
```

This creates a virtual environment named `.venv` in the backend directory.

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
cd frontend
```

**Install Frontend Dependencies**

- Open a terminal in the `frontend` directory.
- Run the following command to install all required packages:
```bash
npm install
```
- You can also use the shorthand
```bash
npm i
```
- This will start installing all the dependencies.
- Wait for the installation to complete. This may take a few minutes.
!!!Note
    - If you see only a blinking cursor or a loader for more than 3 minutes and no progress, check your Zscaler or JFrog access settings. This usually indicates a network or authentication issue.


## Configuration Setup

**Frontend Configuration**

Open `src/constants.js` and update it according to your VM configuration:

```bash
export const BASE_URL = "http://10.77.18.62:8000"; // Windows
```

- 10.77.18.62 is the IP address of the VM.
- 8000 is the port where the FastAPI backend is running.

**Backend Configuration (CORS)**

Make sure your backend allows requests from the frontend. You will find these lines in `agentic_workflow_as_service_endpoints.py`:

```python
origins = [
    "http://localhost",              # Allow localhost
    "http://localhost:3000",        # Frontend running on port 3000
    "http://10.77.18.62",           # Local network IP
    "http://10.77.18.62:3000",      # Local network IP with port
    "null",                         # For file:// or sandboxed environments
    # Add other origins as needed, such as your deployed frontend URL
]
```

- Instead of 10.77.18.62 you can have your own VM IP address.
- Instead of 3000 mention the port number where the frontend is running.

Make sure to update the .env file with your API keys.

## Running the Project

**1. Start the Backend Server**

Set the environment variables to enable telemetry:

```bash
set HTTP_PROXY=
set NO_PROXY=localhost,127.0.0.1
```

In the Terminal with the active virtual environment:

```bash
cd backend  # If not already in the backend directory
uvicorn agentic_workflow_as_service_endpoints:app --host 0.0.0.0 --port 8000 --workers 4
```

!!! info "Backend Server Details"
    - **Server**: Uvicorn (ASGI server)
    - **Module**: `agentic_workflow_as_service_endpoints:app`
    - **Host**: 0.0.0.0 (accessible from any network interface)
    - **Port**: 8000
    - **Workers**: 4 processes to handle requests

Once running, you can access the backend API at [http://localhost:8000](http://localhost:8000)

**2. Start the React Frontend**

In a new Terminal window:

```bash
cd frontend  # If not already in the frontend directory
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

```
Infyagentframework/
├── backend/                  # Backend FastAPI application
│   ├── .venv/                # Python virtual environment (generated)
│   ├── requirements.txt      # Python dependencies
│   └── agentic_workflow_as_service_endpoints.py  # Main API file
├── frontend/                 # React frontend application
│   ├── node_modules/         # Node.js dependencies (generated)
│   ├── public/               # Static assets
│   ├── src/                  # React source code
│   │   ├── components/       # React components
│   │   ├── pages/            # Page components
│   │   ├── services/         # API service functions
│   │   ├── constants.js      # Configuration constants (BASE_URL)
│   │   ├── App.js            # Main App component
│   │   └── index.js          # Entry point
│   ├── package.json          # Node.js dependencies and scripts
│   └── package-lock.json     # Lock file for dependencies
└── README.md                 # Project documentation
```

- `src/components/`: Contains reusable React components.
- `src/constants.js`: Stores configuration constants.
- `src/App.js`: Main application component.
- `public/`: Static assets and the HTML template.

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