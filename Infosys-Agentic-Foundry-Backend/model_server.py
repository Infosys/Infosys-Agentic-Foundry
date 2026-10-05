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
from telemetry_wrapper import logger 
from dotenv import load_dotenv

load_dotenv()

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()

logger.info(f"Environment: {ENVIRONMENT}")


def _format_error(e: Exception) -> str:
    """Format exception based on environment."""
    if ENVIRONMENT == "development":
        return repr(e)
    return str(e)

# Global model variables
embedding_model = None
cross_encoder_model = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models on startup and cleanup on shutdown"""
    global embedding_model, cross_encoder_model

    logger.info("="*60)
    logger.info("Model Server startup initiated")
    logger.info(f"Environment: {ENVIRONMENT}")

    try:
        embedding_model_name = os.getenv("SBERT_MODEL_PATH")
        cross_encoder_model_name = os.getenv("CROSS_ENCODER_PATH")

        logger.info(f"Loading embedding model from: {embedding_model_name}")
        embedding_model = SentenceTransformer(embedding_model_name)
        logger.info(f"Embedding model loaded successfully (model={embedding_model_name})")

        logger.info(f"Loading cross-encoder model from: {cross_encoder_model_name}")
        cross_encoder_model = CrossEncoder(cross_encoder_model_name)
        logger.info(f"Cross-encoder model loaded successfully (model={cross_encoder_model_name})")

        logger.info("All model dependencies initialized successfully")
        logger.info("Model Server startup complete")
        logger.info("="*60)
    except Exception as e:
        logger.error(f"Failed to load models: {_format_error(e)}", exc_info=ENVIRONMENT == "development")
        raise e

    yield
    logger.info("Model Server shutdown initiated")
    logger.info("Model Server shutdown complete")

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

@app.get("/health")
async def health_check():
    logger.debug("Health check requested")
    return {
        "status": "healthy",
        "embedding_model_loaded": embedding_model is not None,
        "cross_encoder_loaded": cross_encoder_model is not None
    }

@app.post("/embeddings", response_model=EmbeddingResponse)
async def get_embeddings(request: EmbeddingRequest):
    if embedding_model is None:
        logger.error("Embedding request rejected: model not loaded")
        raise HTTPException(status_code=500, detail="Embedding model not loaded")
    try:
        texts = request.texts if isinstance(request.texts, list) else [request.texts]
        logger.info(f"Embedding request received: input_count={len(texts)}, convert_to_tensor={request.convert_to_tensor}")
        embeddings = embedding_model.encode(texts, show_progress_bar=False)
        if len(embeddings.shape) == 1:
            embeddings = [embeddings.tolist()]
        else:
            embeddings = embeddings.tolist()
        logger.info(f"Embedding request completed: output_count={len(embeddings)}")
        return EmbeddingResponse(embeddings=embeddings)
    except Exception as e:
        logger.error(f"Error generating embeddings: {_format_error(e)}", exc_info=ENVIRONMENT == "development")
        raise HTTPException(status_code=500, detail=f"Error generating embeddings: {str(e)}")

@app.post("/rerank", response_model=RerankResponse)
async def rerank_texts(request: RerankRequest):
    if cross_encoder_model is None:
        logger.error("Rerank request rejected: cross-encoder model not loaded")
        raise HTTPException(status_code=500, detail="Cross encoder model not loaded")
    try:
        pairs = [[request.query, candidate] for candidate in request.candidates]
        logger.info(f"Rerank request received: query_length={len(request.query)}, candidates_count={len(request.candidates)}")
        scores = cross_encoder_model.predict(pairs)
        if hasattr(scores, 'tolist'):
            scores = scores.tolist()
        logger.info(f"Rerank request completed: scores_count={len(scores)}")
        return RerankResponse(scores=scores)
    except Exception as e:
        logger.error(f"Error in reranking: {_format_error(e)}", exc_info=ENVIRONMENT == "development")
        raise HTTPException(status_code=500, detail=f"Error in reranking: {str(e)}")

if __name__ == "__main__":
    host = os.getenv("MODEL_SERVER_HOST")
    port = int(os.getenv("MODEL_SERVER_PORT"))
    ssl_certfile = os.getenv("SSL_CERTFILE")
    ssl_keyfile = os.getenv("SSL_KEYFILE")

    logger.info(f"Starting Model Server on {host}:{port} (environment={ENVIRONMENT})")
    logger.info(f"SBERT_MODEL_PATH={os.getenv('SBERT_MODEL_PATH')}")
    logger.info(f"CROSS_ENCODER_PATH={os.getenv('CROSS_ENCODER_PATH')}")

    uvicorn.run(
        "model_server:app",
        host=host,
        port=port,
        reload=False,
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
    )
