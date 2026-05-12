# Deployment of IAF with Autoscaling in AKS

## Prerequisites

Ensure user have access to below:

- Infosys Github Repos
    - [https://github.com/Infosys-Generative-AI/Agentic-Pro-UI](https://github.com/Infosys-Generative-AI/Agentic-Pro-UI) (Frontend)
    - [https://github.com/Infosys-Generative-AI/Infyagentframework](https://github.com/Infosys-Generative-AI/Infyagentframework) (Backend)
- Ensure Azure resources are created, and you have access to push and pull from these resources
    - Azure Container Registry (ACR)
    - Azure Kubernetes Service (AKS)
    - Azure Postgres Service
- Install Docker, helm and kubectl in your Azure VM

---

## Steps for Login to AKS and ACR from Azure VM

**ACR**

Login to ACR using the below command (You can find the login steps directly in your ACR resource from the azure portal)

```bash
az login
az acr login --name <acr name>
```

**AKS**

Login to the AKS using the below commands (you can get these commands directly from the AKS resource in your azure portal)

```bash
az login --tenant <your tenant id>
az account set --subscription "<subscription name>"
sudo az aks get-credentials --resource-group <resource group name> --name <aks name> --overwrite-existing
```

!!! note
    Merged `"<aks name>"` as current context in `/root/.kube/config` — You will get a message like this, that means you were logged into AKS successfully.

Before deploying IAF in VMs we need to have KAFKA setup, KEDA setup in AKS and LiteLLM setup in our VM.

---

## Steps for Setting up Kafka in AKS

1. Use the command below to pull the docker image for Kafka to your VM:

    ```bash
    docker pull bitnamilegacy/kafka:4.0.0-debian-12-r10
    ```

2. **Create the Kafka configuration file (`kafka-values.yaml`)** — Create a custom Helm values file to configure Kafka for AKS, including KRaft (ZooKeeperless) mode, replica counts, listener settings, persistent storage, service exposure, and the Kafka image source mirrored to ACR. This file customizes the Bitnami Kafka Helm chart for AKS and applies simple tuning required for a single-broker deployment.

3. Use the command below to run the Kafka:

    ```bash
    helm install kafka bitnami/kafka -n kafka -f kafka-values.yaml
    ```

4. Use the command below to check the Kafka container status:

    ```bash
    kubectl get pods -n <namespace>
    ```

5. After creating the Kafka pod, you need to create a `__consumer_offset` topic for the Kafka cluster, it will not be created automatically.

6. Now you can access the Kafka using the following URL:

    ```
    <External-IP>:9092
    ```
    or
    ```
    <service>.<namespace>.svc.cluster.local:9092
    ```

---

## Steps for KEDA Setup in AKS

1. Install Keda by deploying the manifests below directly:

    ```bash
    kubectl apply -f https://github.com/kedacore/keda/releases/download/v2.12.0/keda-2.14.0.yaml
    ```

2. Check Keda pods using below command:

    ```bash
    kubectl get pods -n keda
    ```

    User will see something like:

    ```
    keda-operator-xxxxxx
    keda-metrics-apiserver-xxxxxx
    ```

3. Create ScaledObject for agent-worker and tool-worker deployment pods.

    The ScaledObject configuration should include a reference to the target agent worker Deployment, the minimum and maximum replica limits, and polling/cooldown settings. It must define a Kafka-based trigger specifying the bootstrap server, topic, and consumer group. Lag and activation thresholds are configured to control when scaling starts and how aggressively it scales. Optional HPA behavior settings can be used to fine-tune scale-up and scale-down behavior.

---

## Steps for Setting up LiteLLM Server in VM

You can find the setup process for litellm in the below URL, follow the same and complete the setup for the litellm server in your VM.

[:octicons-arrow-right-24: LiteLLM Proxy Setup](../linux.md#litellm-proxy-setup)

---

## Steps for Setting up Model Server

You can find the setup process for model server in the below URL, follow the same and complete the setup for model server in your VM.

[:octicons-arrow-right-24: Model Server Setup](../../Model_server.md#model-server-setup-localvm-deployment)

---

## Steps for Setting up Knowledge Base Server

You can find the setup process for knowledge base server in the below URL, follow the same and complete the setup for knowledge base server in your VM.

[:octicons-arrow-right-24: Knowledge Base Setup](../linux.md#knowledgebase-server-setup)

---

Before deploying frontend and backend in AKS we need to deploy the following services:

1. Arize Phoenix
2. Elastic Search
3. Opentelemetry
4. Redis
5. Grafana

Let us start with the deployment of these services first.

!!! warning
    Make sure that you always use the latest version of the images for these services.

---

## Steps for Deploying Arize Phoenix in AKS

**Login to Azure VM:**

1. Create a yaml file for deploying arize phoenix as a container, you can use the arize phoenix image directly in the yaml file.
2. Now you need to use this command for creating deployment and service:

    ```bash
    kubectl apply -f filename.yaml
    ```

3. You can check the pods deployed using the command below:

    ```bash
    kubectl get pods -n namespace
    ```

4. You can check the services deployed using the command below:

    ```bash
    kubectl get svc -n namespace
    ```

5. Note down the load balancer IP for the container.

---

## Steps for Deploying Redis in AKS

**Login to Azure VM:**

1. Create a yaml file for deploying Redis as a container, you can use the redis image directly in the yaml file.
2. Now you need to use this command for creating deployment and service:

    ```bash
    kubectl apply -f filename.yaml
    ```

3. You can check the pods deployed using the command below:

    ```bash
    kubectl get pods -n namespace
    ```

4. You can check the services deployed using the command below:

    ```bash
    kubectl get svc -n namespace
    ```

5. Note down the load balancer IP for the container.

---

## Steps for Deploying Grafana in AKS

**Login to Azure VM:**

1. Create a yaml file for deploying Grafana as a container, you can use the grafana image directly in the yaml file.
2. Now you need to use this command for creating deployment and service:

    ```bash
    kubectl apply -f filename.yaml
    ```

3. You can check the pods deployed using the command below:

    ```bash
    kubectl get pods -n namespace
    ```

4. You can check the services deployed using the command below:

    ```bash
    kubectl get svc -n namespace
    ```

5. Note down the load balancer IP for the container.

---

## Steps for Deploying Elastic Search in AKS

**Login to Azure VM:**

1. Create a yaml file for deploying elastic search as a container, you can use the elastic search image directly in the yaml file.
2. Now you need to use this command for creating deployment and service:

    ```bash
    kubectl apply -f filename.yaml
    ```

3. You can check the pods deployed using the command below:

    ```bash
    kubectl get pods -n namespace
    ```

4. You can check the services deployed using the command below:

    ```bash
    kubectl get svc -n namespace
    ```

5. Note down the load balancer IP for the container.

---

## Steps for Deploying OpenTelemetry in AKS

**Login to Azure VM:**

1. Create a yaml file for deploying opentelemetry as a container, you can use the opentelemetry image directly in the yaml file.
2. Now you need to use this command for creating deployment and service:

    ```bash
    kubectl apply -f filename.yaml
    ```

3. You can check the pods deployed using the command below:

    ```bash
    kubectl get pods -n namespace
    ```

4. You can check the services deployed using the command below:

    ```bash
    kubectl get svc -n namespace
    ```

5. Note down the load balancer IP for the container.

Once you get these IPs, you need to mention them in the `.env` of backend and frontend accordingly.

Now we can proceed to create backend, agent worker, tool worker and frontend images and deploy them in VMs.

---

## Backend

**Login to VM:**

1. Before the image creation, ensure that you configure the values for the variables in the `.env` of backend correctly.
2. After confirming you have configured all the values correctly proceed to create image for backend by following the below steps.
3. Download backend code from GitHub Main branch.
4. Copy Dockerfile into the same folder.
5. Update the details in your `.env` file.
6. Update `main.py` file as below (If we already have `*` in origins, then no need to update):

    Update origins — For testing update CORS (optional):

    ```python
    # Configure CORS
    origins = [
        "",  # Add your frontend IP address
        "",  # Add you frontend Ip with port number being
        "http://127.0.0.1", # Allow 127.0.0.1
        "http://127.0.0.1:3000", #If your frontend runs on port 3000
        "http://localhost",
        "http://localhost:3000"
    ]

    app.add_middleware(
        CORSMiddleware,
    #    allow_origins=origins,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],  # Allows all methods
        allow_headers=["*"],  # Allows all headers
    ```

7. Now build a docker image for your backend folder using the command below:

    ```bash
    docker build -f <docker filename with path> -t <image name>:<image tag>
    ```

8. Now you will be getting your backend image something like this:

    ```
    localhost/<image name>:<image tag>
    ```

9. Login to jfrog using the command below:

    ```bash
    docker login infyartifactory.jfrog.io
    ```

10. Tag the image with acr as shown below:

    ```bash
    docker tag localhost/<image name>:<image tag>  <acr name>.azurecr.io/<image name>:<image tag>
    ```

11. Push the image into the ACR using the command below (If you get any authentication error for ACR then again login to ACR using the steps mentioned earlier):

    ```bash
    docker push <acr name>.azurecr.io/<image name>:<image tag>
    ```

12. You can check the images in ACR using the command below:

    ```bash
    az acr repository list --name <acrname> --output table
    ```

13. Create a backend YAML file.
14. Deploy the file using the command below:

    ```bash
    kubectl apply -f filename.yaml
    ```

15. You can check the pods deployed using the command below:

    ```bash
    kubectl get pods -n namespace
    ```

16. You can check the services deployed using the command below:

    ```bash
    kubectl get svc -n namespace
    ```

17. Now you can access the backend service using Swagger UI from web browser. You can find the external ip by using the command mentioned in step 16.

    ```
    <your external ip>:<port number>/docs
    ```

---

## Agent Worker

**Login to VM:**

1. Before the image creation, ensure that you configure the values for the variables in the `.env` of backend correctly.
2. After confirming you have configured all the values correctly proceed to create image for backend by following the below steps.
3. Download backend code from GitHub Main branch.
4. Copy Dockerfile into the same folder.
5. In Dockerfile you need to use the command to run the `run_agent_worker.py` file, you should not run the `main.py` file for agent worker image creation.
6. Update the details in your `.env` file.
7. Update `main.py` file as below (If we already have `*` in origins, then no need to update):

    Update origins — For testing update CORS (optional):

    ```python
    # Configure CORS
    origins = [
        "",  # Add your frontend IP address
        "",  # Add you frontend Ip with port number being
        "http://127.0.0.1", # Allow 127.0.0.1
        "http://127.0.0.1:3000", #If your frontend runs on port 3000
        "http://localhost",
        "http://localhost:3000"
    ]

    app.add_middleware(
        CORSMiddleware,
    #    allow_origins=origins,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],  # Allows all methods
        allow_headers=["*"],  # Allows all headers
    ```

8. Now build a docker image for your backend folder using the command below:

    ```bash
    docker build -f <docker filename with path> -t <image name>:<image tag>
    ```

9. Now you will be getting your agent worker image something like this:

    ```
    localhost/<image name>:<image tag>
    ```

10. Tag the image with acr as shown below:

    ```bash
    docker localhost/<image name>:<image tag>  <acr name>.azurecr.io/<image name>:<image tag>
    ```

11. Push the image into the ACR using the command below (If you get any authentication error for ACR then again login to ACR using the steps mentioned earlier):

    ```bash
    docker push <acr name>.azurecr.io/<image name>:<image tag>
    ```

12. You can check the images in ACR using the command below:

    ```bash
    az acr repository list --name <acrname> --output table
    ```

13. Create a agent worker YAML file.
14. Deploy the file using the command below:

    ```bash
    kubectl apply -f filename.yaml
    ```

15. You can check the pods deployed using the command below:

    ```bash
    kubectl get pods -n namespace
    ```

16. You can check the services deployed using the command below:

    ```bash
    kubectl get svc -n namespace
    ```

17. Now you can access the backend service using Swagger UI from web browser. You can find the external ip by using the command mentioned in step 16.

    ```
    <your external ip>:<port number>/docs
    ```

---

## Tool Worker

**Login to Infosys VM for Image creation:**

1. Before the image creation, ensure that you configure the values for the variables in the `.env` of backend correctly.
2. After confirming you have configured all the values correctly proceed to create image for backend by following the below steps.
3. Download backend code from GitHub Main branch.
4. Copy Dockerfile into the same folder.
5. In Dockerfile you need to use the command to run the `tool_worker/main.py` file, you should not run the `main.py` file from the root directory for tool worker image creation.
6. Update the details in your `.env` file.
7. Update `main.py` file as below (If we already have `*` in origins, then no need to update):

    Update origins — For testing update CORS (optional):

    ```python
    # Configure CORS
    origins = [
        "",  # Add your frontend IP address
        "",  # Add you frontend Ip with port number being
        "http://127.0.0.1", # Allow 127.0.0.1
        "http://127.0.0.1:3000", #If your frontend runs on port 3000
        "http://localhost",
        "http://localhost:3000"
    ]

    app.add_middleware(
        CORSMiddleware,
    #    allow_origins=origins,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],  # Allows all methods
        allow_headers=["*"],  # Allows all headers
    ```

8. Now build a docker image for your backend folder using the command below:

    ```bash
    docker build -f <docker filename with path> -t <image name>:<image tag>
    ```

9. Now you will be getting your tool worker image something like this:

    ```
    localhost/<image name>:<image tag>
    ```

10. Tag the image with acr as shown below:

    ```bash
    docker tag localhost/<image name>:<image tag>  <acr name>.azurecr.io/<image name>:<image tag>
    ```

11. Push the image into the ACR using the command below (If you get any authentication error for ACR then again login to ACR using the steps mentioned earlier):

    ```bash
    docker push <acr name>.azurecr.io/<image name>:<image tag>
    ```

12. You can check the images in ACR using the command below:

    ```bash
    az acr repository list --name <acrname> --output table
    ```

13. Create tool worker YAML file.
14. Deploy the file using the command below:

    ```bash
    kubectl apply -f filename.yaml
    ```

15. You can check the pods deployed using the command below:

    ```bash
    kubectl get pods -n namespace
    ```

16. You can check the services deployed using the command below:

    ```bash
    kubectl get svc -n namespace
    ```

17. Now you can access the backend service using Swagger UI from web browser. You can find the external ip by using the command mentioned in step 16.

    ```
    <your external ip>:<port number>/docs
    ```

---

## Frontend

**Login to VM:**

1. Before the image creation, ensure that you configure the values for the variables in the `.env` of frontend correctly.
2. After confirming you have configured all the values correctly proceed to create image for frontend by following the below steps.
3. Download frontend code from Github Main branch.
4. Copy Dockerfile into the same folder.
5. Update the `.env` file in the Frontend folder with your deployment URLs for Backend, MKDocs, Arize Phoenix, Grafana etc…
6. Build the docker image for your frontend folder:

    ```bash
    docker build -f <Dockerfile> -t <imagename>:<imagetag>
    ```

7. Now you will be getting your frontend image something like this:

    ```
    localhost/<image name>:<image tag>
    ```

8. Tag the image with acr as shown below:

    ```bash
    docker tag localhost/<image name>:<image tag>  <acr name>.azurecr.io/<image name>:<image tag>
    ```

9. Push the image into the ACR using the command below (If you get any authentication error for ACR then again login to ACR using the steps mentioned earlier):

    ```bash
    docker push <acr name>.azurecr.io/<image name>:<image tag>
    ```

10. You can check the images in ACR using the command below:

    ```bash
    az acr repository list --name <acrname> --output table
    ```

11. Create a frontend YAML file.
12. Deploy the file using the command below:

    ```bash
    kubectl apply -f filename.yaml
    ```

13. You can check the pods deployed using the command below:

    ```bash
    kubectl get pods -n namespace
    ```

14. You can check the services deployed using the command below:

    ```bash
    kubectl get svc -n namespace
    ```

15. Now you can access your frontend service from a web browser by using the external ip which you will get after deployment. You can find the external ip by using the command mentioned in step 14.

---

Now we have done setup of everything in AKS, so we can start consuming it.
