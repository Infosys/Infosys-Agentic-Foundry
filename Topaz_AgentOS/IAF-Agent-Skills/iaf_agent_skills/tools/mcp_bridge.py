"""
MCP Tool Bridge — Unified adapter for Direct MCP servers and Enterprise MCP Registry.

Supports three connection types via a single `mcp_connections` config:
  - direct+stdio   : Local MCP server via stdio (command + args)
  - direct+http    : Remote MCP server via streamable HTTP (url)
  - registry       : Enterprise MCP Registry (REST discovery + proxied execution)

Each adapter discovers tools from the MCP source and converts them to
LangChain StructuredTool instances that can be injected into create_react_agent.

Usage:
    bridge = MCPToolBridge(connections=[
        {"name": "calc", "type": "direct", "transport": "stdio",
         "command": "python3", "args": ["calc_server.py"]},
        {"name": "corp-registry", "type": "registry",
         "url": "http://registry:7001", "auth": {"type": "bearer", "token": "${MCP_TOKEN}"}},
    ])
    tools = await bridge.get_tools()  # List[StructuredTool]
"""

import os
import re
import json
import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _resolve_env_vars(value: str, consumer: str | None = None, config_dir: str | None = None) -> str:
    """Resolve ``${VAR}``, ``${CRED:name/field}`` and ``${VAULT:conn@path#key}``
    placeholders in a string.

        ${VAR}              -> os.environ lookup (legacy behaviour, unchanged).
        ${CRED:name/field}  -> `field` from credential `name` in the AgentOS
                               CredentialStore (encrypted at rest). The tenant
                               config dir comes from AGENTOS_CREDENTIAL_CONFIG_DIR,
                               else it is auto-discovered by walking up from CWD for
                               enterprise_root/tenants/*/shared/config/credentials.yaml.
                               The lookup consumer is AGENTOS_CRED_CONSUMER (set by the
                               agent around tool discovery) so scoped credentials pass.
        ${VAULT:conn@path#key} -> `key` read live from HashiCorp Vault, using a
                               ``type: vault`` connection stored as credential `conn`
                               in credentials.yaml (addr/namespace/mount/AppRole or
                               token). Scope-checked against AGENTOS_CRED_CONSUMER
                               exactly like ${CRED:...}; the secret is fetched below
                               the agent and never logged. `path` is the KV path
                               within the connection's mount.

    Example:
        _resolve_env_vars("Bearer ${MCP_TOKEN}")                 -> "Bearer abc123"
        _resolve_env_vars("${CRED:splunk_mcp/token}")            -> "<decrypted token>"
        _resolve_env_vars("${VAULT:dcm_vault@network/prod#api_token}") -> "<live vault secret>"

    Unresolved refs are left as-is so callers get a clear signal.
    """
    if not isinstance(value, str):
        return value
    # Delegate to the neutral resolver shared by every secret-consuming surface.
    from agent_os.secret_refs import expand_secret_refs
    # Prefer an explicitly-threaded consumer/config_dir over the process-global env
    # vars: os.environ is shared across concurrent resumes, so an explicit scope makes
    # credential resolution isolated per call (no cross-tenant bleed). Env is the
    # fallback so existing callers that don't thread a scope are unchanged.
    consumer = consumer or os.environ.get("AGENTOS_CRED_CONSUMER") or None
    return expand_secret_refs(value, _get_cred_store(config_dir), consumer, purpose="mcp_connection")


def _redact_url_for_log(url: str) -> str:
    """Strip secret-bearing parts (userinfo, query, fragment) from a URL so a
    resolved ``${VAULT:...}``/``${CRED:...}`` value embedded in the connection URL
    never reaches the logs. Keeps only ``scheme://host[:port]/path``."""
    try:
        from urllib.parse import urlsplit
        p = urlsplit(str(url))
        host = p.hostname or ""
        if p.port:
            host = f"{host}:{p.port}"
        return f"{p.scheme}://{host}{p.path}" if p.scheme else (host or "<redacted-url>")
    except Exception:
        return "<redacted-url>"



_CRED_STORES: dict = {}


def _get_cred_store(config_dir: str | None = None):
    """Lazy-init a CredentialStore rooted at the tenant config dir.

    Resolution:
      * If an explicit ``config_dir`` is supplied (threaded per-call by the agent) it
        is **authoritative**: it is validated and used, and if it is invalid/missing
        this returns None rather than falling back — so a misconfigured or
        mid-provisioning tenant can never silently resolve ${CRED:...} against another
        tenant's credentials via CWD auto-discovery.
      * Otherwise discovery is: env var AGENTOS_CREDENTIAL_CONFIG_DIR, else walk up
        from CWD for enterprise_root/tenants/*/shared/config/credentials.yaml.
    Returns None when nothing is found (retried on the next call) so a transient
    missing-config-dir never permanently disables ${CRED:...} resolution.

    Stores are cached per resolved config directory so concurrent tenants never
    share one another's credentials.
    """
    try:
        from pathlib import Path
        from agent_os.safe_path import SecurityError, validated_path
        cfg_dir = None
        explicit = str(config_dir).strip() if config_dir else ""
        if explicit:
            # Explicit tenant config dir is authoritative — never fall back to CWD
            # auto-discovery, which could select a different tenant's credentials.yaml.
            try:
                safe_explicit = validated_path(explicit, label="config_dir")
            except SecurityError as exc:
                logger.warning("MCP bridge: invalid explicit config_dir (%s); ${CRED:...} disabled", exc)
                return None
            if not safe_explicit.is_dir():
                logger.warning(
                    "MCP bridge: explicit config_dir does not exist (%s); ${CRED:...} disabled "
                    "(not falling back to auto-discovery, to preserve tenant isolation)", safe_explicit,
                )
                return None
            cfg_dir = safe_explicit
        else:
            env_dir = os.environ.get("AGENTOS_CREDENTIAL_CONFIG_DIR", "").strip()
            safe_env_dir = None
            if env_dir:
                try:
                    safe_env_dir = validated_path(env_dir, label="AGENTOS_CREDENTIAL_CONFIG_DIR")
                except SecurityError as exc:
                    logger.warning("MCP bridge: ignoring invalid AGENTOS_CREDENTIAL_CONFIG_DIR: %s", exc)
            if safe_env_dir is not None and safe_env_dir.is_dir():
                cfg_dir = safe_env_dir
            else:
                here = Path(os.getcwd()).resolve()
                for parent in [here, *here.parents]:
                    hits = list(parent.glob("enterprise_root/tenants/*/shared/config/credentials.yaml"))
                    if hits:
                        cfg_dir = hits[0].parent
                        break
        if cfg_dir is None:
            logger.debug("MCP bridge: no credential config dir found; ${CRED:...} refs disabled")
            return None
        cache_key = str(cfg_dir.resolve())
        cached = _CRED_STORES.get(cache_key)
        if cached is not None:
            return cached
        from agent_os.credential_store import CredentialStore  # lazy
        store = CredentialStore.create(config_dir=cfg_dir)
        _CRED_STORES[cache_key] = store
        logger.info("MCP bridge: credential store initialised at %s", cfg_dir)
        return store
    except Exception as e:
        logger.warning("MCP bridge: credential store init failed (%s); ${CRED:...} refs disabled", e)
        return None




def _resolve_dict_env_vars(d: dict, consumer: str | None = None, config_dir: str | None = None) -> dict:
    """Recursively resolve ${VAR}/${CRED:...}/${VAULT:...} in all string values.

    ``consumer``/``config_dir`` are preferred over the process-global env vars so
    concurrent resumes resolve credentials under their own isolated scope; env is the
    fallback (see ``_resolve_env_vars``)."""
    from agent_os.secret_refs import expand_secret_refs_in_obj
    consumer = consumer or os.environ.get("AGENTOS_CRED_CONSUMER") or None
    return expand_secret_refs_in_obj(d, _get_cred_store(config_dir), consumer, purpose="mcp_connection")


def _mcp_ssl_verify():
    """Resolve the TLS verify setting for remote (http/sse) MCP connections.

    Mirrors the LLM path's _get_ssl_verify so deployments behind a corporate proxy
    with SSL inspection (Zscaler) can trust the inspected chain. Precedence:
      MCP_SSL_VERIFY=false/0/no/off        -> False (skip verification; insecure)
      MCP_SSL_VERIFY=/path/to/ca.pem       -> that path (custom CA bundle)
      else MCP_CA_BUNDLE / REQUESTS_CA_BUNDLE / SSL_CERT_FILE, if a file -> that path
      else                                 -> True (default certifi trust store)
    Returns True | False | "<path>".
    """
    val = (os.getenv("MCP_SSL_VERIFY", "") or "").strip()
    if val.lower() in {"0", "false", "no", "off"}:
        return False
    if val and os.path.isfile(val):
        return val
    for env_name in ("MCP_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"):
        candidate = (os.getenv(env_name, "") or "").strip()
        if candidate and os.path.isfile(candidate):
            return candidate
    return True


def _conn_ssl_verify(conn: dict):
    """TLS verify for a single MCP connection: a per-connection override if the
    connection sets one, else the global MCP setting (``_mcp_ssl_verify``).

    A connection may set ``verify_ssl`` / ``ssl_verify`` / ``tls_verify``:
        false/0/no/off  -> skip verification (self-signed internal endpoints)
        true/1/yes/on   -> force verification (default trust store)
        /path/to/ca.pem -> use that CA bundle
    Absent/blank -> fall back to ``_mcp_ssl_verify()`` (MCP_SSL_VERIFY / CA bundles).

    This lets a self-signed endpoint (e.g. an internal Splunk) opt out of TLS
    verification for just its own connection, without weakening it globally.
    """
    for key in ("verify_ssl", "ssl_verify", "tls_verify"):
        raw = conn.get(key)
        if raw is None or str(raw).strip() == "":
            continue
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip()
        if s.lower() in {"0", "false", "no", "off"}:
            return False
        if s.lower() in {"1", "true", "yes", "on"}:
            return True
        if os.path.isfile(s):
            return s
        # Unknown string — ignore the override and fall back to the global setting.
    return _mcp_ssl_verify()


def _discovery_timeout(default: float = 30.0) -> float:
    """Seconds to wait for MCP tool discovery before giving up.

    A cold `npx`/`uvx` first run downloads the server package, which can take far
    longer than a warm launch — the old hard-coded 10s frequently timed out on the
    first call. Configurable via MCP_DISCOVERY_TIMEOUT (seconds); default 30.
    """
    raw = (os.getenv("MCP_DISCOVERY_TIMEOUT", "") or "").strip()
    if raw:
        try:
            val = float(raw)
            if val > 0:
                return val
        except ValueError:
            logger.warning("Invalid MCP_DISCOVERY_TIMEOUT=%r; using default %ss", raw, default)
    return default


def _install_windows_console_guard():
    """Belt-and-suspenders: guarantee stdio MCP child processes never flash a
    console window under console-less pythonw.exe.

    The MCP SDK (>=1.x) already passes CREATE_NO_WINDOW when spawning stdio servers,
    but older/pinned versions and the anyio fast-path did not. We wrap
    ``anyio.open_process`` once so that on Windows every async subprocess spawn ORs in
    CREATE_NO_WINDOW when the caller didn't set creationflags. OR-ing a flag the SDK
    already sets is a no-op, so this is safe and idempotent across SDK versions.
    """
    if os.name != "nt":
        return
    try:
        import anyio  # noqa
        import subprocess as _sp
    except Exception:
        return
    if getattr(anyio, "_iaf_noflash_patched", False):
        return
    no_window = getattr(_sp, "CREATE_NO_WINDOW", 0)
    if not no_window:
        return
    _orig_open_process = anyio.open_process

    async def _open_process_no_window(*a, **kw):
        if "creationflags" not in kw or not kw.get("creationflags"):
            kw["creationflags"] = no_window
        return await _orig_open_process(*a, **kw)

    try:
        anyio.open_process = _open_process_no_window
        anyio._iaf_noflash_patched = True
        logger.debug("MCP: installed Windows no-console-window guard on anyio.open_process")
    except Exception as e:
        logger.debug("MCP: could not install Windows console guard (non-fatal): %s", e)


# Apply the Windows console guard at import so any MCP stdio spawn is covered.
_install_windows_console_guard()


def _make_mcp_httpx_factory(verify):
    """Build an McpHttpClientFactory that applies `verify` (CA bundle / bool) while
    preserving the MCP SDK's client defaults (follow_redirects + timeouts). Passed
    as `httpx_client_factory` on http/sse connections so the corporate CA is trusted."""
    def _factory(headers=None, timeout=None, auth=None) -> httpx.AsyncClient:
        kwargs = {"follow_redirects": True, "verify": verify}
        if timeout is None:
            kwargs["timeout"] = httpx.Timeout(30.0, read=300.0)
        else:
            kwargs["timeout"] = timeout
        if headers is not None:
            kwargs["headers"] = headers
        if auth is not None:
            kwargs["auth"] = auth
        return httpx.AsyncClient(**kwargs)
    return _factory


def _match_tool_filter(tool_name: str, filters: Optional[List[str]]) -> bool:
    """
    Check if a tool name matches the allowlist filter.
    
    Args:
        tool_name: Name of the discovered tool
        filters: List of allowed tool names (glob not supported yet).
                 None or empty means 'allow all'.
    
    Returns:
        True if the tool should be included.
    """
    if not filters:
        return True
    return tool_name in filters



_REQUIRED_DIRECT = {"name", "type", "transport"}
_REQUIRED_REGISTRY = {"name", "type", "url"}


def validate_connection(conn: dict) -> List[str]:
    """
    Validate a single connection config dict.
    
    Returns:
        List of error strings. Empty means valid.
    """
    errors = []
    conn_type = conn.get("type", "")
    conn_name = conn.get("name", "<unnamed>")
    
    if conn_type == "direct":
        for key in _REQUIRED_DIRECT:
            if key not in conn:
                errors.append(f"[{conn_name}] Missing required field '{key}' for direct connection")
        transport = conn.get("transport", "")
        if transport == "stdio" and "command" not in conn:
            errors.append(f"[{conn_name}] stdio transport requires 'command'")
        elif transport == "streamable_http" and "url" not in conn:
            errors.append(f"[{conn_name}] streamable_http transport requires 'url'")
        elif transport == "sse" and "url" not in conn:
            errors.append(f"[{conn_name}] sse transport requires 'url'")
        elif transport not in ("stdio", "streamable_http", "sse"):
            errors.append(f"[{conn_name}] Unknown transport '{transport}'. Must be 'stdio', 'streamable_http', or 'sse'")
    elif conn_type == "registry":
        for key in _REQUIRED_REGISTRY:
            if key not in conn:
                errors.append(f"[{conn_name}] Missing required field '{key}' for registry connection")
    else:
        errors.append(f"[{conn_name}] Unknown connection type '{conn_type}'. Must be 'direct' or 'registry'")
    
    return errors



def _wrap_async_tool(tool):
    """
    Wrap an async-only LangChain tool so it can be called synchronously.
    The ReAct agent invokes tools via tool.run() (sync). MCP tools from
    langchain_mcp_adapters are async-only, so we add a sync _run that
    runs the coroutine in a new event loop on a background thread.
    """
    from langchain_core.tools import StructuredTool
    import concurrent.futures

    original_func = tool.func  # may be None for async-only tools
    original_coroutine = tool.coroutine  # the async function

    if original_func is not None:
        # Already has sync version
        return tool

    if original_coroutine is None:
        return tool

    def sync_func(**kwargs):
        """Sync wrapper: runs the async MCP tool in a fresh event loop."""
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, original_coroutine(**kwargs))
            return future.result(timeout=30)

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        func=sync_func,
        coroutine=original_coroutine,
    )



class DirectAdapter:
    """
    Adapter for direct MCP server connections (stdio or HTTP).
    
    Wraps langchain-mcp-adapters MultiServerMCPClient to discover tools
    and return them as LangChain StructuredTool instances.
    """
    
    def __init__(self, connections: List[dict], consumer: str | None = None, config_dir: str | None = None):
        """
        Args:
            connections: List of direct-type connection configs.
                Each must have: name, type='direct', transport, and
                either command+args (stdio) or url (http).
            consumer / config_dir: optional credential scope threaded explicitly so
                ${CRED:...} resolves under the right tenant/skill without relying on
                the process-global env (isolated across concurrent resumes).
        """
        self.connections = connections
        self._consumer = consumer
        self._config_dir = config_dir

    def _build_client_config(self) -> dict:
        """
        Convert our unified connection format to MultiServerMCPClient config.

        Returns:
            Dict keyed by server name with transport-specific config.
        """
        # Bind the threaded credential scope into the resolvers for this adapter.
        def _rv(v):
            return _resolve_env_vars(v, self._consumer, self._config_dir)
        def _rd(d):
            return _resolve_dict_env_vars(d, self._consumer, self._config_dir)
        config = {}
        for conn in self.connections:
            name = conn["name"]
            transport = conn["transport"]

            if transport == "stdio":
                entry = {
                    "command": conn["command"],
                    "args": conn.get("args", []),
                    "transport": "stdio",
                }
                # Add env vars (resolved)
                if "env" in conn:
                    entry["env"] = _rd(conn["env"])

            elif transport == "streamable_http":
                entry = {
                    "url": _rv(conn["url"]),
                    "transport": "streamable_http",
                }
                # Add headers (resolved, includes auth)
                headers = {}
                if "headers" in conn:
                    headers.update(_rd(conn["headers"]))
                auth = conn.get("auth", {})
                if auth.get("type") == "bearer":
                    token = _rv(auth.get("token", ""))
                    headers["Authorization"] = f"Bearer {token}"
                if headers:
                    entry["headers"] = headers
                if "timeout_sec" in conn:
                    entry["timeout"] = conn["timeout_sec"]
                _verify = _conn_ssl_verify(conn)
                if _verify is not True:
                    entry["httpx_client_factory"] = _make_mcp_httpx_factory(_verify)

            elif transport == "sse":
                entry = {
                    "url": _rv(conn["url"]),
                    "transport": "sse",
                }
                # Add headers (resolved, includes auth)
                headers = {}
                if "headers" in conn:
                    headers.update(_rd(conn["headers"]))
                # api_key shorthand → X-API-Key header
                if "api_key" in conn:
                    headers["X-API-Key"] = _rv(conn["api_key"])
                auth = conn.get("auth", {})
                if auth.get("type") == "bearer":
                    token = _rv(auth.get("token", ""))
                    headers["Authorization"] = f"Bearer {token}"
                if headers:
                    entry["headers"] = headers
                if "timeout_sec" in conn:
                    entry["timeout"] = conn["timeout_sec"]
                # Corporate CA trust (Zscaler) — see streamable_http above.
                _verify = _conn_ssl_verify(conn)
                if _verify is not True:
                    entry["httpx_client_factory"] = _make_mcp_httpx_factory(_verify)
            else:
                logger.warning(f"Skipping connection '{name}' with unknown transport '{transport}'")
                continue
            
            config[name] = entry
        
        return config
    
    async def get_tools(self, tool_filter: Optional[List[str]] = None) -> List:
        """
        Discover and return tools from all direct MCP connections.
        
        Args:
            tool_filter: Optional list of allowed tool names.
        
        Returns:
            List of LangChain tool objects from MultiServerMCPClient.
        """
        from langchain_mcp_adapters.client import MultiServerMCPClient
        
        client_config = self._build_client_config()
        if not client_config:
            return []
        
        try:
            client = MultiServerMCPClient(client_config)
            _timeout = _discovery_timeout()
            try:
                tools = await asyncio.wait_for(client.get_tools(), timeout=_timeout)
            except asyncio.TimeoutError:
                logger.error(
                    "DirectAdapter: tool discovery timed out after %ss for %d server(s) — "
                    "a cold npx/uvx first run may need longer; raise MCP_DISCOVERY_TIMEOUT.",
                    _timeout, len(client_config),
                )
                return []

            if tool_filter:
                tools = [t for t in tools if _match_tool_filter(t.name, tool_filter)]

            # Wrap async-only tools to support sync invocation (ReAct agent calls tools sync)
            tools = [_wrap_async_tool(t) for t in tools]

            logger.info(f"DirectAdapter: discovered {len(tools)} tools from {len(client_config)} server(s)")
            return tools
        except Exception as e:
            logger.error(f"DirectAdapter: failed to get tools — {e}")
            return []



class RegistryAdapter:
    """
    Adapter for Enterprise MCP Registry (Pattern B: REST discovery + proxied execution).
    
    Discovery:
        GET /approved-servers → list of servers this team can access
        GET /tools            → aggregated tool schemas from all approved servers
    
    Execution:
        POST /query           → NL query routed to auto-selected server, executed
                                via LangGraph ReAct agent inside the registry
    
    Each discovered tool is wrapped as a LangChain StructuredTool that, when
    invoked, calls the registry's /query endpoint with the tool invocation.
    """
    
    def __init__(self, connection: dict, consumer: str | None = None, config_dir: str | None = None):
        """
        Args:
            connection: A registry-type connection config dict with at least:
                name, type='registry', url, and optionally auth, server_filter, tool_filter.
            consumer / config_dir: optional credential scope threaded explicitly so
                ${CRED:...} resolves without relying on the process-global env.
        """
        self.name = connection["name"]
        self.base_url = _resolve_env_vars(connection["url"], consumer, config_dir).rstrip("/")
        self.timeout_sec = connection.get("timeout_sec", 30)
        self.server_filter = connection.get("server_filter", [])
        self.tool_filter = connection.get("tool_filter", [])

        self.headers = {}
        if "headers" in connection:
            self.headers.update(_resolve_dict_env_vars(connection["headers"], consumer, config_dir))
        auth = connection.get("auth", {})
        if auth.get("type") == "bearer":
            token = _resolve_env_vars(auth.get("token", ""), consumer, config_dir)
            self.headers["Authorization"] = f"Bearer {token}"
    
    async def _fetch_servers(self) -> List[dict]:
        """
        GET /approved-servers — returns list of servers this team can access.
        
        Applies server_filter if configured (match by server name).
        """
        async with httpx.AsyncClient(timeout=self.timeout_sec, headers=self.headers) as client:
            resp = await client.get(f"{self.base_url}/approved-servers")
            resp.raise_for_status()
            servers = resp.json()
        
        if self.server_filter:
            servers = [s for s in servers if s.get("name") in self.server_filter]
        
        return servers
    
    async def _fetch_tools(self) -> List[dict]:
        """
        GET /tools — returns aggregated tool schemas from all approved servers.
        
        Returns:
            List of dicts with keys: name, description, inputSchema, server_name, server_id
        """
        async with httpx.AsyncClient(timeout=self.timeout_sec, headers=self.headers) as client:
            resp = await client.get(f"{self.base_url}/tools")
            resp.raise_for_status()
            return resp.json()
    
    async def _execute_query(self, server_id: str, requirement: str) -> dict:
        """
        POST /query — execute a natural-language requirement against a specific server.
        
        Args:
            server_id: The registry server ID to target.
            requirement: The NL query / tool invocation description.
        
        Returns:
            Registry response dict with 'result', 'tools_used', etc.
        """
        payload = {
            "server_id": server_id,
            "requirement": requirement,
        }
        async with httpx.AsyncClient(timeout=self.timeout_sec, headers=self.headers) as client:
            resp = await client.post(f"{self.base_url}/query", json=payload)
            resp.raise_for_status()
            return resp.json()
    
    def _make_registry_tool(self, tool_info: dict) -> StructuredTool:
        """
        Wrap a registry tool schema into a LangChain StructuredTool.
        
        The tool's func calls the registry /query endpoint with the arguments
        serialized as a natural-language requirement string.
        
        Args:
            tool_info: Dict with name, description, server_id, server_name, inputSchema.
        
        Returns:
            A LangChain StructuredTool that proxies to the registry.
        """
        tool_name = tool_info.get("name", "unknown")
        description = tool_info.get("description", f"Registry tool: {tool_name}")
        server_id = tool_info.get("server_id", "")
        server_name = tool_info.get("server_name", "")
        
        # Build pydantic model from inputSchema for the tool's args_schema
        input_schema = tool_info.get("inputSchema", {})
        properties = input_schema.get("properties", {})
        required_fields = input_schema.get("required", [])
        
        # Create a dynamic Pydantic model for the tool arguments
        # For simplicity and robustness, we use a flexible input model
        field_annotations = {}
        field_defaults = {}
        for prop_name, prop_def in properties.items():
            prop_type = prop_def.get("type", "string")
            prop_desc = prop_def.get("description", "")
            
            # Map JSON schema types to Python types
            type_map = {
                "string": str, "integer": int, "number": float,
                "boolean": bool, "array": list, "object": dict,
            }
            python_type = type_map.get(prop_type, str)
            
            if prop_name in required_fields:
                field_annotations[prop_name] = python_type
                field_defaults[prop_name] = Field(description=prop_desc)
            else:
                field_annotations[prop_name] = Optional[python_type]
                field_defaults[prop_name] = Field(default=None, description=prop_desc)
        
        # If no properties defined, accept a single 'input' string
        if not field_annotations:
            field_annotations["input"] = str
            field_defaults["input"] = Field(description="Input for the tool")
        
        DynamicModel = type(
            f"{tool_name}_Args",
            (BaseModel,),
            {"__annotations__": field_annotations, **field_defaults}
        )
        
        # Capture vars for closure
        _server_id = server_id
        _tool_name = tool_name
        _base_url = self.base_url
        _headers = self.headers.copy()
        _timeout = self.timeout_sec
        
        async def _invoke_registry(**kwargs) -> str:
            """Execute tool via registry /query endpoint."""
            # Build a clear requirement string from the tool call args
            requirement = f"Use the tool '{_tool_name}' with arguments: {json.dumps(kwargs)}"
            payload = {
                "server_id": _server_id,
                "requirement": requirement,
            }
            try:
                async with httpx.AsyncClient(timeout=_timeout, headers=_headers) as client:
                    resp = await client.post(f"{_base_url}/query", json=payload)
                    resp.raise_for_status()
                    result = resp.json()
                return json.dumps(result.get("result", result), default=str)
            except httpx.HTTPStatusError as e:
                return f"Registry error ({e.response.status_code}): {e.response.text[:500]}"
            except Exception as e:
                return f"Registry error: {str(e)}"
        
        # Sync wrapper (LangGraph calls tools synchronously by default)
        def _invoke_sync(**kwargs) -> str:
            """Sync wrapper around async registry call."""
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            
            if loop and loop.is_running():
                # Already in an async context — use nest_asyncio or run in thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, _invoke_registry(**kwargs))
                    return future.result(timeout=_timeout + 5)
            else:
                return asyncio.run(_invoke_registry(**kwargs))
        
        return StructuredTool(
            name=tool_name,
            description=f"[Registry:{server_name}] {description}",
            func=_invoke_sync,
            coroutine=_invoke_registry,
            args_schema=DynamicModel,
        )
    
    async def get_tools(self) -> List[StructuredTool]:
        """
        Discover tools from the registry and wrap each as a LangChain StructuredTool.
        
        Returns:
            List of StructuredTool instances (one per registry tool).
        """
        try:
            raw_tools = await self._fetch_tools()
            
            tools = []
            for tool_info in raw_tools:
                if not _match_tool_filter(tool_info.get("name", ""), self.tool_filter):
                    continue
                # Apply server_filter (if tool has server_name)
                if self.server_filter:
                    if tool_info.get("server_name") not in self.server_filter:
                        continue
                
                try:
                    st = self._make_registry_tool(tool_info)
                    tools.append(st)
                except Exception as e:
                    logger.warning(f"RegistryAdapter: failed to wrap tool '{tool_info.get('name')}' — {e}")
            
            logger.info(f"RegistryAdapter[{self.name}]: discovered {len(tools)} tools from registry")
            return tools
        except httpx.HTTPStatusError as e:
            # Redact the URL (it may carry a resolved secret) and omit the raw
            # response body, which can echo credentials back.
            logger.error(
                "RegistryAdapter[%s]: HTTP %s from %s",
                self.name, e.response.status_code, _redact_url_for_log(self.base_url),
            )
            return []
        except Exception as e:
            logger.error(f"RegistryAdapter[{self.name}]: failed to discover tools — {e}")
            return []



class MCPToolBridge:
    """
    Unified bridge that loads tools from all configured MCP connections.
    
    Merges connections from agent config and skill-level overrides.
    Supports both direct (stdio/HTTP) and registry connection types.
    
    Usage:
        bridge = MCPToolBridge(connections=[...])
        tools = await bridge.get_tools()
    """
    
    def __init__(self, connections: Optional[List[dict]] = None,
                 consumer: str | None = None, config_dir: str | None = None):
        """
        Args:
            connections: List of MCP connection configs. Each dict must have
                at least 'name' and 'type' ('direct' or 'registry').
            consumer / config_dir: optional credential scope threaded to the adapters
                so ${CRED:...} resolves under the right tenant/skill without relying on
                the process-global env (isolated across concurrent resumes).
        """
        self.connections = connections or []
        self._consumer = consumer
        self._config_dir = config_dir
        self._validated = False
        self._errors: List[str] = []

    @classmethod
    def from_merged_config(
        cls,
        agent_connections: Optional[List[dict]] = None,
        skill_connections: Optional[List[dict]] = None,
        consumer: str | None = None,
        config_dir: str | None = None,
    ) -> "MCPToolBridge":
        """
        Create bridge by merging agent-level and skill-level connections.

        Skill connections override agent connections with the same name.

        Args:
            agent_connections: Connections from agent config.yaml
            skill_connections: Connections from SKILL.md frontmatter mcp_connections
            consumer / config_dir: credential scope threaded to the bridge.

        Returns:
            Configured MCPToolBridge instance.
        """
        agent_conns = agent_connections or []
        skill_conns = skill_connections or []

        # Index by name — skill overrides agent for same name
        merged = {c["name"]: c for c in agent_conns}
        for c in skill_conns:
            merged[c["name"]] = c  # Skill takes precedence

        return cls(connections=list(merged.values()), consumer=consumer, config_dir=config_dir)
    
    def validate(self) -> List[str]:
        """
        Validate all connection configs.
        
        Returns:
            List of error strings. Empty means all valid.
        """
        all_errors = []
        for conn in self.connections:
            all_errors.extend(validate_connection(conn))
        self._errors = all_errors
        self._validated = True
        return all_errors
    
    async def get_tools(self) -> List:
        """
        Discover and return tools from all configured MCP connections.
        
        Direct connections use MultiServerMCPClient.
        Registry connections use REST discovery + StructuredTool wrappers.
        
        Returns:
            List of LangChain tool objects (StructuredTool or equivalent).
        """
        if not self.connections:
            return []
        
        # Validate if not already done
        if not self._validated:
            errors = self.validate()
            if errors:
                for err in errors:
                    logger.error(f"MCPToolBridge validation: {err}")
                # Continue with valid connections only
        
        # Partition connections by type
        direct_conns = [c for c in self.connections if c.get("type") == "direct" and not validate_connection(c)]
        registry_conns = [c for c in self.connections if c.get("type") == "registry" and not validate_connection(c)]
        
        all_tools = []
        
        if direct_conns:
            # Collect per-connection tool_filter
            global_filter = []
            for c in direct_conns:
                tf = c.get("tool_filter", [])
                if tf:
                    global_filter.extend(tf)
            
            adapter = DirectAdapter(direct_conns, consumer=self._consumer, config_dir=self._config_dir)
            try:
                tools = await adapter.get_tools(tool_filter=global_filter if global_filter else None)
                all_tools.extend(tools)
            except Exception as e:
                logger.error(f"MCPToolBridge: DirectAdapter failed — {e}")
        
        for conn in registry_conns:
            adapter = RegistryAdapter(conn, consumer=self._consumer, config_dir=self._config_dir)
            try:
                tools = await adapter.get_tools()
                all_tools.extend(tools)
            except Exception as e:
                logger.error(f"MCPToolBridge: RegistryAdapter[{conn.get('name')}] failed — {e}")
        
        # Deduplicate by tool name (first occurrence wins)
        seen_names = set()
        unique_tools = []
        for t in all_tools:
            if t.name not in seen_names:
                seen_names.add(t.name)
                unique_tools.append(t)
            else:
                logger.info(f"MCPToolBridge: skipping duplicate tool '{t.name}'")
        
        logger.info(f"MCPToolBridge: total {len(unique_tools)} unique MCP tools from {len(self.connections)} connection(s)")
        return unique_tools
    
    def get_connection_summary(self) -> dict:
        """
        Return a summary of configured connections for diagnostics.
        
        Returns:
            Dict with connection counts and names by type.
        """
        direct = [c["name"] for c in self.connections if c.get("type") == "direct"]
        registry = [c["name"] for c in self.connections if c.get("type") == "registry"]
        return {
            "total": len(self.connections),
            "direct": direct,
            "registry": registry,
            "errors": self._errors if self._validated else [],
        }
