"""Azure OpenAI Responses API chat wrapper.

This adapter is intentionally narrow: it supports the provider-native ReAct
runtime's needs (messages, tool binding, tool-call parsing, usage metadata, and
reasoning item passthrough). It is only selected when reasoning replay is
explicitly enabled; ModelRegistry falls back to AzureChatOpenAI otherwise.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import PrivateAttr


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return {}


class ChatAzureResponsesRaw(BaseChatModel):
    """LangChain BaseChatModel backed by Azure OpenAI Responses API."""

    azure_endpoint: str
    api_key: str
    api_version: str = "2025-04-01-preview"
    azure_deployment: str
    reasoning_effort: str = "medium"
    timeout: int = 120
    previous_response_id: Optional[str] = None

    _client: Any = PrivateAttr(default=None)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from openai import AzureOpenAI
        except Exception as exc:  # pragma: no cover - dependency failure path
            raise ImportError("openai SDK is required for ChatAzureResponsesRaw") from exc
        self._client = AzureOpenAI(
            azure_endpoint=self.azure_endpoint,
            api_key=self.api_key,
            api_version=self.api_version,
            timeout=self.timeout,
        )
        return self._client

    @staticmethod
    def _responses_tools(tools: list[Any]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for tool in tools or []:
            oa = convert_to_openai_tool(tool)
            fn = oa.get("function", oa)
            converted.append({
                "type": "function",
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
            })
        return converted

    @staticmethod
    def _messages_to_responses_input(messages: List[BaseMessage]) -> list[dict[str, Any]]:
        inputs: list[dict[str, Any]] = []
        for message in messages:
            if isinstance(message, SystemMessage):
                inputs.append({"role": "system", "content": str(message.content)})
            elif isinstance(message, HumanMessage):
                inputs.append({"role": "user", "content": str(message.content)})
            elif isinstance(message, ToolMessage):
                inputs.append({
                    "type": "function_call_output",
                    "call_id": str(getattr(message, "tool_call_id", "") or ""),
                    "output": str(message.content),
                })
            elif isinstance(message, AIMessage):
                if message.content:
                    inputs.append({"role": "assistant", "content": str(message.content)})
                for tool_call in getattr(message, "tool_calls", None) or []:
                    inputs.append({
                        "type": "function_call",
                        "call_id": str(tool_call.get("id") or ""),
                        "name": str(tool_call.get("name") or ""),
                        "arguments": json.dumps(tool_call.get("args") or {}),
                    })
            else:
                inputs.append({"role": "user", "content": str(getattr(message, "content", message))})
        return inputs

    @staticmethod
    def _parse_response(resp: Any) -> AIMessage:
        response = _as_dict(resp)
        output = response.get("output") or []
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        reasoning_items: list[dict[str, Any]] = []

        for raw_item in output:
            item = _as_dict(raw_item)
            item_type = str(item.get("type") or "")
            if item_type == "reasoning":
                reasoning_items.append(item)
                continue
            if item_type == "function_call":
                args = item.get("arguments") or "{}"
                try:
                    parsed_args = json.loads(args) if isinstance(args, str) else dict(args)
                except Exception:
                    parsed_args = {"_raw_arguments": str(args)}
                tool_calls.append({
                    "id": str(item.get("call_id") or item.get("id") or f"call_{len(tool_calls)}"),
                    "name": str(item.get("name") or ""),
                    "args": parsed_args,
                    "type": "tool_call",
                })
                continue
            if item_type == "message":
                for content_item in item.get("content") or []:
                    content = _as_dict(content_item)
                    if content.get("type") in {"output_text", "text"}:
                        text_parts.append(str(content.get("text") or ""))

        content = "".join(text_parts).strip()
        if not content:
            content = str(getattr(resp, "output_text", "") or response.get("output_text") or "")

        usage = response.get("usage") or {}
        response_id = str(response.get("id") or "")
        return AIMessage(
            content=content,
            tool_calls=tool_calls,
            additional_kwargs={
                "provider": "azure",
                "response_id": response_id,
                "codex_reasoning_items": reasoning_items,
            },
            response_metadata={
                "id": response_id,
                "model": str(response.get("model") or ""),
                "finish_reason": str(response.get("status") or ""),
                "token_usage": usage,
            },
            usage_metadata=_usage_metadata_from_responses(usage),
        )

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        body: dict[str, Any] = {
            "model": self.azure_deployment,
            "input": self._messages_to_responses_input(messages),
            "reasoning": {"effort": self.reasoning_effort, "summary": "auto"},
            "max_output_tokens": int(kwargs.get("max_output_tokens") or kwargs.get("max_tokens") or 4096),
        }
        previous_response_id = kwargs.get("previous_response_id") or self.previous_response_id
        if previous_response_id:
            body["previous_response_id"] = str(previous_response_id)
        raw_tools = kwargs.get("tools") or []
        tools = self._responses_tools(list(raw_tools))
        if tools:
            body["tools"] = tools
        tool_choice = kwargs.get("tool_choice")
        if tool_choice:
            body["tool_choice"] = tool_choice
        if stop:
            body["stop"] = list(stop)

        resp = self._get_client().responses.create(**body)
        msg = self._parse_response(resp)
        return ChatResult(generations=[ChatGeneration(message=msg)])

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
        return "azure-responses-raw"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "azure_deployment": self.azure_deployment,
            "api_version": self.api_version,
            "reasoning_effort": self.reasoning_effort,
        }


def _usage_metadata_from_responses(usage: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(usage, dict):
        return None
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
    output_details = usage.get("output_tokens_details") or {}
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "output_token_details": {
            "reasoning": int(output_details.get("reasoning_tokens") or 0)
            if isinstance(output_details, dict) else 0,
        },
    }
