"""OpenTelemetry integration for AgentOS.

Optional and self-contained: nothing here runs unless TELEMETRY_EXPORTERS includes
`otel`. The local trace store (trace_emitter.py) is unaffected either way.
"""
