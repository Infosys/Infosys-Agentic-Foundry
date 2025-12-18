# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import sys
import asyncio
import uvicorn
import argparse
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from contextlib import asynccontextmanager
from fastapi.staticfiles import StaticFiles

from src.utils.helper_functions import resolve_and_get_additional_no_proxys
os.environ["NO_PROXY"] = resolve_and_get_additional_no_proxys()

from src.config.settings import IS_PRODUCTION
from src.api.app_container import app_container
from src.api import app_router
from src.api import cleanup_old_files

from src.auth.middleware import AuditMiddleware, AuthenticationMiddleware
from src.auth.routes import router as auth_router

from src.utils.stream_sse import SSEManager
from src.utils.gzip_middleware import CustomGZipMiddleware

from telemetry_wrapper import logger as log


load_dotenv()

# Set Phoenix collector endpoint
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = os.getenv("PHOENIX_COLLECTOR_ENDPOINT")
os.environ["PHOENIX_GRPC_PORT"] = os.getenv("PHOENIX_GRPC_PORT",'50051')
os.environ["PHOENIX_SQL_DATABASE_URL"] = os.getenv("PHOENIX_SQL_DATABASE_URL")


# --- Lifespan Function (for FastAPI) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the startup and shutdown events for the FastAPI application.
    - On startup: Initializes database connections, creates tables, and sets up service instances.
    - On shutdown: Closes database connections.
    """

    log.info("FastAPI Lifespan: Startup initiated.")

    try:
        await app_container.initialize_services()
        app.state.sse_manager = SSEManager()
        
        # Create background tasks
        asyncio.create_task(cleanup_old_files())
        log.info("FastAPI Lifespan: Cleanup task created.")
        
        asyncio.create_task(app_container.core_consistency_service.schedule_continuous_reevaluations())
        log.info("FastAPI Lifespan: Consistency evaluation task created.")
        
        asyncio.create_task(app_container.core_robustness_service.schedule_continuous_robustness_reevaluations())
        log.info("FastAPI Lifespan: Robustness evaluation task created.")

        # Log environment-specific startup information
        if IS_PRODUCTION:
            log.info("PRODUCTION MODE: Security features enabled, API documentation disabled")
        else:
            log.info("DEVELOPMENT MODE: API documentation available at /docs")
        
        log.info("FastAPI Lifespan: Application startup complete. FastAPI is ready to serve requests.")

        yield

    except Exception as e:
        log.critical(f"FastAPI Lifespan: Critical error during application startup: {e}", exc_info=True)
        # In a real application, you might want to exit here or put the app in a degraded state.
        # For now, re-raising will prevent the app from starting.
        raise # Re-raise to prevent app from starting if initialization fails

    finally:
        log.info("FastAPI Lifespan: Shutdown initiated.")
        await app_container.shutdown_services()
        log.info("FastAPI Lifespan: Shutdown complete.")


# Configure FastAPI with environment-based settings
fastapi_config = {
    "lifespan": lifespan,
    "title": "Infosys Agentic Foundry API",
    "description": "API for Infosys Agentic Foundry",
    "swagger_ui_init_oauth": {
        "usePkceWithAuthorizationCodeGrant": True
    }
}

# In production, disable Swagger UI and OpenAPI for security
if IS_PRODUCTION:
    fastapi_config.update({
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None  # Completely disable OpenAPI JSON endpoint in production
    })
    log.info("Production mode: Swagger UI and OpenAPI documentation disabled for security")


app = FastAPI(**fastapi_config)


# Add JWT Bearer security scheme to OpenAPI
app.openapi_schema = None
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT"
        }
    }
    # Apply security globally (optional, you can also do per-route)
    for path in openapi_schema["paths"].values():
        for method in path.values():
            method.setdefault("security", [{"BearerAuth": []}])
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi
UPLOAD_DIR = "user_uploads"

# Ensure the upload directory exists
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR) # os.makedirs creates all intermediate directories too

# Mount static files and user uploads
app.mount("/user_uploads", StaticFiles(directory=UPLOAD_DIR), name="user_uploads")

if IS_PRODUCTION:
    # In production, return 404 for /docs to prevent access
    @app.get("/docs", include_in_schema=False)
    async def docs_disabled():
        from fastapi import HTTPException
        raise HTTPException(
            status_code=404, 
            detail="API documentation is disabled in production mode for security reasons."
        )


app.add_middleware(CustomGZipMiddleware, minimum_size=500, compresslevel=5)

# Various routers for different functionalities
app.include_router(auth_router)
app.include_router(app_router)

# Configure CORS
origins = [
    os.getenv("UI_CORS_IP", ""),
    os.getenv("UI_CORS_IP_WITH_PORT", ""),
    "http://127.0.0.1", # Allow 127.0.0.1
    "http://127.0.0.1:3000", #If your frontend runs on port 3000
    "http://localhost:3000"
]


app.add_middleware(AuditMiddleware)
app.add_middleware(AuthenticationMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)


# Health check endpoint
@app.get("/health")
async def health_check():
    """
    Health check endpoint to verify the application status.
    Returns the health status of the application and its dependencies.
    """
    try:
        # Read version from VERSION file
        version_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'VERSION')
        try:
            with open(version_file_path, 'r') as f:
                version = f.read().strip()
        except FileNotFoundError:
            version = "unknown"
        
        # Basic health check - application is running
        health_status = {
            "status": "healthy",
            "service": "Infosys Agentic Foundry API",
            "timestamp": asyncio.get_event_loop().time(),
            "version": version
        }
        
        # Check database connectivity if available
        try:
            if hasattr(app_container, 'db_manager') and app_container.db_manager:
                # Attempt a simple database query to verify connectivity
                # Use the main database pool (first in the REQUIRED_DATABASES list)
                pool = await app_container.db_manager.get_pool('agentic_workflow_as_service_database')
                if pool:
                    async with pool.acquire() as connection:
                        await connection.fetchval("SELECT 1")
                    health_status["database"] = "connected"
                else:
                    health_status["database"] = "disconnected"
            else:
                health_status["database"] = "not_configured"
        except Exception as db_error:
            log.warning(f"Health check database connectivity failed: {db_error}")
            health_status["database"] = "error"
            health_status["database_error"] = str(db_error)
        
        return health_status
        
    except Exception as e:
        log.error(f"Health check failed: {e}", exc_info=True)
        return {
            "status": "unhealthy",
            "service": "Infosys Agentic Foundry API",
            "error": str(e),
            "timestamp": asyncio.get_event_loop().time()
        }



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run FastAPI app with custom event loop policy on Windows.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")

    args = parser.parse_args()

    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    uvicorn.run(app, host=args.host, port=args.port)