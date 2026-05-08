from kafka import KafkaProducer, KafkaConsumer
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError, UnknownTopicOrPartitionError
from kafka.structs import OffsetAndMetadata, TopicPartition
import json
import uuid
import time
import logging
from typing import Union, List, Optional, Dict, Any

from src.config.constants import KafkaDefaults, KafkaTopics, FrameworkType

from telemetry_wrapper import logger

KAFKA_DEFAULTS = KafkaDefaults()


class KafkaManager:
    """
    Centralized manager for Kafka producer, consumer, and admin client instances.
    Handles topic management, message publishing, and consumer creation.
    """

    def __init__(self, bootstrap_servers: Union[str, List[str]] = None):
        """
        Args:
            bootstrap_servers: Kafka broker address(es).
                - str: single broker e.g. "localhost:9092"
                - list: multiple brokers e.g. ["broker1:9092", "broker2:9092"]
                Defaults to KAFKA_BOOTSTRAP_SERVERS env var or "localhost:9092".
        """
        if bootstrap_servers is None:
            bootstrap_servers = KAFKA_DEFAULTS.BOOTSTRAP_SERVERS
        self._bootstrap_servers = bootstrap_servers
        self.ensure_topics_exist()

    # ------------------------------------------------------------------ #
    #  Admin Client
    # ------------------------------------------------------------------ #

    def get_admin_client(self, client_id: str = "iaf-kafka-admin", **kwargs) -> KafkaAdminClient:
        return KafkaAdminClient(
            bootstrap_servers=self._bootstrap_servers,
            client_id=client_id,
            **kwargs,
        )

    # ------------------------------------------------------------------ #
    #  Producer
    # ------------------------------------------------------------------ #

    def get_producer(
        self,
        acks: str = KAFKA_DEFAULTS.PRODUCER_ACKS,
        retries: int = KAFKA_DEFAULTS.PRODUCER_RETRIES,
        batch_size: int = KAFKA_DEFAULTS.PRODUCER_BATCH_SIZE,
        linger_ms: int = KAFKA_DEFAULTS.PRODUCER_LINGER_MS,
        value_serializer=None,
        **kwargs,
    ) -> KafkaProducer:
        if value_serializer is None:
            value_serializer = lambda x: json.dumps(x).encode("utf-8")
        return KafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            value_serializer=value_serializer,
            acks=acks,
            retries=retries,
            batch_size=batch_size,
            linger_ms=linger_ms,
            **kwargs,
        )

    # ------------------------------------------------------------------ #
    #  Consumer
    # ------------------------------------------------------------------ #

    def get_consumer(
        self,
        topic: str,
        group_id: str = None,
        auto_generate_group_id: bool = False,
        latest: bool = False,
        auto_commit: bool = True,
        max_poll_records: int = KAFKA_DEFAULTS.CONSUMER_MAX_POLL_RECORDS,
        value_deserializer=None,
        **kwargs,
    ) -> KafkaConsumer:
        """
        Create a KafkaConsumer instance.

        Args:
            topic: Topic to subscribe to.
            group_id: Explicit consumer group id. Takes priority over auto_generate_group_id.
            auto_generate_group_id: If True and group_id is None, generates a UUID-based group id.
            latest: If True, auto_offset_reset='latest'; otherwise 'earliest'.
            auto_commit: enable_auto_commit flag.
            max_poll_records: max_poll_records passed to consumer.
            value_deserializer: Custom deserializer. Defaults to JSON.
        """
        if group_id is None:
            group_id = f"consumer-{uuid.uuid4().hex[:12]}" if auto_generate_group_id else None

        if value_deserializer is None:
            value_deserializer = lambda x: json.loads(x.decode("utf-8"))

        return KafkaConsumer(
            topic,
            bootstrap_servers=self._bootstrap_servers,
            auto_offset_reset="latest" if latest else "earliest",
            enable_auto_commit=auto_commit,
            group_id=group_id,
            max_poll_records=max_poll_records,
            value_deserializer=value_deserializer,
            **kwargs,
        )

    # ------------------------------------------------------------------ #
    #  Topic Management
    # ------------------------------------------------------------------ #

    def create_topic(
        self,
        topic_name: str,
        num_partitions: int = KAFKA_DEFAULTS.DEFAULT_NUM_PARTITIONS,
        replication_factor: int = KAFKA_DEFAULTS.DEFAULT_REPLICATION_FACTOR,
    ) -> bool:
        try:
            admin = self.get_admin_client()
            new_topic = NewTopic(
                name=topic_name,
                num_partitions=num_partitions,
                replication_factor=replication_factor,
            )
            admin.create_topics([new_topic])
            logger.info(f"Topic '{topic_name}' created (partitions={num_partitions})")
            admin.close()
            return True
        except TopicAlreadyExistsError:
            logger.debug(f"Topic '{topic_name}' already exists")
            return True
        except Exception as e:
            logger.error(f"Failed to create topic '{topic_name}': {e}")
            return False

    def delete_topic(self, topic_name: str) -> bool:
        try:
            admin = self.get_admin_client()
            admin.delete_topics([topic_name], timeout_ms=10000)
            admin.close()
            logger.info(f"Topic '{topic_name}' deleted")
            return True
        except UnknownTopicOrPartitionError:
            logger.debug(f"Topic '{topic_name}' does not exist")
            return True
        except Exception as e:
            logger.error(f"Failed to delete topic '{topic_name}': {e}")
            return False

    def list_topics(self) -> List[str]:
        try:
            admin = self.get_admin_client()
            topics = list(admin.list_topics())
            admin.close()
            return topics
        except Exception as e:
            logger.error(f"Failed to list topics: {e}")
            return []

    def ensure_topics_exist(self) -> None:
        """Create the standard tool_requests , tool_responses and agent_requests topics if they don't exist."""
        for topic in KafkaTopics:
            if topic.value == KafkaTopics.AGENT_REQUESTS.value:
                # Create AGENT_REQUESTS with more partitions for better scalability
                self.create_topic(topic.value, num_partitions=KAFKA_DEFAULTS.AGENT_REQUESTS_NUM_PARTITIONS)
            else:
                self.create_topic(topic.value)

    # ------------------------------------------------------------------ #
    #  Publish helpers
    # ------------------------------------------------------------------ #

    def send_tool_request(
        self,
        tool_call_id: str,
        tool_id: str,
        tool_name: str,
        args: Dict[str, Any],
        producer: KafkaProducer = None,
        tool_version: str = "v1",
    ) -> bool:
        """
        Publish a tool call request to the TOOL_REQUESTS topic.

        Args:
            tool_call_id: Unique id for this tool call (usually from the LLM).
            tool_id: Database primary key of the tool (prefix "mcp_" for MCP tools).
            tool_name: Name of the tool to execute.
            args: Dictionary of arguments for the tool.
            producer: Optional reusable producer instance.
            tool_version: Version of the tool to execute (e.g., 'v1', 'v2').
        """
        _producer = producer or self.get_producer()
        message = {
            "tool_call_id": tool_call_id,
            "tool_id": tool_id,
            "tool_name": tool_name,
            "args": args,
            "tool_version": tool_version,
            "timestamp": time.time(),
        }
        try:
            future = _producer.send(
                KafkaTopics.TOOL_REQUESTS.value,
                key=tool_call_id.encode("utf-8"),
                value=message,
            )
            future.get(timeout=10)
            _producer.flush()
            logger.info(f"Tool request sent: tool_call_id={tool_call_id}, tool={tool_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to send tool request (tool_call_id={tool_call_id}): {e}")
            return False

    def send_tool_response(
        self,
        tool_call_id: str,
        tool_name: str,
        args: Dict[str, Any],
        result: Any,
        status: str = "success",
        producer: KafkaProducer = None,
    ) -> bool:
        """
        Publish a tool execution result to the TOOL_RESPONSES topic.
        """
        _producer = producer or self.get_producer()
        message = {
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "args": args,
            "result": result,
            "status": status,
            "timestamp": time.time(),
        }
        try:
            future = _producer.send(
                KafkaTopics.TOOL_RESPONSES.value,
                key=tool_call_id.encode("utf-8"),
                value=message,
            )
            future.get(timeout=10)
            _producer.flush()
            logger.debug(f"Tool response sent: tool_call_id={tool_call_id}, status={status}")
            return True
        except Exception as e:
            logger.error(f"Failed to send tool response (tool_call_id={tool_call_id}): {e}")
            return False
        
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
        producer: KafkaProducer = None,
    ) -> bool:
        """
        Publish an agent inference request to the AGENT_REQUESTS topic.
        """
        _producer = producer or self.get_producer()
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
            "timestamp": time.time(),
        }
        try:
            future = _producer.send(
                KafkaTopics.AGENT_REQUESTS.value,
                key=agent_call_id.encode("utf-8"),
                value=message,
            )
            future.get(timeout=10)
            _producer.flush()
            logger.debug(f"Agent request sent: agent_call_id={agent_call_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to send agent request (agent_call_id={agent_call_id}): {e}")
            return False
