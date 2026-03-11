import os
from fastapi import FastAPI, BackgroundTasks, UploadFile, File, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
from dotenv import load_dotenv
import asyncpg
import logging

from utils.postgres_vector_store_jsonb import PostgresVectorStoreJSONB
from utils.remote_model_client import get_remote_models
from workers.embed_processor import EmbeddingProcessor

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="KB Server", version="1.0.0")

DB_CONFIG = {
    'host': os.getenv('POSTGRESQL_HOST', 'localhost'),
    'port': int(os.getenv('POSTGRESQL_PORT', '5432')),
    'database': os.getenv('DATABASE', 'agentic_workflow_as_service_database'),
    'user': os.getenv('POSTGRESQL_USER', 'postgres'),
    'password': os.getenv('POSTGRESQL_PASSWORD', 'postgres'),
    'min_size': 1,
    'max_size': 2
}

db_pool: Optional[asyncpg.Pool] = None


async def get_db_pool() -> asyncpg.Pool:
    global db_pool
    if db_pool is None:
        try:
            db_pool = await asyncpg.create_pool(**DB_CONFIG)
            logger.info("Database pool created")
        except Exception as e:
            logger.error(f"Failed to create database pool: {e}")
            raise HTTPException(status_code=500, detail=f"Database connection failed: {str(e)}")
    return db_pool


@app.on_event("startup")
async def startup_event():
    logger.info("KB Server starting")
    await get_db_pool()
    logger.info("KB Server started")


@app.on_event("shutdown")
async def shutdown_event():
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("Database pool closed")


@app.get("/health")
async def health_check():
    """
    Health check endpoint to verify the service is running and database is accessible
    """
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.fetchval('SELECT 1')
        
        return {
            "status": "healthy",
            "service": "KB Server",
            "database": "connected"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "service": "KB Server",
                "database": "disconnected",
                "error": str(e)
            }
        )


@app.post("/upload-documents")
async def upload_documents(
    kb_id: str,
    created_by: str = "system",
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    try:
        processor = EmbeddingProcessor(pool)
        
        content = await file.read()
        file_content = {
            'filename': file.filename,
            'content': content,
            'content_type': file.content_type
        }
        
        background_tasks.add_task(
            processor.process_document,
            kb_id=kb_id,
            file_content=file_content,
            created_by=created_by
        )
        
        logger.info(f"Queued document processing for KB ID: {kb_id} with file: {file.filename}")
        
        return {
            "status": "processing",
            "kb_id": kb_id,
            "filename": file.filename
        }
        
    except Exception as e:
        logger.error(f"Error uploading document: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.getenv("KB_SERVER_PORT", "8003"))
    uvicorn.run(app, host="0.0.0.0", port=port)
