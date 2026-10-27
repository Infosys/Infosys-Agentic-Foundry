"""
Workstream templates router.

A *template* is a workstream YAML with the runtime / lifecycle fields stripped
out — items, dates (started_at, completed_at), runtime statuses, last_trace_id
references. What remains is the *shape*: worker_skill, items_source query
template, escalation rules, priority_strategy, max_attempts_per_item, cron
schedule. Useful when a user finds a workstream design that works well and
wants to instantiate the same shape later for a new question / period / cohort.

Endpoints
---------
    GET  /api/workstream-templates                 list templates (summary)
    GET  /api/workstream-templates/{name}          full YAML
    POST /api/workstream-templates                 create from existing workstream
    DELETE /api/workstream-templates/{name}        delete

Storage
-------
    enterprise_root/tenants/<tenant_id>/workstream_templates/<name>.yaml

Kept deliberately separate from `routers/workstreams.py` so the template
concern doesn't bloat the workstream CRUD/runtime router.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from iaf_agent_skills.workstream_store import WorkstreamStore
from shared.config import SERVER_DIR, DATA_ROOT

logger = logging.getLogger("workstream_templates")

router = APIRouter(tags=["workstream-templates"])

DEFAULT_TENANT_ID = "company"

# Runtime/per-instance state stripped when persisting a template; the reuser populates it fresh.
_STRIPPED_TOP_LEVEL = frozenset({
    "started_at",
    "completed_at",
    "status",          # template defaults to active; reuser starts paused if they want
    "items",           # runtime backlog — never persisted in a template
})
_STRIPPED_PER_ITEM = frozenset({
    "status",
    "attempts",
    "last_trace_id",
    "started_at",
    "completed_at",
    "resolution",
    "escalated_approval_id",
})

# Conservative regex — kebab/snake-case names, no path separators or shell metas.
_VALID_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{1,79}$")


def _templates_dir(tenant_id: str) -> Path:
    p = Path(SERVER_DIR) / DATA_ROOT / "tenants" / tenant_id / "workstream_templates"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _strip_for_template(ws: dict) -> dict:
    """Return a copy of *ws* with runtime/lifecycle fields removed.

    Pure function — no IO. Tested in isolation.
    """
    template = {k: v for k, v in ws.items() if k not in _STRIPPED_TOP_LEVEL}
    template["status"] = "active"  # default for instantiation

    # Keep items_source if present (it's part of the shape, not the runtime state)
    # but drop any inline items the original had.
    template.pop("items", None)

    # Stash a marker so consumers can tell templates from workstreams at a glance
    template["__template__"] = True
    return template


class TemplateCreateRequest(BaseModel):
    template_name: str = Field(..., description="Slug-style name (a-z, 0-9, _, -). 2–80 chars.")
    source_workstream: str = Field(..., description="Name of an existing workstream to use as the shape source.")
    overwrite: bool = Field(default=False, description="Allow overwriting an existing template of the same name.")


def _store(tenant_id: str) -> WorkstreamStore:
    """Build a WorkstreamStore rooted at the tenant — same shape as routers/workstreams.py."""
    return WorkstreamStore(Path(SERVER_DIR) / DATA_ROOT / "tenants" / tenant_id)


@router.get("/api/workstream-templates")
async def list_templates(tenant_id: str = DEFAULT_TENANT_ID):
    """List all templates for the tenant — summary fields only."""
    tdir = _templates_dir(tenant_id)
    out = []
    for f in sorted(tdir.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            logger.warning("Skipping malformed template %s: %s", f.name, exc)
            continue
        out.append({
            "name": f.stem,
            "display_name": data.get("display_name") or f.stem,
            "skill": data.get("skill") or data.get("worker_skill"),
            "priority_strategy": data.get("priority_strategy"),
            "has_items_source": bool(data.get("items_source")),
            "escalation_count": len(data.get("escalation") or []),
            "description": (data.get("description") or "")[:200],
        })
    return {"templates": out, "count": len(out)}


@router.get("/api/workstream-templates/{name}")
async def get_template(name: str, tenant_id: str = DEFAULT_TENANT_ID):
    """Return the full template YAML as parsed JSON."""
    if not _VALID_NAME.match(name):
        raise HTTPException(status_code=400, detail="Invalid template name")
    path = _templates_dir(tenant_id) / f"{name}.yaml"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Template {name!r} not found")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.exception("get_template failed")
        raise HTTPException(status_code=500, detail="An internal error occurred")
    return data


@router.post("/api/workstream-templates")
async def create_template(body: TemplateCreateRequest, tenant_id: str = DEFAULT_TENANT_ID):
    """Create a template from an existing workstream."""
    if not _VALID_NAME.match(body.template_name):
        raise HTTPException(
            status_code=400,
            detail="Template name must match ^[a-z0-9][a-z0-9_-]{1,79}$",
        )
    if not _VALID_NAME.match(body.source_workstream):
        raise HTTPException(status_code=400, detail="Invalid source_workstream name")

    try:
        ws = _store(tenant_id).load(body.source_workstream)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"source workstream {body.source_workstream!r} not found",
        )

    template = _strip_for_template(ws)
    template["__template_source__"] = body.source_workstream

    out_path = _templates_dir(tenant_id) / f"{body.template_name}.yaml"
    if out_path.exists() and not body.overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"Template {body.template_name!r} already exists. Pass overwrite=true to replace.",
        )

    try:
        out_path.write_text(yaml.safe_dump(template, sort_keys=False), encoding="utf-8")
    except Exception as exc:
        logger.exception("create_template failed")
        raise HTTPException(status_code=500, detail="An internal error occurred")

    logger.info("Saved workstream template %r from workstream %r", body.template_name, body.source_workstream)
    return {
        "ok": True,
        "template_name": body.template_name,
        "source_workstream": body.source_workstream,
        "path": str(out_path.relative_to(SERVER_DIR)),
    }


@router.delete("/api/workstream-templates/{name}")
async def delete_template(name: str, tenant_id: str = DEFAULT_TENANT_ID):
    if not _VALID_NAME.match(name):
        raise HTTPException(status_code=400, detail="Invalid template name")
    path = _templates_dir(tenant_id) / f"{name}.yaml"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Template {name!r} not found")
    try:
        path.unlink()
    except Exception as exc:
        logger.exception("delete_template failed")
        raise HTTPException(status_code=500, detail="An internal error occurred")
    return {"ok": True, "deleted": name}
