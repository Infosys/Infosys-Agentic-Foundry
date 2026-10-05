import os
import sys
import logging
from dotenv import load_dotenv

_kb_dir = os.path.dirname(os.path.abspath(__file__))
if _kb_dir not in sys.path:
    sys.path.insert(0, _kb_dir)

load_dotenv(dotenv_path=os.path.join(_kb_dir, '..', '.env'), override=False)
load_dotenv(override=True)

from azure_vault.db_password import load_db_password_from_vault

load_db_password_from_vault()

from fastapi import FastAPI, BackgroundTasks, UploadFile, File, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
import asyncpg

from utils.postgres_vector_store_jsonb import PostgresVectorStoreJSONB
from utils.remote_model_client import get_remote_models
from workers.embed_processor import EmbeddingProcessor

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
XLSX_MAX_ROWS_PER_SHEET = int(os.getenv("XLSX_MAX_ROWS_PER_SHEET", "2000"))

logging.basicConfig(
    level=logging.DEBUG if ENVIRONMENT == "development" else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

logger.info(f"Environment: {ENVIRONMENT}")


def _format_error(e: Exception) -> str:
    """Format exception based on environment."""
    if ENVIRONMENT == "development":
        return repr(e)
    return str(e)


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

logger.info(f"Database configuration: host={DB_CONFIG['host']}, port={DB_CONFIG['port']}, database={DB_CONFIG['database']}, user={DB_CONFIG['user']}, pool_min={DB_CONFIG['min_size']}, pool_max={DB_CONFIG['max_size']}")

db_pool: Optional[asyncpg.Pool] = None


async def get_db_pool() -> asyncpg.Pool:
    global db_pool
    if db_pool is None:
        logger.info(f"Initiating database connection pool to {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
        try:
            db_pool = await asyncpg.create_pool(**DB_CONFIG)
            logger.info(f"Database connection pool established successfully (min_size={DB_CONFIG['min_size']}, max_size={DB_CONFIG['max_size']})")
        except Exception as e:
            logger.error(f"Failed to create database pool to {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}: {_format_error(e)}", exc_info=ENVIRONMENT == "development")
            raise HTTPException(status_code=500, detail=f"Database connection failed: {str(e)}")
    return db_pool


@app.on_event("startup")
async def startup_event():
    logger.info("="*60)
    logger.info("KB Server startup initiated")
    logger.info(f"Environment: {ENVIRONMENT}")
    logger.info(f"Model Server URL: {os.getenv('MODEL_SERVER_URL', 'not configured')}")
    logger.info("Initializing database connection pool...")
    await get_db_pool()
    logger.info("All dependencies initialized successfully")
    logger.info("KB Server startup complete")
    logger.info("="*60)


@app.on_event("shutdown")
async def shutdown_event():
    global db_pool
    logger.info("KB Server shutdown initiated")
    if db_pool:
        logger.info("Closing database connection pool...")
        await db_pool.close()
        logger.info("Database connection pool closed successfully")
    logger.info("KB Server shutdown complete")


@app.get("/health")
async def health_check():
    """
    Health check endpoint to verify the service is running and database is accessible
    """
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.fetchval('SELECT 1')
        
        logger.debug("Health check passed: database connection verified")
        return {
            "status": "healthy",
            "service": "KB Server",
            "database": "connected"
        }
    except Exception as e:
        logger.error(f"Health check failed: {_format_error(e)}", exc_info=ENVIRONMENT == "development")
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
    ALLOWED_EXTENSIONS = {
        '.pdf', '.txt', '.md', '.docx',           # documents (.doc excluded — Word 97-2003 not supported)
        '.csv', '.pptx', '.ppt', '.xlsx', '.xls', # spreadsheets / presentations
        '.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.gif'  # images (OCR supported)
    }

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' is not allowed. Supported types: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    try:
        logger.info(f"Upload request received: kb_id={kb_id}, file={file.filename}, content_type={file.content_type}, created_by={created_by}")
        processor = EmbeddingProcessor(pool)

        content = await file.read()
        logger.debug(f"File read complete: {file.filename}, size={len(content)} bytes")
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

        response = {
            "status": "processing",
            "kb_id": kb_id,
            "filename": file.filename
        }

        if ext in ['.xlsx', '.xls']:
            response["warning"] = (
                f"XLSX files are limited to {XLSX_MAX_ROWS_PER_SHEET:,} rows per sheet. "
                "Content beyond this limit will not be indexed."
            )

        return response
        
    except Exception as e:
        logger.error(f"Error uploading document for KB ID '{kb_id}', file '{file.filename}': {_format_error(e)}", exc_info=ENVIRONMENT == "development")
        raise HTTPException(status_code=500, detail=str(e))


class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    hybrid: Optional[bool] = None


@app.post("/search")
async def search_documents(
    kb_id: str,
    body: SearchRequest,
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """Semantic (or hybrid BM25+semantic) search over an indexed KB."""
    try:
        model_server_url = os.getenv("MODEL_SERVER_URL")
        embedding_model, _ = get_remote_models(model_server_url)
        raw = embedding_model.encode([body.query], convert_to_numpy=True)
        query_embedding = raw[0].tolist() if hasattr(raw[0], "tolist") else list(raw[0])

        vector_store = PostgresVectorStoreJSONB(pool)
        results = await vector_store.semantic_search(
            query_embedding=query_embedding,
            kb_id=kb_id,
            top_k=body.top_k,
            query_text=body.query,
            hybrid=body.hybrid,
        )
        return {
            "kb_id": kb_id,
            "query": body.query,
            "hybrid": body.hybrid,
            "count": len(results),
            "results": results,
        }
    except Exception as e:
        logger.error(f"Search error for KB '{kb_id}': {e}", exc_info=ENVIRONMENT == "development")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.getenv("KB_SERVER_PORT", "8003"))
    ssl_certfile = os.getenv("SSL_CERTFILE")
    ssl_keyfile = os.getenv("SSL_KEYFILE")
    logger.info(f"Starting KB Server on 0.0.0.0:{port}")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
    )
