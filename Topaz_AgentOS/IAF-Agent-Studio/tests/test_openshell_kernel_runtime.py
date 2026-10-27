"""Tests for the optional OpenShell kernel backend (Step 1a).

The OpenShell SDK is not installable on every host (some corporate networks
block PyPI), so the transport is exercised against a stub module registered in
sys.modules — the same technique test_runtime_provider_slots.py uses for
provider slots. What is asserted here:

  * the factory still fails closed on an unknown backend
  * selecting 'openshell' does NOT import the SDK unless it is used
  * the backend satisfies the KernelRuntime protocol
  * AgentOS governance still applies (blocked commands + egress registry) —
    i.e. the sandbox adds isolation without removing policy
  * exec/write_file round-trip through the sandbox session
  * a missing SDK or missing endpoint fails closed with a clear message
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "IAF-Agent-Skills"))
sys.path.insert(0, str(ROOT / "IAF-Agent-Studio"))

from agent_os.kernel_runtime import KernelRuntime, create_kernel_runtime  # noqa: E402
from agent_os.openshell_runtime import OpenShellKernelRuntime  # noqa: E402

ENTERPRISE_ROOT = ROOT / "enterprise_root"
ALLOW_ALL = lambda action, rtype, rid, ctx: True   # noqa: E731


class _ExecResult:
    def __init__(self, exit_code=0, stdout="", stderr=""):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


class _Session:
    """Records what the backend asked the sandbox to run."""

    def __init__(self):
        self.calls: list[dict] = []

    def exec(self, argv, *, workdir=None, stdin=None, timeout_seconds=None, **kw):
        self.calls.append(
            {"argv": list(argv), "workdir": workdir, "stdin": stdin, "timeout": timeout_seconds}
        )
        return _ExecResult(0, stdout="SANDBOX_OK")


def _agent_call(session: _Session) -> dict:
    """The sandbox call carrying the agent's own command.

    Attaching runs one-off tree preparation (`mkdir -p` of the virtual dirs, then a
    `cat >` per staged file), so the agent command is the LAST call, not the first.
    Indexing by position made these tests fragile once staging was added.
    """
    assert session.calls, "nothing reached the sandbox"
    return session.calls[-1]


def _install_stub_sdk(monkeypatch, session):
    """Register a fake `openshell` module mirroring the real SDK surface.

    Shapes verified against openshell 0.1.2: the client is constructed with a
    bare `host:port` target plus an optional TlsConfig, and sessions come from
    `get_session` / `create_session` (there is no `attach`).
    """

    class _Client:
        def __init__(self, endpoint, *, tls=None, bearer_token=None, timeout=30.0, **kw):
            self.endpoint = endpoint
            self.tls = tls
            self.bearer_token = bearer_token

        def get_session(self, name, *, workspace):
            return session

        def create_session(self, *, workspace, name=None, **kw):  # pragma: no cover
            return session

        def wait_ready(self, name, *, workspace, timeout_seconds=300.0):  # pragma: no cover
            return None

    class _TlsConfig:
        def __init__(self, ca_path=None, cert_path=None, key_path=None):
            self.ca_path, self.cert_path, self.key_path = ca_path, cert_path, key_path

    module = types.ModuleType("openshell")
    module.SandboxClient = _Client
    module.TlsConfig = _TlsConfig
    monkeypatch.setitem(sys.modules, "openshell", module)
    return module


def _backend(td, **over):
    kwargs = dict(
        data_root=td, tenant_id="company", agent_id="enterprise_agent",
        user_id="u1", require_confirmation=False,
        endpoint="https://sandbox.invalid:443", token="t0ken",
    )
    kwargs.update(over)
    return OpenShellKernelRuntime(**kwargs)


def test_factory_still_fails_closed_on_unknown_backend():
    with pytest.raises(ValueError, match="AGENTOS_KERNEL_BACKEND"):
        create_kernel_runtime(backend="not-a-backend", data_root="/tmp")


def test_factory_default_is_unchanged_local():
    with TemporaryDirectory() as td:
        runtime = create_kernel_runtime(
            backend="local", data_root=td, tenant_id="company",
            agent_id="enterprise_agent", user_id="u1",
        )
        assert type(runtime).__name__ == "LocalKernelRuntime"


def test_factory_builds_openshell_without_importing_sdk(monkeypatch):
    """Selecting the backend must not require the SDK — only *using* it does."""
    monkeypatch.delitem(sys.modules, "openshell", raising=False)
    with TemporaryDirectory() as td:
        runtime = create_kernel_runtime(
            backend="openshell", data_root=td, tenant_id="company",
            agent_id="enterprise_agent", user_id="u1",
        )
        assert isinstance(runtime, OpenShellKernelRuntime)
        assert "openshell" not in sys.modules


def test_backend_satisfies_kernel_runtime_protocol():
    with TemporaryDirectory() as td:
        assert isinstance(_backend(td), KernelRuntime)


def test_blocked_command_is_refused_before_reaching_sandbox(monkeypatch):
    session = _Session()
    _install_stub_sdk(monkeypatch, session)
    with TemporaryDirectory() as td:
        out = _backend(td).run_shell_command("python3 -c 'print(1)'", confirmed=True)
    assert "COMMAND_BLOCKED" in out
    assert session.calls == [], "blocked command must never be executed in the sandbox"


def test_unregistered_egress_is_refused_before_reaching_sandbox(monkeypatch):
    session = _Session()
    _install_stub_sdk(monkeypatch, session)
    monkeypatch.setenv("EXTERNAL_ACCESS_ENABLED", "true")
    monkeypatch.setenv("EXTERNAL_ACCESS_UNKNOWN_MODE", "deny")
    runtime = _backend(str(ENTERPRISE_ROOT))
    runtime.set_entitlement_context(principal=None, checker=ALLOW_ALL)
    out = runtime.run_shell_command("curl https://example.com/x", confirmed=True)
    assert "EXTERNAL_ACCESS_DENIED" in out
    assert session.calls == []


def test_registered_egress_reaches_the_sandbox(monkeypatch):
    session = _Session()
    _install_stub_sdk(monkeypatch, session)
    monkeypatch.setenv("EXTERNAL_ACCESS_ENABLED", "true")
    monkeypatch.setenv("EXTERNAL_ACCESS_UNKNOWN_MODE", "deny")
    runtime = _backend(str(ENTERPRISE_ROOT))
    runtime.set_entitlement_context(principal=None, checker=ALLOW_ALL)
    url = "https://localhost:9091/sap/opu/odata/sap/API_CUSTOMER_INVOICE_SRV/x"
    out = runtime.run_shell_command(f"curl {url}", confirmed=True)
    assert out == "SANDBOX_OK"
    # Exactly one *agent* command reached the sandbox (earlier calls are tree prep).
    assert _agent_call(session)["argv"][2].startswith("curl ")


def test_shell_command_runs_in_sandbox(monkeypatch):
    session = _Session()
    _install_stub_sdk(monkeypatch, session)
    with TemporaryDirectory() as td:
        out = _backend(td).run_shell_command("ls /workspace", confirmed=True)
    assert out == "SANDBOX_OK"
    call = _agent_call(session)
    assert call["argv"][:2] == ["/bin/sh", "-lc"]
    # /workspace is a virtual path and must be rewritten to the sandbox root.
    assert "ls /sandbox/workspace" in call["argv"][2]


def test_write_file_streams_content_via_stdin(monkeypatch):
    session = _Session()
    _install_stub_sdk(monkeypatch, session)
    with TemporaryDirectory() as td:
        out = _backend(td).write_file("/workspace/a/b.txt", "hello")
    assert "Wrote 5 bytes" in out
    call = _agent_call(session)
    assert call["stdin"] == b"hello"
    assert "mkdir -p" in call["argv"][2]
    assert "b.txt" in call["argv"][2]


def test_virtual_dirs_are_created_before_the_first_agent_command(monkeypatch):
    """The sandbox FS starts empty, so /shared, /workspace, … must be made first."""
    session = _Session()
    _install_stub_sdk(monkeypatch, session)
    with TemporaryDirectory() as td:
        _backend(td).run_shell_command("ls /workspace", confirmed=True)
    prep = session.calls[0]["argv"][2]
    assert prep.startswith("mkdir -p ")
    for virtual in ("shared", "workspace", "memory"):
        assert f"/sandbox/{virtual}" in prep


def test_exec_failure_is_returned_as_error_string(monkeypatch):
    class _FailSession(_Session):
        def exec(self, argv, **kw):
            return _ExecResult(2, stderr="boom")

    session = _FailSession()
    _install_stub_sdk(monkeypatch, session)
    with TemporaryDirectory() as td:
        out = _backend(td).run_shell_command("ls /nope", confirmed=True)
    assert "KERNEL_OPENSHELL" in out and "boom" in out


def test_missing_sdk_fails_closed(monkeypatch):
    monkeypatch.setitem(sys.modules, "openshell", None)  # import raises
    with TemporaryDirectory() as td:
        out = _backend(td).run_shell_command("ls", confirmed=True)
    assert "KERNEL_OPENSHELL" in out
    assert "not installed" in out or "SDK" in out


def test_missing_endpoint_fails_closed(monkeypatch):
    session = _Session()
    _install_stub_sdk(monkeypatch, session)
    monkeypatch.delenv("AGENTOS_SANDBOX_URL", raising=False)
    with TemporaryDirectory() as td:
        out = _backend(td, endpoint="").run_shell_command("ls", confirmed=True)
    assert "AGENTOS_SANDBOX_URL" in out
    assert session.calls == []


def test_health_never_exposes_the_token(monkeypatch):
    with TemporaryDirectory() as td:
        snap = _backend(td).snapshot()
    assert "t0ken" not in str(snap)
    assert snap["backend"] == "openshell"


@pytest.mark.parametrize(
    "command, expected",
    [
        ("ls /workspace", "ls /sandbox/workspace"),
        ("cat /shared/databases/_index.md", "cat /sandbox/shared/databases/_index.md"),
        ("head -2 /memory/notes.md", "head -2 /sandbox/memory/notes.md"),
        ("cat '/shared/a b.md'", "cat '/sandbox/shared/a b.md'"),
        # Negative cases: these must NOT be rewritten.
        ("cat /etc/passwd", "cat /etc/passwd"),
        ("cat /sharedstuff/x", "cat /sharedstuff/x"),
        ("echo /opt/shared/x", "echo /opt/shared/x"),
    ],
)
def test_virtual_paths_are_translated(monkeypatch, command, expected):
    """`run_shell_command` must rewrite virtual paths the way the local kernel does.

    The sandbox takes paths literally, so an untranslated `/shared/...` is simply
    absent inside the guest. Only a leading, whole-segment virtual prefix is rewritten.
    """
    session = _Session()
    _install_stub_sdk(monkeypatch, session)
    with TemporaryDirectory() as td:
        _backend(td).run_shell_command(command, confirmed=True)
    assert _agent_call(session)["argv"][2].strip() == expected


def test_recursive_staging_preserves_directory_structure(monkeypatch, tmp_path):
    """`**` staging must keep subdirectories distinct, not flatten them.

    Flattening would collapse same-named files from different folders onto one
    another — e.g. contexts/exceptions/doc.md and contexts/judgment/doc.md.
    """
    shared = tmp_path / "shared" / "contexts"
    (shared / "exceptions").mkdir(parents=True)
    (shared / "judgment").mkdir(parents=True)
    (shared / "exceptions" / "doc.md").write_text("EXC")
    (shared / "judgment" / "doc.md").write_text("JUD")

    session = _Session()
    _install_stub_sdk(monkeypatch, session)
    monkeypatch.setenv("AGENTOS_SANDBOX_STAGE", "/shared/contexts/**/*.md")
    runtime = _backend(str(tmp_path))
    monkeypatch.setattr(runtime._policy, "_resolve_path", lambda p: str(tmp_path / p.lstrip("/")))
    runtime.run_shell_command("true", confirmed=True)

    staged = {
        c["argv"][2].split("cat > ")[1].split(" ")[0]: c["stdin"]
        for c in session.calls
        if "cat > " in c["argv"][2]
    }
    assert staged == {
        "/sandbox/shared/contexts/exceptions/doc.md": b"EXC",
        "/sandbox/shared/contexts/judgment/doc.md": b"JUD",
    }
    # Staged files are read-only inside the sandbox.
    assert all("chmod 444" in c["argv"][2] for c in session.calls if "cat > " in c["argv"][2])
