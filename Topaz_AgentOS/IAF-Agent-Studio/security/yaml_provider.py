"""YAML-backed entitlement provider for tenant-owned policies."""

from __future__ import annotations

import threading
from fnmatch import fnmatch
from typing import Any

import yaml

from shared.config import DATA_ROOT, ENTITLEMENTS_FAIL_CLOSED, SERVER_DIR

from .models import Decision, Principal, Resource
from .provider import EntitlementProvider


_VALID_EFFECTS = {"allow", "deny"}
_REQUIRED_POLICY_FIELDS = ("id", "effect", "actions", "resources")


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def parse_policy_yaml(raw: str) -> tuple[dict, list[str]]:
    """Parse policy YAML and return the document plus parse/shape errors."""
    try:
        parsed = yaml.safe_load(raw) or {}
    except Exception as exc:
        return {}, [f"YAML parse error: {exc}"]
    if not isinstance(parsed, dict):
        return {}, ["Policy document must be a YAML mapping"]
    return parsed, []


def _principal_scopes_overlap(policy_a: dict, policy_b: dict) -> bool:
    """Return True when the same principal could match both policies."""
    users_a = set(_as_list(policy_a.get("users")))
    users_b = set(_as_list(policy_b.get("users")))
    if users_a and users_b and not users_a.intersection(users_b):
        return False
    return True


def _actions_overlap(actions_a: Any, actions_b: Any) -> bool:
    left = set(_as_list(actions_a))
    right = set(_as_list(actions_b))
    if not left or not right:
        return False
    if "*" in left or "*" in right:
        return True
    return bool(left.intersection(right))


def _resource_patterns_overlap(pattern_a: str, pattern_b: str) -> bool:
    if pattern_a == pattern_b:
        return True
    if pattern_a in ("*", "all") or pattern_b in ("*", "all"):
        return True
    if fnmatch(pattern_a, pattern_b) or fnmatch(pattern_b, pattern_a):
        return True
    probes = {pattern_a, pattern_b}
    for pattern in (pattern_a, pattern_b):
        if "*" in pattern or "?" in pattern:
            probes.add(pattern.replace("*", "overlap-probe"))
            if ":" in pattern:
                prefix = pattern.split(":", 1)[0]
                probes.add(f"{prefix}:overlap-probe")
    for probe in probes:
        if fnmatch(probe, pattern_a) and fnmatch(probe, pattern_b):
            return True
    return False


def _resources_overlap(resources_a: Any, resources_b: Any) -> bool:
    left = _as_list(resources_a)
    right = _as_list(resources_b)
    if not left or not right:
        return False
    return any(_resource_patterns_overlap(a, b) for a in left for b in right)


def _overlap_values(left_raw: Any, right_raw: Any, *, multi_valued: bool = False) -> list[str]:
    left = set(_as_list(left_raw))
    right = set(_as_list(right_raw))
    if not left or not right:
        return sorted(left or right)
    both = left & right
    if both:
        return sorted(both)
    if multi_valued:
        return sorted(left | right)
    return []


def _overlapping_actions_list(actions_a: Any, actions_b: Any) -> list[str]:
    left = set(_as_list(actions_a))
    right = set(_as_list(actions_b))
    if not left or not right:
        return []
    if "*" in left and "*" in right:
        return ["*"]
    if "*" in left:
        return sorted(right)
    if "*" in right:
        return sorted(left)
    return sorted(left & right)


def _overlapping_resources_list(resources_a: Any, resources_b: Any) -> list[str]:
    left = _as_list(resources_a)
    right = _as_list(resources_b)
    hits: list[str] = []
    seen: set[str] = set()
    for pattern_a in left:
        for pattern_b in right:
            if not _resource_patterns_overlap(pattern_a, pattern_b):
                continue
            label = pattern_a if pattern_a == pattern_b else f"{pattern_a} / {pattern_b}"
            if label in seen:
                continue
            seen.add(label)
            hits.append(label)
    return hits


def _policy_overlap_fields(policy_a: dict, policy_b: dict) -> dict[str, list[str]]:
    overlaps: dict[str, list[str]] = {}
    roles = _overlap_values(policy_a.get("roles"), policy_b.get("roles"), multi_valued=True)
    if roles:
        overlaps["roles"] = roles
    groups = _overlap_values(policy_a.get("groups"), policy_b.get("groups"), multi_valued=True)
    if groups:
        overlaps["groups"] = groups
    users = _overlap_values(policy_a.get("users"), policy_b.get("users"))
    if users:
        overlaps["users"] = users
    actions = _overlapping_actions_list(policy_a.get("actions"), policy_b.get("actions"))
    if actions:
        overlaps["actions"] = actions
    resources = _overlapping_resources_list(policy_a.get("resources"), policy_b.get("resources"))
    if resources:
        overlaps["resources"] = resources[:5]
        if len(resources) > 5:
            overlaps["resources_more"] = [str(len(resources) - 5)]
    return overlaps


def _format_conflict_message(
    policy_a_id: str,
    effect_a: str,
    policy_b_id: str,
    effect_b: str,
    overlaps: dict[str, list[str]],
) -> str:
    parts: list[str] = []
    if overlaps.get("roles"):
        parts.append(f"roles: {', '.join(overlaps['roles'])}")
    if overlaps.get("groups"):
        parts.append(f"groups: {', '.join(overlaps['groups'])}")
    if overlaps.get("users"):
        parts.append(f"users: {', '.join(overlaps['users'])}")
    if overlaps.get("actions"):
        parts.append(f"actions: {', '.join(overlaps['actions'])}")
    if overlaps.get("resources"):
        resource_text = ", ".join(overlaps["resources"])
        extra = overlaps.get("resources_more", [])
        if extra:
            resource_text = f"{resource_text} (+{extra[0]} more)"
        parts.append(f"resources: {resource_text}")
    overlap_text = "; ".join(parts) if parts else "same scope"
    return f"'{policy_a_id}' ({effect_a}) and '{policy_b_id}' ({effect_b}) conflict on {overlap_text}."


def _policy_effect_conflict_details(policies: list[Any]) -> list[dict[str, Any]]:
    """Detect allow/deny pairs that overlap on principals, actions, and resources."""
    details: list[dict[str, Any]] = []
    for idx_a, policy_a in enumerate(policies):
        if not isinstance(policy_a, dict):
            continue
        effect_a = str(policy_a.get("effect", "")).lower()
        if effect_a not in _VALID_EFFECTS:
            continue
        policy_a_id = str(policy_a.get("id", "")).strip() or f"policies[{idx_a}]"
        for idx_b in range(idx_a + 1, len(policies)):
            policy_b = policies[idx_b]
            if not isinstance(policy_b, dict):
                continue
            effect_b = str(policy_b.get("effect", "")).lower()
            if effect_b not in _VALID_EFFECTS or effect_a == effect_b:
                continue
            if not _principal_scopes_overlap(policy_a, policy_b):
                continue
            if not _actions_overlap(policy_a.get("actions"), policy_b.get("actions")):
                continue
            if not _resources_overlap(policy_a.get("resources"), policy_b.get("resources")):
                continue
            policy_b_id = str(policy_b.get("id", "")).strip() or f"policies[{idx_b}]"
            overlaps = _policy_overlap_fields(policy_a, policy_b)
            details.append(
                {
                    "policy_a": policy_a_id,
                    "policy_b": policy_b_id,
                    "effect_a": effect_a,
                    "effect_b": effect_b,
                    "overlaps": overlaps,
                    "message": _format_conflict_message(
                        policy_a_id, effect_a, policy_b_id, effect_b, overlaps
                    ),
                }
            )
    return details


def validate_policy_doc(policy_doc: dict) -> dict:
    """Validate policy document shape without applying enterprise-specific rules."""
    errors: list[str] = []
    warnings: list[str] = []
    policies = policy_doc.get("policies", [])

    if policies is None:
        policies = []
    if not isinstance(policies, list):
        return {
            "valid": False,
            "errors": ["policies must be a list"],
            "warnings": warnings,
            "policy_count": 0,
            "conflict_details": [],
        }

    seen_ids: set[str] = set()
    for idx, policy in enumerate(policies):
        prefix = f"policies[{idx}]"
        if not isinstance(policy, dict):
            errors.append(f"{prefix} must be a mapping")
            continue
        for field in _REQUIRED_POLICY_FIELDS:
            if field not in policy or policy.get(field) in (None, ""):
                errors.append(f"{prefix}.{field} is required")
        policy_id = str(policy.get("id", "")).strip()
        if policy_id:
            if policy_id in seen_ids:
                errors.append(f"{prefix}.id duplicates '{policy_id}'")
            seen_ids.add(policy_id)
        effect = str(policy.get("effect", "")).lower()
        if effect and effect not in _VALID_EFFECTS:
            errors.append(f"{prefix}.effect must be one of: allow, deny")
        for list_field in ("actions", "resources", "roles", "groups", "users"):
            if list_field in policy and not isinstance(policy[list_field], list):
                errors.append(f"{prefix}.{list_field} must be a list")
        if not _as_list(policy.get("roles")) and not _as_list(policy.get("groups")) and not _as_list(policy.get("users")):
            warnings.append(f"{prefix} applies to any principal")

    conflict_details = _policy_effect_conflict_details(policies)
    errors.extend(detail["message"] for detail in conflict_details)

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "policy_count": len(policies),
        "conflict_details": conflict_details,
    }


def validate_policy_yaml(raw: str) -> dict:
    policy_doc, errors = parse_policy_yaml(raw)
    if errors:
        return {"valid": False, "errors": errors, "warnings": [], "policy_count": 0, "parsed": policy_doc}
    result = validate_policy_doc(policy_doc)
    result["parsed"] = policy_doc
    return result


# policies.yaml path -> ((mtime_ns, size), parsed document)
_POLICY_CACHE: dict[str, tuple[tuple[int, int], dict]] = {}
_POLICY_CACHE_LOCK = threading.Lock()


class YamlEntitlementProvider(EntitlementProvider):
    """Evaluate simple allow/deny policies stored under each tenant."""

    # Access classes whose broad auto-compiled grant a curated policies.yaml rule may
    # "take ownership" of, so an admin can scope a role to specific skills/agents (e.g.
    # "user" -> skill:general without unlocking every other skill). Plumbing grants
    # (tool:*, context:*, …) are always preserved so the role's permitted skills still
    # run, and the built-in admin wildcard baseline is never dropped.
    _CURATED_ACCESS_CLASSES = ("skill", "agent")

    def _policy_file(self, tenant_id: str):
        return SERVER_DIR / DATA_ROOT / "tenants" / tenant_id / "security" / "policies.yaml"

    def _load_policy(self, tenant_id: str) -> dict:
        """Parsed policies.yaml, re-read only when the file changes.

        This used to parse the file on EVERY check (~37 ms with pure-Python PyYAML). Pages
        check once per skill — /api/skills made 183 checks, ~2.5 s of event-loop time per
        call — and every request makes at least one. The cache key is (mtime_ns, size), so
        an edit (Security Console save, hand edit) takes effect on the next check. Callers
        only read the returned document.
        """
        policy_file = self._policy_file(tenant_id)
        # Cache the parsed policy file by (mtime_ns, size); an edit invalidates it.
        doc = None
        try:
            st = policy_file.stat()
        except FileNotFoundError:
            st = None
            # Evict stale entries so a recreated file with identical (mtime_ns, size) is re-parsed.
            with _POLICY_CACHE_LOCK:
                _POLICY_CACHE.pop(str(policy_file), None)
        if st is not None:
            key = (st.st_mtime_ns, st.st_size)
            with _POLICY_CACHE_LOCK:
                cached = _POLICY_CACHE.get(str(policy_file))
                if cached and cached[0] == key:
                    doc = cached[1]
            if doc is None:
                doc = yaml.safe_load(policy_file.read_text(encoding="utf-8")) or {}
                with _POLICY_CACHE_LOCK:
                    _POLICY_CACHE[str(policy_file)] = (key, doc)
        if doc is None:
            doc = {}
        # Merge role-derived allow-rules; a fresh dict keeps the cached doc unmutated.
        try:
            from .roles import compile_role_policies
            compiled = compile_role_policies(tenant_id)
        except Exception:
            compiled = []
        if compiled:
            base = list(doc.get("policies") or [])
            # Curated policies.yaml rules take precedence: drop the broad auto-compiled
            # <class>:* grant for any role/group the admin has scoped by hand, so the
            # hand-written narrower rule actually wins instead of being nullified by the
            # role-derived wildcard (any-allow-wins would otherwise re-grant everything).
            compiled = self._suppress_curated_access(base, compiled)
            doc = {**doc, "policies": base + compiled}
        return doc

    @classmethod
    def _suppress_curated_access(cls, base_policies: list, compiled: list) -> list:
        """Curated policies.yaml rules take precedence over auto-compiled defaults.

        If the admin has authored explicit ``allow`` rules in policies.yaml that
        scope a *curated access class* (skill/agent) for a role or group, the broad
        auto-compiled ``<class>:*`` grant for that selector is dropped — so the
        hand-written scope wins instead of being nullified by the role-derived
        wildcard (any-allow-wins would otherwise re-grant everything).

        Only *pure broad-access* grants are dropped (resources are exactly
        ``<class>:*`` for a curated class). Runtime plumbing grants (specific tool
        lists, ``context:*`` reads, etc.) are always kept so permitted skills still
        execute, and the built-in admin wildcard baseline is never touched. Roles
        with no curated rules keep their full compiled defaults, so brand-new UI
        roles and an empty/missing policies.yaml never lock out.
        """
        curated_roles: dict[str, set[str]] = {}
        curated_groups: dict[str, set[str]] = {}
        for p in base_policies:
            # Skip non-mapping entries (e.g. a malformed ``policies: [null]``). They
            # stay in the doc so validate_policy_doc() still fails the tenant closed on
            # the structural error; calling p.get() here would raise AttributeError and
            # mask that clean failure.
            if not isinstance(p, dict) or str(p.get("effect", "allow")).lower() != "allow":
                continue
            # Only a concrete ``<class>:<name>`` resource takes ownership of the class.
            # Require a colon and a non-empty suffix: the evaluator only matches concrete
            # skill:<name>/agent:<name> patterns, so a malformed ``resources: [skill]`` (or
            # ``skill:``) must NOT suppress the role's broad skill:* grant — doing so would
            # drop the default while granting no matching skill, locking the role out.
            classes = {
                head.strip().lower()
                for res in _as_list(p.get("resources"))
                for head, sep, tail in [str(res).partition(":")]
                if sep == ":" and tail.strip()
            } & set(cls._CURATED_ACCESS_CLASSES)
            if not classes:
                continue
            roles = _as_list(p.get("roles"))
            groups = _as_list(p.get("groups"))
            users = _as_list(p.get("users"))
            # A curated rule only "takes ownership" of a role's (or group's) broad
            # compiled grant when it scopes that one dimension ALONE. _principal_matches
            # ANDs the selectors, so a rule narrowed by an extra dimension (e.g.
            # roles:[user] + groups:[finance], or any users:[...]) matches a strict
            # SUBSET of the role's principals — suppressing the per-role compiled grant
            # on its behalf would lock out principals outside that subset (e.g. every
            # non-finance user). Such narrower rules add access via any-allow instead;
            # they must never suppress. compile_role_policies always emits
            # single-dimension rules, so single-dimension ownership is sufficient.
            if users:
                continue
            if roles and not groups:
                for r in roles:
                    curated_roles.setdefault(str(r).strip().lower(), set()).update(classes)
            elif groups and not roles:
                for g in groups:
                    curated_groups.setdefault(str(g).strip().lower(), set()).update(classes)

        if not curated_roles and not curated_groups:
            return compiled

        kept = []
        for rule in compiled:
            # Never drop the built-in admin safety baseline.
            if rule.get("id") == "role-auto:admin:full":
                kept.append(rule)
                continue
            sel_classes: set[str] = set()
            for r in _as_list(rule.get("roles")):
                sel_classes |= curated_roles.get(str(r).strip().lower(), set())
            for g in _as_list(rule.get("groups")):
                sel_classes |= curated_groups.get(str(g).strip().lower(), set())
            resources = _as_list(rule.get("resources"))

            def _is_broad_curated(res: str) -> bool:
                head, sep, tail = str(res).partition(":")
                return sep == ":" and tail.strip() == "*" and head.strip().lower() in sel_classes

            # Drop only when every resource is a "<curated-class>:*" wildcard — i.e.
            # a pure broad-access grant the admin has taken ownership of. Plumbing
            # and specific-resource grants fall through and are kept.
            if sel_classes and resources and all(_is_broad_curated(r) for r in resources):
                continue
            kept.append(rule)
        return kept

    @staticmethod
    def _matches_any(value: str, patterns: list[str] | None) -> bool:
        patterns = _as_list(patterns)
        if not patterns:
            return True
        return any(fnmatch(value, pattern) for pattern in patterns)

    @staticmethod
    def _principal_matches(principal: Principal, policy: dict[str, Any]) -> bool:
        roles = _as_list(policy.get("roles"))
        groups = _as_list(policy.get("groups"))
        users = _as_list(policy.get("users"))
        if users and principal.user_id not in users and principal.email not in users:
            return False
        if roles and not set(principal.roles).intersection(roles):
            return False
        if groups and not set(principal.groups).intersection(groups):
            return False
        return True

    def can(
        self,
        principal: Principal,
        action: str,
        resource: Resource,
        context: dict[str, Any] | None = None,
    ) -> Decision:
        policy_doc = self._load_policy(principal.tenant_id)
        validation = validate_policy_doc(policy_doc)
        # Only structural errors fail closed at runtime; allow/deny overlaps stay an authoring-time lint (deny wins).
        _conflict_msgs = {d.get("message") for d in validation.get("conflict_details", [])}
        _structural_errors = [e for e in validation["errors"] if e not in _conflict_msgs]
        if _structural_errors:
            return Decision(
                False,
                reason=f"invalid entitlement policy: {_structural_errors[0]}",
                matched_policy="invalid_policy",
                metadata={"errors": _structural_errors},
            )
        policies = policy_doc.get("policies") or []
        resource_key = resource.key

        matched: list[tuple[int, dict]] = []
        for idx, policy in enumerate(policies):
            if (
                self._principal_matches(principal, policy)
                and self._matches_any(action, policy.get("actions"))
                and self._matches_any(resource_key, policy.get("resources"))
            ):
                matched.append((idx, policy))

        for idx, policy in matched:
            if str(policy.get("effect", "deny")).lower() == "deny":
                return Decision(
                    False,
                    reason=policy.get("reason", "yaml policy deny"),
                    matched_policy=policy.get("id", f"policy[{idx}]"),
                    metadata={"effect": "deny"},
                )

        if matched:
            idx, policy = matched[0]
            return Decision(
                True,
                reason=policy.get("reason", "yaml policy allow"),
                matched_policy=policy.get("id", f"policy[{idx}]"),
                metadata={"effect": "allow"},
            )

        if not policies and not ENTITLEMENTS_FAIL_CLOSED:
            return Decision(True, reason="no tenant policy; fail-open", matched_policy="default")
        return Decision(False, reason="no matching entitlement policy", matched_policy="default_deny")
