"""
LLM provider API.

Lets authenticated users inspect which model providers are configured on the
running server, see which one is currently active, and switch between them
at runtime without editing .env or restarting the process.

Endpoints:
    GET  /api/llm/providers           list configured providers + active one
    PUT  /api/llm/providers/active    set the active provider {"provider":"openai|azure"}

Authoritative state lives in `LLM_ACTIVE_PROVIDER` (env var) and is consumed
by `iaf_agent_skills.model_registry.ModelRegistry`. Switching clears the
ModelRegistry's cached LLM instances so the next call rebuilds against the
newly chosen backend.

The provider id "openai" covers any OpenAI-compatible endpoint (vLLM, Ollama,
the public OpenAI API, Gemma served via vLLM, etc.) and is selected via
OPENAI_BASE_URL / OPENAI_MODEL_NAME. "azure" uses AZURE_OPENAI_*.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth.middleware import require_admin, require_auth

logger = logging.getLogger(__name__)
router = APIRouter(tags=["llm-providers"])


class SetActiveProviderRequest(BaseModel):
    provider: str = Field(..., description="Provider id: 'openai' | 'azure' | 'anthropic'")


def _registry():
    """Lazy import — keeps router import cheap and avoids hard coupling."""
    from iaf_agent_skills.model_registry import ModelRegistry  # noqa: WPS433
    return ModelRegistry


@router.get("/api/llm/providers")
async def list_providers(_: dict = Depends(require_auth)) -> dict:
    """List configured providers and which one is currently active."""
    return _registry().list_providers()


@router.put("/api/llm/providers/active")
async def set_active_provider(
    body: SetActiveProviderRequest,
    user: dict = Depends(require_admin),
) -> dict:
    """Switch the active LLM provider for the running process."""
    reg = _registry()
    info = reg.list_providers()
    chosen = (body.provider or "").strip().lower()

    by_id = {p["id"]: p for p in info["providers"]}
    if chosen not in by_id:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{body.provider}'. Use one of: {sorted(by_id)}")
    if not by_id[chosen]["configured"]:
        raise HTTPException(status_code=409, detail=f"Provider '{chosen}' is not configured (missing env vars).")

    try:
        reg.set_active_provider(chosen)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Update every live agent (templates and session clones): they cache self.llm at creation.
    from shared.state import state
    from iaf_agent_skills.model_provider import default_model_provider
    default_model_provider.reset()

    try:
        new_primary = default_model_provider.get("primary")
        new_light = default_model_provider.get("light")
        new_router = default_model_provider.get("router")
    except Exception as e:
        logger.error("Failed to create LLMs for provider '%s': %s", chosen, e)
        raise HTTPException(status_code=500, detail="An internal error occurred")

    # Collect ALL live agent instances: templates + session-pool clones
    all_agents = list(state.agents.values())
    for pool in state._session_pool.values():
        all_agents.extend(pool.values())

    swapped = 0
    for agent in all_agents:
        try:
            agent.llm = new_primary
            agent.light_llm = new_light
            if hasattr(agent, 'router') and agent.router:
                agent.router.llm = new_router
            swapped += 1
        except Exception as e:
            logger.warning("Failed to refresh LLM on agent: %s", e)

    logger.info("LLM provider switched to '%s' by user_id=%s (%d agents updated)", chosen, user.get("user_id"), swapped)
    return reg.list_providers()
