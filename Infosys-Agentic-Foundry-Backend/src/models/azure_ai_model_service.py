# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import json
import asyncio
from typing import Any, Dict, List, Optional

from openai import AzureOpenAI
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageToolCall

from src.models.base_ai_model_service import BaseAIModelService
from src.database.repositories import ChatStateHistoryManagerRepository

from telemetry_wrapper import logger as log


class AzureAIModelService(BaseAIModelService):
    """
    Concrete implementation of BaseAIModelService for Azure OpenAI models.
    """

    def __init__(
        self,
        api_key: str,
        api_base: str, # Azure endpoint
        api_version: str, # Azure API version, e.g., "2023-12-01-preview"
        model: Optional[str] = None,
        temperature: float = 0.0,
        chat_history_manager: Optional[ChatStateHistoryManagerRepository] = None
    ):
        super().__init__(
            api_key=api_key,
            api_base=api_base,
            api_version=api_version,
            model=model,
            temperature=temperature,
            chat_history_manager=chat_history_manager
        )

        if not self._api_key or not self._api_base or not self._api_version:
            raise ValueError("For AzureAIAgent, 'api_key', 'api_base' and 'api_version' must be provided.")

        self._client = AzureOpenAI(
            api_key=self._api_key,
            api_version=self._api_version,
            azure_endpoint=self._api_base
        )
        log.info(f"[AzureAIModelService] Initialized.")


    async def ainvoke(
        self,
        messages: Optional[List[Dict[str, str]]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Invokes the Azure agent with a list of messages, handling multi-turn conversations,
        parallel tool calls, chat history, and tool interruption.

        Args:
            messages: A list of message dictionaries (e.g., [{"role": "user", "content": "..."}]).
                      If None, the agent attempts to resume an interrupted chat.
            config: Optional dictionary for configurable parameters:
                - "configurable":
                    - "thread_id": (str) Unique ID for the conversation thread. If not provided,
                                   chat history will not be stored or retrieved.
                    - "history_lookback": (int) Number of previous 'agent_steps' entries to consider
                                          for context. If None, all available history is used.
                    - "resume_previous_chat": (bool) If True, attempts to resume the most recent
                                              chat entry for the thread_id, updating it instead
                                              of creating a new one.
                    - "store_response_custom_metadata": (bool) If True, stores custom metadata
                                              from the final LLM response in the chat history. Default is False.
                - "tool_choice": (str) Strategy for tool selection by the LLM. Default is "auto".
                - "tool_interrupt": (bool) If True, the agent will pause and return tool calls
                                    for user approval/modification before execution.
                - "parallel_tool_calls": (bool) If True, allows the LLM to request multiple tool calls
                                             in a single response. Default is False.
                - "updated_tool_calls": (Union[List[Dict], Dict]) 
                    - If a list, each item should be a dictionary with keys:
                        - "id": (str) The tool_call_id of the tool to update.
                        - "updated_arguments": (Dict) The new arguments for the tool.
                    This is used when resuming an interrupted chat to modify tool arguments for multiple tool calls.
                    - If a dict, it should be the argument dictionary for the first tool call only.
                    This is typically used when parallel tool calls are disabled and only the first tool call's arguments need to be updated.

        Returns:
            Dict[str, Any]:
                A dictionary containing the final response from the LLM, or an error message,
                along with the agent steps for the current turn.
                Example: {
                    "user_query": "...",
                    "final_response": "...",
                    "agent_steps": [...]
                }
        """
        if not self._model:
            raise ValueError("Model not set. Please set the model before invoking the agent.")

        if messages and isinstance(messages, str):
            messages = [self.format_content_with_role(messages)]

        config = config or {}
        configurable: dict = config.get("configurable", {})
        thread_id = configurable.get("thread_id", None)
        history_lookback = configurable.get("history_lookback", None)
        resume_previous_chat = configurable.get("resume_previous_chat", False)
        store_response_custom_metadata = configurable.get("store_response_custom_metadata", False)

        tool_choice = config.get("tool_choice", "auto")
        tool_interrupt = config.get("tool_interrupt", False)
        parallel_tool_calls = config.get("parallel_tool_calls", not tool_interrupt)
        updated_tool_calls: List[Dict[str, Any]] = config.get("updated_tool_calls", None)
        if not updated_tool_calls:
            updated_tool_calls = []
        elif isinstance(updated_tool_calls, dict):
            updated_tool_calls = [{"id": self.first_tool_id_placeholder, "updated_arguments": updated_tool_calls}]


        max_tool_call_iterations = self._agent_config_kwargs.get("max_tool_call_iterations", 25)

        current_turn_messages: List[Dict[str, Any]] = [] # Messages generated during the current user query's turn
        conversation_history: List[Dict[str, Any]] = [] # Full chronological history for LLM context
        if self._system_prompt:
            # Prepend system prompt if set, ensuring it's the first message for the LLM
            # Note: This is for the LLM's context, not stored in DB history per user request
            conversation_history.append(self.format_content_with_role(self._system_prompt, "system"))

        current_entry_id: Optional[int] = None
        initial_user_query: Optional[str] = None

        # Determine if we are storing chat (thread_id is mandatory for history and _chat_history_manager must exist)
        store_chat = bool(thread_id and self._chat_history_manager)
        log.debug(f"[Agent] Chat history storage enabled: {store_chat}")

        most_recent_entry_id = most_recent_entry_data = None
        if store_chat:
            most_recent_entry_id, most_recent_entry_data = await self._chat_history_manager.get_most_recent_chat_entry(thread_id)

            if most_recent_entry_data:
                most_recent_agent_steps = most_recent_entry_data.get("agent_steps", [])
                pending_tool_calls = most_recent_agent_steps[-1].get("tool_calls", None) if most_recent_agent_steps else None

                if pending_tool_calls and messages:
                    log.info(f"[Agent] New query received while chat {most_recent_entry_id} was interrupted. Deleting old interrupted state.")
                    await self._chat_history_manager.delete_chat_entry(most_recent_entry_id, thread_id)
                    most_recent_entry_id = most_recent_entry_data = None
                    resume_previous_chat = False

                elif pending_tool_calls or resume_previous_chat:
                    resume_previous_chat = True
                    current_entry_id = most_recent_entry_id
                    current_turn_messages.extend(most_recent_agent_steps)

                    if pending_tool_calls:
                        log.info(f"[Agent] Resuming interrupted chat {current_entry_id} for thread '{thread_id}'.")
                        updated_tool_calls_dict = {tc["id"]: tc["updated_arguments"] for tc in updated_tool_calls}

                        if len(pending_tool_calls)==1 and self.first_tool_id_placeholder in updated_tool_calls_dict:
                            updated_tool_calls_dict[pending_tool_calls[0]["id"]] = updated_tool_calls_dict[self.first_tool_id_placeholder]
                            log.info(f"  [Agent] Mapped placeholder ID to actual tool_call_id '{pending_tool_calls[0]['id']}', for single tool call update.")

                        tool_execution_tasks = []
                        for tool_call in pending_tool_calls:
                            if tool_call["id"] in updated_tool_calls_dict:
                                # Update tool call arguments with user-provided updates
                                reference_args = json.loads(tool_call["function"]["arguments"])
                                updated_tool_calls_dict[tool_call["id"]] = self.convert_value_type_of_candidate_as_given_in_reference(
                                                                                    reference=reference_args,
                                                                                    candidate=updated_tool_calls_dict[tool_call["id"]]
                                                                                )
                                tool_call["function"]["arguments"] = json.dumps(updated_tool_calls_dict[tool_call["id"]])
                                log.info(f"  [Agent] Applied user update for tool '{tool_call['function']['name']}' (ID: {tool_call['id']}).")

                            tool_execution_tasks.append(self._execute_tool_call(tool_call))

                        tool_outputs = await asyncio.gather(*tool_execution_tasks)
                        for tool_output, tool_call in zip(tool_outputs, pending_tool_calls):
                            tool_message = {
                                "tool_call_id": tool_call["id"],
                                "role": "tool",
                                "name": tool_call["function"]["name"],
                                "content": json.dumps(tool_output),
                            }
                            current_turn_messages.append(tool_message)

                        log.info(f"[Agent] Resuming interrupted chat {most_recent_entry_id} for thread '{thread_id}' with {len(current_turn_messages)} messages.")


        if messages:
            current_turn_messages.extend(messages)

        elif not current_turn_messages:
            log.error("[Agent] No messages provided and no previous chat to resume.")
            raise ValueError("Messages is None, and no previous chat to resume.")

        initial_user_query = current_turn_messages[0]["content"]


        if store_chat:
            if resume_previous_chat and history_lookback is not None:
                history_lookback += 1

            history_entries = await self._chat_history_manager.get_recent_history(thread_id, history_lookback)
            if resume_previous_chat and history_entries:
                history_entries.pop()

            for entry in history_entries:
                # Add previous agent_steps to conversation history for context
                conversation_history.extend(entry["agent_steps"])
            log.info(f"[Agent] Loaded {len(history_entries)} previous turns for context.")


        conversation_history.extend(current_turn_messages)
        iteration = 0
        final_llm_response_content: Optional[str] = None

        while iteration < max_tool_call_iterations:
            iteration += 1
            try:
                completion_params = {
                    "model": self._model,
                    "messages": conversation_history,
                    "temperature": self._temperature
                }

                if self._tools_json_schema:
                    completion_params["tools"] = self._tools_json_schema
                    completion_params["tool_choice"] = tool_choice
                    completion_params["parallel_tool_calls"] = parallel_tool_calls

                log.info(f"\n[Agent] Iteration {iteration}: Calling LLM with {len(conversation_history)} messages...")
                response = await asyncio.to_thread(self._client.chat.completions.create, **completion_params)
                response_message: ChatCompletionMessage = response.choices[0].message

                # Add LLM's message to current turn and full history
                current_turn_messages.append(response_message.model_dump(exclude_unset=True))
                conversation_history.append(response_message.model_dump(exclude_unset=True))

                if store_response_custom_metadata and response_message.content:
                    parsed_response = await self._json_output_parser(response_message.content)
                    if isinstance(parsed_response, dict) and "error" not in parsed_response:
                        current_turn_messages[-1]["response_custom_metadata"] = parsed_response

                if response_message.tool_calls:
                    log.info(f"[Agent] LLM requested {len(response_message.tool_calls)} tool call(s).")

                    # --- Tool Interrupt Logic ---
                    # Interrupt only if tool_interrupt flag is True
                    if tool_interrupt:
                        log.info("[Agent] Tool interrupt flag is ON. Interrupting for user approval.")
                        if store_chat:
                            if current_entry_id:
                                await self._chat_history_manager.update_chat_entry(
                                    entry_id=current_entry_id,
                                    thread_id=thread_id,
                                    agent_steps=current_turn_messages,
                                    final_response=None # Still interrupted
                                )
                            else:
                                current_entry_id = await self._chat_history_manager.add_chat_entry(
                                    thread_id=thread_id,
                                    user_query=initial_user_query,
                                    agent_steps=current_turn_messages,
                                    final_response=None # Mark as potentially interrupted or ongoing
                                )
                        return {
                            "user_query": initial_user_query,
                            "final_response": None,
                            "agent_steps": current_turn_messages
                        }

                    # --- Tool Execution Logic (if not interrupted or if resuming) ---
                    tool_calls_for_execution: List[ChatCompletionMessageToolCall] = response_message.tool_calls

                    # Execute all requested tool calls in parallel
                    tool_execution_tasks = [
                        self._execute_tool_call(tool_call)
                        for tool_call in tool_calls_for_execution
                    ]
                    tool_results = await asyncio.gather(*tool_execution_tasks)

                    # Add the outputs of the tool calls back to the conversation history
                    for i, tool_call in enumerate(tool_calls_for_execution):
                        tool_output = tool_results[i]
                        tool_message = {
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": tool_call.function.name,
                            "content": json.dumps(tool_output),
                        }
                        current_turn_messages.append(tool_message)
                        conversation_history.append(tool_message)
                    log.info(f"[Agent] Added {len(tool_results)} tool output(s) to history. Re-querying LLM.")
                    
                else:
                    # The LLM provided a final text response (no more tool calls requested)
                    log.info("[Agent] LLM provided a final text response.")
                    final_llm_response_content = response_message.content
                    break # Exit the loop, we have a final response

            except Exception as e:
                log.error(f"[Agent] An error occurred during ainvoke: {e}", exc_info=True)
                return {
                    "error": f"LLM interaction error: {e}",
                    "user_query": initial_user_query,
                    "final_response": None,
                    "agent_steps": current_turn_messages
                }

        # After loop, update DB if chat_saver is active and an entry was created/updated
        if store_chat:
            if current_entry_id:
                await self._chat_history_manager.update_chat_entry(
                    entry_id=current_entry_id,
                    thread_id=thread_id,
                    agent_steps=current_turn_messages,
                    final_response=final_llm_response_content
                )
            else:
                await self._chat_history_manager.add_chat_entry(
                    thread_id=thread_id,
                    user_query=initial_user_query,
                    agent_steps=current_turn_messages,
                    final_response=final_llm_response_content
                )


        if final_llm_response_content is None:
            return {
                "error": f"Max tool call iterations ({max_tool_call_iterations}) reached without a final response.",
                "user_query": initial_user_query,
                "final_response": None,
                "agent_steps": current_turn_messages
            }
        else:
            return {
                "user_query": initial_user_query,
                "final_response": final_llm_response_content,
                "agent_steps": current_turn_messages
            }


