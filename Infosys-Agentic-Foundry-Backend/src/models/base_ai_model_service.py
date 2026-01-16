# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import re
import ast
import json
import inspect
import asyncio
from abc import ABC, abstractmethod

from typing import get_origin, get_args, Literal, List, Dict, Any, Optional, Union, Callable
from openai.types.chat import ChatCompletionMessageToolCall

from src.database.repositories import ChatStateHistoryManagerRepository
from src.tools.mcp_tool_adapter import MCPToolAdapter
from src.utils.helper_functions import convert_value_type_of_candidate_as_given_in_reference
from telemetry_wrapper import logger as log


# --- Abstract Base Agent Class ---

class BaseAIModelService(ABC):
    """
    Abstract Base Class for AI Agents. Provides common functionalities like
    tool schema extraction, agent configuration, and tool execution.
    Concrete subclasses must implement the 'ainvoke' method.
    """

    def __init__(
        self,
        api_key: str,
        api_base: Optional[str] = None,
        api_version: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
        chat_history_manager: Optional[ChatStateHistoryManagerRepository] = None
    ):
        """
        Initializes the BaseAIModelService.

        Args:
            api_key: The API key for the chosen LLM provider.
            model: The specific model identifier (e.g., 'gpt-4o', 'gemini-pro', 'azure/gpt-4o').
            api_base: Optional API base URL (e.g., for Azure).
            api_version: Optional API version (e.g., for Azure).
            **llm_config_kwargs: Additional keyword arguments for the LLM client/completion method.
        """
        self._api_key = api_key
        self._api_base = api_base
        self._api_version = api_version
        self._model = model
        self._temperature = temperature
        self._chat_history_manager = chat_history_manager

        # Agent-specific state, to be set by create_agent
        self._system_prompt: Optional[str] = None
        self._tools_json_schema: List[Dict[str, Any]] = []
        self._tools_callable_instances: Dict[str, Callable] = {}
        self._agent_config_kwargs: Dict[str, Any] = {} # Stores agent-specific settings like max_tool_call_iterations

        # Additional keys
        self.first_tool_id_placeholder = "__first_tool_id__"


    # Helper methods

    @staticmethod
    async def _json_output_parser(content: str) -> Dict[str, Any]:
        """
        Parses JSON content from a string, handling markdown code blocks.
        Enhances robustness by attempting literal_eval if json.loads fails.
        """
        try:
            pattern = r"```json\s*([\s\S]*?)\s*```"
            match = re.search(pattern, content)
            if match:
                content = match.group(1).strip()
            return json.loads(content)
        except Exception as e:
            log.warning(f"JSONDecodeError: {e}. Attempting ast.literal_eval.")
            try:
                return ast.literal_eval(content)
            except Exception as e_literal:
                log.error(f"Failed to parse as JSON or Python literal: {e_literal}. Content: {content}")
                return {"error": f"Invalid JSON or Python literal format: {e_literal}"}

    @staticmethod
    def format_content_with_role(content: str, role: str = "user", **kwargs) -> Dict[str, str]:
        """
        Formats a message dictionary with the specified role and content.
        """
        kwargs.update({"role": role, "content": content})
        return kwargs

    # Utility to convert types of values in a dict based on a reference dict
    @staticmethod
    def convert_value_type_of_candidate_as_given_in_reference(reference: dict, candidate: dict) -> dict:
        """
        Convert the values of `candidate` dict to the types of the corresponding values in `reference` dict.
        Only keys present in both dicts are converted.

        Args:
            reference (dict): The dictionary with desired value types.
            candidate (dict): The dictionary whose values will be converted.

        Returns:
            dict: A new dictionary with converted value types.
        """
        result = convert_value_type_of_candidate_as_given_in_reference(reference, candidate)
        log.info(f"Converted candidate: {candidate} to {result} based on reference: {reference}")
        return result

    # --- Static Helper Methods for Tool Schema Extraction ---

    @staticmethod
    def _get_json_schema_type(annotation: Any) -> Dict[str, Any]:
        """
        Converts a Python type hint to a JSON schema type definition.
        Handles Literal, List, Dict, Optional, and basic types.
        """
        origin = get_origin(annotation)
        args = get_args(annotation)

        if origin is Literal:
            return {"type": "string", "enum": list(args)}
        elif origin is List:
            if args:
                item_schema = BaseAIModelService._get_json_schema_type(args[0])
                return {"type": "array", "items": item_schema}
            else:
                return {"type": "array", "items": {"type": "string"}}
        elif origin is Dict:
            return {"type": "object", "additionalProperties": True}
        elif origin is Union:
            # Filter out NoneType if present (for Optional[X] -> Union[X, None])
            non_none_args = [arg for arg in args if arg is not type(None)]

            if not non_none_args:
                return {"type": "null"} # Union[None, None] or just None
            elif len(non_none_args) == 1:
                # If it's effectively Optional[X] or just X, return schema for X
                return BaseAIModelService._get_json_schema_type(non_none_args[0])
            else:
                # For true Union types (e.g., Union[str, dict]), use 'oneOf'
                one_of_schemas = [BaseAIModelService._get_json_schema_type(arg) for arg in non_none_args]
                return {"oneOf": one_of_schemas}
        elif annotation is str:
            return {"type": "string"}
        elif annotation is int:
            return {"type": "integer"}
        elif annotation is float:
            return {"type": "number"}
        elif annotation is bool:
            return {"type": "boolean"}
        elif annotation is type(None):
            return {"type": "null"}
        elif annotation is Any:
            return {} # Any type
        else:
            # Fallback for custom classes or other unhandled types.
            return {"type": "object"}

    @staticmethod
    def extract_tool_schema(func: Union[Callable, MCPToolAdapter]) -> Dict[str, Any]:
        """
        Extracts an OpenAI-compatible tool schema from a Python function
        using inspect and basic docstring parsing.
        """
        if isinstance(func, MCPToolAdapter):
            return func.get_ai_tool_schema(func.tool)

        signature = inspect.signature(func)
        description = inspect.getdoc(func)
        function_description = description.split('\n')[0].strip() if description else func.__name__

        tool_properties = {}
        required_params = []

        for name, param in signature.parameters.items():
            if param.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
                param_schema = BaseAIModelService._get_json_schema_type(param.annotation)
                if param.default is not inspect.Parameter.empty:
                    param_schema["default"] = param.default
                else:
                    required_params.append(name)
                tool_properties[name] = param_schema
            else:
                raise ValueError(
                    f"Unsupported parameter kind: {param.kind} for parameter {name}. "
                    f"Supported kinds are: {inspect.Parameter.POSITIONAL_OR_KEYWORD}."
                )

        return {
            "type": "function",
            "function": {
                "name": func.__name__,
                "description": function_description,
                "parameters": {
                    "type": "object",
                    "properties": tool_properties,
                    "required": required_params,
                },
            },
        }

    def get_copy(self) -> "BaseAIModelService":
        # Create a new instance of the same class with the original init parameters
        new_obj = self.__class__(
                api_key=self._api_key,
                api_base=self._api_base,
                api_version=self._api_version,
                model=self._model,
                temperature = self._temperature,
                chat_history_manager=self._chat_history_manager
            )
        # Copy over mutable runtime state (shallow copy is enough)
        new_obj._system_prompt = self._system_prompt
        new_obj._tools_json_schema = list(self._tools_json_schema)
        new_obj._tools_callable_instances = dict(self._tools_callable_instances)
        new_obj._agent_config_kwargs = dict(self._agent_config_kwargs)
        # Reuse same underlying client (no deepcopy)
        if hasattr(self, "_client"):
            new_obj._client = self._client
        return new_obj

    def create_agent(
        self,
        system_prompt: Optional[str] = None,
        tools: Optional[List[Union[Callable, MCPToolAdapter]]] = None,
        model: str = None,
        temperature: float = 0.0,
        **agent_config_kwargs: Any
    ) -> "BaseAIModelService":
        """
        Creates a new agent instance (a copy of the current one) with
        the specified system prompt and tools.

        Args:
            system_prompt: The system prompt (initial instructions) for the agent.
            tools: A list of callable Python functions that the agent can use as tools.
            temperature: The sampling temperature for the LLM.
            **agent_config_kwargs: Additional agent-specific configuration (e.g., max_tool_call_iterations).

        Returns:
            A new BaseAIModelService instance configured with the provided prompt and tools.
        """
        new_agent = self.get_copy()
        if model:
            new_agent._model = model
        if not new_agent._model:
            raise ValueError("Model must be specified when creating an agent.")

        new_agent._system_prompt = system_prompt
        new_agent._temperature = temperature
        new_agent._agent_config_kwargs = agent_config_kwargs

        new_agent._tools_json_schema = []
        new_agent._tools_callable_instances = {}
        if tools:
            for func in tools:
                new_agent._tools_json_schema.append(self.extract_tool_schema(func))

                if isinstance(func, MCPToolAdapter):
                    func = func.create_callable_wrapper(func)
                new_agent._tools_callable_instances[func.__name__] = func

        return new_agent

    async def _execute_tool_call(self, tool_call: ChatCompletionMessageToolCall | dict) -> Dict[str, Any]:
        """
        Executes a single tool call requested by the LLM.
        Handles both synchronous and asynchronous tool functions.
        `tool_call` type depends on the LLM client (e.g., litellm.utils.ToolCall or openai.types.chat.ChatCompletionMessageToolCall).
        """
        # Extract function name and arguments dynamically based on the tool_call object structure
        # This assumes a structure similar to OpenAI's tool_calls
        if not isinstance(tool_call, dict):
            tool_call = tool_call.model_dump(exclude_unset=True) # Ensure all fields are populated

        # function_name = tool_call.function.name
        function_name = tool_call["function"]["name"]

        
        try:
            # function_args = json.loads(tool_call.function.arguments)
            function_args = json.loads(tool_call["function"]["arguments"])
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON arguments for tool '{function_name}': {tool_call['function']['arguments']}"}


        if function_name not in self._tools_callable_instances:
            return {"error": f"Function '{function_name}' not found in available tools."}

        func_to_call = self._tools_callable_instances[function_name]

        try:
            log.info(f"  [Agent] Executing tool: {function_name} with args: {function_args}")
            if asyncio.iscoroutinefunction(func_to_call):
                result = await func_to_call(**function_args)
            else:
                result = await asyncio.to_thread(func_to_call, **function_args)
            return result
        except Exception as e:
            log.info(f"  [Agent] Error executing tool '{function_name}': {e}")
            return {"error": f"Error executing tool '{function_name}': {str(e)}"}

    @abstractmethod
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
        pass


