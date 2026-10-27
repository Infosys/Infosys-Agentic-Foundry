"""Data Privacy platform services.

Implements the platform-buildable Data Privacy (DP) controls required by the
AgentOS-V1.0.0 Privacy Impact Assessment (PIA):

- :mod:`privacy.service` — login privacy notice + mandatory declaration /
  acknowledgement gate (PIA controls 1 & 3). Acceptance is persisted to the
  existing auth audit sink (event ``PRIVACY_ACK_ACCEPTED``); nothing changes
  unless ``PRIVACY_ACK_REQUIRED`` is enabled.
"""
