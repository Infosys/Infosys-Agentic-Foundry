"""
Centralized LLM factory — single source of truth for all model instances.

Instead of 5 places calling os.getenv("AZURE_OPENAI_*") independently,
all code calls ModelRegistry.get("primary") or ModelRegistry.get("light").

Adding a new model role = 1 line in ROLE_ENV_MAP + 1 env var.

Usage:
    from iaf_agent_skills.model_registry import ModelRegistry

    llm = ModelRegistry.get("primary")        # Main reasoning model
    light = ModelRegistry.get("light")         # Cheap/fast classification
    router_llm = ModelRegistry.get("router")   # Skill routing
"""

import logging
import os
from typing import Optional, Union

import httpx

logger = logging.getLogger(__name__)


def _coerce_verify(val: str):
    """Map a raw env value to an httpx-compatible verify value, or None if unset.

    false/0/no/off  → False (disable verification)
    /path/to/ca.pem → that path (custom CA bundle)
    empty / unset   → None (caller decides the fallback)
    anything else   → True (use the process default trust store)
    """
    val = (val or "").strip()
    if not val:
        return None
    if val.lower() in {"0", "false", "no", "off"}:
        return False
    if os.path.isfile(val):
        return val
    return True


def _get_internal_ssl_verify():
    """CA trust for DIRECT internal endpoints (self-hosted vLLM/Gemma, KB server).

    These hosts are in NO_PROXY, so they bypass the corporate proxy and present a
    cert signed by the internal Infosys CA chain — that chain must be supplied
    here. Priority: INTERNAL_CA_BUNDLE, then OPENAI_SSL_VERIFY (back-compat).
    Falls back to the default trust store (True) when neither is set.
    """
    for name in ("INTERNAL_CA_BUNDLE", "OPENAI_SSL_VERIFY"):
        verify = _coerce_verify(os.getenv(name))
        if verify is not None:
            return verify
    return True


def _get_public_ssl_verify():
    """CA trust for PUBLIC endpoints reached THROUGH the corporate proxy (Azure).

    A TLS-intercepting proxy (e.g. Zscaler / Infosys-PXY) re-signs the server cert
    with its own root CA, so the trust store MUST contain that interception CA.

    Priority (mirrors the ANTHROPIC_* pattern so Azure has its own isolated knobs):
      1. AZURE_SSL_VERIFY   — false/0/no/off → skip; path → that CA; true → default
      2. AZURE_CA_BUNDLE    — path to PEM bundle for Azure specifically
      3. PUBLIC_CA_BUNDLE   — back-compat: shared "public + proxy" bundle
      4. default trust store (True)

    Deliberately does NOT read the internal-only bundle: pointing Azure at the
    internal CA chain is exactly what causes CERTIFICATE_VERIFY_FAILED here.
    """
    for name in ("AZURE_SSL_VERIFY", "AZURE_CA_BUNDLE", "PUBLIC_CA_BUNDLE"):
        verify = _coerce_verify(os.getenv(name))
        if verify is not None:
            return verify
    return True


def _make_httpx_client(verify) -> httpx.Client:
    return httpx.Client(verify=verify, timeout=30.0)


def _make_async_httpx_client(verify) -> httpx.AsyncClient:
    return httpx.AsyncClient(verify=verify, timeout=30.0)
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from .anthropic_thinking_chat import ChatAnthropicThinking
from .azure_responses_chat import ChatAzureResponsesRaw
from .model_reasoning_meta import get_reasoning_capability, reasoning_replay_enabled
from .vertex_chat import ChatVertexAIRaw


AZURE_ROLE_ENV_MAP: dict[str, str] = {
    "primary":      "AZURE_OPENAI_DEPLOYMENT",
    "fallback":     "AZURE_OPENAI_DEPLOYMENT_FALLBACK",
    "light":        "AZURE_OPENAI_DEPLOYMENT_LIGHT",
    "router":       "AZURE_OPENAI_DEPLOYMENT",
    "queue_router": "AZURE_OPENAI_DEPLOYMENT_LIGHT",
}

# router and queue_router alias to primary/light respectively.
ROLE_ALIAS: dict[str, str] = {
    "router":       "primary",
    "queue_router": "light",
}


def _role_key(role: str) -> str:
    """Normalise role to its config key (router→primary, queue_router→light)."""
    return ROLE_ALIAS.get(role, role)


# Minimum Azure api-version that accepts the reasoning_effort parameter.
_REASONING_MIN_API_VERSION = "2025-03-01-preview"


def _api_version_supports_reasoning(api_version: str) -> bool:
    """True when the Azure api-version is new enough for reasoning_effort.

    Azure api-versions are date-prefixed (YYYY-MM-DD[-preview]); a lexical
    compare on the date prefix is sufficient and avoids brittle parsing.
    """
    if not api_version:
        return False
    return api_version[:10] >= _REASONING_MIN_API_VERSION[:10]


def _reasoning_kwargs_for(role: str, api_version: str) -> dict:
    """Return model_kwargs to enable native reasoning, or {} to keep legacy behaviour.

    Opt-in only: returns {} unless AZURE_REASONING_ENABLED is truthy. Degrades to
    {} (legacy) with a warning when the api-version is too old, so a misconfig
    never breaks model creation. Reasoning is applied to heavy roles only
    (primary/router); cheap light/queue_router classification stays untouched.
    """
    if os.getenv("AZURE_REASONING_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        return {}
    if _role_key(role) != "primary":
        return {}
    if not _api_version_supports_reasoning(api_version):
        logger.warning("ModelRegistry: AZURE_REASONING_ENABLED is on but api-version is too old — reasoning disabled (legacy path).")
        return {}
    effort = os.getenv("AZURE_REASONING_EFFORT", "medium").strip().lower() or "medium"
    return {"reasoning_effort": effort}


class ModelRegistry:
    """Singleton factory for LLM instances, keyed by role.

    Three modes — selected automatically based on what is set in config.env:

    ── Mode 1: Per-role hybrid (most flexible) ───────────────────────────────
      Activated when LLM_PRIMARY_PROVIDER (or any LLM_*_PROVIDER) is set.
      Each role independently chooses its provider and model.

      Required per role (replace PRIMARY with LIGHT or FALLBACK):
        LLM_PRIMARY_PROVIDER = azure | openai
        LLM_PRIMARY_MODEL    = <deployment name (azure) or model id (openai)>
        LLM_PRIMARY_BASE_URL = <only needed when provider=openai>

      Shared credentials:
        AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT   (for any azure role)
        OPENAI_API_KEY, OPENAI_TEMPERATURE             (for any openai role)

      Example — GPT-5 for heavy calls, Gemma for light/cheap calls:
        LLM_PRIMARY_PROVIDER=azure
        LLM_PRIMARY_MODEL=gpt-5.2-chat
        LLM_LIGHT_PROVIDER=openai
        LLM_LIGHT_MODEL=google/gemma-4-31B
        LLM_LIGHT_BASE_URL=http://10.232.180.7:8004/v1
        LLM_FALLBACK_PROVIDER=azure
        LLM_FALLBACK_MODEL=gpt-5-mini

    ── Mode 2: OpenAI-compatible only (all roles → same server) ──────────────
      Activated when OPENAI_BASE_URL is set (and no LLM_*_PROVIDER vars).

        OPENAI_BASE_URL   = http://10.232.180.7:8004/v1
        OPENAI_MODEL_NAME = google/gemma-4-31B
        OPENAI_API_KEY    = none
        OPENAI_TEMPERATURE = 0.7

      Optional per-role overrides (fall back to OPENAI_MODEL_NAME if not set):
        OPENAI_MODEL_NAME_LIGHT    = <lighter model id>
        OPENAI_MODEL_NAME_FALLBACK = <fallback model id>
        OPENAI_BASE_URL_LIGHT      = <different server for light role>
        OPENAI_BASE_URL_FALLBACK   = <different server for fallback role>

    ── Mode 3: Azure only (original behaviour, no new vars needed) ───────────
      Activated when neither LLM_*_PROVIDER nor OPENAI_BASE_URL is set.

        AZURE_OPENAI_API_KEY         = ...
        AZURE_OPENAI_ENDPOINT        = https://...
        AZURE_OPENAI_DEPLOYMENT      = gpt-5.2-chat
        AZURE_OPENAI_DEPLOYMENT_LIGHT    = gpt-5-nano
        AZURE_OPENAI_DEPLOYMENT_FALLBACK = gpt-5-mini

    ── Adding Anthropic or other providers ───────────────────────────────────
      Add a new branch in _build() for provider="anthropic" etc.
      No other file needs to change.

    Notes:
    - get("primary") raises ValueError when required env vars are missing.
    - Non-primary roles return None on failure (graceful fallback).
    - Instances are cached per role — repeated calls are free.
    """

    _instances: dict[str, Union[AzureChatOpenAI, ChatOpenAI, ChatVertexAIRaw, ChatAzureResponsesRaw, ChatAnthropicThinking]] = {}


    @classmethod
    def _build_azure(cls, role: str, deployment: str) -> Union[AzureChatOpenAI, ChatAzureResponsesRaw]:
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
        # Azure is public and reached via the corporate proxy → trust the proxy's
        # interception CA (PUBLIC_CA_BUNDLE), never the internal-only bundle.
        verify = _get_public_ssl_verify()
        http_client = _make_httpx_client(verify)
        # Async paths need their own httpx client; the SDK default ignores `verify` (mirrors _build_openai).
        http_async_client = _make_async_httpx_client(verify)
        reasoning_kwargs = _reasoning_kwargs_for(role, api_version)
        if reasoning_kwargs and reasoning_replay_enabled("azure"):
            cap = get_reasoning_capability("azure", deployment)
            if cap.supports_reasoning and cap.replayable and _api_version_supports_reasoning(api_version):
                try:
                    llm = ChatAzureResponsesRaw(
                        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT") or "",
                        api_key=os.getenv("AZURE_OPENAI_API_KEY") or "",
                        api_version=api_version,
                        azure_deployment=deployment,
                        reasoning_effort=str(reasoning_kwargs.get("reasoning_effort") or cap.default_effort),
                        http_client=http_client,
                    )
                    logger.debug("ModelRegistry: '%s' reasoning replay enabled [azure/responses]", role)
                    return llm
                except Exception as exc:
                    logger.warning("ModelRegistry: Azure Responses reasoning replay unavailable — falling back to AzureChatOpenAI.")
                    logger.debug("ModelRegistry reasoning replay error details", exc_info=True)
        kwargs: dict = dict(
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version=api_version,
            azure_deployment=deployment,
            http_client=http_client,
            http_async_client=http_async_client,
        )
        if reasoning_kwargs:
            # Pass reasoning_effort as a constructor arg; fall back to the legacy build if the installed langchain_openai rejects it.
            try:
                llm = AzureChatOpenAI(**kwargs, **reasoning_kwargs)
                logger.debug("ModelRegistry: '%s' reasoning enabled", role)
                return llm
            except TypeError as exc:
                logger.warning("ModelRegistry: reasoning kwargs not accepted by AzureChatOpenAI — building legacy model.")
                logger.debug("ModelRegistry reasoning kwargs error details", exc_info=True)
        return AzureChatOpenAI(**kwargs)

    @classmethod
    def _build_openai(cls, model: str, base_url: str) -> ChatOpenAI:
        # OpenAI-compatible endpoints here are the internal, direct-reached models
        # (e.g. self-hosted Gemma/vLLM) → verify against the internal CA chain.
        verify = _get_internal_ssl_verify()
        return ChatOpenAI(
            base_url=base_url,
            model=model,
            api_key=os.getenv("OPENAI_API_KEY", "none"),
            temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.7")),
            http_client=_make_httpx_client(verify),
            http_async_client=_make_async_httpx_client(verify),
        )

    @classmethod
    def _build_vertex(cls, model: str) -> ChatVertexAIRaw:
        """Build a Vertex AI Gemini chat model using service-account auth.

        Reads from env:
            VERTEX_PROJECT             (required)   GCP project id
            VERTEX_LOCATION            (default us-central1)
            VERTEX_SA_KEY_PATH         (required)   absolute path to SA JSON
            VERTEX_CA_BUNDLE           (optional)   PEM bundle for corporate SSL trust
            VERTEX_TEMPERATURE         (default 0.7)
            VERTEX_IMAGE_OUTPUT_DIR    (auto-detect)  Filesystem dir for file-backed image storage
            VERTEX_IMAGE_URL_PREFIX    (/static/generated_images)  URL prefix served by static handler
            VERTEX_IMAGE_RETENTION_DAYS (default 7)  Lazy cleanup threshold
        """
        from .vertex_chat import _autodetect_image_dir

        project = os.getenv("VERTEX_PROJECT")
        sa_key_path = os.getenv("VERTEX_SA_KEY_PATH")
        if not project:
            raise ValueError("VERTEX_PROJECT not set in config.env (required for provider=vertex)")
        if not sa_key_path:
            raise ValueError("VERTEX_SA_KEY_PATH not set in config.env (required for provider=vertex)")

        # Output dir: VERTEX_IMAGE_OUTPUT_DIR, else auto-detect static/generated_images, else None (inline data URLs).
        image_output_dir = os.getenv("VERTEX_IMAGE_OUTPUT_DIR")
        if not image_output_dir:
            auto = _autodetect_image_dir()
            if auto is not None:
                image_output_dir = str(auto)

        return ChatVertexAIRaw(
            project=project,
            location=os.getenv("VERTEX_LOCATION", "us-central1"),
            model=model,
            sa_key_path=sa_key_path,
            ca_bundle_path=os.getenv("VERTEX_CA_BUNDLE") or None,
            temperature=float(os.getenv("VERTEX_TEMPERATURE", "0.7")),
            image_output_dir=image_output_dir,
            image_url_prefix=os.getenv("VERTEX_IMAGE_URL_PREFIX", "/static/generated_images"),
            image_retention_days=int(os.getenv("VERTEX_IMAGE_RETENTION_DAYS", "7")),
            thinking_enabled=reasoning_replay_enabled("vertex"),
            thinking_budget=int(os.getenv("VERTEX_REASONING_BUDGET"))
            if os.getenv("VERTEX_REASONING_BUDGET") else None,
        )

    @classmethod
    def _build_anthropic(cls, model: str) -> ChatAnthropicThinking:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set in config.env (required for provider=anthropic)")
        cap = get_reasoning_capability("anthropic", model)
        thinking_enabled = reasoning_replay_enabled("anthropic") and cap.supports_reasoning
        budget_raw = os.getenv("ANTHROPIC_REASONING_BUDGET")
        return ChatAnthropicThinking(
            model=model,
            api_key=api_key,
            api_url=os.getenv("ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages"),
            anthropic_version=os.getenv("ANTHROPIC_API_VERSION", "2023-06-01"),
            max_tokens=int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096")),
            thinking_enabled=thinking_enabled,
            thinking_budget_tokens=int(budget_raw) if budget_raw else None,
            thinking_effort=os.getenv("ANTHROPIC_REASONING_EFFORT", cap.default_effort),
            ca_bundle_path=os.getenv("ANTHROPIC_CA_BUNDLE") or None,
        )


    @classmethod
    def get(cls, role: str = "primary") -> Optional[Union[AzureChatOpenAI, ChatOpenAI, ChatVertexAIRaw, ChatAzureResponsesRaw, ChatAnthropicThinking]]:
        """Get or create an LLM for the given role."""
        if role in cls._instances:
            return cls._instances[role]

        try:
            llm = cls._create(role)
        except Exception as e:
            if role == "primary":
                raise
            logger.warning("ModelRegistry: '%s' LLM creation failed", role)
            logger.debug("ModelRegistry creation error details", exc_info=True)
            return None

        if llm is not None:
            cls._instances[role] = llm
        return llm

    @classmethod
    def _create_for_provider(cls, provider: str, role: str, key: str):
        """Build an LLM for an explicitly selected provider (runtime switch),
        resolving the per-role model from that provider's own env vars. Returns
        None for a non-primary role the provider can't satisfy (same contract as
        _create); raises for a missing primary model so the error surfaces."""
        if provider == "anthropic":
            anthropic_role_env = {
                "primary": "ANTHROPIC_MODEL_NAME",
                "light": "ANTHROPIC_MODEL_NAME_LIGHT",
                "fallback": "ANTHROPIC_MODEL_NAME_FALLBACK",
            }
            model = (
                os.getenv(f"LLM_{key.upper()}_MODEL")
                or os.getenv(anthropic_role_env.get(key, "ANTHROPIC_MODEL_NAME"))
                or os.getenv("ANTHROPIC_MODEL_NAME")
            )
            if not model:
                if role == "primary":
                    raise ValueError("ANTHROPIC_MODEL_NAME not set (required for provider=anthropic)")
                return None
            return cls._build_anthropic(model)

        if provider == "azure":
            primary_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
            env_var = AZURE_ROLE_ENV_MAP.get(role, "AZURE_OPENAI_DEPLOYMENT")
            deployment = os.getenv(env_var, primary_deployment)
            if not deployment:
                if role == "primary":
                    raise ValueError("AZURE_OPENAI_DEPLOYMENT not set (required for provider=azure)")
                return None
            return cls._build_azure(role, deployment)

        if provider == "openai":
            openai_model_env = {"light": "OPENAI_MODEL_NAME_LIGHT", "fallback": "OPENAI_MODEL_NAME_FALLBACK"}
            openai_url_env = {"light": "OPENAI_BASE_URL_LIGHT", "fallback": "OPENAI_BASE_URL_FALLBACK"}
            model = os.getenv(openai_model_env.get(key, ""), "") or os.getenv("OPENAI_MODEL_NAME", "")
            base_url = os.getenv(openai_url_env.get(key, ""), "") or os.getenv("OPENAI_BASE_URL", "")
            if not model or not base_url:
                if role == "primary":
                    raise ValueError("OPENAI_MODEL_NAME + OPENAI_BASE_URL required (provider=openai)")
                return None
            return cls._build_openai(model, base_url)

        if provider == "vertex":
            model = os.getenv(f"LLM_{key.upper()}_MODEL") or os.getenv("VERTEX_MODEL_NAME", "")
            if not model:
                if role == "primary":
                    raise ValueError("VERTEX_MODEL_NAME not set (required for provider=vertex)")
                return None
            return cls._build_vertex(model)

        return None

    @classmethod
    def _create(cls, role: str) -> Optional[Union[AzureChatOpenAI, ChatOpenAI, ChatVertexAIRaw, ChatAzureResponsesRaw, ChatAnthropicThinking]]:
        key = _role_key(role)   # router→primary, queue_router→light

        # A concrete LLM_ACTIVE_PROVIDER overrides the static Mode 1/2/3 precedence below.
        active = (os.getenv("LLM_ACTIVE_PROVIDER") or "").strip().lower()
        if active in ("azure", "openai", "vertex", "anthropic"):
            return cls._create_for_provider(active, role, key)

        # Mode 1: per-role hybrid
        provider = os.getenv(f"LLM_{key.upper()}_PROVIDER")
        if provider:
            provider = provider.lower()
            model    = os.getenv(f"LLM_{key.upper()}_MODEL", "")
            base_url = os.getenv(f"LLM_{key.upper()}_BASE_URL", "")

            if not model:
                if role == "primary":
                    raise ValueError(f"LLM_{key.upper()}_MODEL not set in config.env")
                return None

            if provider == "azure":
                llm = cls._build_azure(role, model)
                logger.debug("ModelRegistry: '%s' created [azure/hybrid]", role)
                return llm

            if provider == "openai":
                if not base_url:
                    raise ValueError(f"LLM_{key.upper()}_BASE_URL required when provider=openai")
                llm = cls._build_openai(model, base_url)
                logger.debug("ModelRegistry: '%s' created [openai/hybrid]", role)
                return llm

            if provider == "vertex":
                llm = cls._build_vertex(model)
                logger.debug("ModelRegistry: '%s' created [vertex/hybrid]", role)
                return llm

            if provider == "anthropic":
                llm = cls._build_anthropic(model)
                logger.debug("ModelRegistry: '%s' created [anthropic/hybrid]", role)
                return llm

            raise ValueError(f"Unknown provider '{provider}' for role '{role}'. Use: azure | openai | vertex | anthropic")

        # Mode 2: OpenAI-compatible (all roles, same server)
        if os.getenv("OPENAI_BASE_URL"):
            openai_model_env = {
                "light":    "OPENAI_MODEL_NAME_LIGHT",
                "fallback": "OPENAI_MODEL_NAME_FALLBACK",
            }
            openai_url_env = {
                "light":    "OPENAI_BASE_URL_LIGHT",
                "fallback": "OPENAI_BASE_URL_FALLBACK",
            }
            default_model = os.getenv("OPENAI_MODEL_NAME", "")
            default_url   = os.getenv("OPENAI_BASE_URL", "")
            model    = os.getenv(openai_model_env.get(key, ""), "") or default_model
            base_url = os.getenv(openai_url_env.get(key, ""), "") or default_url

            if not model:
                if role == "primary":
                    raise ValueError("OPENAI_MODEL_NAME not set in config.env")
                return None

            llm = cls._build_openai(model, base_url)
            logger.debug("ModelRegistry: '%s' created [openai-compat]", role)
            return llm

        # Mode 3: Azure only
        api_key  = os.getenv("AZURE_OPENAI_API_KEY")
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        if not api_key or not endpoint:
            if role == "primary":
                raise ValueError(
                    "No LLM configured. Options:\n"
                    "  Hybrid:       set LLM_PRIMARY_PROVIDER in config.env\n"
                    "  OpenAI-compat: set OPENAI_BASE_URL in config.env\n"
                    "  Azure:        set AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT"
                )
            return None

        primary_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
        env_var    = AZURE_ROLE_ENV_MAP.get(role, "AZURE_OPENAI_DEPLOYMENT")
        deployment = os.getenv(env_var, primary_deployment)
        if not deployment:
            return None

        llm = cls._build_azure(role, deployment)
        logger.debug("ModelRegistry: '%s' created [azure]", role)
        return llm

    @classmethod
    def reset(cls):
        """Clear cached instances (useful for testing or env reload)."""
        cls._instances.clear()


    @classmethod
    def get_active_provider(cls) -> str:
        """Return effective active provider: 'openai', 'azure', 'anthropic', 'vertex', or '' (auto)."""
        v = (os.getenv("LLM_ACTIVE_PROVIDER") or os.getenv("LLM_PRIMARY_PROVIDER") or "").strip().lower()
        return v if v in ("openai", "azure", "anthropic", "vertex") else ""

    @classmethod
    def set_active_provider(cls, provider: str) -> None:
        """Flip the active provider at runtime; clears cached LLM instances.

        Caller is responsible for verifying that the chosen provider is
        actually configured (env vars present). Pass "" to clear and let
        auto-detection run.
        """
        v = (provider or "").strip().lower()
        if v not in ("", "openai", "azure", "anthropic", "vertex"):
            raise ValueError(f"Unknown provider '{provider}'. Use: openai | azure | anthropic | vertex | ''")
        os.environ["LLM_ACTIVE_PROVIDER"] = v
        cls.reset()

    @classmethod
    def list_providers(cls) -> dict:
        """Report which providers are configured and which is currently active."""
        openai_ready = bool(os.getenv("OPENAI_BASE_URL") and os.getenv("OPENAI_MODEL_NAME"))
        azure_ready = bool(os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_DEPLOYMENT"))
        anthropic_ready = bool(os.getenv("ANTHROPIC_API_KEY"))
        vertex_ready = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("VERTEX_PROJECT_ID"))

        active = cls.get_active_provider()
        if not active:
            active = "openai" if openai_ready else ("azure" if azure_ready else ("anthropic" if anthropic_ready else ("vertex" if vertex_ready else "")))

        return {
            "active": active,
            "providers": [
                {
                    "id": "openai",
                    "label": "Gemma / OpenAI-compatible (vLLM)",
                    "configured": openai_ready,
                    "model": os.getenv("OPENAI_MODEL_NAME", ""),
                    "endpoint": os.getenv("OPENAI_BASE_URL", ""),
                },
                {
                    "id": "azure",
                    "label": "Azure OpenAI",
                    "configured": azure_ready,
                    "model": os.getenv("AZURE_OPENAI_DEPLOYMENT", ""),
                    "endpoint": os.getenv("AZURE_OPENAI_ENDPOINT", ""),
                },
                {
                    "id": "anthropic",
                    "label": "Anthropic Claude",
                    "configured": anthropic_ready,
                    "model": os.getenv("LLM_PRIMARY_MODEL", "claude-haiku-4-5-20251001"),
                    "endpoint": "api.anthropic.com",
                },
                {
                    "id": "vertex",
                    "label": "Google Vertex AI",
                    "configured": vertex_ready,
                    "model": os.getenv("VERTEX_MODEL_NAME", ""),
                    "endpoint": os.getenv("VERTEX_LOCATION", ""),
                },
            ],
        }


def llm_model_name(llm: object) -> str:
    """Best-effort model/deployment name for logging, across all wrapper types.

    Covers Azure (azure_deployment / deployment_name), OpenAI-compat (model_name /
    model), Vertex and Anthropic. Falls back to the class name so logs are never
    blank when the model is actually set.
    """
    if llm is None:
        return ""
    for attr in ("azure_deployment", "deployment_name", "model_name", "model"):
        val = getattr(llm, attr, None)
        if val:
            return str(val)
    return type(llm).__name__


def llm_base_url(llm: object) -> str:
    """Best-effort base/endpoint for logging, across all wrapper types.

    Azure -> azure_endpoint; OpenAI-compat / local (e.g. Gemma) -> openai_api_base /
    base_url; Anthropic/Claude -> api_url. Vertex has no URL, so fall back to
    'vertex:{location}/{project}' which is what actually identifies the endpoint.
    """
    if llm is None:
        return ""
    for attr in ("azure_endpoint", "openai_api_base", "base_url", "api_url", "api_base", "endpoint"):
        val = getattr(llm, attr, None)
        if val:
            return str(val)
    # Vertex AI: no single base URL -- identify by region/project instead.
    location = getattr(llm, "location", None)
    if location:
        project = getattr(llm, "project", None)
        return f"vertex:{location}/{project}" if project else f"vertex:{location}"
    return ""
