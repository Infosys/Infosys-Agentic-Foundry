"""Model-call policy pipeline.

This module adds a narrow policy boundary around provider calls without
changing the broader hook architecture. It is intentionally disabled by
default via ``MODEL_CALL_PIPELINE_ENABLED=false``.
"""

from __future__ import annotations

import contextlib
import contextvars
import copy
import hashlib
import inspect
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

try:  # pragma: no cover - dependency exists in normal runtime
    from langchain_core.messages import AIMessage
except Exception:  # pragma: no cover
    AIMessage = None  # type: ignore

try:  # pragma: no cover - dependency exists in normal runtime
    from langchain_core.runnables import Runnable
except Exception:  # pragma: no cover
    class Runnable:  # type: ignore
        pass

from .hook_runner import (
    HookResult,
    HOOK_AFTER_MODEL_CALL,
    HOOK_AROUND_MODEL_CALL,
    HOOK_BEFORE_MODEL_CALL,
)


_MODEL_CALL_CONTEXT: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "iaf_model_call_context",
    default=None,
)


def model_call_pipeline_enabled() -> bool:
    """Return whether the model-call pipeline is enabled for this process."""
    return os.environ.get("MODEL_CALL_PIPELINE_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@contextlib.contextmanager
def model_call_context(ctx: dict[str, Any]) -> Iterator[None]:
    """Set request-local context for nested model.invoke() calls."""
    token = _MODEL_CALL_CONTEXT.set(dict(ctx or {}))
    try:
        yield
    finally:
        _MODEL_CALL_CONTEXT.reset(token)


def current_model_call_context() -> dict[str, Any]:
    return dict(_MODEL_CALL_CONTEXT.get() or {})


@dataclass
class ModelCallAuditEvent:
    hook_id: str
    event: str
    priority: int = 100
    input_hash: str = ""
    output_hash: str = ""
    mutation_summary: str = ""
    blocked: bool = False
    short_circuited: bool = False
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelCallRequest:
    messages: Any
    model_role: str = "primary"
    model_name: str = ""
    tools: list[Any] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    session_ctx: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    locks: set[str] = field(default_factory=set)
    audit: list[ModelCallAuditEvent] = field(default_factory=list)


@dataclass
class ModelCallResponse:
    message: Any = None
    content: str = ""
    tool_calls: list[Any] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    model_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    short_circuited: bool = False


@dataclass
class ModelCallMutation:
    messages: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    model_override: str = ""
    tools_allow: list[str] = field(default_factory=list)
    tools_deny: list[str] = field(default_factory=list)
    cached_response: Any = None
    response_content: str | None = None
    blocked: bool = False
    reason: str = ""
    on_block: str = "deny"
    approval: dict[str, Any] = field(default_factory=dict)


class ModelCallBlocked(RuntimeError):
    """Raised when a model-call hook blocks a provider call."""

    def __init__(self, reason: str, *, hook_result: HookResult | None = None):
        super().__init__(reason or "Model call blocked by policy hook.")
        self.reason = reason or "Model call blocked by policy hook."
        self.hook_result = hook_result


class ModelCallPipeline:
    """Execute ordered model-call hooks around a provider invocation."""

    def __init__(self, hook_runner: Any):
        self.hook_runner = hook_runner

    def invoke(
        self,
        request: ModelCallRequest,
        provider_call: Callable[[ModelCallRequest], Any],
    ) -> ModelCallResponse:
        try:
            if self.hook_runner is None:
                response = self._response_from_message(provider_call(request), request)
                self._capture_rl_model_call(request, response)
                return response

            self._run_before_hooks(request)
            around_call = self._compose_around_hooks(request, provider_call)
            response = around_call()
            if not isinstance(response, ModelCallResponse):
                response = self._response_from_message(response, request)
            if not response.short_circuited:
                self._run_after_hooks(request, response)
            self._publish_pipeline_audit(request, response)
            response.message = self._merge_message_metadata(response.message, response.metadata)
            self._capture_rl_model_call(request, response)
            return response
        except ModelCallBlocked as exc:
            blocked_response = ModelCallResponse(
                content="",
                model_name=request.model_name,
                metadata={"blocked": True, "blocked_reason": str(exc), "model_call_pipeline": {"audit": [event.__dict__ for event in request.audit]}},
            )
            self._capture_rl_model_call(request, blocked_response, status="blocked", error=str(exc))
            raise

    def _model_call_hooks(self, event: str, request: ModelCallRequest) -> list[Any]:
        try:
            return list(
                self.hook_runner.iter_model_call_hooks(
                    event,
                    skill_name=str(request.session_ctx.get("skill_name") or ""),
                )
            )
        except Exception:
            return []

    def _run_before_hooks(self, request: ModelCallRequest) -> None:
        for hook in self._model_call_hooks(HOOK_BEFORE_MODEL_CALL, request):
            mutation = self._run_hook(hook, request, None)
            self._apply_request_mutation(request, hook, mutation)

    def _run_after_hooks(self, request: ModelCallRequest, response: ModelCallResponse) -> None:
        for hook in self._model_call_hooks(HOOK_AFTER_MODEL_CALL, request):
            mutation = self._run_hook(hook, request, response)
            self._apply_response_mutation(response, hook, mutation)

    def _compose_around_hooks(
        self,
        request: ModelCallRequest,
        provider_call: Callable[[ModelCallRequest], Any],
    ) -> Callable[[], ModelCallResponse]:
        def leaf() -> ModelCallResponse:
            return self._response_from_message(provider_call(request), request)

        call = leaf
        for hook in reversed(self._model_call_hooks(HOOK_AROUND_MODEL_CALL, request)):
            next_call = call

            def wrapped(hook=hook, next_call=next_call) -> ModelCallResponse:
                start = time.time() * 1000
                ctx = self._hook_ctx(request, HOOK_AROUND_MODEL_CALL, None)
                ctx["next_call"] = next_call
                try:
                    result = self._call_around_handler(hook, ctx, next_call)
                    response = (
                        result
                        if isinstance(result, ModelCallResponse)
                        else self._response_from_message(result, request)
                    )
                    self._append_audit(
                        request,
                        hook=hook,
                        event=HOOK_AROUND_MODEL_CALL,
                        duration_ms=time.time() * 1000 - start,
                        mutation_summary="around_wrapper",
                        short_circuited=response.short_circuited,
                    )
                    return response
                except ModelCallBlocked:
                    raise
                except Exception as exc:
                    if getattr(hook, "fail_policy", "open") == "closed":
                        raise ModelCallBlocked(f"model-call hook error: {exc}") from exc
                    return next_call()

            call = wrapped
        return call

    def _call_around_handler(self, hook: Any, ctx: dict[str, Any], next_call: Callable[[], ModelCallResponse]):
        handler = getattr(hook, "handler", None)
        if handler is None:
            return next_call()
        try:
            params = inspect.signature(handler).parameters
            if len(params) >= 2:
                return handler(ctx, next_call)
        except (TypeError, ValueError):
            pass
        result = handler(ctx)
        return next_call() if result is None else result

    def _run_hook(
        self,
        hook: Any,
        request: ModelCallRequest,
        response: ModelCallResponse | None,
    ) -> ModelCallMutation | ModelCallResponse | None:
        event = getattr(hook, "event", "")
        start = time.time() * 1000
        ctx = self._hook_ctx(request, event, response)
        result = self.hook_runner.run_model_call_hook(hook, ctx)
        mutation = self._normalize_hook_result(result)
        self._append_audit(
            request,
            hook=hook,
            event=event,
            duration_ms=time.time() * 1000 - start,
            mutation_summary=self._mutation_summary(mutation),
            blocked=bool(getattr(mutation, "blocked", False)),
            short_circuited=isinstance(mutation, ModelCallResponse)
            and bool(mutation.short_circuited),
        )
        return mutation

    def _hook_ctx(
        self,
        request: ModelCallRequest,
        event: str,
        response: ModelCallResponse | None,
    ) -> dict[str, Any]:
        return {
            **request.session_ctx,
            "hook_event": event,
            "model_role": request.model_role,
            "model_name": request.model_name,
            "messages": request.messages,
            "message_count": len(request.messages) if isinstance(request.messages, list) else 1,
            "metadata": dict(request.metadata),
            "locks": sorted(request.locks),
            "response": response.message if response else None,
            "response_content": response.content if response else "",
            "short_circuited": bool(response.short_circuited) if response else False,
        }

    def _apply_request_mutation(
        self,
        request: ModelCallRequest,
        hook: Any,
        mutation: ModelCallMutation | ModelCallResponse | None,
    ) -> None:
        if mutation is None:
            return
        if isinstance(mutation, ModelCallResponse):
            raise _ShortCircuit(mutation)
        if mutation.blocked:
            raise ModelCallBlocked(
                mutation.reason,
                hook_result=HookResult(
                    blocked=True,
                    reason=mutation.reason,
                    hook_event=getattr(hook, "event", HOOK_BEFORE_MODEL_CALL),
                    hook_id=getattr(hook, "hook_id", ""),
                    on_block=mutation.on_block,
                    approval=mutation.approval,
                ),
            )
        if mutation.cached_response is not None:
            raise _ShortCircuit(
                self._response_from_message(mutation.cached_response, request, short_circuited=True)
            )
        if mutation.messages is not None:
            request.messages = mutation.messages
        if mutation.metadata:
            request.metadata.update(mutation.metadata)
        if mutation.model_override:
            locked = "model" in request.locks or "security_boundary" in request.locks
            if not locked:
                request.metadata["model_override"] = mutation.model_override
        for field_name in getattr(hook, "lock_fields", []) or []:
            request.locks.add(str(field_name))

    def _apply_response_mutation(
        self,
        response: ModelCallResponse,
        hook: Any,
        mutation: ModelCallMutation | ModelCallResponse | None,
    ) -> None:
        if mutation is None:
            return
        if isinstance(mutation, ModelCallResponse):
            response.message = mutation.message
            response.content = mutation.content
            response.metadata.update(mutation.metadata)
            response.short_circuited = mutation.short_circuited
            return
        if mutation.blocked:
            raise ModelCallBlocked(
                mutation.reason,
                hook_result=HookResult(
                    blocked=True,
                    reason=mutation.reason,
                    hook_event=getattr(hook, "event", HOOK_AFTER_MODEL_CALL),
                    hook_id=getattr(hook, "hook_id", ""),
                    on_block=mutation.on_block,
                    approval=mutation.approval,
                ),
            )
        if mutation.response_content is not None:
            response.content = mutation.response_content
            response.message = self._replace_message_content(response.message, mutation.response_content)
        if mutation.metadata:
            response.metadata.update(mutation.metadata)

    def _normalize_hook_result(self, result: Any) -> ModelCallMutation | ModelCallResponse | None:
        if result is None:
            return None
        if isinstance(result, ModelCallMutation | ModelCallResponse):
            return result
        if isinstance(result, HookResult):
            return ModelCallMutation(
                blocked=bool(result.blocked),
                reason=result.reason,
                on_block=result.on_block,
                approval=result.approval,
                metadata={"hook_response": result.response} if result.response else {},
            )
        if isinstance(result, dict):
            if result.get("cached_response") is not None:
                return ModelCallMutation(cached_response=result.get("cached_response"))
            return ModelCallMutation(
                messages=result.get("messages"),
                metadata=result.get("metadata") if isinstance(result.get("metadata"), dict) else {},
                model_override=str(result.get("model_override") or ""),
                tools_allow=[str(item) for item in result.get("tools_allow", []) or []],
                tools_deny=[str(item) for item in result.get("tools_deny", []) or []],
                response_content=result.get("response_content"),
                blocked=bool(result.get("blocked", False)),
                reason=str(result.get("reason") or ""),
                on_block=str(result.get("on_block") or "deny"),
                approval=result.get("approval") if isinstance(result.get("approval"), dict) else {},
            )
        return None

    def _response_from_message(
        self,
        message: Any,
        request: ModelCallRequest,
        *,
        short_circuited: bool = False,
    ) -> ModelCallResponse:
        if isinstance(message, ModelCallResponse):
            return message
        if isinstance(message, str) and AIMessage is not None:
            message = AIMessage(content=message)
        content = getattr(message, "content", "")
        tool_calls = getattr(message, "tool_calls", None) or []
        usage = getattr(message, "usage_metadata", None) or getattr(message, "response_metadata", {}) or {}
        return ModelCallResponse(
            message=message,
            content=str(content or ""),
            tool_calls=list(tool_calls or []),
            usage=dict(usage) if isinstance(usage, dict) else {},
            model_name=request.model_name,
            metadata=dict(request.metadata),
            short_circuited=short_circuited,
        )

    def _replace_message_content(self, message: Any, content: str) -> Any:
        if message is None:
            return AIMessage(content=content) if AIMessage is not None else content
        if hasattr(message, "model_copy"):
            return message.model_copy(update={"content": content})
        if hasattr(message, "copy"):
            try:
                return message.copy(update={"content": content})
            except TypeError:
                pass
        try:
            clone = copy.copy(message)
            setattr(clone, "content", content)
            return clone
        except Exception:
            return AIMessage(content=content) if AIMessage is not None else content

    def _merge_message_metadata(self, message: Any, metadata: dict[str, Any]) -> Any:
        if not message or not metadata:
            return message
        existing = getattr(message, "response_metadata", None)
        if not isinstance(existing, dict):
            existing = {}
        merged = {**existing, **metadata}
        if hasattr(message, "model_copy"):
            return message.model_copy(update={"response_metadata": merged})
        if hasattr(message, "copy"):
            try:
                return message.copy(update={"response_metadata": merged})
            except TypeError:
                pass
        try:
            clone = copy.copy(message)
            setattr(clone, "response_metadata", merged)
            return clone
        except Exception:
            return message

    def _append_audit(
        self,
        request: ModelCallRequest,
        *,
        hook: Any,
        event: str,
        duration_ms: float,
        mutation_summary: str,
        blocked: bool = False,
        short_circuited: bool = False,
    ) -> None:
        request.audit.append(
            ModelCallAuditEvent(
                hook_id=str(getattr(hook, "hook_id", "") or event),
                event=event,
                priority=int(getattr(hook, "priority", 100) or 100),
                input_hash=self._stable_hash(request.messages),
                output_hash=self._stable_hash(request.metadata),
                mutation_summary=mutation_summary,
                blocked=blocked,
                short_circuited=short_circuited,
                duration_ms=int(duration_ms),
            )
        )

    def _publish_pipeline_audit(self, request: ModelCallRequest, response: ModelCallResponse) -> None:
        if not request.audit:
            return
        response.metadata["model_call_pipeline"] = {
            "enabled": True,
            "audit": [event.__dict__ for event in request.audit],
        }

    @staticmethod
    def _capture_rl_model_call(
        request: ModelCallRequest,
        response: ModelCallResponse,
        *,
        status: str = "success",
        error: str = "",
    ) -> None:
        try:
            from .capture_events import emit_model_call

            emit_model_call(request=request, response=response, status=status, error=error)
        except Exception:
            return

    @staticmethod
    def _stable_hash(value: Any) -> str:
        try:
            raw = repr(value).encode("utf-8", errors="replace")
        except Exception:
            raw = b"unhashable"
        return hashlib.sha256(raw).hexdigest()[:16]

    @staticmethod
    def _mutation_summary(mutation: ModelCallMutation | ModelCallResponse | None) -> str:
        if mutation is None:
            return "observe"
        if isinstance(mutation, ModelCallResponse):
            return "short_circuit" if mutation.short_circuited else "response_replace"
        parts: list[str] = []
        if mutation.blocked:
            parts.append("blocked")
        if mutation.messages is not None:
            parts.append("messages")
        if mutation.model_override:
            parts.append("model_override")
        if mutation.cached_response is not None:
            parts.append("cached_response")
        if mutation.response_content is not None:
            parts.append("response_content")
        if mutation.metadata:
            parts.append("metadata")
        return ",".join(parts) or "observe"


class _ShortCircuit(Exception):
    def __init__(self, response: ModelCallResponse):
        super().__init__("model call short-circuited")
        self.response = response


class PolicyChatModel(Runnable):
    """LangChain-compatible wrapper that runs provider calls through a pipeline."""

    def __init__(
        self,
        *,
        inner: Any,
        pipeline: ModelCallPipeline | None = None,
        model_role: str = "primary",
        bound_tools: list[Any] | None = None,
    ) -> None:
        self.inner = inner
        self.pipeline = pipeline
        self.model_role = model_role
        self.bound_tools = list(bound_tools or [])

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def bind_tools(self, tools, **kwargs):
        return PolicyChatModel(
            inner=self.inner.bind_tools(tools, **kwargs),
            pipeline=self.pipeline,
            model_role=self.model_role,
            bound_tools=list(tools or []),
        )

    def bind(self, **kwargs):
        if not hasattr(self.inner, "bind"):
            raise AttributeError(f"{type(self.inner).__name__} has no bind()")
        return PolicyChatModel(
            inner=self.inner.bind(**kwargs),
            pipeline=self.pipeline,
            model_role=self.model_role,
            bound_tools=list(self.bound_tools),
        )

    def model_copy(self, *args, **kwargs):
        if hasattr(self.inner, "model_copy"):
            copied = self.inner.model_copy(*args, **kwargs)
        elif hasattr(self.inner, "copy"):
            copied = self.inner.copy(*args, **kwargs)
        else:
            copied = copy.copy(self.inner)
        return PolicyChatModel(
            inner=copied,
            pipeline=self.pipeline,
            model_role=self.model_role,
            bound_tools=list(self.bound_tools),
        )

    def invoke(self, input: Any, config: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        if not model_call_pipeline_enabled() or self.pipeline is None:
            return self._invoke_inner(input, config=config, **kwargs)

        ctx = current_model_call_context()
        model_name = (
            getattr(self.inner, "azure_deployment", "")
            or getattr(self.inner, "model_name", "")
            or getattr(self.inner, "model", "")
            or ""
        )
        request = ModelCallRequest(
            messages=input,
            model_role=str(ctx.get("model_role") or self.model_role or "primary"),
            model_name=str(ctx.get("model_name") or model_name),
            tools=list(self.bound_tools),
            config=dict(config or {}),
            session_ctx=ctx,
            metadata={"invoke_kwargs": dict(kwargs or {})},
        )

        def provider_call(req: ModelCallRequest) -> Any:
            return self._invoke_inner(req.messages, config=config, **kwargs)

        try:
            response = self.pipeline.invoke(request, provider_call)
            return response.message
        except _ShortCircuit as short:
            return short.response.message

    def _invoke_inner(self, input: Any, config: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        if config is None:
            return self.inner.invoke(input, **kwargs)
        return self.inner.invoke(input, config=config, **kwargs)

