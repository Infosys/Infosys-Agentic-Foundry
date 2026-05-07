# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import sys
import asyncio
import uvicorn
import argparse
import time
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from contextlib import asynccontextmanager
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from src.utils.helper_functions import resolve_and_get_additional_no_proxys
os.environ["NO_PROXY"] = resolve_and_get_additional_no_proxys()

from src.config.settings import IS_PRODUCTION
from src.config.constants import DatabaseName
from src.config.application_config import app_config
from src.api.app_container import app_container
from src.api import (
    mcp_conversion_router, tool_router, agent_router, chat_router, evaluation_router, feedback_learning_router,
    secrets_router, tag_router, utility_router, data_connector_router, user_agent_access_router,
    group_router, group_keys_router, workflow_router
)
from src.api.admin_config_endpoints import router as admin_config_router
from src.api.resource_dashboard_endpoints import router as resource_dashboard_router
from src.api.resource_allocation_endpoints import router as resource_allocation_router
from src.api.token_usage_report_endpoints import router as token_usage_report_router
from src.api.evaluation_endpoints import cleanup_old_files

from src.auth.middleware import AuditMiddleware, AuthenticationMiddleware
from src.auth.routes import router as auth_router
from src.api.role_access_endpoints import router as role_access_router
from src.api.department_endpoints import router as department_router

from src.utils.gzip_middleware import CustomGZipMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from telemetry_wrapper import logger as log


load_dotenv()


# --- Request Timing Middleware ---
class RequestTimingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to measure and log the total request processing time.
    Logs the time from when the request arrives to when the response is sent.
    """
    async def dispatch(self, request: Request, call_next):
        start_time = time.perf_counter()
        
        # Process the request
        response = await call_next(request)
        
        # Calculate total time
        process_time = time.perf_counter() - start_time
        
        # Format time in appropriate unit
        if process_time < 1:
            time_str = f"{process_time * 1000:.2f}ms"
        else:
            time_str = f"{process_time:.2f}s"
        
        # Add timing header to response
        response.headers["X-Process-Time"] = time_str
        
        # Log the request timing
        log.info(
            f"⏱️ [Request Timing] {request.method} {request.url.path} | "
            f"Status: {response.status_code} | Duration: {time_str}"
        )
        
        return response


# Set Phoenix collector endpoint
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "")
os.environ["PHOENIX_GRPC_PORT"] = os.getenv("PHOENIX_GRPC_PORT",'50051')
os.environ["PHOENIX_SQL_DATABASE_URL"] = app_config.postgres_db.connection_string(database=DatabaseName.ARIZE_TRACES)


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
        
        # Register token usage logging hook for direct Azure OpenAI calls
        import os
        use_litellm_proxy = os.getenv("USE_LITELLM_PROXY_FLAG", "false").lower() == "true"
        log.info(f"🔧 FastAPI Lifespan: USE_LITELLM_PROXY_FLAG={use_litellm_proxy}")
        
        from src.models.azure_ai_model_service import register_post_completion_hook, token_usage_logging_hook
        register_post_completion_hook(token_usage_logging_hook)
        log.info("✅ FastAPI Lifespan: Token usage logging hook registered successfully.")

        # Initialize the standalone tracker (DB pool + cost service).
        # Must run here (inside lifespan) where the event loop is active — NOT at
        # ModelService.__init__ time which runs during module import with no loop.
        from litellm_standalone_tracker import register_tracker_hooks
        await register_tracker_hooks()
        log.info("✅ FastAPI Lifespan: Standalone token tracker initialized.")
        
        if not use_litellm_proxy:
            log.info("📊 FastAPI Lifespan: Direct Azure OpenAI calls will log token usage via hook system")
        else:
            log.info("📊 FastAPI Lifespan: LiteLLM proxy will handle token usage logging")
        
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
        
        # Start the file server in a separate thread if enabled (with delay to ensure uvicorn message shows first)
        try:
            from src.file_server.file_server import start_file_server_thread, FILE_SERVER_ENABLED
            import time
            import threading
            
            if FILE_SERVER_ENABLED:
                def delayed_file_server_start():
                    """Start file server after a small delay so main uvicorn message appears first"""
                    time.sleep(1)  # Wait for uvicorn to print its startup message
                    start_file_server_thread()
                
                # Start the delayed launcher in a separate thread
                launcher_thread = threading.Thread(target=delayed_file_server_start, daemon=True, name="FileServerLauncher")
                launcher_thread.start()
                log.info("FastAPI Lifespan: File server scheduled to start")
        except ImportError as e:
            log.warning(f"FastAPI Lifespan: File server module not available: {e}")
        except Exception as e:
            log.error(f"FastAPI Lifespan: Error scheduling file server: {e}")
        
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


# Add Request Timing Middleware first (wraps all other middlewares)
app.add_middleware(RequestTimingMiddleware)

app.add_middleware(CustomGZipMiddleware, minimum_size=500, compresslevel=5)

# Various routers for different functionalities
app.include_router(auth_router)
app.include_router(role_access_router)
app.include_router(department_router)
app.include_router(tool_router)
app.include_router(agent_router)
app.include_router(chat_router)
app.include_router(evaluation_router)
app.include_router(feedback_learning_router)
app.include_router(secrets_router)
app.include_router(tag_router)
app.include_router(utility_router)
app.include_router(workflow_router)
app.include_router(admin_config_router)
app.include_router(data_connector_router)
app.include_router(mcp_conversion_router)
app.include_router(user_agent_access_router)
app.include_router(group_router)
app.include_router(group_keys_router)
app.include_router(resource_dashboard_router)  # Resource Dashboard for access key management
app.include_router(resource_allocation_router)  # Resource Allocation Management (admin only)
app.include_router(token_usage_report_router)   # Token Usage & Cost Excel export


# Configure CORS
origins = [
    os.getenv("UI_CORS_IP", ""),
    os.getenv("UI_CORS_IP_WITH_PORT", ""),
    "http://127.0.0.1", # Allow 127.0.0.1
    "*",
    "http://127.0.0.1:3000", #If your frontend runs on port 3000
    "http://localhost:3000",
    "http://127.0.0.1:3001", #If your frontend runs on port 3000
    "http://localhost:3001",

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

# Add ProxyHeadersMiddleware to trust X-Forwarded-Proto and X-Forwarded-For headers
# This ensures FastAPI uses HTTPS in redirect URLs when behind a reverse proxy
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=origins)



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
                # Use the main database pool
                pool = await app_container.db_manager.get_pool(DatabaseName.MAIN.db_name)
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


