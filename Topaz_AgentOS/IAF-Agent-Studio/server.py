#!/usr/bin/env python3
"""
IAF Agent Studio — App Factory (Slim Entry Point)

Assembles the FastAPI application by including router modules,
configuring middleware, and serving static files.

All business logic lives in routers/*.py.
All shared state and singletons live in shared/state.py.
All configuration and path setup lives in shared/config.py.
All Pydantic models live in shared/models.py.

Usage:
    python server.py
    # Open http://localhost:8080
"""

import asyncio
import logging
import sys
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Windows UTF-8 fix — must be first, before any file I/O occurs.
# On Windows, Python defaults to cp1252 (charmap) which crashes on any file
# containing UTF-8 characters (emojis, smart quotes, non-ASCII in SKILL.md).
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    # Reconfigure stdout/stderr to UTF-8 (affects logging output)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    # ProactorEventLoop raises ConnectionResetError([WinError 10054]) when
    # a client closes a socket before the server finishes its shutdown handshake.
    # This is harmless but noisy. WindowsSelectorEventLoopPolicy avoids it.
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # -----------------------------------------------------------------------
    # Ignore stray Ctrl+C / Ctrl+Break injected into a shared console by child
    # subprocesses (the shell tool's curl, workstream cron iterates, python3,
    # etc.). On Windows those events propagate to every process in the console
    # group — including this server — and cleanly shut it down mid-run. Enable
    # by setting IAF_IGNORE_CONSOLE_CTRL=1 (as an OS env var, or in
    # agent_os/config.env). config.env is only loaded later by dotenv, so read
    # the file directly here — this runs before any subprocess is spawned.
    # Real CTRL_CLOSE / LOGOFF / SHUTDOWN are still honoured, so the machine
    # can still stop the process; only the stray C/Break is swallowed.
    # (No-op when running console-less via pythonw — there is no console to
    #  receive these events — so it's safe to leave enabled everywhere.)
    # -----------------------------------------------------------------------
    _ignore_ctrl = os.getenv("IAF_IGNORE_CONSOLE_CTRL", "")
    if not _ignore_ctrl:
        _cfg = Path(__file__).resolve().parent.parent / "agent_os" / "config.env"
        if _cfg.is_file():
            for _line in _cfg.read_text(encoding="utf-8", errors="replace").splitlines():
                _line = _line.strip()
                if _line.startswith("IAF_IGNORE_CONSOLE_CTRL="):
                    _ignore_ctrl = _line.split("=", 1)[1].strip()
                    break
    if _ignore_ctrl.lower() in ("1", "true", "yes"):
        import ctypes
        _HandlerRoutine = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong)
        @_HandlerRoutine
        def _console_ctrl_handler(event):
            # 0 = CTRL_C_EVENT, 1 = CTRL_BREAK_EVENT → swallow (return True).
            # Anything else (close/logoff/shutdown) → return False = default handling.
            return event in (0, 1)
        # Keep a module-level reference so the callback is never GC'd (the OS
        # holds only a raw pointer to it).
        _IAF_CONSOLE_CTRL_HANDLER = _console_ctrl_handler
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_console_ctrl_handler, True)
        try:
            print("[Console] IAF_IGNORE_CONSOLE_CTRL on — ignoring Ctrl+C/Break")
        except Exception:
            pass
# PYTHONUTF8=1 makes open() default to UTF-8 — effective for subprocesses
# launched by this process (e.g. shell tool). Set it early.
os.environ.setdefault("PYTHONUTF8", "1")

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

# ---------------------------------------------------------------------------
# Enterprise structured logging — configure FIRST, before any other imports
# emit logs so module-load errors are captured in the file.
# ---------------------------------------------------------------------------
from shared.logging_config import setup_logging, set_request_context
_LOG_FILE = setup_logging(Path(__file__).resolve().parent / "logs")

# ---------------------------------------------------------------------------
# Shared config & state (must import config FIRST — sets up sys.path)
# ---------------------------------------------------------------------------
from shared.config import (
    AUTH_ENABLED,
    ALLOW_UNSIGNED_FILE_URLS,
    CORS_ALLOWED_ORIGINS,
    DB_BACKEND,
    DEMO_PUBLIC_SURFACES,
    ENTERPRISE_STRICT_MODE,
    FILE_URL_SIGNING_SECRET,
    HOST,
    PORT,
    AGENTOS_KERNEL_BACKEND,
    AGENTOS_KERNEL_REQUIRE_REMOTE,
    AGENTOS_KERNEL_TOKEN_SECRET,
    CC_QUEUE_STORAGE_BACKEND,
    QUEUE_WORKER_REPLICAS,
    QUEUE_INGEST_API_KEY,
    REDIS_URL,
    ROOT_PATH,
    SCHEDULER_LEADER_LOCK_TTL_SECONDS,
    SCHEDULER_LEADER_RETRY_SECONDS,
    SERVER_DIR,
    STUDIO_RUNTIME_ROLES,
    TRACE_VALUE_ROUTER_ENABLED,
    USE_REDIS_SESSIONS,
    UVICORN_WORKERS,
)
from shared.runtime_roles import (
    RedisLeaderLease,
    parse_runtime_roles,
    validate_enterprise_security_config,
    validate_replica_safety,
)
from shared.runtime_health import connect_session_dependency, session_readiness

RUNTIME_ROLES = parse_runtime_roles(STUDIO_RUNTIME_ROLES)
validate_replica_safety(
    roles=RUNTIME_ROLES,
    uvicorn_workers=UVICORN_WORKERS,
    queue_worker_replicas=QUEUE_WORKER_REPLICAS,
    db_backend=DB_BACKEND,
    cc_queue_storage_backend=CC_QUEUE_STORAGE_BACKEND,
)
validate_enterprise_security_config(
    strict_mode=ENTERPRISE_STRICT_MODE,
    roles=RUNTIME_ROLES,
    auth_enabled=AUTH_ENABLED,
    use_redis_sessions=USE_REDIS_SESSIONS,
    demo_public_surfaces=DEMO_PUBLIC_SURFACES,
    allow_unsigned_file_urls=ALLOW_UNSIGNED_FILE_URLS,
    file_url_signing_secret=FILE_URL_SIGNING_SECRET,
    queue_ingest_api_key=QUEUE_INGEST_API_KEY,
    cors_allowed_origins=CORS_ALLOWED_ORIGINS,
    agentos_kernel_backend=AGENTOS_KERNEL_BACKEND,
    agentos_kernel_require_remote=AGENTOS_KERNEL_REQUIRE_REMOTE,
    agentos_kernel_token_secret=AGENTOS_KERNEL_TOKEN_SECRET,
    # Raw env (not the resolved config value, which is a per-process random fallback).
    jwt_secret_env=os.getenv("JWT_SECRET", "").strip(),
)

from shared.state import (
    state,
    set_main_loop,
    cron_scheduler,
    approval_store,
    twin_emitter,
    trace_emitter,
)

# ---------------------------------------------------------------------------
# Router modules (each exports `router = APIRouter()`)
# ---------------------------------------------------------------------------
from security.dependencies import require_request_tenant
from routers import files, agents, audit, skills, cron
from routers import skill_packs as skill_packs_router
from routers import knowledge, approvals, evolution, twin, chat
from routers import world_model as world_model_router
from routers import conversations, settings, mock_apis
from routers import plans as plans_router
from routers import oauth as oauth_router
from routers import auth as auth_router
from routers import privacy as privacy_router
from routers import llm_providers as llm_providers_router
from routers import personal_skills as personal_skills_router
from routers import queue as queue_router
from routers import context_manager as context_manager_router
from routers import email as email_router
from routers import finops as finops_router
from routers import observers as observers_router
from routers import doc_to_skill as doc_to_skill_router
from routers import designer as designer_router
from routers import file_explorer as file_explorer_router
from routers import evidence as evidence_router
from routers import security as security_router
from routers import policy_control as policy_control_router
from routers import workstreams as workstreams_router
from routers import workstream_templates as workstream_templates_router
from routers import automations as automations_router
from routers import evals as evals_router
from routers import rl_capture as rl_capture_router
from routers import metrics as metrics_router
from routers import trace_value as trace_value_router
from routers import recovery_readiness as recovery_readiness_router

logger = logging.getLogger("iaf_server")


# ============================================================================
# Lifespan — startup / shutdown hooks
# ============================================================================

async def _event_loop_watchdog(interval: float = 0.5, threshold: float = 1.0) -> None:
    """Log whenever the event loop was blocked for longer than `threshold` seconds.

    Every request shares this one loop, so a handler that does slow work inline (an LLM
    call, agent.run) freezes the whole server for every user. This measures how late a
    short sleep wakes up; the access-log lines around the warning name the culprit.
    """
    loop = asyncio.get_running_loop()
    while True:
        started = loop.time()
        await asyncio.sleep(interval)
        lag = loop.time() - started - interval
        if lag > threshold:
            logger.warning("Event loop was blocked for %.1fs — a request did slow work "
                           "on the event loop (see the requests logged just before)", lag)


def _log_tenancy_model() -> None:
    """State the deployment model: one server process serves exactly one tenant.

    Login tokens are minted with allowed_tenants=[TENANT_ID] and the request guard refuses
    any other tenant, so a second tenant's data on this disk is unreachable through the API.
    It is still on the same disk, which an operator should know about.
    """
    from shared.config import DATA_ROOT_PATH, TENANT_ID as _TENANT
    logger.info("Tenancy: single-tenant server for '%s' (one server per customer)", _TENANT)
    try:
        others = sorted(
            d.name for d in (DATA_ROOT_PATH / "tenants").iterdir()
            if d.is_dir() and d.name != _TENANT and not d.name.startswith(".")
        )
    except OSError:
        others = []
    if others:
        logger.warning(
            "Tenancy: data for other tenants is present on this server's disk (%s). The API "
            "refuses them, but for customer deployments give each tenant its own server and "
            "data root.", ", ".join(others),
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background services on startup, stop them on shutdown."""
    # Capture the main event loop for cron threads
    set_main_loop(asyncio.get_running_loop())

    logger.info("IAF Agent Studio starting...")
    logger.info("URL: http://%s:%s", HOST, PORT)
    logger.info("Runtime roles: %s", ", ".join(sorted(RUNTIME_ROLES)))
    _log_tenancy_model()
    app.state.runtime_roles = sorted(RUNTIME_ROLES)
    session_state_connected = False
    if "api" in RUNTIME_ROLES:
        try:
            session_state_connected = await connect_session_dependency(
                roles=RUNTIME_ROLES,
                session_state=state,
                strict_mode=ENTERPRISE_STRICT_MODE,
            )
        except RuntimeError:
            try:
                await state.disconnect()
            finally:
                raise
        if not session_state_connected:
            logger.warning(
                "Session State: Redis unavailable; using process-local compatibility fallback"
            )
        else:
            logger.info("Session State: READY")
    scheduler_started = False
    scheduler_task = None
    maintenance_task = None
    scheduler_stop = asyncio.Event()
    scheduler_lease = RedisLeaderLease(
        redis_url=REDIS_URL,
        key="iaf:studio:scheduler:leader",
        ttl_seconds=SCHEDULER_LEADER_LOCK_TTL_SECONDS,
    )

    if TRACE_VALUE_ROUTER_ENABLED and "scheduler" in RUNTIME_ROLES:
        async def _trace_value_reconcile_once():
            try:
                from shared.trace_value_service import evaluate_batch_async

                summary = await evaluate_batch_async()
                logger.info(
                    "Trace Value Router: startup reconciliation completed "
                    "(evaluated=%s skipped=%s errors=%s)",
                    summary.get("evaluated"),
                    summary.get("skipped"),
                    summary.get("errors"),
                )
            except Exception as exc:  # noqa: BLE001 - startup must continue
                logger.warning("Trace Value Router: startup reconciliation failed: %s", exc)

    def _start_scheduler_services() -> None:
        nonlocal scheduler_started
        if scheduler_started:
            return
        cron_scheduler.start(blocking=False)
        scheduler_started = True
        logger.info(
            "Cron Scheduler: LEADER STARTED (%s jobs)",
            cron_scheduler.get_status()["total_jobs"],
        )
        try:
            reconcile = workstreams_router.reconcile_workstream_cron_jobs()
            logger.info(
                "Workstream cron reconcile: %s job(s), %s skipped",
                reconcile.get("total", 0),
                len(reconcile.get("skipped") or []),
            )
        except Exception as reconcile_err:
            logger.warning("Workstream cron reconcile skipped: %s", reconcile_err)
        try:
            from shared.standalone_crons import reconcile_standalone_cron_jobs

            standalone = reconcile_standalone_cron_jobs()
            logger.info(
                "Standalone cron reconcile: %s job(s), %s skipped",
                standalone.get("total", 0),
                len(standalone.get("skipped") or []),
            )
        except Exception as standalone_err:
            logger.warning("Standalone cron reconcile skipped: %s", standalone_err)
        if TRACE_VALUE_ROUTER_ENABLED:
            asyncio.create_task(_trace_value_reconcile_once())

    async def _scheduler_leader_loop() -> None:
        nonlocal scheduler_started
        while not scheduler_stop.is_set():
            try:
                acquired = await asyncio.to_thread(scheduler_lease.acquire)
            except Exception as lease_err:
                if not ENTERPRISE_STRICT_MODE:
                    logger.warning(
                        "Scheduler leader lock unavailable; using local development fallback: %s",
                        lease_err,
                    )
                    try:
                        _start_scheduler_services()
                    except Exception as sched_err:
                        logger.warning("Cron Scheduler: DISABLED — %s", sched_err)
                    return
                logger.error("Scheduler leader lock unavailable in strict mode: %s", lease_err)
                try:
                    await asyncio.wait_for(
                        scheduler_stop.wait(),
                        timeout=SCHEDULER_LEADER_RETRY_SECONDS,
                    )
                except asyncio.TimeoutError:
                    continue
                return

            if not acquired:
                logger.info("Cron Scheduler: STANDBY (another leader owns the lease)")
                try:
                    await asyncio.wait_for(
                        scheduler_stop.wait(),
                        timeout=SCHEDULER_LEADER_RETRY_SECONDS,
                    )
                except asyncio.TimeoutError:
                    continue
                return

            try:
                _start_scheduler_services()
                while not scheduler_stop.is_set():
                    try:
                        await asyncio.wait_for(
                            scheduler_stop.wait(),
                            timeout=max(5, SCHEDULER_LEADER_LOCK_TTL_SECONDS // 3),
                        )
                        break
                    except asyncio.TimeoutError:
                        # renew_resilient tolerates a transient Redis blip (retries with
                        # jitter, never raises) so a single dropped heartbeat can't kill
                        # this loop task — only a definitively lost lease relinquishes.
                        renewed = await asyncio.to_thread(scheduler_lease.renew_resilient)
                        if not renewed:
                            logger.error("Cron Scheduler: leader lease lost; stopping local scheduler")
                            break
            finally:
                if scheduler_started:
                    cron_scheduler.stop(wait=True, timeout=10.0)
                    scheduler_started = False
                try:
                    await asyncio.to_thread(scheduler_lease.release)
                except Exception:
                    pass

    def _run_maintenance() -> None:
        """Retention pass (runs in a worker thread): prune cold transcript files per agent
        (no-op unless TRANSCRIPT_HOT_DAYS>0) and purge old execution traces. Best-effort."""
        # 1) Transcript tiering — prune cold history JSONL whose turns are archived.
        try:
            from shared.config import SERVER_DIR as _SD, DATA_ROOT as _DR
            from iaf_agent_skills.conversation_manager import ConversationManager
            tenants = (_SD / _DR).resolve() / "tenants"
            pruned = 0
            if tenants.exists():
                for tdir in tenants.iterdir():
                    adir = tdir / "agents"
                    if not adir.is_dir():
                        continue
                    for agdir in adir.iterdir():
                        hist = agdir / "memory" / "history"
                        dbp = agdir / "memory" / "knowledge_index.db"
                        if hist.exists():
                            try:
                                pruned += ConversationManager(db_path=dbp).tier_cold_files(hist)
                            except Exception as e:
                                logger.warning("maintenance: prune failed for %s: %s", agdir.name, e)
            if pruned:
                logger.info("maintenance: pruned %d cold transcript file(s)", pruned)
        except Exception as e:
            logger.warning("maintenance: transcript pass failed: %s", e)
        # 2) knowledge.jsonl compaction — the file is append-only (edits/tombstones appended);
        #    collapse superseded duplicates when bloated. Archives first; rare (high threshold).
        try:
            pct = int(os.getenv("KNOWLEDGE_COMPACT_BLOAT_PCT", "50") or "50")
            if pct > 0:
                from shared.config import SERVER_DIR as _SD2, DATA_ROOT as _DR2
                from iaf_agent_skills.knowledge_query import get_jsonl_bloat_stats, compact_knowledge_jsonl
                tenants2 = (_SD2 / _DR2).resolve() / "tenants"
                if tenants2.exists():
                    for tdir in tenants2.iterdir():
                        adir = tdir / "agents"
                        if not adir.is_dir():
                            continue
                        for agdir in adir.iterdir():
                            kj = agdir / "memory" / "context_graph" / "knowledge.jsonl"
                            if not kj.exists():
                                continue
                            try:
                                b = get_jsonl_bloat_stats(kj)
                                if b.get("total_lines", 0) >= 200 and b.get("bloat_pct", 0) >= pct:
                                    r = compact_knowledge_jsonl(kj)
                                    logger.info("maintenance: compacted %s knowledge.jsonl (%s→%s lines)",
                                                agdir.name, r.get("total_before"), r.get("unique_after"))
                            except Exception as e:
                                logger.warning("maintenance: compact failed for %s: %s", agdir.name, e)
        except Exception as e:
            logger.warning("maintenance: knowledge compaction pass failed: %s", e)
        # 3) Trace retention (previously unscheduled).
        try:
            from shared.state import trace_emitter as _te
            if _te:
                _te.purge_old_traces(days=int(os.getenv("TRACE_RETENTION_DAYS", "30") or "30"))
        except Exception as e:
            logger.warning("maintenance: trace purge failed: %s", e)

    async def _maintenance_loop() -> None:
        """Leader-safe daily maintenance. Fleet-safe via a Redis NX day-key so only ONE instance
        runs each window (falls through to run on a single node without Redis). First pass runs
        shortly after boot, then every MAINTENANCE_INTERVAL_SECONDS."""
        interval = int(os.getenv("MAINTENANCE_INTERVAL_SECONDS", "86400") or "86400")
        delay = min(120, interval)  # first pass ~2 min after startup
        while not scheduler_stop.is_set():
            try:
                await asyncio.wait_for(scheduler_stop.wait(), timeout=delay)
                break  # shutting down
            except asyncio.TimeoutError:
                pass
            delay = interval
            # Fleet-safe leader election: only the instance that sets the NX day-key runs this
            # window. Isolated in its own try so an import/Redis failure NEVER skips maintenance —
            # it just degrades to single-node (run=True), which is correct on a Redis-less node.
            run = True
            try:
                from shared.state import redis_client
                if redis_client is not None:
                    got = await redis_client.set(
                        "agentos:maintenance:daily", "1", nx=True, ex=max(60, interval - 60)
                    )
                    run = bool(got)
            except Exception as lease_err:
                run = True
                logger.debug("maintenance leader-key unavailable, running on this node: %s", lease_err)
            try:
                if run:
                    await asyncio.to_thread(_run_maintenance)
            except Exception as e:
                logger.warning("maintenance loop error (non-fatal): %s", e)

    if "scheduler" in RUNTIME_ROLES:
        scheduler_task = asyncio.create_task(_scheduler_leader_loop())
        maintenance_task = asyncio.create_task(_maintenance_loop())

    # Connect HITL Approval Store to Redis
    try:
        await approval_store.connect()
        logger.info("HITL Approval Store: CONNECTED")
    except Exception as hitl_err:
        logger.warning("HITL Approval Store: DISABLED — %s (start Redis to enable)", hitl_err)

    # Start Digital Twin telemetry emitter
    if twin_emitter:
        await twin_emitter.start()
        logger.info("Twin Telemetry: ENABLED (async queue -> SQLite)")
    else:
        logger.info("Twin Telemetry: DISABLED (set TWIN_TELEMETRY=true to enable)")

    # Start Execution Trace emitter
    if trace_emitter:
        await trace_emitter.start()
        logger.info("Trace Telemetry: ENABLED (async queue -> SQLite)")
    else:
        logger.info("Trace Telemetry: DISABLED (set TRACE_TELEMETRY=true to enable)")

    # Eager storage-backend health check — catches misconfiguration (e.g.
    # DB_BACKEND=postgres without DATABASE_URL) at startup rather than on the
    # first request, where the error would be much harder to diagnose.
    try:
        from shared.config import DB_BACKEND, DATABASE_URL, VECTOR_BACKEND
        from iaf_agent_skills.storage import get_engine, resolve_backend
        _backend = resolve_backend()
        if _backend == "postgres" and not DATABASE_URL:
            logger.error(
                "Storage: DB_BACKEND=postgres but DATABASE_URL is not set — "
                "all agent DB operations will fail. Set DATABASE_URL or switch "
                "DB_BACKEND=sqlite."
            )
        else:
            _health = get_engine(
                db_path=None if _backend == "postgres" else
                DATA_ROOT_PATH / "tenants" / "company" / "shared" / "databases" / "health_check.db"
            ).health()
            _reachable = _health.get("reachable", True)
            if _reachable:
                logger.info("Storage: %s backend REACHABLE", _backend.upper())
            else:
                logger.error(
                    "Storage: %s backend NOT reachable — %s",
                    _backend.upper(), _health.get("error", "unknown")
                )
    except Exception as _storage_err:
        logger.error("Storage: health check failed — %s", _storage_err)

    # Init Command Center store for API/queue roles. Only queue roles process items.
    if RUNTIME_ROLES.intersection({"api", "queue"}):
        try:
            from cc_queue.db import init_db_path, get_db
            import os as _os
            _STATIC_DIR_REF = Path(__file__).resolve().parent
            init_db_path(_STATIC_DIR_REF)
            get_db()  # Creates tables on first call
            logger.info("Command Center: store ready (%s)", CC_QUEUE_STORAGE_BACKEND)
            if "queue" in RUNTIME_ROLES:
                from cc_queue.processor import get_processor

                _queue_proc = get_processor()
                _queue_proc.start()
                logger.info(
                    "Command Center: STARTED (queue worker role online; replicas=%s)",
                    QUEUE_WORKER_REPLICAS,
                )
                if _os.getenv("QUEUE_SEED_DEMO", "false").lower() == "true":
                    from cc_queue.seed import seed_demo_items
                    seed_demo_items()
        except Exception as cc_err:
            logger.warning("Command Center: DISABLED — %s", cc_err)

    # Ensure seed admin exists (optional; disabled by default for safety)
    if os.getenv("AUTH_SEED_ADMIN_ON_STARTUP", "false").lower() == "true":
        try:
            from auth.seed_admin import main as _seed_admin
            await _seed_admin(quiet=True)
            logger.info("Auth: seed admin verified")
        except Exception as seed_err:
            logger.warning("Auth: seed admin check failed — %s", seed_err)

    # Init Workstream runtime DB. Workstream YAML remains the business state,
    # while this SQLite store keeps live execution steps durable for the UI.
    try:
        from workstream_runtime.db import init_db_path as init_ws_runtime_path, get_db as get_ws_runtime_db
        _STATIC_DIR_REF = Path(__file__).resolve().parent
        init_ws_runtime_path(_STATIC_DIR_REF)
        get_ws_runtime_db()
        logger.info("Workstream Runtime DB: ENABLED")
    except Exception as ws_runtime_err:
        logger.warning("Workstream Runtime DB: DISABLED — %s", ws_runtime_err)

    # Init Automation runtime DB. Automation YAML remains the business state;
    # this SQLite store keeps deterministic run traces durable for the UI.
    try:
        from automation_runtime.db import init_db_path as init_auto_runtime_path, get_db as get_auto_runtime_db
        _STATIC_DIR_REF = Path(__file__).resolve().parent
        init_auto_runtime_path(_STATIC_DIR_REF)
        get_auto_runtime_db()
        logger.info("Automation Runtime DB: ENABLED")
    except Exception as auto_runtime_err:
        logger.warning("Automation Runtime DB: DISABLED — %s", auto_runtime_err)

    # Phase 3: Apply saved admin config overrides to live objects
    from routers.settings import apply_saved_overrides_on_startup
    admin_result = apply_saved_overrides_on_startup()
    logger.info(
        "Admin Config: %d applied, %d skipped, %d errors",
        admin_result["applied"], admin_result["skipped"], admin_result["errors"],
    )

    # Batch 4: expose the capability registry on app.state so routers can pull
    # it from ``request.app.state.capability_registry`` instead of having to
    # ``from shared.state import capability_registry``. The registry itself is
    # built in shared/state.py during module import; this just publishes the
    # reference + the hook kill-switch state for diagnostics.
    try:
        from shared.state import capability_registry as _cap_registry
        from shared.config import CAPABILITY_HOOKS_ENABLED as _cap_hooks
        app.state.capability_registry = _cap_registry
        app.state.capability_hooks_enabled = bool(_cap_hooks)
        logger.info(
            "Capability registry attached to app.state (capability_hooks_enabled=%s)",
            _cap_hooks,
        )
    except Exception as cap_err:
        logger.warning("Capability registry attach failed (non-fatal): %s", cap_err)

    logger.info("")

    loop_watchdog_task = asyncio.create_task(_event_loop_watchdog())

    yield  # ── application runs here ──

    # Graceful shutdown
    logger.info("Shutting down...")
    loop_watchdog_task.cancel()
    from telemetry.otel_setup import shutdown_otel
    shutdown_otel()  # flush pending spans/metrics/logs (no-op when OTel is off)
    if "queue" in RUNTIME_ROLES:
        try:
            from cc_queue.processor import get_processor
            await get_processor().stop()
            logger.info("Command Center: STOPPED")
        except Exception:
            pass
    if scheduler_task is not None:
        scheduler_stop.set()
        try:
            await asyncio.wait_for(scheduler_task, timeout=15)
        except asyncio.TimeoutError:
            scheduler_task.cancel()
        logger.info("Cron Scheduler: STOPPED")
    if maintenance_task is not None:
        scheduler_stop.set()  # shared stop signal
        try:
            await asyncio.wait_for(maintenance_task, timeout=10)
        except asyncio.TimeoutError:
            maintenance_task.cancel()
        logger.info("Maintenance loop: STOPPED")

    await approval_store.disconnect()
    logger.info("HITL Approval Store: DISCONNECTED")

    if "api" in RUNTIME_ROLES:
        await state.disconnect()
        logger.info("Session State: DISCONNECTED")

    if twin_emitter:
        await twin_emitter.stop()
        logger.info("Twin Telemetry: STOPPED")

    if trace_emitter:
        await trace_emitter.stop()
        logger.info("Trace Telemetry: STOPPED")

    # Close the shared async Redis client (auth blacklist / rate-limit / audit / maintenance).
    try:
        from shared.state import redis_client as _rc
        if _rc is not None:
            await _rc.aclose()
            logger.info("Shared Redis client: CLOSED")
    except Exception as exc:  # noqa: BLE001 - shutdown best-effort
        logger.debug("Shared Redis client close failed (non-fatal): %s", exc)

    # Drain the shared Postgres connection pool LAST — one pooled engine backs both the
    # Command Center queue and the knowledge index, so this is closed after every
    # consumer above has stopped. No-op on SQLite / when psycopg_pool is unavailable.
    try:
        from iaf_agent_skills.storage.engine import close_engines
        close_engines()
        logger.info("Storage engine pool: CLOSED")
    except Exception as exc:  # noqa: BLE001 - shutdown best-effort
        logger.warning("Storage engine pool close failed (non-fatal): %s", exc)


# ============================================================================
# App creation
# ============================================================================

app = FastAPI(
    title="IAF Agent Studio",
    description="Web UI for IAF Agent Skills",
    version="1.0.0",
    lifespan=lifespan,
    # Sub-path deployments (served behind a gateway under e.g. /qlabs). Empty by
    # default => root deployment, unchanged. Drives correct redirect/openapi URLs.
    root_path=ROOT_PATH,
)


# Auth middleware — enforces JWT on /api/* when AUTH_ENABLED=true
from auth.middleware import AuthMiddleware
app.add_middleware(AuthMiddleware)

from shared.static_cors import StaticExemptCORSMiddleware
app.add_middleware(
    StaticExemptCORSMiddleware,
    allow_origins=list(CORS_ALLOWED_ORIGINS),
    allow_credentials=bool(CORS_ALLOWED_ORIGINS) and "*" not in CORS_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-API-Key", "X-Trace-Id"],
)

from shared.config import BEHIND_PROXY, FORWARDED_ALLOW_IPS
if BEHIND_PROXY:
    logger.info("Proxy header support enabled (forwarded_allow_ips=%s)", FORWARDED_ALLOW_IPS)


# ---------------------------------------------------------------------------
# Logging context middleware — injects trace_id / user_id into every log line
# ---------------------------------------------------------------------------

def _current_otel_trace_id() -> str:
    try:
        from opentelemetry import trace as _otel_trace
        ctx = _otel_trace.get_current_span().get_span_context()
        return format(ctx.trace_id, "032x") if ctx.is_valid else ""
    except Exception:
        return ""


@app.middleware("http")
async def logging_context_middleware(request: Request, call_next):
    """Stamp each request with a trace_id so all logs for a request are linkable."""
    trace_id = request.headers.get("x-trace-id") or _current_otel_trace_id() or str(uuid.uuid4())[:8]
    # user_id is set by AuthMiddleware on request.state; read after it runs
    user_id = getattr(request.state, "user_id", "")
    set_request_context(trace_id=trace_id, user_id=user_id)
    response = await call_next(request)
    response.headers["x-trace-id"] = trace_id
    return response


# ---------------------------------------------------------------------------
# Global exception handler — ensures all unhandled 500s return JSON, not HTML.
# Without this, FastAPI returns "Internal Server Error" as plain text, which
# causes "Unexpected token 'I'..." JSON parse errors in the frontend.
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": str(exc) or "Internal server error", "path": request.url.path},
    )


# ============================================================================
# Static HTML routes (must come BEFORE the static mount)
# ============================================================================

_STATIC_DIR = SERVER_DIR / "static"


# ---------------------------------------------------------------------------
# Base-path (sub-path) injection
#
# When ROOT_PATH is set (e.g. "/qlabs"), the app is served behind a gateway
# under that prefix. The frontend makes root-absolute API/WS calls (fetch("/api
# /..."), new WebSocket("wss://host/ws/chat")), which the browser resolves
# against the ORIGIN root — bypassing the prefix and 404ing at the gateway.
#
# Rather than rewrite hundreds of scattered call sites, we inject a tiny inline
# bootstrap into the <head> of every served HTML page. It records the base path
# and transparently shims fetch / WebSocket / window.open to prefix same-origin
# absolute paths. It also exposes window.apiUrl()/window.wsUrl() helpers.
#
# CRITICAL: when ROOT_PATH is empty (root deployment), NOTHING is injected and
# pages are served via FileResponse exactly as before — byte-for-byte identical.
# ---------------------------------------------------------------------------
from shared.base_path import inject_base_path as _inject_base_path
from shared.csp_nonce import inject_nonce as _inject_csp_nonce


def _serve_html(path: Path, *, nocache: bool = False, nonce: Optional[str] = None) -> FileResponse | HTMLResponse:
    """Serve an HTML file, stamping the request's CSP nonce (SEC-4) onto its
    inline <script>/<style> tags and injecting the base-path bootstrap when
    ROOT_PATH is set.

    Every call now reads and transforms the file (no more byte-identical
    FileResponse fast path at root) because the nonce must be unique per
    request to satisfy the nonce-based CSP. Falls back to a raw, un-nonced
    FileResponse only if the file can't be read as UTF-8 text.
    """
    try:
        html = Path(path).read_text(encoding="utf-8")
        if ROOT_PATH:
            html = _inject_base_path(html, ROOT_PATH)
        if nonce:
            html = _inject_csp_nonce(html, nonce)
        response: FileResponse | HTMLResponse = HTMLResponse(html)
    except Exception:  # pragma: no cover - fall back to raw file on read error
        response = FileResponse(path)
    if nocache:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/health/live", tags=["Health"])
async def health_live():
    """Return process liveness without probing external dependencies."""
    return {"status": "live"}


@app.get("/health/ready", tags=["Health"])
async def health_ready():
    """Return role-aware readiness without exposing dependency connection data."""
    sessions = await session_readiness(
        roles=RUNTIME_ROLES,
        session_state=state,
    )
    content = {
        "status": "ready" if sessions != "unavailable" else "not_ready",
        "dependencies": {"sessions": sessions},
    }
    if sessions == "unavailable":
        return JSONResponse(status_code=503, content=content)
    return content


@app.get("/")
async def root(request: Request):
    """Serve main UI."""
    return _serve_html(_STATIC_DIR / "index.html", nonce=request.state.csp_nonce)


@app.get("/skill-builder")
async def skill_builder():
    """Redirect old skill-builder URL to v2."""
    from fastapi.responses import RedirectResponse
    # Prefix-aware: under a sub-path deployment the target must carry ROOT_PATH
    # so the browser stays inside the gateway prefix. Empty ROOT_PATH => "/skill-builder/v2".
    return RedirectResponse(url=f"{ROOT_PATH}/skill-builder/v2", status_code=301)


@app.get("/skill-builder/v2")
async def skill_builder_v2(request: Request):
    """Serve Skill Designer Studio V2."""
    return _serve_html(_STATIC_DIR / "skill-builder-v2.html", nonce=request.state.csp_nonce)


@app.get("/skill-creator")
async def skill_creator(request: Request):
    """Serve Skill Creator — non-technical wizard for creating skills from documents."""
    return _serve_html(_STATIC_DIR / "skill-creator.html", nonce=request.state.csp_nonce)


@app.get("/studio")
@app.get("/customize")
async def studio(request: Request):
    """Serve AgentPro Studio — unified customization surface."""
    return _nocache_response("studio.html", nonce=request.state.csp_nonce)


def _nocache_response(filename: str, *, nonce: Optional[str] = None) -> FileResponse | HTMLResponse:
    """Serve a static HTML file with no-cache headers (base-path aware)."""
    return _serve_html(_STATIC_DIR / filename, nocache=True, nonce=nonce)


def _nocache_path_response(path: Path, *, nonce: Optional[str] = None) -> FileResponse | HTMLResponse:
    """Serve a module-owned HTML path with no-cache headers (base-path aware)."""
    return _serve_html(path, nocache=True, nonce=nonce)


@app.get("/dashboard")
@app.get("/dashboard/v2")
async def command_surface_v2(request: Request):
    """Serve Agent Command Surface V2 — enterprise dashboard."""
    return _nocache_response("dashboard_v2.html", nonce=request.state.csp_nonce)


@app.get("/twin")
async def digital_twin_dashboard(request: Request):
    """Serve Operational Digital Twin dashboard."""
    return _nocache_response("twin.html", nonce=request.state.csp_nonce)


@app.get("/twin/optimization")
async def twin_optimization_page(request: Request):
    """Serve full ESAA Process Optimization page."""
    return _nocache_response("optimization.html", nonce=request.state.csp_nonce)


@app.get("/login")
async def login_page(request: Request):
    """Serve authentication login/register page."""
    return _nocache_response("login.html", nonce=request.state.csp_nonce)


@app.get("/finops")
async def finops_page(request: Request):
    """Serve AI FinOps cost intelligence dashboard."""
    return _nocache_response("finops.html", nonce=request.state.csp_nonce)


@app.get("/observers")
async def observers_page(request: Request):
    """Serve the Observers console (list)."""
    return _nocache_response("bp_observers.html", nonce=request.state.csp_nonce)


@app.get("/observers/{name}")
async def observer_detail_page(name: str, request: Request):
    """Serve the Observer detail console."""
    return _nocache_response("bp_observer_detail.html", nonce=request.state.csp_nonce)


@app.get("/rl-capture")
@app.get("/rl-eval")
async def rl_capture_page(request: Request):
    """Serve standalone RL/Eval Training Studio."""
    return _nocache_response("rl_capture.html", nonce=request.state.csp_nonce)


@app.get("/world-model")
@app.get("/graph-review")
async def world_model_review_page(request: Request):
    """Serve the World-Model graph review surface (promote/reject pending edges)."""
    return _nocache_response("world_model_review.html", nonce=request.state.csp_nonce)


@app.get("/rl-capture/workbench")
async def rl_capture_workbench_page(request: Request):
    """Serve the dark 3-pane RL trajectory Workbench (opened from the Studio)."""
    return _nocache_response("rl_workbench.html", nonce=request.state.csp_nonce)


# ============================================================================
# Include all routers
# ============================================================================

# Every API router except the pre-login / public ones gets the tenant guard: a request
# naming a tenant its caller is not entitled to is refused with 403 before any handler
# runs (security/dependencies.py:require_request_tenant). context_manager binds its own.
_TENANT_GUARD = [Depends(require_request_tenant)]

app.include_router(files.router, dependencies=_TENANT_GUARD)
app.include_router(agents.router, dependencies=_TENANT_GUARD)
app.include_router(audit.router, dependencies=_TENANT_GUARD)
app.include_router(metrics_router.router)
app.include_router(skills.router, dependencies=_TENANT_GUARD)
app.include_router(skill_packs_router.router, dependencies=_TENANT_GUARD)  # skill import/export (.skillpack.zip)
app.include_router(cron.router, dependencies=_TENANT_GUARD)
app.include_router(knowledge.router, dependencies=_TENANT_GUARD)
app.include_router(world_model_router.router, dependencies=_TENANT_GUARD)
app.include_router(approvals.router, dependencies=_TENANT_GUARD)
app.include_router(evolution.router, dependencies=_TENANT_GUARD)
app.include_router(twin.router, dependencies=_TENANT_GUARD)
app.include_router(chat.router, dependencies=_TENANT_GUARD)
app.include_router(conversations.router, dependencies=_TENANT_GUARD)
app.include_router(settings.router, dependencies=_TENANT_GUARD)
app.include_router(mock_apis.router)  # Mock external APIs for testing
app.include_router(plans_router.router, dependencies=_TENANT_GUARD)
app.include_router(auth_router.router)
app.include_router(oauth_router.router)            # Keycloak SSO — OAuth 2.0 + PKCE
app.include_router(privacy_router.router)          # Data Privacy — login notice + acknowledgement gate
app.include_router(llm_providers_router.router, dependencies=_TENANT_GUARD)    # Runtime LLM provider selection (admin)
app.include_router(personal_skills_router.router, dependencies=_TENANT_GUARD)  # Personal skill workspace + review workflow
app.include_router(queue_router.router, dependencies=_TENANT_GUARD)             # Command Center — autonomous queue processor
app.include_router(context_manager_router.router)   # Enterprise Context Manager
app.include_router(email_router.router, dependencies=_TENANT_GUARD)             # Email compose + send (O365 Graph)
app.include_router(finops_router.router, dependencies=_TENANT_GUARD)            # AI FinOps — cost & token analytics
app.include_router(observers_router.router, dependencies=_TENANT_GUARD)         # Observers — Headlong companion agents (feature-flagged)
app.include_router(doc_to_skill_router.router, dependencies=_TENANT_GUARD)      # Doc-to-Skill pipeline + Skill Creator
app.include_router(designer_router.router, dependencies=_TENANT_GUARD)          # Skill Designer — NL authoring (Dev Mode)
app.include_router(file_explorer_router.router, dependencies=_TENANT_GUARD)     # Admin File Explorer (enterprise_root + skills)
app.include_router(evidence_router.router, dependencies=_TENANT_GUARD)          # Enterprise Evidence retrieval/content API
app.include_router(security_router.router, dependencies=_TENANT_GUARD)          # Security Console — entitlement policies/simulator/audit
app.include_router(policy_control_router.router, dependencies=_TENANT_GUARD)    # Central Policy & Control Registry
app.include_router(workstreams_router.router, dependencies=_TENANT_GUARD)        # Mission Mode — workstreams REST + WebSocket
app.include_router(workstream_templates_router.router, dependencies=_TENANT_GUARD)  # Workstream templates — reusable shapes
app.include_router(automations_router.router, dependencies=_TENANT_GUARD)        # Deterministic Automations — no-LLM pipelines
app.include_router(evals_router.router, dependencies=_TENANT_GUARD)              # Private Learning Loop — eval registry and golden sets
app.include_router(rl_capture_router.router, dependencies=_TENANT_GUARD)         # RL/eval capture dataset inspection
app.include_router(trace_value_router.router, dependencies=_TENANT_GUARD)         # Trace Value Router — advisory learning destination routing
app.include_router(recovery_readiness_router.router, dependencies=_TENANT_GUARD)  # Recovery Readiness — isolated restore verification and reports

# OpenTelemetry HTTP server spans + traceparent propagation (no-op unless TELEMETRY_EXPORTERS
# includes `otel`). Installed after every other middleware so it is the outermost layer and
# the request span exists for the logging middleware above.
from telemetry.otel_setup import instrument_app as _otel_instrument_app  # noqa: E402
_otel_instrument_app(app)


# ============================================================================
# Static file mount (AFTER explicit routes so they take priority)
# ============================================================================

from shared.static_guard import is_backup_artifact as _is_backup_artifact


class BasePathStaticFiles(StaticFiles):
    """StaticFiles that stamps the request's CSP nonce (SEC-4) onto served
    HTML and injects the base-path bootstrap into it when ROOT_PATH is set.

    Some UI surfaces (e.g. the Mission-Mode workstream pages) are reached only
    through the ``/static`` mount rather than an explicit route, so they never
    pass through ``_serve_html``. Under a sub-path deployment their
    ``<script src="/static/...">`` assets and ``<a href="/...">`` links would
    otherwise resolve against the origin root and 404 at the gateway. And
    regardless of ``ROOT_PATH``, these pages carry the same
    nonce-based Content-Security-Policy response header as every other route
    (``auth/middleware.py`` applies it to all responses) — their inline
    ``<script>``/``<style>`` tags need the matching nonce stamped on or the
    browser refuses to run them.

    SEC-14: editor/backup artefacts are refused with 404. ``StaticFiles``
    serves whatever sits in the directory, so a stray ``page.html.bak_*`` or
    ``page.html~`` publishes a superseded copy of the app's own source —
    including auth code that has since been hardened. They are served as
    ``application/octet-stream`` (unknown suffix) rather than parsed as HTML,
    so they also bypass the nonce/base-path stamping above. Refusing them is
    safer than relying on the files being deleted.
    """

    async def get_response(self, path: str, scope):  # type: ignore[override]
        if _is_backup_artifact(path):
            raise HTTPException(status_code=404)
        response = await super().get_response(path, scope)
        if not path.lower().endswith(".html"):
            return response
        file_path = getattr(response, "path", None)
        if not file_path:
            return response
        try:
            html = Path(file_path).read_text(encoding="utf-8")
        except Exception:  # pragma: no cover - fall back to raw file on read error
            return response
        if ROOT_PATH:
            html = _inject_base_path(html, ROOT_PATH)
        nonce = (scope.get("state") or {}).get("csp_nonce")
        if nonce:
            html = _inject_csp_nonce(html, nonce)
        return HTMLResponse(html)


app.mount("/static", BasePathStaticFiles(directory=str(_STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn
    from shared.config import SSL_CERTFILE, SSL_KEYFILE

    ssl_kwargs = {}
    if SSL_CERTFILE and SSL_KEYFILE:
        ssl_kwargs = {"ssl_certfile": SSL_CERTFILE, "ssl_keyfile": SSL_KEYFILE}
        logger.info("TLS enabled")
    else:
        logger.warning("TLS disabled; serving HTTP")

    # workers>1 requires an import string (not the app object) so each process
    # imports server:app independently.
    run_target = "server:app" if UVICORN_WORKERS > 1 else app
    if UVICORN_WORKERS > 1:
        logger.info("Multi-process mode enabled with %s workers", UVICORN_WORKERS)

    uvicorn.run(
        run_target,
        host=HOST,
        port=PORT,
        workers=UVICORN_WORKERS,
        reload=False,
        log_level="info",
        proxy_headers=BEHIND_PROXY,
        forwarded_allow_ips=FORWARDED_ALLOW_IPS or '127.0.0.1',
        # Sub-path deployments. Empty ROOT_PATH keeps the historical root mount.
        root_path=ROOT_PATH,
        **ssl_kwargs,
    )
