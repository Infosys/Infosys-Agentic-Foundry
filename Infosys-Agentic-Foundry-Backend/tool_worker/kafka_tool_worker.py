"""
IAF Kafka Tool Worker
=====================
Consumes tool-call requests from Kafka, resolves tool code (Python or MCP),
executes the tool, and publishes the result back to Kafka.

Request schema (JSON on ``iaf_tool_call_requests`` topic):
    tool_call_id : str          — unique id for this invocation
    tool_id      : str          — DB primary key (e.g. "abc123" for Python, "mcp_xyz" for MCP)
    tool_name    : str          — function / MCP tool name to call
    args         : dict         — keyword arguments for the tool
    timestamp    : float        — epoch seconds (set by the caller)
"""
import asyncio
import inspect
import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Union

from kafka import KafkaProducer

from src.config.constants import KafkaDefaults, KafkaTopics
from src.database.repositories import ToolRepository, McpToolRepository, ToolVersionRepository
from src.tools.mcp_tool_adapter import MCPToolAdapter
from mcp.types import TextContent, Content
from src.utils.secrets_handler import (
    get_user_secrets,
    get_public_key,
    get_group_secrets,
    current_user_email,
    current_user_department,
    current_request_headers
)
from src.decorators.tool_access import (
    resource_access,
    require_role,
    authorized_tool,
    current_tool_user,
    get_tool_user_context,
)
from src.utils.sandbox import get_sandbox_builtins, get_sandbox_extras

from src.utils.kafka_manager import KafkaManager
from telemetry_wrapper import logger

KAFKA_DEFAULTS = KafkaDefaults()


# ── Helpers ─────────────────────────────────────────────────────────────────


def _normalise_mcp_response(response: Any) -> Any:
    """Convert MCP Content objects into plain strings for JSON serialisation."""
    if isinstance(response, list) and response and isinstance(response[0], Content):
        parts = []
        for item in response:
            if isinstance(item, TextContent) and item.text:
                parts.append(item.text)
            elif isinstance(item, dict):
                parts.append(json.dumps(item))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    if isinstance(response, Content):
        if isinstance(response, TextContent) and response.text:
            return response.text
        return str(response)
    return response


def _build_local_var() -> Dict[str, Any]:
    """Return the namespace dict injected into every ``exec()`` call."""
    return {
        "__builtins__": get_sandbox_builtins(),
        **get_sandbox_extras(),
        "get_user_secrets": get_user_secrets,
        "current_user_email": current_user_email,
        "current_user_department": current_user_department,
        "get_public_secrets": get_public_key,
        "get_group_secrets": get_group_secrets,
        "resource_access": resource_access,
        "require_role": require_role,
        "authorized_tool": authorized_tool,
        "current_tool_user": current_tool_user,
        "get_tool_user_context": get_tool_user_context,
        "current_request_headers": current_request_headers,
    }


def _clean_string_args(args: Dict[str, Any]) -> Dict[str, Any]:
    """Strip extraneous wrapping double-quotes from string arguments."""
    cleaned: Dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str) and len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            cleaned[key] = value[1:-1]
        else:
            cleaned[key] = value
    return cleaned


def _execute_python_tool(tool_name: str, code_snippet: str, args: Dict[str, Any]) -> Any:
    """
    ``exec()`` the tool's code_snippet, locate the function by *tool_name*,
    and invoke it with the given *args*.  Handles sync and async callables.
    """
    local_var = _build_local_var()
    exec(code_snippet, local_var)

    func = local_var.get(tool_name)
    if func is None:
        raise ValueError(f"Function '{tool_name}' not found after exec of code_snippet")

    cleaned_args = _clean_string_args(args)

    if inspect.iscoroutinefunction(func):
        return asyncio.run(func(**cleaned_args))
    return func(**cleaned_args)


def _process_python_request(
    tool_call_id: str,
    tool_name: str,
    args: Dict[str, Any],
    code_snippet: str,
    kafka_mgr: KafkaManager,
    producer: KafkaProducer,
) -> None:
    """Execute a Python tool and publish the result (runs in thread pool)."""
    try:
        result = _execute_python_tool(tool_name, code_snippet, args)
        kafka_mgr.send_tool_response(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            args=args,
            result=result,
            status="success",
            producer=producer,
        )
        logger.info(f"Python tool OK: tool_call_id={tool_call_id}, tool={tool_name}")
    except Exception as e:
        logger.error(f"Python tool FAIL: tool_call_id={tool_call_id}, tool={tool_name}, error={e}")
        kafka_mgr.send_tool_response(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            args=args,
            result=str(e),
            status="error",
            producer=producer,
        )


# ── Worker class ────────────────────────────────────────────────────────────


class KafkaToolWorker:
    """
    Polls ``iaf_tool_call_requests``, executes each tool (Python *or* MCP),
    and publishes results to ``iaf_tool_call_responses``.

    *  Python tools → ``exec()`` + ``ThreadPoolExecutor``
    *  MCP tools    → ``MCPToolAdapter.create_mcp_client()`` + ``client.call_tool()``
    """

    def __init__(
        self,
        tool_repo: ToolRepository,
        mcp_tool_repo: McpToolRepository,
        tool_version_repo: ToolVersionRepository = None,
        bootstrap_servers: Union[str, List[str]] = None,
        group_id: str = KAFKA_DEFAULTS.CONSUMER_GROUP_TOOL_WORKERS,
        max_records: int = KAFKA_DEFAULTS.CONSUMER_MAX_POLL_RECORDS,
        max_parallel: int = KAFKA_DEFAULTS.WORKER_MAX_PARALLEL_EXECUTIONS,
        poll_timeout_ms: int = KAFKA_DEFAULTS.CONSUMER_POLL_TIMEOUT_MS,
    ):
        self.tool_repo = tool_repo
        self.mcp_tool_repo = mcp_tool_repo
        self.tool_version_repo = tool_version_repo
        self.group_id = group_id
        self.max_records = max_records
        self.max_parallel = max_parallel
        self.poll_timeout_ms = poll_timeout_ms
        self.kafka_mgr = KafkaManager(bootstrap_servers=bootstrap_servers)

    # ── DB look-ups ──────────────────────────────────────────────────────

    async def _fetch_python_tool_code(self, tool_id: str, tool_version: str = "v1") -> Optional[str]:
        """
        Return the ``code_snippet`` for a Python tool.

        Tries the versioned ``tool_versions_table`` first (if a
        ``tool_version_repo`` was provided).  Falls back to the
        ``tool_table.code_snippet`` column when versioned code is
        not available.
        """
        # 1. Try versioned code
        if self.tool_version_repo:
            try:
                version_record = await self.tool_version_repo.get_version(
                    tool_id=tool_id, version=tool_version,
                )
                if version_record and version_record.get("code_snippet"):
                    logger.info(f"Loaded versioned code: tool_id={tool_id}, version={tool_version}")
                    return version_record["code_snippet"]
            except Exception as e:
                logger.warning(f"Version lookup failed for {tool_id} {tool_version}: {e}")

        # 2. Fallback to tool_table
        try:
            records = await self.tool_repo.get_tool_record(tool_id=tool_id)
            if records:
                logger.info(f"Using fallback code_snippet from tool_table: tool_id={tool_id}")
                return records[0].get("code_snippet")
            logger.warning(f"Python tool not found: tool_id={tool_id}")
        except Exception as e:
            logger.error(f"Failed to fetch Python tool {tool_id}: {e}")
        return None

    async def _fetch_mcp_tool_config(self, tool_id: str) -> Optional[Dict[str, Any]]:
        """Return the full MCP tool record (contains ``mcp_config``, etc.)."""
        try:
            records = await self.mcp_tool_repo.get_mcp_tool_record(tool_id=tool_id)
            if records:
                return records[0]
            logger.warning(f"MCP tool not found: tool_id={tool_id}")
        except Exception as e:
            logger.error(f"Failed to fetch MCP tool {tool_id}: {e}")
        return None

    # ── MCP execution (async) ────────────────────────────────────────────

    async def _execute_mcp_tool(
        self,
        tool_call_id: str,
        tool_id: str,
        tool_name: str,
        args: Dict[str, Any],
        producer: KafkaProducer,
    ) -> None:
        """Invoke an MCP tool via FastMCPClient and publish the result."""
        record = await self._fetch_mcp_tool_config(tool_id)
        if record is None:
            self.kafka_mgr.send_tool_response(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                args=args,
                result=f"MCP tool record not found for tool_id '{tool_id}'",
                status="error",
                producer=producer,
            )
            return

        mcp_config = record.get("mcp_config") or record.get("config") or {}
        if isinstance(mcp_config, str):
            mcp_config = json.loads(mcp_config)
        try:
            client = await MCPToolAdapter.create_mcp_client(mcp_config)
            async with client:
                raw_result = await client.call_tool(name=tool_name, arguments=args)
            result = _normalise_mcp_response(raw_result)
            self.kafka_mgr.send_tool_response(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                args=args,
                result=result,
                status="success",
                producer=producer,
            )
            logger.info(f"MCP tool OK: tool_call_id={tool_call_id}, tool={tool_name}")
        except Exception as e:
            logger.error(f"MCP tool FAIL: tool_call_id={tool_call_id}, tool={tool_name}, error={e}")
            self.kafka_mgr.send_tool_response(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                args=args,
                result=str(e),
                status="error",
                producer=producer,
            )

    # ── Single-request dispatch ─────────────────────────────────────────

    async def _dispatch_tool(
        self,
        req: Dict[str, Any],
        producer: KafkaProducer,
        thread_pool: ThreadPoolExecutor,
        loop: asyncio.AbstractEventLoop,
        semaphore: asyncio.Semaphore,
    ) -> None:
        """Dispatch a single tool request to the appropriate executor, then release the slot."""
        tool_call_id = req.get("tool_call_id", "unknown")
        tool_id = req.get("tool_id", "")
        tool_name = req.get("tool_name", "unknown")
        args = req.get("args", {})
        tool_version = req.get("tool_version", "v1")

        try:
            if tool_id.startswith("mcp_"):
                # MCP tools are async — run directly
                await self._execute_mcp_tool(tool_call_id, tool_id, tool_name, args, producer)
            else:
                # Python tools are sync — run in thread pool
                code_snippet = await self._fetch_python_tool_code(tool_id, tool_version)
                if code_snippet is None:
                    self.kafka_mgr.send_tool_response(
                        tool_call_id=tool_call_id, tool_name=tool_name,
                        args=args, result=f"No code found for tool_id '{tool_id}'",
                        status="error", producer=producer,
                    )
                    return

                await loop.run_in_executor(
                    thread_pool,
                    _process_python_request,
                    tool_call_id, tool_name, args, code_snippet, self.kafka_mgr, producer,
                )
        except Exception as e:
            logger.error(f"Tool dispatch failed: tool_call_id={tool_call_id}, error={e}")
        finally:
            semaphore.release()

    # ── Main loop ────────────────────────────────────────────────────────

    async def run(self) -> None:
        """
        Demand-based worker loop with semaphore backpressure.

        - Acquires a semaphore slot before each poll (backpressure).
        - Polls Kafka for one record at a time.
        - Spawns a fire-and-forget task that releases the slot when done.
        - Uses pause/resume to send heartbeats when all slots are busy.
        - Python tools run in a shared ThreadPoolExecutor.
        - MCP tools run as async coroutines.
        """
        consumer = self.kafka_mgr.get_consumer(
            topic=KafkaTopics.TOOL_REQUESTS.value,
            group_id=self.group_id,
            latest=False,
            auto_commit=True,
            max_poll_records=1,
        )
        producer = self.kafka_mgr.get_producer()
        thread_pool = ThreadPoolExecutor(max_workers=self.max_parallel)
        loop = asyncio.get_running_loop()

        semaphore = asyncio.Semaphore(self.max_parallel)
        active_tasks: set = set()

        logger.info(
            f"Tool worker started | group={self.group_id} | "
            f"topic={KafkaTopics.TOOL_REQUESTS.value} | "
            f"max_parallel={self.max_parallel} | demand-based polling"
        )

        try:
            while True:
                # Try to grab a slot (short timeout so we can heartbeat if busy)
                try:
                    await asyncio.wait_for(semaphore.acquire(), timeout=0.1)
                except asyncio.TimeoutError:
                    # All slots busy — pause consumer and heartbeat
                    assignment = consumer.assignment()
                    consumer.pause(*assignment)
                    logger.debug("Consumer paused - all slots busy, sending heartbeats")
                    empty_records = consumer.poll(timeout_ms=10)
                    if empty_records:
                        logger.info(f"Polled empty tool records: {empty_records}")
                    consumer.resume(*assignment)

                    await asyncio.sleep(0.2)
                    continue

                # Slot acquired — resume if paused and poll for a record
                logger.debug("Consumer resumed - slot available")

                records = consumer.poll(timeout_ms=self.poll_timeout_ms)

                if not records:
                    semaphore.release()
                    await asyncio.sleep(KAFKA_DEFAULTS.WORKER_IDLE_SLEEP_SECONDS)
                    continue

                # Process the first (only) record
                for _tp, messages in records.items():
                    for message in messages:
                        req = message.value
                        logger.info(f"Polled 1 tool request: tool_call_id={req.get('tool_call_id', 'unknown')}")
                        task = asyncio.create_task(
                            self._dispatch_tool(req, producer, thread_pool, loop, semaphore)
                        )
                        active_tasks.add(task)
                        task.add_done_callback(active_tasks.discard)
                        break
                    break

        except KeyboardInterrupt:
            logger.info("Worker interrupted, shutting down…")
        except asyncio.CancelledError:
            logger.info("Worker cancelled, shutting down…")
        finally:
            # Cancel all in-flight tasks and wait for them
            for t in active_tasks:
                t.cancel()
            if active_tasks:
                await asyncio.gather(*active_tasks, return_exceptions=True)
            thread_pool.shutdown(wait=True)
            consumer.close()
            producer.close()
            logger.info("Worker stopped")
