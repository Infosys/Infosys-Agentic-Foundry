import re
import json
import uuid
import inspect
from datetime import datetime, timezone
import pandas as pd

from typing import List, Optional, Union, Dict, Any

from langchain_core.tools import BaseTool
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, ChatMessage, AnyMessage

from src.database.repositories import AgentRepository,ToolRepository,ChatHistoryRepository
from src.prompts.prompts import CONVERSATION_SUMMARY_PROMPT
from src.models.model import load_model
# from src.tools.tool_code_processor import ToolCodeProcessor
from telemetry_wrapper import logger as log, update_session_context

class ToolService:
    """
    Service layer for managing tools.
    Applies business rules, handles docstring generation, validation,
    dependency checks, and orchestrates repository calls.
    """

    def __init__(
        self,
        tool_repo: ToolRepository,
        agent_repo: AgentRepository 
    ):
        self.tool_repo = tool_repo
        self.agent_repo = agent_repo 
    
    async def get_tool(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves a single tool record by ID or name, with associated tags.

        Args:
            tool_id (str, optional): Tool ID.
            tool_name (str, optional): Tool name.

        Returns:
            dict: A dictionary representing the retrieved tool, or None if not found.
        """
        tool_records = await self.tool_repo.get_tool_record(tool_id=tool_id, tool_name=tool_name)
        if not tool_records:
            log.info(f"No tool found with ID: {tool_id} or Name: {tool_name}.")
            return []

        log.info(f"Retrieved tool with ID: {tool_records[0]['tool_id']} and Name: {tool_records[0]['tool_name']}.")
        return tool_records
    @staticmethod
    async def render_text_description_for_tools(tools: List[BaseTool]) -> str:
        """Render the tool name and description in plain text.

        Args:
            tools: The tools to render.

        Returns:
            The rendered text.

        Output will be in the format of:

        .. code-block:: markdown

            search: This tool is used for search
            calculator: This tool is used for math
        """
        descriptions = []
        for tool in tools:

            signature = inspect.signature(tool)
            args_list = ""

            for param_name, param in signature.parameters.items():
                args_list +=f"Parameter: {param_name}, Type: {param.annotation}\n"
            description = f"tool name:\n{tool.__name__} \n tool arguments:\n{args_list} \ntool Docstring:\n{tool.__doc__}\n"
            descriptions.append(description)
        return "\n\n".join(descriptions)
    async def _extract_tools_using_tool_ids(self, tools_id: Union[List[str], str]) -> Dict[str, Any]:
        """
        Extracts tool information from the database using tool IDs.

        Args:
            tools_id (Union[List[str], str]): List of tool IDs to retrieve details for.

        Returns:
            dict: A dictionary containing tool information indexed by tool names.
        """
        if isinstance(tools_id, str):
            tools_id = [tools_id]

        tools_info_user = {}
        for idx, tool_id_single in enumerate(tools_id):
            tool_record = await self.tool_repo.get_tool_record(tool_id=tool_id_single)
            if tool_record:
                tool_record = tool_record[0]
                tools_info_user[f"Tool_{idx+1}"] = {
                    "Tool_Name": tool_record.get("tool_name"),
                    "Tool_Description": tool_record.get("tool_description"),
                    "code_snippet": tool_record.get("code_snippet")
                }
            else:
                tools_info_user[f"Tool_{idx+1}"] = {"error": f"No data found for tool_id: {tool_id_single}"}
        log.info(f"Extracted {len(tools_info_user)} tools using provided tool IDs.")
        return tools_info_user
class AgentService:
    """
    Service layer for managing agents (Agentic Applications).
    Applies business rules, handles prompt generation, validation,
    dependency checks, and orchestrates repository and other service calls.
    """

    def __init__(
        self,
        agent_repo: AgentRepository,
        tool_repo: ToolRepository,
        tool_service: ToolService,
        meta_type_templates: List[str] = ["meta_agent", "planner_meta_agent"]
    ):
        self.agent_repo = agent_repo
        self.tool_repo = tool_repo
        self.tool_service = tool_service
        self.meta_type_templates = meta_type_templates

    async def get_agents_details_for_chat(self) -> List[Dict[str, Any]]:
        """
        Fetches basic agent details (ID, name, type) for chat purposes.

        Returns:
            list[dict]: A list of dictionaries, where each dictionary contains
                        'agentic_application_id', 'agentic_application_name',
                        and 'agentic_application_type'.
        """
        return await self.agent_repo.get_agents_details_for_chat_records()
    # --- Agent Retrieval Operations ---

    async def get_agent(self,
                        agentic_application_id: Optional[str] = None,
                        agentic_application_name: Optional[str] = None,
                        agentic_application_type: Optional[str] = None,
                        created_by: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves agents from the database based on provided parameters, with associated tags.

        Args:
            agentic_application_id (str, optional): The ID of the agentic application to filter by.
            agentic_application_name (str, optional): The name of the agentic application to filter by.
            agentic_application_type (str, optional): The type of agentic application to filter by.
            created_by (str, optional): The creator of the agentic application to filter by.

        Returns:
            list: A list of dictionaries representing the retrieved agents, or an empty list on error.
        """
        agent_records = await self.agent_repo.get_agent_record(
            agentic_application_id=agentic_application_id,
            agentic_application_name=agentic_application_name,
            agentic_application_type=agentic_application_type,
            created_by=created_by
        )

        if not agent_records:
            log.error(f"No agentic application found with ID: {agentic_application_id or agentic_application_name or agentic_application_type or created_by}")
            return []

        for agent_record in agent_records:
            if agent_record:
                agentic_application_name = agent_record.get('agentic_application_name')
                # Ensure JSONB fields are loaded as Python objects (asyncpg usually handles this)
                agent_record['system_prompt'] = json.loads(agent_record['system_prompt']) if isinstance(agent_record['system_prompt'], str) else agent_record['system_prompt']
                agent_record['tools_id'] = json.loads(agent_record['tools_id']) if isinstance(agent_record['tools_id'], str) else agent_record['tools_id']
                # agent_record['tags'] = await self.tag_service.get_tags_by_agent(agent_record['agentic_application_id'])
                log.info(f"Retrieved agentic application with name: {agentic_application_name}")
        return agent_records

    @staticmethod
    async def _normalize_agent_name(agent_name: str):
        """
        Normalizes the agent name by removing invalid characters and formatting it.
        """
        return re.sub(r'[^a-z0-9_]', '', agent_name.strip().lower().replace(" ", "_"))
  

class ChatService:
    """
    Service layer for managing chat history.
    Applies business rules for naming conventions and orchestrates repository calls.
    """

    def __init__(self, chat_history_repo: ChatHistoryRepository):
        """
        Initializes the ChatService.

        Args:
            chat_history_repo (ChatHistoryRepository): The repository for chat history data access.
        """
        self.repo = chat_history_repo
        self.conversation_summary_prompt_template = PromptTemplate.from_template(CONVERSATION_SUMMARY_PROMPT)
    
    async def get_checkpointer_context_manager(self):
        """
        Retrieves the checkpointer context manager for managing conversation state.
        """
        return await self.repo.get_checkpointer_context_manager()
    async def delete_session(self, agentic_application_id: str, session_id: str) -> Dict[str, Any]:
        """
        Deletes the entire conversation history for a specific session.
        This involves deleting from chat history and checkpoint tables transactionally.

        Args:
            agentic_application_id (str): The ID of the agent.
            session_id (str): The session ID to delete records for.

        Returns:
            dict: A status dictionary indicating the result of the operation.
        """
        chat_table_name = await self._get_chat_history_table_name(agentic_application_id)
        thread_id = await self._get_thread_id(agentic_application_id, session_id)
        
        try:
            chat_rows_deleted = await self.repo.delete_session_transactional(
                chat_table_name=chat_table_name,
                thread_id=thread_id,
                session_id=session_id
            )
            return {
                "status": "success",
                "message": f"Memory history deleted successfully for session {session_id}.",
                "chat_rows_deleted": chat_rows_deleted
            }
        except Exception as e:
            log.error(f"Service-level error during transactional delete for session '{session_id}': {e}")
            return {"status": "error", "message": f"An error occurred during deletion: {e}"}

    @staticmethod
    async def _get_chat_history_table_name(agentic_application_id: str) -> str:
        """
        Generates the dynamic table name for a specific agent's chat history.
        This encapsulates the naming convention logic.
        
        Args:
            agentic_application_id (str): The unique ID of the agentic application.

        Returns:
            str: The formatted table name.
        """
        return f'table_{agentic_application_id.replace("-", "_")}'

    @staticmethod
    async def _get_thread_id(agentic_application_id: str, session_id: str) -> str:
        """
        Generates the thread_id used in checkpoint tables.

        Args:
            agentic_application_id (str): The unique ID of the agentic application.
            session_id (str): The unique ID for the session.
        
        Returns:
            str: The formatted thread ID.
        """
        table_name = await ChatService._get_chat_history_table_name(agentic_application_id)
        return f"{table_name}_{session_id}"
    @staticmethod
    async def _get_thread_config(thread_id: str, recursion_limit: int = 100) -> Dict[str, Any]:
        """
        Retrieves the thread configuration for a specific thread_id.
        """
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}
    
    @staticmethod
    async def segregate_conversation_from_raw_chat_history_with_pretty_steps(response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Segregates and formats conversation messages from a raw response into a human-readable list.
        """
        if "error" in response:
            log.error(f"Error in response")
            return [response]
        error_message = [{"error": "Chat History not compatable with the new version. Please reset your chat."}]
        executor_messages = response.get("executor_messages", [{}])
        # return executor_messages
        if not executor_messages[0] or not hasattr(executor_messages[0], 'role') or executor_messages[0].role != "user_query":
            return error_message

        conversation_list = []
        agent_steps = []

        for message in reversed(executor_messages):
            agent_steps.append(message)
            if message.type == "human" and hasattr(message, 'role') and message.role=="user_query":
                data = ""

                # Pretty-print each message to the buffer
                for msg in list(reversed(agent_steps)):
                    data += "\n"+ msg.pretty_repr()


                new_conversation = {
                    "user_query": message.content,
                    "final_response": agent_steps[0].content if (agent_steps[0].type == "ai") and ("tool_calls" not in agent_steps[0].additional_kwargs) and ("function_call" not in agent_steps[0].additional_kwargs) else "",
                    "agent_steps": data,
                    "additional_details": agent_steps
                }
                conversation_list.append(new_conversation)
                agent_steps = []
        log.info("Conversation segregated from chat history successfully")
        return list(reversed(conversation_list))

    @staticmethod
    async def segregate_conversation_from_raw_chat_history_with_json_like_steps(response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Segregates and formats conversation messages from a raw response into a JSON-serializable list.
        """
        if "error" in response:
            log.error(f"Error in response")
            return [response]
        error_message = [{"error": "Chat History not compatable with the new version. Please reset your chat."}]
        executor_messages = response.get("executor_messages", [{}])
        # return executor_messages
        if not executor_messages[0] or not hasattr(executor_messages[0], 'role') or executor_messages[0].role != "user_query":
            return error_message

        conversation_list = []
        agent_steps = []

        for message in reversed(executor_messages):
            agent_steps.append(message)
            if message.type == "human" and hasattr(message, 'role') and message.role=="user_query":
                new_conversation = {
                    "user_query": message.content,
                    "final_response": agent_steps[0].content if (agent_steps[0].type == "ai") and ("tool_calls" not in agent_steps[0].additional_kwargs) and ("function_call" not in agent_steps[0].additional_kwargs) else "",
                    "agent_steps": list(reversed(agent_steps)),
                }
                conversation_list.append(new_conversation)
                agent_steps = []
        log.info("Conversation segregated in JSON format successfully")
        return list(reversed(conversation_list))
    
    async def get_chat_summary(self, agentic_application_id, session_id, llm, conversation_limit=30, executor_messages=None, executor_message_limit=30) -> str:
        """Retrieves a summary of the conversation history for a given session ID."""
        conversation_history_df = pd.DataFrame(
            await self.get_chat_history_from_long_term_memory(
                    agentic_application_id=agentic_application_id,
                    session_id=session_id,
                    limit=conversation_limit
                )
        )
        conversation_summary_chain = await self._get_summary_chain(llm)

        # Process chat history if available
        if len(conversation_history_df):
            conversation_history_df = conversation_history_df.sort_values(
                by=["start_timestamp", "end_timestamp"]
            ).reset_index(drop=True)
            chat_history = "\n\n".join(
                [
                    f"""Human Message: {Human_Message}
    AI Message: {AI_Message}"""
                    for Human_Message, AI_Message in conversation_history_df[
                        ["human_message", "ai_message"]
                    ].itertuples(index=False)
                ]
            )
            if executor_messages:
                chat_history += "\n\n" + "\n\n".join(self.get_formatted_messages(messages=executor_messages, msg_limit=executor_message_limit))
            conversation_summary = await conversation_summary_chain.ainvoke(
                {"chat_history": chat_history}
            )
        else:
            conversation_summary = ""
        log.info(f"Conversation Summary generated for agent id {agentic_application_id} and session {session_id}")
        return conversation_summary
    async def _get_summary_chain(self, llm):
        return self.conversation_summary_prompt_template | llm | StrOutputParser()
    
    async def get_chat_history_from_long_term_memory(
            self,
            agentic_application_id: str,
            session_id: str,
            limit: int = 30
        ) -> List[Dict[str, Any]]:
        """
        Retrieves recent chat history for a given session.

        Args:
            agentic_application_id (str): The ID of the agent.
            session_id (str): The ID of the chat session.
            limit (int): The maximum number of conversation pairs to retrieve.

        Returns:
            A list of chat history records.
        """
        table_name = await self._get_chat_history_table_name(agentic_application_id)
        return await self.repo.get_chat_records_by_session_from_long_term_memory(
            table_name=table_name,
            session_id=session_id,
            limit=limit
        )
    @staticmethod
    async def get_formatted_messages(messages: List[AnyMessage], msg_limit: int = 30) -> str:
        """
        Formats a list of messages for display.

        Args:
            messages (list): The list of messages.
            msg_limit (int): The maximum number of messages to display.

        Returns:
            str: The formatted message string.
        """

        msg_formatted = ""
        for m in messages[-msg_limit:]: # Display only the last `msg_limit` messages
            if isinstance(m, HumanMessage):
                hmn_format = f"Human Message: {m.content}"
                msg_formatted += hmn_format + "\n\n"
            elif isinstance(m, ChatMessage) and m.role == "feedback":
                feedback_format = f"Feedback: {m.content}"
                msg_formatted += feedback_format + "\n\n"
            elif isinstance(m, AIMessage):
                ai_format = f"AI Message: {m.content}"
                msg_formatted += ai_format + "\n\n"
            elif isinstance(m, ToolMessage):
                tool_msg_format = f"Tool Message: {m.content}"
                msg_formatted += tool_msg_format + "\n\n"
        return msg_formatted.strip()
    
    async def save_chat_message(
        self,
        agentic_application_id: str,
        session_id: str,
        start_timestamp: str,
        end_timestamp: str,
        human_message: str,
        ai_message: str
    ) -> bool:
        """
        Orchestrates saving a new chat message pair to the database.
        It ensures the target table exists before inserting the record.

        Args:
            (all args are data for the chat message)

        Returns:
            bool: True if successful, False otherwise.
        """
        table_name = await self._get_chat_history_table_name(agentic_application_id)
        try:
            # Orchestration: ensure table exists, then insert.
            await self.repo.create_chat_history_table(table_name)
            await self.repo.insert_chat_record(
                table_name=table_name,
                session_id=session_id,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                human_message=human_message,
                ai_message=ai_message,
            )
            return True
        except Exception as e:
            log.error(f"Service-level error saving chat message for session '{session_id}': {e}")
            return False

    async def handle_like_feedback_message(
        self,
        agentic_application_id: str,
        session_id: str,
        message_type: str = "ai",
        start_tag: str = "[liked_by_user:]",
        end_tag: str = "[:liked_by_user]"
    ) -> Dict[str, str]:
        """
        Handles the like/unlike feedback for the latest message and returns a user-friendly message.

        Args:
            agentic_application_id (str): The ID of the agentic application.
            session_id (str): The session ID to identify the conversation.
            message_type (str): The type of message to update ('ai' or 'human').
            start_tag (str): The starting tag to add or remove.
            end_tag (str): The ending tag to add or remove.

        Returns:
            Dict[str, str]: A dictionary containing a 'message' key with the status.
        """
        update_status = await self.update_latest_query_response_with_tag(
            agentic_application_id=agentic_application_id,
            session_id=session_id,
            message_type=message_type,
            start_tag=start_tag,
            end_tag=end_tag
        )

        if update_status is True: # Tags were added
            return {"message": "Thanks for the like! We're glad you found the response helpful. If you have any more questions or need further assistance, feel free to ask!"}
        elif update_status is False: # Tags were removed
            return {"message": "Your like has been removed. If you have any more questions or need further assistance, feel free to ask!"}
        else: # None was returned (message not found or error)
            return {"message": "Sorry, we couldn't update your request at the moment. Please try again later."}

    async def get_chat_history_from_short_term_memory(
            self,
            agentic_application_id: str,
            session_id: str
        ) -> Dict[str, Any]:
        """
        Retrieves the previous conversation history for a given session from the LangGraph checkpointer.

        Args:
            agentic_application_id (str): The ID of the agent.
            session_id (str): The session ID of the user.

        Returns:
            Dict[str, Any]: A dictionary containing the previous conversation history,
                            or an error message if retrieval fails.
        """
        thread_id = await self._get_thread_id(agentic_application_id, session_id)

        try:
            # The checkpointer needs its own connection setup
            async with await self.get_checkpointer_context_manager() as checkpointer:
                # checkpointer.setup() is often called implicitly or handled by LangGraph's app.compile()
                # but explicitly calling it here ensures the table exists if it's the first time.
                # However, for just retrieving, it might not be strictly necessary if tables are pre-created.
                await checkpointer.setup()

                config = await self._get_thread_config(thread_id)
                data = await checkpointer.aget(config) # Retrieve the state
                if data:
                    # data.channel_values contains the state of the graph, including messages
                    data = data.get("channel_values", {})
                else:
                    data = {}

                if not data:
                    log.warning(f"No previous conversation found for session ID: {session_id} and agent ID: {agentic_application_id}.")
                    return {"executor_messages": []} # Return empty list if no data

                # Segregate messages using the static method
                data["executor_messages"] = await self.segregate_conversation_from_raw_chat_history_with_pretty_steps(data)
                log.info(f"Previous conversation retrieved successfully for session ID: {session_id} and agent ID: {agentic_application_id}.")
                return data

        except Exception as e:
            log.error(f"Error occurred while retrieving previous conversation for session {session_id}: {e}", exc_info=True)
            return {"error": f"An unknown error occurred while retrieving conversation: {e}"}
        finally:
            update_session_context(session_id='Unassigned',agent_id='Unassigned')
    async def update_latest_query_response_with_tag(
        self,
        agentic_application_id: str,
        session_id: str,
        message_type: str = "ai",
        start_tag: str = "[liked_by_user:]",
        end_tag: str = "[:liked_by_user]"
    ) -> Optional[bool]: # <--- Reverted return type hint
        """
        Updates the latest query response (or human message) by adding or removing
        specified tags.

        Args:
            agentic_application_id (str): The ID of the agentic application.
            session_id (str): The session ID to identify the conversation.
            message_type (str): The type of message to update ('ai' or 'human').
            start_tag (str): The starting tag to add or remove.
            end_tag (str): The ending tag to add or remove.

        Returns:
            Optional[bool]: True if tags were added, False if tags were removed,
                            None if the message was not found or an error occurred.
        """
        table_name = await self._get_chat_history_table_name(agentic_application_id)

        message_type_lower = message_type.lower()
        if message_type_lower == "human":
            message_column = "human_message"
        elif message_type_lower == "ai":
            message_column = "ai_message"
        else:
            log.warning(f"Invalid message_type '{message_type}'. Must be 'ai' or 'human'.")
            return None

        try:
            latest_message_record = await self.repo.get_latest_message_record(
                table_name=table_name,
                session_id=session_id,
                message_column=message_column
            )

            if not latest_message_record:
                log.warning(f"No latest {message_type} message found for session {session_id} in table {table_name}.")
                return None

            current_message_content = latest_message_record['message_content']
            end_timestamp = latest_message_record['end_timestamp']

            tags_were_present: bool
            if current_message_content.startswith(start_tag) and current_message_content.endswith(end_tag):
                # Tags are present, remove them
                updated_content = current_message_content[len(start_tag):-len(end_tag)].strip()
                tags_were_present = True
                log.info(f"Removing tags from latest {message_type} message for session {session_id}.")
            else:
                # Tags are not present, add them
                updated_content = f"{start_tag}{current_message_content}{end_tag}".strip()
                tags_were_present = False
                log.info(f"Adding tags to latest {message_type} message for session {session_id}.")

            success = await self.repo.update_message_tag_record(
                table_name=table_name,
                session_id=session_id,
                message_column=message_column,
                updated_message_content=updated_content,
                end_timestamp=end_timestamp
            )

            if success:
                return not tags_were_present # True if tags were added, False if removed
            else:
                log.error(f"Failed to update {message_type} message for session {session_id} in table {table_name} after processing tags.")
                return None

        except Exception as e:
            log.error(f"Service-level error updating query response with tag for session '{session_id}': {e}")
            return None
