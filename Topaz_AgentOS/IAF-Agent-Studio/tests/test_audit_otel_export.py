"""Security audit decisions can be exported as OpenTelemetry log records (for a SIEM).

TELEMETRY_EXPORT_AUDIT: off (default) emits nothing, `denials` only denied decisions,
`all` everything. Records go to the non-propagating `agentos.audit` logger, which the
OTel log handler is attached to — they must never leak into the normal app log.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_os.audit_log import AUDIT_LOGGER, emit_audit  # noqa: E402

DENY = {"tenant_id": "company", "user_id": "u1", "action": "use", "resource": "skill:x",
        "allowed": False, "reason": "deny-rule", "matched_policy": "p1"}
ALLOW = {**DENY, "allowed": True, "reason": "allow-rule"}


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def captured():
    h = _Capture()
    AUDIT_LOGGER.addHandler(h)
    yield h
    AUDIT_LOGGER.removeHandler(h)


@pytest.mark.parametrize("mode,expected", [("off", 0), ("denials", 1), ("all", 2)])
def test_modes(monkeypatch, captured, mode, expected):
    monkeypatch.setenv("TELEMETRY_EXPORT_AUDIT", mode)
    emit_audit("entitlement_decision", DENY)
    emit_audit("entitlement_decision", ALLOW)
    assert len(captured.records) == expected


def test_record_carries_structured_attributes(monkeypatch, captured):
    monkeypatch.setenv("TELEMETRY_EXPORT_AUDIT", "denials")
    emit_audit("external_access", DENY)
    rec = captured.records[0]
    assert rec.levelno == logging.WARNING
    assert getattr(rec, "agentos.audit.category") == "external_access"
    assert getattr(rec, "agentos.audit.allowed") is False
    assert getattr(rec, "agentos.audit.matched_policy") == "p1"


def test_audit_records_do_not_reach_the_app_log(monkeypatch):
    monkeypatch.setenv("TELEMETRY_EXPORT_AUDIT", "all")
    root = _Capture()
    logging.getLogger().addHandler(root)
    try:
        emit_audit("entitlement_decision", DENY)
    finally:
        logging.getLogger().removeHandler(root)
    assert not root.records, "audit records leaked into the root/app log"


def test_otel_log_handler_exports_audit_record(monkeypatch):
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.instrumentation.logging.handler import LoggingHandler
    from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor
    from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter

    exporter = InMemoryLogRecordExporter()
    lp = LoggerProvider()
    lp.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    handler = LoggingHandler(level=logging.INFO, logger_provider=lp)
    AUDIT_LOGGER.addHandler(handler)
    monkeypatch.setenv("TELEMETRY_EXPORT_AUDIT", "denials")
    try:
        emit_audit("entitlement_decision", DENY)
    finally:
        AUDIT_LOGGER.removeHandler(handler)
    logs = exporter.get_finished_logs()
    assert len(logs) == 1
    attrs = dict(logs[0].log_record.attributes)
    assert attrs["agentos.audit.category"] == "entitlement_decision"
    assert attrs["agentos.audit.allowed"] is False
