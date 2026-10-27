"""Provider-native React runtime implementation.

This runtime removes LangGraph from the React loop while reusing the configured
chat model, LangChain tool schemas, and the shared AgentOS governance boundary.
The first concrete path is Azure OpenAI through the existing AzureChatOpenAI
model object returned by ModelRegistry.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from .types import NativeProviderMetadata, NativeTurn, NativeUsage, bounded_preview
from .. import cancellation as _run_cancel


class ReactRuntimeUnavailable(RuntimeError):
    """Raised when native React runtime is selected but no adapter is configured."""


class NativeReactRuntime:
    """Provider-native tool loop using the existing configured chat model."""

    name = "native"

    MAX_DENY_FEEDBACKS = 3

    def __init__(
        self,
        *,
        llm: Any,
        tools: list[Any],
        system_prompt: str,
        max_iterations: int = 8,
        model_kwargs: dict[str, Any] | None = None,
        emit: Callable[[str, Any], None] | None = None,
    ) -> None:
        if llm is None:
            raise ReactRuntimeUnavailable("Native React runtime requires a configured primary LLM")
        if not hasattr(llm, "bind_tools"):
            raise ReactRuntimeUnavailable(
                f"Configured LLM type {type(llm).__name__} does not support native tool binding"
            )
        self.llm = llm
        self.tools = list(tools or [])
        self.system_prompt = system_prompt or ""
        self.max_iterations = max(1, int(max_iterations or 8))
        self.model_kwargs = dict(model_kwargs or {})
        # Default None → no behavior change. Always guarded so it can never break the loop.
        self._emit = emit
        self._tool_by_name = {
            str(getattr(tool, "name", "")): tool
            for tool in self.tools
            if getattr(tool, "name", "")
        }
        self.last_turn: NativeTurn | None = None
        self.pending_resume: dict[str, Any] | None = None

    def invoke_turn(
        self,
        *,
        messages: list[Any],
        tools: list[Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> NativeTurn:
        """Invoke one Azure-native model turn and return a normalized turn."""
        options = options or {}
        active_tools = list(tools if tools is not None else self.tools)
        model = self._bind_model(active_tools)
        from ..model_registry import llm_model_name as _llm_model_name, llm_base_url as _llm_base_url
        _nt_model = _llm_model_name(model)
        _nt_base = _llm_base_url(model)
        import logging as _logging
        _logging.getLogger(__name__).info("⚡ NATIVE REACT invoke_turn  ▸ model=%s  base_url=%s", _nt_model, _nt_base)
        message = model.invoke(messages, config=options.get("config"))
        if not isinstance(message, AIMessage):
            message = AIMessage(content=getattr(message, "content", str(message)))
        turn = self._native_turn_from_message(message)
        self.last_turn = turn
        return turn

    def run(
        self,
        *,
        messages: list[Any],
        config: dict[str, Any] | None,
        govern_batch: Callable[[list[dict[str, Any]]], list[Any]],
        record_tool_result: Callable[[dict[str, Any], str], None] | None = None,
    ) -> dict[str, list[Any]] | str:
        """Run a complete native React loop and return LangGraph-compatible output."""
        if not self.tools:
            raise ReactRuntimeUnavailable("Native React runtime requires at least one tool")

        current_messages: list[Any] = []
        if self.system_prompt:
            current_messages.append(SystemMessage(content=self.system_prompt))
        current_messages.extend(list(messages))
        collected: list[Any] = list(messages)
        return self._loop(current_messages, collected, config, govern_batch, record_tool_result)

    def _loop(self, current_messages, collected, config, govern_batch, record_tool_result):
        """The governed React loop body — shared by run() and resume_and_continue()."""
        model = self._bind_model(self.tools)
        from ..model_registry import llm_model_name as _llm_model_name, llm_base_url as _llm_base_url
        _loop_model = _llm_model_name(model)
        _loop_base = _llm_base_url(model)
        import logging as _logging
        _logging.getLogger(__name__).info("⚡ NATIVE REACT loop start  ▸ model=%s  base_url=%s", _loop_model, _loop_base)
        deny_feedback_count = 0  # denied tool calls fed back to the model this run (bounded)
        for _turn_index in range(self.max_iterations):
            _run_cancel.check_cancelled()  # cooperative stop before each native LLM turn
            _logging.getLogger(__name__).info("⚡ NATIVE REACT turn #%d  ▸ model=%s", _turn_index + 1, _loop_model)
            self._safe_emit("reason", _turn_index)
            ai_message = model.invoke(current_messages, config=config)
            if not isinstance(ai_message, AIMessage):
                ai_message = AIMessage(content=getattr(ai_message, "content", str(ai_message)))
            self.last_turn = self._native_turn_from_message(ai_message)
            # Surface the model's own reasoning for this turn into the thinking box (Tier 3, per-turn).
            if getattr(self.last_turn, "reasoning", ""):
                self._safe_emit("reasoning_text", self.last_turn.reasoning)

            collected.append(ai_message)
            current_messages.append(ai_message)
            tool_calls = self.last_turn.normalized_tool_calls()
            if not tool_calls:
                return {"messages": collected}

            decisions = govern_batch(tool_calls)

            # HITL pause takes precedence and is unchanged: if any call in this batch
            # needs human approval, checkpoint the whole batch so an approval resumes it.
            if any(getattr(d, "status", "") in ("pending", "already_pending") for d in decisions):
                self.pending_resume = {
                    "messages": list(current_messages),
                    "collected": list(collected),
                    "tool_calls": list(tool_calls),
                }
                return "__PENDING__"

            _turn_denies = [d for d in decisions if getattr(d, "status", "") == "blocked"]
            if _turn_denies:
                deny_feedback_count += len(_turn_denies)
                if deny_feedback_count > self.MAX_DENY_FEEDBACKS:
                    self.pending_resume = None
                    return f"__BLOCKED__|{_turn_denies[0].reason or 'Tool call blocked by policy hook.'}"

            _decision_by_id = {str(getattr(d, "tool_call_id", "")): d for d in decisions}
            for tool_call in tool_calls:
                _d = _decision_by_id.get(str(tool_call.get("id") or ""))
                if _d is not None and getattr(_d, "status", "") == "blocked":
                    _reason = getattr(_d, "reason", "") or "Tool call blocked by policy."
                    tool_message = ToolMessage(
                        content=(f"BLOCKED by policy — this tool call was not permitted: {_reason} "
                                 f"Do not repeat this call; use an allowed tool instead."),
                        name=str(tool_call.get("name") or ""),
                        tool_call_id=str(tool_call.get("id") or ""),
                    )
                else:
                    self._safe_emit("tool", tool_call.get("name"))
                    tool_message = self._execute_tool_call(tool_call, config=config)
                if record_tool_result is not None:
                    record_tool_result(tool_call, str(tool_message.content))
                collected.append(tool_message)
                current_messages.append(tool_message)

        exhausted = ReactRuntimeUnavailable(
            f"Native React runtime reached max_iterations={self.max_iterations} before a final answer"
        )
        exhausted.exhausted_max_iterations = True
        exhausted.collected_messages = list(collected)
        raise exhausted

    def _safe_emit(self, kind: str, value: Any) -> None:
        """Fire the optional live-activity emitter; never let it break the loop."""
        if self._emit is None:
            return
        try:
            self._emit(kind, value)
        except Exception:
            pass

    def _bind_model(self, tools: list[Any]):
        model = self.llm.bind_tools(tools) if tools else self.llm
        if self.model_kwargs and hasattr(model, "bind"):
            return model.bind(**self.model_kwargs)
        return model

    def resume_and_continue(self, *, config, govern_batch, record_tool_result=None, execute_held=None):
        """Resume a paused turn after approval: execute the previously-blocked tool
        call(s) directly (approval already granted — bypass the gate), then re-enter the
        governed loop so the model can finish the task (and pause again if a NEW call is
        blocked). Returns the normal {"messages": [...]} or "__PENDING__" again.

        `execute_held` (required for correctness with kernel-gated tools): a callback
        that runs a held tool_call with the right confirmed=True semantics and returns
        the result string. Without it, kernel-gated tools (shell/write_file) would be
        re-blocked by their auto_run gate. Falls back to the raw tool loop only for
        tools that don't gate.
        """
        rs = self.pending_resume
        if not rs:
            raise ReactRuntimeUnavailable("Native runtime has no pending_resume to continue")
        self.pending_resume = None
        current_messages = list(rs.get("messages") or [])
        collected = list(rs.get("collected") or [])
        for tool_call in (rs.get("tool_calls") or []):
            if execute_held is not None:
                content = execute_held(tool_call)
                tool_message = ToolMessage(
                    content=content if isinstance(content, str) else str(content),
                    name=str(tool_call.get("name") or ""),
                    tool_call_id=str(tool_call.get("id") or ""),
                )
            else:
                tool_message = self._execute_tool_call(tool_call, config=config)
            if record_tool_result is not None:
                record_tool_result(tool_call, str(tool_message.content))
            collected.append(tool_message)
            current_messages.append(tool_message)
        return self._loop(current_messages, collected, config, govern_batch, record_tool_result)

    def _execute_tool_call(self, tool_call: dict[str, Any], *, config: dict[str, Any] | None) -> ToolMessage:
        tool_name = str(tool_call.get("name") or "")
        tool_args = tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {}
        tool_call_id = str(tool_call.get("id") or "")
        tool = self._tool_by_name.get(tool_name)
        if tool is None:
            return ToolMessage(
                content=f"Error: native runtime could not find tool '{tool_name}'",
                name=tool_name,
                tool_call_id=tool_call_id,
            )

        try:
            result = tool.invoke(tool_args, config=config)
            content = result if isinstance(result, str) else str(result)
        except Exception as exc:
            content = f"Error: {type(exc).__name__}: {str(exc)[:500]}"

        return ToolMessage(content=content, name=tool_name, tool_call_id=tool_call_id)

    @staticmethod
    def _native_turn_from_message(message: AIMessage) -> NativeTurn:
        usage_meta = getattr(message, "usage_metadata", None) or {}
        response_meta = getattr(message, "response_metadata", None) or {}
        token_usage = response_meta.get("token_usage") if isinstance(response_meta, dict) else {}
        token_usage = token_usage if isinstance(token_usage, dict) else {}

        input_tokens = usage_meta.get("input_tokens") or token_usage.get("prompt_tokens") or 0
        output_tokens = usage_meta.get("output_tokens") or token_usage.get("completion_tokens") or 0
        total_tokens = usage_meta.get("total_tokens") or token_usage.get("total_tokens") or 0
        additional = getattr(message, "additional_kwargs", None) or {}
        reasoning = _extract_reasoning(additional, message.content)
        reasoning_items = _extract_reasoning_items(additional, message.content)
        response_id = _extract_response_id(additional, response_meta)
        provider = _extract_provider(additional, response_meta)
        finish_reason = ""
        if isinstance(response_meta, dict):
            finish_reason = str(response_meta.get("finish_reason") or response_meta.get("stop_reason") or "")

        raw_preview = _safe_json_preview({
            "response_metadata": response_meta,
            "additional_kwargs_keys": sorted(str(k) for k in additional.keys()),
        })
        content = message.content if isinstance(message.content, str) else str(message.content)
        return NativeTurn(
            content=content,
            reasoning=reasoning,
            reasoning_items=reasoning_items,
            response_id=response_id,
            tool_calls=list(getattr(message, "tool_calls", None) or []),
            usage=NativeUsage(
                input_tokens=int(input_tokens or 0),
                output_tokens=int(output_tokens or 0),
                total_tokens=int(total_tokens or 0),
                raw=dict(token_usage or usage_meta or {}),
            ),
            provider_metadata=NativeProviderMetadata(
                provider=provider,
                model=str(response_meta.get("model_name") or response_meta.get("model") or "")
                if isinstance(response_meta, dict) else "",
                finish_reason=finish_reason,
                response_id=response_id,
            ),
            raw_response_preview=raw_preview,
        )


def _extract_reasoning(additional: dict[str, Any], content: Any) -> str:
    for key in ("reasoning", "reasoning_content", "thinking", "thinking_content"):
        value = additional.get(key)
        if value:
            return bounded_preview(_coerce_reasoning_text(value))
    if isinstance(content, list):
        parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if str(item.get("type", "")).lower() in {"reasoning", "thinking"}:
                parts.append(_coerce_reasoning_text(item))
        return bounded_preview("\n".join(part for part in parts if part))
    return ""


def _coerce_reasoning_text(value: Any) -> str:
    """Flatten a reasoning payload into text.

    Handles plain strings, chat-completions reasoning blocks, and the Responses
    API shape where reasoning arrives as {"summary": [{"text": ...}, ...]} or a
    list of such items. Always returns a string so callers can preview it.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if value.get("text"):
            return str(value["text"])
        if value.get("content"):
            return str(value["content"])
        summary = value.get("summary")
        if summary is not None:
            return _coerce_reasoning_text(summary)
        return ""
    if isinstance(value, (list, tuple)):
        return "\n".join(t for t in (_coerce_reasoning_text(v) for v in value) if t)
    return str(value)


def _extract_reasoning_items(additional: dict[str, Any], content: Any) -> list[dict[str, Any]]:
    """Extract provider reasoning items in a neutral bounded shape.

    Provider adapters should place replayable reasoning under
    ``additional_kwargs["reasoning_items"]`` or ``["codex_reasoning_items"]``.
    This helper is intentionally conservative and keeps only simple dict items.
    """
    candidates = (
        additional.get("reasoning_items"),
        additional.get("codex_reasoning_items"),
        additional.get("reasoning_details"),
    )
    items: list[dict[str, Any]] = []
    for candidate in candidates:
        if isinstance(candidate, list):
            items.extend(_safe_reasoning_item(item) for item in candidate if isinstance(item, dict))
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and str(block.get("type", "")).lower() in {"reasoning", "thinking"}:
                items.append(_safe_reasoning_item(block))
    return [item for item in items if item]


def _safe_reasoning_item(item: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe bounded reasoning item for traces/UI previews."""
    safe: dict[str, Any] = {}
    redacted_keys = {"encrypted_content", "signature", "signed_content"}
    for key, value in item.items():
        if key in redacted_keys:
            continue
        if key in {"text", "content", "summary", "thinking"}:
            safe[key] = bounded_preview(_coerce_reasoning_text(value))
        elif isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = bounded_preview(value) if isinstance(value, str) else value
    if "type" not in safe:
        safe["type"] = str(item.get("type") or "reasoning")
    return safe


def _extract_response_id(additional: dict[str, Any], response_meta: dict[str, Any]) -> str:
    if isinstance(response_meta, dict):
        value = response_meta.get("id") or response_meta.get("response_id")
        if value:
            return str(value)
    return str(additional.get("response_id") or additional.get("id") or "")


def _extract_provider(additional: dict[str, Any], response_meta: dict[str, Any]) -> str:
    value = additional.get("provider")
    if value:
        return str(value)
    if isinstance(response_meta, dict):
        value = response_meta.get("provider") or response_meta.get("system_fingerprint")
        model = str(response_meta.get("model_name") or response_meta.get("model") or "").lower()
        if value:
            return str(value)
        if "gemini" in model:
            return "vertex"
        if "claude" in model:
            return "anthropic"
    return "azure_openai"


def _is_thinking_only_assistant(message: Any) -> bool:
    """True when an assistant message has reasoning but no content/tool calls.

    This mirrors the provider safety valve used by Hermes: some providers reject
    replayed assistant turns whose final block is only thinking/reasoning.
    """
    if isinstance(message, dict):
        role = message.get("role")
        content = message.get("content")
        tool_calls = message.get("tool_calls")
        additional = message
    else:
        role = getattr(message, "type", None) or getattr(message, "role", None)
        content = getattr(message, "content", None)
        tool_calls = getattr(message, "tool_calls", None)
        additional = getattr(message, "additional_kwargs", None) or {}
    if str(role).lower() not in {"assistant", "ai", "aimessage"}:
        return False
    if tool_calls:
        return False
    if isinstance(content, str) and content.strip():
        return False
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                if block:
                    return False
                continue
            block_type = str(block.get("type") or "").lower()
            if block_type in {"thinking", "redacted_thinking", "reasoning"}:
                continue
            if block_type == "text" and not str(block.get("text") or "").strip():
                continue
            return False
    elif content not in (None, ""):
        return False
    return bool(_extract_reasoning(additional, content) or _extract_reasoning_items(additional, content))


def _safe_json_preview(value: Any) -> str:
    try:
        return bounded_preview(json.dumps(value, default=str, sort_keys=True))
    except Exception:
        return bounded_preview(value)
