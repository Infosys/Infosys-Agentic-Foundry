"""
IAF Agent Studio — Observers subsystem.

Persistent, scoped "observer" agents (Headlong companions) that watch a narrow,
deterministically-enforced scope and request governed AgentOS skill actions
through the existing HITL approval machinery.

Layering (mirrors cc_queue/):
    routers/observers.py  (HTTP)  ->  observers.service  (logic)  ->  observers.store  (persistence)

Pure, independently-testable engines:
    observers.policy    — trust-tier gate
    observers.triggers  — deterministic rule matching
"""
