"""
Standalone Token & Cost Tracker for LiteLLM Proxy and Direct Azure OpenAI

This module provides token usage tracking and cost calculation for:
- LiteLLM proxy server (independent guardrail/moderation server)
- Direct Azure OpenAI API calls (without proxy)

It integrates with the existing database schema:
- token_usage_logs table (for logging)
- model_costs table (for cost lookup)

Features:
- Extracts tokens from both LiteLLM and Azure OpenAI responses
- Calculates costs from model_costs table  
- Logs to token_usage_logs table
- Background task to update model_costs from LiteLLM's API
- Works regardless of USE_LITELLM_PROXY_FLAG setting

Usage in src/models/guardrail_aware_llm.py or similar:
    from litellm_standalone_tracker import log_token_usage, is_tracker_enabled
    
    if is_tracker_enabled():
        await log_token_usage(
            model_name="gpt-4o",
            prompt_tokens=150,
            completion_tokens=300,
            total_tokens=450,
            agent_id=123
        )
"""

import os
import asyncio
import asyncpg
import litellm
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from contextlib import asynccontextmanager
import logging
from enum import Enum

# Use telemetry_wrapper if available, else fallback to standard logging
try:
    from telemetry_wrapper import logger as log
except ImportError:
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger(__name__)


# ==========================================
# CALL CATEGORIZATION ENUMS
# ==========================================

class LLMCallCategory(str, Enum):
    """Main categories of LLM calls for tracking and filtering"""
    AGENT_INFERENCE = "agent_inference"           # Agent chat/reasoning
    TOOL_OPERATION = "tool_operation"             # Tool validation/execution
    EVALUATION = "evaluation"                      # Response evaluation
    PROMPT_GENERATION = "prompt_generation"        # Dynamic prompt creation
    FILE_ANALYSIS = "file_analysis"                # File/document processing
    RAG_QUERY = "rag_query"                       # Knowledge base queries
    GUARDRAIL = "guardrail"                        # Safety/moderation checks
    CONVERSATION = "conversation"                  # Welcome msgs, summaries
    OTHER = "other"                                # Miscellaneous

class AgentType(str, Enum):
    """Types of agents for agent_inference calls"""
    REACT = "react"
    META = "meta"
    PLANNER_EXECUTOR = "planner_executor"
    PLANNER_EXECUTOR_CRITIC = "planner_executor_critic"
    HYBRID = "hybrid"
    CUSTOM = "custom"

class ToolOperation(str, Enum):
    """Types of tool operations"""
    PARAMETER_VALIDATION = "parameter_validation"
    EXECUTION_VALIDATION = "execution_validation"
    JSON_VALIDATION = "json_validation"
    AUTO_FIX = "auto_fix"
    EXECUTION = "execution"

class EvaluationType(str, Enum):
    """Types of evaluations"""
    GROUND_TRUTH = "ground_truth"
    RESPONSE_QUALITY = "response_quality"
    METRIC_CALCULATION = "metric_calculation"
    PREFERENCE_ANALYSIS = "preference_analysis"


# ==========================================
# CONFIGURATION
# ==========================================

class TrackerConfig:
    """Configuration for standalone token tracker"""
    
    def __init__(self):
        self.enabled = True
        
        # Database configuration
        self.db_host = os.getenv("POSTGRESQL_HOST", "localhost")
        self.db_port = int(os.getenv("POSTGRESQL_PORT", "5432"))
        self.db_user = os.getenv("POSTGRESQL_USER", "postgres")
        self.db_password = os.getenv("POSTGRESQL_PASSWORD", "postgres")
        self.db_name = os.getenv("DATABASE", "agentic_workflow_as_service_database")
        
        # Connection pool settings
        pool_size = os.getenv("CONNECTION_POOL_SIZE", "low").lower()
        pool_configs = {
            "low": {"min_size": 2, "max_size": 5, "max_queries": 50000, "max_inactive_connection_lifetime": 300.0},
            "medium": {"min_size": 5, "max_size": 10, "max_queries": 50000, "max_inactive_connection_lifetime": 300.0},
            "high": {"min_size": 10, "max_size": 20, "max_queries": 50000, "max_inactive_connection_lifetime": 300.0}
        }
        self.pool_config = pool_configs.get(pool_size, pool_configs["low"])
        
        # Timeout settings
        self.connection_timeout = float(os.getenv("DB_CONNECTION_TIMEOUT", "30.0"))
        
        # LiteLLM URL for cost updates
        self.litellm_url = os.getenv("LITELLM_URL", "http://localhost:8080")
        
        log.info(f"Standalone Tracker Config: db={self.db_name}, pool={pool_size}")


# Global configuration instance
_config = TrackerConfig()



def build_model_mapping_from_env() -> Dict[str, Tuple[str, str]]:
    """
    Build MODEL_MAPPING by scanning the process environment for every
    variable whose name ends with ``_MODELS``.

    For each ``<PREFIX>_MODELS`` that has a non-empty value:
      1. Split on commas to get individual model names.
      2. Look for ``<PREFIX>_API_VERSION`` — used for exact Azure dated-key
         matching in the cost map. If absent the version is empty and the
         lookup automatically falls back to provider-agnostic matching.
      3. Register each model in the mapping.



    Returns:
        Dict[model_name, (model_name_in_cost_map, api_version)]
    """
    mapping: Dict[str, Tuple[str, str]] = {}

    for key, value in os.environ.items():
        if not key.endswith("_MODELS"):
            continue

        models_str = value.strip()
        if not models_str:
            continue  # var present but empty — skip this group

        # Derive matching version var: <PREFIX>_API_VERSION
        prefix = key[: -len("_MODELS")]
        version_key = f"{prefix}_API_VERSION"
        api_version = os.getenv(version_key, "").strip()

        for model in (m.strip() for m in models_str.split(",") if m.strip()):
            mapping[model] = (model, api_version)
            log.info(
                f"Model registered: {model!r} "
                f"(from {key}, version_env={version_key}, "
                f"api_version={api_version or 'n/a'})"
            )

    if mapping:
        log.info(f"MODEL_MAPPING built: {len(mapping)} model(s) from environment")
    else:
        log.warning(
            "MODEL_MAPPING is empty — no *_MODELS environment variables found "
            "with non-empty values. Cost tracking will be skipped."
        )

    return mapping


PREFERRED_AZURE_SCOPE = None


# ==========================================
# BASE MODEL MAPPING FOR CUSTOM MODELS
# ==========================================

def load_base_model_mapping() -> Dict[str, str]:
    """
    Load base model mapping from environment variables.
    
    Environment format:
        BASE_MODEL_MAPPING=gpt-5.1-chat=gpt-5-chat,gpt-5.2-preview=gpt-5-chat,custom-v2=gpt-4o
    
    Returns:
        Dict mapping derived model names to their base models
        Example: {"gpt-5.1-chat": "gpt-5-chat", "custom-v2": "gpt-4o"}
    """
    mapping = {}
    env_value = os.getenv("BASE_MODEL_MAPPING", "").strip()
    
    if not env_value:
        log.info("📋 No BASE_MODEL_MAPPING configured - using auto-extraction only")
        return mapping
    
    for pair in env_value.split(","):
        pair = pair.strip()
        if "=" not in pair:
            continue
        
        derived, base = pair.split("=", 1)
        derived = derived.strip()
        base = base.strip()
        
        if derived and base:
            mapping[derived] = base
            log.info(f"🔗 Base model mapping: {derived!r} -> {base!r}")
    
    log.info(f"✅ Loaded {len(mapping)} base model mappings from environment")
    return mapping


import re

def extract_base_model(model_name: str) -> str:
    """
    Extract base model name from version-specific model strings.
    
    Examples:
        'gpt-4o-2024-11-20' -> 'gpt-4o'
        'gpt-4-turbo-2024-04-09' -> 'gpt-4-turbo'
        'gpt-35-turbo-16k' -> 'gpt-35-turbo-16k'
        'azure/gpt-4o-2024-11-20' -> 'gpt-4o'
        'gpt-5.1-chat' -> 'gpt-5.1-chat' (no change if no date pattern)
    
    Returns:
        Base model name for cost lookup
    """
    # Remove azure/ prefix if present
    clean_name = model_name.replace('azure/', '')
    
    # Pattern: Remove date suffixes like -2024-11-20, -20241120, etc.
    base_model = re.sub(r'-\d{4}-\d{2}-\d{2}$', '', clean_name)
    base_model = re.sub(r'-\d{8}$', '', base_model)
    
    # Pattern: Remove version numbers like -0125, -1106, etc. (4 digits)
    base_model = re.sub(r'-\d{4}$', '', base_model)
    
    if base_model != clean_name:
        log.debug(f"🔍 Extracted base model '{base_model}' from '{model_name}'")
    
    return base_model


# Load base model mapping at module initialization
_BASE_MODEL_MAPPING = load_base_model_mapping()


# ==========================================
# COST MAP HELPERS (from cost_map.py)
# ==========================================

def _azure_tail(key: str) -> Optional[str]:
    """Extract tail from azure/ prefixed key"""
    if not key.startswith("azure/"):
        return None
    return key.split("/")[-1]


def _azure_scope(key: str) -> Optional[str]:
    """Extract scope from azure/ prefixed key"""
    if not key.startswith("azure/"):
        return None
    parts = key.split("/")
    return parts[1] if len(parts) >= 3 else None


def _extract_costs(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "input_cost_per_token": entry.get("input_cost_per_token"),
        "output_cost_per_token": entry.get("output_cost_per_token"),
        "cache_read_input_token_cost": entry.get("cache_read_input_token_cost"),
    }


def select_exact_azure_dated_keys(cost_map, base, date, preferred_scope):
    """Find the cost-map entry whose key or Azure tail matches exactly ``{base}-{date}``.

    Lookup order:
    1. If ``preferred_scope`` is set (Azure deployment): try Azure scoped key first
       (``azure/{scope}/{base}-{date}``), then any Azure key, then bare key.
    2. If no scope preference (OpenAI / non-Azure): try bare key first
       (``{base}-{date}``), then fall back to any Azure key — so that plain
       OpenAI dated models are not silently mis-priced using Azure rates.
    """
    target = f"{base}-{date}"
    azure_matches = [(k, v) for k, v in cost_map.items() if _azure_tail(k) == target]

    if preferred_scope:
        # Azure deployment — honour scope preference, Azure key takes priority
        scoped = [(k, v) for k, v in azure_matches if _azure_scope(k) == preferred_scope]
        if scoped:
            return scoped[0]
        if azure_matches:
            return sorted(azure_matches, key=lambda x: _azure_scope(x[0]) is None)[0]
        # Fall through to bare key as last resort
        if target in cost_map:
            return (target, cost_map[target])
        return None

    # No scope preference — bare key first (OpenAI / non-Azure path)
    if target in cost_map:
        return (target, cost_map[target])

    if not azure_matches:
        return None

    # Prefer scoped keys over unscoped; sort for determinism within each group
    return sorted(azure_matches, key=lambda x: _azure_scope(x[0]) is None)[0]


def fallback_if_not_found(cost_map, base):
    """
    Fallback cost-map lookup when the exact dated key is not found.

    Search order:
    1. Direct exact key match (e.g. ``gpt-4o``, ``gemini-1.5-flash``).
    2. Provider-prefix stripping: if ``base`` contains ``/`` (e.g.
       ``vertex_ai/gemini-1.5-pro``), strip the prefix and restart lookup
       on the bare name so those models are never silently lost.
    3. Azure key whose tail is exactly ``base`` (undated) — exact preferred.
    4. Azure key whose tail starts with ``base-`` (any dated version) — latest.
       Within steps 3-4 PREFERRED_AZURE_SCOPE is honoured when set.
    5. Non-Azure key whose last segment is exactly ``base`` — exact preferred.
    6. Non-Azure key whose last segment starts with ``base-`` (dated variants).
       Steps 5-6 are tried only when no Azure match is found, avoiding the
       previous bug where OpenAI bare keys silently resolved to Azure entries.
    7. Returns None if nothing matches.
    """
    # Guard — never match on an empty model name
    if not base:
        return None

    # Step 1 — direct exact key
    if base in cost_map:
        return (base, cost_map[base])

    # Step 2 — provider-prefixed name (e.g. "vertex_ai/gemini-1.5-pro")
    if "/" in base:
        bare = base.split("/")[-1]
        result = fallback_if_not_found(cost_map, bare)
        if result:
            return result
        return None  # avoid further matching with the slash-containing base

    # Steps 3-4 — Azure tail matching (exact first, then prefix)
    azure_exact = [
        (k, v) for k, v in cost_map.items() if _azure_tail(k) == base
    ]
    azure_prefix = [
        (k, v) for k, v in cost_map.items()
        if (t := _azure_tail(k)) and t.startswith(base + "-")
    ]
    azure_matches = azure_exact if azure_exact else azure_prefix

    if azure_matches:
        if PREFERRED_AZURE_SCOPE:
            scoped = [(k, v) for k, v in azure_matches if _azure_scope(k) == PREFERRED_AZURE_SCOPE]
            if scoped:
                return sorted(scoped, reverse=True)[0]
        return sorted(azure_matches, reverse=True)[0]

    # Steps 5-6 — any non-Azure provider, exact last-segment match first
    anyprov_exact = [
        (k, v) for k, v in cost_map.items()
        if not k.startswith("azure/") and k.split("/")[-1] == base
    ]
    if anyprov_exact:
        return sorted(anyprov_exact, reverse=True)[0]

    anyprov_prefix = [
        (k, v) for k, v in cost_map.items()
        if not k.startswith("azure/") and k.split("/")[-1].startswith(base + "-")
    ]
    if anyprov_prefix:
        return sorted(anyprov_prefix, reverse=True)[0]

    return None


def map_models_to_costs(cost_map, model_mapping, preferred_scope):
    """Map model names to their costs using the MODEL_MAPPING.

    Lookup order for each model:
    1. Exact dated key — bare (e.g. ``gpt-4o-2024-11-20``) or Azure-scoped
       (e.g. ``azure/{scope}/gpt-4o-2024-11-20``) — only when api_version set.
    2. Fallback: direct exact key match in cost_map (e.g. ``gpt-4o``).
    3. Fallback: provider-prefix stripped if model_name contains ``/``.
    4. Fallback: Azure key matching base name — exact tail first, then dated.
    5. Fallback: non-Azure key — exact last segment first, then dated prefix.
    6. If nothing found: costs stored as None (no charge calculated).
    """
    results = {}

    for name, (model_name, model_version) in model_mapping.items():
        picked = None

        # Step 1 — exact dated lookup (skip entirely when no version is set)
        if model_version:
            picked = select_exact_azure_dated_keys(cost_map, model_name, model_version, preferred_scope)
            if picked:
                log.debug(f"Cost found via exact dated key for {name!r}: {picked[0]}")

        # Step 2 & 3 — fallback to base model (any date or undated)
        if picked is None:
            picked = fallback_if_not_found(cost_map, model_name)
            if picked:
                log.debug(
                    f"Cost found via fallback for {name!r} "
                    f"(requested version={model_version or 'n/a'}): {picked[0]}"
                )

        if picked:
            k, entry = picked
            results[name] = {
                "model_name": model_name,
                "model_version": model_version,
                "provider_key": k,
                **_extract_costs(entry)
            }
        else:
            # Try BASE_MODEL_MAPPING before giving up
            if name in _BASE_MODEL_MAPPING:
                base_model = _BASE_MODEL_MAPPING[name]
                log.info(f"🔍 Trying BASE_MODEL_MAPPING: {name!r} -> {base_model!r}")
                
                # Try to find cost for base model
                base_picked = fallback_if_not_found(cost_map, base_model)
                if base_picked:
                    k, entry = base_picked
                    log.info(f"✅ Cost found via BASE_MODEL_MAPPING: {name!r} -> {base_model!r}")
                    results[name] = {
                        "model_name": base_model,  # Use base model name for DB storage
                        "model_version": model_version,
                        "provider_key": k,
                        **_extract_costs(entry)
                    }
                    continue
            
            # No cost found anywhere - warn and store zeros
            log.warning(f"⚠️ No cost entry found for model {name!r} ({model_name}) — costs will be zero")
            results[name] = {
                "model_name": model_name,
                "model_version": model_version,
                "provider_key": None,
                "input_cost_per_token": None,
                "output_cost_per_token": None,
                "cache_read_input_token_cost": None,
            }

    return results


# ==========================================
# DATABASE CONNECTION POOL
# ==========================================

class DatabasePool:
    """Manages PostgreSQL connection pool for token logging"""
    
    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None
        self._initialized = False
        self._lock = asyncio.Lock()
    
    async def initialize(self):
        """Initialize the connection pool"""
        if not _config.enabled:
            return
        
        async with self._lock:
            if self._initialized:
                return
            
            try:
                self._pool = await asyncpg.create_pool(
                    host=_config.db_host,
                    port=_config.db_port,
                    user=_config.db_user,
                    password=_config.db_password,
                    database=_config.db_name,
                    min_size=_config.pool_config["min_size"],
                    max_size=_config.pool_config["max_size"],
                    max_queries=_config.pool_config["max_queries"],
                    max_inactive_connection_lifetime=_config.pool_config["max_inactive_connection_lifetime"],
                    timeout=_config.connection_timeout,
                    command_timeout=60.0
                )
                self._initialized = True
                log.info(f"✅ Standalone Tracker database pool initialized: {_config.db_host}:{_config.db_port}/{_config.db_name}")
                
                # Ensure tables exist (they should already exist, just verify)
                await self._ensure_tables_exist()
                
            except Exception as e:
                log.error(f"❌ Failed to initialize Standalone Tracker database pool: {e}", exc_info=True)
                self._initialized = False
    
    async def _ensure_tables_exist(self):
        """
        Verify tables exist (DO NOT modify existing schema)
        Tables should already exist: token_usage_logs, model_costs
        """
        try:
            async with self._pool.acquire() as conn:
                # Just verify tables exist
                tables = await conn.fetch("""
                    SELECT table_name FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name IN ('token_usage_logs', 'model_costs')
                """)
                
                table_names = [row['table_name'] for row in tables]
                
                if 'token_usage_logs' in table_names:
                    log.info("✅ Standalone Tracker: token_usage_logs table exists")
                else:
                    log.warning("⚠️ Standalone Tracker: token_usage_logs table not found! Please create it first.")
                
                if 'model_costs' in table_names:
                    log.info("✅ Standalone Tracker: model_costs table exists")
                else:
                    log.warning("⚠️ Standalone Tracker: model_costs table not found! Please create it first.")
                    
        except Exception as e:
            log.error(f"❌ Failed to verify tables: {e}", exc_info=True)
    
    @asynccontextmanager
    async def acquire(self):
        """Acquire a connection from the pool"""
        if not self._initialized:
            await self.initialize()
        
        if not self._pool:
            raise RuntimeError("Database pool not initialized")
        
        async with self._pool.acquire() as conn:
            yield conn
    
    async def close(self):
        """Close the connection pool"""
        if self._pool:
            await self._pool.close()
            self._initialized = False
            log.info("🔒 Standalone Tracker database pool closed")


# Global database pool instance
_db_pool = DatabasePool()


# ==========================================
# MODEL COST SERVICE
# ==========================================

class ModelCostService:
    """Service for retrieving and updating model costs"""
    
    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._initialized = False
        self._lock = asyncio.Lock()
        self._last_update: Optional[datetime] = None
    
    async def initialize(self):
        """Initialize cost service"""
        if not _config.enabled:
            return
        
        async with self._lock:
            if self._initialized:
                return
            
            try:
                # Load costs from database into cache
                await self._load_costs_from_db()
                self._initialized = True
                log.info(f"✅ Model Cost Service initialized with {len(self._cache)} models")
            except Exception as e:
                log.error(f"❌ Failed to initialize Model Cost Service: {e}", exc_info=True)
                self._initialized = False
    
    async def _load_costs_from_db(self):
        """Load costs from model_costs table into cache"""
        try:
            async with _db_pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM model_costs")
                
                for row in rows:
                    self._cache[row['name']] = {
                        'model_name': row['model_name'],
                        'model_version': row['model_version'],
                        'provider_key': row['provider_key'],
                        # Cast NUMERIC columns to float so downstream arithmetic
                        # produces float (not Decimal) and json.dumps never fails.
                        'input_cost_per_token': float(row['input_cost_per_token'] or 0),
                        'output_cost_per_token': float(row['output_cost_per_token'] or 0),
                        'cache_read_input_token_cost': float(row['cache_read_input_token_cost'] or 0),
                    }
                
                self._last_update = datetime.now()
                log.info(f"📊 Loaded {len(self._cache)} model costs from database")
                
        except Exception as e:
            log.error(f"❌ Failed to load costs from database: {e}", exc_info=True)
    
    async def fetch_and_update_costs_from_litellm(self):
        """Fetch costs from LiteLLM API and update database"""
        try:
            log.info("🔄 Fetching model costs from LiteLLM...")
            
            # Fetch from LiteLLM
            cost_map = litellm.get_model_cost_map(url=_config.litellm_url)
            log.info(f"✓ Retrieved {len(cost_map)} cost entries from LiteLLM")
            
            # Rebuild mapping fresh so any newly added env-var models are included
            current_mapping = build_model_mapping_from_env()
            if not current_mapping:
                log.warning("⚠️ No models in MODEL_MAPPING — skipping cost update")
                return

            # Map to our models
            results = map_models_to_costs(cost_map, current_mapping, PREFERRED_AZURE_SCOPE)
            
            # Save to database
            async with _db_pool.acquire() as conn:
                saved_count = 0
                updated_count = 0
                
                for name, info in results.items():
                    try:
                        # Check if exists
                        existing = await conn.fetchrow("SELECT id FROM model_costs WHERE name = $1", name)
                        
                        if existing:
                            # Update
                            await conn.execute("""
                                UPDATE model_costs 
                                SET model_name = $2, model_version = $3, provider_key = $4,
                                    input_cost_per_token = $5, output_cost_per_token = $6,
                                    cache_read_input_token_cost = $7, updated_at = CURRENT_TIMESTAMP
                                WHERE name = $1
                            """, name, info["model_name"], info["model_version"], info["provider_key"],
                                 info["input_cost_per_token"], info["output_cost_per_token"],
                                 info["cache_read_input_token_cost"])
                            updated_count += 1
                        else:
                            # Insert
                            await conn.execute("""
                                INSERT INTO model_costs 
                                (name, model_name, model_version, provider_key, input_cost_per_token,
                                 output_cost_per_token, cache_read_input_token_cost)
                                VALUES ($1, $2, $3, $4, $5, $6, $7)
                            """, name, info["model_name"], info["model_version"], info["provider_key"],
                                 info["input_cost_per_token"], info["output_cost_per_token"],
                                 info["cache_read_input_token_cost"])
                            saved_count += 1
                    except Exception as e:
                        log.error(f"Error processing {name}: {e}")
                        continue
                
                log.info(f"✅ Database updated: {saved_count} new, {updated_count} updated")
            
            # Reload cache
            await self._load_costs_from_db()
            
        except Exception as e:
            log.error(f"❌ Failed to update costs from LiteLLM: {e}", exc_info=True)
    
    def calculate_cost(self, model_name: str, prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0, fallback_model: Optional[str] = None) -> Tuple[float, float, float, float]:
        """
        Calculate costs for token usage with comprehensive fallback chain.
        
        Lookup order:
        1. Exact model name match (e.g., 'gpt-5.1-chat')
        2. Fallback model (deployment name like 'gpt-4o')
        3. Environment-configured base model mapping (BASE_MODEL_MAPPING)
        4. Auto-extracted base model from response name (removes date suffixes)
        5. Return zero costs if nothing matches

        When the exact model_name (e.g. the version string returned by Azure like
        'gpt-5.1-2025-11-13') is not in the pricing cache, falls back to
        fallback_model (typically the configured deployment name, e.g. 'gpt-4o').

        Returns:
            Tuple of (prompt_cost, completion_cost, cached_cost, total_cost)
        """
        cost_data = None
        used_lookup = None  # Track which lookup method succeeded
        
        # Step 1: Try exact match first
        cost_data = self._cache.get(model_name)
        if cost_data:
            used_lookup = f"exact match: {model_name}"

        # Step 2: Fall back to the deployment/configured model name
        if not cost_data and fallback_model and fallback_model != model_name:
            cost_data = self._cache.get(fallback_model)
            if cost_data:
                used_lookup = f"deployment fallback: {fallback_model}"
        
        # Step 3: Try environment-configured base model mapping
        if not cost_data and model_name in _BASE_MODEL_MAPPING:
            base_model = _BASE_MODEL_MAPPING[model_name]
            cost_data = self._cache.get(base_model)
            if cost_data:
                used_lookup = f"env mapping: {model_name} -> {base_model}"
        
        # Step 4: Try auto-extracted base model (removes date suffixes)
        if not cost_data:
            base_model = extract_base_model(model_name)
            if base_model != model_name:
                cost_data = self._cache.get(base_model)
                if cost_data:
                    used_lookup = f"auto-extracted: {base_model}"

        if not cost_data:
            log.warning(
                f"⚠️ No cost data found for model '{model_name}' "
                f"(fallback: {fallback_model or 'none'}, "
                f"env mapping: {_BASE_MODEL_MAPPING.get(model_name, 'none')})"
            )
            return (0.0, 0.0, 0.0, 0.0)
        
        # Log successful lookup method
        log.info(f"💡 Cost lookup succeeded via {used_lookup} for response model '{model_name}'")
        
        # Calculate costs
        prompt_cost = prompt_tokens * (cost_data.get('input_cost_per_token') or 0.0)
        completion_cost = completion_tokens * (cost_data.get('output_cost_per_token') or 0.0)
        cached_cost = cached_tokens * (cost_data.get('cache_read_input_token_cost') or 0.0)
        total_cost = prompt_cost + completion_cost + cached_cost
        
        return (
            round(prompt_cost, 8),
            round(completion_cost, 8),
            round(cached_cost, 8),
            round(total_cost, 8)
        )


# Global cost service instance
_cost_service = ModelCostService()


# ==========================================
# BACKGROUND COST UPDATER
# ==========================================

_scheduler_task: Optional[asyncio.Task] = None
_scheduler_running = False


async def _background_cost_updater():
    """Background task that updates costs every 2 days"""
    global _scheduler_running
    
    while _scheduler_running:
        try:
            log.info("🔄 Standalone Tracker: Starting scheduled model cost update...")
            await _cost_service.fetch_and_update_costs_from_litellm()
            log.info("✅ Standalone Tracker: Model cost update completed")
        except Exception as e:
            log.error(f"❌ Error in scheduled cost update: {e}", exc_info=True)
        
        # Wait for 2 days (48 hours)
        await asyncio.sleep(2 * 24 * 60 * 60)


def start_cost_update_scheduler():
    """Start background task to update model costs periodically"""
    global _scheduler_task, _scheduler_running
    
    if not _config.enabled:
        return
    
    if _scheduler_task and not _scheduler_task.done():
        log.info("⏭️ Cost update scheduler already running")
        return
    
    _scheduler_running = True
    _scheduler_task = asyncio.create_task(_background_cost_updater())
    log.info("🚀 Standalone Tracker: Cost update scheduler started (updates every 2 days)")


def stop_cost_update_scheduler():
    """Stop background cost updater"""
    global _scheduler_task, _scheduler_running
    
    _scheduler_running = False
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        log.info("🛑 Standalone Tracker: Cost update scheduler stopped")


# ==========================================
# TOKEN USAGE LOGGER
# ==========================================

class StandaloneTokenLogger:
    """Standalone token usage logger that writes to token_usage_logs table"""
    
    def __init__(self):
        self.enabled = _config.enabled
    
    async def initialize(self):
        """Initialize logger and dependencies"""
        if not self.enabled:
            log.info("⏭️ Standalone Token Logger disabled")
            return
        
        try:
            # Initialize database pool
            await _db_pool.initialize()
            
            # Initialize cost service
            await _cost_service.initialize()
            
            # Start background cost updater
            start_cost_update_scheduler()
            
            log.info("✅ Standalone Token Logger fully initialized")
            
        except Exception as e:
            log.error(f"❌ Failed to initialize Standalone Token Logger: {e}", exc_info=True)
    
    async def log_token_usage(
        self,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cached_tokens: int = 0,
        agent_id: Optional[int] = None,
        agent_name: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        request_id: Optional[str] = None,
        status: str = "success",
        metadata: Optional[Dict[str, Any]] = None,
        call_category: Optional[str] = None,
        call_sub_category: Optional[str] = None,
        call_operation: Optional[str] = None,
        tool_id: Optional[int] = None,
        tool_name: Optional[str] = None,
        evaluation_type: Optional[str] = None,
        agent_type: Optional[str] = None,
        agent_component: Optional[str] = None,
        deployment_model: Optional[str] = None,
    ):
        """
        Log token usage to token_usage_logs table with categorization
        
        Standard fields:
        - timestamp, agent_id, agent_name, model_name, session_id, user_id, request_id
        - prompt_tokens, completion_tokens, total_tokens, cached_tokens
        - prompt_cost, completion_cost, cached_cost, total_cost
        - status, metadata
        
        NEW Categorization fields:
        - call_category: Main category (agent_inference, tool_operation, evaluation, etc.)
        - call_sub_category: Specific subcategory (react_stream, tool_validation, etc.)
        - call_operation: Detailed operation (chat_inference, parameter_validation, etc.)
        - tool_id: ID of tool being used (for tool operations)
        - tool_name: Name of tool being used
        - evaluation_type: Type of evaluation (ground_truth, response_quality, etc.)
        - agent_type: Type of agent (react, meta, planner_executor, etc.)
        - agent_component: Component within agent (planner, executor, critic, etc.)
        """
        if not self.enabled:
            return
        
        try:
            # Calculate costs — pass deployment_model as fallback for version-string model names
            prompt_cost, completion_cost, cached_cost, total_cost = _cost_service.calculate_cost(
                model_name, prompt_tokens, completion_tokens, cached_tokens,
                fallback_model=deployment_model,
            )
            
            # Fetch agent name from database if agent_id provided but no agent_name
            if agent_id and not agent_name:
                try:
                    async with _db_pool.acquire() as conn:
                        result = await conn.fetchrow(
                            "SELECT agentic_application_name FROM agent_table WHERE agentic_application_id = $1",
                            agent_id
                        )
                        if result:
                            agent_name = result["agentic_application_name"]
                except Exception as e:
                    log.warning(f"⚠️ Could not fetch agent name for agent_id={agent_id}: {e}")
            
            # Insert into token_usage_logs table with categorization columns
            async with _db_pool.acquire() as conn:
                # Check if new columns exist
                has_new_columns = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name = 'token_usage_logs' 
                        AND column_name = 'call_category'
                    )
                """)
                
                if has_new_columns:
                    # Use new schema with categorization columns
                    await conn.execute(
                        """
                        INSERT INTO token_usage_logs (
                            timestamp, agent_id, agent_name, model_name, session_id, user_id, request_id,
                            prompt_tokens, completion_tokens, total_tokens, cached_tokens,
                            prompt_tokens_cost, cached_tokens_cost, completion_tokens_cost, total_cost,
                            status, error_message,
                            call_category, call_sub_category, call_operation,
                            tool_id, tool_name, evaluation_type, agent_type, agent_component
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17,
                                  $18, $19, $20, $21, $22, $23, $24, $25)
                        """,
                        datetime.now(), agent_id, agent_name, model_name, session_id, user_id, request_id,
                        prompt_tokens, completion_tokens, total_tokens, cached_tokens,
                        prompt_cost, cached_cost, completion_cost, total_cost,
                        status, None,  # error_message
                        call_category, call_sub_category, call_operation,
                        tool_id, tool_name, evaluation_type, agent_type, agent_component
                    )
                    log.info(
                        f"✅ Token usage logged: model={model_name}, category={call_category}, "
                        f"sub_category={call_sub_category}, agent_id={agent_id}, tokens={total_tokens}, cost=${total_cost:.8f}"
                    )
                else:
                    # Fallback to old schema without categorization
                    log.warning("⚠️ Categorization columns not found. Using legacy schema. Run migration script!")
                    await conn.execute(
                        """
                        INSERT INTO token_usage_logs (
                            timestamp, agent_id, agent_name, model_name, session_id, user_id, request_id,
                            prompt_tokens, completion_tokens, total_tokens, cached_tokens,
                            prompt_tokens_cost, cached_tokens_cost, completion_tokens_cost, total_cost,
                            status, error_message
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
                        """,
                        datetime.now(), agent_id, agent_name, model_name, session_id, user_id, request_id,
                        prompt_tokens, completion_tokens, total_tokens, cached_tokens,
                        prompt_cost, cached_cost, completion_cost, total_cost,
                        status, None  # error_message
                    )
                    log.info(
                        f"✅ Token usage logged (legacy): model={model_name}, agent_id={agent_id}, "
                        f"tokens={total_tokens}, cost=${total_cost:.8f}"
                    )
            
        except Exception as e:
            log.error(
                f"❌ Failed to log token usage: {e}\n"
                f"   Model: {model_name}, Agent ID: {agent_id}, Tokens: {total_tokens}",
                exc_info=True
            )
    
    async def close(self):
        """Cleanup resources"""
        stop_cost_update_scheduler()
        await _db_pool.close()


# ==========================================
# GLOBAL SINGLETON INSTANCE
# ==========================================

# Global logger instance
standalone_token_logger = StandaloneTokenLogger()


# ==========================================
# PUBLIC API
# ==========================================

async def initialize_tracker():
    """Initialize the standalone tracker (call once at startup)"""
    await standalone_token_logger.initialize()


async def log_token_usage(**kwargs):
    """Log token usage"""
    await standalone_token_logger.log_token_usage(**kwargs)


def calculate_cost(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
    fallback_model: Optional[str] = None,
) -> Dict[str, float]:
    """Return prompt, completion, cached, and total cost for a single LLM call.

    Uses the same model-cost lookup that log_token_usage uses internally so all
    cost figures are consistent across the system.

    Args:
        model_name: The model name from the response (e.g. 'gpt-5.1-2025-11-13').
        fallback_model: The configured deployment name (e.g. 'gpt-4o') used when
            the response model name has no pricing entry in the cache.

    Returns a dict with keys: prompt_cost, completion_cost, cached_cost, total_cost.
    All values are floats rounded to 8 decimal places (0.0 when no cost data found).
    """
    p, c, ca, tot = _cost_service.calculate_cost(
        model_name, prompt_tokens, completion_tokens, cached_tokens,
        fallback_model=fallback_model,
    )
    return {
        "prompt_cost":     p,
        "completion_cost": c,
        "cached_cost":     ca,
        "total_cost":      tot,
    }


async def cleanup_tracker():
    """Cleanup tracker resources"""
    await standalone_token_logger.close()


def is_tracker_enabled() -> bool:
    """Check if tracker is enabled"""
    return _config.enabled


# ==========================================
# PER-REQUEST TOKEN ACCUMULATOR
# ==========================================
# Keyed by session_id. Because FastAPI/asyncio runs on a single event loop,
# concurrent requests each hold their own session_id key with no locking needed.
# The value is a list of lightweight dicts — one entry per LLM call.

_request_accumulators: Dict[str, List[Dict]] = {}


def init_request_accumulator(session_id: str) -> None:
    """Create a fresh token bucket for a new inference request.
    Call this from the API handler before the graph starts."""
    if session_id:
        _request_accumulators[session_id] = []
        log.info(f"🪣 [TokenAccumulator] Bucket opened for session={session_id}")


def record_to_accumulator(session_id: str, record: Dict) -> None:
    """Append one LLM call's token record to the in-flight accumulator.
    No-ops silently if the accumulator was never initialised (e.g. background tasks)."""
    if session_id and session_id in _request_accumulators:
        _request_accumulators[session_id].append(record)
        call_n = len(_request_accumulators[session_id])
        log.info(
            f"📥 [TokenAccumulator] Call #{call_n} recorded: "
            f"model={record.get('model')}, "
            f"prompt={record.get('prompt_tokens')}, "
            f"completion={record.get('completion_tokens')}, "
            f"total={record.get('total_tokens')}, "
            f"category={record.get('call_category')}, "
            f"session={session_id}"
        )
    else:
        log.debug(
            f"⏭️  [TokenAccumulator] No bucket for session={session_id} — skipping "
            f"(background task or accumulator already cleared)"
        )


def get_and_clear_accumulator(session_id: str) -> List[Dict]:
    """Return every record collected for this request and remove the bucket.
    Returns an empty list if nothing was registered."""
    records = _request_accumulators.pop(session_id, [])
    total_tokens = sum(r.get('total_tokens', 0) for r in records)
    total_prompt = sum(r.get('prompt_tokens', 0) for r in records)
    total_completion = sum(r.get('completion_tokens', 0) for r in records)
    log.info(
        f"📤 [TokenAccumulator] Bucket drained for session={session_id}: "
        f"{len(records)} LLM call(s), "
        f"prompt={total_prompt}, completion={total_completion}, total={total_tokens}"
    )
    return records


async def update_costs_now():
    """Manually trigger cost update from LiteLLM"""
    await _cost_service.fetch_and_update_costs_from_litellm()


# ==========================================
# LITELLM CALLBACK — GOOGLE ADK PATH
# ==========================================

class _ADKTokenTracker:
    """
    LiteLLM custom callback that captures token usage from Google ADK LiteLlm calls.

    Google ADK's LiteLlm class calls litellm.acompletion() / litellm.completion()
    internally. By registering this callback via litellm.callbacks, every ADK
    completion is automatically tracked without any changes to the inference files.

    This callback is ONLY triggered for direct LiteLLM SDK calls (ADK path).
    It does NOT fire for:
    - AzureAIModelService  (uses Azure SDK directly, not LiteLLM)
    - LangChain wrappers   (call the proxy over HTTP, not the SDK)
    """

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        """Called by LiteLLM after every successful async completion."""
        try:
            if not is_tracker_enabled():
                return

            usage = getattr(response_obj, 'usage', None)
            if not usage:
                return

            prompt_tokens = getattr(usage, 'prompt_tokens', 0) or 0
            completion_tokens = getattr(usage, 'completion_tokens', 0) or 0
            total_tokens = getattr(usage, 'total_tokens', 0) or 0

            if total_tokens == 0:
                return

            model = getattr(response_obj, 'model', None) or kwargs.get('model', 'unknown')

            # Pull context injected by the agent session
            try:
                from telemetry_wrapper import SessionContext
                session_ctx = SessionContext.get()
                user_id = session_ctx[0] if session_ctx and session_ctx[0] != 'Unassigned' else None
                session_id = session_ctx[1] if session_ctx and session_ctx[1] != 'Unassigned' else None
                agent_id = session_ctx[3] if session_ctx and session_ctx[3] != 'Unassigned' else None
            except Exception:
                user_id = session_id = agent_id = None

            await log_token_usage(
                model_name=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
                status="success",
                call_category="agent_inference",
            )
            log.info(
                f"✅ [ADKTokenTracker] Logged ADK usage: model={model}, "
                f"prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}"
            )

        except Exception as exc:
            log.error(f"❌ [ADKTokenTracker] async_log_success_event failed: {exc}", exc_info=True)

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        """Called by LiteLLM after every successful sync completion."""
        try:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self.async_log_success_event(kwargs, response_obj, start_time, end_time)
                )
            except RuntimeError:
                log.debug("[ADKTokenTracker] No running event loop for sync LiteLLM callback")
        except Exception as exc:
            log.error(f"❌ [ADKTokenTracker] log_success_event failed: {exc}", exc_info=True)


# ==========================================
# INTEGRATION HOOK
# ==========================================

async def register_tracker_hooks():
    """
    Register token tracking hooks for both proxy and direct Azure OpenAI calls.
    Call this during application startup.

    Registers:
    1. DB / cost scheduler initialisation (always)
    2. LiteLLM SDK callback for Google ADK LiteLlm calls (_ADKTokenTracker)
    """
    try:
        await initialize_tracker()

        # Register the ADK callback with LiteLLM if not already present
        existing_types = {type(c) for c in litellm.callbacks}
        if _ADKTokenTracker not in existing_types:
            litellm.callbacks.append(_ADKTokenTracker())
            log.info("🪝 [ADKTokenTracker] LiteLLM callback registered for Google ADK path")
        else:
            log.info("🪝 [ADKTokenTracker] LiteLLM callback already registered")

        log.info("🪝 Standalone token tracking hooks registered successfully")
    except Exception as e:
        log.error(f"❌ Failed to register tracker hooks: {e}", exc_info=True)


__all__ = [
    "standalone_token_logger",
    "initialize_tracker",
    "log_token_usage",
    "calculate_cost",
    "cleanup_tracker",
    "is_tracker_enabled",
    "update_costs_now",
    "register_tracker_hooks",
    "StandaloneTokenLogger",
    "TrackerConfig",
    "LLMCallCategory",
    "AgentType",
    "ToolOperation",
    "EvaluationType",
    "init_request_accumulator",
    "record_to_accumulator",
    "get_and_clear_accumulator",
]
