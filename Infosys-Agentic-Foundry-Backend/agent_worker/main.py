"""
IAF Kafka Agent Worker — Standalone FastAPI Service
====================================================
Runs independently of the main IAF application.
Initialises its own DB pools, repositories, services, and ContextVars,
then starts a Kafka consumer loop that executes agent/workflow requests.
"""
import os
import sys
import asyncio
import argparse
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# Ensure the project root is on sys.path so `src.*` imports resolve
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agent_worker.config import (
    WORKER_USER_EMAIL,
    WORKER_DEPARTMENT,
    WORKER_ROLE,
    WORKER_HOST,
    WORKER_PORT,
)

# ContextVars (set once at startup so agent code can use secrets helpers)
from src.utils.secrets_handler import (
    current_user_email,
    current_user_department,
    current_user_role,
)

from src.api.app_container import app_container
from src.api.dependencies import ServiceProvider
from agent_worker.kafka_agent_worker import AgentWorker
from telemetry_wrapper import logger


# ── Global references for the health endpoint ───────────────────────────────
_worker_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: DB pools → repos → services → ContextVars → worker loop."""
    global _worker_task

    # 1. Set ContextVars for headless worker identity
    current_user_email.set(WORKER_USER_EMAIL)
    current_user_department.set(WORKER_DEPARTMENT)
    current_user_role.set(WORKER_ROLE)
    logger.info(
        f"ContextVars set — email={WORKER_USER_EMAIL}, "
        f"dept={WORKER_DEPARTMENT}, role={WORKER_ROLE}"
    )

    # 2. Initialize all services via AppContainer
    await app_container.initialize_services()
    logger.info("AppContainer services initialized")

    # 2a. Register the token-usage logging hook (mirrors main.py startup)
    from src.models.azure_ai_model_service import register_post_completion_hook, token_usage_logging_hook
    register_post_completion_hook(token_usage_logging_hook)
    logger.info("Token usage logging hook registered")

    # 2b. Initialize the standalone tracker (DB pool + model-cost service + ADK callback)
    from litellm_standalone_tracker import register_tracker_hooks
    await register_tracker_hooks()
    logger.info("Standalone token tracker initialized")

    # 3. Create ServiceProvider instance
    service_provider = ServiceProvider()

    # 4. Start Kafka agent worker loop as background task
    worker = AgentWorker(
        service_provider=service_provider,
    )
    _worker_task = asyncio.create_task(worker.run_auto())
    logger.info("Kafka agent worker started")

    yield  # ── app is running ──

    # Shutdown
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
    if app_container.db_manager:
        await app_container.db_manager.close()
    logger.info("Agent worker service shut down")


# ── FastAPI app ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="IAF Kafka Agent Worker",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Kubernetes liveness / readiness probe."""
    worker_alive = _worker_task is not None and not _worker_task.done()
    status = "healthy" if worker_alive else "degraded"
    return JSONResponse(
        status_code=200 if worker_alive else 503,
        content={"status": status, "worker_running": worker_alive},
    )


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    parser = argparse.ArgumentParser(description="Run FastAPI app with custom event loop policy on Windows.")
    parser.add_argument("--host", default=WORKER_HOST, help="Host to bind to")
    parser.add_argument("--port", type=int, default=WORKER_PORT, help="Port to bind to")

    args = parser.parse_args()

    uvicorn.run(
        "agent_worker.main:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )
