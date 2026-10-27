"""
Workstream storage layer for Mission Mode.

A workstream is a YAML file describing a multi-item backlog that an agent
grinds through across many cron iterations. This module owns the file
schema, locked read-modify-write, and a few query helpers used by the
mission engine and the REST API.

Layout:
    enterprise_root/tenants/<tenant_id>/workstreams/<name>.yaml

Public surface:
    WorkstreamStore.load(name)              -> dict
    WorkstreamStore.save(name, ws_dict)     -> None      (locked, atomic)
    WorkstreamStore.update_item(name, item_id, **patches)
    WorkstreamStore.list_summaries()        -> list[dict]
    WorkstreamStore.exists(name)            -> bool
    WorkstreamStore.delete(name)            -> bool
    validate_workstream(ws_dict)            -> list[str]  (error messages, empty = ok)
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from .yaml_fast import safe_load as _fast_yaml_load

_SUMMARY_CACHE: dict[str, tuple[float, int, dict]] = {}

from .file_utils import locked_rmw_yaml_sync
from .workstream_business_lens import refresh_business_lens

logger = logging.getLogger(__name__)



VALID_STATUSES = {"active", "paused", "completed", "failed"}
VALID_ITEM_STATUSES = {"pending", "in_progress", "done", "failed", "awaiting_human"}
VALID_PRIORITY_STRATEGIES = {"highest_aged_first", "highest_amount", "round_robin", "sequential"}

# Items-source: where to pull items from automatically
VALID_SOURCE_TYPES = {"sql", "http", "directory", "skill"}
VALID_REFRESH_STRATEGIES = {"append_new", "replace_all", "merge"}

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")

MAX_ITEM_RESULT_SUMMARY_CHARS = 1000
MAX_ITEM_LOG_ENTRIES = 20
MAX_ITEM_LOG_FIELD_CHARS = 500
MAX_ITEM_CHAT_PREVIEW_ENTRIES = 10
MAX_ITEM_CHAT_MESSAGE_CHARS = 500
MAX_ITEM_CHAT_RESPONSE_CHARS = 8000
MAX_ITEM_APPROVAL_NOTE_CHARS = 500
MAX_ITEM_ACTIONS = 8
MAX_ITEM_LEDGER_ENTRIES = 20
MAX_ITEM_STEP_ENTRIES = 20
MAX_ITEM_ACTION_EVENTS = 20
MAX_ITEM_EVENT_FIELD_CHARS = 500



def validate_workstream(ws: dict) -> list[str]:
    """Return list of error messages; empty list means valid."""
    errors: list[str] = []
    if not isinstance(ws, dict):
        return ["workstream must be a dict"]

    name = ws.get("name", "")
    if not _NAME_RE.match(str(name)):
        errors.append(f"name must match {_NAME_RE.pattern!r}, got {name!r}")
    if not ws.get("skill") and not ws.get("automation"):
        errors.append("skill or automation is required")
    status = ws.get("status", "active")
    if status not in VALID_STATUSES:
        errors.append(f"status must be one of {sorted(VALID_STATUSES)}, got {status!r}")
    strategy = ws.get("priority_strategy", "sequential")
    if strategy not in VALID_PRIORITY_STRATEGIES:
        errors.append(f"priority_strategy must be one of {sorted(VALID_PRIORITY_STRATEGIES)}, got {strategy!r}")
    max_attempts = ws.get("max_attempts_per_item", 3)
    if not isinstance(max_attempts, int) or max_attempts < 1 or max_attempts > 20:
        errors.append("max_attempts_per_item must be int in [1,20]")

    # items_source (optional): the workstream pulls items from an upstream
    # source instead of (or in addition to) hand-typed items.
    src = ws.get("items_source")
    if src is not None:
        if not isinstance(src, dict):
            errors.append("items_source must be a dict")
        else:
            stype = src.get("type")
            if stype not in VALID_SOURCE_TYPES:
                errors.append(f"items_source.type must be one of {sorted(VALID_SOURCE_TYPES)}, got {stype!r}")
            rstrat = src.get("refresh_strategy", "append_new")
            if rstrat not in VALID_REFRESH_STRATEGIES:
                errors.append(f"items_source.refresh_strategy must be one of {sorted(VALID_REFRESH_STRATEGIES)}, got {rstrat!r}")
            # Per-type required fields
            if stype == "sql":
                if not src.get("database"):
                    errors.append("items_source[sql].database is required")
                if not src.get("query"):
                    errors.append("items_source[sql].query is required")
            elif stype == "http":
                if not src.get("url"):
                    errors.append("items_source[http].url is required")
            elif stype == "directory":
                if not src.get("path"):
                    errors.append("items_source[directory].path is required")
            elif stype == "skill":
                if not src.get("skill"):
                    errors.append("items_source[skill].skill is required")

    items = ws.get("items", [])
    if not isinstance(items, list):
        errors.append("items must be a list")
        return errors
    ids_seen: set[str] = set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"items[{i}] must be a dict")
            continue
        iid = item.get("id")
        if not iid or not isinstance(iid, str):
            errors.append(f"items[{i}].id is required (string)")
            continue
        if iid in ids_seen:
            errors.append(f"items[{i}].id={iid!r} duplicates an earlier item")
        ids_seen.add(iid)
        if not item.get("description"):
            errors.append(f"items[{i}].description is required")
        istatus = item.get("status", "pending")
        if istatus not in VALID_ITEM_STATUSES:
            errors.append(f"items[{i}].status must be one of {sorted(VALID_ITEM_STATUSES)}, got {istatus!r}")
    return errors



def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounded_text(value: Any, limit: int) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _bounded_execution_log(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    bounded: list[dict] = []
    for entry in value[-MAX_ITEM_LOG_ENTRIES:]:
        if not isinstance(entry, dict):
            continue
        clean = dict(entry)
        for key in ("result_preview", "error_preview", "reason"):
            if key in clean:
                clean[key] = _bounded_text(clean.get(key), MAX_ITEM_LOG_FIELD_CHARS)
        bounded.append(clean)
    return bounded


def _bounded_chat_preview(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    bounded: list[dict] = []
    for entry in value[-MAX_ITEM_CHAT_PREVIEW_ENTRIES:]:
        if not isinstance(entry, dict):
            continue
        clean = dict(entry)
        if "message" in clean:
            clean["message"] = _bounded_text(clean.get("message"), MAX_ITEM_CHAT_MESSAGE_CHARS)
        if "response" in clean:
            clean["response"] = _bounded_text(clean.get("response"), MAX_ITEM_CHAT_RESPONSE_CHARS)
        bounded.append(clean)
    return bounded


def _bounded_approval_context(value: Any) -> Optional[dict]:
    if value is None:
        return None
    if not isinstance(value, dict):
        return {"summary": _bounded_text(value, MAX_ITEM_APPROVAL_NOTE_CHARS)}
    clean = dict(value)
    for key in ("decision", "decided_by", "decision_note", "approval_id", "followup_approval_id"):
        if key in clean:
            clean[key] = _bounded_text(clean.get(key), MAX_ITEM_APPROVAL_NOTE_CHARS)
    return clean


def _bounded_actions(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    actions: list[dict] = []
    for action in value[:MAX_ITEM_ACTIONS]:
        if isinstance(action, dict):
            clean = dict(action)
            if "label" in clean:
                clean["label"] = _bounded_text(clean.get("label"), 120)
            if "description" in clean:
                clean["description"] = _bounded_text(clean.get("description"), 240)
            actions.append(clean)
    return actions


def _bounded_steps(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    steps: list[dict] = []
    for step in value[-MAX_ITEM_STEP_ENTRIES:]:
        if not isinstance(step, dict):
            continue
        clean = dict(step)
        for key in ("tool_name", "status", "input_preview", "output_preview", "error_preview", "result_preview"):
            if key in clean:
                clean[key] = _bounded_text(clean.get(key), MAX_ITEM_EVENT_FIELD_CHARS)
        steps.append(clean)
    return steps


def _bounded_execution_ledger(value: Any) -> list[dict]:
    """Bound the audit ledger, keeping full step detail only on the newest entry.

    `steps` is ~95% of a ledger entry (measured: 10.5 KB of an 11 KB entry), and with 20
    entries per item it was the single largest contributor to workstream file size —
    120 items turned into a 1.8 MB file that had to be parsed on every page load.

    Only the newest entry's steps are ever displayed: the Execution Trace tab falls back
    to `ledger[-1].steps` (workstream_detail.html traceSteps()), and the Audit Ledger tab
    renders nothing but a count for every entry. So older entries keep `step_count` and
    drop `steps`.

    This discards a DUPLICATE, not the only copy. Every entry carries a `trace_id`, and
    the authoritative span-level trace lives in the trace store with no retention policy
    (verified: traces present from the first day of data onwards). Full detail for any
    historical run remains available via /api/traces/{trace_id}.
    """
    if not isinstance(value, list):
        return []
    entries = [e for e in value[-MAX_ITEM_LEDGER_ENTRIES:] if isinstance(e, dict)]
    ledger: list[dict] = []
    newest = len(entries) - 1
    for idx, entry in enumerate(entries):
        clean = dict(entry)
        for key in ("result_preview", "error_preview", "reason"):
            if key in clean:
                clean[key] = _bounded_text(clean.get(key), MAX_ITEM_EVENT_FIELD_CHARS)
        steps = _bounded_steps(clean.get("steps"))
        clean["step_count"] = len(steps) or int(clean.get("step_count") or 0)
        if idx == newest:
            clean["steps"] = steps
        else:
            clean.pop("steps", None)
        ledger.append(clean)
    return ledger


def _bounded_action_events(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    events: list[dict] = []
    for event in value[-MAX_ITEM_ACTION_EVENTS:]:
        if not isinstance(event, dict):
            continue
        clean = dict(event)
        for key in ("action_type", "requested_by", "status", "reason", "result", "error_preview"):
            if key in clean:
                clean[key] = _bounded_text(clean.get(key), MAX_ITEM_EVENT_FIELD_CHARS)
        events.append(clean)
    return events


def _ensure_item_defaults(item: dict) -> dict:
    item.setdefault("status", "pending")
    item.setdefault("attempts", 0)
    item.setdefault("last_attempted_at", None)
    item.setdefault("last_trace_id", None)
    item.setdefault("resolution", None)
    item.setdefault("escalated_approval_id", None)
    item.setdefault("acceptance_criteria", [])
    item.setdefault("execution_log", [])
    item.setdefault("last_result_summary", None)
    item.setdefault("last_result_at", None)
    item.setdefault("evidence_trace_id", None)
    item.setdefault("evidence_count", 0)
    item.setdefault("chat_session_id", None)
    item.setdefault("chat_last_message_at", None)
    item.setdefault("chat_transcript_preview", [])
    item.setdefault("last_approval_context", None)
    item.setdefault("suggested_actions", [])
    item.setdefault("closed_at", None)
    item.setdefault("closed_by", None)
    item.setdefault("current_execution_id", None)
    item.setdefault("execution_ledger", [])
    item.setdefault("action_events", [])
    item.setdefault("last_failure_reason", None)
    if item.get("last_result_summary") is not None:
        item["last_result_summary"] = _bounded_text(
            item.get("last_result_summary"),
            MAX_ITEM_RESULT_SUMMARY_CHARS,
        )
    try:
        item["evidence_count"] = max(0, int(item.get("evidence_count") or 0))
    except (TypeError, ValueError):
        item["evidence_count"] = 0
    item["execution_log"] = _bounded_execution_log(item.get("execution_log"))
    item["chat_transcript_preview"] = _bounded_chat_preview(item.get("chat_transcript_preview"))
    item["last_approval_context"] = _bounded_approval_context(item.get("last_approval_context"))
    item["suggested_actions"] = _bounded_actions(item.get("suggested_actions"))
    item["execution_ledger"] = _bounded_execution_ledger(item.get("execution_ledger"))
    item["action_events"] = _bounded_action_events(item.get("action_events"))
    if item.get("last_failure_reason") is not None:
        item["last_failure_reason"] = _bounded_text(item.get("last_failure_reason"), MAX_ITEM_EVENT_FIELD_CHARS)
    return item


def _ensure_workstream_defaults(ws: dict) -> dict:
    ws.setdefault("status", "active")
    ws.setdefault("priority_strategy", "sequential")
    ws.setdefault("max_attempts_per_item", 3)
    ws.setdefault("created_at", _now_iso())
    ws.setdefault("escalation", [])
    ws.setdefault("description", "")
    ws.setdefault("display_name", ws.get("name", ""))
    ws.setdefault("owner", "")
    ws.setdefault("skill", "")
    ws.setdefault("automation", "")
    ws.setdefault("started_at", None)
    ws.setdefault("completed_at", None)
    ws.setdefault("items_source", None)
    ws.setdefault("last_source_refresh_at", None)
    # Cron-tick throughput config (defaults preserve the original 1-item-per-tick
    # behaviour for backward compatibility). Set higher in high-volume workstreams.
    ws.setdefault("batch_size", 1)       # max items per cron tick
    ws.setdefault("parallelism", 1)      # concurrent workers per cron tick
    # Clamp to sane bounds — also belt-and-braces validation
    try:
        ws["batch_size"] = max(1, min(int(ws["batch_size"] or 1), 100))
    except (TypeError, ValueError):
        ws["batch_size"] = 1
    try:
        ws["parallelism"] = max(1, min(int(ws["parallelism"] or 1), 10))
    except (TypeError, ValueError):
        ws["parallelism"] = 1
    # parallelism > batch_size is wasteful — cap it
    if ws["parallelism"] > ws["batch_size"]:
        ws["parallelism"] = ws["batch_size"]
    # When items_source is set, also seed refresh_strategy default
    if isinstance(ws.get("items_source"), dict):
        ws["items_source"].setdefault("refresh_strategy", "append_new")
    items = ws.get("items", [])
    ws["items"] = [_ensure_item_defaults(dict(it)) for it in items]
    return ws


def _refresh_business_lens_safe(ws: dict) -> dict:
    try:
        return refresh_business_lens(ws)
    except Exception as exc:
        logger.warning("WorkstreamStore: business lens refresh skipped: %s", exc)
        return ws



class WorkstreamStore:
    """File-backed workstream store, one YAML per workstream."""

    def __init__(self, tenant_root: Path | str):
        self.tenant_root = Path(tenant_root)
        self.workstreams_dir = self.tenant_root / "workstreams"

    # ── path resolution ──

    def _path(self, name: str) -> Path:
        if not _NAME_RE.match(name):
            raise ValueError(f"invalid workstream name: {name!r}")
        return self.workstreams_dir / f"{name}.yaml"

    def exists(self, name: str) -> bool:
        return self._path(name).exists()

    # ── CRUD ──

    def load(self, name: str) -> dict:
        path = self._path(name)
        if not path.exists():
            raise FileNotFoundError(f"workstream {name!r} not found at {path}")
        data = _fast_yaml_load(path.read_text(encoding="utf-8")) or {}
        ws = _ensure_workstream_defaults(data)
        return _refresh_business_lens_safe(ws)

    def save(self, ws: dict) -> None:
        """Locked save. Validates before writing."""
        errors = validate_workstream(ws)
        if errors:
            raise ValueError(f"workstream invalid: {'; '.join(errors)}")
        ws = _refresh_business_lens_safe(_ensure_workstream_defaults(dict(ws)))
        path = self._path(ws["name"])
        path.parent.mkdir(parents=True, exist_ok=True)
        # If file doesn't exist yet, write directly (atomic via locked rmw on a fresh file).
        locked_rmw_yaml_sync(path, lambda _existing: ws)
        logger.info("WorkstreamStore: saved %s (%d items, status=%s)",
                    ws["name"], len(ws.get("items", [])), ws.get("status"))

    def delete(self, name: str) -> bool:
        path = self._path(name)
        if not path.exists():
            return False
        path.unlink()
        logger.info("WorkstreamStore: deleted %s", name)
        return True

    # ── field-level atomic updates ──

    def update_item(self, name: str, item_id: str, **patches) -> dict:
        """Atomic field-level patch on a single item. Returns the updated workstream.

        Auto-completion: when this patch transitions an item to a terminal
        state (done / failed) AND no items remain that could still execute
        or resume (pending / in_progress / awaiting_human), the workstream
        itself is auto-flipped to ``status=completed``. Single source of
        truth — callers don't need to remember to check terminal state
        separately.
        """
        path = self._path(name)
        if not path.exists():
            raise FileNotFoundError(f"workstream {name!r} not found")

        def _modify(ws: dict) -> dict:
            ws = _ensure_workstream_defaults(ws)
            found = False
            for it in ws.get("items", []):
                if it.get("id") == item_id:
                    it.update(patches)
                    _ensure_item_defaults(it)
                    found = True
                    break
            if not found:
                raise KeyError(f"item {item_id!r} not in workstream {name!r}")

            if ws.get("status") == "active" and ws.get("items"):
                incomplete = any(
                    (it.get("status") or "pending") in ("pending", "in_progress", "awaiting_human")
                    for it in ws["items"]
                )
                if not incomplete:
                    ws["status"] = "completed"
                    ws["completed_at"] = _now_iso()
                    logger.info(
                        "WorkstreamStore: auto-completed %s "
                        "(all items terminal after %s → %s)",
                        name, item_id, patches.get("status", "?"),
                    )

            return _refresh_business_lens_safe(ws)

        return locked_rmw_yaml_sync(path, _modify)

    def append_item_execution(self, name: str, item_id: str, entry: dict, **patches) -> dict:
        """Append one structured execution ledger row to an item atomically."""
        path = self._path(name)
        if not path.exists():
            raise FileNotFoundError(f"workstream {name!r} not found")

        def _modify(ws: dict) -> dict:
            ws = _ensure_workstream_defaults(ws)
            found = False
            for it in ws.get("items", []):
                if it.get("id") == item_id:
                    it.update(patches)
                    ledger = list(it.get("execution_ledger") or [])
                    ledger.append(dict(entry))
                    it["execution_ledger"] = ledger
                    _ensure_item_defaults(it)
                    found = True
                    break
            if not found:
                raise KeyError(f"item {item_id!r} not in workstream {name!r}")
            if ws.get("status") == "active" and ws.get("items"):
                incomplete = any(
                    (it.get("status") or "pending") in ("pending", "in_progress", "awaiting_human")
                    for it in ws["items"]
                )
                if not incomplete:
                    ws["status"] = "completed"
                    ws["completed_at"] = _now_iso()
            return _refresh_business_lens_safe(ws)

        return locked_rmw_yaml_sync(path, _modify)

    def append_item_action_event(self, name: str, item_id: str, event: dict, **patches) -> dict:
        """Append one governed action event to an item and apply item patches atomically."""
        path = self._path(name)
        if not path.exists():
            raise FileNotFoundError(f"workstream {name!r} not found")

        def _modify(ws: dict) -> dict:
            ws = _ensure_workstream_defaults(ws)
            found = False
            for it in ws.get("items", []):
                if it.get("id") == item_id:
                    it.update(patches)
                    events = list(it.get("action_events") or [])
                    events.append(dict(event))
                    it["action_events"] = events
                    _ensure_item_defaults(it)
                    found = True
                    break
            if not found:
                raise KeyError(f"item {item_id!r} not in workstream {name!r}")

            if ws.get("status") == "active" and ws.get("items"):
                incomplete = any(
                    (it.get("status") or "pending") in ("pending", "in_progress", "awaiting_human")
                    for it in ws["items"]
                )
                if not incomplete:
                    ws["status"] = "completed"
                    ws["completed_at"] = _now_iso()
            return _refresh_business_lens_safe(ws)

        return locked_rmw_yaml_sync(path, _modify)

    def claim_next_item(self, name: str) -> Optional[dict]:
        """Atomic pick-next-eligible-item + mark in_progress, under one lock.

        Replaces the racy two-step ``_pick_next_item(ws)`` + ``update_item(...
        status=in_progress)`` pattern in mission_engine. When two
        concurrent workers (run_n with parallel>1) both want to drain a
        workstream, each call to this method returns a DIFFERENT pending
        item (or None if none remain) — no item is ever claimed by two
        workers.

        Priority strategies match ``mission_engine._pick_next_item``:
            sequential | highest_amount | highest_aged_first | round_robin

        Returns:
            The claimed item dict (with status now 'in_progress',
            attempts bumped, last_attempted_at set) or None if no
            eligible items remain.
        """
        path = self._path(name)
        if not path.exists():
            raise FileNotFoundError(f"workstream {name!r} not found")

        claimed: dict = {}

        def _modify(ws: dict) -> dict:
            ws = _ensure_workstream_defaults(ws)
            eligible = [it for it in ws.get("items", []) if it.get("status") == "pending"]
            if not eligible:
                return _refresh_business_lens_safe(ws)  # no change

            strategy = ws.get("priority_strategy", "sequential")
            if strategy == "highest_amount":
                picked = max(eligible, key=lambda it: float(it.get("priority_metric", 0) or 0))
            elif strategy == "highest_aged_first":
                picked = min(eligible, key=lambda it: it.get("created_at", "0000") or "0000")
            elif strategy == "round_robin":
                picked = min(eligible, key=lambda it: it.get("attempts", 0))
            else:  # sequential
                picked = eligible[0]

            # Claim in-place
            picked["status"] = "in_progress"
            picked["attempts"] = int(picked.get("attempts", 0)) + 1
            picked["last_attempted_at"] = _now_iso()
            claimed["item"] = dict(picked)  # snapshot for the caller
            return _refresh_business_lens_safe(ws)

        locked_rmw_yaml_sync(path, _modify)
        return claimed.get("item")

    def update_workstream(self, name: str, *, validator=None, **patches) -> dict:
        """Atomic field-level patch on workstream-level fields (status, owner, …).

        `validator`, if given, is called as ``validator(current, merged)`` from
        INSIDE the write lock, where `current` is the document as stored and
        `merged` is what would be persisted. Raising from it aborts the patch with
        nothing written — `locked_rmw_yaml_sync` invokes the modifier before it
        writes, and the lock is a context manager, so an exception leaves the file
        untouched and the lock released.

        Callers previously read, checked, then called this — three steps with the
        check outside the lock, so two concurrent patches could each validate
        against a stale document and persist a combination neither had validated.
        Passing the check in closes that window. The store stays generic: it
        supplies atomicity, the caller supplies policy.

        Note: `validator` is keyword-only and therefore not patchable as a field
        name. No workstream field is called `validator`.
        """
        path = self._path(name)
        if not path.exists():
            raise FileNotFoundError(f"workstream {name!r} not found")

        def _modify(ws: dict) -> dict:
            ws = _ensure_workstream_defaults(ws)
            for k in patches:
                if k == "items":
                    raise ValueError("use update_item() or append_item() for items mutations")
            if validator is not None:
                merged = {**ws, **patches}
                validator(ws, merged)
            for k, v in patches.items():
                ws[k] = v
            return _refresh_business_lens_safe(ws)

        return locked_rmw_yaml_sync(path, _modify)

    def append_item(self, name: str, item: dict) -> dict:
        """Atomic append of one new item."""
        path = self._path(name)
        if not path.exists():
            raise FileNotFoundError(f"workstream {name!r} not found")
        new_item = _ensure_item_defaults(dict(item))
        if not new_item.get("id") or not new_item.get("description"):
            raise ValueError("item must have id and description")

        def _modify(ws: dict) -> dict:
            ws = _ensure_workstream_defaults(ws)
            existing_ids = {it["id"] for it in ws["items"]}
            if new_item["id"] in existing_ids:
                raise ValueError(f"item id {new_item['id']!r} already present")
            ws["items"].append(new_item)
            return _refresh_business_lens_safe(ws)

        return locked_rmw_yaml_sync(path, _modify)

    # ── queries ──

    def list_summaries(self) -> list[dict]:
        """Return a lightweight list (no items array) for the index page.

        Cached per file on (mtime, size). The summary is tiny — a name, an owner and
        some status counts — but producing it means fully parsing the workstream, items
        and all. On this tenant that is 6.3 MB of YAML for 25 KB of output, and it was
        being redone on every single page load: measured at 4.7s, dead consistent across
        runs, which is the signature of no caching at all.

        A workstream only changes when something writes the file, and every writer goes
        through locked_rmw_yaml_sync, which updates mtime — so staleness is not possible
        without the file changing underneath us. A clock going backwards or a same-second
        write of identical length is the only miss, and size guards most of that.
        """
        if not self.workstreams_dir.exists():
            return []
        summaries = []
        for p in sorted(self.workstreams_dir.glob("*.yaml")):
            try:
                stat = p.stat()
                key = str(p)
                cached = _SUMMARY_CACHE.get(key)
                if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
                    summaries.append(cached[2])
                    continue
                data = _fast_yaml_load(p.read_text(encoding="utf-8")) or {}
                data = _ensure_workstream_defaults(data)
                summary = self._summarize(data)
                _SUMMARY_CACHE[key] = (stat.st_mtime, stat.st_size, summary)
                summaries.append(summary)
            except Exception as exc:
                logger.warning("Skipping unreadable workstream %s: %s", p, exc)
        return summaries

    @staticmethod
    def _summarize(ws: dict) -> dict:
        items = ws.get("items", [])
        by_status: dict[str, int] = {s: 0 for s in VALID_ITEM_STATUSES}
        for it in items:
            by_status[it.get("status", "pending")] = by_status.get(it.get("status", "pending"), 0) + 1
        return {
            "name": ws.get("name"),
            "display_name": ws.get("display_name") or ws.get("name"),
            "owner": ws.get("owner", ""),
            "skill": ws.get("skill", ""),
            "automation": ws.get("automation", ""),
            "status": ws.get("status", "active"),
            "total_items": len(items),
            "by_status": by_status,
            "created_at": ws.get("created_at"),
            "started_at": ws.get("started_at"),
            "completed_at": ws.get("completed_at"),
            "cron_job_id": ws.get("cron_job_id"),
        }

    # ── higher-level state transitions used by the engine ──

    def mark_started_if_first(self, name: str) -> bool:
        """If started_at is unset, set it. Returns True if this was the first activation."""
        path = self._path(name)
        marker = {"fired": False}

        def _modify(ws: dict) -> dict:
            ws = _ensure_workstream_defaults(ws)
            if not ws.get("started_at"):
                ws["started_at"] = _now_iso()
                marker["fired"] = True
            return _refresh_business_lens_safe(ws)

        locked_rmw_yaml_sync(path, _modify)
        return marker["fired"]

    def mark_completed(self, name: str) -> dict:
        """Set status=completed + completed_at=now."""
        return self.update_workstream(name, status="completed", completed_at=_now_iso())

    def mark_completed_once(self, name: str) -> bool:
        """Idempotent completion latch — returns True for the FIRST caller only.

        ``update_item`` already auto-flips ``status`` to ``completed`` the moment
        the last item goes terminal, so callers can no longer rely on observing
        an ``active → completed`` transition to know they are the one that
        finished the workstream. Under parallel drain (``run_n`` with
        ``parallelism > 1``) several workers can also see the workstream go
        terminal in the same instant.

        This sets a single-shot ``meta.on_complete_fired_at`` sentinel under the
        per-file lock and returns True exactly once, regardless of how many
        workers race here or how many times cron re-enters. Use it to gate the
        OnMissionComplete hook + research synthesis so they fire exactly once.
        """
        path = self._path(name)
        marker = {"fired": False}

        def _modify(ws: dict) -> dict:
            ws = _ensure_workstream_defaults(ws)
            meta = ws.get("meta")
            if not isinstance(meta, dict):
                meta = {}
                ws["meta"] = meta
            if not meta.get("on_complete_fired_at"):
                if ws.get("status") != "completed":
                    ws["status"] = "completed"
                    if not ws.get("completed_at"):
                        ws["completed_at"] = _now_iso()
                meta["on_complete_fired_at"] = _now_iso()
                marker["fired"] = True
            return _refresh_business_lens_safe(ws)

        locked_rmw_yaml_sync(path, _modify)
        return marker["fired"]

    @staticmethod
    def is_terminal(ws: dict) -> bool:
        """A workstream is terminal when every item is in {done, failed, awaiting_human}."""
        terminal_item_statuses = {"done", "failed"}
        # awaiting_human items are NOT terminal until they're resolved
        return all(it.get("status") in terminal_item_statuses for it in ws.get("items", []))

    @staticmethod
    def is_complete(ws: dict) -> bool:
        """Stricter: all items done (no failed, no awaiting_human)."""
        return bool(ws.get("items")) and all(it.get("status") == "done" for it in ws.get("items", []))



def now_iso() -> str:
    """Exposed for callers that want consistent timestamps."""
    return _now_iso()
