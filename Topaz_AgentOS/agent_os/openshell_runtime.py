"""OpenShell kernel backend — execute agent commands inside an NVIDIA OpenShell sandbox.

Selected with ``AGENTOS_KERNEL_BACKEND=openshell``. Default stays ``local``, so
existing deployments are untouched and the OpenShell SDK is imported lazily —
nothing here loads unless the backend is actually chosen.

Why a *composed* backend rather than a pure proxy
-------------------------------------------------
OpenShell gives OS-level containment (kernel-enforced filesystem/syscall limits
and a policy-checked network boundary). It does NOT know about AgentOS
governance: the blocked-command list, the tenant ``external_access.yaml``
registry, entitlements, or the audit trail. A backend that simply forwarded
every string to ``session.exec`` would therefore *improve* isolation while
*removing* governance — a net regression.

So this class composes the two:

    policy  →  a local SafeKernel instance used ONLY to make decisions
               (blocked commands, egress registry, audit). It never executes
               agent commands itself.
    exec    →  the OpenShell sandbox, which provides the real boundary.

Recommended alternative (no code in this file)
----------------------------------------------
For full governance parity, run the existing ``IAF-Agent-Studio/kernel_worker.py``
*inside* the OpenShell sandbox image and point the already-shipped
``remote`` backend at it (``AGENTOS_KERNEL_BACKEND=remote`` +
``AGENTOS_KERNEL_URL=<sandbox service>``). That composition gets OpenShell's
isolation and an unmodified SafeKernel — with zero new adapter code. This module
exists for the case where you want OpenShell's own policy engine to be the
boundary and do not want an AgentOS worker in the image.

Status: the OpenShell Python SDK is not installable on every host (some corporate
networks block PyPI), so this backend fails closed with an explicit message
rather than degrading to in-process execution.
"""

from __future__ import annotations

import logging
import os
import posixpath
import re
import shlex
from pathlib import Path
from typing import Any

from .kernel_runtime import LocalKernelRuntime, _principal_to_dict
from .safe_path import SecurityError, validated_path

logger = logging.getLogger(__name__)

# Shell control operators are rejected so chaining cannot slip past the first-token policy check.
_SHELL_CONTROL_RE = re.compile(r"[;&|<>`\n]|\$[({]")

# OpenShell's guest init prepares /sandbox and sets it as the sandbox user's HOME
# (there is no /workspace), so virtual paths map under it by default.
DEFAULT_SANDBOX_ROOT = "/sandbox"

# AgentOS virtual-path prefixes are rewritten to sandbox-local paths; the guest does not know /shared etc.
VIRTUAL_PREFIXES = ("shared", "workspace", "memory", "me", "local", "global")
_ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_VIRTUAL_PATH_RE = re.compile(
    r"(?<![\w/])/(" + "|".join(VIRTUAL_PREFIXES) + r")(?=/|\s|['\"]|$)"
)


class OpenShellUnavailable(RuntimeError):
    """Raised when the OpenShell SDK or gateway cannot be reached."""


class OpenShellKernelRuntime:
    """KernelRuntime backed by an OpenShell sandbox for execution."""

    def __init__(
        self,
        *,
        data_root: str = "./data",
        tenant_id: str = "company",
        agent_id: str = "enterprise_agent",
        user_id: str | None = None,
        user_role: str = "user",
        require_confirmation: bool = False,
        confirm_operations: list[str] | None = None,
        confirm_paths: list[str] | None = None,
        local_mount: str | None = None,
        endpoint: str | None = None,
        token: str | None = None,
        workspace: str | None = None,
        sandbox_name: str | None = None,
        sandbox_root: str | None = None,
        timeout_seconds: int | None = None,
        tls_ca: str | None = None,
        tls_cert: str | None = None,
        tls_key: str | None = None,
        **_extra: Any,
    ) -> None:
        self.data_root = Path(data_root).resolve()
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.user_id = user_id
        self.user_role = user_role
        self.require_confirmation = require_confirmation
        self.confirm_operations = confirm_operations or ["write", "delete"]
        self.confirm_paths = confirm_paths
        self.local_mount = Path(local_mount).resolve() if local_mount else None
        self.tenant_root = self.data_root / "tenants" / tenant_id
        self.agent_root = self.tenant_root / "agents" / agent_id
        self.shared_path = self.tenant_root / "shared"
        self.global_shared = self.data_root / "global_shared"
        self.current_skill: str | None = None

        # gRPC wants a bare host:port, so strip the URL scheme from config values.
        _raw_endpoint = (endpoint or os.getenv("AGENTOS_SANDBOX_URL", "")).strip()
        for _scheme in ("https://", "http://", "grpc://", "grpcs://"):
            if _raw_endpoint.lower().startswith(_scheme):
                _raw_endpoint = _raw_endpoint[len(_scheme):]
                break
        self._endpoint = _raw_endpoint.rstrip("/")
        self._token = token or os.getenv("AGENTOS_SANDBOX_TOKEN", "").strip()
        self._workspace = workspace or os.getenv("AGENTOS_SANDBOX_WORKSPACE", "default").strip()
        self._sandbox_root = (sandbox_root or os.getenv("AGENTOS_SANDBOX_ROOT", DEFAULT_SANDBOX_ROOT)).rstrip("/")
        self._timeout = int(
            timeout_seconds
            if timeout_seconds is not None
            else os.getenv("AGENTOS_SANDBOX_TIMEOUT_SECONDS", "120")
        )
        # mTLS client materials; the gateway requires an auth mechanism.
        self._tls_ca = tls_ca or os.getenv("AGENTOS_SANDBOX_TLS_CA", "").strip()
        self._tls_cert = tls_cert or os.getenv("AGENTOS_SANDBOX_TLS_CERT", "").strip()
        self._tls_key = tls_key or os.getenv("AGENTOS_SANDBOX_TLS_KEY", "").strip()
        # One sandbox per (tenant, agent, user); overrides only act as a name prefix.
        _identity = f"agentos-{tenant_id}-{agent_id}-{(user_id or 'anon')}".lower().replace("_", "-")
        _override = (sandbox_name or os.getenv("AGENTOS_SANDBOX_NAME", "")).strip()
        self._sandbox_name = (
            f"{_override.lower().replace('_', '-')}-{_identity}" if _override else _identity
        )
        self._session: Any = None
        self._principal: dict[str, Any] | None = None
        self._tree_ready = False
        # Files staged read-only into the otherwise empty sandbox, as virtual paths (comma-separated, `*` glob on filename).
        self._stage_paths = [
            s.strip() for s in os.getenv("AGENTOS_SANDBOX_STAGE", "").split(",") if s.strip()
        ]

        # Policy-only kernel: reuses SafeKernel governance, never executes commands.
        self._policy = LocalKernelRuntime(
            data_root=data_root,
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
            user_role=user_role,
            require_confirmation=False,
            confirm_operations=confirm_operations,
            confirm_paths=confirm_paths,
            local_mount=local_mount,
        )

    def set_entitlement_context(self, principal=None, checker=None):
        self._principal = _principal_to_dict(principal)
        # The governance gates live on the policy kernel, so the context must
        # reach it or every entitlement/egress check would silently pass.
        self._policy.set_entitlement_context(principal=principal, checker=checker)

    def attach_hook_runner(self, *args, **kwargs):
        # Hook runners are in-process callables around the tool layer; they stay
        # host-side. Mirrors RemoteKernelRuntime.attach_hook_runner.
        return None

    def run_shell_command(self, command: str, confirmed: bool = False) -> str:
        self._policy.current_skill = self.current_skill
        # Policy is judged on the ORIGINAL command so the egress registry and the
        # blocked-command list see exactly what the skill asked for.
        verdict = self._policy_verdict(command)
        if verdict:
            return verdict
        # Credentials are exported as shell-quoted assignments ahead of the command, never spliced into its text.
        script = self._translate_virtual_paths(command)
        try:
            script = self._credential_exports(command) + script
        except Exception:
            pass
        try:
            return self._exec(["/bin/sh", "-lc", script])
        except OpenShellUnavailable as exc:
            return f"Error [KERNEL_OPENSHELL]: {exc}"

    def _credential_exports(self, command: str) -> str:
        """Shell-quoted `export NAME=value; ` prefix for session credentials.

        Mirrors SafeKernel._substitute_session_vars scoping: only commands that
        are allowed to consume credentials get them.
        """
        session_vars = getattr(self._policy, "_session_vars", None) or {}
        if not session_vars or not self._policy._command_allows_credentials(command):
            return ""
        parts = []
        for name, value in session_vars.items():
            if not _ENV_NAME_RE.fullmatch(str(name)):
                continue
            parts.append(f"export {name}={shlex.quote(str(value))}; ")
        return "".join(parts)

    def _translate_virtual_paths(self, command: str) -> str:
        """Rewrite AgentOS virtual-path prefixes to their sandbox-local equivalents.

        `/shared/x` → `/sandbox/shared/x`, `/workspace/y` → `/sandbox/workspace/y`, …
        This is the sandbox counterpart of SafeKernel._resolve_path(); the local
        backend does the same translation to real tenant directories.
        """
        if not command:
            return command
        return _VIRTUAL_PATH_RE.sub(lambda m: f"{self._sandbox_root}/{m.group(1)}", command)

    def write_file(self, virtual_path: str, content: bytes | str, append: bool = False) -> str:
        payload = content.encode("utf-8") if isinstance(content, str) else content
        # Normalise before the policy check so `..` cannot bypass _is_writable.
        virtual_path = posixpath.normpath("/" + str(virtual_path).lstrip("/"))
        # Mirror the local backend's write policy: read-only prefixes (/shared,
        # /global, …) must stay read-only here too, not writable via the sandbox.
        if not self._policy._is_writable(virtual_path):
            return f"Error [WRITE_DENIED]: {virtual_path} is read-only"
        try:
            target = self._sandbox_path(virtual_path)  # contained; raises on traversal
        except ValueError as exc:
            return f"Error [PATH_DENIED]: {exc}"
        redirect = ">>" if append else ">"
        script = f"mkdir -p {shlex.quote(posixpath.dirname(target))} && cat {redirect} {shlex.quote(target)}"
        try:
            result = self._exec(["/bin/sh", "-lc", script], stdin=payload)
        except OpenShellUnavailable as exc:
            return f"Error [KERNEL_OPENSHELL]: {exc}"
        # A nonzero guest exit comes back as an error string from _exec — surface it
        # instead of falsely reporting success.
        if isinstance(result, str) and result.startswith("Error [KERNEL_OPENSHELL]:"):
            return result
        return f"Wrote {len(payload)} bytes to {virtual_path}"

    def _resolve_path(self, virtual_path: str) -> Path:
        """Host-side path resolution for legacy readback callers.

        Delegates to the policy kernel so virtual-path semantics stay identical
        to the local backend (RemoteKernelRuntime re-implements this for the same
        reason — some callers expect a Path back after a tool call).
        """
        return self._policy._resolve_path(virtual_path)

    def health(self) -> dict[str, Any]:
        return {
            "backend": "openshell",
            "endpoint": self._endpoint or "(unset)",
            "workspace": self._workspace,
            "sandbox": self._sandbox_name,
            "attached": self._session is not None,
            "sdk_available": self._sdk_available(),
        }

    def snapshot(self) -> dict[str, Any]:
        # Redacted by construction: never include the token.
        return self.health()

    def _policy_verdict(self, command: str) -> str:
        """Return an error string when AgentOS governance refuses the command.

        Intentionally narrow: the sandbox is the containment boundary, so this
        only enforces the decisions the sandbox cannot make for us — the
        blocked-command list and the tenant's egress registry.
        """
        clean = (command or "").strip()
        if not clean:
            return "Error: empty command"
        # Reject shell control operators outright; a first-token verdict cannot see past `;`.
        if _SHELL_CONTROL_RE.search(clean):
            return (
                "Error [COMMAND_BLOCKED]: shell operators (; | & < > ` $() ${}) are not "
                "permitted — run a single command"
            )
        head = clean.split(None, 1)[0]
        blocked = getattr(self._policy, "BLOCKED_COMMANDS", {}) or {}
        if head in blocked:
            reason = blocked[head] if isinstance(blocked, dict) else "not permitted"
            return f"Error [COMMAND_BLOCKED]: '{head}' {reason}"
        if head == "curl":
            try:
                args = shlex.split(clean)[1:]
            except ValueError:
                return "Error [CURL_BLOCKED]: unparseable curl command"
            allowed, why = self._policy._check_http_external_access(args, clean)
            if not allowed:
                return f"Error [EXTERNAL_ACCESS_DENIED]: {why}"
        return ""

    def _sandbox_path(self, virtual_path: str) -> str:
        # Normalise `..` so the write cannot escape the sandbox root.
        rooted = f"{self._sandbox_root}/{str(virtual_path).lstrip('/')}"
        norm = posixpath.normpath(rooted)
        root = posixpath.normpath(self._sandbox_root)
        if norm != root and not norm.startswith(root + "/"):
            raise ValueError(f"path escapes sandbox root: {virtual_path!r}")
        return norm

    def database_allowed(self, database: str, operation: str = "read") -> tuple[bool, str]:
        # Delegate the SQL entitlement gate to the policy kernel; a missing gate would be read as permission.
        return self._policy.database_allowed(database, operation)

    @staticmethod
    def _sdk_available() -> bool:
        try:
            import openshell  # noqa: F401
            return True
        except Exception:
            return False

    def _client(self):
        """Lazily build the OpenShell SDK client. Fails closed."""
        if not self._endpoint:
            raise OpenShellUnavailable(
                "AGENTOS_SANDBOX_URL is not set; refusing to execute (fail-closed)"
            )
        try:
            from openshell import SandboxClient, TlsConfig  # type: ignore
        except Exception as exc:  # SDK genuinely absent
            raise OpenShellUnavailable(
                f"the 'openshell' SDK is not installed ({exc}). Install it "
                f"(`uv add openshell`) or select a different AGENTOS_KERNEL_BACKEND."
            ) from exc
        kwargs: dict[str, Any] = {"timeout": float(self._timeout)}
        if self._tls_cert and self._tls_key:
            # TlsConfig calls read_bytes(), so it needs Paths, not strings.
            try:
                ca_path = validated_path(self._tls_ca, label="AGENTOS_SANDBOX_TLS_CA") if self._tls_ca else None
                cert_path = validated_path(self._tls_cert, label="AGENTOS_SANDBOX_TLS_CERT")
                key_path = validated_path(self._tls_key, label="AGENTOS_SANDBOX_TLS_KEY")
            except SecurityError as exc:
                raise OpenShellUnavailable(f"invalid sandbox TLS path ({exc})") from exc
            kwargs["tls"] = TlsConfig(ca_path=ca_path, cert_path=cert_path, key_path=key_path)
        if self._token:
            kwargs["bearer_token"] = self._token
        try:
            return SandboxClient(self._endpoint, **kwargs)
        except Exception as exc:
            raise OpenShellUnavailable(f"cannot reach the OpenShell gateway: {exc}") from exc

    def _attach(self):
        """Attach to this runtime's sandbox session, creating it on first use.

        `get_session` reuses an existing sandbox so repeated tool calls land in the
        same filesystem; `create_session` provisions one the first time. Both are
        workspace-scoped, which is what keeps tenants from sharing a sandbox.
        """
        if self._session is not None:
            return self._session
        client = self._client()
        try:
            self._session = client.get_session(self._sandbox_name, workspace=self._workspace)
        except Exception:
            try:
                self._session = client.create_session(
                    workspace=self._workspace, name=self._sandbox_name
                )
                # VM provisioning (image prep + libkrun boot) is not instant.
                client.wait_ready(
                    self._sandbox_name,
                    workspace=self._workspace,
                    timeout_seconds=float(max(self._timeout, 120)),
                )
            except Exception as exc:
                raise OpenShellUnavailable(
                    f"cannot attach or create sandbox {self._sandbox_name!r}: {exc}"
                ) from exc
        self._prepare_sandbox_tree()
        return self._session

    def _prepare_sandbox_tree(self) -> None:
        """Create the virtual-path directories and stage any declared read-only files.

        Runs once per attach and is best-effort: a staging failure must not take the
        whole run down, since the governed tools (run_sql_query / fetch_canonical) are
        the primary data path and stay host-side regardless.
        """
        if self._tree_ready:
            return
        self._tree_ready = True
        dirs = " ".join(f"{self._sandbox_root}/{p}" for p in VIRTUAL_PREFIXES)
        try:
            self._exec(["/bin/sh", "-lc", f"mkdir -p {dirs}"])
        except OpenShellUnavailable as exc:
            logger.warning("openshell: could not create virtual dirs: %s", exc)
            return
        for spec in self._stage_paths:
            try:
                self._stage_one(spec)
            except Exception as exc:  # best-effort
                logger.warning("openshell: staging %s failed: %s", spec, exc)

    def _stage_one(self, virtual_glob: str) -> None:
        """Copy host file(s) matching a virtual path into the sandbox, read-only.

        Supports `*` and recursive `**`. The directory structure *below the glob base*
        is preserved, so `/shared/contexts/**/*.md` lands nested files at their real
        virtual paths rather than flattening them into one directory (flattening would
        also silently drop same-named files from different folders).
        """
        if "*" in virtual_glob:
            vbase, pattern = virtual_glob.split("*", 1)[0].rstrip("/"), None
            pattern = virtual_glob[len(vbase):].lstrip("/")
        else:
            vbase, pattern = virtual_glob, None

        host_base = Path(self._policy._resolve_path(vbase))
        if pattern:
            if not host_base.is_dir():
                logger.info("openshell: stage base %s is not a directory", vbase)
                return
            matches = sorted(p for p in host_base.glob(pattern) if p.is_file())
        else:
            matches = [host_base] if host_base.is_file() else []

        if not matches:
            logger.info("openshell: nothing to stage for %s", virtual_glob)
            return

        for src in matches:
            if pattern:
                rel = src.relative_to(host_base).as_posix()
                target = f"{self._translate_virtual_paths(vbase)}/{rel}"
            else:
                target = self._translate_virtual_paths(vbase)
            quoted = shlex.quote(target)
            parent = shlex.quote(target.rsplit("/", 1)[0])
            self._exec(
                [
                    "/bin/sh",
                    "-lc",
                    f"mkdir -p {parent} && cat > {quoted} && chmod 444 {quoted}",
                ],
                stdin=src.read_bytes(),
            )
            logger.info("openshell: staged %s (read-only)", target)

    def _exec(self, argv: list[str], stdin: bytes | None = None) -> str:
        session = self._attach()
        try:
            result = session.exec(
                argv,
                workdir=self._sandbox_root,
                stdin=stdin,
                timeout_seconds=self._timeout,
            )
        except Exception as exc:
            raise OpenShellUnavailable(f"sandbox exec failed: {exc}") from exc
        stdout = getattr(result, "stdout", "") or ""
        stderr = getattr(result, "stderr", "") or ""
        code = int(getattr(result, "exit_code", 0) or 0)
        if code != 0:
            return f"Error [KERNEL_OPENSHELL]: exit {code}: {(stderr or stdout).strip()[:800]}"
        return stdout if stdout else stderr
