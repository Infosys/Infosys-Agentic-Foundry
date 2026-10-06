"""
Azure Service Bus Manager
=========================
Implements the MessageQueueManager interface using Azure Service Bus queues.
Supports both connection-string and Azure AD (ClientSecretCredential) auth.
"""
import json
import time
import asyncio
from typing import Any, Dict, Optional, List

from src.utils.message_queue_factory.message_queue_manager import MessageQueueManager
from src.config.constants import MQTopics, AzureServiceBusDefaults, FrameworkType

from telemetry_wrapper import logger

_DEFAULTS = AzureServiceBusDefaults()


class AzureServiceBusManager(MessageQueueManager):
    """
    Message queue manager backed by Azure Service Bus.

    Auth priority:
      1. Connection string (AZURE_SERVICEBUS_CONNECTION_STRING)
      2. ClientSecretCredential (namespace + tenant_id + client_id + client_secret_id)
      3. DefaultAzureCredential (namespace only — uses Managed Identity, CLI, etc.)
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        namespace: Optional[str] = None,
        tenant_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ):
        self._connection_string = connection_string or _DEFAULTS.CONNECTION_STRING
        self._namespace = namespace or _DEFAULTS.NAMESPACE
        self._tenant_id = tenant_id or _DEFAULTS.TENANT_ID
        self._client_id = client_id or _DEFAULTS.CLIENT_ID
        self._client_secret = client_secret or _DEFAULTS.CLIENT_SECRET

        # Validate that we have at least one auth method
        if not self._connection_string and not self._namespace:
            raise ValueError(
                "Azure Service Bus requires either AZURE_SERVICEBUS_CONNECTION_STRING "
                "or AZURE_SERVICEBUS_NAMESPACE (with optional client credentials for "
                "ClientSecretCredential, otherwise DefaultAzureCredential is used)"
            )

        self._use_connection_string = bool(self._connection_string)
        self._client = None
        self._senders: Dict[str, Any] = {}
        self.ensure_topics_exist()
        self._init_persistent_client()

    # ------------------------------------------------------------------ #
    #  Persistent connection management
    # ------------------------------------------------------------------ #

    def _init_persistent_client(self):
        """Initialize the persistent ServiceBusClient and senders for publishing."""
        try:
            self._client = self._get_servicebus_client()
            for topic in MQTopics:
                self._senders[topic.value] = self._client.get_queue_sender(queue_name=topic.value)
            logger.info("Persistent Service Bus client and senders initialized")
        except Exception as e:
            logger.error(f"Failed to initialize persistent Service Bus client: {e}")
            self._client = None
            self._senders = {}

    def _get_sender(self, queue_name: str):
        """Get a cached sender for the given queue, recreating if needed."""
        if queue_name not in self._senders or self._senders[queue_name] is None:
            if self._client is None:
                self._init_persistent_client()
            if self._client:
                self._senders[queue_name] = self._client.get_queue_sender(queue_name=queue_name)
        return self._senders.get(queue_name)

    def close(self):
        """Close all persistent senders and the client connection. Call on server shutdown."""
        for queue_name, sender in self._senders.items():
            try:
                if sender:
                    sender.close()
            except Exception as e:
                logger.debug(f"Error closing sender for '{queue_name}': {e}")
        self._senders = {}
        try:
            if self._client:
                self._client.close()
        except Exception as e:
            logger.debug(f"Error closing Service Bus client: {e}")
        self._client = None
        logger.info("Persistent Service Bus connections closed")

    # ------------------------------------------------------------------ #
    #  Client factories
    # ------------------------------------------------------------------ #

    def _get_credential(self):
        """Return an Azure AD credential.
        
        Uses ClientSecretCredential if tenant/client/secret_id are all provided,
        otherwise falls back to DefaultAzureCredential (Managed Identity, CLI, etc.).
        """
        if self._tenant_id and self._client_id and self._client_secret:
            from azure.identity import ClientSecretCredential
            return ClientSecretCredential(
                tenant_id=self._tenant_id,
                client_id=self._client_id,
                client_secret=self._client_secret,
            )
        from azure.identity import DefaultAzureCredential
        # Pass managed_identity_client_id if AZURE_CLIENT_ID is set (without secret_id/tenant)
        # This hints DefaultAzureCredential to use a specific user-assigned managed identity.
        kwargs = {}
        if self._client_id:
            kwargs["managed_identity_client_id"] = self._client_id
        return DefaultAzureCredential(**kwargs)

    def _get_servicebus_client(self):
        """Return a ServiceBusClient (for send/receive)."""
        from azure.servicebus import ServiceBusClient
        if self._use_connection_string:
            return ServiceBusClient.from_connection_string(self._connection_string)
        return ServiceBusClient(
            fully_qualified_namespace=self._namespace,
            credential=self._get_credential(),
        )

    def _get_admin_client(self):
        """Return a ServiceBusAdministrationClient (for queue management)."""
        from azure.servicebus.management import ServiceBusAdministrationClient
        if self._use_connection_string:
            return ServiceBusAdministrationClient.from_connection_string(self._connection_string)
        return ServiceBusAdministrationClient(
            fully_qualified_namespace=self._namespace,
            credential=self._get_credential(),
        )

    # ------------------------------------------------------------------ #
    #  Topic/Queue Management
    # ------------------------------------------------------------------ #

    def ensure_topics_exist(self) -> None:
        """Create the standard IAF queues if they don't exist."""
        from azure.core.exceptions import ResourceExistsError
        try:
            admin = self._get_admin_client()
            for topic in MQTopics:
                try:
                    # TOOL_RESPONSES queue requires sessions for targeted receive
                    requires_session = (topic == MQTopics.TOOL_RESPONSES)
                    admin.create_queue(topic.value, requires_session=requires_session)
                    logger.info(f"Service Bus queue '{topic.value}' created (session={requires_session})")
                except ResourceExistsError:
                    logger.debug(f"Service Bus queue '{topic.value}' already exists")
                except Exception as e:
                    if "409" in str(e) or "already exists" in str(e).lower():
                        logger.debug(f"Service Bus queue '{topic.value}' already exists")
                    else:
                        logger.error(f"Failed to create queue '{topic.value}': {e}")
        except Exception as e:
            logger.error(f"Failed to connect to Service Bus admin: {e}")

    # ------------------------------------------------------------------ #
    #  Publish helpers
    # ------------------------------------------------------------------ #

    def _send_message(self, queue_name: str, message: Dict[str, Any], message_id: str = None, session_id: str = None) -> bool:
        """Send a single message to a queue using the persistent sender."""
        from azure.servicebus import ServiceBusMessage
        try:
            sender = self._get_sender(queue_name)
            if sender is None:
                logger.error(f"No sender available for '{queue_name}'")
                return False
            msg = ServiceBusMessage(
                json.dumps(message),
                message_id=message_id,
                session_id=session_id,
                subject=message.get("tool_call_id") or message.get("agent_call_id"),
            )
            sender.send_messages(msg)
            return True
        except Exception as e:
            logger.error(f"Failed to send message to '{queue_name}': {e}")
            # Connection may be stale — reset and retry once
            try:
                logger.info("Reconnecting persistent Service Bus client...")
                self.close()
                self._init_persistent_client()
                sender = self._get_sender(queue_name)
                if sender:
                    msg = ServiceBusMessage(
                        json.dumps(message),
                        message_id=message_id,
                        session_id=session_id,
                        subject=message.get("tool_call_id") or message.get("agent_call_id"),
                    )
                    sender.send_messages(msg)
                    return True
            except Exception as retry_err:
                logger.error(f"Retry also failed for '{queue_name}': {retry_err}")
            return False

    def send_tool_request(
        self,
        tool_call_id: str,
        tool_id: str,
        tool_name: str,
        args: Dict[str, Any],
        tool_version: str = "v1",
        **kwargs,
    ) -> bool:
        message = {
            "tool_call_id": tool_call_id,
            "tool_id": tool_id,
            "tool_name": tool_name,
            "args": args,
            "tool_version": tool_version,
            "timestamp": time.time(),
        }
        success = self._send_message(MQTopics.TOOL_REQUESTS.value, message, message_id=tool_call_id)
        if success:
            logger.info(f"Tool request sent: tool_call_id={tool_call_id}, tool={tool_name}")
        else:
            logger.error(f"Failed to send tool request: tool_call_id={tool_call_id}, tool={tool_name}")
        return success

    def send_tool_response(
        self,
        tool_call_id: str,
        tool_name: str,
        args: Dict[str, Any],
        result: Any,
        status: str = "success",
        **kwargs,
    ) -> bool:
        message = {
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "args": args,
            "result": result,
            "status": status,
            "timestamp": time.time(),
        }
        success = self._send_message(MQTopics.TOOL_RESPONSES.value, message, message_id=tool_call_id, session_id=tool_call_id)
        if success:
            logger.debug(f"Tool response sent: tool_call_id={tool_call_id}, status={status}")
        else:
            logger.error(f"Failed to send tool response: tool_call_id={tool_call_id}, status={status}")

    def send_agent_request(
        self,
        agent_call_id: str,
        agentic_application_id: str,
        session_id: str,
        model_name: str,
        query: str,
        user_role: str = "User",
        department_name: str = None,
        username: str = None,
        user_email: str = None,  # Add user_email parameter
        reset_conversation: bool = False,
        tool_verifier_flag: bool = False,
        plan_verifier_flag: bool = False,
        evaluation_flag: bool = False,
        validator_flag: bool = False,
        context_flag: bool = False,
        file_context_management_flag: bool = False,
        response_formatting_flag: bool = False,
        temperature: float = None,
        framework_type: FrameworkType = FrameworkType.LANGGRAPH.value,
        tool_feedback: Any = None,
        is_plan_approved: bool = None,
        plan_feedback: str = None,
        mentioned_agentic_application_id: str = None,
        interrupt_items: Any = None,
        uploaded_files: List[str] = None,
        execution_mode: str = None,
        **kwargs,
    ) -> bool:
        message = {
            "agent_call_id": agent_call_id,
            "agentic_application_id": agentic_application_id,
            "session_id": session_id,
            "model_name": model_name,
            "query": query,
            "user_role": user_role,
            "department_name": department_name,
            "username": username,
            "user_email": user_email,  # Include user_email in message
            "reset_conversation": reset_conversation,
            "tool_verifier_flag": tool_verifier_flag,
            "plan_verifier_flag": plan_verifier_flag,
            "evaluation_flag": evaluation_flag,
            "validator_flag": validator_flag,
            "context_flag": context_flag,
            "file_context_management_flag": file_context_management_flag,
            "response_formatting_flag": response_formatting_flag,
            "temperature": temperature,
            "framework_type": framework_type,
            "tool_feedback": tool_feedback,
            "is_plan_approved": is_plan_approved,
            "plan_feedback": plan_feedback,
            "mentioned_agentic_application_id": mentioned_agentic_application_id,
            "interrupt_items": interrupt_items,
            "uploaded_files": uploaded_files,
            "execution_mode": execution_mode,
            "timestamp": time.time(),
        }
        success = self._send_message(MQTopics.AGENT_REQUESTS.value, message, message_id=agent_call_id)
        if success:
            logger.debug(f"Agent request sent: agent_call_id={agent_call_id}")
        return success

    # ------------------------------------------------------------------ #
    #  Consumer / Receiver
    # ------------------------------------------------------------------ #

    def get_consumer(self, topic: str, **kwargs) -> Any:
        """
        Return a ServiceBusReceiver for the given queue.
        The caller must manage the client lifecycle.
        Returns a tuple of (client, receiver) — caller must close both.
        """
        client = self._get_servicebus_client()
        receiver = client.get_queue_receiver(
            queue_name=topic,
            max_wait_time=kwargs.get("max_wait_time", _DEFAULTS.MAX_WAIT_TIME_SECONDS),
            prefetch_count=kwargs.get("prefetch_count", _DEFAULTS.PREFETCH_COUNT),
        )
        return (client, receiver)

    def create_response_consumer(self) -> Any:
        """
        Create a ServiceBusClient for receiving tool responses.
        The session-based receiver is created inside collect_responses.
        """
        return self._get_servicebus_client()

    async def collect_responses(
        self,
        consumer: Any,
        tool_call_id: str,
        timeout_seconds: int = _DEFAULTS.LISTENER_DEFAULT_TIMEOUT,
    ) -> Optional[Dict[str, Any]]:
        """
        Wait for the response matching the given tool_call_id using a
        session-based receiver. Only receives messages from the session
        matching the tool_call_id, so no message stealing is possible.
        """
        from azure.servicebus import ServiceBusClient
        result: Optional[Dict[str, Any]] = None
        client: ServiceBusClient = consumer

        deadline = time.time() + timeout_seconds
        loop = asyncio.get_event_loop()

        logger.debug(f"Listening for tool_call_id={tool_call_id} on Service Bus (session-based)")

        receiver = None
        try:
            receiver = client.get_queue_receiver(
                queue_name=MQTopics.TOOL_RESPONSES.value,
                session_id=tool_call_id,
                max_wait_time=_DEFAULTS.MAX_WAIT_TIME_SECONDS,
            )
            while result is None and time.time() < deadline:
                remaining = max(1, int(deadline - time.time()))
                messages = await loop.run_in_executor(
                    None,
                    lambda: receiver.receive_messages(
                        max_message_count=1,
                        max_wait_time=min(remaining, _DEFAULTS.MAX_WAIT_TIME_SECONDS),
                    ),
                )

                for msg in messages:
                    try:
                        data: dict = json.loads(str(msg))
                        result = data
                        receiver.complete_message(msg)
                        logger.info(f"Response received: tool_call_id={tool_call_id}, status={data.get('status')}")
                    except Exception as e:
                        logger.warning(f"Failed to process response message: {e}")
                        try:
                            receiver.complete_message(msg)
                        except Exception:
                            pass

                if result is None and not messages:
                    await asyncio.sleep(_DEFAULTS.LISTENER_POLL_INTERVAL)
        except Exception as e:
            logger.error(f"Error collecting response for tool_call_id={tool_call_id}: {e}")
        finally:
            try:
                if receiver:
                    receiver.close()
            except Exception:
                pass

        if result is None:
            logger.warning(f"Timeout: tool_call_id={tool_call_id} not received")

        return result
