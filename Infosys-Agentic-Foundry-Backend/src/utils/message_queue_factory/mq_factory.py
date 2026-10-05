"""
Message Queue Factory
=====================
Creates the appropriate MessageQueueManager based on the MESSAGE_QUEUE_PROVIDER
environment variable.
"""
from typing import Optional

from src.config.constants import MessageQueueProvider
from src.utils.message_queue_factory.message_queue_manager import MessageQueueManager

from telemetry_wrapper import logger


def create_mq_manager(**kwargs) -> Optional[MessageQueueManager]:
    """
    Factory function that returns a concrete MessageQueueManager instance
    based on the MESSAGE_QUEUE_PROVIDER env var.

    Returns None when the provider is set to 'none' or left empty (MQ disabled).
    Kwargs are forwarded to the concrete manager constructor.
    """
    provider = MessageQueueProvider.from_env()

    if provider == MessageQueueProvider.NONE:
        logger.info("Message Queue Provider: None (disabled)")
        return None

    if provider == MessageQueueProvider.AZURE_SERVICE_BUS:
        from src.utils.message_queue_factory.azure_servicebus_manager import AzureServiceBusManager
        logger.info("Message Queue Provider: Azure Service Bus")
        return AzureServiceBusManager(**kwargs)
    else:
        from src.utils.message_queue_factory.kafka_manager import KafkaManager
        logger.info("Message Queue Provider: Kafka")
        return KafkaManager(**kwargs)
