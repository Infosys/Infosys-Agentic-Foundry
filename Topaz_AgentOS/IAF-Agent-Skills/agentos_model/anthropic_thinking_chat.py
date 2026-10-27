"""Anthropic Claude chat wrapper with optional thinking capture.

This adapter is intentionally conservative and only activates when the
Anthropic provider is selected. It uses stdlib HTTP to avoid adding a hard SDK
dependency to existing deployments.
"""

from __future__ import annotations

import json
import os
import secrets
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import PrivateAttr


_RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504, 529})

# OS-backed CSPRNG for retry jitter.
_rng = secrets.SystemRandom()


class ChatAnthropicThinking(BaseChatModel):
    """Minimal Anthropic Messages API wrapper with LangChain tool binding."""

    model: str
    api_key: str
    api_url: str = "https://api.anthropic.com/v1/messages"
    anthropic_version: str = "2023-06-01"
    max_tokens: int = 4096
    thinking_enabled: bool = False
    thinking_budget_tokens: Optional[int] = None
    thinking_effort: str = "medium"
    ca_bundle_path: Optional[str] = None
    timeout: int = 120

    # A brief upstream blip must not fail the turn (e.g. a remedy approval RESUME with a minted one-time token).
    max_retries: int = 4
    retry_base_delay: float = 1.0
    retry_max_delay: float = 20.0

    _ssl_context: Optional[ssl.SSLContext] = PrivateAttr(default=None)

    def _get_ssl_context(self) -> ssl.SSLContext:
        if self._ssl_context is not None:
            return self._ssl_context
        ca = self.ca_bundle_path if self.ca_bundle_path and os.path.isfile(self.ca_bundle_path) else None
        ctx = ssl.create_default_context(cafile=ca)
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        self._ssl_context = ctx
        return ctx

    @staticmethod
    def _to_anthropic_tools(tools: list[Any]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for tool in tools or []:
            oa = convert_to_openai_tool(tool)
            fn = oa.get("function", oa)
            converted.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            })
        return converted

    @staticmethod
    def _messages_to_anthropic(messages: List[BaseMessage]) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        out: list[dict[str, Any]] = []
        for message in messages:
            if isinstance(message, SystemMessage):
                system_parts.append(str(message.content))
            elif isinstance(message, HumanMessage):
                out.append({"role": "user", "content": str(message.content)})
            elif isinstance(message, ToolMessage):
                out.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": str(getattr(message, "tool_call_id", "") or ""),
                        "content": str(message.content),
                    }],
                })
            elif isinstance(message, AIMessage):
                content_blocks: list[dict[str, Any]] = []
                for item in (getattr(message, "additional_kwargs", None) or {}).get("reasoning_items") or []:
                    if isinstance(item, dict) and item.get("type") in {"thinking", "redacted_thinking"}:
                        content_blocks.append(dict(item))
                if message.content:
                    content_blocks.append({"type": "text", "text": str(message.content)})
                for call in getattr(message, "tool_calls", None) or []:
                    content_blocks.append({
                        "type": "tool_use",
                        "id": str(call.get("id") or ""),
                        "name": str(call.get("name") or ""),
                        "input": call.get("args") or {},
                    })
                out.append({"role": "assistant", "content": content_blocks or [{"type": "text", "text": ""}]})
            else:
                out.append({"role": "user", "content": str(getattr(message, "content", message))})
        return "\n\n".join(system_parts), out

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        system, anth_messages = self._messages_to_anthropic(messages)
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": int(kwargs.get("max_tokens") or self.max_tokens),
            "messages": anth_messages,
        }
        if system:
            body["system"] = system
        if stop:
            body["stop_sequences"] = list(stop)
        tools = self._to_anthropic_tools(list(kwargs.get("tools") or []))
        if tools:
            body["tools"] = tools
        if self.thinking_enabled:
            use_adaptive = any(v in self.model.lower() for v in (
                "4-6", "4-7", "4-8", "4.6", "4.7", "4.8",
                "sonnet-5", "fable-5", "mythos-5",
            ))
            if use_adaptive:
                body["thinking"] = {"type": "adaptive"}
            else:
                budget = int(self.thinking_budget_tokens) if self.thinking_budget_tokens else max(int(body["max_tokens"]) // 2, 1024)
                if body["max_tokens"] <= budget:
                    body["max_tokens"] = budget + 4096
                body["thinking"] = {"type": "enabled", "budget_tokens": budget}

        req = urllib.request.Request(
            self.api_url,
            data=json.dumps(body).encode(),
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": self.anthropic_version,
                "content-type": "application/json",
            },
            method="POST",
        )
        try:
            data = self._send_with_retry(req)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:500]
            raise RuntimeError(f"Anthropic HTTP {exc.code}: {detail}") from exc

        msg = self._parse_response(data)
        usage = data.get("usage") or {}
        return ChatResult(
            generations=[ChatGeneration(message=msg)],
            llm_output={
                "model_name": self.model,
                "model": self.model,
                "stop_reason": data.get("stop_reason"),
                "usage": usage,
            },
        )

    def _send_with_retry(self, req: "urllib.request.Request") -> dict[str, Any]:
        """POST with exponential backoff on transient Anthropic errors (429 rate-limit,
        5xx, and 529 overloaded) plus transient network faults. Non-transient 4xx fail
        fast (re-raised for the caller's existing handler). Honors a `Retry-After` header."""
        attempts = max(1, int(self.max_retries) + 1)
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(
                    req, context=self._get_ssl_context(), timeout=self.timeout
                ) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                # Last attempt, or a non-transient status → let the caller's handler format it.
                if attempt >= attempts - 1 or exc.code not in _RETRY_STATUSES:
                    raise
                retry_after = exc.headers.get("Retry-After") if getattr(exc, "headers", None) else None
                time.sleep(self._retry_delay(attempt, retry_after))
            except (urllib.error.URLError, TimeoutError, ssl.SSLError) as exc:
                # DNS / connection reset / timeout — transient network, retry.
                if attempt >= attempts - 1:
                    raise RuntimeError(f"Anthropic request error: {type(exc).__name__}: {exc}") from exc
                time.sleep(self._retry_delay(attempt, None))
        # Loop always returns or raises above; this satisfies type-checkers.
        raise RuntimeError("Anthropic request failed after retries")

    def _retry_delay(self, attempt: int, retry_after: Optional[str]) -> float:
        """Exponential backoff with jitter, capped; prefers a server `Retry-After`."""
        if retry_after:
            try:
                return min(float(retry_after), float(self.retry_max_delay))
            except (TypeError, ValueError):
                pass
        base = float(self.retry_base_delay) * (2 ** attempt)
        return min(base, float(self.retry_max_delay)) + _rng.uniform(0, 0.5)

    def _parse_response(self, data: dict[str, Any]) -> AIMessage:
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        reasoning_items: list[dict[str, Any]] = []
        for block in data.get("content") or []:
            block_type = str(block.get("type") or "")
            if block_type == "text":
                text_parts.append(str(block.get("text") or ""))
            elif block_type == "tool_use":
                tool_calls.append({
                    "id": str(block.get("id") or f"call_{len(tool_calls)}"),
                    "name": str(block.get("name") or ""),
                    "args": block.get("input") if isinstance(block.get("input"), dict) else {},
                    "type": "tool_call",
                })
            elif block_type in {"thinking", "redacted_thinking"}:
                reasoning_items.append(dict(block))
        usage = data.get("usage") or {}
        return AIMessage(
            content="".join(text_parts).strip(),
            tool_calls=tool_calls,
            additional_kwargs={
                "provider": "anthropic",
                "response_id": str(data.get("id") or ""),
                "reasoning_items": reasoning_items,
            },
            response_metadata={
                "id": str(data.get("id") or ""),
                "model": self.model,
                "finish_reason": str(data.get("stop_reason") or ""),
                "token_usage": usage,
            },
            usage_metadata={
                "input_tokens": int(usage.get("input_tokens") or 0),
                "output_tokens": int(usage.get("output_tokens") or 0),
                "total_tokens": int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0),
            },
        )

    def bind_tools(
        self,
        tools: List[Any],
        *,
        tool_choice: Optional[Any] = None,
        **kwargs: Any,
    ) -> Runnable:
        bind_kwargs: dict[str, Any] = {"tools": list(tools)}
        if tool_choice is not None:
            bind_kwargs["tool_choice"] = tool_choice
        return self.bind(**bind_kwargs, **kwargs)

    @property
    def _llm_type(self) -> str:
        return "anthropic-thinking"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "thinking_enabled": self.thinking_enabled,
            "thinking_budget_tokens": self.thinking_budget_tokens,
        }
