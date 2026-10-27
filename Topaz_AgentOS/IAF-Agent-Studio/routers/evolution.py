"""
IAF Agent Studio — Self-Evolution API Router

Tier 1-4 self-evolution analysis: session mining, gap classification,
code analysis, and improvement generation.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from shared.config import SERVER_DIR, DATA_ROOT, REDIS_URL, SKILLS_PATH
from shared.evolution_availability import resolve_evolution_availability
from shared.models import EvolutionRequest

logger = logging.getLogger(__name__)

router = APIRouter()


_evolution_engine = None
_evolution_cache = None


def _build_analysis_kwargs(request: EvolutionRequest) -> dict:
    """Build additive analysis kwargs while preserving legacy defaults."""
    return {
        "lookback_hours": request.lookback_hours,
        "start_time": request.start_time,
        "end_time": request.end_time,
        "max_sessions": request.max_sessions,
        "sources": request.sources,
        "tenant_id": request.tenant_id,
        "agent_id": request.agent_id,
        "skill_filter": request.skill_filter,
        "context_pack_id": request.context_pack_id,
        "context_docs": request.context_docs,
        "analysis_mode": request.analysis_mode,
        "confidence_threshold": request.confidence_threshold,
        "dedup_threshold": request.dedup_threshold,
        "force_fresh": request.force_fresh,
    }


def _get_evolution_engine():
    """Get or create SelfEvolutionEngine instance (lazy init)."""
    global _evolution_engine, _evolution_cache
    if _evolution_engine is None:
        try:
            from iaf_agent_skills.self_evolution import (
                SelfEvolutionEngine,
                EvolutionCache,
            )
            import redis

            # Get workspace root (engine code) and skills root (SKILL.md files)
            workspace_root = SERVER_DIR.parent / "IAF-Agent-Skills"
            skills_root = (SERVER_DIR / SKILLS_PATH).resolve().parent  # enterprise_root/tenants/company/

            # Bounded Redis timeouts so an unreachable Redis cannot stall engine init.
            redis_client = None
            try:
                redis_client = redis.Redis.from_url(
                    REDIS_URL,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                redis_client.ping()
                logger.info("Self-Evolution connected to Redis for caching")
            except Exception as e:
                logger.warning("Self-Evolution Redis not available: %s", e)
                redis_client = None

            llm = None
            light_llm = None
            try:
                from iaf_agent_skills.model_provider import default_model_provider
                llm = default_model_provider.get("primary")
                light_llm = default_model_provider.get("light")
                if llm:
                    logger.info("Self-Evolution LLM ready via ModelProviderAdapter")
                else:
                    logger.warning("Self-Evolution: AZURE_OPENAI env vars not set, LLM analysis disabled")
            except ImportError:
                logger.warning("Self-Evolution: model_provider not available, LLM analysis disabled")
            except Exception as e:
                logger.warning("Self-Evolution LLM init failed: %s", e)

            _evolution_cache = EvolutionCache(redis_client) if redis_client else None
            _evolution_engine = SelfEvolutionEngine(
                workspace_root=str(workspace_root),
                llm=llm,
                light_llm=light_llm,
                redis_client=redis_client,
                data_root=str(SERVER_DIR / DATA_ROOT),
                skills_root=str(skills_root),
            )
            logger.info("Self-Evolution Engine initialized")
        except ImportError as e:
            logger.warning("Self-Evolution module not available: %s", e)
            return None

    return _evolution_engine


def _probe_evolution_module() -> bool:
    """True if the self-evolution module can be imported in this deployment."""
    try:
        import iaf_agent_skills.self_evolution  # noqa: F401
        return True
    except Exception:
        return False


def _probe_redis() -> bool:
    """True if Redis responds to a ping (optional — enables result caching)."""
    try:
        import redis
        # Bounded probe: never let an unreachable Redis block the async event loop.
        client = redis.Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        client.ping()
        return True
    except Exception:
        return False


def _evolution_availability() -> dict:
    """Structured, admin-facing availability status for the Self-Improvement page."""
    return resolve_evolution_availability(
        module_ok=_probe_evolution_module(),
        redis_ok=_probe_redis(),
    )


@router.get("/api/evolution/availability")
async def evolution_availability():
    """Report whether Self-Evolution can run, with a clean reason if it cannot.

    Never leaks an ImportError / stack trace — the UI branches on ``reason``:
    ``ready`` | ``degraded_no_redis`` | ``module_missing``.
    """
    return _evolution_availability()


@router.post("/api/evolution/analyze")
async def start_evolution_analysis(request: EvolutionRequest):
    """
    Start a new self-evolution analysis.

    Args:
        tier: Analysis depth (1=sessions, 2=+classification, 3=+code, 4=+improvements)
        days_back: Number of days of history to analyze

    Returns:
        Job ID and initial status
    """
    engine = _get_evolution_engine()
    if not engine:
        raise HTTPException(503, "Self-evolution module not available")

    analysis_kwargs = _build_analysis_kwargs(request)

    try:
        tier = request.tier
        if tier == 1:
            report = await engine.analyze_tier1_only(days_back=request.days_back, **analysis_kwargs)
        elif tier == 2:
            report = await engine.analyze_tier2(days_back=request.days_back, **analysis_kwargs)
        elif tier == "3a":
            report = await engine.analyze_tier3a(days_back=request.days_back, **analysis_kwargs)
        elif tier == "3b":
            report = await engine.analyze_tier3b(days_back=request.days_back, **analysis_kwargs)
        elif tier == 3 or tier == "3":
            report = await engine.analyze_tier3(days_back=request.days_back, **analysis_kwargs)
        elif tier == "4a":
            report = await engine.analyze_tier4a(days_back=request.days_back, **analysis_kwargs)
        elif tier == "4b":
            report = await engine.analyze_tier4b(days_back=request.days_back, **analysis_kwargs)
        else:
            report = await engine.analyze_full(days_back=request.days_back, **analysis_kwargs)

        # Return full report (gaps + improvements arrays) so dashboard can render directly
        return report.to_dict()
    except Exception as e:
        logger.exception("Evolution analysis failed")
        raise HTTPException(500, "Analysis failed")


@router.get("/api/evolution/status/{job_id}")
async def get_evolution_status(job_id: str):
    """
    Get status of an evolution analysis job.

    Args:
        job_id: Job ID from analyze endpoint

    Returns:
        Current status and progress
    """
    global _evolution_cache

    if _evolution_cache:
        job_data = await _evolution_cache.get_job(job_id)
        if job_data:
            return job_data

    raise HTTPException(404, f"Job '{job_id}' not found")


@router.get("/api/evolution/report/{job_id}")
async def get_evolution_report(job_id: str):
    """
    Get full report for a completed evolution analysis.

    Args:
        job_id: Job ID from analyze endpoint

    Returns:
        Complete EvolutionReport JSON
    """
    global _evolution_cache

    if _evolution_cache:
        report_data = await _evolution_cache.get_report(job_id)
        if report_data:
            return report_data

    raise HTTPException(404, f"Report '{job_id}' not found")


@router.get("/api/evolution/summary")
async def get_evolution_summary():
    """
    Get a quick summary of recent evolution analyses.

    Returns:
        Summary of capabilities and recent gaps
    """
    engine = _get_evolution_engine()
    if not engine:
        raise HTTPException(503, "Self-evolution module not available")

    try:
        report = await engine.analyze_tier1_only(days_back=7)

        return {
            "status": "ok",
            "sessions_last_7_days": report.sessions_analyzed,
            "workspace": str(engine.workspace_root),
            "message": "Use POST /api/evolution/analyze for full analysis",
        }
    except Exception as e:
        logger.error("Evolution summary failed: %s", e, exc_info=True)
        return {
            "status": "error",
            "error": "An internal error occurred",
        }
