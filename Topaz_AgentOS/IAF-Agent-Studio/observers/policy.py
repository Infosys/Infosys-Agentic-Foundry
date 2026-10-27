"""
Observers — trust-tier policy engine.

Pure, no-I/O gate that decides whether an observer may trigger a given skill,
and whether the action must be forced to human approval. Modeled on the pure
`iaf_agent_skills.approval_rules.evaluate_rules` — unit-testable in isolation.

Decision precedence:
  1. deny        — the tier forbids this skill outright.
  2. force_human — allowed, but approval is forced to human regardless of ask.
  3. allow       — allowed at the requested approval level.
"""

from dataclasses import dataclass
from typing import List, Optional

from observers.models import Approval, TrustTier

# Skills every tier may always trigger (pure notification, no side effects).
NOTIFY_SKILLS = frozenset({"notify"})

# Low-risk skills auto_act may run without human approval; keep small.
AUTO_ACT_LOW_RISK = frozenset({"notify"})


@dataclass(frozen=True)
class PolicyDecision:
    allow: bool
    approval: Approval          # effective approval level if allowed
    reason: str = ""

    @property
    def denied(self) -> bool:
        return not self.allow


def evaluate(
    trust_tier: TrustTier,
    skill: str,
    requested_approval: Approval,
    allowed_skills: Optional[List[str]] = None,
) -> PolicyDecision:
    """Return the policy decision for (tier, skill, requested_approval).

    `allowed_skills` is the observer's effective allowlist (the caller derives it from
    the trigger skills when the spec leaves it empty, and denies outright when neither
    is configured). When non-empty, a skill not in it (and not a NOTIFY skill) is
    denied regardless of tier.
    """
    allowed_skills = allowed_skills or []

    # Explicit allowlist gate (notify is always permitted).
    if allowed_skills and skill not in allowed_skills and skill not in NOTIFY_SKILLS:
        return PolicyDecision(
            allow=False,
            approval=requested_approval,
            reason=f"skill '{skill}' not in observer allowlist",
        )

    # Per-tier rules.
    if trust_tier == TrustTier.observe_only:
        if skill in NOTIFY_SKILLS:
            return PolicyDecision(True, Approval.auto, "observe_only: notify permitted")
        return PolicyDecision(
            False, requested_approval,
            "observe_only: may only trigger notify",
        )

    if trust_tier == TrustTier.recommend:
        # Allowed, but never auto — always route to a human.
        return PolicyDecision(True, Approval.human, "recommend: forced human approval")

    if trust_tier == TrustTier.auto_act:
        if skill in AUTO_ACT_LOW_RISK:
            return PolicyDecision(True, requested_approval, "auto_act: low-risk skill")
        # Non-low-risk skills still need a human even for an auto_act observer.
        return PolicyDecision(True, Approval.human, "auto_act: non-low-risk forced human")

    if trust_tier == TrustTier.supervised:
        # Any permitted skill, but always human approval.
        return PolicyDecision(True, Approval.human, "supervised: forced human approval")

    # Unknown tier — fail closed: deny (a malformed/future tier must not be permitted,
    # even with human approval).
    return PolicyDecision(False, requested_approval, "unknown tier: denied")
