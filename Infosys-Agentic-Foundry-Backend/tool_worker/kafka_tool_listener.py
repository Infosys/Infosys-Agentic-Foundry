import asyncio
import time
from typing import Optional, Dict, Any, List, Union

from kafka import KafkaConsumer

from src.config.constants import KafkaDefaults, KafkaTopics
from src.utils.kafka_manager import KafkaManager

from telemetry_wrapper import logger

KAFKA_DEFAULTS = KafkaDefaults()


def create_response_consumer(
    kafka_mgr: KafkaManager,
) -> KafkaConsumer:
    """
    Create a Kafka consumer subscribed to the TOOL_RESPONSES topic.

    Uses ``group_id=None`` (no consumer group) so there is nothing to
    clean up afterwards, and ``auto_offset_reset='latest'`` so only
    messages produced **after** this consumer is ready are visible.

    The caller **must** invoke this BEFORE publishing any tool requests
    to avoid the race condition where a response arrives before the
    consumer is subscribed.

    A ``poll(timeout_ms=3)`` forces the metadata fetch and partition
    assignment so the consumer is ready to receive messages immediately.

    Returns:
        A ready-to-poll KafkaConsumer instance. The caller is responsible
        for closing it when done.
    """
    consumer = kafka_mgr.get_consumer(
        topic=KafkaTopics.TOOL_RESPONSES.value,
        group_id=None,               # no consumer group — nothing to clean up
        auto_generate_group_id=False,
        latest=True,
        auto_commit=False,           # no group → auto-commit is meaningless
    )

    # Force metadata fetch + partition assignment
    consumer.poll(timeout_ms=3)

    logger.debug(f"Response consumer ready on {KafkaTopics.TOOL_RESPONSES.value} (group_id=None)")
    return consumer


async def collect_responses(
    consumer: KafkaConsumer,
    tool_call_ids: Union[str, List[str]],
    timeout_seconds: int = KAFKA_DEFAULTS.LISTENER_DEFAULT_TIMEOUT,
    poll_timeout_ms: int = KAFKA_DEFAULTS.LISTENER_POLL_TIMEOUT_MS,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Poll an already-created consumer until responses for every requested
    ``tool_call_id`` have been collected, or the timeout expires.

    Args:
        consumer: A KafkaConsumer returned by :func:`create_response_consumer`.
        tool_call_ids: One or more tool_call_id strings to wait for.
        timeout_seconds: Max seconds to wait before returning partial results.
        poll_timeout_ms: Kafka consumer poll timeout per iteration.

    Returns:
        Dict mapping each tool_call_id to its response dict
        (keys: tool_call_id, tool_name, args, result, status, timestamp),
        or ``None`` for ids that were not received before timeout.
    """
    if isinstance(tool_call_ids, str):
        tool_call_ids = [tool_call_ids]

    pending = set(tool_call_ids)
    results: Dict[str, Optional[Dict[str, Any]]] = {tid: None for tid in tool_call_ids}

    logger.debug(
        f"Listening for {len(pending)} tool_call_id(s) on "
        f"{KafkaTopics.TOOL_RESPONSES.value}"
    )

    loop = asyncio.get_event_loop()
    deadline = time.time() + timeout_seconds
    try:
        while pending and time.time() < deadline:
            records = await loop.run_in_executor(
                None, lambda: consumer.poll(timeout_ms=poll_timeout_ms)
            )

            for _tp, messages in records.items():
                for message in messages:
                    data = message.value
                    msg_id = data.get("tool_call_id")
                    if msg_id in pending:
                        results[msg_id] = data
                        pending.discard(msg_id)
                        logger.info(
                            f"Response received: tool_call_id={msg_id}, "
                            f"status={data.get('status')} "
                            f"({len(pending)} still pending)"
                        )
                        if not pending:
                            break
                if not pending:
                    break

            # Yield to event loop so other coroutines can run
            await asyncio.sleep(0.05)

        if pending:
            logger.warning(
                f"Timeout ({timeout_seconds}s): {len(pending)} id(s) not received: "
                f"{pending}"
            )

        return results

    except Exception as e:
        logger.error(f"Error listening for tool responses: {e}")
        return results
    finally:
        try:
            consumer.close()
        except Exception:
            pass

