"""
Message Queue Manager — Abstract Base Class
============================================
Defines the contract that all MQ providers (Kafka, Azure Service Bus, etc.)
must implement.  Code that publishes or consumes messages should depend on
this interface, not on a concrete provider.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union


class MessageQueueManager(ABC):
    """
    Abstract base class for message queue managers.
    All providers must implement these methods.
    """

    @abstractmethod
    def ensure_topics_exist(self) -> None:
        """Create the standard topics/queues if they don't exist."""
        ...

    @abstractmethod
    def send_tool_request(
        self,
        tool_call_id: str,
        tool_id: str,
        tool_name: str,
        args: Dict[str, Any],
        tool_version: str = "v1",
        **kwargs,
    ) -> bool:
        """Publish a tool call request."""
        ...

    @abstractmethod
    def send_tool_response(
        self,
        tool_call_id: str,
        tool_name: str,
        args: Dict[str, Any],
        result: Any,
        status: str = "success",
        **kwargs,
    ) -> bool:
        """Publish a tool execution result."""
        ...

    @abstractmethod
    def send_agent_request(
        self,
        agent_call_id: str,
        agentic_application_id: str,
        session_id: str,
        model_name: str,
        query: str,
        **kwargs,
    ) -> bool:
        """Publish an agent inference request."""
        ...

    @abstractmethod
    def get_consumer(self, topic: str, **kwargs) -> Any:
        """
        Return a consumer/receiver for the given topic/queue.
        The returned object is provider-specific.
        """
        ...

    @abstractmethod
    def create_response_consumer(self) -> Any:
        """
        Create a consumer/receiver optimized for listening to tool responses.
        Must be called BEFORE publishing requests to avoid race conditions.
        """
        ...

    @abstractmethod
    async def collect_responses(
        self,
        consumer: Any,
        tool_call_id: str,
        timeout_seconds: int = 300,
    ) -> Optional[Dict[str, Any]]:
        """
        Wait for the response matching the given tool_call_id on the consumer.
        Returns the response dict, or None if timeout.
        """
        ...

    def close(self) -> None:
        """
        Close any persistent connections held by this manager.
        Called during application shutdown. Default is no-op.
        """
        pass
