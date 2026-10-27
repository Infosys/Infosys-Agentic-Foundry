"""
IAF Agent Studio — Knowledge Store & Memory Dashboard Router

Knowledge CRUD (confirm, reject, edit, merge, duplicates), learning,
thumbs feedback, batch extraction, and memory search/stats/reindex.
"""

import asyncio
import logging
import os
import re
import traceback
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from security.dependencies import require_scoped_identity
from shared.models import (
    KnowledgeAction, KnowledgeEdit, KnowledgeMerge, KnowledgeBulkAction,
    ThumbsFeedback, LearnRequest, BatchExtractRequest,
)
from shared.state import state
from shared.config import DATA_ROOT, DATA_ROOT_PATH, SERVER_DIR, SKILLS_PATH_PATH
from iaf_agent_skills.capture_events import emit_feedback_thumbs

logger = logging.getLogger(__name__)

router = APIRouter()


# Dialect-neutral SQL helpers (SQLite and Postgres); use via `with indexer.connect() as conn`.
def _kn_group_concat(indexer, expr: str, sep: str = "|") -> str:
    """Portable GROUP_CONCAT(expr, sep) — string_agg() on Postgres."""
    if getattr(indexer, "backend", "sqlite") == "postgres":
        return f"string_agg({expr}, '{sep}')"
    return f"GROUP_CONCAT({expr}, '{sep}')"


def _kn_ts_cutoff(days: int) -> str:
    """ISO cutoff string for 'last N days' on the TEXT ts column. String comparison
    is chronologically correct for same-format ISO timestamps and portable across
    backends — avoids SQLite-only datetime('now', ...)."""
    from datetime import datetime as _dt, timedelta as _td
    return (_dt.now() - _td(days=days)).isoformat()


def _scope(
    request: Request,
    *,
    tenant_id: str,
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
    action: str = "read",
    resource_type: str = "knowledge",
    resource_id: str = "*",
):
    return require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        requested_agent=agent_id,
        requested_user=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
    )


_file_routers: dict = {}   # {(contexts_dir_str, agent_id, user_id): KnowledgeFileRouter}


def _resolve_data_root() -> Path:
    """Resolve DATA_ROOT using the same rules as the runtime agent."""
    data_root = Path(DATA_ROOT)
    if not data_root.is_absolute():
        data_root = (SERVER_DIR / data_root).resolve()
    return data_root


def _get_knowledge_dashboard_store(
    tenant_id: str,
    agent_id: str,
):
    """Return a lightweight read-only store for Knowledge Dashboard endpoints."""
    from knowledge_dashboard_store import KnowledgeDashboardStore

    data_root = _resolve_data_root()
    memory_root = data_root / "tenants" / tenant_id / "agents" / agent_id / "memory"
    return KnowledgeDashboardStore(memory_root)


def _get_file_router(
    tenant_id: str,
    agent_id: str,
    user_id: Optional[str] = None,
):
    """
    Return the KnowledgeFileRouter for a tenant+agent, building it lazily.

    memory_root is resolved from the agent's own memory/ directory (same path
    SafeKernel uses) so that write_to_memory() writes MEMORY.md topic files
    and regenerates the index after every confirmed knowledge append.
    agent_id comes from the request — never hardcoded here.
    """
    from knowledge_file_router import KnowledgeFileRouter

    data_root = _resolve_data_root()

    contexts_dir = data_root / "tenants" / tenant_id / "shared" / "contexts"
    memory_root  = data_root / "tenants" / tenant_id / "agents" / agent_id / "memory"
    knowledge_dir = data_root / "tenants" / tenant_id / "shared" / "knowledge"
    skills_dir = Path(SKILLS_PATH_PATH)

    key = (str(contexts_dir), str(knowledge_dir), str(skills_dir), agent_id, user_id or "")
    if key not in _file_routers:
        _file_routers[key] = KnowledgeFileRouter(
            contexts_dir=contexts_dir,
            memory_root=memory_root,
            knowledge_dir=knowledge_dir,
            skills_dir=skills_dir,
            user_id=user_id,
        )

    return _file_routers[key]


def _record_by_id(agent, knowledge_id: str) -> Optional[dict]:
    """Read the authoritative latest record without a pagination limit."""
    finder = getattr(agent.memory, "_find_knowledge_by_id", None)
    if callable(finder):
        return finder(knowledge_id)
    items = agent.memory.query_knowledge(
        status=None,
        limit=10_000,
        include_archived=True,
    ).get("items", [])
    return next((item for item in items if item.get("id") == knowledge_id), None)


def _resolve_target_file(file_router, target_file: str) -> str:
    """Resolve virtual/relative targets and reject paths outside tenant roots."""
    raw = str(target_file or "").strip()
    if not raw:
        return ""

    virtual_roots = {
        "/shared/contexts/": file_router.contexts_dir,
        "/shared/knowledge/": file_router.knowledge_dir,
        "/memory/": file_router.memory_root,
        "/skills/": file_router.skills_dir,
        "shared/contexts/": file_router.contexts_dir,
        "shared/knowledge/": file_router.knowledge_dir,
        "memory/": file_router.memory_root,
        "skills/": file_router.skills_dir,
    }
    candidate: Optional[Path] = None
    for prefix, root in virtual_roots.items():
        if raw.startswith(prefix):
            if root is None:
                raise HTTPException(400, f"Target namespace is unavailable: {prefix}")
            candidate = Path(root) / raw[len(prefix):]
            break
    if candidate is None:
        candidate = Path(raw)
        if not candidate.is_absolute():
            raise HTTPException(400, "target_file must be an allowed virtual or absolute path")

    resolved = candidate.resolve()
    allowed_roots = [
        Path(root).resolve()
        for root in (
            file_router.contexts_dir,
            file_router.knowledge_dir,
            file_router.memory_root,
            file_router.skills_dir,
        )
        if root is not None
    ]
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise HTTPException(400, "target_file is outside the tenant knowledge roots")
    return str(resolved)


def _validate_skill_definition_target(
    file_router,
    target_file: str,
    record: dict,
    *,
    allow_skill_definition: bool,
) -> None:
    """Require an explicit, exact skill match before mutating SKILL.md."""
    target_skill = file_router._skill_definition_name(Path(target_file))
    if not target_skill:
        return
    if not allow_skill_definition:
        raise HTTPException(
            400,
            "Writing to SKILL.md requires explicit advanced-target approval",
        )
    scope = record.get("scope") or {}
    record_skill = str(record.get("skill") or scope.get("skill") or "").strip()
    if not record_skill:
        raise HTTPException(
            409,
            "This knowledge record has no skill scope; assign a skill before writing to SKILL.md",
        )
    if record_skill != target_skill:
        raise HTTPException(
            409,
            f"Knowledge skill '{record_skill}' does not match target skill '{target_skill}'",
        )


def _confirm_and_publish(
    *,
    agent,
    file_router,
    knowledge_id: str,
    target_file: Optional[str],
    allow_skill_definition: bool = False,
) -> dict:
    """Confirm first, then publish; persist written_to only after a real write."""
    record = _record_by_id(agent, knowledge_id)
    if not record:
        return {
            "status": "failed",
            "knowledge_id": knowledge_id,
            "publication_status": "not_attempted",
            "error": "Knowledge record not found",
        }

    resolved_target = ""
    if target_file:
        resolved_target = _resolve_target_file(file_router, target_file)
        _validate_skill_definition_target(
            file_router,
            resolved_target,
            record,
            allow_skill_definition=allow_skill_definition,
        )

    if not agent.memory.confirm_knowledge(knowledge_id):
        return {
            "status": "failed",
            "knowledge_id": knowledge_id,
            "publication_status": "not_attempted",
            "error": "Knowledge record could not be confirmed",
        }

    response = {
        "status": "confirmed",
        "knowledge_id": knowledge_id,
        "publication_status": "skipped",
        "written_to": None,
    }
    if not resolved_target:
        return response

    confirmed_record = dict(record)
    confirmed_record["status"] = "confirmed"
    try:
        file_router.append(resolved_target, confirmed_record)
    except Exception as append_err:
        logger.exception(
            "Knowledge %s confirmed but publication to %s failed",
            knowledge_id,
            resolved_target,
        )
        response.update({
            "status": "partial",
            "publication_status": "failed",
            "append_error": str(append_err),
        })
        return response

    if not agent.memory.edit_knowledge(knowledge_id, written_to=resolved_target):
        response.update({
            "status": "partial",
            "publication_status": "published_metadata_failed",
            "written_to": resolved_target,
            "append_error": "File was written, but written_to metadata could not be persisted",
        })
        return response

    response.update({
        "publication_status": "published",
        "written_to": resolved_target,
    })
    logger.info("Knowledge %s published to %s", knowledge_id, resolved_target)
    return response


@router.get("/api/knowledge")
async def list_knowledge(
    request: Request,
    status: Optional[str] = None,
    knowledge_type: Optional[str] = None,
    skill: Optional[str] = None,
    tag: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    include_archived: bool = False,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Query the knowledge store with optional filters and pagination."""
    _principal, tenant_id, agent_id, user_id = _scope(
        request, tenant_id=tenant_id, agent_id=agent_id, user_id=user_id
    )
    try:
        store = _get_knowledge_dashboard_store(tenant_id, agent_id)
        # Auto-include archived if explicitly filtering for them or requesting all
        effective_include_archived = include_archived or status == "archived" or status is None
        result = store.query_knowledge(
            status=status,
            knowledge_type=knowledge_type,
            skill=skill,
            tag=tag,
            source=source,
            limit=limit,
            offset=offset,
            include_archived=effective_include_archived,
        )
        return {"knowledge": result["items"], "total": result["total"],
                "offset": result["offset"], "limit": result["limit"]}
    except Exception as e:
        logger.error("list_knowledge failed: %s", e, exc_info=True)
        return {"knowledge": [], "total": 0, "offset": offset, "limit": limit, "error": "An internal error occurred"}


@router.get("/api/knowledge/context-files")
async def list_context_files(
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
):
    """Return all available context .md files for the tenant (used by Written To picker)."""
    _principal, tenant_id, agent_id, _user_id = _scope(
        request, tenant_id=tenant_id, agent_id=agent_id
    )
    try:
        file_router = _get_file_router(tenant_id, agent_id)
        files = file_router.list_files()
        return {"files": files}
    except Exception as e:
        logger.error("list_context_files failed: %s", e, exc_info=True)
        return {"files": [], "error": "An internal error occurred"}


@router.get("/api/knowledge/stats")
async def knowledge_stats(
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Get knowledge store statistics (counts by status, type, source)."""
    _principal, tenant_id, agent_id, user_id = _scope(
        request, tenant_id=tenant_id, agent_id=agent_id, user_id=user_id
    )
    try:
        store = _get_knowledge_dashboard_store(tenant_id, agent_id)
        return store.get_knowledge_stats()
    except Exception as e:
        logger.error("knowledge_stats failed: %s", e, exc_info=True)
        return {"error": "An internal error occurred"}


@router.get("/api/learning-inbox")
async def get_learning_inbox(
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    limit: int = 50,
):
    """Aggregate pending knowledge and captured feedback into one review inbox."""
    _principal, tenant_id, agent_id, _user_id = _scope(
        request, tenant_id=tenant_id, agent_id=agent_id
    )
    try:
        from shared.learning_inbox_store import learning_inbox

        return learning_inbox(tenant_id=tenant_id, agent_id=agent_id, limit=limit)
    except Exception as e:
        logger.error("learning_inbox failed: %s", e, exc_info=True)
        return {"items": [], "total": 0, "error": "An internal error occurred"}


@router.get("/api/knowledge/{knowledge_id}/suggest-file")
async def suggest_file_for_knowledge(
    knowledge_id: str,
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """
    Suggest which context .md file a knowledge record should be appended to.

    Returns:
        - suggested_file  : relative path of the best-match file (empty if none)
        - confidence      : "high" | "medium" | "low" | "none"
        - method          : "skill" | "alias" | "llm" | "none"
        - all_files       : list of all context files (for the dashboard override picker)
    """
    principal, tenant_id, agent_id, user_id = _scope(
        request,
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        resource_id=knowledge_id,
    )
    try:
        user_role = principal.roles[0] if principal.roles else "user"
        # Fetch the knowledge record so we can route on its fields
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        result = agent.memory.query_knowledge(status=None, limit=1, include_archived=True)

        record = None
        all_items = agent.memory.query_knowledge(
            status=None, limit=500, include_archived=True
        ).get("items", [])
        for item in all_items:
            if item.get("id") == knowledge_id:
                record = item
                break

        if not record:
            raise HTTPException(404, f"Knowledge record {knowledge_id} not found")

        file_router = _get_file_router(tenant_id, agent_id, user_id)

        # Fast path: nightly batch pre-computed the suggestion — skip LLM call
        pre_computed = (record.get("scope") or {}).get("suggested_file")
        if pre_computed:
            all_files = file_router.list_files()
            matched = next((f for f in all_files if f["rel_path"] == pre_computed), None)
            file_path = matched["file_path"] if matched else ""
            logger.info("suggest-file fast path: %s (pre_computed)", pre_computed)
            return {
                "knowledge_id"    : knowledge_id,
                "suggested_file"  : pre_computed,
                "file_path"       : file_path,
                "confidence"      : "high",
                "method"          : "pre_computed",
                "all_files"       : all_files,
                "memory_dest_type": "",
                "memory_dest_name": "",
                "bundle_id"       : "",
            }

        suggestion = file_router.suggest(record)

        return {
            "knowledge_id"    : knowledge_id,
            "suggested_file"  : suggestion.rel_path,
            "file_path"       : suggestion.file_path,
            "confidence"      : suggestion.confidence,
            "method"          : suggestion.method,
            "all_files"       : suggestion.candidates,
            "memory_dest_type": suggestion.memory_dest_type,
            "memory_dest_name": suggestion.memory_dest_name,
            "bundle_id"       : suggestion.bundle_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("suggest-file failed for %s", knowledge_id)
        raise HTTPException(500, "An internal error occurred")


@router.post("/api/knowledge/confirm")
async def confirm_knowledge(req: KnowledgeAction, request: Request):
    """
    Confirm a pending_review knowledge record.

    If req.target_file is provided, the confirmed record is also appended to
    that context .md file so file-mode agents see it on the next run.
    """
    principal, req.tenant_id, req.agent_id, req.user_id = _scope(
        request,
        tenant_id=req.tenant_id,
        agent_id=req.agent_id,
        user_id=req.user_id,
        action="write",
        resource_id=req.knowledge_id,
    )
    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(req.tenant_id, req.agent_id, req.user_id, user_role=user_role)
        file_router = _get_file_router(req.tenant_id, req.agent_id, req.user_id)
        target_file = req.target_file
        if not target_file and req.new_file_name and req.new_file_type:
            stem = re.sub(r"[^\w\-]", "_", req.new_file_name.strip()).strip("_") or "unknown"
            if req.new_file_type == "entity":
                target_file = str(file_router.memory_root / "entities" / f"{stem}.md")
            elif req.new_file_type == "org":
                target_file = str(file_router.memory_root / "org" / f"{stem}.md")
            else:
                raise HTTPException(400, "new_file_type must be 'entity' or 'org'")

        # If the user did not choose a target file, only auto-target convention
        # knowledge bundles. Explicit skip_file_write disables all publication.
        record = _record_by_id(agent, req.knowledge_id)
        if not record:
            raise HTTPException(404, f"Knowledge {req.knowledge_id} not found")
        suggested_file = ""
        bundle_id = ""
        if not target_file and not req.skip_file_write:
            try:
                suggestion = file_router.suggest(record)
                if suggestion.method.startswith("bundle_"):
                    target_file = suggestion.file_path
                    suggested_file = suggestion.rel_path
                    bundle_id = suggestion.bundle_id
            except Exception as suggest_err:
                logger.warning("Bundle suggestion after confirm failed (non-fatal): %s", suggest_err)

        response = _confirm_and_publish(
            agent=agent,
            file_router=file_router,
            knowledge_id=req.knowledge_id,
            target_file=target_file,
            allow_skill_definition=req.allow_skill_definition,
        )
        if response["status"] == "failed":
            raise HTTPException(409, response["error"])
        if suggested_file:
            response["suggested_file"] = suggested_file
            response["bundle_id"] = bundle_id
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("confirm_knowledge failed")
        raise HTTPException(500, "An internal error occurred")


@router.post("/api/knowledge/reject")
async def reject_knowledge(req: KnowledgeAction, request: Request):
    """Reject/archive a knowledge record."""
    principal, req.tenant_id, req.agent_id, req.user_id = _scope(
        request,
        tenant_id=req.tenant_id,
        agent_id=req.agent_id,
        user_id=req.user_id,
        action="write",
        resource_id=req.knowledge_id,
    )
    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(req.tenant_id, req.agent_id, req.user_id, user_role=user_role)
        result = agent.memory.reject_knowledge(req.knowledge_id)
        if result:
            return {"status": "archived", "knowledge_id": req.knowledge_id}
        else:
            raise HTTPException(404, f"Knowledge {req.knowledge_id} not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("reject_knowledge failed")
        raise HTTPException(500, "An internal error occurred")


@router.post("/api/knowledge/edit")
async def edit_knowledge(req: KnowledgeEdit, request: Request):
    """Edit a knowledge record in place, preserving its status.

    If written_to changes to a new file path, the record is also appended to that file.
    Empty string clears the written_to association without appending.
    """
    principal, req.tenant_id, req.agent_id, req.user_id = _scope(
        request,
        tenant_id=req.tenant_id,
        agent_id=req.agent_id,
        user_id=req.user_id,
        action="write",
        resource_id=req.knowledge_id,
    )
    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(req.tenant_id, req.agent_id, req.user_id, user_role=user_role)
        result = agent.memory.edit_knowledge(
            knowledge_id=req.knowledge_id,
            summary=req.summary,
            knowledge_type=req.knowledge_type,
            applies_when=req.applies_when,
            tags=req.tags,
            entity_keys=req.entity_keys,
            written_to=req.written_to,
        )
        if not result:
            raise HTTPException(404, f"Knowledge {req.knowledge_id} not found")

        response: dict = {"status": "updated", "knowledge_id": req.knowledge_id}

        # Append to the new context file when written_to is set to a real path
        if req.written_to:
            try:
                all_items = agent.memory.query_knowledge(
                    status=None, limit=500, include_archived=True
                ).get("items", [])
                record = next((i for i in all_items if i.get("id") == req.knowledge_id), None)
                if record:
                    file_router = _get_file_router(req.tenant_id, req.agent_id, req.user_id)
                    file_router.append(req.written_to, record)
                    response["written_to"] = req.written_to
                    logger.info("Knowledge %s written_to updated → %s", req.knowledge_id, req.written_to)
            except Exception as append_err:
                logger.warning("Append on written_to edit failed (non-fatal): %s", append_err)
                response["append_error"] = str(append_err)

        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("edit_knowledge failed")
        raise HTTPException(500, "An internal error occurred")


@router.post("/api/knowledge/bulk-confirm")
async def bulk_confirm_knowledge(req: KnowledgeBulkAction, request: Request):
    """Bulk confirm records and publish deterministic/high-confidence routes."""
    principal, req.tenant_id, req.agent_id, req.user_id = _scope(
        request,
        tenant_id=req.tenant_id,
        agent_id=req.agent_id,
        user_id=req.user_id,
        action="write",
        resource_id="bulk",
    )
    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(req.tenant_id, req.agent_id, req.user_id, user_role=user_role)
        file_router = _get_file_router(req.tenant_id, req.agent_id, req.user_id)
        results = []
        for knowledge_id in req.knowledge_ids:
            record = _record_by_id(agent, knowledge_id)
            target_file = ""
            route_method = "none"
            if record and req.publish_to_suggested_file:
                try:
                    suggestion = file_router.suggest(record)
                    route_method = suggestion.method
                    # LLM fallback is intentionally not auto-published in bulk.
                    if suggestion.file_path and (
                        route_method == "entity"
                        or route_method == "source_context"
                        or route_method.startswith("bundle_")
                    ):
                        target_file = suggestion.file_path
                except Exception as route_err:
                    logger.warning("Bulk route failed for %s: %s", knowledge_id, route_err)
            item = _confirm_and_publish(
                agent=agent,
                file_router=file_router,
                knowledge_id=knowledge_id,
                target_file=target_file or None,
            )
            item["route_method"] = route_method
            results.append(item)

        confirmed = [r for r in results if r["status"] in ("confirmed", "partial")]
        failed = [r for r in results if r["status"] == "failed"]
        published = [r for r in confirmed if r["publication_status"] == "published"]
        publication_failed = [
            r for r in confirmed
            if r["publication_status"] in ("failed", "published_metadata_failed")
        ]
        confirmed_only = [
            r for r in confirmed if r["publication_status"] == "skipped"
        ]
        return {
            "status": "partial" if failed or publication_failed or confirmed_only else "ok",
            "confirmed": len(confirmed),
            "published": len(published),
            "confirmed_only": len(confirmed_only),
            "publication_failed": len(publication_failed),
            "failed": len(failed),
            "success_ids": [r["knowledge_id"] for r in confirmed],
            "failed_ids": [r["knowledge_id"] for r in failed],
            "results": results,
        }
    except Exception as e:
        logger.exception("bulk_confirm_knowledge failed")
        raise HTTPException(500, "An internal error occurred")


@router.post("/api/knowledge/bulk-reject")
async def bulk_reject_knowledge(req: KnowledgeBulkAction, request: Request):
    """Bulk reject/archive multiple knowledge records."""
    principal, req.tenant_id, req.agent_id, req.user_id = _scope(
        request,
        tenant_id=req.tenant_id,
        agent_id=req.agent_id,
        user_id=req.user_id,
        action="write",
        resource_id="bulk",
    )
    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(req.tenant_id, req.agent_id, req.user_id, user_role=user_role)
        result = agent.memory.bulk_reject_knowledge(req.knowledge_ids)
        return {
            "status": "ok",
            "archived": len(result["success"]),
            "failed": len(result["failed"]),
            "success_ids": result["success"],
            "failed_ids": result["failed"],
        }
    except Exception as e:
        logger.exception("bulk_reject_knowledge failed")
        raise HTTPException(500, "An internal error occurred")


@router.get("/api/knowledge/duplicates")
async def find_knowledge_duplicates(
    request: Request,
    status: str = "all",
    min_group_size: int = 2,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """LLM-powered semantic duplicate detection across knowledge records."""
    principal, tenant_id, agent_id, user_id = _scope(
        request, tenant_id=tenant_id, agent_id=agent_id, user_id=user_id
    )
    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        if not agent.memory:
            raise HTTPException(500, "Agent memory not initialized")

        # LLM-backed and slow: run it off the event loop so other requests keep flowing.
        result = await asyncio.to_thread(
            agent.memory.find_duplicate_groups,
            status=status,
            min_group_size=min_group_size,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        logger.exception("find_knowledge_duplicates failed")
        raise HTTPException(500, "An internal error occurred")


@router.post("/api/knowledge/merge")
async def merge_knowledge(req: KnowledgeMerge, request: Request):
    """Merge duplicate knowledge: keep one record, archive the rest."""
    principal, req.tenant_id, req.agent_id, req.user_id = _scope(
        request,
        tenant_id=req.tenant_id,
        agent_id=req.agent_id,
        user_id=req.user_id,
        action="write",
        resource_id=req.keep_id,
    )
    try:
        if req.keep_id in req.archive_ids:
            raise HTTPException(400, "keep_id cannot be in archive_ids")
        if not req.archive_ids:
            raise HTTPException(400, "At least one archive_id required")

        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(req.tenant_id, req.agent_id, req.user_id, user_role=user_role)
        if not agent.memory:
            raise HTTPException(500, "Agent memory not initialized")

        result = agent.memory.merge_knowledge(
            keep_id=req.keep_id,
            archive_ids=req.archive_ids,
            merged_summary=req.merged_summary,
        )

        if result.get("status") == "error":
            raise HTTPException(400, result.get("errors", ["Unknown error"])[0])

        return result
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        logger.exception("merge_knowledge failed")
        raise HTTPException(500, "An internal error occurred")


@router.post("/api/thumbs")
async def thumbs_feedback(req: ThumbsFeedback, request: Request):
    """Handle thumbs up/down on assistant messages."""
    principal, req.tenant_id, req.agent_id, req.user_id = _scope(
        request,
        tenant_id=req.tenant_id,
        agent_id=req.agent_id,
        user_id=req.user_id,
        action="write",
        resource_id="feedback",
    )
    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(req.tenant_id, req.agent_id, req.user_id, user_role=user_role)
        try:
            emit_feedback_thumbs(
                data_root=DATA_ROOT_PATH,
                tenant_id=req.tenant_id,
                agent_id=req.agent_id,
                user_id=req.user_id,
                direction=req.direction,
                trajectory_id=req.rl_trajectory_id or req.request_trace_id or "",
                model_call_id=req.rl_model_call_id or "",
                query=req.query,
                response_snippet=req.response_snippet,
                skill=req.skill,
            )
        except Exception as _rl_err:
            logger.warning("RL thumbs reward capture failed (non-fatal): %s", _rl_err)

        if req.direction == "down":
            knowledge_id = agent.memory.write_knowledge(
                knowledge_type="correction",
                summary=f"User flagged response as unhelpful for: {req.query[:200]}",
                skill=req.skill,
                tags=["thumbs_down", "needs_review"],
                source="thumbs_down",
                status="pending_review",
                episode_id=None,
            )
            return {
                "status": "recorded",
                "direction": "down",
                "knowledge_id": knowledge_id,
                "message": "Feedback recorded. You can teach me what went wrong.",
            }
        else:
            # Thumbs up — positive signal, log for analytics
            return {
                "status": "recorded",
                "direction": "up",
                "message": "Thanks for the feedback!",
            }
    except Exception as e:
        logger.error("thumbs_feedback failed: %s", e, exc_info=True)
        return {"status": "error", "error": "An internal error occurred"}


@router.post("/api/learn")
async def learn_from_user(req: LearnRequest, request: Request):
    """User explicitly teaches the agent via /learn command or learning card."""
    principal, req.tenant_id, req.agent_id, req.user_id = _scope(
        request,
        tenant_id=req.tenant_id,
        agent_id=req.agent_id,
        user_id=req.user_id,
        action="write",
        resource_id="learn",
    )
    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(req.tenant_id, req.agent_id, req.user_id, user_role=user_role)

        status = req.status if req.status in ("confirmed", "pending_review") else "confirmed"
        source = req.source or ("user_taught" if status == "confirmed" else "llm_suggested")

        # Use source_context_file from request if provided, else fall back to
        # the agent's current session context file (for non-card /learn calls).
        _src_ctx = req.source_context_file or Path(
            getattr(state.get_or_create(req.tenant_id, req.agent_id, req.user_id,
                                        user_role=user_role), '_context_file_path', '') or ''
        ).name or None

        knowledge_id = agent.memory.write_knowledge(
            knowledge_type=req.knowledge_type,
            summary=req.summary,
            skill=req.skill,
            tags=req.tags,
            applies_when=req.applies_when,
            source=source,
            status=status,
            episode_id=None,
            entity_keys=req.entity_keys or [],
            source_context_file=_src_ctx,
        )

        written_to = None
        if status == "confirmed":
            try:
                file_router = _get_file_router(req.tenant_id, req.agent_id, req.user_id)
                all_items = agent.memory.query_knowledge(
                    status=None, limit=500, include_archived=True
                ).get("items", [])
                record = next((i for i in all_items if i.get("id") == knowledge_id), None)
                if not record:
                    raise ValueError(f"Knowledge {knowledge_id} not found after write")

                ctx_path = file_router.contexts_dir / _src_ctx if _src_ctx else None
                if ctx_path and ctx_path.exists():
                    file_router.append(str(ctx_path), record)
                    written_to = str(ctx_path)
                    logger.info("learn /api/learn: appended %s to %s", knowledge_id, _src_ctx)
                else:
                    suggestion = file_router.suggest(record)
                    if suggestion.method.startswith("bundle_"):
                        file_router.append(suggestion.file_path, record)
                        written_to = suggestion.file_path
                        agent.memory.edit_knowledge(knowledge_id, written_to=written_to)
                    else:
                        # Context file not found — still write to memory topic tree directly
                        file_router.write_to_memory(record)
            except Exception as _fe:
                logger.warning("learn /api/learn: file/memory write failed (non-fatal): %s", _fe)

        return {
            "status": "learned" if status == "confirmed" else "pending_review",
            "knowledge_id": knowledge_id,
            "written_to": written_to,
            "message": (
                f"Got it! I'll remember: {req.summary[:100]}"
                if status == "confirmed"
                else f"Saved for review. Check Knowledge Dashboard: {req.summary[:80]}..."
            ),
        }
    except Exception as e:
        logger.error("learn_from_user failed: %s", e, exc_info=True)
        return {"status": "error", "error": "An internal error occurred"}


@router.post("/api/knowledge/batch-extract")
async def batch_extract_knowledge(req: BatchExtractRequest, request: Request):
    """Mine recent episodic logs for reusable knowledge."""
    principal, req.tenant_id, req.agent_id, req.user_id = _scope(
        request,
        tenant_id=req.tenant_id,
        agent_id=req.agent_id,
        user_id=req.user_id,
        action="write",
        resource_id="batch-extract",
    )
    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(req.tenant_id, req.agent_id, req.user_id, user_role=user_role)

        if not agent.memory:
            return {"status": "error", "error": "Agent memory not initialized"}

        result = agent.memory.batch_extract_knowledge(
            hours_back=req.hours_back,
            max_tokens_budget=req.max_tokens_budget,
            skill=req.skill,
            force_full=req.force_full,
        )

        # Pre-compute a file routing suggestion per record (scope.suggested_file) to avoid an LLM call at review.
        knowledge_ids = result.get("knowledge_ids", [])
        if knowledge_ids:
            try:
                file_router = _get_file_router(req.tenant_id, req.agent_id, req.user_id)
                all_items = agent.memory.query_knowledge(
                    status=None, limit=1000, include_archived=False
                ).get("items", [])
                id_to_record = {r["id"]: r for r in all_items if r.get("id")}
                suggested_count = 0
                for kid in knowledge_ids:
                    record = id_to_record.get(kid)
                    if not record:
                        continue
                    suggestion = file_router.suggest(record)
                    if suggestion.rel_path:
                        agent.memory.edit_knowledge(kid, suggested_file=suggestion.rel_path)
                        suggested_count += 1
                result["suggested_files_pre_computed"] = suggested_count
                logger.info("batch_extract: pre-computed %d file suggestions", suggested_count)
            except Exception as _sfe:
                logger.warning("batch_extract: file suggestion pre-compute failed (non-fatal): %s", _sfe)

        return result
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "error": "An internal error occurred"}


@router.get("/api/knowledge/extract-status")
async def get_extract_status(
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Return the extraction cursor — last_extracted_at, episodes_processed, knowledge_extracted."""
    _principal, tenant_id, agent_id, user_id = _scope(
        request, tenant_id=tenant_id, agent_id=agent_id, user_id=user_id
    )
    try:
        store = _get_knowledge_dashboard_store(tenant_id, agent_id)
        cursor = store.get_extraction_status()
        return {"status": "ok", "cursor": cursor}
    except Exception as e:
        logger.error("get_extract_status failed: %s", e, exc_info=True)
        return {"status": "error", "error": "An internal error occurred"}


@router.get("/api/memory/stats")
async def memory_stats(
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Unified memory statistics for the dashboard."""
    principal, tenant_id, agent_id, user_id = _scope(
        request,
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        resource_type="memory",
    )
    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        indexer = agent.memory.knowledge_indexer
        stats = indexer.get_stats()

        # DB file size (human-readable). Prefer the backend-aware size from get_stats
        # (Postgres schema total / SQLite file+WAL); fall back to the legacy file check.
        db_size_bytes = stats.get("storage_size_bytes")
        if db_size_bytes is None:
            db_path = stats.get("db_path", "")
            db_size_bytes = 0
            if db_path and os.path.exists(db_path):
                db_size_bytes = os.path.getsize(db_path)

        if db_size_bytes > 1_048_576:
            db_size_str = f"{db_size_bytes / 1_048_576:.1f} MB"
        elif db_size_bytes > 1024:
            db_size_str = f"{db_size_bytes / 1024:.1f} KB"
        else:
            db_size_str = f"{db_size_bytes} B"

        total_k = stats.get("knowledge_records", 0)
        with_emb = stats.get("with_embeddings", 0)
        coverage_pct = round((with_emb / total_k * 100) if total_k > 0 else 0, 1)

        # JSONL bloat stats for observability
        jsonl_bloat = {}
        try:
            jsonl_bloat = agent.memory.get_jsonl_bloat_stats()
        except Exception as e:
            logger.warning("JSONL bloat stats unavailable (non-fatal): %s", e)
            jsonl_bloat = {"total_lines": 0, "bloat_pct": 0.0, "error": "unavailable"}

        return {
            "knowledge_records": total_k,
            "episode_records": stats.get("episode_records", 0),
            "unique_entities": stats.get("unique_entities", 0),
            "entity_xrefs": stats.get("entity_xrefs", 0),
            "with_embeddings": with_emb,
            "without_embeddings": stats.get("without_embeddings", 0),
            "embedding_coverage_pct": coverage_pct,
            "has_embedding_fn": stats.get("has_embedding_fn", False),
            "by_status": stats.get("by_status", {}),
            "by_type": stats.get("by_type", {}),
            "db_size": db_size_str,
            "db_size_bytes": db_size_bytes,
            "jsonl_bloat": jsonl_bloat,
        }
    except Exception as e:
        logger.error("memory_stats failed: %s", e, exc_info=True)
        return {"error": "An internal error occurred", "knowledge_records": 0, "episode_records": 0,
                "unique_entities": 0, "embedding_coverage_pct": 0}


@router.get("/api/memory/search")
async def memory_search(
    request: Request,
    q: str = "",
    scope: str = "all",
    skill: Optional[str] = None,
    entity: Optional[str] = None,
    limit: int = 10,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Unified semantic search across knowledge and episodes."""
    principal, tenant_id, agent_id, user_id = _scope(
        request,
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        resource_type="memory",
        resource_id="search",
    )
    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        indexer = agent.memory.knowledge_indexer

        knowledge_results = []
        episode_results = []

        effective_skill = skill if skill and skill != "all" else None

        # Entity lookup path (uses entity_xref table, no embedding needed)
        if entity and entity.strip():
            entity_hits = indexer.entity_lookup(entity.strip(), top_k=limit)
            for hit in entity_hits:
                if hit.get("id", "").startswith("ep_"):
                    episode_results.append(hit)
                else:
                    knowledge_results.append(hit)

            # If also have a query, merge with semantic results
            if q and q.strip():
                if scope in ("all", "knowledge"):
                    sem_k = indexer.search_similar(q.strip(), top_k=limit, skill=effective_skill, min_score=0.74)
                    existing_ids = {r["id"] for r in knowledge_results}
                    for r in sem_k:
                        if r["id"] not in existing_ids:
                            knowledge_results.append(r)

                if scope in ("all", "episodes"):
                    sem_e = indexer.search_episodes(q.strip(), top_k=limit, skill=effective_skill, min_score=0.74)
                    existing_ids = {r["id"] for r in episode_results}
                    for r in sem_e:
                        if r["id"] not in existing_ids:
                            episode_results.append(r)

        elif q and q.strip():
            query = q.strip()
            # Pure semantic search (no entity filter)
            if scope in ("all", "knowledge"):
                knowledge_results = indexer.search_similar(
                    query, top_k=limit, skill=effective_skill, min_score=0.74,
                )
            if scope in ("all", "episodes"):
                episode_results = indexer.search_episodes(
                    query, top_k=limit, skill=effective_skill, min_score=0.74,
                )

            # Entity-name fallback: queries like 'ACME Corp' are entity refs that cosine/FTS may miss.
            entity_hits = indexer.entity_lookup(query, top_k=limit)
            k_ids = {r["id"] for r in knowledge_results}
            e_ids = {r["id"] for r in episode_results}
            for hit in entity_hits:
                hid = hit.get("id", "")
                if not hid:
                    continue
                if hid.startswith("ep_"):
                    if scope in ("all", "episodes") and hid not in e_ids:
                        episode_results.append(hit)
                        e_ids.add(hid)
                elif scope in ("all", "knowledge") and hid not in k_ids:
                    knowledge_results.append(hit)
                    k_ids.add(hid)

        return {
            "knowledge": knowledge_results[:limit],
            "episodes": episode_results[:limit],
            "query": q,
            "scope": scope,
            "skill": skill,
            "entity": entity,
        }
    except Exception as e:
        traceback.print_exc()
        return {"knowledge": [], "episodes": [], "error": "An internal error occurred"}


@router.post("/api/memory/reindex")
async def memory_reindex(
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Trigger full reindex of knowledge + episodes."""
    principal, tenant_id, agent_id, user_id = _scope(
        request,
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        action="write",
        resource_type="memory",
        resource_id="reindex",
    )
    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        indexer = agent.memory.knowledge_indexer

        # Compact JSONL first to remove duplicates before reindexing
        compact_stats = agent.memory.compact_knowledge_jsonl()

        knowledge_jsonl = agent.memory.knowledge_jsonl_path
        k_stats = indexer.reindex_all(knowledge_jsonl)

        history_path = agent.memory.history_path
        e_stats = indexer.reindex_episodes(history_path)

        return {
            "status": "ok",
            "compact": compact_stats,
            "knowledge": k_stats,
            "episodes": e_stats,
            "message": f"Compacted ({compact_stats.get('removed', 0)} dupes removed), reindexed {k_stats.get('indexed', 0)} knowledge + {e_stats.get('indexed', 0)} episodes",
        }
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "error": "An internal error occurred"}


@router.post("/api/memory/compact")
async def memory_compact(
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """
    Compact knowledge JSONL by deduplicating records (last-write-wins).
    Archives the original file before compaction for safety.
    """
    principal, tenant_id, agent_id, user_id = _scope(
        request,
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        action="write",
        resource_type="memory",
        resource_id="compact",
    )
    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        result = agent.memory.compact_knowledge_jsonl()
        return {"status": "ok", **result}
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "error": "An internal error occurred"}


@router.get("/api/memory/taxonomy")
async def memory_taxonomy(
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Return taxonomy nodes (tower/process/activity/skill/ENTITY_TYPE) with full metadata.

    Used by the Ontology tab — Taxonomy sub-tab (Query 1 view).
    """
    import json as _json

    principal, tenant_id, agent_id, user_id = _scope(
        request,
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        resource_type="memory",
        resource_id="taxonomy",
    )
    TYPE_ORDER = {"tower": 0, "process": 1, "activity": 2, "ENTITY_TYPE": 3, "skill": 4, "ENTITY": 5}

    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        indexer = agent.memory.knowledge_indexer
        with indexer.connect() as conn:
            cur = conn.cursor()
            cur.execute("""
            SELECT er.node_id, er.node_type, er.display_name, er.parent_id,
                   er.skill_name, er.metadata_json, er.aliases_json,
                   COALESCE(kl.cnt, 0) AS knowledge_links,
                   COALESCE(el.cnt, 0) AS episode_links
            FROM entity_registry er
            LEFT JOIN (SELECT entity, COUNT(*) AS cnt FROM entity_xref
                       WHERE record_type='knowledge' GROUP BY entity) kl
                ON kl.entity = er.node_id
            LEFT JOIN (SELECT entity, COUNT(*) AS cnt FROM entity_xref
                       WHERE record_type='episode' GROUP BY entity) el
                ON el.entity = er.node_id
            WHERE er.node_type IN ('tower','process','activity','skill','ENTITY_TYPE','ENTITY')
            ORDER BY er.node_type, er.node_id
            """)
            rows = cur.fetchall()

        nodes = []
        for row in rows:
            node_id, node_type, display_name, parent_id, skill_name, metadata_json, aliases_json, k_links, e_links = row
            try:
                metadata = _json.loads(metadata_json) if metadata_json else {}
            except Exception as e:
                logger.warning("Failed to parse entity metadata JSON for node %s: %s", node_id, e)
                metadata = {}
            try:
                aliases = _json.loads(aliases_json) if aliases_json else []
            except Exception as e:
                logger.warning("Failed to parse entity aliases JSON for node %s: %s", node_id, e)
                aliases = []
            nodes.append({
                "node_id": node_id,
                "node_type": node_type,
                "display_name": display_name,
                "parent_id": parent_id,
                "skill_name": skill_name or "",
                "metadata": metadata,
                "aliases": aliases,
                "knowledge_links": k_links,
                "episode_links": e_links,
                "sort_order": TYPE_ORDER.get(node_type, 99),
            })

        nodes.sort(key=lambda n: (n["sort_order"], n["parent_id"] or "", n["node_id"]))
        return {"nodes": nodes, "total": len(nodes)}

    except Exception as e:
        traceback.print_exc()
        return {"nodes": [], "total": 0, "error": "An internal error occurred"}


@router.get("/api/memory/entity-path")
async def memory_entity_path(
    node_id: str,
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Return full ancestry path (root → leaf) + sibling skills for a given entity/node.

    Used by the Ontology tab — Entity Path sub-tab (Query 4 view).
    """
    import json as _json

    principal, tenant_id, agent_id, user_id = _scope(
        request,
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        resource_type="memory",
        resource_id=node_id,
    )
    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        indexer = agent.memory.knowledge_indexer
        _ph = indexer.placeholder
        with indexer.connect() as conn:
            cur = conn.cursor()

            def _get_node(nid: str):
                cur.execute(
                    f"SELECT node_id, node_type, display_name, parent_id, skill_name, metadata_json FROM entity_registry WHERE node_id = {_ph}",
                    (nid,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                try:
                    meta = _json.loads(row[5]) if row[5] else {}
                except Exception as e:
                    logger.warning("Failed to parse metadata JSON for entity-path node %s: %s", nid, e)
                    meta = {}
                return {
                    "node_id": row[0], "node_type": row[1], "display_name": row[2],
                    "parent_id": row[3], "skill_name": row[4] or "", "metadata": meta,
                }

            def _resolve_start_id(nid: str):
                """Resolve the starting node_id. Exact node_id wins; otherwise fall back to
                a skill_name match (e.g. 'skill:ar_ops' or bare 'ar_ops' → the ENTITY node
                carrying that skill), then a display_name match. Handles data where skills
                live as skill_name on ENTITY nodes rather than as skill: node_ids."""
                if _get_node(nid):
                    return nid
                candidate = nid.split(":", 1)[1] if ":" in nid else nid
                cur.execute(
                    f"SELECT node_id FROM entity_registry WHERE skill_name = {_ph} ORDER BY node_type LIMIT 1",
                    (candidate,),
                )
                row = cur.fetchone()
                if row:
                    return row[0]
                cur.execute(
                    f"SELECT node_id FROM entity_registry WHERE lower(display_name) = {_ph} LIMIT 1",
                    (candidate.replace("_", " ").replace("-", " ").strip().lower(),),
                )
                row = cur.fetchone()
                return row[0] if row else None

            path = []
            current_id = _resolve_start_id(node_id)
            visited = set()
            while current_id and current_id not in visited:
                visited.add(current_id)
                node = _get_node(current_id)
                if not node:
                    break
                path.append(node)
                current_id = node.get("parent_id")

            # path is leaf→root, reverse to root→leaf
            path.reverse()

            # Find sibling skills: skills that share the same activity/process parent as this node's skill
            sibling_skills = []
            if path:
                leaf = path[-1]
                activity_id = None
                for ancestor in reversed(path):
                    if ancestor["node_type"] in ("activity", "process", "tower"):
                        activity_id = ancestor["node_id"]
                        break
                if activity_id:
                    cur.execute(
                        f"SELECT node_id, node_type, display_name, parent_id, skill_name, metadata_json FROM entity_registry WHERE parent_id = {_ph} AND node_type = 'skill'",
                        (activity_id,),
                    )
                    for row in cur.fetchall():
                        try:
                            meta = _json.loads(row[5]) if row[5] else {}
                        except Exception as e:
                            logger.warning("Failed to parse metadata JSON for sibling skill node %s: %s", row[0], e)
                            meta = {}
                        sibling_skills.append({
                            "node_id": row[0], "node_type": row[1], "display_name": row[2],
                            "parent_id": row[3], "skill_name": row[4] or "", "metadata": meta,
                        })

        return {
            "path": path,
            "sibling_skills": sibling_skills,
            "selected_node_id": node_id,
        }

    except Exception as e:
        traceback.print_exc()
        return {"path": [], "sibling_skills": [], "selected_node_id": node_id, "error": "An internal error occurred"}


@router.get("/api/memory/ontology")
async def memory_ontology(
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Return the full entity ontology tree with cross-reference link counts.

    Used by the dashboard #memory Ontology tab to render the interactive tree.
    """
    principal, tenant_id, agent_id, user_id = _scope(
        request,
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        resource_type="memory",
        resource_id="ontology",
    )
    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        indexer = agent.memory.knowledge_indexer
        if not hasattr(indexer, "entity_registry") or indexer.entity_registry is None:
            return {"nodes": [], "stats": {"total_nodes": 0, "by_type": {},
                    "skill_linked": 0, "total_aliases": 0, "total_knowledge_links": 0}}
        tree = indexer.entity_registry.get_tree()
        return tree
    except Exception as e:
        traceback.print_exc()
        return {"nodes": [], "stats": {"total_nodes": 0, "by_type": {},
                "skill_linked": 0, "total_aliases": 0, "total_knowledge_links": 0},
                "error": "An internal error occurred"}


@router.get("/api/memory/traversal-path")
async def memory_traversal_path(
    node_id: str,
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Return traversal path from root to node (root → leaf order) with metadata.

    Used by Traversal Explorer to show path when a node is selected.
    """
    principal, tenant_id, agent_id, user_id = _scope(
        request,
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        resource_type="memory",
        resource_id=node_id,
    )
    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        indexer = agent.memory.knowledge_indexer
        entity_store = getattr(indexer, "entity_registry", None)
        if not entity_store:
            return {"path": [], "selected_node_id": node_id, "error": "Entity registry not available"}

        ancestors = entity_store.walk_ancestors(node_id)
        if not ancestors:
            return {"path": [], "selected_node_id": node_id}

        path = list(reversed(ancestors))
        return {"path": path, "selected_node_id": node_id}
    except Exception as e:
        traceback.print_exc()
        return {"path": [], "selected_node_id": node_id, "error": "An internal error occurred"}


def _derive_entity_display(entity_key: str) -> tuple:
    """Parse entity key into (display_name, entity_type) without registry lookup.

    Examples:
      customer:skyward_aerospace → ('Skyward Aerospace', 'customer')
      vendor:acme_supplies      → ('Acme Supplies', 'vendor')
      apqc:l3:invoice_proc      → ('Invoice Proc', 'process')
      entity:shared_cloud_svc   → ('Shared Cloud Svc', 'entity')
      skill:payment_processing  → ('Payment Processing', 'skill')
    """
    if not entity_key or ":" not in entity_key:
        return entity_key.replace("_", " ").title(), "unknown"
    prefix, rest = entity_key.split(":", 1)
    # For multi-level keys like apqc:l3:invoice_proc use last segment for name
    name_part = rest.split(":")[-1] if ":" in rest else rest
    display = name_part.replace("_", " ").replace("-", " ").strip().title()
    entity_type = "process" if prefix == "apqc" else prefix
    return display, entity_type


@router.get("/api/memory/entity-usage")
async def memory_entity_usage(
    request: Request,
    limit: int = 50,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Return xref-driven entity intelligence data.

    All data sourced from entity_xref + episode_vectors/knowledge_vectors.
    Works in both table mode and file mode — no entity_registry dependency.
    Powers the Entity Intelligence tab in the Memory dashboard.
    """
    principal, tenant_id, agent_id, user_id = _scope(
        request,
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        resource_type="memory",
        resource_id="entity-usage",
    )
    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        indexer = agent.memory.knowledge_indexer
        _ph = indexer.placeholder
        _gc = _kn_group_concat(indexer, "x.entity", "|")

        safe_limit = max(0, min(limit, 500))

        # All DB reads run inside one scoped connection (backend-agnostic); the raw
        # rows are processed into the response shape afterwards (pure Python).
        with indexer.connect() as conn:
            cur = conn.cursor()

            cur.execute(f"""
                SELECT
                    x.entity                          AS entity_key,
                    SUM(CASE WHEN x.record_type = 'knowledge' THEN 1 ELSE 0 END) AS knowledge_refs,
                    SUM(CASE WHEN x.record_type = 'episode'   THEN 1 ELSE 0 END) AS episode_refs,
                    COUNT(*)                          AS total_refs
                FROM entity_xref x
                GROUP BY x.entity
                ORDER BY total_refs DESC, x.entity ASC
                LIMIT {_ph}
            """, (safe_limit,))
            usage_rows = cur.fetchall()

            cur.execute("SELECT COUNT(*) FROM entity_xref")
            total_xrefs = cur.fetchone()[0]

            cur.execute("SELECT COUNT(DISTINCT entity) FROM entity_xref")
            unique_entities = cur.fetchone()[0]

            cur.execute(f"""
                SELECT COUNT(DISTINCT x.entity)
                FROM entity_xref x
                JOIN episode_vectors ep ON ep.id = x.record_id AND x.record_type = 'episode'
                WHERE ep.ts >= {_ph}
            """, (_kn_ts_cutoff(1),))
            active_today = cur.fetchone()[0] or 0

            cur.execute(f"""
                SELECT COUNT(DISTINCT x.entity)
                FROM entity_xref x
                JOIN episode_vectors ep ON ep.id = x.record_id AND x.record_type = 'episode'
                WHERE ep.ts >= {_ph}
            """, (_kn_ts_cutoff(7),))
            active_7d = cur.fetchone()[0] or 0

            cur.execute(f"""
                SELECT COUNT(DISTINCT x.entity)
                FROM entity_xref x
                JOIN episode_vectors ep ON ep.id = x.record_id AND x.record_type = 'episode'
                WHERE ep.ts >= {_ph}
            """, (_kn_ts_cutoff(30),))
            active_30d = cur.fetchone()[0] or 0

            cur.execute("SELECT DISTINCT entity FROM entity_xref")
            type_keys = [k for (k,) in cur.fetchall()]

            cur.execute(f"""
                SELECT ep.id, ep.ts, ep.skill, ep.user_input,
                       {_gc} AS entities
                FROM episode_vectors ep
                JOIN entity_xref x ON x.record_id = ep.id AND x.record_type = 'episode'
                GROUP BY ep.id
                ORDER BY ep.ts DESC
                LIMIT 10
            """)
            recent_rows = cur.fetchall()

        usage = []
        for r in usage_rows:
            display_name, entity_type = _derive_entity_display(r[0])
            usage.append({
                "entity_key": r[0],
                "display_name": display_name,
                "node_type": entity_type,
                "knowledge_refs": r[1],
                "episode_refs": r[2],
                "total_refs": r[3],
            })

        top_entities = usage[:5]

        type_counts: dict = {}
        for key in type_keys:
            _, etype = _derive_entity_display(key)
            type_counts[etype] = type_counts.get(etype, 0) + 1
        entity_type_breakdown = [
            {"entity_type": t, "count": c}
            for t, c in sorted(type_counts.items(), key=lambda x: -x[1])
        ]

        recent_activity = []
        for r in recent_rows:
            entity_keys = (r[4] or "").split("|")
            recent_activity.append({
                "episode_id": r[0],
                "ts": r[1],
                "skill": r[2] or "",
                "user_input": (r[3] or "")[:120],
                "entities": [
                    {"key": k, "display": _derive_entity_display(k)[0]}
                    for k in entity_keys if k
                ],
            })

        # Reuse registry_health / xref_coverage keys the frontend already reads
        registry_health = {
            "total_nodes": unique_entities,  # total unique entities seen in xref
            "skills_linked": active_7d,       # active in last 7 days
            "total_aliases": active_30d,      # active in last 30 days
            "depth_levels": active_today,     # active today
        }
        xref_coverage = {
            "total_xrefs": total_xrefs,
            "unique_entities": unique_entities,
            "unlinked_count": 0,
        }

        routing_stats = {}
        entity_store = getattr(indexer, "entity_registry", None)
        if entity_store and hasattr(entity_store, "get_routing_stats"):
            try:
                routing_stats = entity_store.get_routing_stats()
            except Exception as e:
                logger.warning("Routing stats unavailable (non-fatal): %s", e)

        return {
            "usage": usage,
            "top_entities": top_entities,
            "unlinked_count": 0,
            "registry_health": registry_health,
            "xref_coverage": xref_coverage,
            "unlinked_entities": [],
            "process_gaps": {"orphaned_skills": [], "sparse_aliases": [], "dead_activities": []},
            "routing_stats": routing_stats,
            "entity_activity": {
                "active_today": active_today,
                "active_7d": active_7d,
                "active_30d": active_30d,
                "total_unique": unique_entities,
            },
            "entity_type_breakdown": entity_type_breakdown,
            "recent_activity": recent_activity,
        }
    except Exception as e:
        traceback.print_exc()
        return {
            "usage": [], "top_entities": [], "unlinked_count": 0,
            "registry_health": {}, "xref_coverage": {}, "unlinked_entities": [],
            "process_gaps": {}, "routing_stats": {},
            "entity_activity": {}, "entity_type_breakdown": [], "recent_activity": [],
            "error": "An internal error occurred",
        }


@router.post("/api/memory/entity-register")
async def memory_entity_register(
    payload: dict,
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Register an unlinked entity into the ontology registry.

    Payload: {entity_key, display_name, parent_type (customer|vendor|entity), skill_name?, aliases?[]}
    """
    principal, tenant_id, agent_id, user_id = _scope(
        request,
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        action="write",
        resource_type="memory",
        resource_id="entity-register",
    )
    try:
        entity_key = payload.get("entity_key", "").strip()
        display_name = payload.get("display_name", entity_key).strip()
        parent_type = payload.get("parent_type", "entity").strip()
        skill_name = payload.get("skill_name", "").strip() or None
        aliases = payload.get("aliases", [])

        if not entity_key:
            raise HTTPException(status_code=400, detail="entity_key is required")

        if parent_type and parent_type != "entity":
            parent_id = f"entity_type:{parent_type}"
        else:
            parent_id = None

        prefix = parent_type if parent_id else "entity"
        slug = entity_key.lower().strip().replace(" ", "_")[:60]
        node_id = f"{prefix}:{slug}"

        if not aliases:
            aliases = [entity_key.lower(), slug.replace("_", " ")]

        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        indexer = agent.memory.knowledge_indexer
        entity_store = getattr(indexer, "entity_registry", None)
        if not entity_store:
            raise HTTPException(status_code=500, detail="Entity registry not available")

        ok = entity_store.register_entity(
            node_id=node_id,
            node_type="ENTITY",
            display_name=display_name,
            parent_id=parent_id,
            skill_name=skill_name,
            aliases=aliases,
            embed=True,
        )
        return {
            "success": ok,
            "node_id": node_id,
            "display_name": display_name,
            "parent_id": parent_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": "An internal error occurred"}


@router.get("/api/memory/entity-intelligence-recommendations")
async def entity_intelligence_recommendations(
    request: Request,
    min_confidence: float = 0.7,
    min_records: int = 1,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Read knowledge.jsonl and derive policy/metadata recommendations per entity.

    Matches knowledge entity_keys against entity_registry using:
    1. Exact node_id match (after slug normalisation)
    2. Display_name fuzzy match (lowercase, strip, first-word prefix)
    3. Suffix slug match (last word(s) of the name against node_id tail)

    Returns recommendations sorted by most supporting records first.
    """
    import json as _json
    import re
    from collections import defaultdict

    principal, tenant_id, agent_id, user_id = _scope(
        request,
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        resource_type="memory",
        resource_id="entity-intelligence-recommendations",
    )
    def _slugify(text: str) -> str:
        """Convert a free-text name to a registry-style slug."""
        text = text.strip().lower()
        text = re.sub(r"\s*\([^)]*\)", "", text)
        text = re.sub(r"[^a-z0-9]+", "_", text)
        return text.strip("_")

    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        knowledge_jsonl = agent.memory.knowledge_jsonl_path

        if not knowledge_jsonl.exists():
            return {"recommendations": [], "total": 0, "source_records": 0}

        indexer = agent.memory.knowledge_indexer
        with indexer.connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT node_id, display_name, node_type, metadata_json, aliases_json FROM entity_registry"
            )
            registry_rows = cur.fetchall()

        # Build lookup maps
        # 1. exact node_id → row
        reg_by_node_id: dict = {}
        # 2. slugified display_name → row  (e.g. "alpha_office_supplies" → row)
        reg_by_display_slug: dict = {}
        # 3. node_id tail slug → list[row]  (e.g. "alpha_office" from vendor:alpha_office)
        reg_by_tail: dict = defaultdict(list)
        # 4. alias slug → row  (e.g. "msft" → customer:microsoft row)
        reg_by_alias: dict = {}

        for node_id, display_name, node_type, metadata_json, aliases_json in registry_rows:
            row = (node_id, display_name, node_type, metadata_json)
            reg_by_node_id[node_id] = row
            if display_name:
                ds = _slugify(display_name)
                reg_by_display_slug[ds] = row
            # tail = part after colon in node_id
            tail = node_id.split(":")[-1] if ":" in node_id else node_id
            reg_by_tail[tail].append(row)
            # Index every alias (lowercased and slugified) for this node
            if aliases_json:
                try:
                    aliases = _json.loads(aliases_json) if isinstance(aliases_json, str) else aliases_json
                    for alias in (aliases or []):
                        if isinstance(alias, str) and alias.strip():
                            reg_by_alias[alias.strip().lower()] = row
                            reg_by_alias[_slugify(alias)] = row
                except Exception as e:
                    logger.warning("Failed to parse aliases JSON for recommendation index: %s", e)

        def _resolve_to_registry(raw_key: str):
            """Try to resolve a knowledge entity_key to a registry row.

            Returns (resolved_node_id, display_name, node_type, metadata_json) or None.
            """
            # raw_key may look like: "vendor:Alpha Office Supplies" or "vendor:alpha_office"
            parts = raw_key.split(":", 1)
            prefix = parts[0].strip().lower() if len(parts) == 2 else ""
            name_part = parts[1].strip() if len(parts) == 2 else parts[0].strip()
            name_slug = _slugify(name_part)

            # 1. Exact match on node_id after normalising the whole key
            exact_key = f"{prefix}:{name_slug}" if prefix else name_slug
            if exact_key in reg_by_node_id:
                return reg_by_node_id[exact_key]

            # 2. Exact match on full raw_key lowercased
            raw_lower = raw_key.strip().lower()
            if raw_lower in reg_by_node_id:
                return reg_by_node_id[raw_lower]

            # Alias match on the full name (raw and slug), ignoring the prefix constraint (e.g. service:MSFT -> customer:microsoft).
            for alias_key in (name_part.lower(), name_slug):
                if alias_key in reg_by_alias:
                    return reg_by_alias[alias_key]
                if prefix:
                    full_alias_key = f"{prefix}:{alias_key}"
                    if full_alias_key in reg_by_alias:
                        return reg_by_alias[full_alias_key]

            # 4. Display name slug match (full name)
            if name_slug in reg_by_display_slug:
                row = reg_by_display_slug[name_slug]
                if not prefix or row[0].startswith(prefix + ":"):
                    return row

            # 5. Tail slug match: take first word(s) of name and match against node_id tails
            #    e.g. "Alpha Office Supplies" → "alpha_office" matches vendor:alpha_office
            words = name_slug.split("_")
            for n_words in range(len(words), 0, -1):
                candidate_tail = "_".join(words[:n_words])
                if candidate_tail in reg_by_tail:
                    candidates = reg_by_tail[candidate_tail]
                    if prefix:
                        narrowed = [r for r in candidates if r[0].startswith(prefix + ":")]
                        if narrowed:
                            return narrowed[0]
                    if len(candidates) == 1:
                        return candidates[0]

            # 6. Prefix-tolerant alias scan: check if any alias *starts with* the name_slug
            #    Handles truncated names like "TechCor" matching alias "techcorp"
            if len(name_slug) >= 5:
                for alias_k, row in reg_by_alias.items():
                    if alias_k.startswith(name_slug) or name_slug.startswith(alias_k):
                        if not prefix or row[0].startswith(prefix + ":"):
                            return row

            return None

        ACTIONABLE_TYPES = {"rule", "exception", "workaround"}

        def _read_knowledge_records():
            records = []
            seen_ids = set()
            with open(knowledge_jsonl, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = _json.loads(line)
                    except Exception as e:
                        logger.warning("Skipping malformed JSONL line in knowledge store: %s", e)
                        continue
                    rid = rec.get("id", "")
                    if rid in seen_ids:
                        continue
                    seen_ids.add(rid)
                    if rec.get("status") == "archived":
                        continue
                    if rec.get("type") not in ACTIONABLE_TYPES:
                        continue
                    if rec.get("confidence", 1.0) < min_confidence:
                        continue
                    if not rec.get("summary", "").strip():
                        continue
                    records.append(rec)
            return records

        try:
            records = await asyncio.to_thread(_read_knowledge_records)
        except Exception as e:
            traceback.print_exc()
            return {"recommendations": [], "total": 0, "source_records": 0, "error": "An internal error occurred"}

        entity_groups: dict = defaultdict(lambda: {
            "summaries": [],
            "knowledge_ids": [],
            "confidences": [],
            "types": [],
            "registry_row": None,   # set on first successful resolve
            "raw_keys": set(),      # original keys from knowledge.jsonl
        })

        for rec in records:
            summary = rec.get("summary", "").strip()
            rec_id = rec.get("id", "")
            confidence = rec.get("confidence", 1.0)
            rec_type = rec.get("type", "rule")

            raw_keys = rec.get("entity_keys", [])
            applies_to = rec.get("applies_to", {}) or {}
            applies_entity = applies_to.get("entity_id", "")
            applies_type = applies_to.get("entity_type", "")

            candidates: list[str] = []
            for k in raw_keys:
                if isinstance(k, str) and k.strip():
                    candidates.append(k.strip())
            if applies_entity:
                prefix = applies_type.strip().lower() if applies_type else ""
                candidates.append(f"{prefix}:{applies_entity.strip()}" if prefix else applies_entity.strip())

            if not candidates:
                continue  # Skip records with no entity context

            for raw_key in candidates:
                resolved = _resolve_to_registry(raw_key)
                if resolved:
                    group_key = resolved[0]  # canonical node_id
                    grp = entity_groups[group_key]
                    grp["registry_row"] = resolved
                else:
                    # Keep unresolved under a normalised key, no registry data
                    group_key = raw_key.strip().lower()
                    grp = entity_groups[group_key]

                grp["raw_keys"].add(raw_key)
                if summary not in grp["summaries"]:
                    grp["summaries"].append(summary)
                if rec_id not in grp["knowledge_ids"]:
                    grp["knowledge_ids"].append(rec_id)
                    grp["confidences"].append(confidence)
                    grp["types"].append(rec_type)

        recommendations = []
        for group_key, grp in entity_groups.items():
            if len(grp["knowledge_ids"]) < min_records:
                continue
            if group_key == "_general":
                continue

            row = grp["registry_row"]
            if row:
                node_id, display_name, node_type, metadata_json = row
                try:
                    current_metadata = _json.loads(metadata_json) if metadata_json else {}
                except Exception as e:
                    logger.warning("Failed to parse metadata JSON for recommendation node %s: %s", node_id, e)
                    current_metadata = {}
                registry_matched = True
            else:
                node_id = group_key
                display_name = group_key
                node_type = "unlinked"
                current_metadata = {}
                registry_matched = False

            avg_confidence = (
                sum(grp["confidences"]) / len(grp["confidences"])
                if grp["confidences"] else 0.0
            )

            recommendations.append({
                "entity_key": node_id,
                "display_name": display_name,
                "node_type": node_type,
                "current_metadata": current_metadata,
                "suggested_rules": grp["summaries"],
                "source_knowledge_ids": grp["knowledge_ids"],
                "record_count": len(grp["knowledge_ids"]),
                "avg_confidence": round(avg_confidence, 3),
                "types": list(set(grp["types"])),
                "registry_matched": registry_matched,
                "raw_knowledge_keys": sorted(grp["raw_keys"]),
            })

        # Sort: registry-matched first, then by record count desc
        recommendations.sort(key=lambda r: (-int(r["registry_matched"]), -r["record_count"]))

        return {
            "recommendations": recommendations,
            "total": len(recommendations),
            "source_records": len(records),
            "registry_matched_count": sum(1 for r in recommendations if r["registry_matched"]),
        }

    except Exception as e:
        traceback.print_exc()
        return {"recommendations": [], "total": 0, "source_records": 0, "error": "An internal error occurred"}


@router.get("/api/memory/entity-graph")
async def memory_entity_graph(
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Return D3-compatible nodes + links for the entity network graph.

    Nodes: entity_registry nodes + top xref-only entities
    Links: parent-child hierarchy + entity co-occurrence (shared records)
    """
    import json as _json
    from collections import defaultdict

    principal, tenant_id, agent_id, user_id = _scope(
        request,
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        resource_type="memory",
        resource_id="entity-graph",
    )
    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        indexer = agent.memory.knowledge_indexer
        with indexer.connect() as conn:
            cur = conn.cursor()

            cur.execute("""
                SELECT er.node_id, er.display_name, er.node_type, er.parent_id,
                       er.skill_name, er.aliases_json,
                       COALESCE(kl.cnt, 0), COALESCE(el.cnt, 0)
                FROM entity_registry er
                LEFT JOIN (SELECT entity, COUNT(*) AS cnt FROM entity_xref
                           WHERE record_type='knowledge' GROUP BY entity) kl
                    ON kl.entity = er.node_id OR kl.entity = er.skill_name
                LEFT JOIN (SELECT entity, COUNT(*) AS cnt FROM entity_xref
                           WHERE record_type='episode' GROUP BY entity) el
                    ON el.entity = er.node_id OR el.entity = er.skill_name
                ORDER BY er.node_type, er.display_name
            """)
            registry_rows = cur.fetchall()

            cur.execute("""
                SELECT x.entity,
                       SUM(CASE WHEN x.record_type='knowledge' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN x.record_type='episode' THEN 1 ELSE 0 END),
                       COUNT(*)
                FROM entity_xref x
                LEFT JOIN entity_registry er
                    ON er.node_id = x.entity OR er.skill_name = x.entity
                WHERE er.node_id IS NULL AND er.skill_name IS NULL
                GROUP BY x.entity
                ORDER BY COUNT(*) DESC
                LIMIT 60
            """)
            xref_rows = cur.fetchall()

            cur.execute("""
                SELECT x1.entity AS e1, x2.entity AS e2, COUNT(DISTINCT x1.record_id) AS shared
                FROM entity_xref x1
                JOIN entity_xref x2 ON x1.record_id = x2.record_id
                                    AND x1.record_type = x2.record_type
                                    AND x1.entity < x2.entity
                GROUP BY x1.entity, x2.entity
                HAVING COUNT(DISTINCT x1.record_id) >= 1
                ORDER BY shared DESC
                LIMIT 200
            """)
            cooccur_rows = cur.fetchall()

        nodes = []
        node_ids = set()
        for r in registry_rows:
            aliases = _json.loads(r[5]) if r[5] else []
            nodes.append({
                "id": r[0], "name": r[1], "type": r[2],
                "parent_id": r[3], "skill_name": r[4],
                "aliases": aliases,
                "knowledge_count": r[6], "episode_count": r[7],
                "total": r[6] + r[7],
                "source": "registry",
            })
            node_ids.add(r[0])

        for r in xref_rows:
            nodes.append({
                "id": r[0], "name": r[0], "type": "xref_entity",
                "parent_id": None, "skill_name": None,
                "aliases": [],
                "knowledge_count": r[1], "episode_count": r[2],
                "total": r[3],
                "source": "xref_only",
            })
            node_ids.add(r[0])

        links = []
        link_set = set()

        for n in nodes:
            if n["parent_id"] and n["parent_id"] in node_ids:
                key = (n["parent_id"], n["id"])
                if key not in link_set:
                    links.append({
                        "source": n["parent_id"], "target": n["id"],
                        "type": "hierarchy", "weight": 1,
                    })
                    link_set.add(key)

        for r in cooccur_rows:
            if r[0] in node_ids and r[1] in node_ids:
                key = (r[0], r[1])
                if key not in link_set:
                    links.append({
                        "source": r[0], "target": r[1],
                        "type": "co_occurrence", "weight": r[2],
                    })
                    link_set.add(key)

        registry_count = sum(1 for n in nodes if n["source"] == "registry")
        xref_count = sum(1 for n in nodes if n["source"] == "xref_only")

        return {
            "nodes": nodes,
            "links": links,
            "stats": {
                "total_nodes": len(nodes),
                "registry_nodes": registry_count,
                "xref_only_nodes": xref_count,
                "total_links": len(links),
                "hierarchy_links": sum(1 for l in links if l["type"] == "hierarchy"),
                "cooccurrence_links": sum(1 for l in links if l["type"] == "co_occurrence"),
            },
        }
    except Exception as e:
        traceback.print_exc()
        return {"nodes": [], "links": [], "stats": {}, "error": "An internal error occurred"}


@router.get("/api/memory/simulate-routing")
async def simulate_routing(
    request: Request,
    q: str = "",
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Simulate dual-signal routing for a query without executing it.

    Returns the full entity + process signal breakdown so the UI
    can visualise how the router would behave.
    """
    principal, tenant_id, agent_id, user_id = _scope(
        request,
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        resource_type="memory",
        resource_id="simulate-routing",
    )
    if not q.strip():
        return {"error": "Query parameter 'q' is required", "signals": {}}

    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        indexer = getattr(agent.memory, "knowledge_indexer", None)
        entity_store = getattr(indexer, "entity_registry", None) if indexer else None

        if not entity_store:
            return {"error": "Entity registry not available", "signals": {}}

        q_emb = indexer._safe_get_embedding(q)
        ctx = entity_store.collect_context(
            query_embedding=q_emb, query_text=q
        ) if q_emb else entity_store.collect_context(query_text=q)

        entity_hint = ctx.get("skill_hint")
        entity_confidence = ctx.get("skill_confidence", 0.0)
        process_hint = ctx.get("process_hint")
        process_matches = ctx.get("process_matches", [])
        signals_agree = ctx.get("signals_agree")
        resolved_entities = ctx.get("resolved_entities", [])
        tree_context = ctx.get("tree_context", [])

        router_result = agent.router.match(
            q,
            current_skill=agent.current_skill,
            return_details=True,
            entity_hint=entity_hint,
            entity_confidence=entity_confidence,
            process_hint=process_hint,
            process_matches=process_matches,
            signals_agree=signals_agree,
        )

        return {
            "query": q,
            "routed_skill": router_result.get("skill") if isinstance(router_result, dict) else router_result,
            "routing_method": router_result.get("method", "llm") if isinstance(router_result, dict) else "llm",
            "routing_confidence": router_result.get("confidence", 0.0) if isinstance(router_result, dict) else 0.0,
            "entity_signal": {
                "hint": entity_hint,
                "confidence": entity_confidence,
                "resolved_entities": resolved_entities,
                "tree_context": tree_context,
            },
            "process_signal": {
                "hint": process_hint,
                "matches": process_matches,
            },
            "signals_agree": signals_agree,
            "alternatives": router_result.get("alternatives", []) if isinstance(router_result, dict) else [],
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": "An internal error occurred", "signals": {}}


@router.get("/api/memory/entity/{node_id:path}")
async def memory_entity_detail(
    node_id: str,
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """Return full entity detail: identity, hierarchy, aliases, linked knowledge & episodes.

    Works for BOTH entity_registry nodes (ontology) and raw entity_xref keys.
    - If node_id exists in entity_registry → full identity + ancestor breadcrumb
    - Always queries entity_xref for linked knowledge & episode records
    """
    import json as _json

    principal, tenant_id, agent_id, user_id = _scope(
        request,
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        resource_type="memory",
        resource_id=node_id,
    )
    try:
        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
        indexer = agent.memory.knowledge_indexer
        _ph = indexer.placeholder
        with indexer.connect() as conn:
            cur = conn.cursor()

            identity = None
            aliases = []
            metadata = {}
            cur.execute(f"""
                SELECT node_id, node_type, display_name, parent_id,
                       skill_name, metadata_json, aliases_json, updated_at
                FROM entity_registry WHERE node_id = {_ph}
            """, (node_id,))
            row = cur.fetchone()
            if row:
                aliases = _json.loads(row[6]) if row[6] else []
                metadata = _json.loads(row[5]) if row[5] else {}
                identity = {
                    "node_id": row[0],
                    "node_type": row[1],
                    "display_name": row[2],
                    "parent_id": row[3],
                    "skill_name": row[4],
                    "metadata": metadata,
                    "aliases": aliases,
                    "updated_at": row[7],
                }

            breadcrumb = []
            if identity and identity["parent_id"]:
                cur.execute(f"""
                    WITH RECURSIVE ancestors AS (
                        SELECT node_id, display_name, node_type, parent_id, 0 AS depth
                        FROM entity_registry WHERE node_id = {_ph}
                        UNION ALL
                        SELECT er.node_id, er.display_name, er.node_type, er.parent_id, a.depth + 1
                        FROM entity_registry er
                        JOIN ancestors a ON er.node_id = a.parent_id
                    )
                    SELECT node_id, display_name, node_type FROM ancestors
                    ORDER BY depth DESC
                """, (node_id,))
                breadcrumb = [
                    {"node_id": r[0], "display_name": r[1], "node_type": r[2]}
                    for r in cur.fetchall()
                ]

            children = []
            if identity:
                cur.execute(f"""
                    SELECT node_id, display_name, node_type, skill_name
                    FROM entity_registry WHERE parent_id = {_ph}
                    ORDER BY node_type, display_name
                """, (node_id,))
                children = [
                    {"node_id": r[0], "display_name": r[1], "node_type": r[2], "skill_name": r[3]}
                    for r in cur.fetchall()
                ]

            lookup_keys = {node_id.lower().strip()}
            if identity:
                lookup_keys.add(identity["display_name"].lower().strip())
                if identity.get("skill_name"):
                    lookup_keys.add(identity["skill_name"].lower().strip())
                for a in aliases:
                    lookup_keys.add(a.lower().strip())

            placeholders = ",".join([_ph] * len(lookup_keys))
            cur.execute(f"""
                SELECT DISTINCT kv.id, kv.summary, kv.knowledge_type, kv.skill,
                       kv.status, kv.ts, kv.entities_json, kv.raw_json
                FROM entity_xref ex
                JOIN knowledge_vectors kv ON ex.record_id = kv.id
                WHERE ex.entity IN ({placeholders})
                  AND ex.record_type = 'knowledge'
                ORDER BY kv.ts DESC
                LIMIT 50
            """, list(lookup_keys))

            linked_knowledge = []
            for r in cur.fetchall():
                raw = _json.loads(r[7]) if r[7] else {}
                linked_knowledge.append({
                    "id": r[0], "summary": r[1], "knowledge_type": r[2],
                    "skill": r[3] or "", "status": r[4], "ts": r[5],
                    "entities": _json.loads(r[6]) if r[6] else [],
                    "lifecycle": raw.get("lifecycle"),
                })

            cur.execute(f"""
                SELECT DISTINCT ev.id, ev.user_input, ev.summary, ev.skill,
                       ev.ts, ev.session_id, ev.entities, ev.reasoning
                FROM entity_xref ex
                JOIN episode_vectors ev ON ex.record_id = ev.id
                WHERE ex.entity IN ({placeholders})
                  AND ex.record_type = 'episode'
                ORDER BY ev.ts DESC
                LIMIT 50
            """, list(lookup_keys))

            linked_episodes = []
            for r in cur.fetchall():
                linked_episodes.append({
                    "id": r[0], "user_input": r[1] or "", "summary": r[2] or "",
                    "skill": r[3] or "", "ts": r[4], "session_id": r[5] or "",
                    "entities": _json.loads(r[6]) if r[6] else [],
                    "reasoning": r[7] or "",
                })

            cur.execute(f"""
                SELECT substr(ev.ts, 1, 7) AS month, COUNT(DISTINCT ev.id) AS cnt
                FROM entity_xref ex
                JOIN episode_vectors ev ON ex.record_id = ev.id
                WHERE ex.entity IN ({placeholders})
                  AND ex.record_type = 'episode'
                GROUP BY month
                ORDER BY month ASC
            """, list(lookup_keys))
            temporal_activity = [
                {"month": r[0], "count": r[1]}
                for r in cur.fetchall()
            ]

        derived_display = None
        if not identity:
            parts = node_id.split(":", 1)
            entity_type = parts[0] if len(parts) > 1 else "unknown"
            name_raw = parts[1] if len(parts) > 1 else node_id
            # For multi-level keys like apqc:l3:invoice_proc take last segment
            name_raw = name_raw.split(":")[-1] if ":" in name_raw else name_raw
            name_display = name_raw.replace("_", " ").replace("-", " ").strip().title()
            derived_display = {
                "display_name": name_display,
                "entity_type": "process" if entity_type == "apqc" else entity_type,
            }

        return {
            "node_id": node_id,
            "identity": identity,
            "derived_display": derived_display,
            "breadcrumb": breadcrumb,
            "children": children,
            "linked_knowledge": linked_knowledge,
            "linked_episodes": linked_episodes,
            "knowledge_count": len(linked_knowledge),
            "episode_count": len(linked_episodes),
            "temporal_activity": temporal_activity,
        }
    except Exception as e:
        traceback.print_exc()
        logger.exception("memory_entity_detail failed")
        raise HTTPException(status_code=500, detail="An internal error occurred")


@router.get("/api/knowledge/context-graph")
async def context_graph(
    request: Request,
    tenant_id: str = "company",
):
    """
    Build a D3-compatible { nodes, links, stats } graph by parsing the enterprise
    markdown context files (taxonomy, skills, entities, pillar files).

    Auto-discovers new files on every call (30-second mtime cache).
    """
    _principal, tenant_id, _agent_id, _user_id = _scope(
        request,
        tenant_id=tenant_id,
        resource_id="context-graph",
    )
    try:
        from context_graph_builder import build_context_graph

        root = Path(DATA_ROOT)
        if not root.is_absolute():
            root = (SERVER_DIR / root).resolve()

        return build_context_graph(str(root), tenant_id)
    except Exception as e:
        traceback.print_exc()
        logger.exception("context_graph failed")
        raise HTTPException(status_code=500, detail="An internal error occurred")


@router.get("/api/knowledge/context-graph/simulate")
async def context_graph_simulate(
    request: Request,
    q: str = "",
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
):
    """
    Simulate routing using the same LLM router the agent uses, then map the
    result onto the context graph topology — highlighting the full path from
    the matched skill / entity / process back up to the L1 domain node.

    Returns:
      routed_skill, entity_signal, process_signal  — same as /api/memory/simulate-routing
      matched_ids   — graph node IDs directly identified by the router
      path_ids      — ancestor nodes walking up hierarchy to L1 (the "trail")
      neighbor_ids  — other 1-hop connected nodes
    """
    principal, tenant_id, agent_id, user_id = _scope(
        request,
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        resource_id="context-graph-simulate",
    )
    if not q.strip():
        return {"error": "Query required"}

    try:
        from context_graph_builder import build_context_graph

        user_role = principal.roles[0] if principal.roles else "user"
        agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)

        routed_skill = None
        routing_method = "llm"
        routing_confidence = 0.0

        try:
            rr = agent.router.match(q, current_skill=agent.current_skill, return_details=True)
            routed_skill = rr.get("skill") if isinstance(rr, dict) else rr
            routing_method = rr.get("method", "llm") if isinstance(rr, dict) else "llm"
            routing_confidence = rr.get("confidence", 0.0) if isinstance(rr, dict) else 0.0
        except Exception:
            pass

        root = Path(DATA_ROOT)
        if not root.is_absolute():
            root = (SERVER_DIR / root).resolve()
        graph_data = build_context_graph(str(root), tenant_id)

        graph_nodes = graph_data.get("nodes", [])
        graph_links = graph_data.get("links", [])
        node_ids_set = {n["id"] for n in graph_nodes}
        node_lookup = {n["id"]: n for n in graph_nodes}

        matched_ids: set = set()

        # Skill node from LLM router
        if routed_skill:
            sid = f"skill_{routed_skill}"
            if sid in node_ids_set:
                matched_ids.add(sid)

        # Entity nodes: text scan of query against context graph labels
        # (entities live in contexts/entities/*.md — no DB needed)
        q_lower = q.lower()
        for n in graph_nodes:
            if n["node_type"] == "entity":
                for word in re.split(r'\W+', n["label"].lower()):
                    if len(word) >= 4 and word in q_lower:
                        matched_ids.add(n["id"])
                        break

        # Taxonomy nodes: match query tokens against process/subprocess labels
        q_tokens = set(w for w in re.split(r'\W+', q_lower) if len(w) >= 4)
        for n in graph_nodes:
            if n["node_type"] in ("process", "subprocess"):
                label_words = set(re.split(r'\W+', n["label"].lower()))
                if q_tokens & label_words:
                    matched_ids.add(n["id"])

        parent_of: dict = {}
        skill_covers: dict = {}

        for link in graph_links:
            src = link["source"] if isinstance(link["source"], str) else link["source"].get("id", "")
            tgt = link["target"] if isinstance(link["target"], str) else link["target"].get("id", "")
            ltype = link.get("type", "")
            if ltype == "hierarchy":
                parent_of[tgt] = src
            elif ltype == "skill_covers":
                skill_covers.setdefault(src, []).append(tgt)

        path_ids: set = set()

        def _walk_up(nid: str):
            cur = nid
            while cur in parent_of:
                cur = parent_of[cur]
                path_ids.add(cur)

        def _expand_skill(skill_id: str):
            for pid in skill_covers.get(skill_id, []):
                path_ids.add(pid)
                _walk_up(pid)

        for nid in matched_ids:
            nt = node_lookup.get(nid, {}).get("node_type", "")
            _walk_up(nid)
            if nt == "skill":
                _expand_skill(nid)
            if nt == "entity":
                for link in graph_links:
                    s = link["source"] if isinstance(link["source"], str) else link["source"].get("id","")
                    t = link["target"] if isinstance(link["target"], str) else link["target"].get("id","")
                    if s == nid and link.get("type") == "entity_via":
                        path_ids.add(t)
                        _expand_skill(t)
                        _walk_up(t)

        path_ids -= matched_ids

        neighbor_ids: set = set()
        all_lit = matched_ids | path_ids
        for link in graph_links:
            src = link["source"] if isinstance(link["source"], str) else link["source"].get("id","")
            tgt = link["target"] if isinstance(link["target"], str) else link["target"].get("id","")
            if src in all_lit and tgt not in all_lit:
                neighbor_ids.add(tgt)
            elif tgt in all_lit and src not in all_lit:
                neighbor_ids.add(src)

        return {
            "routed_skill": routed_skill,
            "routing_method": routing_method,
            "routing_confidence": routing_confidence,
            "matched_ids": list(matched_ids),
            "path_ids": list(path_ids),
            "neighbor_ids": list(neighbor_ids),
            "query": q,
        }

    except Exception as e:
        traceback.print_exc()
        logger.exception("_expand_skill failed")
        raise HTTPException(status_code=500, detail="An internal error occurred")
