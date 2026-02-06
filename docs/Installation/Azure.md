# Project Setup Guide

This document provides comprehensive step-by-step instructions to set up and run the project on your local machine and deploy it to Azure VM.

## Prerequisites

Before setting up the project, ensure you have the following requirements and access permissions:

### System Requirements

- **Azure Linux VM** - Virtual machine for deployment
- **Azure Kubernetes Cluster (AKS)** - Container orchestration service
- **Azure Container Registry (ACR)** - Container image registry
- **Python 3.12+** - Required Python version
- **React** - Frontend framework
- **Azure Postgres DB** - Database service

### Download Source Code

Download Backend and Frontend code from GitHub. For detailed instructions, see [Download the Backend Project Code](windows.md#download-the-backend-project-code).

## Azure Deployment

### BACKEND

1. Login in to Azure VM
2. Download Backend source code folder into Azure VM
3. Change working directory to the Backend Folder:

    cd `<BE foldername>`

4. Create Dockerfile inside Backend folder to create docker image from Backend code.
5. Create backend image:

    docker build -f `<dockerfile-name>` -t `<tag-name>`

4. Retag the created image to ACR name:
    ```bash
    docker tag localhost/<imagename>:<tag> <acr login server>/<imagename>:<tag>
    ```
5. Login to az and then login to acr:
    ```bash
    docker login <acr login servername>
    ```
6. Push the retagged image to ACR:
    ```bash
    docker push <acr login servername>/<imagename>:<tag>
    ```
7. Create backend deployment file:
    ```bash
    nano <deployment filename.yaml>
    ```
8. Login to Azure Kubernetes
9. Execute the deployment file:
    ```bash
    kubectl apply -f <deployment filename.yaml>
    ```
10. Check if the pods is deployed successfully:
    ```bash
    kubectl get pods
    ```
11. Check if the service is up & running successfully:
    ```bash
    kubectl get svc
    ```

### FRONTEND

1. Login in to Azure VM
2. Download Frontend source code folder into Azure VM
3. Change working directory to the Frontend Folder:
```bash
    cd <Frontend foldername>
```
4. Create Dockerfile inside Frontend golder to create docker image from Frontend code.
5. In `.env` file of Frontend, update below service loadbalancer urls which were generated after deployment of backend server in Azure Kubernetes.
    `REACT_APP_BASE_URL`,
    `REACT_APP_MKDOCS_BASE_URL`,
    `REACT_APP_LIVE_TRACKING_URL`

6. Create Frontend image:
```bash
    docker build -f <dockerfile-name> -t <tag-name>
```
7. Retag the created image to ACR name:
    ```bash
    docker tag localhost/<imagename>:<tag> <acr login server>/<imagename>:<tag>
    ```
8. Login to az and then login to acr:
    ```bash
    docker login <acr login servername>
    ```
9. Push the retagged image to ACR:
    ```bash
    docker push <acr login servername>/<imagename>:<tag>
    ```
10. Create Frontend deployment file:
    ```bash
    nano <deployment filename.yaml>
    ```
11. Login to Azure Kubernetes
12. Execute the deployment file:
    ```bash
    kubectl apply -f <deployment filename.yaml>
    ```
13. Check if the pods is deployed successfully:
    ```bash
    kubectl get pods
    ```
14. Check if the service is up & running successfully:
    ```bash
    kubectl get svc
    ```

## Troubleshooting
**Virtual Environment Activation Fails**

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
4. To troubleshoot check pod logs in Kubernetes, By using below commands: 
```bash
kubectl describe pods <pod_name>
kubectl logs <pod_name>
```
