"""
IAF Kafka Tool Worker — Standalone FastAPI Service
===================================================
Runs independently of the main IAF application.
Initialises its own DB pools, repositories, services, and ContextVars,
then starts a Kafka consumer loop that executes tool requests.
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

from tool_worker.config import (
    WORKER_USER_EMAIL,
    WORKER_DEPARTMENT,
    WORKER_ROLE,
    WORKER_HOST,
    WORKER_PORT,
)

from src.config.constants import DatabaseName, ConnectionPoolSize
from src.config.application_config import app_config
from src.database.database_manager import DatabaseManager
from src.database.repositories import ToolRepository, McpToolRepository, ToolVersionRepository

# ContextVars (set once at startup so tool code can use secrets helpers)
from src.utils.secrets_handler import (
    current_user_email,
    current_user_department,
    current_user_role,
)

from tool_worker.kafka_tool_worker import KafkaToolWorker
from telemetry_wrapper import logger


# ── Global references for the health endpoint ───────────────────────────────
_worker_task: asyncio.Task | None = None
_db_manager: DatabaseManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: DB pools → repos → services → ContextVars → worker loop."""
    global _worker_task, _db_manager

    # 1. Set ContextVars for headless worker identity
    current_user_email.set(WORKER_USER_EMAIL)
    current_user_department.set(WORKER_DEPARTMENT)
    current_user_role.set(WORKER_ROLE)
    logger.info(
        f"ContextVars set — email={WORKER_USER_EMAIL}, "
        f"dept={WORKER_DEPARTMENT}, role={WORKER_ROLE}"
    )

    # 2. Database pools
    db_manager = DatabaseManager()
    _db_manager = db_manager

    pool_config = app_config.postgres_db.pool_config
    await db_manager.connect(
        db_names=DatabaseName.MAIN.db_name,
        min_size=pool_config.min_size,
        max_size=pool_config.max_size,
    )

    low_pool_config = ConnectionPoolSize.LOW.config 
    await db_manager.connect(
        db_names=DatabaseName.LOGIN.db_name,
        min_size=low_pool_config.min_size,
        max_size=low_pool_config.max_size,
    )

    main_pool = await db_manager.get_pool(DatabaseName.MAIN.db_name)
    login_pool = await db_manager.get_pool(DatabaseName.LOGIN.db_name)
    logger.info("Database pools established")

    # 3. Repositories — only the ones the worker actually queries
    tool_repo = ToolRepository(pool=main_pool, login_pool=login_pool)
    mcp_tool_repo = McpToolRepository(pool=main_pool, login_pool=login_pool)
    tool_version_repo = ToolVersionRepository(pool=main_pool, login_pool=login_pool)
    logger.info("Repositories initialised")

    # 4. Start Kafka worker loop as background task
    worker = KafkaToolWorker(
        tool_repo=tool_repo,
        mcp_tool_repo=mcp_tool_repo,
        tool_version_repo=tool_version_repo,
    )
    _worker_task = asyncio.create_task(worker.run())
    logger.info("Kafka tool worker started")

    yield  # ── app is running ──

    # Shutdown
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
    if _db_manager:
        await _db_manager.close()
    logger.info("Tool worker service shut down")


# ── FastAPI app ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="IAF Kafka Tool Worker",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Kubernetes liveness / readiness probe."""
    worker_alive = _worker_task is not None and not _worker_task.done()
    status = "healthy" if worker_alive else "degraded"
    return JSONResponse(
        status_code=200,
        content={"status": status, "worker_running": worker_alive},
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run FastAPI app.")
    parser.add_argument("--host", default=WORKER_HOST, help="Host to bind to")
    parser.add_argument("--port", type=int, default=WORKER_PORT, help="Port to bind to")

    args = parser.parse_args()

    uvicorn.run(
        "tool_worker.main:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )
