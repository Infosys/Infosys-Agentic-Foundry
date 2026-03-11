from kafka import KafkaProducer, KafkaConsumer
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError, UnknownTopicOrPartitionError
import json
import os
from dotenv import load_dotenv 
import threading
import time
import inspect
import uuid
import logging

load_dotenv()

# Configure logger
logger = logging.getLogger(__name__)

# Global storage for registered functions
registered_functions = {}

def register_function(func_name, func):
    """Register a function to be used as a tool"""
    registered_functions[func_name] = func
    logger.debug(f"Function '{func_name}' registered. Total registered: {len(registered_functions)}")

def get_tool_function(tool_name):
    """Get the registered tool function by name"""
    return registered_functions.get(tool_name, None)

def send_message_to_kafka_topic(topic_name, args_dict, session_id: str = None):
    """
    Send a message directly to a Kafka topic with arguments
    
    Args:
        topic_name (str): Name of the Kafka topic
        args_dict (dict): Dictionary of function arguments
        session_id (str): Session ID to track the request
    """
    try:
        producer = KafkaProducer(
            bootstrap_servers=os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092'),
            value_serializer=lambda x: json.dumps(x).encode('utf-8'),
            acks='all',  # Wait for all replicas to acknowledge
            retries=3,
            batch_size=16384,
            linger_ms=10
        )
        
        message = {
            'tool_name': topic_name,
            'args': args_dict,
            'session_id': session_id,
            'timestamp': time.time(),
            'message_id': str(uuid.uuid4()),
        }
        
        future = producer.send(topic_name, message)
        # Wait for the send to complete
        record_metadata = future.get(timeout=10)
        producer.flush()
        
        logger.info(f"Message sent to topic '{topic_name}' for session '{session_id}'")
        
        return True
        
    except Exception as e:
        logger.error(f"Error sending message to Kafka topic '{topic_name}': {e}")
        return False

def kafka_worker(topic_name):
    """Kafka worker that listens to a topic and executes tool logic"""
    logger.info(f"Kafka worker for '{topic_name}' started")
    
    # Use unique consumer group to avoid conflicts
    consumer_group = f'tool-workers-{topic_name}-{int(time.time())}'
    
    try:
        consumer = KafkaConsumer(
            topic_name,
            bootstrap_servers=os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092'),
            auto_offset_reset='latest',  # Start from latest messages
            enable_auto_commit=True,
            group_id=consumer_group,
            value_deserializer=lambda x: json.loads(x.decode('utf-8')),
            consumer_timeout_ms=1000,  # Check for messages every 1 second
            fetch_min_bytes=1,
            fetch_max_wait_ms=500
        )
        
        # Test if topic exists and is accessible (only show once)
        partitions = consumer.partitions_for_topic(topic_name)
        if not partitions:
            logger.warning(f"Topic '{topic_name}' not found or no partitions")
        
        message_count = 0
        consecutive_empty_polls = 0
        max_empty_polls = 600  # Run for 10 minutes of inactivity
        
        while consecutive_empty_polls < max_empty_polls:
            try:
                # Poll for messages
                messages = consumer.poll(timeout_ms=1000)
                
                if messages:
                    consecutive_empty_polls = 0
                    for topic_partition, records in messages.items():
                        for message in records:
                            message_count += 1
                            
                            try:
                                data = message.value
                                
                                tool_name = data.get('tool_name')
                                args = data.get('args', {})
                                session_id = data.get('session_id')
                                message_id = data.get('message_id', 'unknown')
                                
                                logger.debug(f"Processing message for tool '{tool_name}' with session: {session_id}")
                                
                                # Get the original function to execute
                                original_func = get_tool_function(tool_name)
                                
                                if original_func:
                                    # Clean up string arguments (remove extra quotes if present)
                                    cleaned_args = {}
                                    for key, value in args.items():
                                        if isinstance(value, str) and value.startswith('"') and value.endswith('"'):
                                            cleaned_args[key] = value[1:-1]
                                        else:
                                            cleaned_args[key] = value
                                    
                                    # Execute the original function
                                    result = original_func(**cleaned_args)
                                    logger.info(f"Function '{tool_name}' executed successfully for session '{session_id}'")
                                    
                                    # Send result to dynamic_results topic with session_id
                                    send_result_to_topic(tool_name, cleaned_args, result, session_id)
                                    
                                    
                                else:
                                    error_msg = f"Original function '{tool_name}' not found"
                                    logger.error(error_msg)
                                    send_result_to_topic(tool_name, args, f"ERROR: {error_msg}", session_id)
                                
                            except Exception as e:
                                logger.error(f"Error executing function: {e}")
                                
                                tool_name = data.get('tool_name', 'unknown') if 'data' in locals() else 'unknown'
                                args = data.get('args', {}) if 'data' in locals() else {}
                                session_id = data.get('session_id') if 'data' in locals() else None
                                send_result_to_topic(tool_name, args, f"ERROR: {str(e)}", session_id)
                else:
                    consecutive_empty_polls += 1
                
            except Exception as e:
                # Only log critical errors, not routine polling timeouts
                if "timeout" not in str(e).lower():
                    logger.error(f"Error in message polling for '{topic_name}': {e}")
                consecutive_empty_polls += 1
        
        # Only log shutdown message if we processed any messages
        if message_count > 0:
            logger.info(f"Worker for '{topic_name}' processed {message_count} messages and is shutting down")
        consumer.close()
        
    except Exception as e:
        logger.error(f"Kafka worker error for '{topic_name}': {e}")

def send_result_to_topic(tool_name, args, result, session_id: str = None):
    """Send execution result to dynamic_results topic"""
    try:
        producer = KafkaProducer(
            bootstrap_servers=os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092'),
            value_serializer=lambda x: json.dumps(x).encode('utf-8'),
            acks='all'
        )
        
        result_message = {
            'tool_name': tool_name,
            'args': args,
            'result': result,
            'session_id': session_id,
            'timestamp': time.time(),
            'result_id': str(uuid.uuid4())
        }
        
        future = producer.send('dynamic_results', result_message)
        record_metadata = future.get(timeout=10)
        producer.flush()
        
        logger.debug(f"Result sent to dynamic_results for session '{session_id}'")
        
    except Exception as e:
        logger.error(f"Error sending result to dynamic_results: {e}")

def results_listener():
    """Listen to dynamic_results topic and print results"""
    logger.info("Results listener started")
    
    consumer_group = f'results-listener-{int(time.time())}'
    
    try:
        consumer = KafkaConsumer(
            'dynamic_results',
            bootstrap_servers=os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092'),
            auto_offset_reset='latest',
            enable_auto_commit=True,
            group_id=consumer_group,
            value_deserializer=lambda x: json.loads(x.decode('utf-8')),
            consumer_timeout_ms=1000
        )
        
        result_count = 0
        consecutive_empty_polls = 0
        max_empty_polls = 600  # Run for 10 minutes of inactivity
        
        while consecutive_empty_polls < max_empty_polls:
            try:
                messages = consumer.poll(timeout_ms=1000)
                
                if messages:
                    consecutive_empty_polls = 0
                    for topic_partition, records in messages.items():
                        for message in records:
                            result_count += 1
                            
                            try:
                                data = message.value
                                
                                tool_name = data.get('tool_name')
                                args = data.get('args', {})
                                result = data.get('result')
                                session_id = data.get('session_id')
                                timestamp = data.get('timestamp')
                                result_id = data.get('result_id', 'unknown')
                                
                                logger.info(f"Result received - Tool: {tool_name}, Session: {session_id}")
                                
                            except Exception as e:
                                logger.error(f"Error processing result: {e}")
                else:
                    consecutive_empty_polls += 1
                    
            except Exception as e:
                # Only log non-timeout errors
                if "timeout" not in str(e).lower():
                    logger.error(f"Error in results polling: {e}")
                consecutive_empty_polls += 1
        
        consumer.close()
        
    except Exception as e:
        logger.error(f"Results listener error: {e}")

def start_results_listener():
    """Start the results listener in a separate thread"""
    results_thread = threading.Thread(target=results_listener, daemon=True)
    results_thread.start()
    return results_thread

async def listen_for_tool_response(session_id: str, tool_name: str = None, timeout_seconds: int = 300, request_start_time = None):
    """
    Async function to listen for tool response from dynamic_results topic.
    Filters messages by session_id, tool_name, and timestamp to get the correct tool response.
    
    Args:
        session_id (str): The session ID to filter results for
        tool_name (str): The tool name to filter results for (optional)
        timeout_seconds (int): Maximum time to wait for a response (default: 5 minutes)
        request_start_time: Unix timestamp (float), datetime object, or string - only messages after this time are considered
    
    Returns:
        str: The tool result or None if timeout
    """
    import asyncio
    import datetime
    from kafka import TopicPartition
    
    # Convert request_start_time to float timestamp
    if request_start_time is None:
        request_start_time = time.time() - 30  # Look back 30 seconds to catch recent messages
    elif isinstance(request_start_time, datetime.datetime):
        # Convert datetime object to Unix timestamp
        request_start_time = request_start_time.timestamp()
    elif isinstance(request_start_time, str):
        # Try parsing ISO format datetime string
        try:
            dt = datetime.datetime.fromisoformat(request_start_time.replace('Z', '+00:00'))
            request_start_time = dt.timestamp()
        except Exception:
            request_start_time = time.time() - 60
    else:
        # Ensure it's a float
        try:
            request_start_time = float(request_start_time)
        except (TypeError, ValueError):
            request_start_time = time.time() - 60
    
    logger.debug(f"Listening for tool response for session: {session_id}, tool: {tool_name}")
    
    # Use a FIXED consumer group so offsets are shared across all listeners
    # This ensures committed messages are not re-read by other listeners
    consumer_group = 'dynamic-results-consumers'
    
    try:
        consumer = KafkaConsumer(
            'dynamic_results',
            bootstrap_servers=os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092'),
            auto_offset_reset='earliest',  # Read from earliest to catch messages sent before listener started
            enable_auto_commit=False,
            group_id=consumer_group,
            value_deserializer=lambda x: json.loads(x.decode('utf-8')),
            consumer_timeout_ms=1000
        )
        
        listen_start_time = time.time()
        latest_matching_result = None
        latest_timestamp = 0
        
        while (time.time() - listen_start_time) < timeout_seconds:
            try:
                messages = consumer.poll(timeout_ms=1000)
                
                if messages:
                    for topic_partition, records in messages.items():
                        # Process messages in reverse order (latest first)
                        for message in reversed(records):
                            try:
                                data = message.value
                                
                                msg_session_id = data.get('session_id')
                                msg_tool_name = data.get('tool_name')
                                msg_timestamp = data.get('timestamp', 0)
                                result = data.get('result')
                                
                                # Filter by session_id, tool_name, AND timestamp
                                session_match = msg_session_id == session_id
                                tool_match = tool_name is None or msg_tool_name == tool_name
                                time_match = msg_timestamp >= request_start_time  # Only accept recent messages
                                
                                if session_match and tool_match and time_match:
                                    # Found a matching message - this is what we're looking for
                                    latest_timestamp = msg_timestamp
                                    latest_matching_result = result
                                    logger.debug(f"Found matching result for session '{session_id}', tool '{msg_tool_name}'")
                                    
                                    # Commit the specific offset to mark this message as consumed
                                    from kafka.structs import TopicPartition, OffsetAndMetadata
                                    tp = TopicPartition(topic='dynamic_results', partition=topic_partition.partition)
                                    # OffsetAndMetadata requires: offset, metadata, leader_epoch
                                    offsets = {tp: OffsetAndMetadata(message.offset + 1, '', -1)}
                                    consumer.commit(offsets=offsets)
                                    
                                    # Close consumer and return the result
                                    consumer.close()
                                    return str(latest_matching_result)
                                
                            except Exception as e:
                                logger.error(f"Error processing result: {e}")
                
                # Yield control to the event loop
                await asyncio.sleep(0.1)
                
            except Exception as e:
                if "timeout" not in str(e).lower():
                    logger.error(f"Error in results polling: {e}")
                await asyncio.sleep(0.1)
        
        # If we found a result during polling, return it
        if latest_matching_result is not None:
            consumer.close()
            return str(latest_matching_result)
        
        logger.warning(f"Timeout waiting for tool response for session: {session_id}, tool: {tool_name}")
        consumer.close()
        return None
        
    except Exception as e:
        logger.error(f"Listen for tool response error: {e}")
        return None

def create_kafka_topic(topic_name):
    """Create a Kafka topic"""
    kafka_bootstrap = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
    
    try:
        admin_client = KafkaAdminClient(
            bootstrap_servers=kafka_bootstrap,
            client_id='dynamic_kafka_app',
            request_timeout_ms=10000,  # 10 second timeout
            api_version_auto_timeout_ms=10000
        )
        
        topic = NewTopic(name=topic_name, num_partitions=1, replication_factor=1)
        admin_client.create_topics([topic])
        logger.info(f"Kafka topic '{topic_name}' created successfully")
        return True
    except TopicAlreadyExistsError:
        logger.debug(f"Topic '{topic_name}' already exists, using existing topic")
        return True
    except Exception as e:
        logger.error(f"Error creating topic '{topic_name}': {e}")
        return False

def delete_kafka_topic(topic_name):
    """Delete a Kafka topic"""
    try:
        admin_client = KafkaAdminClient(
            bootstrap_servers=os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092'),
            client_id='dynamic_kafka_app'
        )
        admin_client.delete_topics([topic_name], timeout_ms=10000)
        logger.info(f"Kafka topic '{topic_name}' deleted successfully")
        return True
    except UnknownTopicOrPartitionError:
        logger.debug(f"Topic '{topic_name}' doesn't exist, skipping deletion")
        return True
    except Exception as e:
        logger.error(f"Error deleting topic '{topic_name}': {e}")
        return False

def list_existing_topics():
    """List all existing Kafka topics"""
    try:
        admin_client = KafkaAdminClient(
            bootstrap_servers=os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092'),
            client_id='dynamic_kafka_app'
        )
        metadata = admin_client.list_topics()
        return list(metadata)
    except Exception as e:
        logger.error(f"Error listing topics: {e}")
        return []

def purge_dynamic_results_topic():
    """
    Purge all messages from the dynamic_results topic by deleting and recreating it.
    This clears all old tool responses from the queue.
    """
    topic_name = 'dynamic_results'
    logger.info(f"Purging all messages from '{topic_name}' topic")
    
    try:
        # Delete the topic
        if delete_kafka_topic(topic_name):
            time.sleep(2)  # Wait for deletion to complete
            # Recreate the topic
            if create_kafka_topic(topic_name):
                logger.info(f"Successfully purged '{topic_name}' topic")
                return True
        
        logger.error(f"Failed to purge '{topic_name}' topic")
        return False
    except Exception as e:
        logger.error(f"Error purging topic '{topic_name}': {e}")
        return False

def cleanup_all_topics(topic_list):
    """Clean up multiple topics with better error handling"""
    logger.info(f"Cleaning up {len(topic_list)} topics")
    
    success_count = 0
    for topic in topic_list:
        if delete_kafka_topic(topic):
            success_count += 1
        time.sleep(0.5)
    
    logger.info(f"Successfully cleaned up {success_count}/{len(topic_list)} topics")
    time.sleep(2)