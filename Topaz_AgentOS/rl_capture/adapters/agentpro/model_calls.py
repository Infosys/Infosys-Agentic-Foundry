"""AgentPro model-call pipeline capture adapter."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rl_capture.core.redaction import redact_value
from rl_capture.core.schema import (
    CaptureFidelity,
    CaptureMeta,
    Message,
    ModelCall,
    PolicyRef,
    RedactionMeta,
    RewardChannel,
    RewardEvent,
    Role,
    TargetRef,
    TargetType,
    ToolCallSpec,
)
from rl_capture.store.sqlite_store import get_rl_store


def rl_capture_enabled() -> bool:
    return os.getenv("RL_CAPTURE", "false").strip().lower() in {"1", "true", "yes", "on"}


def record_model_call_event(
    *,
    request: Any,
    response: Any,
    status: str = "success",
    error: str = "",
) -> None:
    """Best-effort capture of one provider call from PolicyChatModel."""
    if not rl_capture_enabled():
        return
    session_ctx = dict(getattr(request, "session_ctx", {}) or {})
    tenant_id = str(session_ctx.get("tenant_id") or "company")
    agent_id = str(session_ctx.get("agent_id") or "")
    data_root = _data_root_from_ctx(session_ctx)
    trajectory_id = str(session_ctx.get("trace_id") or session_ctx.get("run_id") or uuid.uuid4().hex)
    now = datetime.now(timezone.utc).isoformat()
    model_call_id = f"{trajectory_id}:model:{uuid.uuid4().hex[:12]}"
    policy = PolicyRef(
        provider=str(_provider_from_response(response) or session_ctx.get("provider") or ""),
        model=str(getattr(response, "model_name", "") or getattr(request, "model_name", "") or ""),
        decoding_id=str(_response_id(response) or "") or None,
    )
    input_messages = _messages_from_any(getattr(request, "messages", None), role_hint=Role.USER)
    output_messages = _messages_from_any(getattr(response, "message", None), role_hint=Role.ASSISTANT)
    # Attach tool calls the provider pre-extracted on response.tool_calls; .content is usually empty on tool-call turns.
    tool_specs = _tool_call_specs_from_response(response)
    if tool_specs:
        if output_messages:
            output_messages[-1].tool_calls = tool_specs
        else:
            output_messages = [Message(role=Role.ASSISTANT, content=None, tool_calls=tool_specs)]
    available_tools = _available_tools_from_request(request)
    usage = dict(getattr(response, "usage", {}) or {})
    metadata = dict(getattr(response, "metadata", {}) or {})
    redaction = _combine_redactions([m.redaction for m in input_messages + output_messages])
    model_call = ModelCall(
        id=model_call_id,
        policy=policy,
        input_messages=input_messages,
        output_messages=output_messages,
        fidelity=CaptureFidelity.REASONING_PARTIAL
        if metadata.get("native_reasoning") or metadata.get("model_call_pipeline")
        else CaptureFidelity.TEXT_ONLY,
        reasoning_ref=str(_response_id(response) or "") or None,
        prompt_tokens=_usage_int(usage, "input_tokens", "prompt_tokens"),
        completion_tokens=_usage_int(usage, "output_tokens", "completion_tokens"),
        latency_ms=None,
        redaction=redaction,
        metadata={
            "status": status,
            "error": error,
            "model_role": getattr(request, "model_role", ""),
            "short_circuited": bool(getattr(response, "short_circuited", False)),
            "available_tools": available_tools,
            "pipeline_audit": metadata.get("model_call_pipeline", {}),
            "session_ctx": {
                key: session_ctx.get(key)
                for key in (
                    "session_id",
                    "skill_name",
                    "user_id",
                    "execution_mode",
                    "entrypoint",
                    "queue_item_id",
                    "workstream_name",
                    "mission_item_id",
                )
            },
        },
    )
    store = get_rl_store(data_root=data_root, tenant_id=tenant_id, db_path=os.getenv("RL_DB_PATH", "").strip() or None)
    store.record_model_call(trajectory_id, model_call)
    _record_policy_rewards(
        store=store,
        trajectory_id=trajectory_id,
        model_call_id=model_call_id,
        capture=CaptureMeta(
            adapter_version="agentpro:0.1.0",
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_event_id=model_call_id,
            source_trace_id=trajectory_id,
            capture_time=now,
        ),
        audit=((metadata.get("model_call_pipeline") or {}).get("audit") or []),
        status=status,
        error=error,
    )


def _record_policy_rewards(*, store, trajectory_id: str, model_call_id: str, capture: CaptureMeta, audit: list[dict], status: str, error: str) -> None:
    for event in audit:
        raw_label = "block" if event.get("blocked") else "allow"
        if event.get("mutation_summary") == "response_content":
            raw_label = "redact"
        if event.get("short_circuited"):
            raw_label = "short_circuit"
        store.record_reward_event(
            RewardEvent(
                id=f"reward_{uuid.uuid4().hex}",
                channel=RewardChannel.MODEL_CALL_POLICY,
                target=TargetRef(trajectory_id, TargetType.MODEL_CALL, model_call_id),
                raw_label=raw_label,
                judge_id=str(event.get("hook_id") or "model_call_pipeline"),
                created_at=capture.capture_time,
                capture=capture,
                metadata={"audit": event, "status": status, "error": error},
            )
        )


def _data_root_from_ctx(session_ctx: dict[str, Any]) -> Path:
    agent_root = Path(str(session_ctx.get("agent_root") or ".")).resolve()
    for parent in [agent_root, *agent_root.parents]:
        candidate = parent / "enterprise_root"
        if candidate.exists():
            return candidate
    return agent_root


def _messages_from_any(value: Any, *, role_hint: Role) -> list[Message]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_message_from_any(item, role_hint=role_hint) for item in value]
    return [_message_from_any(value, role_hint=role_hint)]


def _message_from_any(value: Any, *, role_hint: Role) -> Message:
    # Store raw text, not repr(): handle LangChain messages, tuples and role/content dicts; repr() only for unknown types.
    role_str = ""
    content: Any = None
    if isinstance(value, (tuple, list)) and len(value) == 2 and all(isinstance(part, str) for part in value):
        role_str, content = value[0], value[1]
    elif isinstance(value, dict):
        role_str = str(value.get("type") or value.get("role") or "")
        content = value.get("content")
    else:
        role_str = str(getattr(value, "type", "") or getattr(value, "role", "") or "")
        content = getattr(value, "content", None)
    role = Role(role_str) if role_str in {r.value for r in Role} else role_hint
    if content is None:
        content = value if isinstance(value, str) else repr(value)
    result = redact_value(content)
    return Message(
        role=role,
        content=str(result.value),
        redaction=RedactionMeta(
            redacted=result.redacted,
            redacted_fields=result.redacted_fields,
            policy_version=result.policy_version if result.redacted else None,
        ),
    )


def _tool_call_specs_from_response(response: Any) -> list[ToolCallSpec]:
    """Extract the structured tool calls the model decided into ToolCallSpecs.

    Reads ``response.tool_calls`` (already pre-extracted by the model-call
    pipeline) and falls back to the raw assistant message's ``.tool_calls``.
    Each provider tool call is a dict/obj shaped ``{id, name, args}``. Arguments
    are redacted (they can carry user PII) before storage.
    """
    try:
        raw = getattr(response, "tool_calls", None)
        if not raw:
            message = getattr(response, "message", None)
            raw = getattr(message, "tool_calls", None)
        specs: list[ToolCallSpec] = []
        for item in raw or []:
            if isinstance(item, dict):
                call_id = item.get("id") or item.get("call_id") or ""
                name = item.get("name") or ""
                args = item.get("args")
                if args is None:
                    args = item.get("arguments")
            else:
                call_id = getattr(item, "id", "") or getattr(item, "call_id", "") or ""
                name = getattr(item, "name", "") or ""
                args = getattr(item, "args", None)
                if args is None:
                    args = getattr(item, "arguments", None)
            if not name:
                continue
            if not isinstance(args, dict):
                args = {"input": args} if args is not None else {}
            redacted = redact_value(args).value
            if not isinstance(redacted, dict):
                redacted = {"input": redacted}
            specs.append(ToolCallSpec(call_id=str(call_id), name=str(name), arguments=redacted))
        return specs
    except Exception:
        return []


def _available_tools_from_request(request: Any) -> list[dict]:
    """Serialize the tools bound on the request into OpenAI-style function schemas.

    This is the tool *menu* the model chose from; exporters put it in the row's
    ``tools`` field so a fine-tune learns which call to make given the options.
    """
    try:
        tools = getattr(request, "tools", None) or []
        schemas: list[dict] = []
        for tool in tools:
            schema = _tool_to_openai_schema(tool)
            if schema:
                # Redact: tool descriptions/defaults/enums can carry secrets.
                schemas.append(redact_value(schema).value)
        return schemas
    except Exception:
        return []


def _tool_to_openai_schema(tool: Any) -> dict | None:
    if isinstance(tool, dict):
        return tool
    try:
        from langchain_core.utils.function_calling import convert_to_openai_tool

        return convert_to_openai_tool(tool)
    except Exception:
        pass
    name = getattr(tool, "name", None)
    if not name:
        return None
    function: dict[str, Any] = {
        "name": str(name),
        "description": str(getattr(tool, "description", "") or ""),
    }
    args_schema = getattr(tool, "args", None)
    if isinstance(args_schema, dict):
        function["parameters"] = {"type": "object", "properties": args_schema}
    return {"type": "function", "function": function}


def _combine_redactions(items: list[RedactionMeta]) -> RedactionMeta:
    fields: list[str] = []
    for item in items:
        fields.extend(item.redacted_fields)
    return RedactionMeta(redacted=bool(fields), redacted_fields=fields, policy_version="rl_redaction_v1" if fields else None)


def _usage_int(usage: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = usage.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


def _provider_from_response(response: Any) -> str:
    metadata = dict(getattr(response, "metadata", {}) or {})
    native = metadata.get("native_reasoning") if isinstance(metadata.get("native_reasoning"), dict) else {}
    return str(native.get("provider") or "")


def _response_id(response: Any) -> str:
    message = getattr(response, "message", None)
    metadata = getattr(message, "response_metadata", None)
    if isinstance(metadata, dict):
        return str(metadata.get("response_id") or metadata.get("id") or "")
    return ""
