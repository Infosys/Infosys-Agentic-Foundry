# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import json
import asyncio
from typing import Any, Dict, List, Optional, AsyncGenerator, Literal

from openai import AzureOpenAI, AsyncAzureOpenAI
from openai.types.chat import ChatCompletionChunk
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageToolCall

from src.models.base_ai_model_service import BaseAIModelService
from src.database.repositories import ChatStateHistoryManagerRepository

from telemetry_wrapper import logger as log

# Define a type for the streaming chunks for better clarity
# You can customize this structure to fit your frontend's needs
StreamChunkType = Dict[str, Any]

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

        # Asynchronous client (New: For astream)
        self._async_client = AsyncAzureOpenAI(
            api_key=self._api_key,
            api_version=self._api_version,
            azure_endpoint=self._api_base
        )
        log.info(f"[AzureAIModelService] Initialized.")

    async def astream(
        self,
        messages: Optional[List[Dict[str, str]]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
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
            raise ValueError("Model not set.")

        if messages and isinstance(messages, str):
            messages = [self.format_content_with_role(messages)]

        # --- 1. Setup Configuration (Same as ainvoke) ---
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

        current_turn_messages: List[Dict[str, Any]] = []
        conversation_history: List[Dict[str, Any]] = []

        # --- 2. Load History (Same as ainvoke) ---
        if self._system_prompt:
            conversation_history.append(self.format_content_with_role(self._system_prompt, "system"))

        current_entry_id: Optional[int] = None
        initial_user_query: Optional[str] = None

        store_chat = bool(thread_id and self._chat_history_manager)
        log.debug(f"[Agent Stream] Chat history storage enabled: {store_chat}")

        most_recent_entry_id = most_recent_entry_data = None
        if store_chat:
            most_recent_entry_id, most_recent_entry_data = await self._chat_history_manager.get_most_recent_chat_entry(thread_id)

            if most_recent_entry_data:
                most_recent_agent_steps = most_recent_entry_data.get("agent_steps", [])
                pending_tool_calls = most_recent_agent_steps[-1].get("tool_calls", None) if most_recent_agent_steps else None

                if pending_tool_calls and messages:
                    log.info(f"[Agent Stream] New query received while chat {most_recent_entry_id} was interrupted. Deleting old interrupted state.")
                    await self._chat_history_manager.delete_chat_entry(most_recent_entry_id, thread_id)
                    most_recent_entry_id = most_recent_entry_data = None
                    resume_previous_chat = False

                elif pending_tool_calls or resume_previous_chat:
                    resume_previous_chat = True
                    current_entry_id = most_recent_entry_id
                    current_turn_messages.extend(most_recent_agent_steps)

                    if pending_tool_calls:
                        log.info(f"[Agent Stream] Resuming interrupted chat {current_entry_id} for thread '{thread_id}'.")
                        updated_tool_calls_dict = {tc["id"]: tc["updated_arguments"] for tc in updated_tool_calls}

                        if len(pending_tool_calls)==1 and self.first_tool_id_placeholder in updated_tool_calls_dict:
                            updated_tool_calls_dict[pending_tool_calls[0]["id"]] = updated_tool_calls_dict[self.first_tool_id_placeholder]
                            log.info(f"  [Agent Stream] Mapped placeholder ID to actual tool_call_id '{pending_tool_calls[0]['id']}', for single tool call update.")

                        # Check if user updated arguments or just approved
                        has_updates = bool(updated_tool_calls_dict)
                        if has_updates:
                            yield {"raw": {"tool_interrupt_update_argument": "User updated the tool arguments."}, "content": "User updated the tool arguments. Updating the agent state accordingly."}
                        else:
                            yield {"raw": {"tool_verifier": "User approved the tool execution."}, "content": "User approved the tool execution by clicking the thumbs up button."}

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
                                log.info(f"  [Agent Stream] Applied user update for tool '{tool_call['function']['name']}' (ID: {tool_call['id']}).")

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
                            yield {"raw": {"Tool Name": tool_call["function"]["name"], "Tool Output": tool_output}, "content": f"Tool {tool_call['function']['name']} returned: {tool_output}"}
                            yield {"Node Name": "Tool Call", "Status": "Completed", "Tool Name": tool_call["function"]["name"]}

                        
                        log.info(f"[Agent] Resuming interrupted chat {most_recent_entry_id} for thread '{thread_id}' with {len(current_turn_messages)} messages.")


        if messages:
            current_turn_messages.extend(messages)
        elif not current_turn_messages:
            log.error("[Agent Stream] No messages provided and no previous chat to resume.")
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
        yield {"Node Name": "Thinking...", "Status": "Started"}
        while iteration < max_tool_call_iterations:
            iteration += 1
            # yield {"Node Name": "Thinking...", "Status": "Started"}
            try:
                completion_params = {
                    "model": self._model,
                    "messages": conversation_history,
                    "temperature": self._temperature,
                    # "stream": True  # ENABLE STREAMING
                }

                if self._tools_json_schema:
                    completion_params["tools"] = self._tools_json_schema
                    completion_params["tool_choice"] = tool_choice
                    completion_params["parallel_tool_calls"] = parallel_tool_calls

                log.info(f"[Agent Stream] Iteration {iteration}: Requesting stream...")
                # Emit Thinking started event
                
                # Use ASYNC client here
                stream = await self._async_client.chat.completions.create(**completion_params)
                response_message: ChatCompletionMessage = stream.choices[0].message
                # # Storage for reconstructing the streamed message
                # collected_content: List[str] = []
                # collected_tool_calls: Dict[int, Dict[str, str]] = {}  # Index -> {id, name, arguments}

                # # --- 4. Stream Chunk Processing --- (aggregate tokens, do NOT emit each delta)
                # async for chunk in stream:
                #     delta = chunk.choices[0].delta

                #     # A. Handle Text Content - Collect but don't yield yet
                #     if delta.content:
                #         collected_content.append(delta.content)

                #     # B. Handle Tool Call Fragments
                #     if delta.tool_calls:
                #         for tc in delta.tool_calls:
                #             idx = tc.index
                #             if idx not in collected_tool_calls:
                #                 collected_tool_calls[idx] = {
                #                     "id": tc.id,
                #                     "name": tc.function.name,
                #                     "arguments": ""
                #                 }
                #             # Append argument fragments
                #             if tc.function.arguments:
                #                 collected_tool_calls[idx]["arguments"] += tc.function.arguments
                # Add LLM's message to current turn and full history
                current_turn_messages.append(response_message.model_dump(exclude_unset=True))
                conversation_history.append(response_message.model_dump(exclude_unset=True))
                
                if store_response_custom_metadata and response_message.content:
                    parsed_response = await self._json_output_parser(response_message.content)
                    if isinstance(parsed_response, dict) and "error" not in parsed_response:
                        current_turn_messages[-1]["response_custom_metadata"] = parsed_response

                
                # --- 6. Handle Tool Execution or Exit ---
                if response_message.tool_calls:
                    yield ({"raw": {"thinking_completed": "Thinking completed. Proceeding to tool calls."}, "content": "Thinking completed. Proceeding to tool calls."})
                    log.info(f"[Agent Stream] Collected {len(response_message.tool_calls)} tool calls.")

                    if tool_interrupt:
                        # Handle interrupt logic - structured interrupt request
                        log.info("[Agent] Tool interrupt flag is ON. Interrupting for user approval.")
                        
                        # Emit Tool Call Started for each pending tool call before interrupt
                        for tool_call in response_message.tool_calls:
                            try:
                                tool_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                            except json.JSONDecodeError:
                                tool_args = tool_call.function.arguments
                            
                            tool_name = tool_call.function.name
                            yield {"Node Name": "Tool Call", "Status": "Started", "Tool Name": tool_name, "Tool Arguments": tool_args if isinstance(tool_args, dict) else {"raw": tool_args}}
                            
                            # Tool call announcement content
                            if tool_args and isinstance(tool_args, dict):
                                args_str = ", ".join(f"{k}={v}" for k, v in tool_args.items())
                                yield {"raw": {"content_display": f"Agent called the tool '{tool_name}', passing arguments: {args_str}."}, "content": f"Agent called the tool '{tool_name}', passing arguments: {args_str}."}
                            else:
                                yield {"raw": {"content_display": f"Agent called the tool '{tool_name}', passing no arguments."}, "content": f"Agent called the tool '{tool_name}', passing no arguments."}
                        
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
                        yield ({"raw": {"tool_verifier": "Please confirm tool execution."}, "content": "Tool execution requires confirmation. Please approve to proceed."})
                        yield {"Node Name": "Thinking...", "Status": "Completed"}
                       

                        yield {
                            "user_query": initial_user_query,
                            "final_response": None,
                            "agent_steps": current_turn_messages
                        }
                        return

                    tool_calls_for_execution: List[ChatCompletionMessageToolCall] = response_message.tool_calls

                    
                    for tool_call in tool_calls_for_execution:
                        # Parse arguments for display
                        try:
                            tool_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                        except json.JSONDecodeError:
                            tool_args = tool_call.function.arguments
                        
                        tool_name = tool_call.function.name
                        
                        # Emit Tool Call Started event
                        yield {"Node Name": "Tool Call", "Status": "Started", "Tool Name": tool_name, "Tool Arguments": tool_args if isinstance(tool_args, dict) else {"raw": tool_args}}

                        # Tool call announcement content (kept separate like other agents)
                        if tool_args and isinstance(tool_args, dict):
                            args_str = ", ".join(f"{k}={v}" for k, v in tool_args.items())
                            yield {"raw": {"content_display": f"Agent called the tool '{tool_name}', passing arguments: {args_str}."}, "content": f"Agent called the tool '{tool_name}', passing arguments: {args_str}."}
                        else:
                            yield {"raw": {"content_display": f"Agent called the tool '{tool_name}', passing no arguments."}, "content": f"Agent called the tool '{tool_name}', passing no arguments."}
                    # Execute Tools (Parallel)
                    tool_execution_tasks = [
                        self._execute_tool_call(tool_call)
                        for tool_call in tool_calls_for_execution
                    ]
                    tool_results = await asyncio.gather(*tool_execution_tasks)
                    
                    # Append Tool Outputs and yield results
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
                        
                        # Emit Tool Result (raw + content pattern)
                        yield {"raw": {"Tool Name": tool_call.function.name, "Tool Output": tool_output}, "content": f"Tool {tool_call.function.name} returned: {tool_output}"}
                        # Emit Tool Call Completed status
                        yield {"Node Name": "Tool Call", "Status": "Completed", "Tool Name": tool_call.function.name}
                    log.info(f"[Agent] Added {len(tool_results)} tool output(s) to history. Re-querying LLM.")
                    

                else:
                    # No tools called, treat this iteration's response as final
                    log.info("[Agent Stream] Final response complete (no tools).")
                    # Emit Thinking completion event only when no tool calls
                    # yield ({"raw": {"Final_response": "Thinking completed proceeding to final response"}, "content": "Thinking completed proceeding to final response"}) 
                    yield {"Node Name": "Thinking...", "Status": "Completed"}
                    final_llm_response_content = response_message.content
                    break
            except Exception as e:
                log.error(f"[Agent Stream] An error occurred during astream: {e}", exc_info=True)
                yield {
                    "error": f"LLM interaction error: {e}",
                    "user_query": initial_user_query,
                    "final_response": None,
                    "agent_steps": current_turn_messages
                }
                return
        # --- 7. Save Chat History ---
        if store_chat:
             # Use the same logic as ainvoke to save/update DB
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
            yield {
                "error": f"Max tool call iterations ({max_tool_call_iterations}) reached without a final response.",
                "user_query": initial_user_query,
                "final_response": None,
                "agent_steps": current_turn_messages
            }
            return
        else:
            yield {
                "user_query": initial_user_query,
                "final_response": final_llm_response_content,
                "agent_steps": current_turn_messages
            }
            return

    # Helper method for tool execution using Dict (since we reconstructed manually)
    async def _execute_tool_call_dict(self, tool_call: Dict[str, Any]) -> Any:
        # Simple wrapper if your original _execute_tool_call expects an object
        # If your original handles dicts, you can just use that.
        # This simulates a ToolCall object if needed or just passes dict
        from collections import namedtuple
        Function = namedtuple('Function', ['name', 'arguments'])
        ToolCall = namedtuple('ToolCall', ['id', 'function'])

        tc_obj = ToolCall(
            id=tool_call['id'],
            function=Function(
                name=tool_call['function']['name'],
                arguments=tool_call['function']['arguments']
            )
        )
        return await self._execute_tool_call(tc_obj)

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
