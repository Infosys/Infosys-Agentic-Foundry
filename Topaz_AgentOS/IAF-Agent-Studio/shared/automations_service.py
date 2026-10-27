"""Service layer for deterministic automation definitions and runs."""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

import yaml

from agent_os import create_kernel_runtime
from automation_runtime.db import get_db
from iaf_agent_skills.automation import AutomationEngine
from shared.config import AGENT_ID, DATA_ROOT_PATH, TENANT_ID
from shared.file_utils import atomic_write_yaml

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def automations_dir(tenant_id: str = TENANT_ID) -> Path:
    root = DATA_ROOT_PATH / "tenants" / tenant_id / "automations"
    root.mkdir(parents=True, exist_ok=True)
    return root


def validate_automation_id(automation_id: str) -> str:
    clean = str(automation_id or "").strip()
    if not _ID_RE.match(clean):
        raise ValueError(
            "Automation id must be 1-128 chars and contain only letters, "
            "numbers, underscores, hyphens, or dots."
        )
    return clean


def automation_path(automation_id: str, tenant_id: str = TENANT_ID) -> Path:
    return automations_dir(tenant_id) / f"{validate_automation_id(automation_id)}.yaml"


def list_automations(tenant_id: str = TENANT_ID) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(automations_dir(tenant_id).glob("*.yaml")):
        try:
            data = _read_yaml(path)
            items.append(_normalize_definition(data, path.stem, tenant_id, source_file=path.name))
        except Exception as exc:
            items.append({
                "id": path.stem,
                "name": path.stem,
                "description": "",
                "steps": [],
                "enabled": False,
                "source_file": path.name,
                "error": str(exc),
            })
    return items


def get_automation(automation_id: str, tenant_id: str = TENANT_ID) -> dict[str, Any]:
    path = automation_path(automation_id, tenant_id)
    if not path.exists():
        raise FileNotFoundError(f"Automation '{automation_id}' not found")
    return _normalize_definition(_read_yaml(path), automation_id, tenant_id, source_file=path.name)


def save_automation(definition: dict[str, Any], tenant_id: str = TENANT_ID) -> dict[str, Any]:
    normalized = _normalize_definition(definition, definition.get("id") or "", tenant_id)
    path = automation_path(normalized["id"], tenant_id)
    atomic_write_yaml(path, _yaml_payload(normalized))
    normalized["source_file"] = path.name
    return normalized


def delete_automation(automation_id: str, tenant_id: str = TENANT_ID) -> None:
    path = automation_path(automation_id, tenant_id)
    if not path.exists():
        raise FileNotFoundError(f"Automation '{automation_id}' not found")
    path.unlink()


def run_automation(
    automation_id: str,
    *,
    tenant_id: str = TENANT_ID,
    agent_id: str = AGENT_ID,
    user_id: str = "automation",
    trigger: str = "manual",
    input_text: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    definition = get_automation(automation_id, tenant_id)
    run_id = f"auto_run_{uuid.uuid4().hex[:12]}"
    db = get_db()
    db.create_run(
        run_id=run_id,
        automation_id=definition["id"],
        automation_name=definition.get("name") or definition["id"],
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        trigger=trigger,
    )

    started = time.time()
    status = "success"
    error_summary = ""
    summary = ""
    try:
        kernel = create_kernel_runtime(
            data_root=str(DATA_ROOT_PATH),
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
            require_confirmation=False,
        )
        engine = AutomationEngine(kernel)
        initial_context = _initial_context(input_text, context)
        result = engine.run(
            automation_id=definition["id"],
            steps=definition.get("steps") or [],
            initial_context=initial_context,
        )
        summary = result.summary
        status = "success" if result.success else "failed"
        actions_by_name = _actions_by_name(definition.get("steps") or [])
        for idx, (step_name, step_result) in enumerate(result.steps.items(), start=1):
            db.append_step(
                run_id=run_id,
                step_number=idx,
                step_name=step_name,
                action=actions_by_name.get(step_name, ""),
                output=step_result.output,
                error=step_result.error or "",
                status="success" if step_result.success else "failed",
                duration_ms=step_result.duration_ms,
            )
    except Exception as exc:
        status = "failed"
        error_summary = str(exc)
        summary = f"Automation failed: {exc}"
    finally:
        duration_ms = int((time.time() - started) * 1000)
        db.update_run(
            run_id,
            status=status,
            duration_ms=duration_ms,
            summary=summary,
            error_summary=error_summary,
        )

    trace = db.get_run(run_id) or {"run": {"run_id": run_id}, "steps": []}
    return {
        "run_id": run_id,
        "automation": definition,
        "status": status,
        "summary": summary,
        "trace": trace,
    }


def list_runs(automation_id: str | None = None, *, limit: int = 25) -> list[dict[str, Any]]:
    return get_db().list_runs(automation_id=automation_id, limit=limit)


def get_run(run_id: str) -> dict[str, Any]:
    run = get_db().get_run(run_id)
    if run is None:
        raise FileNotFoundError(f"Automation run '{run_id}' not found")
    return run


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("Automation YAML must be a mapping")
    return data


def _normalize_definition(
    raw: dict[str, Any],
    fallback_id: str,
    tenant_id: str,
    *,
    source_file: str = "",
) -> dict[str, Any]:
    automation_id = validate_automation_id(raw.get("id") or fallback_id)
    steps = raw.get("steps") or []
    if not isinstance(steps, list):
        raise ValueError("steps must be a list")
    return {
        "id": automation_id,
        "name": str(raw.get("name") or automation_id),
        "description": str(raw.get("description") or ""),
        "enabled": bool(raw.get("enabled", True)),
        "tenant_id": tenant_id,
        "steps": [_normalize_step(step, idx) for idx, step in enumerate(steps, start=1)],
        "source_file": source_file,
    }


def _normalize_step(raw: Any, idx: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"step {idx} must be a mapping")
    step = dict(raw)
    step["name"] = str(step.get("name") or f"step_{idx}")
    step["action"] = str(step.get("action") or "shell")
    step["params"] = dict(step.get("params") or {})
    return step


def _yaml_payload(definition: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": definition["id"],
        "name": definition.get("name") or definition["id"],
        "description": definition.get("description") or "",
        "enabled": bool(definition.get("enabled", True)),
        "steps": definition.get("steps") or [],
    }


def _initial_context(input_text: str | None, context: dict[str, Any] | None) -> str | None:
    if context:
        return json.dumps({"input": input_text or "", "context": context}, sort_keys=True)
    if input_text:
        return input_text
    return None


def _actions_by_name(steps: list[dict[str, Any]]) -> dict[str, str]:
    return {str(step.get("name") or f"step_{idx}"): str(step.get("action") or "") for idx, step in enumerate(steps, start=1)}
