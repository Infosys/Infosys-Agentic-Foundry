# Project Setup Guide

This document provides comprehensive step-by-step instructions to deploy Infosys Agentic Foundry in Azure Kubernetes Cluster(AKS).

## Prerequisites

Before setting up the project, ensure you have the following requirements and access permissions:

**Ensure users have access to below:**

- **Python 3.12+** - Required Python version
- **React** - Frontend framework

- Infosys Github Repo: [Infosys-Agentic-Foundry](https://github.com/Infosys/Infosys-Agentic-Foundry)
-	Ensure users must have their Azure OpenAI Keys and Endpoints, Speech to text Key and Endpoint.
-	Ensure Azure resources are created, and you have access/connectivity to push and pull from these resources
    -	Azure Container Registry (ACR) 
    -	Azure Kubernetes Service (AKS) 
    -	Azure Postgres Service (Compute size: Standard_B2s (2 vCores, 4 GiB memory, 1280 max iops), Storage: 32 GiB)
    -	Azure Linux Virtual Machine
-	Install Docker, Azure CLI, kubectl in your Azure VM
-	Create a namespace in the AKS cluster as per your requirement (Optional)

```bash
kubectl create namespace <namespace>
```


## Azure Deployment

### ARIZE PHOENIX

**STEPS FOR DEPLOYING ARIZE PHOENIX IN AKS**

1.	Create a yaml file for deploying arize phoenix as a container, you can use the arize phoenix image in the yaml file.

```bash
nano filename1.yaml
```
!!! Info
    You can get the image from [Docker - Phoenix](https://arize.com/docs/phoenix/self-hosting/deployment-options/docker#docker) or any other trusted source which your organization allows

2.	Now you need to use this command for creating deployment and service:
```bash
kubectl apply -f filename1.yaml
```
3.	You can check the pods deployed using the command below
```bash
kubectl get pods -n namespace
```
4.	You can check the services deployed using the command below
```bash
kubectl get svc -n namespace
```
5.	 Note down the load balancer IP for the container. You need to update it in the `.env` of your backend and frontend folders before creating the respective docker images.

### REDIS

**STEPS FOR DEPLOYING REDIS IN AKS**

1.	Create a yaml file for deploying Redis as a container, you can use the redis image in the yaml file.

```bash
nano filename2.yaml
```
!!! Info

    You can get the image from [Image Layer Details - redis:8.2.1](https://hub.docker.com/layers/library/redis/8.2.1/images/sha256-b282a7c852f3920972c5fd13a47fcd26baa7f046b7e5633152714124f32bf28c) or any other trusted sources which your organization allows

2.	Now you need to use this command for creating deployment and service:
```bash
kubectl apply -f filename2.yaml
```
3.	You can check the pods deployed using the command below
```bash
kubectl get pods -n namespace
```
4.	You can check the services deployed using the command below
```bash
kubectl get svc -n namespace
```
5.	Note down the load balancer IP for the container. You need to update it in the `.env` of your backend folder before creating the respective docker image.

### GRAFANA

**STEPS FOR DEPLOYING GRAFANA IN AKS**

1.	Create a yaml file for deploying Grafana as a container, you can use the grafana image in the yaml file. 

```bash
nano filename3.yaml
```
!!! Info 
    You can get the image from [Image Layer Details - grafana/grafana:11.2.0](https://hub.docker.com/layers/grafana/grafana/11.2.0/images/sha256-37a5d8860aef847dfa09f5f8947f010f6479f98cf7820b5186f9c6314b44be60?context=explore) or any other trusted sources which your organization allows
2.	Now you need to use this command for creating deployment and service:
```bash
kubectl apply -f filename3.yaml
```
3.	You can check the pods deployed using the command below
```bash
kubectl get pods -n namespace
```
4.	You can check the services deployed using the command below
```bash
kubectl get svc -n namespace
```
5.	Note down the load balancer IP for the container. You need to update it in the `.env` of your backend and frontend folders before creating the respective docker images.

### ELASTIC SEARCH

**STEPS FOR DEPLOYING ELASTIC SEARCH IN AKS**

1.	Create a yaml file for deploying elastic search as a container, you can use the elastic search image in the yaml file. 

```bash
nano filename4.yaml
```
!!! Info
    You can get the image from [elasticsearch - Official Image | Docker Hub](https://hub.docker.com/_/elasticsearch) or any other trusted sources which your organization allows

2.	Now you need to use this command for creating deployment and service:
```bash
kubectl apply -f filename4.yaml
```
3.	You can check the pods deployed using the command below
```bash
kubectl get pods -n namespace
```
4.	You can check the services deployed using the command below
```bash
kubectl get svc -n namespace
```
5.	Note down the load balancer IP for the container and update it in the OpenTelemetry YAML script. 

### OPEN-TELEMETRY 

**STEPS FOR DEPLOYING OPEN-TELEMETRY IN AKS**

1.	Create a yaml file for deploying OpenTelemetry as a container, you can use the OpenTelemetry directly in the yaml file. 

```bash
nano filename5.yaml
```
!!! Info
    You can get the image from [otel/OpenTelemetry-collector-contrib - Docker Image ](https://hub.docker.com/r/otel/opentelemetry-collector-contrib) or any other trusted sources your organization allows

2.	Now you need to use this command for creating deployment and service:
```bash
kubectl apply -f filename5.yaml
```
3.	You can check the pods deployed using the command below
```bash
kubectl get pods -n namespace
```
4.	You can check the services deployed using the command below
```bash
kubectl get svc -n namespace
```

5.	Note down the load balancer IP for the container. You need to update it in the `.env` of your backend folder before creating the respective docker image.

### MODEL SERVER

**STEPS TO SETUP MODEL SERVER**

For detailed instructions on deploying and configuring your model server, refer to the [Model Server Deployment](../Model_server.md#model-server-setup-localvm-deployment) guide.

!!! Note
    You need to update the URL for the model server in the `.env` of the backend folder

### BACKEND

**STEPS TO SETUP BACKEND**

Download Backend code from GitHub. For detailed instructions, see [Download the Backend Project Code](windows.md#download-the-backend-project-code).

1. Login in to Azure VM
2. Download Backend source code folder into Azure VM
3. Before starting backend image creation make sure that arize phoenix, OpenTelemetry, Grafana, Elastic Search, Redis and Model server are setup as per instructions provided above. Update the respective urls of all these services in `.env` file.
4. Update the remaining values for the variables in the `.env` file.
5. Change working directory to the Backend Folder:
```bash
cd `<BE foldername>`
```
5. Create Dockerfile inside Backend folder to create docker image for Backend code.
6. Create backend image:
```bash
    docker build -f `<dockerfile-name>` -t `<tag-name>`
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
10. Create backend deployment file:
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
    kubectl get pods -n <namespace>
    ```
14. Check if the service is up & running successfully:
    ```bash
    kubectl get svc -n <namespace>
    ```

### FRONTEND

**STEPS TO SETUP FRONTEND**

Download Frontend code from GitHub. For detailed instructions, see [Download the Frontend Project Code](windows.md#download-the-frontend-project-code).

1. Login in to Azure VM
2. Download Frontend source code folder into Azure VM
3. Before starting frontend image creation make sure that arize phoenix, Grafana are setup as per instructions provided above. Update the respective urls of all these services in `.env` file.
4. Change working directory to the Frontend Folder:
```bash
    cd <Frontend foldername>
```
5. Create Dockerfile inside Frontend folder to create docker image from Frontend code.
6. In `.env` file of Frontend, update below service loadbalancer urls which were generated after deployment of backend server in Azure Kubernetes.
    - `REACT_APP_BASE_URL` (use Backend url),
    - `REACT_APP_MKDOCS_BASE_URL` (use mkdocs url),
    - `REACT_APP_LIVE_TRACKING_URL` (use Arize phoenix url),
    - `REACT_APP_GRAFANA_DASHBOARD_URL` (use Grafana url)

7. Create Frontend image:
```bash
    docker build -f <dockerfile-name> -t <tag-name>
```
8. Retag the created image to ACR name:
    ```bash
    docker tag localhost/<imagename>:<tag> <acr login server>/<imagename>:<tag>
    ```
9. Login to az and then login to acr:
    ```bash
    docker login <acr login servername>
    ```
10. Push the retagged image to ACR:
    ```bash
    docker push <acr login servername>/<imagename>:<tag>
    ```
11. Create Frontend deployment file:
    ```bash
    nano <deployment filename.yaml>
    ```
12. Login to Azure Kubernetes
13. Execute the deployment file:
    ```bash
    kubectl apply -f <deployment filename.yaml>
    ```
14. Check if the pods is deployed successfully:
    ```bash
    kubectl get pods -n <namespace>
    ```
15. Check if the service is up & running successfully:
    ```bash
    kubectl get svc -n <namespace>
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
kubectl describe pods <pod_name> -n <namespace>
kubectl logs <pod_name> -n <namespace>
```
