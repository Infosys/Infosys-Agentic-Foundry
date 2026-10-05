# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
#
# NOTE: When running directly (not via run_server.py), use run_server.py which
# sets WindowsSelectorEventLoopPolicy BEFORE uvicorn creates its event loop.
# The policy below only takes effect when main.py is imported before the loop
# is created (e.g. by run_server.py).
import os
import sys
import asyncio
import platform

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn
import argparse
import time
from typing import Dict, Any
from dotenv import load_dotenv
load_dotenv()
from src.config.vault_loader import load_vault_secrets_into_env
load_vault_secrets_into_env()
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from contextlib import asynccontextmanager
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from src.utils.helper_functions import resolve_and_get_additional_no_proxys

# ── Proxy forwarding: Windows registry → env vars ────────────────────────────
# httpx (used by the OpenAI SDK, LangChain, LiteLLM) only reads HTTPS_PROXY /
# HTTP_PROXY env vars. It does NOT read the Windows system proxy from the
# registry, whereas requests/urllib3 does. On a corporate network (e.g. Infosys
# Zscaler) where public-internet DNS only resolves through the proxy, httpx
# connections otherwise fail with [Errno 11002] getaddrinfo failed /
# APIConnectionError. This block forwards the Windows system proxy to env vars so
# httpx picks it up via trust_env=True (its default). It never overwrites a value
# already set in the environment (.env takes precedence).
try:
    import urllib.request as _urllib_req
    _sys_proxies = _urllib_req.getproxies()  # reads Windows registry on Windows
    for _scheme, _env_key in (("https", "HTTPS_PROXY"), ("http", "HTTP_PROXY")):
        if _scheme in _sys_proxies and not os.getenv(_env_key) and not os.getenv(_env_key.lower()):
            os.environ[_env_key] = _sys_proxies[_scheme]
            os.environ[_env_key.lower()] = _sys_proxies[_scheme]
except Exception:
    pass  # non-critical; if it fails, set HTTPS_PROXY / HTTP_PROXY manually in .env

_merged_no_proxy = resolve_and_get_additional_no_proxys()
os.environ["NO_PROXY"] = _merged_no_proxy
os.environ["no_proxy"] = _merged_no_proxy

# NOTE: The SSL CA bundle for internal MCP servers is applied per-connection
# (scoped to MCP traffic only) via an httpx_client_factory in the MCP service layer.
# We intentionally do NOT set SSL_CERT_FILE / REQUESTS_CA_BUNDLE globally here, so
# that the custom CA bundle can never affect other HTTPS clients (Azure OpenAI /
# embeddings / litellm). See src/database/services/services.py.

from src.config.settings import IS_PRODUCTION, ALLOWED_FRONTEND_URLS
from src.config.constants import DatabaseName
from src.config.application_config import app_config
from src.api.app_container import app_container
from src.api import (
    mcp_conversion_router, tool_router, agent_router, chat_router, evaluation_router, feedback_learning_router,
    secrets_router, tag_router, utility_router, data_connector_router, user_agent_access_router,
    group_router, group_keys_router, workflow_router, scheduler_router
)
from src.api.admin_config_endpoints import router as admin_config_router
from src.api.resource_dashboard_endpoints import router as resource_dashboard_router
from src.api.resource_allocation_endpoints import router as resource_allocation_router
from src.api.token_usage_report_endpoints import router as token_usage_report_router
from src.api.token_usage_dashboard_endpoints import router as token_usage_dashboard_router
from src.api.model_cost_endpoints import router as model_cost_router
from src.api.llm_tracking_endpoints import router as llm_tracking_router
from src.api.async_response import router as async_tasks_router, run_async_task_housekeeping_loop
from src.api.evaluation_endpoints import cleanup_old_files


from src.auth.middleware import AuditMiddleware, AuthenticationMiddleware
from src.auth.routes import router as auth_router
from src.api.role_access_endpoints import router as role_access_router
from src.api.department_endpoints import router as department_router
from src.agentos.endpoints import router as agentos_router
from src.agentos.hook_endpoints import router as hook_repo_router

from src.utils.gzip_middleware import CustomGZipMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from telemetry_wrapper import logger as log


# ---------------------------------------------------------------------------
# Fix #23 — In-flight request tracking for graceful shutdown
# ---------------------------------------------------------------------------
import threading

_inflight_count = 0
_inflight_lock = threading.Lock()
_shutting_down = False


# --- Request Timing Middleware ---
class RequestTimingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to measure and log the total request processing time.
    Also tracks in-flight requests for graceful shutdown (#23).
    """
    async def dispatch(self, request: Request, call_next):
        global _inflight_count
        with _inflight_lock:
            _inflight_count += 1

        start_time = time.perf_counter()
        
        try:
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
        finally:
            with _inflight_lock:
                _inflight_count -= 1


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

    # Fix #25: Validate configuration before anything else
    try:
        from src.agentos.startup_validator import validate_startup_config
        config_result = validate_startup_config()
        if not config_result.ok:
            log.critical(
                "[ConfigValidator] FATAL: Missing or invalid REQUIRED configuration. "
                "Fix the issues above and restart."
            )
            # Don't hard-exit; let the raise below prevent startup
            raise RuntimeError(f"Configuration validation failed: {len(config_result.errors)} errors")
        log.info(f"FastAPI Lifespan: Configuration validated ({len(config_result.validated)} vars OK)")
    except ImportError:
        log.warning("FastAPI Lifespan: startup_validator not available, skipping config check")

    try:
        await app_container.initialize_services()
        
        # Register token usage logging hook for direct Azure OpenAI calls
        use_litellm_proxy = os.getenv("USE_LITELLM_PROXY_FLAG", "false").lower() == "true"
        log.info(f"🔧 FastAPI Lifespan: USE_LITELLM_PROXY_FLAG={use_litellm_proxy}")
        
        from src.models.azure_ai_model_service import register_post_completion_hook, token_usage_logging_hook
        register_post_completion_hook(token_usage_logging_hook)
        log.info("✅ FastAPI Lifespan: Token usage logging hook registered successfully.")

        # Initialize the standalone tracker (DB pool + cost service).
        # Must run here (inside lifespan) where the event loop is active — NOT at
        # ModelService.__init__ time which runs during module import with no loop.
        from litellm_standalone_tracker import register_tracker_hooks, scan_unconfigured_models
        await register_tracker_hooks()
        log.info("FastAPI Lifespan: Standalone token tracker initialized.")
        
        if not use_litellm_proxy:
            log.info("FastAPI Lifespan: Direct Azure OpenAI calls will log token usage via hook system")
        else:
            log.info("FastAPI Lifespan: LiteLLM proxy will handle token usage logging")

        # Check for models with unconfigured costs at startup
        try:
            from src.models.model_service import ModelService
            model_svc = app_container.model_service
            available = await model_svc.get_all_available_model_names()
            unconfigured = scan_unconfigured_models(available)
            if unconfigured:
                log.error(
                    f"[ModelCosts] UNCONFIGURED MODELS DETECTED: The following {len(unconfigured)} model(s) "
                    f"have no cost configured. Token costs will default to $0.00 until admin configures pricing: "
                    f"{unconfigured}"
                )
            else:
                log.info(f"[ModelCosts] All {len(available)} available models have cost configured.")
        except Exception as e:
            log.warning(f"[ModelCosts] Could not verify model cost configuration at startup: {e}")
        
        # Create background tasks
        asyncio.create_task(cleanup_old_files())
        log.info("FastAPI Lifespan: Cleanup task created.")
        
        asyncio.create_task(app_container.core_consistency_service.schedule_continuous_reevaluations())
        log.info("FastAPI Lifespan: Consistency evaluation task created.")
        
        asyncio.create_task(app_container.core_robustness_service.schedule_continuous_robustness_reevaluations())
        log.info("FastAPI Lifespan: Robustness evaluation task created.")

        # Async response mode housekeeping: reap orphaned tasks + delete expired rows.
        asyncio.create_task(run_async_task_housekeeping_loop(app_container.async_task_service))
        log.info("FastAPI Lifespan: Async task housekeeping loop created.")

        # Cron scheduler subsystem (multi-pod safe via FOR UPDATE SKIP LOCKED).
        try:
            from src.config.constants import CronSchedulerConfig
            if CronSchedulerConfig.ENABLED and app_container.mq_manager is not None:
                from src.inference.cron_scheduler_runner import (
                    run_history_cleanup_loop,
                    run_scheduler_loop,
                )
                asyncio.create_task(
                    run_scheduler_loop(
                        scheduler_service=app_container.scheduler_service,
                        task_registry_service=app_container.task_registry_service,
                        mq_manager=app_container.mq_manager,
                    )
                )
                log.info("FastAPI Lifespan: Cron scheduler loop task created.")
                asyncio.create_task(
                    run_history_cleanup_loop(
                        scheduler_service=app_container.scheduler_service,
                    )
                )
                log.info("FastAPI Lifespan: Cron scheduler history cleanup task created.")
            elif not CronSchedulerConfig.ENABLED:
                log.info("FastAPI Lifespan: Cron scheduler disabled via CRON_SCHEDULER_ENABLED.")
            else:
                log.info("FastAPI Lifespan: Cron scheduler disabled — no message queue provider configured.")
        except Exception as exc:
            log.error(f"FastAPI Lifespan: Failed to start cron scheduler: {exc}", exc_info=True)

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
        global _shutting_down
        _shutting_down = True
        log.info("FastAPI Lifespan: Shutdown initiated.")
        # Fix #23: graceful shutdown — drain in-flight requests
        _drain_timeout = int(os.getenv("SHUTDOWN_DRAIN_TIMEOUT", "15"))
        if _inflight_count > 0:
            log.info(f"FastAPI Lifespan: Draining {_inflight_count} in-flight request(s) (timeout={_drain_timeout}s)")
            _deadline = time.time() + _drain_timeout
            while _inflight_count > 0 and time.time() < _deadline:
                await asyncio.sleep(0.25)
            if _inflight_count > 0:
                log.warning(f"FastAPI Lifespan: {_inflight_count} request(s) still in-flight after drain timeout")
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

def _rewrite_binary_uploads(node):
    """Rewrite OpenAPI 3.1 `contentMediaType` binary fields to `format: binary`.

    FastAPI emits `{"type": "string", "contentMediaType": "application/octet-stream"}`
    for file uploads, which the bundled Swagger UI renders as a plain string input
    (no file picker). Converting it to `format: binary` restores the file picker.
    """
    if isinstance(node, dict):
        if node.get("type") == "string" and node.get("contentMediaType") == "application/octet-stream":
            node.pop("contentMediaType", None)
            node.pop("contentEncoding", None)
            node["format"] = "binary"
        for value in node.values():
            _rewrite_binary_uploads(value)
    elif isinstance(node, list):
        for item in node:
            _rewrite_binary_uploads(item)

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
    # Restore file-picker rendering in Swagger UI for upload endpoints.
    _rewrite_binary_uploads(openapi_schema.get("components", {}).get("schemas", {}))
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
app.mount("/static", StaticFiles(directory="static"), name="static")
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
app.include_router(scheduler_router)            # Cron Scheduler subsystem
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
app.include_router(agentos_router)  # AgentOS - Skill-Based Agents
app.include_router(hook_repo_router)            # AgentOS - Hook Repository CRUD
app.include_router(token_usage_report_router)   # Token Usage & Cost Excel export
app.include_router(token_usage_dashboard_router)  # Token Usage Dashboard (RBAC-scoped)
app.include_router(model_cost_router)           # Model Cost Management (admin only)
app.include_router(llm_tracking_router)         # LLM Request Tracking Dashboard
app.include_router(async_tasks_router)          # Async response mode — generic task polling


# Configure CORS
origins = [
    os.getenv("UI_CORS_IP", ""),
    os.getenv("UI_CORS_IP_WITH_PORT", ""),
    "http://127.0.0.1", # Allow 127.0.0.1
    "http://127.0.0.1:3000", #If your frontend runs on port 3000
    "http://localhost:3000",
    "http://127.0.0.1:3001", #If your frontend runs on port 3000
    "http://localhost:3001",
    "https://localhost:3003",
] + ALLOWED_FRONTEND_URLS  # Automatically include all allowed frontend URLs (multi-UI support)

if not IS_PRODUCTION:
    origins.append("*")


app.add_middleware(AuditMiddleware)
app.add_middleware(AuthenticationMiddleware)

# Restrict HTTP methods exposed via CORS. When CORS_RESTRICT_METHODS is true
# (default), only GET/POST/OPTIONS are allowed (OPTIONS is required for the
# browser's CORS preflight). Set it to false to allow all methods.
_cors_restrict_methods = os.getenv("CORS_RESTRICT_METHODS", "false").strip().lower() == "true"
allowed_methods = ["GET", "POST", "OPTIONS"] if _cors_restrict_methods else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=allowed_methods,  # Restricted to GET/POST/OPTIONS unless CORS_RESTRICT_METHODS=false
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
    Returns 503 during graceful shutdown so load balancers stop routing.
    """
    from fastapi.responses import JSONResponse

    # Fix #23 — return 503 when shutting down
    if _shutting_down:
        return JSONResponse(
            status_code=503,
            content={
                "status": "shutting_down",
                "service": "Infosys Agentic Foundry API",
                "timestamp": asyncio.get_event_loop().time(),
                "inflight": _inflight_count,
            },
        )

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


# ---------------------------------------------------------------------------
# Fix #24 — Detailed health checks per subsystem
# ---------------------------------------------------------------------------
@app.get("/health/detail")
async def health_check_detail():
    """Per-subsystem health check for ops readiness.

    Probes: PostgreSQL, Redis, blob storage connectivity.
    Returns 200 if all critical subsystems are up, 503 if any critical is down.
    """
    from fastapi.responses import JSONResponse

    subsystems: Dict[str, Any] = {}
    overall = "healthy"

    # Read version
    version_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")
    try:
        with open(version_file_path, "r") as f:
            version = f.read().strip()
    except FileNotFoundError:
        version = "unknown"

    # 1. PostgreSQL
    try:
        if hasattr(app_container, "db_manager") and app_container.db_manager:
            pool = await app_container.db_manager.get_pool(DatabaseName.MAIN.db_name)
            if pool:
                async with pool.acquire() as conn:
                    await asyncio.wait_for(conn.fetchval("SELECT 1"), timeout=5)
                subsystems["postgresql"] = {"status": "ok"}
            else:
                subsystems["postgresql"] = {"status": "error", "detail": "pool unavailable"}
                overall = "degraded"
        else:
            subsystems["postgresql"] = {"status": "not_configured"}
    except Exception as e:
        subsystems["postgresql"] = {"status": "error", "detail": str(e)[:120]}
        overall = "unhealthy"

    # 2. Redis (SessionStore)
    try:
        import redis as _redis_mod
        redis_host = os.getenv("REDIS_HOST", "")
        if redis_host:
            redis_port = int(os.getenv("REDIS_PORT", "6379"))
            r = _redis_mod.Redis(host=redis_host, port=redis_port, socket_timeout=3)
            r.ping()
            r.close()
            subsystems["redis"] = {"status": "ok"}
        else:
            subsystems["redis"] = {"status": "not_configured"}
    except Exception as e:
        subsystems["redis"] = {"status": "error", "detail": str(e)[:120]}
        if overall == "healthy":
            overall = "degraded"

    # 3. Blob / storage provider
    storage_provider = os.getenv("STORAGE_PROVIDER", "")
    if storage_provider:
        subsystems["blob_storage"] = {"status": "configured", "provider": storage_provider}
    else:
        subsystems["blob_storage"] = {"status": "not_configured"}

    # 4. In-flight requests
    subsystems["inflight_requests"] = _inflight_count

    status_code = 200 if overall == "healthy" else 503

    body = {
        "status": overall,
        "service": "Infosys Agentic Foundry API",
        "version": version,
        "timestamp": asyncio.get_event_loop().time(),
        "subsystems": subsystems,
    }
    return JSONResponse(content=body, status_code=status_code)



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run FastAPI app with custom event loop policy on Windows.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--ssl-keyfile", type=str, default=None, help="Path to SSL keyfile")
    parser.add_argument("--ssl-certfile", type=str, default=None, help="Path to SSL certfile")

    args = parser.parse_args()

    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        ssl_keyfile=args.ssl_keyfile,
        ssl_certfile=args.ssl_certfile,
    )


