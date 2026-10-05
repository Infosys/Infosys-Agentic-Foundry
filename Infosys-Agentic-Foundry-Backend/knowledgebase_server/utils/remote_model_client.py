"""
Model Client for communicating with the FastAPI model server
"""
import os
import requests
from typing import List, Union, Any
import logging

from dotenv import load_dotenv
load_dotenv(override=True)

logger = logging.getLogger(__name__)

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()


def _format_error(e: Exception) -> str:
    """Format exception based on environment."""
    if ENVIRONMENT == "development":
        return repr(e)
    return str(e)


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
        
        # Configure proxies from environment variables
        proxies = {}
        http_proxy = os.getenv("HTTP_PROXY", "").strip()
        https_proxy = os.getenv("HTTPS_PROXY", "").strip()
        no_proxy = os.getenv("NO_PROXY", "").strip()
        
        if http_proxy:
            proxies["http"] = http_proxy
        if https_proxy:
            proxies["https"] = https_proxy
        
        if proxies:
            self.session.proxies.update(proxies)
            logger.info(f"Configured proxies: http={http_proxy or 'None'}, https={https_proxy or 'None'}")
        
        if no_proxy:
            # Set NO_PROXY environment variable for the session
            os.environ["NO_PROXY"] = no_proxy
            logger.info(f"Configured NO_PROXY: {no_proxy}")
        
        self.server_available = False
        
        if not self.base_url:
            if not ModelServerClient._warning_logged:
                logger.info("ModelServerClient: MODEL_SERVER_URL not configured. Remote model features will be unavailable.")
                ModelServerClient._warning_logged = True
            return
        
        logger.info(f"Initiating connection to model server at {self.base_url}")
        try:
            response = self.session.get(f"{self.base_url}/health", timeout=5, verify=False)
            if response.status_code == 200:
                if self.base_url in ModelServerClient._connection_failed:
                    del ModelServerClient._connection_failed[self.base_url]
                logger.info(f"Model server connection established successfully at {self.base_url} (status=200)")
                self.server_available = True
            else:
                if self.base_url not in ModelServerClient._connection_failed:
                    logger.warning(f"Model server at {self.base_url} responded with unexpected status {response.status_code}, remote features unavailable")
                    ModelServerClient._connection_failed[self.base_url] = True
        except Exception as e:
            if self.base_url not in ModelServerClient._connection_failed:
                logger.error(f"Connection to model server failed at {self.base_url}: {_format_error(e)}", exc_info=ENVIRONMENT == "development")
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
            logger.error("Encoding request failed: Model server is not available. Check MODEL_SERVER_URL configuration.")
            raise ConnectionError("Model server is not available. Please check MODEL_SERVER_URL configuration.")
        
        input_count = len(sentences) if isinstance(sentences, list) else 1
        logger.info(f"Sending encoding request to {self.client.base_url}/embeddings (inputs={input_count})")
        try:
            payload = {
                "texts": sentences if isinstance(sentences, list) else [sentences],
                "convert_to_tensor": False
            }
            response = self.client.session.post(
                f"{self.client.base_url}/embeddings",
                json=payload,
                timeout=120,
                verify=False
            )
            if response.status_code != 200:
                logger.error(f"Model server returned error: status={response.status_code}, response={response.text[:500]}")
                raise Exception(f"Model server error: {response.status_code} - {response.text}")
            
            result = response.json()
            embeddings = result["embeddings"]
            logger.info(f"Encoding successful: received {len(embeddings)} embeddings from model server")
            
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
            logger.error(f"Connection error to model server at {self.client.base_url}: {_format_error(e)}", exc_info=ENVIRONMENT == "development")
            raise ConnectionError(f"Model server unreachable at {self.client.base_url}. Please verify the server is running and the URL is correct.") from e
        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout while connecting to model server at {self.client.base_url} (timeout=120s): {_format_error(e)}", exc_info=ENVIRONMENT == "development")
            raise TimeoutError(f"Model server at {self.client.base_url} is not responding.") from e
        except Exception as e:
            logger.error(f"Error during encoding request to {self.client.base_url}: {_format_error(e)}", exc_info=ENVIRONMENT == "development")
            raise e


def get_remote_models(base_url: str = None):
    """Factory function to get remote model instances"""
    logger.info(f"Initializing remote models (base_url={base_url or 'from env'})")
    client = ModelServerClient(base_url)
    embedding_model = RemoteSentenceTransformer(client=client)
    if client.server_available:
        logger.info(f"Remote embedding model initialized successfully (server={client.base_url})")
    else:
        logger.warning(f"Remote embedding model initialized but server is not available (base_url={base_url})")
    return embedding_model, None  # Return None for cross_encoder for compatibility
