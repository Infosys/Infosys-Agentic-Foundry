# ​© 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import Any, Dict, List, Optional, Union
import asyncio
import time
from datetime import datetime, timezone

from src.inference.centralized_agent_inference import CentralizedAgentInference
from src.utils.message_queue_factory.message_queue_manager import MessageQueueManager
from src.utils.message_queue_factory.mq_factory import create_mq_manager
from src.api.dependencies import ServiceProvider # The dependency provider
from src.inference.workflow_inference import WorkflowInference
from src.schemas import AgentInferenceRequest
from src.config.constants import KafkaDefaults, MQTopics, MessageQueueProvider

from telemetry_wrapper import logger as log, update_session_context


KAFKA_DEFAULTS = KafkaDefaults()


class AgentWorker:
    def __init__(self, 
        service_provider: ServiceProvider,
        bootstrap_servers: Union[str, List[str]] = None,
        group_id: str = KAFKA_DEFAULTS.CONSUMER_GROUP_AGENT_WORKERS,
        max_records_per_poll: int = KAFKA_DEFAULTS.CONSUMER_MAX_POLL_RECORDS,
        max_parallel_tasks: int = KAFKA_DEFAULTS.WORKER_MAX_PARALLEL_EXECUTIONS,
        poll_timeout_ms: int = KAFKA_DEFAULTS.CONSUMER_POLL_TIMEOUT_MS,
        ):
        self.service_provider = service_provider
        self.mq_manager = create_mq_manager(bootstrap_servers=bootstrap_servers) if bootstrap_servers else create_mq_manager()
        self.group_id = group_id
        self.max_records = max_records_per_poll
        self.max_parallel = max_parallel_tasks
        self.poll_timeout_ms = poll_timeout_ms
        
    async def _process_request(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single agent request and return the response.
        
        Args:
            request: The agent request data.
        Returns:
            A dictionary containing the response data.
        """
        start_time = time.monotonic()
        start_time_stamp = datetime.now(timezone.utc).replace(tzinfo=None)

        # Extract request data
        agent_call_id = data.get("agent_call_id")  # This is the task_id
        agent_id = data.get("agentic_application_id")
        # Session ID is already computed by the API (task_id + "_" + email)
        session_id = data.get("session_id")
        model_name = data.get("model_name")
        query = data.get("query")
        role = data.get("user_role", "User")
        department_name = data.get("department_name")
        user_name = data.get("username")
        
        # Get user_email from Kafka message (passed from API layer)
        user_email = data.get("user_email")
        
        if not user_email:
            # Fallback to worker email for testing scenarios
            from agent_worker.config import WORKER_USER_EMAIL
            user_email = WORKER_USER_EMAIL
            log.debug(f"Using worker email as fallback: {user_email}")
        else:
            log.info(f"Using user_email from Kafka message: {user_email}")
        
        # Set user_email in context variable so current_user_email.get() works
        from src.utils.secrets_handler import current_user_email
        current_user_email.set(user_email)

        # Open a per-request token accumulator so every LLM hook call during
        # this inference can append its record — enabling per-query token totals.
        from litellm_standalone_tracker import init_request_accumulator
        init_request_accumulator(session_id)

        # Set session context BEFORE any awaits so all sub-tasks spawned during
        # inference (which copy context at creation time) see the correct values.
        update_session_context(
            user_id=user_email,
            agent_id=agent_id,
            session_id=session_id,
            user_session=session_id,
            model_used=model_name,
            user_query=query,
            response="Processing...",
            call_category="agent_inference",
            request_id=agent_call_id  # Use agent_call_id as request correlation ID so all LLM calls in this inference are grouped
        )

        # Get task registry service for status updates
        task_registry_service = self.service_provider.get_task_registry_service()
        
        # Mark task as started/processing
        await task_registry_service.mark_task_started(task_id=agent_call_id)
        log.info(f"[{session_id}] Processing agent request: {agent_call_id}")

        try:
            response = {}
            # ---------------------------------------------------------
            # Check if this is a Workflow Call
            # ---------------------------------------------------------
            if agent_id.startswith("wf_") or agent_id.startswith("ppl_"):
                workflow_id = agent_id
                log.info(f"[{session_id}] Routing to workflow execution for workflow_id: {workflow_id}")
                
                # Get workflow inference service
                workflow_inference: WorkflowInference = self.service_provider.get_workflow_inference()
                
                response = None
                async for event in workflow_inference.run_workflow(
                    workflow_id=workflow_id,
                    session_id=session_id,
                    model_name=model_name,
                    input_query=query,
                    project_name=f"workflow_{workflow_id}",
                    reset_conversation=data.get("reset_conversation", False),
                    plan_verifier_flag=data.get("plan_verifier_flag", False),
                    is_plan_approved=data.get("is_plan_approved"),
                    plan_feedback=data.get("plan_feedback"),
                    tool_interrupt_flag=data.get("tool_verifier_flag", False),
                    tool_feedback=data.get("tool_feedback"),
                    context_flag=data.get("context_flag", False),
                    evaluation_flag=data.get("evaluation_flag", False),
                    validator_flag=data.get("validator_flag", False),
                    temperature=data.get("temperature") or 0.0,
                    role=str(role)
                ):
                    response = event
                
                end_time = time.monotonic()
                time_taken = end_time - start_time
                time_taken_ms = time_taken * 1000  # Convert to milliseconds
                log.info(f"[{session_id}] Workflow execution completed in {time_taken:.2f}s")
                
                # Mark task as completed in registry
                await task_registry_service.mark_task_completed(
                    task_id=agent_call_id,
                    response_time_ms=time_taken_ms
                )
                
                # Cleanup session context
                update_session_context(
                    agent_id='Unassigned', session_id='Unassigned', user_session='Unassigned',
                    model_used='Unassigned', user_query='Unassigned', response='Unassigned',
                    call_category='Unassigned', request_id='Unassigned'
                )
                
                return response
            
            # ---------------------------------------------------------
            # Regular Agent Inference (Non-Streaming)
            # ---------------------------------------------------------
            else:
                log.info(f"[{session_id}] Routing to agent inference for agent_id: {agent_id}")
                
                # Get inference service
                inference_service: CentralizedAgentInference = self.service_provider.get_centralized_agent_inference()
                
                # Build inference request from data
                inference_request = AgentInferenceRequest(
                    query=query,
                    agentic_application_id=agent_id,
                    session_id=session_id,
                    model_name=model_name,
                    reset_conversation=data.get("reset_conversation", False),
                    tool_verifier_flag=data.get("tool_verifier_flag", False),
                    plan_verifier_flag=data.get("plan_verifier_flag", False),
                    evaluation_flag=data.get("evaluation_flag", False),
                    validator_flag=data.get("validator_flag", False),
                    context_flag=data.get("context_flag", False),
                    file_context_management_flag=data.get("file_context_management_flag", False),
                    response_formatting_flag=data.get("response_formatting_flag", False),
                    temperature=data.get("temperature"),
                    framework_type=data.get("framework_type"),
                    tool_feedback=data.get("tool_feedback"),
                    is_plan_approved=data.get("is_plan_approved"),
                    plan_feedback=data.get("plan_feedback"),
                    mentioned_agentic_application_id=data.get("mentioned_agentic_application_id"),
                    interrupt_items=data.get("interrupt_items"),
                    uploaded_files=data.get("uploaded_files"),
                    enable_streaming_flag=False  # Worker processes non-streaming
                )
                
                # Run inference
                response = await anext(inference_service.run(
                    inference_request, 
                    role=role, 
                    department_name=department_name, 
                    user_name=user_name,
                    use_kafka_tool_worker=True
                ))
                
                end_time = time.monotonic()
                time_taken = end_time - start_time
                time_taken_ms = time_taken * 1000  # Convert to milliseconds
                
                last_message = dict()
                # Inject response time into the last message
                try:
                    if "error" not in response.keys():
                        last_message = response["executor_messages"][-1]
                        last_message["start_timestamp"] = start_time_stamp.isoformat()
                        last_message["response_time"] = time_taken
                    log.info(f"[{session_id}] Agent inference completed in {time_taken:.2f}s")
                except Exception as e:
                    log.error(f"[{session_id}] Failed to inject response time into last message: {e}, final response {response}")
                
                
                # Drain token accumulator and persist per-query token usage
                from litellm_standalone_tracker import get_and_clear_accumulator
                token_records = get_and_clear_accumulator(session_id)
                if token_records:
                    agent_name = token_records[0].get("agent_name") if token_records else None
                    await inference_service.update_token_usage_in_graph(
                        agent_id=agent_id,
                        session_id=session_id,
                        token_records=token_records,
                    )
                    if last_message:
                        last_message["token_usage"] = {
                            "prompt_tokens":     sum(r.get("prompt_tokens", 0)     for r in token_records),
                            "completion_tokens": sum(r.get("completion_tokens", 0) for r in token_records),
                            "total_tokens":      sum(r.get("total_tokens", 0)      for r in token_records),
                            "cached_tokens":     sum(r.get("cached_tokens", 0)     for r in token_records),
                            "total_cost":        sum(r.get("total_cost", 0.0)      for r in token_records),
                            "llm_calls":         token_records,
                        }
                    query_token_usage_repo = self.service_provider.get_query_token_usage_repo()
                    asyncio.create_task(query_token_usage_repo.insert(
                        session_id=session_id,
                        user_id=user_email,
                        agent_id=agent_id,
                        agent_name=agent_name,
                        query=query,
                        token_records=token_records,
                        department_name=department_name,
                    ))
                    log.info(
                        f"[{session_id}] Token usage persisted: "
                        f"{len(token_records)} LLM call(s), "
                        f"total_tokens={sum(r.get('total_tokens', 0) for r in token_records)}"
                    )

                # Mark task as completed in registry
                log.info(f"[{session_id}] About to mark the task as completed")
                if response.get("error") or response.get("errors"):
                    log.error(f"[{session_id}] Error in response: {response}")
                    raise ValueError(str(response.get("error") or response.get("errors")))

                log.info(f"[{session_id}] Actually marking the task as completed")

                await task_registry_service.mark_task_completed(
                    task_id=agent_call_id,
                    response_time_ms=time_taken_ms
                )
                
                # Cleanup session context
                update_session_context(
                    agent_id='Unassigned', session_id='Unassigned', user_session='Unassigned',
                    model_used='Unassigned', user_query='Unassigned', response='Unassigned',
                    call_category='Unassigned', request_id='Unassigned'
                )
                
                return response
                
        except Exception as e:
            log.error(f"[{session_id}] Agent/Workflow execution failed: {e}")
            
            # Mark task as failed in registry
            await task_registry_service.mark_task_failed(
                task_id=agent_call_id,
                error_message=str(e)
            )
            
            # Cleanup session context
            update_session_context(
                agent_id='Unassigned', session_id='Unassigned', user_session='Unassigned',
                model_used='Unassigned', user_query='Unassigned', response='Unassigned',
                call_category='Unassigned', request_id='Unassigned'
            )
            return {
                "status": "error",
                "error": str(e),
                "error_type": response.get("error_type") if response else "unknown",
                "agent_call_id": agent_call_id,
                "session_id": session_id
            }

    async def _finalize_cron_outcome(
        self,
        agent_call_id: str,
        success: bool,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Update scheduler history when a task originated from the cron dispatcher.

        Tasks produced by `src.inference.cron_scheduler_runner` use a `task_id`
        of the form `cron_<framework>_<uuid12>`. We piggy-back on the worker's
        normal completion/failure paths to record the actual execution outcome
        in `schedule_execution_history`. Any failure here is swallowed; this
        hook must never affect the primary agent flow.
        """
        if not agent_call_id or not agent_call_id.startswith("cron_"):
            return
        try:
            scheduler_service = self.service_provider.get_scheduler_service()
            await scheduler_service.finalize_worker_outcome(
                task_id=agent_call_id,
                success=success,
                error_message=error_message,
            )
        except Exception as exc:
            log.warning(
                f"Could not update scheduler history for task '{agent_call_id}': {exc}"
            )

    async def _process_and_publish(
        self,
        data: Dict[str, Any]
    ) -> None:
        """Process a single agent request and publish the response."""
        agent_call_id = data.get("agent_call_id", "unknown")
        try:
            response = await self._process_request(data)
            log.info(f"===========\n\n\n\n {response} \n\n\n\n ============")
            log.info(f"Agent request OK: agent_call_id={agent_call_id}")
            # Mirror the outcome into scheduler history for cron-triggered tasks.
            if isinstance(response, dict) and (response.get("error") or response.get("errors") or response.get("status") == "error"):
                err_text = str(response.get("error") or response.get("errors") or "Agent reported error")
                await self._finalize_cron_outcome(agent_call_id, success=False, error_message=err_text)
            else:
                await self._finalize_cron_outcome(agent_call_id, success=True)
        except Exception as e:
            log.error(f"Agent request FAIL: agent_call_id={agent_call_id}, error={e}", exc_info=True)
            try:
                task_registry_service = self.service_provider.get_task_registry_service()
                await task_registry_service.mark_task_failed(
                    task_id=agent_call_id,
                    error_message=str(e)
                )
                log.info(f"Marked task {agent_call_id} as failed in registry")
            except Exception as registry_err:
                log.error(f"Failed to mark task {agent_call_id} as failed in registry: {registry_err}")
            await self._finalize_cron_outcome(agent_call_id, success=False, error_message=str(e))

    async def _delayed_recovery(self) -> None:
        """
        Background task that waits for RECOVERY_RECHECK_MINUTES, then recovers
        tasks that were recently in 'processing' at startup but are now confirmed stuck.
        
        At startup, tasks < RECHECK_MINUTES old could be legitimately running.
        After waiting RECHECK_MINUTES, those tasks have had enough time to complete.
        If they're still 'processing', they're stuck.
        
        Window: started_at BETWEEN NOW()-2*RECHECK AND NOW()-RECHECK
        (same absolute window as the gap skipped at startup)
        """
        recheck_minutes = KAFKA_DEFAULTS.RECOVERY_RECHECK_MINUTES
        try:
            log.info(f"Recovery: Waiting {recheck_minutes} minutes before rechecking recent tasks...")
            await asyncio.sleep(recheck_minutes * 60)

            log.info("Recovery: Rechecking recent tasks now...")

            task_registry_service = self.service_provider.get_task_registry_service()
            result = await task_registry_service.recover_stuck_tasks(
                lookback_hours=KAFKA_DEFAULTS.RECOVERY_LOOKBACK_HOURS,
                offset_minutes=KAFKA_DEFAULTS.RECOVERY_RECHECK_MINUTES,
                mq_manager=self.mq_manager,
            )

            if result["recovered_count"] > 0:
                log.warning(
                    f"Recovery (delayed): {result['recovered_count']} stuck tasks recovered, "
                    f"{result.get('requeued_count', 0)} re-queued to Kafka"
                )
            else:
                log.info("Recovery (delayed): No stuck tasks found in recent window")
        except asyncio.CancelledError:
            log.info("Recovery background task cancelled")
        except Exception as e:
            log.error(f"Recovery background task failed: {e}")

    async def _run_task(self, data: Dict[str, Any], semaphore: asyncio.Semaphore) -> None:
        """Fire-and-forget wrapper: process one request then release the semaphore slot."""
        agent_call_id = data.get("agent_call_id", "unknown")
        try:
            await self._process_and_publish(data=data)
        except Exception as e:
            log.error(f"Task {agent_call_id} failed unexpectedly in _run_task: {e}", exc_info=True)
            try:
                task_registry_service = self.service_provider.get_task_registry_service()
                await task_registry_service.mark_task_failed(
                    task_id=agent_call_id,
                    error_message=f"Unhandled error in _run_task: {e}"
                )
                log.info(f"Marked task {agent_call_id} as failed in registry (from _run_task)")
            except Exception as registry_err:
                log.error(f"Failed to mark task {agent_call_id} as failed in registry: {registry_err}")
        finally:
            semaphore.release()

    async def _run_kafka(self) -> None:
        """
        Main worker loop with demand-based polling.
        
        - Acquires a semaphore slot before each poll (backpressure).
        - Polls Kafka for one record at a time.
        - Spawns a fire-and-forget task that releases the slot when done.
        - Uses pause/resume to send heartbeats when all slots are busy.
        """
        log.info(
            f"Agent worker starting | group={self.group_id} | "
            f"topic={MQTopics.AGENT_REQUESTS.value} | "
            f"max_parallel={self.max_parallel} | demand-based polling with pause/resume enabled"
        )

        # ============================================================
        # RECOVERY: Immediately recover old stuck tasks, schedule recheck for recent ones
        # ============================================================
        try:
            task_registry_service = self.service_provider.get_task_registry_service()

            # IMMEDIATE: Recover tasks stuck for > RECHECK_MINUTES
            # These have been 'processing' long enough to be confirmed stuck
            result = await task_registry_service.recover_stuck_tasks(
                lookback_hours=KAFKA_DEFAULTS.RECOVERY_LOOKBACK_HOURS,
                offset_minutes=KAFKA_DEFAULTS.RECOVERY_RECHECK_MINUTES,
                mq_manager=self.mq_manager,
            )

            if result["recovered_count"] > 0:
                log.warning(
                    f"Recovery (immediate): {result['recovered_count']} stuck tasks recovered, "
                    f"{result.get('requeued_count', 0)} re-queued to Kafka"
                )
            else:
                log.info("Recovery (immediate): No stuck tasks found")

            # DELAYED: Schedule recheck for tasks that were < RECHECK_MINUTES old at startup
            # After waiting RECHECK_MINUTES, if they're still 'processing', they're stuck
            asyncio.create_task(self._delayed_recovery())

        except Exception as e:
            log.error(f"Failed to initiate recovery: {e}")

        # Create the Kafka consumer
        # auto_commit=True: We rely on the task_registry DB for crash recovery
        # instead of manual offset commits, avoiding the out-of-order commit problem
        # when multiple internal workers process messages from the same partition.
        consumer = self.mq_manager.get_consumer(
            topic=MQTopics.AGENT_REQUESTS.value,
            group_id=self.group_id,
            latest=False,
            auto_commit=True,
            heartbeat_interval_ms=3000,
            session_timeout_ms=30000,
            max_poll_interval_ms=600000,
            max_poll_records=1,
        )

        # Semaphore controls max in-flight tasks (backpressure)
        semaphore = asyncio.Semaphore(self.max_parallel)

        # Track spawned tasks for graceful shutdown
        active_tasks: set = set()
        is_paused = False

        log.info(
            f"Kafka consumer started | group={self.group_id} | "
            f"topic={MQTopics.AGENT_REQUESTS.value} | "
            f"max_parallel={self.max_parallel}"
        )

        try:
            while True:
                # Try to grab a slot (short timeout so we can heartbeat if busy)
                try:
                    await asyncio.wait_for(semaphore.acquire(), timeout=0.1)
                except asyncio.TimeoutError:
                    # All slots busy — pause consumer and heartbeat
                    # Always call pause() (idempotent) to handle rebalances
                    # that may have assigned new unpaused partitions.
                    assignment = consumer.assignment()
                    consumer.pause(*assignment)
                    log.debug("Consumer paused - all slots busy, sending heartbeats")
                    empty_records = consumer.poll(timeout_ms=10)
                    if empty_records:
                        log.info(f"Polled empty agent records: {empty_records}")
                    consumer.resume(*assignment)

                    await asyncio.sleep(0.2)
                    continue

                # Slot acquired — resume if paused and poll for a record
                log.debug("Consumer resumed - slot available")

                records = consumer.poll(timeout_ms=self.poll_timeout_ms)

                if not records:
                    semaphore.release()
                    await asyncio.sleep(KAFKA_DEFAULTS.WORKER_IDLE_SLEEP_SECONDS)
                    continue

                # Log partition and offset for all polled records
                for _tp_log, msgs_log in records.items():
                    for msg_log in msgs_log:
                        log.info(f"Polled record: topic={msg_log.topic} partition={msg_log.partition} offset={msg_log.offset} agent_call_id={msg_log.value.get('agent_call_id', 'unknown')}")

                # Process the first (only) record
                for _tp, messages in records.items():
                    for message in messages:
                        data = message.value
                        log.info(f"Polled 1 agent request: {data.get('agent_call_id', 'unknown')}")
                        task = asyncio.create_task(self._run_task(data, semaphore))
                        active_tasks.add(task)
                        task.add_done_callback(active_tasks.discard)
                        break
                    break

        except KeyboardInterrupt:
            log.info("Agent worker interrupted, shutting down...")
        except asyncio.CancelledError:
            log.info("Agent worker cancelled, shutting down...")
        finally:
            # Cancel all in-flight tasks and wait for them
            for t in active_tasks:
                t.cancel()
            if active_tasks:
                await asyncio.gather(*active_tasks, return_exceptions=True)
            consumer.close()
            self.mq_manager.close()
            log.info("Agent worker stopped")

    async def _run_servicebus(self) -> None:
        """
        Azure Service Bus agent worker loop — competing consumers pattern.
        Uses a persistent receiver to avoid per-message connection overhead.
        """
        import json as _json
        from src.config.constants import AzureServiceBusDefaults

        sb_defaults = AzureServiceBusDefaults()
        semaphore = asyncio.Semaphore(self.max_parallel)
        active_tasks: set = set()
        loop = asyncio.get_running_loop()

        log.info(
            f"Agent worker started (Service Bus) | "
            f"queue={MQTopics.AGENT_REQUESTS.value} | "
            f"max_parallel={self.max_parallel}"
        )

        # Recovery
        try:
            task_registry_service = self.service_provider.get_task_registry_service()
            result = await task_registry_service.recover_stuck_tasks(
                lookback_hours=sb_defaults.RECOVERY_LOOKBACK_HOURS,
                offset_minutes=sb_defaults.RECOVERY_RECHECK_MINUTES,
                mq_manager=self.mq_manager,
            )
            if result["recovered_count"] > 0:
                log.warning(f"Recovery: {result['recovered_count']} stuck tasks recovered")
            asyncio.create_task(self._delayed_recovery())
        except Exception as e:
            log.error(f"Failed to initiate recovery: {e}")

        # Create persistent receiver (reused across iterations)
        recv_client, receiver = self.mq_manager.get_consumer(
            topic=MQTopics.AGENT_REQUESTS.value,
            max_wait_time=sb_defaults.MAX_WAIT_TIME_SECONDS,
        )
        log.info("Persistent Service Bus receiver created for agent requests")

        try:
            while True:
                try:
                    await asyncio.wait_for(semaphore.acquire(), timeout=0.1)
                except asyncio.TimeoutError:
                    await asyncio.sleep(0.2)
                    continue

                try:
                    messages = await loop.run_in_executor(
                        None,
                        lambda: receiver.receive_messages(
                            max_message_count=1,
                            max_wait_time=sb_defaults.MAX_WAIT_TIME_SECONDS,
                        ),
                    )

                    if not messages:
                        semaphore.release()
                        await asyncio.sleep(sb_defaults.WORKER_IDLE_SLEEP_SECONDS)
                        continue

                    for msg in messages:
                        try:
                            data = _json.loads(str(msg))
                            receiver.complete_message(msg)
                            log.info(f"Received agent request: agent_call_id={data.get('agent_call_id', 'unknown')}")
                            task = asyncio.create_task(self._run_task(data, semaphore))
                            active_tasks.add(task)
                            task.add_done_callback(active_tasks.discard)
                        except Exception as e:
                            log.error(f"Failed to process Service Bus message: {e}")
                            try:
                                receiver.complete_message(msg)
                            except Exception:
                                pass
                            semaphore.release()

                except Exception as e:
                    log.error(f"Service Bus receive error: {e}")
                    semaphore.release()
                    # Reconnect the persistent receiver
                    try:
                        receiver.close()
                        recv_client.close()
                    except Exception:
                        pass
                    try:
                        recv_client, receiver = self.mq_manager.get_consumer(
                            topic=MQTopics.AGENT_REQUESTS.value,
                            max_wait_time=sb_defaults.MAX_WAIT_TIME_SECONDS,
                        )
                        log.info("Reconnected Service Bus receiver for agent requests")
                    except Exception as reconn_err:
                        log.error(f"Failed to reconnect receiver: {reconn_err}")
                        await asyncio.sleep(sb_defaults.WORKER_IDLE_SLEEP_SECONDS)

        except KeyboardInterrupt:
            log.info("Agent worker interrupted, shutting down...")
        except asyncio.CancelledError:
            log.info("Agent worker cancelled, shutting down...")
        finally:
            for t in active_tasks:
                t.cancel()
            if active_tasks:
                await asyncio.gather(*active_tasks, return_exceptions=True)
            try:
                receiver.close()
                recv_client.close()
            except Exception:
                pass
            self.mq_manager.close()
            log.info("Agent worker (Service Bus) stopped")

    async def run(self) -> None:
        """
        Auto-select execution mode based on MESSAGE_QUEUE_PROVIDER env var.
        """
        provider = MessageQueueProvider.from_env()

        if provider == MessageQueueProvider.AZURE_SERVICE_BUS:
            log.info("Execution mode: AZURE SERVICE BUS")
            await self._run_servicebus()
            return

        log.info("Execution mode: KAFKA")
        await self._run_kafka()

