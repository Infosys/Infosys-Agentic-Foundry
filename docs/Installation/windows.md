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
- Redis 8.2.1
- Postgres 17

To verify your Node.js and npm installations, open Terminal and run:

```bash
node -v
npm -v
```

- If Node.js is installed, running the version command will display the installed version.
- If Node.js is not installed, you will see an error in the terminal such as `"node" is not recognized as an internal or external command`.

**For Local Windows Setup**

- To install Node.js: 
    - Search for NodeJs  
    - Choose version **22** or any higher stable version.
    - Install Node.js (NPM comes bundled with Node.js).
- After installation, open your command prompt or terminal.
- Run `node -v` to confirm that it shows version 22 or higher.

##  Setting Up Proxy in System Environment Variables (If Required)

If your network requires a proxy to access the internet, follow these steps to set proxy values as system environment variables:

**Steps:**

1. Open the **Start Menu** and search for **Environment Variables**.
2. Click on **"Edit the system environment variables"**.
3. In the **System Properties** window, click on the **"Environment Variables"** button.
4. Under the **System variables** section, click **New**.
5. Create the following two variables (ask your VM creator):

```bash
   Variable name: http_proxy
   Variable value: `<your_proxy>`
   
   Variable name: https_proxy
   Variable value: `<your_proxy>`
```

6. Click **OK** to save and close all windows.
7. Restart your Command Prompt or system (if needed) for the changes to take effect.


## Download the Backend Project Code

You can obtain the project files using one of the following methods:

**Option 1: Clone Using Git**

If you have Git installed, open Terminal and run:

```bash
git clone https://github.com/Infosys/Infosys-Agentic-Foundry
cd Infosys-Agentic-Foundry
```

- The git clone command will create a new folder named "Infosys-Agentic-Foundry" in your current directory and download all repository files into it.
- The cd command navigates into the newly created folder.

**Option 2: Download Zip from GitHub**

1. Navigate to the repository in your web browser: [https://github.com/Infosys/Infosys-Agentic-Foundry](https://github.com/Infosys/Infosys-Agentic-Foundry)
2. Click the green "Code" button
3. Select "Download Zip"
4. Extract the Zip file to your preferred location on your machine


## Download the Frontend Project Code

You can obtain the project files using one of the following methods:

**Option 1: Clone Using Git**

If you have Git installed, open Terminal and run:

```bash
git clone https://github.com/Infosys/Infosys-Agentic-Foundry
cd Infosys-Agentic-Foundry-Frontend
```

- The git clone command will create a new folder named "Infosys-Agentic-Foundry-Frontend" in your current directory and download all repository files into it.
- The cd command navigates into the newly created folder.

**Option 2: Download Zip from GitHub**

1. Navigate to the repository in your web browser: [https://github.com/Infosys//Infosys-Agentic-Foundry-Frontend.git](https://github.com/Infosys/Infosys-Agentic-Foundry-Frontend.git)
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
cd Infosys-Agentic-Foundry-Backend
python -m venv .venv
```

This creates a virtual environment named `.venv` in the Infosys-Agentic-Foundry-Backend directory.

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
cd Infosys-Agentic-Foundry-Frontend
```

**Install Frontend Dependencies**

After cloning or pulling the UI code from GitHub, delete the `package-lock.json` file (if present) before installing dependencies. This helps avoid potential conflicts.

- Open a terminal in the `Infosys-Agentic-Foundry-Frontend` directory.
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


## Configuration Setup

**Frontend Configuration (.env file)**

Open the `.env` file in your frontend project (`Infosys-Agentic-Foundry-Frontend/.env`) and set the base URL for the API server:

```env
# Base URL for the API server
REACT_APP_BASE_URL=`<your_backend_api_url>`
```

**Backend Configuration (.env file)**

Open the `.env` file in your backend project (`Infosys-Agentic-Foundry-Backend/.env`) and set the allowed frontend origins:

```env
# Add your frontend IP address
UI_CORS_IP=`<your_ui_url>`

# Add your frontend IP with port number
UI_CORS_IP_WITH_PORT=`<your_ui_url:port>`
```

**Model Server Setup**

For detailed instructions on deploying and configuring your model server, refer to the [Model Server Deployment](../Model_server.md#model-server-setup-localvm-deployment) guide.

**CORS Origins List**
If you want to let other UI connect to the backend, In `run_server.py` (or `main.py`), you will find an `origins` list:

```python
origins = [
    "http://localhost",
    "http://localhost:3000",
    "null",
    # Add other origins as needed, such as your deployed frontend URL
]
```

- If you want to allow connections to the backend from other hosts, add their IP and port numbers to this `origins` list.

Make sure to update the `.env` files with your API keys and other required configuration values.

## Running the Project

**1. Start the Backend Server**

In the Terminal with the active virtual environment:

```bash
cd Infosys-Agentic-Foundry-Backend  # If not already in the backend directory
python run_server.py --host 0.0.0.0 --port `<your_port_number>` `or`
python main.py --host 0.0.0.0 --port `<your_port_number>`
```

!!! info "Backend Server Details"
    - **Server**: FastAPI (run via Python)
    - **Module**: `run_server.py` or `main.py`
    - **Host**: 0.0.0.0 (accessible from any network interface)
    - **Port**: 5001

Once running, you can access the backend API at [http://localhost:5001](http://localhost:5001)

**2. Start the React Frontend**

In a new Terminal window:

```bash
cd Infosys-Agentic-Foundry-Frontend  # If not already in the frontend directory
npm start
```

!!! info "Frontend Server Details"
    - **Development Server**: The React development server is used for local development and testing.
        - **Default Port**: Runs on port `3000` by default.
        - **Hot Reloading**: Automatically reloads the page when you make changes to the source code.
        - **Custom Port**: To run the frontend on a different port, open PowerShell and run:
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
cd /d "C:\Infosys-Agentic-Foundry\Infosys-Agentic-Foundry-Backend\.venv\Scripts"
call activate.bat

REM Change to backend project directory
cd /d "C:\Infosys-Agentic-Foundry\Infosys-Agentic-Foundry-Backend"

REM Ensure logs directory exists
if not exist logs mkdir logs

REM Get today's date in YYYY-MM-DD format
for /f %%i in ('powershell -Command "Get-Date -Format yyyy-MM-dd"') do set datetime=%%i

REM Start FastAPI backend and log to logs\server_YYYY-MM-DD.log
start cmd /k "python run_server.py --host 0.0.0.0 --port <your_port_number> >> logs\server_%datetime%.log 2>&1"

REM Start Node.js frontend 
cd /d "C:\Infosys-Agentic-Foundry\Infosys-Agentic-Foundry-Frontend"
start cmd /k "npm start"

REM Or if you want specific port number run the below command:
start cmd /k "set PORT=<your_port_number> && npm start"

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
Infosys-Agentic-Foundry-Frontend/                    # React frontend application
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

- Check that `Infosys-Agentic-Foundry-Frontend\.env` has the correct backend URL
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