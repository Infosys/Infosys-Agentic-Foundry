"""
Configuration exclusive to the IAF Kafka Tool Worker service.
Values here are specific to this worker process and do not belong in the shared .env.
"""
import os


# ── Identity ────────────────────────────────────────────────────────────────
# The worker runs headless with no real user session.
# These defaults satisfy ContextVars used inside tool code (secrets_handler).
WORKER_USER_EMAIL: str = os.getenv("TOOL_WORKER_USER_EMAIL", "tool-worker@system.internal")
WORKER_DEPARTMENT: str = os.getenv("TOOL_WORKER_DEPARTMENT", "General")
WORKER_ROLE: str = os.getenv("TOOL_WORKER_ROLE", "system")

# ── FastAPI ─────────────────────────────────────────────────────────────────
WORKER_HOST: str = os.getenv("TOOL_WORKER_HOST", "0.0.0.0")
WORKER_PORT: int = int(os.getenv("TOOL_WORKER_PORT", "8101"))
