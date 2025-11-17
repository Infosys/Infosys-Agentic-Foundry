# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import re
import ast
import json
from typing import List, Dict, Union, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timedelta

from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, ChatMessage
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from sentence_transformers import SentenceTransformer, util
from sentence_transformers import CrossEncoder

from src.models.model_service import ModelService
from src.database.services import ChatService, ToolService, AgentService, FeedbackLearningService, EvaluationService, ConsistencyService
from src.prompts.prompts import FORMATTER_PROMPT
from telemetry_wrapper import logger as log

# Import the Redis-PostgreSQL manager
from src.database.redis_postgres_manager import RedisPostgresManager, TimedRedisPostgresManager, create_manager_from_env, create_timed_manager_from_env
from src.utils.secrets_handler import current_user_email

# Initialize the global manager
_global_manager = None

async def get_global_manager():
    """Get or create the global RedisPostgresManager instance (async)"""
    global _global_manager
    if _global_manager is None and RedisPostgresManager is not None:
        try:
            base_manager = await create_manager_from_env()
            _global_manager = TimedRedisPostgresManager(base_manager, time_threshold_minutes=15)
            log.info("Global TimedRedisPostgresManager initialized successfully")
        except Exception as e:
            log.error(f"Failed to initialize TimedRedisPostgresManager: {e}")
            _global_manager = None
    return _global_manager

class InferenceUtils:
    """
    Utility class providing static methods for common inference-related tasks
    like JSON repair, output parsing, and message formatting.
    """

    def __init__(
        self,
        chat_service: ChatService,
        tool_service: ToolService,
        agent_service: AgentService,
        model_service: ModelService,
        feedback_learning_service: FeedbackLearningService,
        evaluation_service: EvaluationService,
        consistency_service:ConsistencyService,
        embedding_model: SentenceTransformer,
        cross_encoder: CrossEncoder
    ):
        # Getting all required services for Inference
        self.chat_service = chat_service
        self.tool_service = tool_service
        self.agent_service = agent_service
        self.model_service = model_service
        self.feedback_learning_service = feedback_learning_service
        self.evaluation_service = evaluation_service
        self.consistency_service = consistency_service
        self.embedding_model = embedding_model
        self.cross_encoder = cross_encoder

    @staticmethod
    async def force_persistence():
        """Force immediate persistence of cached data to PostgreSQL"""
        manager = await get_global_manager()
        if manager:
            try:
                await manager.force_persistence()
                log.info("Forced persistence to PostgreSQL completed successfully")
                return True
            except Exception as e:
                log.error(f"Error during forced persistence: {e}")
                return False
        else:
            log.warning("Manager not available, cannot force persistence")
            return False

    @staticmethod
    async def get_cache_stats():
        """Get current cache statistics"""
        manager = await get_global_manager()
        if manager:
            try:
                return await manager.base_manager.get_cache_stats()
            except Exception as e:
                log.error(f"Error getting cache stats: {e}")
                return {}
        return {}


    @staticmethod
    async def json_repair_exception_llm(incorrect_json: str, exception: Exception, llm: Any) -> Dict[str, Any] | str:
        """
        Attempts to repair an incorrect JSON response using an LLM.

        Args:
            incorrect_json (str): The incorrect JSON response.
            exception (Exception): The exception raised when parsing the JSON.
            llm (LLM): The LLM to use for repairing the JSON.

        Returns:
            dict or str: The repaired JSON response as a dictionary or string.
            If the LLM fails to repair the JSON, the original incorrect JSON is returned.
        """
        class CorrectedJSON(BaseModel):
            """
            Represents a corrected JSON object.

            Attributes:
                repaired_json (Dict): The repaired JSON object.
            """
            repaired_json: Dict = Field(description="Repaired JSON Object")
        json_correction_parser = JsonOutputParser(pydantic_object=CorrectedJSON)
        json_repair_template = """JSON Response to repair:
{json_response}

Exception Raised:
{exception}

Please review and fix the JSON response above based on the exception provided. Return your corrected JSON as an object with the key "repaired_json":
```json
{{
    "repaired_json": <your_corrected_json>
}}
```
"""
        try:
            try:
                json_repair_prompt = PromptTemplate.from_template(json_repair_template, partial_variables={"format_instructions": json_correction_parser.get_format_instructions()})
                json_repair_chain = json_repair_prompt | llm | json_correction_parser
                repaired_json = await json_repair_chain.ainvoke({'json_response': incorrect_json, 'exception': exception})
                data = repaired_json['repaired_json']
                if isinstance(data, dict):
                    return data
                else:
                    try:
                        return json.loads(data)
                    except Exception as e0:
                        try:
                            return ast.literal_eval(data)
                        except Exception as e:

                            return data
            except Exception as e1:
                json_repair_prompt = PromptTemplate.from_template(json_repair_template)
                json_repair_chain = json_repair_prompt | llm | StrOutputParser()
                repaired_json = await json_repair_chain.ainvoke({'json_response': incorrect_json, 'exception': exception}).strip()
                repaired_json = repaired_json.replace('```json', '').replace('```', '')
                try:
                    try:
                        repaired_json_response = json.loads(repaired_json)
                    except Exception as e2:

                        repaired_json_response = ast.literal_eval(repaired_json)
                    return repaired_json_response['repaired_json']
                except Exception as e3:

                    return repaired_json
        except Exception as e4:
            return incorrect_json

    @staticmethod
    async def output_parser(llm: Any, chain_1: Any, chain_2: Any, invocation_input: Dict[str, Any], error_return_key: str = "Error") -> Dict[str, Any]:
        """
        Parses the output of a chain invocation, attempting to handle errors gracefully.
        """
        try:
            formatted_response = await chain_1.ainvoke(invocation_input)
        except Exception as e:
            try:
                formatted_response = await chain_2.ainvoke(invocation_input)
                formatted_response = formatted_response.replace("```json", "").replace("```", "").replace('AI:', '').strip()
                try:
                    formatted_response = json.loads(formatted_response)
                except Exception as e:
                    try:
                        formatted_response = ast.literal_eval(formatted_response)
                    except Exception as e:
                        try:
                            formatted_response = await InferenceUtils.json_repair_exception_llm(incorrect_json=formatted_response, exception=e, llm=llm)
                        except Exception as e:
                            formatted_response = {error_return_key: [f'{formatted_response}']}
            except Exception as e:
                formatted_response = {error_return_key: [f'Processing error: {e}.\n\nPlease try again.']}
        return formatted_response

    @staticmethod
    async def format_list_str(list_input: List[str]) -> str:
        """
        Formats a list into a string with each element on a new line.

        Args:
            list_input: The list to format.

        Returns:
            A string containing the formatted list.
        """
        frmt_text = "\n".join(list_input)
        return frmt_text.strip()

    @staticmethod
    async def format_past_steps_list(past_input_messages: List[str], past_output_messages: List[str]) -> str:
        """
        Formats past input and output messages into a string, with "Response:" prefix for output.

        Args:
            past_input_messages: A list of past input messages.
            past_output_messages: A list of past output messages.

        Returns:
            A string containing the formatted past messages.
        """
        msg_formatted = ""
        for in_msg, out_msg in zip(past_input_messages, past_output_messages):
            msg_formatted += in_msg + "\n" + f"Response: {out_msg}" + "\n\n"
        return msg_formatted.strip()

    @staticmethod
    async def add_prompt_for_feedback(query: str) -> ChatMessage | HumanMessage:
        """
        Helper to format user query or feedback into a ChatMessage.
        """
        if query == "[regenerate:][:regenerate]":
            prompt = "The previous response did not meet expectations. Please review the query and provide a new, more accurate response."
            return ChatMessage(role="feedback", content=prompt)
        elif query.startswith("[feedback:]") and query.endswith("[:feedback]"):
            prompt = f"""The previous response was not satisfactory. Here is the feedback on your previous response:
{query[11:-11]}

Please review the query and feedback, and provide an appropriate answer.
"""
            return ChatMessage(role="feedback", content=prompt)
        else:
            return HumanMessage(content=query, role="user_query")

    @staticmethod
    async def update_preferences(preferences: str, user_input: str, llm: Any) -> str:
        """
        Update the preferences based on user input.
        """
        prompt = f"""
Current Preferences:
{preferences}

User Input:
{user_input}


Instructions:
- Understand the User query, now analyze is the user intention with query is to provide feedback or related to task.
- Understand the feedback points from the given query and add them into the feedback.
- Inputs related to any task are not preferences. Don't consider them.
- If user intention is providing feed back then update the preferences based on below guidelines.
- Update the preferences based on the user input.
- If it's a new preference or feedback, add it as a new line.
- If it modifies an existing preference or feedback, update the relevant line with detailed preference context.
- User input can include new preferences, feedback on mistakes, or corrections to model behavior.
- Store these preferences or feedback as lessons to help the model avoid repeating the same mistakes.
- The output should contain only the updated preferences, with no extra explanation or commentary.
- if no preferences are there then output should is "no preferences available".

Examples:
user query: output should in markdown format
- the user query is related to preference and should be added to the preferences.
user query: a person is running at 5km per hour how much distance he can cover by 2 hours
- The user query is related to task and should not be added to the preferences.
user query: give me the response in meters.
- This is a perference and should be added to the preferences.
"""+"""
Output:
```json
{
"preferences": "all new preferences with new line as separator are added here"
}
```

"""
        response = await llm.ainvoke(prompt)
        response = response.content.strip()
        if "```json" in response:
            response = response[response.find("```json") + len("```json"):]
        response = response.replace('```json', '').replace('```', '').strip()
        try:
            final_response = json.loads(response)["preferences"]
        except json.JSONDecodeError:
            log.error("Failed to decode JSON response from model.")
            return response
        log.info("Preferences updated successfully")
        return final_response

    @staticmethod
    async def format_feedback_learning_data(data: list) -> str:
        """
        Formats feedback learning data into a structured string.

        Args:
            data (list): List of feedback learning data.

        Returns:
            str: Formatted feedback learning data string.
        """
        formatted_data = "\n\n"
        for item in range(len(data)):
            # Include more context for better learning
            formatted_data += f"Lesson {item}: {data[item]['lesson']}\n"
            # if 'query' in data[item]:
            #     formatted_data += f"Context: {data[item]['query']}\n"
            formatted_data += "------------------------\n"
        log.info(f"Formatted Feedback Learning Data")
        return formatted_data.strip()

    @staticmethod
    async def update_dictionary(original_data, new_data):
        """
        Updates the original data dictionary with new data.

        Args:
            original_data (dict): The original data dictionary.
            new_data (dict): The new data to update the original dictionary with.

        Returns:
            dict: The updated dictionary.
        """
        for key, value in new_data.items():
            if key in original_data:
                if key in ["ongoing_conversation", "executor_messages"]:
                    if type(value) == list:
                        original_data[key].extend(value)
                    else:
                        original_data[key].append(value)
                else:
                    original_data[key] = value
            else:
                if key in ["ongoing_conversation", "executor_messages"]:
                    if type(value) == list:
                        original_data[key] = value
                    else:
                        original_data[key] = [value]
                else:
                    original_data[key] = value
        return original_data

    @staticmethod
    async def create_manage_memory_tool():
        async def manage_memory(memory_key: str, memory_data: Union[str, dict]) -> str:
            """
            Store information in long-term memory for future reference based on user queries.
            
            Use this tool to save any information that might be useful for future conversations:
            - User-provided facts, preferences, or details
            - Information about people, places, or things mentioned by the user
            - Context from conversations that should be remembered
            - Any data the user explicitly wants stored or that seems important for continuity
            
            Args:
                memory_key: A descriptive key for this memory
                memory_data: The information to store (string or dictionary format)
            """
            user_id = current_user_email.get("user_123")
            if not user_id:
                log.error("Error getting current user email: User context not available")
                return "Error: Unable to get current user email - User context not available"
            if not isinstance(memory_data, dict):
                memory_data = {"content": f"memory_key: {memory_key}, memory_data: {memory_data}"}
            
            # Use RedisPostgresManager instead of direct Redis xadd
            try:
                user_id = current_user_email.get("test_user")
                manager = await get_global_manager()
                if manager:
                    record_id = f"{user_id}_{memory_key}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
                    data = {
                        "content": memory_data.get("content", ""),
                        "timestamp": datetime.now().isoformat()
                    }
                    success = await manager.add_record(record_id, data, user_id)
                    if success:
                        return f"Memory stored with key='{memory_key}' for user {user_id}."
                    else:
                        return f"Failed to store memory with key='{memory_key}'."
                else:
                    return f"Manager not available, cannot store memory with key='{memory_key}'."
            except Exception as e:
                log.error(f"Error storing memory: {e}")
                return f"Error storing memory with key='{memory_key}': {e}"
        return manage_memory

    @staticmethod
    async def create_search_memory_tool(embedding_model: SentenceTransformer, agent_id : str = None):
        async def search_memory(query: str) -> str:
            """
            Search through stored memories to find relevant information based on the user's query,
            using semantic similarity scoring via embeddings.
            
            Args:
                query: What to search for in the stored memories
            """
            user_id = agent_id if agent_id else current_user_email.get("user_123")
            try:
                query_embedding = embedding_model.encode(query, convert_to_tensor=True)
                manager = await get_global_manager()
                if manager:
                    records = await manager.get_records_by_category(user_id, limit=50)
                    if not records:
                        return "No memories found for this query."
                    scored_results = []
                    for record in records:
                        record_data = record.data
                        content = record_data.get('content', str(record_data))
                        stored_query = record_data.get('query', '')
                        stored_response = record_data.get('response', '')
                        
                        if stored_query.strip():
                            # Calculate query-to-query similarity
                            query_embedding_for_query = embedding_model.encode(stored_query, convert_to_tensor=True)
                            query_similarity = float(util.cos_sim(query_embedding, query_embedding_for_query).item())
                            
                            # Calculate query-to-response similarity
                            if stored_response.strip():
                                response_embedding = embedding_model.encode(stored_response[:200], convert_to_tensor=True)  # Truncate response
                                response_similarity = float(util.cos_sim(query_embedding, response_embedding).item())
                            else:
                                response_similarity = 0.0
                            
                            # Combined score: 70% query + 30% response
                            similarity = 0.7 * query_similarity + 0.3 * response_similarity
                        else:
                            item_embedding = embedding_model.encode(content, convert_to_tensor=True)
                            similarity = float(util.cos_sim(query_embedding, item_embedding).item())
                        scored_results.append({
                            'key': record_data.get('memory_key', record.id),
                            'content': content,
                            'query': record_data.get('query', ''),
                            'response': record_data.get('response', ''),
                            'label': record_data.get('label', ''),
                            'score': similarity,
                            'tool_calls': ast.literal_eval(record_data.get('tool_calls', '[]')) if record_data.get('tool_calls') else None
                        })
                else:
                    return "Manager not available, cannot search memories."
                        
                if not scored_results:
                    return "No relevant memories found."
                
                scored_results = [r for r in scored_results if r['score'] > 0.1] 
                
                if not scored_results:
                    return "No sufficiently relevant memories found."

                scored_results.sort(key=lambda x: x['score'], reverse=True)
                top_score = scored_results[0]['score']
                
                result_top_five = scored_results[:5] 
                return result_top_five

            except Exception as e:
                return f"Error searching memories: {str(e)}"

        return search_memory

    @staticmethod
    def extract_json_from_code_block(text: str) -> Optional[Dict]:
        """Finds and parses a JSON object from a markdown code block."""
        try:
            # Clean up the text - remove BOM, normalize whitespace, etc.
            cleaned_text = text.strip().replace('\ufeff', '').replace('\u200b', '')
            parsed_json = json.loads(cleaned_text)
            log.info("Successfully parsed JSON without needing code block extraction.")
            return parsed_json

        except json.JSONDecodeError as e:
            log.debug(f"Direct JSON parsing failed: {e}")
            # Try to extract from code block
            pattern = r"```json\s*([\s\S]*?)\s*```"
            match = re.search(pattern, text)
            if match:
                json_string = match.group(1).strip()
                # Clean up the extracted JSON string
                json_string = json_string.replace('\ufeff', '').replace('\u200b', '')
                try:
                    parsed_json = json.loads(json_string)
                    log.info("Successfully extracted JSON from code block.")
                    return parsed_json

                except json.JSONDecodeError as e:
                    log.warning(f"Found JSON code block, but failed to parse. Error: {e}")
                    log.debug(f"Content: {json_string}")
                    # Try to find the specific issue and create a fallback
                    try:
                        # Sometimes the JSON might have trailing commas or other issues
                        # Let's try basic cleaning
                        cleaned_json = json_string.replace(',}', '}').replace(',]', ']')
                        parsed_json = json.loads(cleaned_json)
                        log.info("Successfully parsed JSON after basic cleaning.")
                        return parsed_json
                    except json.JSONDecodeError:
                        log.error(f"JSON parsing failed even after cleaning. Content: {json_string}")
                        return None
        log.info("Warning: No valid JSON code block found in the LLM response.")
        return None

    @staticmethod
    def format_for_ui_node(state: Any, llm: Any):
        """
        Node 2: Formats the agent's text answer into the standardized 
        {type, data, metadata} JSON structure, using the "JSON-in-Code-Block" method.
        """
        log.info("--- FORMATTER NODE: Converting text to standardized UI JSON... ---")

        # This prompt is the core of the solution. It is extremely specific and provides
        # clear examples of the required {type, data, metadata} structure.
        formatter_prompt = FORMATTER_PROMPT.format(query=state["query"], response=state["response"])

        raw_response_text = llm.invoke(formatter_prompt).content
        log.info(f"Formatter LLM Raw Output Generated")

        parsed_json = InferenceUtils.extract_json_from_code_block(raw_response_text)
        
        if not parsed_json:
            # Fallback if the LLM fails to produce valid JSON
            parsed_json = {
                "parts": [{
                    "type": "text",
                    "data": {
                        "content": f"I couldn't format the response correctly, but here is the raw answer:\n\n{state['response']}"
                    },
                    "metadata": {
                        "error": "Failed to parse structured response from LLM.",
                        "timestamp": datetime.now().isoformat()
                    }
                }]
            }
        if len(state["executor_messages"]) > 0:
            parsed_json.update({"parts_storage_dict": {state["executor_messages"][-1].id: parsed_json.get("parts", [])}})
        
        return parsed_json

    @staticmethod
    def add_parts(left_parts, right_parts):
        """
        Merges two dictionaries of UI parts.
        """
        # If either is None or empty, return the other as a new object
        if not left_parts:
            return right_parts.copy() if isinstance(right_parts, dict) else {}
        if not right_parts:
            return left_parts.copy() if isinstance(left_parts, dict) else {}

        # If both are dicts, update left with right and return
        if isinstance(left_parts, dict) and isinstance(right_parts, dict):
            merged = left_parts.copy()
            merged.update(right_parts)
            return merged

        # If both are lists, concatenate
        if isinstance(left_parts, list) and isinstance(right_parts, list):
            return {}

        # If one is dict and one is list, merge appropriately
        if isinstance(left_parts, dict) and isinstance(right_parts, list):
            merged = left_parts.copy()
            return merged
        if isinstance(left_parts, list) and isinstance(right_parts, dict):
            merged = right_parts.copy()
            return merged

        # Fallback: return right_parts
        return {}



class EpisodicMemoryManager:
    def __init__(
            self,
            user_id: str,
            *,
            embedding_model: SentenceTransformer = None,
            cross_encoder: CrossEncoder = None,
            max_examples: int = 3,
            max_queue_size: int = 30,
            retention_days: int = 30,
            relevance_threshold: float = 0.65,
            cleanup_usage_threshold: int = 3,
            low_performer_threshold: float = 0.2
        ):
        self.user_id = user_id
        self.embedding_model = embedding_model
        self.cross_encoder = cross_encoder
        self.MAX_EXAMPLES = max_examples
        self.MAX_QUEUE_SIZE = max_queue_size
        self.RETENTION_DAYS = retention_days
        self.RELEVANCE_THRESHOLD = relevance_threshold
        self.CLEANUP_USAGE_THRESHOLD = cleanup_usage_threshold
        self.LOW_PERFORMER_THRESHOLD = low_performer_threshold
        self.namespace = ("interaction_queue", user_id)

        if self.embedding_model is None:
            try:
                from src.api.dependencies import ServiceProvider
                self.embedding_model = ServiceProvider.get_embedding_model()
            except Exception as e:
                log.error(f"ERROR: Failed to initialize default embedding model: {e}")
                self.embedding_model = None
        
        if self.cross_encoder is None:
            try:
                from src.api.dependencies import ServiceProvider
                self.cross_encoder = ServiceProvider.get_cross_encoder()
            except Exception as e:
                log.error(f"ERROR: Failed to initialize default cross encoder: {e}")
                self.cross_encoder = None

    async def store_interaction_example(self, query: str, response: str, label: str, tool_calls: Optional[List[str]] = None):
        try:
            await self.cleanup_expired_examples()
            manager = await get_global_manager()
            if manager:
                records = await manager.get_records_by_category(self.user_id, limit=self.MAX_QUEUE_SIZE + 5)
            else:
                log.error("Manager not available, cannot retrieve interaction records")
                return {"status": "error", "message": "Manager not available"}
            
            log.info(f"current queue size: {len(records)}")

            query_stripped = query.strip().lower()
            response_stripped = response.strip().lower()
            label_stripped = label.strip().lower()
            # Check for exact duplicates
            for item in records:
                if item.id.startswith('item_') and item.data:
                    existing_query = item.data.get('query', '').strip().lower()
                    existing_response = item.data.get('response', '').strip().lower()
                    existing_label = item.data.get('label', '').strip().lower()
                    if existing_query == query_stripped and existing_response == response_stripped:
                        if existing_label != label_stripped:
                            log.info(f"Updating label of existing interaction from '{existing_label}' to '{label_stripped}' for key: {item.id}")
                            item.data['label'] = label_stripped
                            if manager:
                                await manager.update_record_in_database(item)
                            return {"status": "updated", "message": f"Updated label to {label} for existing interaction"}
                        return {"status": "duplicate", "message": "Duplicate interaction found, not storing again"}

            log.debug("No duplicates found, proceeding with storage")

            if len(records) >= self.MAX_QUEUE_SIZE:
                await self.cleanup_low_performing_examples(records)

            # Use combined query + response for better semantic representation
            content = f"Query: {query.strip()} | Response: {response.strip()} | Label: {label}"
            
            interaction_data = {
                "query": query.strip(),
                "response": response.strip(),
                "content": content,
                "timestamp": datetime.now().isoformat(),
                "total_usage_count": 0,
                "total_relevance_sum": 0.0,
                "creation_time": datetime.now().isoformat(),
                "label": label,
                "tool_calls": str(tool_calls) or str([])
            }

            item_key = f"item_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
            interaction_data["key"] = item_key
            
            # Use RedisPostgresManager to store interaction
            if manager:
                success = await manager.add_record(item_key, interaction_data, self.user_id)
                if not success:
                    log.error(f"Failed to store interaction with key: {item_key}")
                    return {"status": "error", "message": "Failed to store interaction"}
            else:
                log.error("Manager not available, cannot store interaction")
                return {"status": "error", "message": "Manager not available"}
            
            log.debug(f"Successfully stored interaction data with key: {item_key}")
            return {"status": "success", "message": f"Successfully stored as {label} example"}
        except Exception as e:
            log.error(f"Error storing interaction: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def cleanup_expired_examples(self):
        try:
            cutoff = datetime.now() - timedelta(days=self.RETENTION_DAYS)
            manager = await get_global_manager()
            if manager:
                records = await manager.get_records_by_category(self.user_id, limit=100)
            expired_keys = []
            for item in records:
                if item.id.startswith('item_') and item.data:
                    try:
                        t = datetime.fromisoformat(item.data.get('timestamp', ''))
                        if t < cutoff:
                            expired_keys.append(item.id)
                    except Exception:
                        expired_keys.append(item.id)
            for key in expired_keys:
                try:
                    if manager:
                        await manager.delete_record(key)
                        
                except Exception as e:
                    log.error(f"Error deleting record {key}: {e}")
        
            if expired_keys:
                log.info(f"Cleaned up {len(expired_keys)} expired examples")
        except Exception as e:
            log.error(f"Error during cleanup of expired examples: {e}")

    async def cleanup_low_performing_examples(self, current_items):
        candidates = []
        for item in current_items:
            # Support both dict and object types for item and its data/value
            if isinstance(item, dict):
                item_data = item.get('data') or item.get('value') or item
                item_key = item.get('key') or item.get('id')
            else:
                item_data = getattr(item, 'data', None) or getattr(item, 'value', None)
                item_key = getattr(item, 'key', None) or getattr(item, 'id', None)
            if item_data:
                uc = item_data.get('total_usage_count', 0)
                rs = item_data.get('total_relevance_sum', 0.0)
                if uc >= self.CLEANUP_USAGE_THRESHOLD:
                    avg_rel = rs / uc if uc else 0.0
                    if avg_rel < self.LOW_PERFORMER_THRESHOLD:
                        candidates.append({'key': item_key, 'avg_relevance': avg_rel})
        candidates.sort(key=lambda x: x['avg_relevance'])
        to_remove = candidates[:5]
        manager = await get_global_manager()
        for c in to_remove:
            if manager:
                await manager.base_manager.delete_record(c['key'])
        if to_remove:
            log.info(f"Cleaned up {len(to_remove)} low-performing examples")

    async def find_relevant_examples_for_query(self, query: str) -> Dict[str, List[Dict]]:
        episodic_search_tool = await InferenceUtils.create_search_memory_tool(self.embedding_model, self.user_id)
        raw_results = await episodic_search_tool(query=query)
        if not raw_results or "No" in raw_results:
            return {"positive": [], "negative": []}

        positive_cands, negative_cands = [], []
        if type(raw_results)==list:
            for c in raw_results:
                label = c.get('label', '').lower()
                if label == 'negative':
                    negative_cands.append(c)
                else:
                    positive_cands.append(c)

        def rerank_with_cross_encoder(cands):
            if not cands:
                return []
            
            query_pairs = []
            query_response_pairs = []
            for c in cands:
                # Query-to-query comparison
                query_pairs.append([query, c['query']])
                # Query-to-response comparison (if response exists)
                if c.get('response', '').strip():
                    response_truncated = c['response'][:200]
                    query_response_pairs.append([query, response_truncated])
                else:
                    query_response_pairs.append([query, ""])
            
            try:
                # Get raw logits from cross-encoder for both query and response pairs
                query_raw_scores = self.cross_encoder.predict(query_pairs)
                response_raw_scores = self.cross_encoder.predict(query_response_pairs)
                
                # Apply sigmoid to convert logits to probabilities (0-1 range)
                import torch
                if not isinstance(query_raw_scores, torch.Tensor):
                    query_raw_scores = torch.tensor(query_raw_scores)
                if not isinstance(response_raw_scores, torch.Tensor):
                    response_raw_scores = torch.tensor(response_raw_scores)
                    
                query_sigmoid_scores = torch.sigmoid(query_raw_scores).numpy()
                response_sigmoid_scores = torch.sigmoid(response_raw_scores).numpy()
            
                combined_scores = 0.7 * query_sigmoid_scores + 0.3 * response_sigmoid_scores
               
                return [{"candidate": cands[i], "score": float(combined_scores[i]), "bi_score": cands[i]['score']} for i in range(len(cands))]
                
            except Exception as e:
                log.error(f"Cross-encoder failed: {e}, falling back to bi-encoder scores")
                return [{"candidate": cands[i], "score": cands[i]['score'], "bi_score": cands[i]['score']} for i in range(len(cands))]

        scored_pos = rerank_with_cross_encoder(positive_cands)
        scored_neg = rerank_with_cross_encoder(negative_cands)

        # Filter by relevance threshold and update usage statistics for qualifying examples
        qualified_pos = []
        for x in scored_pos:
            if x["score"] >= self.RELEVANCE_THRESHOLD:
                qualified_pos.append(x)
                await self.update_example_usage_statistics(x['candidate']['key'], x['score'])
        
        qualified_neg = []
        for x in scored_neg:
            if x["score"] >= self.RELEVANCE_THRESHOLD:
                qualified_neg.append(x)
                await self.update_example_usage_statistics(x['candidate']['key'], x['score'])

        qualified_pos.sort(key=lambda x: x["score"], reverse=True)
        qualified_neg.sort(key=lambda x: x["score"], reverse=True)
       
        scored_pos = qualified_pos[:self.MAX_EXAMPLES]
        scored_neg = qualified_neg[:self.MAX_EXAMPLES]

        positive_examples = [{
            "query": item['candidate']['query'],
            "response": item['candidate']['response'],
            "relevance_score": item['score'],
            "key": item['candidate']['key'],
            "tool_calls": item['candidate']['tool_calls']
        } for item in scored_pos]
        negative_examples = [{
            "query": item['candidate']['query'],
            "response": item['candidate']['response'],
            "relevance_score": item['score'],
            "key": item['candidate']['key'],
            "tool_calls": item['candidate']['tool_calls']
        } for item in scored_neg]

        return {"positive": positive_examples, "negative": negative_examples}
    
    async def update_example_usage_statistics(self, key: str, relevance_score: float):
        manager = await get_global_manager()
        if manager:
            records = await manager.get_records_by_category(self.user_id, limit=100)
        for item in records:
            if item.id == key:
                usage = item.data.get('total_usage_count', 0)
                sum_rel = item.data.get('total_relevance_sum', 0.0)
                item.data['total_usage_count'] = usage + 1
                item.data['total_relevance_sum'] = sum_rel + relevance_score
                await manager.update_record_in_database(item)
                break

    async def create_context_from_examples(self, positive_examples: List[Dict], negative_examples: List[Dict]) -> str:
        context = ""
        if positive_examples:
            context += "\n\nRELEVANT POSITIVE EXAMPLES (use as guidance):\n"
            for i, ex in enumerate(positive_examples, 1):
                context += f"\nExample {i} (relevance {ex['relevance_score']:.3f}):\n"
                context += f"User: {ex['query']}\n"
                if ex.get('tool_calls'):
                    context += f"Tool calls: {', '.join(ex['tool_calls'])}\n"
                
                context += f"Assistant: {ex['response'][:200]}...\n---\n"
                
        if negative_examples:
            context += "\n\nRELEVANT NEGATIVE EXAMPLES (DO NOT FOLLOW):\n"
            for i, ex in enumerate(negative_examples, 1):
                context += f"\nNegative Example {i} (relevance {ex['relevance_score']:.3f}):\n"
                context += f"User: {ex['query']}\n"
                if ex.get('tool_calls'):
                    context += f"Tool calls (avoid this pattern): {', '.join(ex['tool_calls'])}\n"
                
                context += f"Assistant (incorrect/unwanted): {ex['response'][:200]}...\n---\n"
        if positive_examples or negative_examples:
            context += (
                "\nIMPORTANT INSTRUCTIONS:\n"
                "1. Use positive examples as guidance for response style, structure, and problem solving approach.\n"
                "2. Explicitly avoid generating response similar to negative examples (do not repeat their mistakes or undesirable style).\n"
                "3. Prefer using available tools for specialized tasks.\n"
                "4. Do not fabricate facts, hallucinate, or confidently assert things you are unsure about.\n"
            )
        return context

