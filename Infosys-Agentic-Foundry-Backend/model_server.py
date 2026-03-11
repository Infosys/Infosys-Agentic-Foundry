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

if __name__ == "__main__":
    host = os.getenv("MODEL_SERVER_HOST")
    port = int(os.getenv("MODEL_SERVER_PORT"))
    
    logger.info(f"Starting Model Server on {host}:{port}")
    uvicorn.run("model_server:app", host=host, port=port, reload=False)