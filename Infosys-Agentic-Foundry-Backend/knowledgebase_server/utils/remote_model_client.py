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
            response = self.session.get(f"{self.base_url}/health", timeout=5, verify=False)
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


class RemoteSentenceTransformer:
    """Drop-in replacement for SentenceTransformer"""

    def __init__(self, model_name: str = None, client: ModelServerClient = None):
        self.model_name = model_name
        self.client = client or ModelServerClient()
    
    def encode(self, sentences: Union[str, List[str]], 
               convert_to_tensor: bool = False, 
               convert_to_numpy: bool = False,
               show_progress_bar: bool = False,
               **kwargs) -> Union[List[List[float]], List[float], Any]:
        
        if not self.client.base_url or not self.client.server_available:
            raise ConnectionError("Model server is not available. Please check MODEL_SERVER_URL configuration.")
        
        try:
            payload = {
                "texts": sentences if isinstance(sentences, list) else [sentences],
                "convert_to_tensor": False
            }
            response = self.client.session.post(
                f"{self.client.base_url}/embeddings",
                json=payload,
                timeout=30,
                verify=False
            )
            if response.status_code != 200:
                raise Exception(f"Model server error: {response.status_code} - {response.text}")
            
            result = response.json()
            embeddings = result["embeddings"]
            
            if convert_to_numpy:
                import numpy as np
                embeddings = np.array(embeddings)
                if isinstance(sentences, str):
                    return embeddings[0]
                return embeddings
            
            if isinstance(sentences, str):
                return embeddings[0] if embeddings else []
            else:
                return embeddings
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Cannot connect to model server at {self.client.base_url}: {e}")
            raise ConnectionError(f"Model server unreachable at {self.client.base_url}. Please verify the server is running and the URL is correct.") from e
        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout connecting to model server: {e}")
            raise TimeoutError(f"Model server at {self.client.base_url} is not responding.") from e
        except Exception as e:
            logger.error(f"Error encoding sentences: {e}")
            raise e


def get_remote_models(base_url: str = None):
    """Factory function to get remote model instances"""
    client = ModelServerClient(base_url)
    embedding_model = RemoteSentenceTransformer(client=client)
    logger.info("Remote embedding model initialized successfully.")
    return embedding_model, None  # Return None for cross_encoder for compatibility
