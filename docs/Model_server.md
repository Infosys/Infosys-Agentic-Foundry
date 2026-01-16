To optimize the deployment and usage of bi-encoder and cross-encoder models, we have enhanced our integration to support accessing hosted models via server URLs. Previously, models had to be manually downloaded from Hugging Face and their local paths specified in the `.env` file. This process was inefficient, consuming significant disk space (several GBs per model) and complicating deployments across multiple virtual machines (VMs), as each VM required its own copy of the models.

To resolve these challenges, we introduced a model server based on FastAPI. With this architecture, models are hosted on a single machine (either local or remote), and clients connect to the model server by specifying its URL in their `.env` file. This eliminates redundant downloads and local storage, streamlining both setup and ongoing maintenance.

### How It Works

1. **Model Server Deployment**:  
    Deploy the model server script on the machine designated to host your Hugging Face models.

2. **Client Configuration**:  
    On each client, specify the model server URL in the `.env` file. The application will then access models via the server, rather than loading them locally.

3. **Centralized Model Management**:  
    All model-related operations (such as generating embeddings or reranking candidates) are handled by the server, ensuring consistency and efficiency across all environments.

The model server hosts both bi-encoder and cross-encoder models, allowing clients to request embeddings and reranking results through simple API calls. The client connects to the server, requests embeddings from the bi-encoder, and performs reranking with the cross-encoder, all via HTTP endpoints.

### Example Model Server Script

Below is an example FastAPI script for hosting the `all-MiniLM-L6-v2` (bi-encoder) and `bge-reranker-large` (cross-encoder) models. Run this script on the server where the Hugging Face models will be hosted:

```python
"""
Model Server for hosting all-MiniLM-L6-v2 and bge-reranker-large models
"""

import os
from contextlib import asynccontextmanager
from typing import List, Union
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from sentence_transformers import SentenceTransformer, CrossEncoder
import logging
from dotenv import load_dotenv
import numpy as np
import torch

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global model variables
embedding_model = None
cross_encoder_model = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models on startup and cleanup on shutdown"""
    global embedding_model, cross_encoder_model
    try:
        embedding_model_name = os.getenv("SBERT_MODEL_PATH")
        cross_encoder_model_name = os.getenv("CROSS_ENCODER_PATH")
        embedding_model = SentenceTransformer(embedding_model_name)
        logger.info("Embedding model loaded successfully")
        cross_encoder_model = CrossEncoder(cross_encoder_model_name)
        logger.info("Cross encoder model loaded successfully")
        logger.info("All models loaded successfully!")
    except Exception as e:
        logger.error(f"Failed to load models: {str(e)}")
        raise e
    yield
    logger.info("Shutting down model server...")

app = FastAPI(title="Model Server", version="1.0.0", lifespan=lifespan)

# Request/Response models
class EmbeddingRequest(BaseModel):
    texts: Union[str, List[str]]
    convert_to_tensor: bool = False

class EmbeddingResponse(BaseModel):
    embeddings: List[List[float]]

class RerankRequest(BaseModel):
    query: str
    candidates: List[str]

class RerankResponse(BaseModel):
    scores: List[float]

class CosineSimilarityRequest(BaseModel):
    vector_a: List[float]
    vector_b: Union[List[float], List[List[float]]]

class CosineSimilarityResponse(BaseModel):
    similarity: Union[float, List[float]]

class TensorOpsRequest(BaseModel):
    data: Union[List[float], List[List[float]]]
    operation: str
    kwargs: dict = {}

class TensorOpsResponse(BaseModel):
    result: Union[List[float], List[List[float]], float, bool]

class ArrayOpsRequest(BaseModel):
    data: Union[List[float], List[List[float]]]
    operation: str
    kwargs: dict = {}

class ArrayOpsResponse(BaseModel):
    result: Union[List[float], List[List[float]], float, bool]

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "embedding_model_loaded": embedding_model is not None,
        "cross_encoder_loaded": cross_encoder_model is not None
    }

@app.post("/embeddings", response_model=EmbeddingResponse)
async def get_embeddings(request: EmbeddingRequest):
    if embedding_model is None:
        raise HTTPException(status_code=500, detail="Embedding model not loaded")
    try:
        texts = request.texts if isinstance(request.texts, list) else [request.texts]
        embeddings = embedding_model.encode(texts, show_progress_bar=False)
        if len(embeddings.shape) == 1:
            embeddings = [embeddings.tolist()]
        else:
            embeddings = embeddings.tolist()
        return EmbeddingResponse(embeddings=embeddings)
    except Exception as e:
        logger.error(f"Error generating embeddings: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error generating embeddings: {str(e)}")

@app.post("/rerank", response_model=RerankResponse)
async def rerank_texts(request: RerankRequest):
    if cross_encoder_model is None:
        raise HTTPException(status_code=500, detail="Cross encoder model not loaded")
    try:
        pairs = [[request.query, candidate] for candidate in request.candidates]
        scores = cross_encoder_model.predict(pairs)
        if hasattr(scores, 'tolist'):
            scores = scores.tolist()
        return RerankResponse(scores=scores)
    except Exception as e:
        logger.error(f"Error in reranking: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error in reranking: {str(e)}")

@app.post("/cosine_similarity", response_model=CosineSimilarityResponse)
async def calculate_cosine_similarity(request: CosineSimilarityRequest):
    """Calculate cosine similarity between vectors"""
    try:
        vector_a = np.array(request.vector_a)
        if isinstance(request.vector_b[0], list):
            similarities = []
            for vec_b in request.vector_b:
                vector_b = np.array(vec_b)
                norm_a = np.linalg.norm(vector_a)
                norm_b = np.linalg.norm(vector_b)
                if norm_a == 0 or norm_b == 0:
                    similarity = 0.0
                else:
                    similarity = np.dot(vector_a, vector_b) / (norm_a * norm_b)
                similarities.append(float(similarity))
            return CosineSimilarityResponse(similarity=similarities)
        else:
            vector_b = np.array(request.vector_b)
            norm_a = np.linalg.norm(vector_a)
            norm_b = np.linalg.norm(vector_b)
            if norm_a == 0 or norm_b == 0:
                similarity = 0.0
            else:
                similarity = np.dot(vector_a, vector_b) / (norm_a * norm_b)
            return CosineSimilarityResponse(similarity=float(similarity))
            
    except Exception as e:
        logger.error(f"Error calculating cosine similarity: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error calculating cosine similarity: {str(e)}")

@app.post("/tensor_ops", response_model=TensorOpsResponse)
async def tensor_operations(request: TensorOpsRequest):
    """Handle tensor operations to replace torch operations"""
    try:
        data = request.data
        operation = request.operation
        kwargs = request.kwargs
        
        if operation == "to_tensor":
            tensor = torch.tensor(data)
            result = tensor.tolist()
        elif operation == "sigmoid":
            tensor = torch.tensor(data)
            result = torch.sigmoid(tensor).tolist()
        elif operation == "is_tensor":
            result = False
        elif operation == "flatten":
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                result = [item for sublist in data for item in sublist]
            else:
                result = data
        else:
            logger.warning(f"Unknown tensor operation: {operation}")
            result = data
            
        return TensorOpsResponse(result=result)
        
    except Exception as e:
        logger.error(f"Error in tensor operation {request.operation}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error in tensor operation: {str(e)}")

@app.post("/array_ops", response_model=ArrayOpsResponse)
async def array_operations(request: ArrayOpsRequest):
    """Handle array operations to replace numpy operations"""
    try:
        data = request.data
        operation = request.operation
        kwargs = request.kwargs
        
        if operation == "create_array":
            result = data
        elif operation == "mean":
            if isinstance(data[0], list):
                axis = kwargs.get('axis', None)
                np_array = np.array(data)
                if axis is not None:
                    result = np.mean(np_array, axis=axis).tolist()
                else:
                    result = float(np.mean(np_array))
            else:
                result = float(np.mean(data))
        elif operation == "std":
            if isinstance(data[0], list):
                np_array = np.array(data)
                axis = kwargs.get('axis', None)
                if axis is not None:
                    result = np.std(np_array, axis=axis).tolist()
                else:
                    result = float(np.std(np_array))
            else:
                result = float(np.std(data))
        elif operation == "reshape":
            shape = kwargs.get('shape', (-1,))
            np_array = np.array(data)
            result = np_array.reshape(shape).tolist()
        elif operation == "transpose":
            np_array = np.array(data)
            result = np_array.T.tolist()
        else:
            logger.warning(f"Unknown array operation: {operation}")
            result = data
            
        return ArrayOpsResponse(result=result)
        
    except Exception as e:
        logger.error(f"Error in array operation {request.operation}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error in array operation: {str(e)}")

if __name__ == "__main__":
    host = os.getenv("MODEL_SERVER_HOST")
    port = int(os.getenv("MODEL_SERVER_PORT"))

    logger.info(f"Starting Model Server on {host}:{port}")
    uvicorn.run("model_server:app", host=host, port=port, reload=False)

```
Below is the script for the Model Client, which enables communication with the FastAPI model server hosting two models: `all-MiniLM-L6-v2` (bi-encoder) and `bge-reranker-large` (cross-encoder). This client allows you to connect to the server, request embeddings from the bi-encoder, and perform reranking with the cross-encoder, all via simple API calls.

```python
"""
Model Client for communicating with the FastAPI model server
"""
import os
import requests
from typing import List, Union, Any
import logging

logger = logging.getLogger(__name__)

class ModelServerClient:
    """Client for communicating with the model server"""
    _warning_logged = False  
    _connection_failed = {}  
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or os.getenv("MODEL_SERVER_URL")
        if self.base_url:
            self.base_url = self.base_url.strip()
            if not self.base_url or self.base_url.lower() == "none":
                self.base_url = None
        
        self.session = requests.Session()
        self.server_available = False
        
        if not self.base_url:
            if not ModelServerClient._warning_logged:
                logger.info("MODEL_SERVER_URL not configured. Remote model features will be unavailable.")
                ModelServerClient._warning_logged = True
            return
        
        try:
            response = self.session.get(f"{self.base_url}/health", timeout=5)
            if response.status_code == 200:
                if self.base_url in ModelServerClient._connection_failed:
                    del ModelServerClient._connection_failed[self.base_url]
                logger.info(f"Connected to model server at {self.base_url}")
                self.server_available = True
            else:
                if self.base_url not in ModelServerClient._connection_failed:
                    logger.warning(f"Model server at {self.base_url} responded with status {response.status_code}, remote features unavailable")
                    ModelServerClient._connection_failed[self.base_url] = True
        except Exception as e:
            if self.base_url not in ModelServerClient._connection_failed:
                logger.error(f"Failed to connect to model server at {self.base_url}: {e}")
                ModelServerClient._connection_failed[self.base_url] = True

class RemoteUtils:
    """Remote utilities to replace torch, numpy operations and sentence-transformers utilities"""
    
    def __init__(self, client: ModelServerClient = None):
        self.client = client or ModelServerClient()

    def cos_sim(self, a: List[float], b: Union[List[float], List[List[float]]]) -> Union[float, List[float]]:
        """Remote cosine similarity calculation to replace sentence_transformers.util.cos_sim"""
        if not self.client.base_url or self.client.base_url == "None":
            raise Exception("MODEL_SERVER_URL not configured. Cannot perform cosine similarity without remote server.")
        try:
            def flatten_embedding(embedding):
                if isinstance(embedding, list) and len(embedding) > 0:
                    if isinstance(embedding[0], list):
                        return embedding[0]
                    else:
                        return embedding
                return embedding
            vector_a = flatten_embedding(a)
            vector_b = b
            if isinstance(b, list) and len(b) > 0:
                if isinstance(b[0], list):
                    if len(b) == 1 and isinstance(b[0][0], (int, float)):
                        vector_b = b[0]
                    elif isinstance(b[0][0], list):
                        vector_b = [flatten_embedding(vec) for vec in b]
                    else:
                        vector_b = b
            payload = {
                "vector_a": vector_a,
                "vector_b": vector_b
            }
            response = self.client.session.post(
                f"{self.client.base_url}/cosine_similarity",
                json=payload,
                timeout=30
            )
            if response.status_code != 200:
                raise Exception(f"Model server error: {response.status_code} - {response.text}")
            result = response.json()
            return result["similarity"]
        except Exception as e:
            logger.error(f"Error calculating cosine similarity: {e}")
            raise e
    
    def tensor_operations(self, data: Any, operation: str, **kwargs) -> Any:
        """Remote tensor operations to replace torch operations"""
        if not self.client.base_url or self.client.base_url == "None":
            raise Exception("MODEL_SERVER_URL not configured. Cannot perform tensor operations without remote server.")
        try:
            payload = {
                "data": data,
                "operation": operation,
                "kwargs": kwargs
            }
            response = self.client.session.post(
                f"{self.client.base_url}/tensor_ops",
                json=payload,
                timeout=30
            )
            if response.status_code != 200:
                raise Exception(f"Model server error: {response.status_code} - {response.text}")
            result = response.json()
            return result["result"]
        except Exception as e:
            logger.error(f"Error performing tensor operation {operation}: {e}")
            raise e
    
    def array_operations(self, data: Any, operation: str, **kwargs) -> Any:
        """Remote array operations to replace numpy operations"""
        if not self.client.base_url or self.client.base_url == "None":
            raise Exception("MODEL_SERVER_URL not configured. Cannot perform array operations without remote server.")
        try:
            payload = {
                "data": data,
                "operation": operation,
                "kwargs": kwargs
            }
            response = self.client.session.post(
                f"{self.client.base_url}/array_ops",
                json=payload,
                timeout=30
            )
            if response.status_code != 200:
                raise Exception(f"Model server error: {response.status_code} - {response.text}")
            result = response.json()
            return result["result"]
        except Exception as e:
            logger.error(f"Error performing array operation {operation}: {e}")
            raise e

class RemoteSentenceTransformer:
    """Drop-in replacement for SentenceTransformer"""

    def __init__(self, model_name: str = None, client: ModelServerClient = None):
        self.model_name = model_name
        self.client = client or ModelServerClient()
    
    def encode(self, sentences: Union[str, List[str]], 
               convert_to_tensor: bool = False, 
               show_progress_bar: bool = False,
               **kwargs) -> Union[List[List[float]], List[float]]:
        try:
            payload = {
                "texts": sentences,
                "convert_to_tensor": False
            }
            response = self.client.session.post(
                f"{self.client.base_url}/embeddings",
                json=payload,
                timeout=30
            )
            if response.status_code != 200:
                raise Exception(f"Model server error: {response.status_code} - {response.text}")
            result = response.json()
            embeddings = result["embeddings"]
            if isinstance(sentences, str):
                return embeddings[0] if embeddings else []
            else:
                return embeddings
        except Exception as e:
            logger.error(f"Error encoding sentences: {e}")
            raise e

class RemoteCrossEncoder:
    """Drop-in replacement for CrossEncoder"""
    
    def __init__(self, model_name: str = None, client: ModelServerClient = None):
        self.model_name = model_name
        self.client = client or ModelServerClient()
    
    def predict(self, sentences: List[List[str]], **kwargs) -> Union[List[float], float]:
        try:
            if len(sentences) == 0:
                return []
            if isinstance(sentences[0], str):
                query, candidates = sentences[0], [sentences[1]]
            else:
                query = sentences[0][0]
                candidates = [pair[1] for pair in sentences]
            payload = {
                "query": query,
                "candidates": candidates
            }
            response = self.client.session.post(
                f"{self.client.base_url}/rerank",
                json=payload,
                timeout=30
            )
            if response.status_code != 200:
                raise Exception(f"Model server error: {response.status_code} - {response.text}")
            result = response.json()
            scores = result["scores"]
            if isinstance(sentences[0], str):
                return scores[0] if scores else 0.0
            return scores
            
        except Exception as e:
            logger.error(f"Error predicting with cross encoder: {e}")
            raise e

class RemoteTensorUtils:
    """Utility class to replace torch tensor operations with remote calls"""
    
    def __init__(self, client: ModelServerClient = None):
        self.client = client or ModelServerClient()
        self.remote_utils = RemoteUtils(client)
    
    def tensor(self, data: List) -> List:
        """Replace torch.tensor() with remote operation"""
        return self.remote_utils.tensor_operations(data, "to_tensor")
    
    def sigmoid(self, data: List) -> List:
        """Replace torch.sigmoid() with remote operation"""
        return self.remote_utils.tensor_operations(data, "sigmoid")
    
    def is_tensor(self, obj: Any) -> bool:
        """Check if object is tensor-like (in remote setup, check if it's a list of numbers)"""
        return isinstance(obj, (list, tuple)) and len(obj) > 0 and isinstance(obj[0], (int, float))

class RemoteNumpyUtils:
    """Utility class to replace numpy operations with remote calls"""
    
    def __init__(self, client: ModelServerClient = None):
        self.client = client or ModelServerClient()
        self.remote_utils = RemoteUtils(client)
    
    def array(self, data: List) -> List:
        """Replace numpy.array() with remote operation"""
        return self.remote_utils.array_operations(data, "create_array")

class RemoteSentenceTransformersUtil:
    """Utility class to replace sentence_transformers.util operations"""
    
    def __init__(self, client: ModelServerClient = None):
        self.client = client or ModelServerClient()
        self.remote_utils = RemoteUtils(client)
    
    def cos_sim(self, a: List[float], b: Union[List[float], List[List[float]]]) -> Union[float, List[float]]:
        """Replace sentence_transformers.util.cos_sim with remote calculation"""
        return self.remote_utils.cos_sim(a, b)

def get_remote_models_and_utils(base_url: str = None):
    """Factory function to get all remote model instances and utilities"""
    client = ModelServerClient(base_url)
    embedding_model = RemoteSentenceTransformer(client=client)
    cross_encoder = RemoteCrossEncoder(client=client)
    torch_utils = RemoteTensorUtils(client=client)
    numpy_utils = RemoteNumpyUtils(client=client) 
    util = RemoteSentenceTransformersUtil(client=client)
    logger.info("Remote models and utilities initialized successfully.")
    return {
        "embedding_model": embedding_model,
        "cross_encoder": cross_encoder,
        "torch": torch_utils,
        "np": numpy_utils,
        "util": util,
        "client": client
    }

def get_remote_models(base_url: str = None):
    """Original function for backwards compatibility"""
    components = get_remote_models_and_utils(base_url)
    return components["embedding_model"], components["cross_encoder"]
```

### Key Benefits

- **Reduced Storage Requirements**: Models are downloaded and stored only once on the server.
- **Simplified Deployment**: No need to manage model files on every VM or environment.
- **Centralized Updates**: Updating a model on the server instantly benefits all connected clients.
- **Scalability**: Multiple clients can access the same models concurrently via the server API.

This architecture ensures efficient, scalable, and maintainable model usage across your infrastructure.
