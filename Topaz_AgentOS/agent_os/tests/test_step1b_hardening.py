"""Regression tests for the Step 1b security hardening.

Each test pins a specific defect found in the adversarial review so it cannot
silently come back:

  * an entitlement DENY was discarded unless EXTERNAL_ACCESS_UNKNOWN_MODE=deny
  * curl target detection only matched `^https?://`, so scheme-less hosts,
    `--url=` forms and non-HTTP schemes skipped governance entirely
  * $CRED_* was substituted into EVERY command, so `echo $CRED_X` leaked plaintext
  * an http resource with no `hosts` silently matched every host
  * there were no SSRF controls at all
"""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "IAF-Agent-Skills"))
sys.path.insert(0, str(ROOT / "IAF-Agent-Studio"))

from agent_os.egress_ssrf import SSRFBlocked, assert_safe_url, is_safe_url  # noqa: E402
from agent_os.external_access import validate_external_access_yaml  # noqa: E402
from agent_os.kernel_runtime import create_kernel_runtime  # noqa: E402

ENTERPRISE_ROOT = ROOT / "enterprise_root"
SAP_URL = "https://localhost:9091/sap/opu/odata/sap/API_CUSTOMER_INVOICE_SRV/x"

ALLOW_ALL = lambda action, rtype, rid, ctx: True   # noqa: E731
DENY_ALL = lambda action, rtype, rid, ctx: False   # noqa: E731


def _egress_kernel(checker, monkeypatch, unknown_mode: str, tenant: str = "company"):
    monkeypatch.setenv("EXTERNAL_ACCESS_ENABLED", "true")
    monkeypatch.setenv("EXTERNAL_ACCESS_UNKNOWN_MODE", unknown_mode)
    kernel = create_kernel_runtime(
        backend="local", data_root=str(ENTERPRISE_ROOT), tenant_id=tenant,
        agent_id="enterprise_agent", user_id="u1", require_confirmation=False,
    )
    kernel.set_entitlement_context(principal={"user_id": "u1"}, checker=checker)
    return kernel


def _check(kernel, argv):
    return kernel._check_http_external_access(argv, "curl " + " ".join(argv))


@pytest.mark.parametrize("unknown_mode", ["audit", "deny"])
def test_entitlement_deny_is_honoured_in_every_mode(monkeypatch, unknown_mode):
    """A registered resource whose entitlement check denies must be refused even
    in audit mode. Previously audit mode discarded the denial while the audit
    record still said allowed=False."""
    kernel = _egress_kernel(DENY_ALL, monkeypatch, unknown_mode)
    allowed, reason = _check(kernel, [SAP_URL])
    assert allowed is False
    assert "denied" in reason.lower()


def test_entitlement_allow_still_passes(monkeypatch):
    kernel = _egress_kernel(ALLOW_ALL, monkeypatch, "deny")
    allowed, _ = _check(kernel, [SAP_URL])
    assert allowed is True


def test_registered_self_api_post_is_allowed(monkeypatch):
    """Mission Mode curls the loopback self-API; it must stay reachable under
    deny, otherwise every cron-driven workstream stops."""
    kernel = _egress_kernel(ALLOW_ALL, monkeypatch, "deny")
    allowed, _ = _check(
        kernel, ["-X", "POST", "http://localhost:8082/api/workstreams/x/iterate"]
    )
    assert allowed is True


@pytest.mark.parametrize("argv", [
    ["example.com/x"],                 # scheme-less: curl prepends http://
    ["--url=https://example.com/x"],   # --url= form
])
def test_previously_undetected_targets_are_governed(monkeypatch, argv):
    kernel = _egress_kernel(ALLOW_ALL, monkeypatch, "deny")
    allowed, reason = _check(kernel, argv)
    assert allowed is False
    assert "not registered" in reason


@pytest.mark.parametrize("target", [
    "file:///etc/passwd",
    "dict://169.254.169.254:80/",
    "gopher://example.com/",
])
def test_non_http_schemes_refused_in_every_mode(monkeypatch, target):
    for mode in ("audit", "deny"):
        kernel = _egress_kernel(ALLOW_ALL, monkeypatch, mode)
        allowed, reason = _check(kernel, [target])
        assert allowed is False, f"{target} allowed in {mode}"
        assert "non-HTTP(S) scheme" in reason


def test_header_values_are_not_mistaken_for_targets(monkeypatch):
    """A header/data value must not be classified as a scheme-less target, or
    legitimate curl calls would break."""
    kernel = _egress_kernel(ALLOW_ALL, monkeypatch, "deny")
    allowed, _ = _check(kernel, ["-H", "Accept: application/json", SAP_URL])
    assert allowed is True


def test_credentials_only_substituted_for_credential_consuming_commands():
    with TemporaryDirectory() as td:
        kernel = create_kernel_runtime(
            backend="local", data_root=td, tenant_id="company",
            agent_id="enterprise_agent", user_id="u1", require_confirmation=False,
        )
        kernel._session_vars["CRED_X_TOKEN"] = "SUPERSECRET123"

        # negative: a non-curl command keeps the placeholder
        assert "SUPERSECRET123" not in kernel._substitute_session_vars("echo $CRED_X_TOKEN")
        assert "SUPERSECRET123" not in kernel._substitute_session_vars("cat $CRED_X_TOKEN")
        # positive: curl still receives the real value
        assert "SUPERSECRET123" in kernel._substitute_session_vars(
            'curl -H "Authorization: Bearer $CRED_X_TOKEN" https://localhost:9091/x'
        )


def test_echo_does_not_leak_credential_end_to_end():
    with TemporaryDirectory() as td:
        kernel = create_kernel_runtime(
            backend="local", data_root=td, tenant_id="company",
            agent_id="enterprise_agent", user_id="u1", require_confirmation=False,
        )
        kernel._session_vars["CRED_X_TOKEN"] = "SUPERSECRET123"
        assert "SUPERSECRET123" not in kernel.run_shell_command("echo $CRED_X_TOKEN", confirmed=True)


def test_http_resource_without_hosts_is_rejected():
    result = validate_external_access_yaml(
        "resources:\n  - id: external:oops\n    type: http\n    paths: ['/x']\n"
    )
    assert result["valid"] is False
    assert any("hosts is required" in e for e in result["errors"])


@pytest.mark.parametrize("tenant", ["company"])
def test_shipped_registries_remain_valid(tenant):
    path = ENTERPRISE_ROOT / "tenants" / tenant / "security" / "external_access.yaml"
    result = validate_external_access_yaml(path.read_text())
    assert result["valid"] is True, result["errors"]


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",
    "https://169.254.169.254.nip.io/",      # DNS-rebind style
    "http://metadata.google.internal/x",
    "http://127.0.0.1:8082/api/x",
    "http://10.0.0.5/x",
    "http://192.168.1.1/x",
    "http://172.16.0.1/x",
    "file:///etc/passwd",
    "dict://169.254.169.254:80/",
    "",
])
def test_ssrf_guard_blocks(url):
    ok, reason = is_safe_url(url)
    assert ok is False, f"{url} was allowed"
    assert reason


def test_ssrf_guard_allows_public_host():
    ok, reason = is_safe_url("https://example.com/x")
    assert ok is True, reason


def test_ssrf_guard_loopback_opt_in():
    """Loopback is blocked by default but permitted for deliberate self-API use."""
    assert is_safe_url("http://127.0.0.1:8082/x")[0] is False
    assert is_safe_url("http://127.0.0.1:8082/x", allow_loopback=True)[0] is True


def test_ssrf_guard_raises_typed_error():
    with pytest.raises(SSRFBlocked):
        assert_safe_url("file:///etc/passwd")
