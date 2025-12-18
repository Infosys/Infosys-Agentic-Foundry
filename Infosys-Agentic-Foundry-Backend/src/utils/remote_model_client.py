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