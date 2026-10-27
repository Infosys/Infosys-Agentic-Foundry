"""
Observers — deterministic trigger engine.

Pure, no-I/O rule matcher. Given an observer spec and a single trajectory
event, it returns the ActRequests that should fire, honoring per-rule cooldown.
Cooldown state is passed in and returned (never stored inside) so the engine
stays pure and unit-testable — the same design as the ESAA Tier-1 rules.

Two rule forms (see observers.models.TriggerRule):
  - threshold: field / op / value   (numeric or string comparison)
  - pattern:   regex matched against the event's text
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from observers.models import ActRequest, ObserverSpec, TriggerRule

CooldownState = Dict[str, float]

_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def _event_text(event: Dict[str, Any]) -> str:
    """Best-effort text view of a trajectory event for pattern/field search."""
    for key in ("content", "text", "message"):
        val = event.get(key)
        if isinstance(val, str) and val:
            return val
    return json.dumps(event, default=str)


def _extract_field(event: Dict[str, Any], field: str) -> Optional[str]:
    """Pull a field value: prefer a structured key, else parse `field=..`/
    `field: ..`/`"field": ..` out of the event text."""
    if field in event and event[field] is not None:
        return str(event[field])
    text = _event_text(event)
    m = re.search(
        rf'["\']?{re.escape(field)}["\']?\s*[=:]\s*["\']?([^\s,"\'}}]+)',
        text,
    )
    return m.group(1) if m else None


def _to_number(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    m = _NUM_RE.search(str(raw))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _compare(actual: Any, op: str, expected: Any) -> bool:
    """Numeric compare when both coerce to numbers, else string compare."""
    a_num, e_num = _to_number(actual), _to_number(expected)
    a: Any
    e: Any
    if a_num is not None and e_num is not None:
        a, e = a_num, e_num
    else:
        a, e = str(actual), str(expected)
    if op in (">=",):
        return a >= e
    if op in (">",):
        return a > e
    if op in ("<=",):
        return a <= e
    if op in ("<",):
        return a < e
    if op in ("==", "="):
        return a == e
    if op in ("!=", "<>"):
        return a != e
    return False


def _render(template: str, mapping: Dict[str, Any]) -> str:
    """Safe `{key}` substitution — unknown keys left intact."""
    if not template:
        return template

    def _sub(m: "re.Match[str]") -> str:
        key = m.group(1)
        return str(mapping.get(key, m.group(0)))

    return re.sub(r"\{(\w+)\}", _sub, template)


class TriggerEngine:
    """Stateless evaluator. All state (cooldown) flows through arguments."""

    @staticmethod
    def _rule_key(observer: str, rule: TriggerRule, index: int) -> str:
        return f"{observer}:{rule.name or index}"

    def match(
        self,
        spec: ObserverSpec,
        event: Dict[str, Any],
        cooldown_state: Optional[CooldownState] = None,
        now: float = 0.0,
    ) -> Tuple[List[ActRequest], CooldownState]:
        """Evaluate every rule against one event.

        Returns (fired_requests, new_cooldown_state). Does not mutate the input
        cooldown_state.
        """
        new_state: CooldownState = dict(cooldown_state or {})
        fired: List[ActRequest] = []
        text = _event_text(event)

        for idx, rule in enumerate(spec.triggers):
            matched_value: Optional[str] = None

            if rule.pattern:
                m = re.search(rule.pattern, text)
                if not m:
                    continue
                matched_value = m.group(0)
            elif rule.field and rule.op is not None:
                actual = _extract_field(event, rule.field)
                if actual is None or not _compare(actual, rule.op, rule.value):
                    continue
                matched_value = actual
            else:
                continue  # malformed rule — neither pattern nor threshold

            # Cooldown check.
            key = self._rule_key(spec.name, rule, idx)
            last = new_state.get(key)
            if last is not None and (now - last) < rule.cooldown_seconds:
                continue
            new_state[key] = now

            mapping = {
                "field": rule.field or "",
                "value": rule.value,
                "matched": matched_value,
                **{k: v for k, v in event.items() if isinstance(k, str)},
            }
            # Let a threshold template reference the field by name (e.g. {amount})
            # even when the value came from parsing free text.
            if rule.field:
                mapping[rule.field] = matched_value
            # Resolve any other {token} in the template by parsing it out of the
            # raw event text (e.g. {invoice_id} from "invoice_id=INV-1").
            for token in re.findall(r"\{(\w+)\}", rule.task_template or ""):
                if token not in mapping or mapping[token] is None:
                    extracted = _extract_field(event, token)
                    if extracted is not None:
                        mapping[token] = extracted
            task = _render(rule.task_template, mapping) or (
                f"Observer '{spec.name}' rule '{rule.name or idx}' fired on {rule.skill}"
            )
            fired.append(
                ActRequest(
                    observer=spec.name,
                    skill=rule.skill,
                    task=task,
                    context={
                        "rule": rule.name or str(idx),
                        "field": rule.field,
                        "op": rule.op,
                        "value": rule.value,
                        "matched": matched_value,
                    },
                    evidence=[text[:500]],
                    approval=rule.approval,
                    tenant_id=spec.tenant_id,
                    agent_id=spec.agent_id,
                    user_id=spec.user_id,
                )
            )

        return fired, new_state
