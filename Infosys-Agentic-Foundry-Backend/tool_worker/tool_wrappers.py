"""
Kafka Tool Wrappers
===================
Factory functions that wrap a local tool (Python function) into an async
function whose body sends the call to Kafka and waits for the result.

The returned wrapper preserves the **original function's signature** via
``functools.wraps`` so that LangGraph (or any other framework that inspects
``inspect.signature``) sees the correct parameter names and types.

MCP tools are handled separately in
``BaseAgentInference._make_kafka_mcp_tool`` because their metadata lives
on the ``StructuredTool`` object rather than on a plain function.
"""
# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import uuid
from functools import wraps
from typing import Any

from src.utils.kafka_manager import KafkaManager
from tool_worker.kafka_tool_listener import create_response_consumer, collect_responses

from telemetry_wrapper import logger


def make_kafka_tool(
    original_func,
    tool_id: str,
    kafka_mgr: KafkaManager,
    response_consumer=None,
    tool_version: str = "v1",
):
    """
    Return an async wrapper that, when called, publishes the invocation to
    Kafka and blocks (async) until the remote worker responds.

    The wrapper carries the original function's ``__name__``, ``__doc__``,
    ``__annotations__``, and ``__wrapped__`` (set by ``functools.wraps``)
    so ``inspect.signature(wrapper)`` returns the **original** signature.

    Args:
        original_func: The plain Python tool function (sync or async).
        tool_id: Database primary key of the tool — sent in every Kafka
                 message so the worker can look it up.
        kafka_mgr: A :class:`KafkaManager` instance used to publish
                   tool-call requests.
        response_consumer: An **already-created** Kafka consumer (from
                           ``create_response_consumer``).  If ``None`` a
                           fresh consumer is created per call (safe but
                           slightly slower).
        tool_version: Version of the tool to execute (e.g., 'v1', 'v2').

    Returns:
        An ``async def`` that can be passed directly to ``create_react_agent``
        as a tool.
    """
    tool_name = getattr(original_func, "__name__", str(original_func))

    @wraps(original_func)
    async def _kafka_dispatch(**kwargs: Any) -> str:
        tool_call_id = uuid.uuid4().hex

        # If no shared consumer was provided, create one just for this call
        consumer = response_consumer
        own_consumer = consumer is None
        if own_consumer:
            consumer = create_response_consumer(kafka_mgr)

        try:
            kafka_mgr.send_tool_request(
                tool_call_id=tool_call_id,
                tool_id=tool_id,
                tool_name=tool_name,
                args=kwargs,
                tool_version=tool_version,
            )

            results = await collect_responses(consumer, [tool_call_id])
            response = results.get(tool_call_id)

            if response is None:
                return f"[Kafka timeout] No response received for {tool_name}"

            if response.get("status") != "success":
                return f"[Kafka error] {response.get('result', 'Unknown error')}"

            return str(response.get("result", ""))
        finally:
            if own_consumer:
                try:
                    consumer.close()
                except Exception:
                    pass

    return _kafka_dispatch
