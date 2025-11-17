"""
Model Client for communicating with the FastAPI model server
"""
import os
import requests
import numpy as np
from typing import List, Union
import logging
import torch

logger = logging.getLogger(__name__)

class ModelServerClient:
    """Client for communicating with the model server"""
    def __init__(self, base_url: str = None):
        self.base_url = base_url or os.getenv("MODEL_SERVER_URL")
        self.session = requests.Session()
        try:
            response = self.session.get(f"{self.base_url}/health", timeout=5)
            if response.status_code == 200:
                logger.info(f"Connected to model server at {self.base_url}")
            else:
                logger.warning(f"Model server responded with status {response.status_code}")
        except Exception as e:
            logger.debug(f"Failed to connect to model server at {self.base_url}: {e}")

class RemoteSentenceTransformer:
    """Drop-in replacement for SentenceTransformer"""

    def __init__(self, model_name: str = None, client: ModelServerClient = None):
        self.model_name = model_name
        self.client = client or ModelServerClient()
    
    def encode(self, sentences: Union[str, List[str]], 
               convert_to_tensor: bool = False, 
               show_progress_bar: bool = False,
               **kwargs) -> Union[List[List[float]], torch.Tensor, np.ndarray]:
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
            if convert_to_tensor:
                return torch.tensor(embeddings)
            else:
                return np.array(embeddings)
        except Exception as e:
            logger.error(f"Error encoding sentences: {e}")
            raise e

class RemoteCrossEncoder:
    """Drop-in replacement for CrossEncoder"""
    
    def __init__(self, model_name: str = None, client: ModelServerClient = None):
        self.model_name = model_name
        self.client = client or ModelServerClient()
    
    def predict(self, sentences: List[List[str]], **kwargs) -> Union[List[float], np.ndarray]:
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
            return np.array(scores)
            
        except Exception as e:
            logger.error(f"Error predicting with cross encoder: {e}")
            raise e

def get_remote_models(base_url: str = None):
    """Factory function to get remote model instances"""
    client = ModelServerClient(base_url)
    embedding_model = RemoteSentenceTransformer(client=client)
    logger.info("Remote SBERT model initialized successfully.")
    cross_encoder = RemoteCrossEncoder(client=client)
    logger.info("Remote Cross Encoder (Reranker) model initialized successfully.")
    return embedding_model, cross_encoder