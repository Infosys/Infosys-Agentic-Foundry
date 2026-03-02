# Project Setup Guide

This document provides comprehensive step-by-step instructions to deploy Infosys Agentic Foundry in Amazon Elastic Kubernetes Service (EKS).

## Prerequisites

Before setting up the project, ensure you have the following requirements and access permissions:

**Ensure users have access to the following:**

- **Python 3.12+** - Required Python version
- **React** - Frontend framework

- Infosys GitHub Repo: [Infosys-Agentic-Foundry](https://github.com/Infosys/Infosys-Agentic-Foundry)
-	Ensure users have their AWS Bedrock / Amazon Comprehend / Amazon Transcribe (Speech-to-Text) Keys and Endpoints as required.
-	Ensure AWS resources are created, and you have access/connectivity to push and pull from these resources:
    -	Amazon Elastic Container Registry (ECR)
    -	Amazon Elastic Kubernetes Service (EKS)
    -	Amazon RDS for PostgreSQL
(Instance equivalent: db.t3.small – 2 vCPUs, 4 GiB memory, 32 GiB storage or as per requirement)
    -	Amazon EC2 Linux Virtual Machine
-	Install Docker, AWS CLI, and kubectl on your EC2 instance
-	Create a namespace in the EKS cluster as per your requirement (Optional)

```bash
kubectl create namespace <namespace>
```


## AWS Deployment

### ARIZE PHOENIX

**STEPS FOR DEPLOYING ARIZE PHOENIX IN EKS**

1. Create a YAML file for deploying Arize Phoenix as a container. You can use the Arize Phoenix image in the YAML file.

```bash
nano filename1.yaml
```
!!! Info
    You can get the image from [Docker - Phoenix](https://arize.com/docs/phoenix/self-hosting/deployment-options/docker#docker) or any other trusted source which your organization allows

2. Now you need to use this command for creating deployment and service:
```bash
kubectl apply -f filename1.yaml
```
3. You can check the pods deployed using the command below
```bash
kubectl get pods -n namespace
```
4. You can check the services deployed using the command below
```bash
kubectl get svc -n namespace
```
5. Note down the load balancer IP for the container. You need to update it in the `.env` of your backend and frontend folders before creating the respective docker images.

### REDIS

**STEPS FOR DEPLOYING REDIS IN EKS**

1. Create a YAML file for deploying Redis as a container. You can use the Redis image in the YAML file.

```bash
nano filename2.yaml
```
!!! Info

    You can get the image from [Image Layer Details - redis:8.2.1](https://hub.docker.com/layers/library/redis/8.2.1/images/sha256-b282a7c852f3920972c5fd13a47fcd26baa7f046b7e5633152714124f32bf28c) or any other trusted source which your organization allows

2. Now you need to use this command for creating deployment and service:
```bash
kubectl apply -f filename2.yaml
```
3. You can check the pods deployed using the command below
```bash
kubectl get pods -n namespace
```
4. You can check the services deployed using the command below
```bash
kubectl get svc -n namespace
```
5. Note down the load balancer IP for the container. You need to update it in the `.env` of your backend folder before creating the respective docker image.

### GRAFANA

**STEPS FOR DEPLOYING GRAFANA IN EKS**

1. Create a YAML file for deploying Grafana as a container. You can use the Grafana image in the YAML file.

```bash
nano filename3.yaml
```
!!! Info 
    You can get the image from [Image Layer Details - grafana/grafana:11.2.0](https://hub.docker.com/layers/grafana/grafana/11.2.0/images/sha256-37a5d8860aef847dfa09f5f8947f010f6479f98cf7820b5186f9c6314b44be60?context=explore) or any other trusted source which your organization allows
2. Now you need to use this command for creating deployment and service:
```bash
kubectl apply -f filename3.yaml
```
3. You can check the pods deployed using the command below
```bash
kubectl get pods -n namespace
```
4. You can check the services deployed using the command below
```bash
kubectl get svc -n namespace
```
5. Note down the load balancer IP for the container. You need to update it in the `.env` of your backend and frontend folders before creating the respective docker images.

### ELASTIC SEARCH

**STEPS FOR DEPLOYING ELASTIC SEARCH IN EKS**

1. Create a YAML file for deploying Elasticsearch as a container. You can use the Elasticsearch image in the YAML file.

```bash
nano filename4.yaml
```
!!! Info
    You can get the image from [elasticsearch - Official Image | Docker Hub](https://hub.docker.com/_/elasticsearch) or any other trusted source which your organization allows

2. Now you need to use this command for creating deployment and service:
```bash
kubectl apply -f filename4.yaml
```
3. You can check the pods deployed using the command below
```bash
kubectl get pods -n namespace
```
4. You can check the services deployed using the command below
```bash
kubectl get svc -n namespace
```
5. Note down the load balancer IP for the container and update it in the OpenTelemetry YAML script. 

### OPEN-TELEMETRY 

**STEPS FOR DEPLOYING OPEN-TELEMETRY IN EKS**

1. Create a YAML file for deploying OpenTelemetry as a container, and use the OpenTelemetry Collector image in the YAML file. 

```bash
nano filename5.yaml
```
!!! Info
    You can get the image from [otel/OpenTelemetry-collector-contrib - Docker Image ](https://hub.docker.com/r/otel/opentelemetry-collector-contrib) or any other trusted source your organization allows

2. Now you need to use this command for creating deployment and service:
```bash
kubectl apply -f filename5.yaml
```
3. You can check the pods deployed using the command below
```bash
kubectl get pods -n namespace
```
4. You can check the services deployed using the command below
```bash
kubectl get svc -n namespace
```

5. Note down the load balancer IP for the container. You need to update it in the `.env` of your backend folder before creating the respective docker image.

### MODEL SERVER

**STEPS TO SET UP MODEL SERVER**

For detailed instructions on deploying and configuring your model server, refer to the [Model Server Deployment](../Model_server.md#model-server-setup-localvm-deployment) guide.

!!! Note
    You need to update the URL for the model server in the `.env` of the backend folder

### BACKEND

**STEPS TO SET UP BACKEND**

Download Backend code from GitHub. For detailed instructions, see [Download the Backend Project Code](windows.md#download-the-backend-project-code).

1. Log in to AWS EC2 Linux OS (AWS VM).
2. Download Backend source code folder into AWS VM.
3. Before starting backend image creation make sure that Arize Phoenix, OpenTelemetry, Grafana, Elasticsearch, Redis, and Model server are set up as per instructions provided above. Update the respective URLs of all these services in `.env` file.
4. Update the remaining values for the variables in the `.env` file.
5. Change working directory to the Backend Folder:
```bash
cd `<BE foldername>`
```
6. Create a Dockerfile inside the Backend folder to create docker image for Backend code.
7. Create backend image:
```bash
    docker build -f `<dockerfile-name>` -t `<tag-name>`
```
8. Retag the created image to ECR name:
    ```bash
    docker tag localhost/<imagename>:<tag> <ecr login server>/<imagename>:<tag>
    ```
9. Log in to ECR:
    ```bash
    docker login <ecr login server>
    ```
10. Push the retagged image to ECR:
    ```bash
    docker push <ecr login server>/<imagename>:<tag>
    ```
11. Create backend deployment file:
    ```bash
    nano <deployment filename.yaml>
    ```
12. Log in to EKS
13. Execute the deployment file:
    ```bash
    kubectl apply -f <deployment filename.yaml>
    ```
14. Check if the pods are deployed successfully:
    ```bash
    kubectl get pods -n <namespace>
    ```
15. Check if the service is up & running successfully:
    ```bash
    kubectl get svc -n <namespace>
    ```

### FRONTEND

**STEPS TO SET UP FRONTEND**

Download Frontend code from GitHub. For detailed instructions, see [Download the Frontend Project Code](windows.md#download-the-frontend-project-code).

1. Log in to AWS VM
2. Download Frontend source code folder into AWS VM
3. Before starting frontend image creation make sure that Arize Phoenix and Grafana are set up as per instructions provided above. Update the respective URLs of all these services in `.env` file.
4. Change working directory to the Frontend Folder:
```bash
    cd <Frontend foldername>
```
5. Create a Dockerfile inside the Frontend folder to create docker image from Frontend code.
6. In `.env` file of Frontend, update the following service load balancer URLs, which   were generated after deployment of the backend server in Amazon Elastic Kubernetes Service (EKS).
    - `REACT_APP_BASE_URL` (use Backend URL),
    - `REACT_APP_MKDOCS_BASE_URL` (use mkdocs URL),
    - `REACT_APP_LIVE_TRACKING_URL` (use Arize Phoenix URL),
    - `REACT_APP_GRAFANA_DASHBOARD_URL` (use Grafana URL)

7. Create Frontend image:
```bash
    docker build -f <dockerfile-name> -t <tag-name>
```
8. Retag the created image to ECR name:
    ```bash
    docker tag localhost/<imagename>:<tag> <ecr login server>/<imagename>:<tag>
    ```
9. Log in to ECR:
    ```bash
    docker login <ecr login server>
    ```
10. Push the retagged image to ECR:
    ```bash
    docker push <ecr login server>/<imagename>:<tag>
    ```
11. Create Frontend deployment file:
    ```bash
    nano <deployment filename.yaml>
    ```
12. Log in to Amazon Elastic Kubernetes Service (EKS)
13. Execute the deployment file:
    ```bash
    kubectl apply -f <deployment filename.yaml>
    ```
14. Check if the pods are deployed successfully:
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


1. Check for typos in commands or file names
2. To troubleshoot, check pod logs in Kubernetes using the following commands: 
```bash
kubectl describe pods <pod_name> -n <namespace>
kubectl logs <pod_name> -n <namespace>
```
