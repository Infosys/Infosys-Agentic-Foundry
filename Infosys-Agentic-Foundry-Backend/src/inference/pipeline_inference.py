from src.inference.abstract_base_inference import AbstractBaseInference
from src.inference.inference_utils import InferenceUtils
from src.database.services import PipelineService
from typing import Dict, List, Any, Optional, AsyncGenerator, Tuple, Literal
from dataclasses import dataclass, field
from fastapi import HTTPException
from src.utils.secrets_handler import current_user_email
from src.schemas import AgentInferenceRequest
from src.prompts.prompts import CONDITION_EVALUATION_PROMPT, OUTPUT_FORMATTING_PROMPT
import json
import time
import re
from src.inference.centralized_agent_inference import CentralizedAgentInference
import uuid
from telemetry_wrapper import logger as log

def _serialize_messages(messages: Any) -> Any:
    """
    Recursively convert LangChain/LangGraph message objects to JSON-serializable dictionaries.
    Handles AIMessage, HumanMessage, ToolMessage, and other message types.
    """
    if messages is None:
        return None
    
    if isinstance(messages, list):
        return [_serialize_messages(msg) for msg in messages]
    
    if isinstance(messages, dict):
        return {k: _serialize_messages(v) for k, v in messages.items()}
    
    # Check if it's a LangChain message object (has content attribute)
    if hasattr(messages, 'content'):
        serialized = {
            "type": messages.__class__.__name__,
            "content": messages.content
        }
        # Add additional_kwargs if present
        if hasattr(messages, 'additional_kwargs') and messages.additional_kwargs:
            serialized["additional_kwargs"] = _serialize_messages(messages.additional_kwargs)
        # Add tool_calls if present (for AIMessage)
        if hasattr(messages, 'tool_calls') and messages.tool_calls:
            serialized["tool_calls"] = _serialize_messages(messages.tool_calls)
        # Add tool_call_id if present (for ToolMessage)
        if hasattr(messages, 'tool_call_id') and messages.tool_call_id:
            serialized["tool_call_id"] = messages.tool_call_id
        # Add name if present
        if hasattr(messages, 'name') and messages.name:
            serialized["name"] = messages.name
        # Add response_metadata if present
        if hasattr(messages, 'response_metadata') and messages.response_metadata:
            serialized["response_metadata"] = _serialize_messages(messages.response_metadata)
        return serialized
    
    # For primitive types or already serializable objects
    try:
        json.dumps(messages)
        return messages
    except (TypeError, ValueError):
        return str(messages)

@dataclass
class ExecutionContext:
    """Holds the context for a pipeline execution."""
    execution_id: str
    pipeline_id: str
    pipeline_definition: Dict[str, Any]
    session_id: str
    model_name: str
    input_query: str
    
    # Input data from input node config schema
    input_data: Dict[str, Any] = field(default_factory=dict)
    
    # Runtime state
    completed_nodes: List[str] = field(default_factory=list)
    pending_nodes: List[str] = field(default_factory=list)
    node_outputs: Dict[str, Any] = field(default_factory=dict)
    node_states: Dict[str, Dict] = field(default_factory=dict)  # Stores thread_id per node for conversation continuity
    current_query: str = ""
    is_paused: bool = False
    pause_node_id: Optional[str] = None
    pause_type: Optional[str] = None  # 'tool_verifier' or 'plan_verifier'
    pause_data: Optional[Dict] = None  # Data about the pause (pending_plan or pending_tool_calls)
    
    def get_nodes(self) -> List[Dict]:
        """Get list of nodes from definition."""
        return self.pipeline_definition.get('nodes', [])
    
    def get_edges(self) -> List[Dict]:
        """Get list of edges from definition."""
        return self.pipeline_definition.get('edges', [])
    
    def get_node(self, node_id: str) -> Optional[Dict]:
        """Get a specific node by ID."""
        for node in self.get_nodes():
            if node['node_id'] == node_id:
                return node
        return None
    
    def get_outgoing_edges(self, node_id: str) -> List[Dict]:
        """Get all edges originating from a node."""
        return [e for e in self.get_edges() if e['source_node_id'] == node_id]
    
    def get_input_node(self) -> Optional[Dict]:
        """Get the input node."""
        for node in self.get_nodes():
            if node['node_type'] == 'input':
                return node
        return None
    
    def get_output_node(self) -> Optional[Dict]:
        """Get the output node if it exists."""
        for node in self.get_nodes():
            if node['node_type'] == 'output':
                return node
        return None
    
    def get_agent_config(self, node: Dict) -> Dict:
        """Get the agent config from a node, handling new schema."""
        config = node.get('config', {})
        if isinstance(config, dict):
            return config
        return {}
    
    def get_accessible_inputs(self, node: Dict) -> Dict[str, Any]:
        """
        Get the filtered inputs based on accessible_inputs config.
        
        Args:
            node: The agent node
            
        Returns:
            Dict of accessible input key-value pairs
        """
        config = self.get_agent_config(node)
        accessible_inputs_config = config.get('accessible_inputs', {})
        
        # Get input_keys from the config
        input_keys = accessible_inputs_config.get('input_keys', ['all']) if isinstance(accessible_inputs_config, dict) else ['all']
        
        # If 'all' or empty, return all input data
        if not input_keys or 'all' in input_keys:
            return self.input_data.copy()
        
        # Filter to only specified keys
        return {k: v for k, v in self.input_data.items() if k in input_keys}


class PipelineInference(AbstractBaseInference):
    def __init__(self, 
        inference_utils: InferenceUtils,        
        pipeline_service: PipelineService,
        centralized_agent_inference: CentralizedAgentInference
    ):
        super().__init__(inference_utils)
        self.pipeline_service = pipeline_service
        self.centralized_agent_inference = centralized_agent_inference

    async def _get_mcp_tools_instances(self, tool_ids: List[str] = []) -> list:
        """
        Retrieves MCP tool instances based on the provided tool IDs.
        Pipeline uses centralized_agent_inference for tool handling.
        
        Args:
            tool_ids (List[str], optional): List of tool IDs. Defaults to [].
            
        Returns:
            list: List of MCP tool records/instances.
        """
        return await super()._get_mcp_tools_instances(tool_ids)

    async def _get_next_node(self, condition: str, next_node_ids: List[str], llm: Any, agent_response: str, input_query: str) -> str:
        """
        Use LLM to determine the next node based on condition evaluation.
        
        Args:
            condition: The routing condition to evaluate
            next_node_ids: List of possible next nodes in "node_id node_name" format
            llm: The LLM instance to use for evaluation
            agent_response: The current agent response to evaluate against
            input_query: The original user query
            
        Returns:
            str: The selected node_id
        """
        prompt = CONDITION_EVALUATION_PROMPT.format(
            agent_response=agent_response,
            routing_condition=condition,
            current_query=input_query,
            target_nodes=", ".join(next_node_ids)
        )
        response = await llm.ainvoke(prompt)
        return response.content.strip()

    async def _format_output(self, output: Any, output_schema: str, llm: Any) -> Any:
        """
        Format the pipeline output according to the specified schema.
        
        Args:
            output: The output to format
            output_schema: The desired output schema
            llm: The LLM instance to use for formatting
            
        Returns:
            Any: The formatted output (JSON if applicable)
        """
        prompt = OUTPUT_FORMATTING_PROMPT.format(
            pipeline_outputs=output,
            output_schema=output_schema
        )
        response = await llm.ainvoke(prompt)
        response_text = response.content.strip()
        return self._parse_json_response(response_text)

    def _parse_json_response(self, response_text: str) -> Any:
        """
        Parse JSON from LLM response, handling markdown code blocks and various formats.
        
        Args:
            response_text: The raw response text from LLM
            
        Returns:
            Any: Parsed JSON object (dict, list, or primitive)
            
        Raises:
            ValueError: If JSON cannot be parsed after all cleanup attempts
        """
        if not response_text or not isinstance(response_text, str):
            raise ValueError("Empty or invalid response text")
        
        cleaned = response_text.strip()
        
        # Try direct parsing first (most efficient path)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        
        # Remove markdown code block markers (various formats)
        # Handle: ```json, ```JSON, ```Json, ``` with newlines
        code_block_patterns = [
            r'^```json\s*\n?(.*?)\n?```$',  # ```json ... ```
            r'^```JSON\s*\n?(.*?)\n?```$',  # ```JSON ... ```
            r'^```\s*\n?(.*?)\n?```$',       # ``` ... ```
        ]
        
        for pattern in code_block_patterns:
            match = re.match(pattern, cleaned, re.DOTALL | re.IGNORECASE)
            if match:
                extracted = match.group(1).strip()
                try:
                    return json.loads(extracted)
                except json.JSONDecodeError:
                    continue
        
        # Fallback: Remove code block markers with simple string replacement
        for marker in ['```json', '```JSON', '```Json', '```']:
            cleaned = cleaned.replace(marker, '')
        cleaned = cleaned.strip()
        
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        
        # Try to extract JSON object or array from the text
        # Look for outermost { } or [ ]
        json_obj_match = re.search(r'(\{.*\})', cleaned, re.DOTALL)
        if json_obj_match:
            try:
                return json.loads(json_obj_match.group(1))
            except json.JSONDecodeError:
                pass
        
        json_arr_match = re.search(r'(\[.*\])', cleaned, re.DOTALL)
        if json_arr_match:
            try:
                return json.loads(json_arr_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # If all parsing attempts fail, raise an error with context
        # raise ValueError(f"Could not parse JSON from response: {response_text[:200]}...")
        return cleaned

    def _build_pipeline_maps(self, pipeline_definition: Dict) -> tuple:
        """
        Build lookup maps from pipeline definition for efficient access.
        
        Args:
            pipeline_definition: The pipeline definition containing nodes and edges
            
        Returns:
            tuple: (node_map, node_name_map, edges_by_source)
                - node_map: Dict mapping node_id to node object
                - node_name_map: Dict mapping node_id to node_name
                - edges_by_source: Dict mapping source_node_id to list of target_node_ids
        """
        nodes = pipeline_definition.get('nodes', [])
        edges = pipeline_definition.get('edges', [])
        
        node_map = {node['node_id']: node for node in nodes}
        node_name_map = {node['node_id']: node.get('node_name', node['node_id']) for node in nodes}
        
        edges_by_source = {}
        for edge in edges:
            source_id = edge['source_node_id']
            target_id = edge['target_node_id']
            if source_id not in edges_by_source:
                edges_by_source[source_id] = []
            edges_by_source[source_id].append(target_id)
        
        return node_map, node_name_map, edges_by_source

    def _get_next_node_ids_with_names(self, node_id: str, edges_by_source: Dict, node_name_map: Dict) -> List[str]:
        """
        Get outgoing node IDs with their names for condition evaluation.
        
        Args:
            node_id: The current node ID
            edges_by_source: Dict mapping source_node_id to list of target_node_ids
            node_name_map: Dict mapping node_id to node_name
            
        Returns:
            List[str]: List of "node_id node_name" strings
        """
        target_ids = edges_by_source.get(node_id, [])
        return [f"{tid} {node_name_map.get(tid, tid)}" for tid in target_ids]

    def _select_next_node_id(self, llm_response: str, next_node_ids: List[str]) -> str:
        """
        Extract the selected node ID from LLM response.
        
        Args:
            llm_response: The LLM's response containing the selected node
            next_node_ids: List of "node_id node_name" strings
            
        Returns:
            str: The selected node_id
        """
        # Default to first node's id
        default_node_id = next_node_ids[0].split(" ")[0]
        
        for node_id_name in next_node_ids:
            node_id = node_id_name.split(" ")[0]
            if node_id in llm_response:
                return node_id
        
        return default_node_id

    def _build_agent_input(self, accessible_inputs: Any, input_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build agent input dictionary based on accessible_inputs configuration.
        
        Args:
            accessible_inputs: Configuration for which inputs the agent can access
            input_dict: Dictionary containing all available inputs
            
        Returns:
            Dict[str, Any]: Filtered input dictionary for the agent
        """
        input_keys = accessible_inputs.get('input_keys', ['all']) if isinstance(accessible_inputs, dict) else accessible_inputs
        
        if isinstance(input_keys, list):
            if len(input_keys) == 1 and input_keys[0] == 'all':
                return input_dict.copy()
            return {key: input_dict[key] for key in input_keys if key in input_dict}
        
        return input_dict.copy()

    def _build_query_with_inputs(self, input_query: str, agent_input: Dict[str, Any]) -> str:
        """
        Build the query string with additional inputs appended.
        
        Args:
            input_query: The original user query
            agent_input: Dictionary of inputs to append
            
        Returns:
            str: Query string with inputs appended
        """
        additional_inputs = [f"{k}: {v}" for k, v in agent_input.items() if k != 'query']
        if additional_inputs:
            return input_query + "\n" + "\n".join(additional_inputs)
        return input_query

    def _extract_reasoning_from_response(self, response: str) -> Optional[str]:
        """
        Extract reasoning content from LLM response with robust error handling.
        Handles various response formats including JSON with markdown code blocks.
        
        Args:
            response: The raw LLM response string
            
        Returns:
            Optional[str]: The extracted reasoning content, or None if extraction fails
        """
        if not response or not isinstance(response, str):
            return None
        
        try:
            # Clean up markdown code block markers
            cleaned_response = response.strip()
            
            # Remove various markdown code block formats
            for marker in ["```json", "```JSON", "```"]:
                cleaned_response = cleaned_response.replace(marker, "")
            
            cleaned_response = cleaned_response.strip()
            
            # Skip if empty after cleaning
            if not cleaned_response:
                return None
            
            # Try to parse as JSON
            try:
                parsed_json = json.loads(cleaned_response)
            except json.JSONDecodeError:
                # If JSON parsing fails, try to extract JSON from the response
                # Look for JSON-like structure in the response
                import re
                json_match = re.search(r'\{[^{}]*\}', cleaned_response, re.DOTALL)
                if json_match:
                    try:
                        parsed_json = json.loads(json_match.group())
                    except json.JSONDecodeError:
                        log.debug(f"Could not parse JSON from response: {cleaned_response[:100]}...")
                        return None
                else:
                    log.debug(f"No JSON structure found in response: {cleaned_response[:100]}...")
                    return None
            
            # Extract reasoning with fallback keys
            if isinstance(parsed_json, dict):
                # Try common keys for reasoning
                for key in ['reasoning', 'reason', 'explanation', 'rationale', 'thought']:
                    if key in parsed_json and parsed_json[key]:
                        return str(parsed_json[key])
                
                # If no reasoning key found, try to get any descriptive content
                for key in ['message', 'description', 'content', 'text']:
                    if key in parsed_json and parsed_json[key]:
                        return str(parsed_json[key])
            
            # If parsed_json is a string, return it directly
            if isinstance(parsed_json, str) and parsed_json:
                return parsed_json
            
            return None
            
        except Exception as e:
            log.warning(f"Error extracting reasoning from response: {e}")
            return None

    async def run(self,
                  inference_request: 'AgentInferenceRequest',
                  *,
                  agent_config: Optional[Dict] = None,
                  **kwargs
                ) -> Any:
        """
        Run the pipeline inference using the inference request.
        This wraps run_pipeline for compatibility with the abstract interface.
        
        Args:
            inference_request (AgentInferenceRequest): The agent inference request object.
            agent_config (Optional[dict], optional): Pre-fetched agent configuration. Defaults to None.
            **kwargs: Additional keyword arguments.
            
        Returns:
            Any: The result of the pipeline execution.
        """
        # Extract parameters from inference_request and call run_pipeline
        async for output in self.run_pipeline(
            pipeline_id=inference_request.agentic_application_id,
            session_id=inference_request.session_id,
            model_name=inference_request.model_name,
            input_query=inference_request.query,
            project_name=inference_request.project_name,
            reset_conversation=inference_request.reset_conversation,
            plan_verifier_flag=inference_request.plan_verifier_flag,
            is_plan_approved=inference_request.is_plan_approved,
            plan_feedback=inference_request.plan_feedback,
            tool_interrupt_flag=inference_request.tool_interrupt_flag,
            tool_feedback=inference_request.tool_feedback,
            context_flag=inference_request.context_flag,
            evaluation_flag=inference_request.evaluation_flag,
            validator_flag=inference_request.validator_flag,
            temperature=inference_request.temperature,
            role=inference_request.role
        ):
            yield output

    async def run_pipeline(
        self, 
        pipeline_id: str,
        session_id: str,
        model_name: str,
        input_query: str,
        project_name: str,
        reset_conversation: bool = False,
        plan_verifier_flag: bool = False,
        is_plan_approved: Literal["yes", "no", None] = None,
        plan_feedback: str = None,
        tool_interrupt_flag: bool = False,
        tool_feedback: str = None,
        context_flag: bool = True,
        evaluation_flag: bool = False,
        validator_flag: bool = False,
        temperature: float = 0.0,
        role: str = "user"
        ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Run the pipeline with the given ID and input query.
        Args:
            pipeline_id (str): The ID of the pipeline to run.
            session_id (str): The session ID for user context.
            model_name (str): The model name to use for inference.
            input_query (str): The input query string.
            project_name (str): The project name for scoping.
            reset_conversation (bool): Whether to reset the conversation history.
            plan_verifier_flag (bool): Flag for plan verification step.
            is_plan_approved (Literal["yes", "no", None]): User's decision on plan.
            plan_feedback (str): Feedback if plan is rejected.
            tool_interrupt_flag (bool): Flag for tool verification.
            tool_feedback (str): Feedback for tool verification.
            
        Yields:
            AsyncGenerator[Dict[str, Any], None]: Yields output data from the pipeline execution.
        """
        start_time = time.monotonic()
        execution_id = str(uuid.uuid4())
        
        # Create a run record
        try:
            await self.pipeline_service.create_pipeline_run(
                execution_id, 
                input_query, 
                pipeline_id=pipeline_id,
                session_id=session_id,
                status="pending"
            )
        except Exception as e:
            log.warning(f"Failed to create pipeline run record: {e}")

        # Get LLM and pipeline definition
        llm = await self.model_service.get_llm_model(model_name=model_name, temperature=temperature)
        pipeline = await self.pipeline_service.get_pipeline(pipeline_id)
        if not pipeline:
            raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' not found.")
        
        # Build efficient lookup maps
        node_map, node_name_map, edges_by_source = self._build_pipeline_maps(pipeline['pipeline_definition'])
        
        # Find the input node
        start_node = None
        for node in pipeline['pipeline_definition'].get('nodes', []):
            if node['node_type'] == 'input':
                start_node = node
                break
        
        if not start_node:
            raise HTTPException(status_code=400, detail="Pipeline has no input node defined.")
        
        final_response = None
        input_dict = {"query": input_query}
        step_order = 0
        
        # Mark run as running
        try:
            await self.pipeline_service.update_pipeline_run_status(execution_id, status="running")
        except Exception as e:
            log.warning(f"Failed to update pipeline run status: {e}")

        # Record input node step
        try:
            step_order += 1
            await self.pipeline_service.add_pipeline_step(
                run_id=execution_id,
                step_order=step_order,
                agent_id=None,
                step_data={
                    "node_type": "input",
                    "node_id": start_node['node_id'],
                    "input_query": input_query,
                    "input_data": input_dict,
                    "status": "completed"
                }
            )
        except Exception as e:
            log.warning(f"Failed to record input step: {e}")
        
        try:
            while True:
                # Get outgoing edges with node names for LLM context
                next_node_ids = self._get_next_node_ids_with_names(
                    start_node['node_id'], edges_by_source, node_name_map
                )
                condition_met = ""

                # Handle condition node - evaluate which path to take
                if start_node["node_type"] == "condition":
                    yield {"Node Name": "Evaluating Condition", "Status": "Started"}
                    condition_met = start_node.get('config', {}).get('condition', "")
                    
                    # Record condition node step
                    try:
                        step_order += 1
                        await self.pipeline_service.add_pipeline_step(
                            run_id=execution_id,
                            step_order=step_order,
                            agent_id=None,
                            step_data={
                                "node_type": "condition",
                                "node_id": start_node['node_id'],
                                "condition": condition_met,
                                "next_node_ids": next_node_ids,
                                "status": "evaluating"
                            }
                        )
                    except Exception as e:
                        log.warning(f"Failed to record condition step: {e}")
                    
                    
                # Validate that we have next nodes to proceed
                if not next_node_ids:
                    raise HTTPException(status_code=400, detail=f"No next node found from node '{start_node['node_id']}'.")
                
                # Determine which node to go to next
                if len(next_node_ids) > 1:
                    # Multiple outgoing edges - use LLM to decide based on condition
                    nxt_node_response = await self._get_next_node(
                        condition_met, next_node_ids, llm, final_response or "", input_query
                    )
                    
                    # Extract and yield reasoning from LLM response with robust error handling
                    reasoning_content = self._extract_reasoning_from_response(nxt_node_response)
                    if reasoning_content:
                        yield {"content": reasoning_content}
                    
                    yield {"Node Name": "Evaluating Condition", "Status": "Completed"}
                    current_node_id = self._select_next_node_id(nxt_node_response, next_node_ids)
                else:
                    current_node_id = next_node_ids[0].split(" ")[0]
                
                # Get current node using efficient lookup
                current_node = node_map.get(current_node_id)
                if not current_node:
                    raise HTTPException(status_code=400, detail=f"Node '{current_node_id}' not found in pipeline definition.")
                
                # Process based on node type
                if current_node['node_type'] == 'output':
                    yield {"Node Name": "Output Formatting...", "Status": "Started"}
                    output_schema = current_node.get('config', {}).get('output_schema', 'text')
                    if output_schema:
                        final_response = await self._format_output(final_response, output_schema, llm)
                    
                    # Record output node step
                    try:
                        step_order += 1
                        await self.pipeline_service.add_pipeline_step(
                            run_id=execution_id,
                            step_order=step_order,
                            agent_id=None,
                            step_data={
                                "node_type": "output",
                                "node_id": current_node['node_id'],
                                "output_schema": output_schema,
                                "response": final_response if isinstance(final_response, str) else json.dumps(final_response),
                                "status": "completed"
                            }
                        )
                    except Exception as e:
                        log.warning(f"Failed to record output step: {e}")
                    
                    yield {"Node Name": "Output Formatting...", "Status": "Completed"}
                    break 
                
                elif current_node['node_type'] == 'agent':
                    yield {"Node Name": "Running Agent", "Status": "Started"}

                    agent_config = current_node.get('config', {})
                    agent_id = agent_config.get('agent_id', '')
                    tool_verifier = agent_config.get('tool_verifier', False)
                    plan_verifier = agent_config.get('plan_verifier', False)
                    accessible_inputs = agent_config.get('accessible_inputs', {})
                    
                    # Build unique thread_id for this node to maintain conversation continuity
                    node_thread_id = f"{session_id}_{execution_id}_{current_node_id}"
                    
                    # Build agent input based on accessible_inputs configuration
                    agent_input = self._build_agent_input(accessible_inputs, input_dict)
                    updated_query_with_input = self._build_query_with_inputs(input_query, agent_input)
                    
                    inference_request = AgentInferenceRequest(
                        query=updated_query_with_input,
                        agentic_application_id=agent_id,
                        session_id=node_thread_id,
                        model_name=model_name,
                        reset_conversation=reset_conversation,
                        response_formatting_flag=False,
                        enable_streaming_flag=True,
                        context_flag=context_flag,
                        tool_verifier_flag=tool_verifier,
                        plan_verifier_flag=plan_verifier,
                        evaluation_flag=evaluation_flag,
                        validator_flag=validator_flag
                    )
                    
                    agent_response = None
                    async for response in self.centralized_agent_inference.run(
                        inference_request,
                        role=role
                    ):
                        if isinstance(response, dict) and "query" not in response:
                            yield response
                        agent_response = response
                    
                    # Extract final response from agent
                    final_response = agent_response.get('response', '') if isinstance(agent_response, dict) else str(agent_response)
                    
                    # Update state tracking
                    input_dict[current_node_id] = final_response
                    
                    # Record agent node step
                    try:
                        step_order += 1
                        step_payload = {
                            "node_type": "agent",
                            "node_id": current_node_id,
                            "agent_id": agent_id,
                            "input_query": updated_query_with_input,
                            "response": final_response,
                            "status": "completed",
                            "agent_config": {
                                "tool_verifier": tool_verifier,
                                "plan_verifier": plan_verifier,
                                "accessible_inputs": accessible_inputs
                            }
                        }
                        # Include executor_messages if available (serialize to avoid JSON errors)
                        if isinstance(agent_response, dict) and agent_response.get('executor_messages'):
                            step_payload["executor_messages"] = _serialize_messages(agent_response.get('executor_messages'))
                        await self.pipeline_service.add_pipeline_step(
                            run_id=execution_id,
                            step_order=step_order,
                            agent_id=agent_id,
                            step_data=step_payload
                        )
                    except Exception as e:
                        log.warning(f"Failed to record agent step: {e}")
                        
                    yield {"Node Name": "Running Agent", "Status": "Completed"}
                    start_node = current_node
                
                elif current_node['node_type'] == 'condition':
                    # Condition node - set as start_node for next iteration to evaluate
                    start_node = current_node
                
                else:
                    # Unknown node type - skip to next
                    log.warning(f"Unknown node type '{current_node['node_type']}' for node '{current_node_id}'")
                    start_node = current_node
                    
        except Exception as e:
            try:
                await self.pipeline_service.update_pipeline_run_status(execution_id, status="interrupted")
            except Exception as update_err:
                log.warning(f"Failed to update interrupted status: {update_err}")
            raise
        
        # Calculate response time
        end_time = time.monotonic()
        response_time = round(end_time - start_time, 2)
        
        # Update run status to completed with final response and response_time
        try:
            safe_final = final_response if isinstance(final_response, str) else json.dumps(final_response)
            await self.pipeline_service.update_pipeline_run_status(
                execution_id, 
                status="completed", 
                final_response=safe_final,
                response_time=response_time
            )
        except Exception as e:
            log.warning(f"Failed to update completed status: {e}")
        
        # Build current response with parts
        current_response = self._build_response_with_parts(input_query, final_response)
        
        # Format response with conversation history
        try:
            conversation_history = await self.pipeline_service.format_pipeline_response_with_history(
                current_response=current_response,
                pipeline_id=pipeline_id,
                session_id=session_id,
                role=role,
                response_time=response_time
            )
            yield {"executor_messages": conversation_history}
        except Exception as e:
            log.error(f"Error formatting pipeline conversation history: {e}")
            yield current_response

    def _build_response_with_parts(self, input_query: str, final_response: Any) -> Dict[str, Any]:
        """
        Build a response dictionary with appropriate parts structure.
        
        Args:
            input_query: The original user query
            final_response: The final response (str or dict/JSON)
            
        Returns:
            Dict[str, Any]: Response dictionary with parts
        """
        if isinstance(final_response, str):
            return {
                "query": input_query, 
                "response": final_response, 
                "executor_messages": [],
                "parts": [{
                    "type": "text",
                    "data": {"content": final_response},
                    "metadata": {}
                }]
            }
        else:
            return {
                "query": input_query, 
                "response": final_response, 
                "executor_messages": [],
                "parts": [{
                    "type": "json",
                    "data": final_response,
                    "metadata": {}
                }]
            }

    async def resume_pipeline(
        self,
        pipeline_id: str,
        session_id: str,
        model_name: str,
        execution_id: str,
        node_states: Dict[str, Dict],
        input_dict: Dict[str, Any],
        paused_node_id: str,
        is_plan_approved: Literal["yes", "no", None] = None,
        plan_feedback: str = None,
        tool_feedback: str = None,
        context_flag: bool = True,
        temperature: float = 0.0,
        role: str = "user"
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Resume a paused pipeline execution.
        
        Args:
            pipeline_id: The pipeline ID
            session_id: The session ID
            model_name: The model name
            execution_id: The execution ID from the paused state
            node_states: The node states from the paused state
            input_dict: The input dictionary from the paused state
            paused_node_id: The node that was paused
            is_plan_approved: 'yes' to approve plan, 'no' to reject with feedback
            plan_feedback: Feedback if plan is rejected
            tool_feedback: 'yes' to approve tool call, or modified tool arguments JSON
            context_flag: Whether to use context
            temperature: LLM temperature
            role: User role
            
        Yields:
            Pipeline execution events
        """
        async def get_next_node(condition: str, next_node_ids: List[str], llm: Any) -> str:
            prompt = f"""
Given the condition: "{condition}", choose the appropriate next node from the following options: {next_node_ids}.
Return only the node ID as a string.
            """
            response = await llm.ainvoke(prompt)
            return response.content.strip()
        
        async def output_formatter(output: Any, format_type: str, llm: Any) -> Any:
            prompt = f"""
Format the following output into {format_type} format: {output}
            """
            response = await llm.ainvoke(prompt)
            response = response.content.strip()
            json_response = json.loads(response)
            return json_response

        llm = await self.model_service.get_llm_model(model_name=model_name, temperature=temperature)
        
        pipeline = await self.pipeline_service.get_pipeline(pipeline_id)
        if not pipeline:
            raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' not found.")
        
        # Get the paused node
        paused_node = None
        for node in pipeline['pipeline_definition'].get('nodes', []):
            if node['node_id'] == paused_node_id:
                paused_node = node
                break
        
        if not paused_node:
            raise HTTPException(status_code=400, detail=f"Paused node '{paused_node_id}' not found in pipeline.")
        
        node_state = node_states.get(paused_node_id, {})
        pause_type = node_state.get('status')
        
        if pause_type not in ['paused_plan_verifier', 'paused_tool_verifier']:
            raise HTTPException(status_code=400, detail=f"Node '{paused_node_id}' is not in a paused state.")
        
        # Handle plan verification resume
        if pause_type == 'paused_plan_verifier':
            if is_plan_approved == 'no' and not plan_feedback:
                yield {
                    'event_type': 'waiting_feedback',
                    'execution_id': execution_id,
                    'node_id': paused_node_id,
                    'message': 'Plan rejected. Please provide feedback.'
                }
                return
        
        # Resume execution from the paused node
        start_node = paused_node
        final_response = None
        input_query = input_dict.get('query', '')

        while True:
            current_node = start_node
            current_node_id = current_node['node_id']
            
            if current_node['node_type'] == 'output':
                output_format = current_node.get('config', {}).get('output_format', 'text')
                if output_format == 'text':
                    yield final_response
                elif output_format == 'json':
                    formatted_output = await output_formatter(final_response, 'JSON', llm)
                    yield formatted_output
                return
            
            elif current_node['node_type'] == 'agent':
                agent_config = current_node.get('config', {})
                agent_id = agent_config.get('agent_id', '')
                tool_verifier = agent_config.get('tool_verifier', False)
                plan_verifier = agent_config.get('plan_verifier', False)
                
                node_thread_id = node_states.get(current_node_id, {}).get('thread_id') or f"{session_id}_{execution_id}_{current_node_id}"
                
                # Check if this is the paused node we need to resume
                current_pause_type = node_states.get(current_node_id, {}).get('status')
                
                if current_pause_type == 'paused_plan_verifier':
                    inference_request = AgentInferenceRequest(
                        query=None if is_plan_approved == 'yes' else None,
                        agentic_application_id=agent_id,
                        session_id=node_thread_id,
                        model_name=model_name,
                        reset_conversation=False,
                        response_formatting_flag=True,
                        enable_streaming_flag=False,
                        context_flag=context_flag,
                        plan_verifier_flag=True,
                        is_plan_approved=is_plan_approved,
                        plan_feedback=plan_feedback if is_plan_approved == 'no' else None,
                        tool_verifier_flag=tool_verifier
                    )
                elif current_pause_type == 'paused_tool_verifier':
                    inference_request = AgentInferenceRequest(
                        query=None,
                        agentic_application_id=agent_id,
                        session_id=node_thread_id,
                        model_name=model_name,
                        reset_conversation=False,
                        response_formatting_flag=True,
                        enable_streaming_flag=False,
                        context_flag=context_flag,
                        tool_verifier_flag=True,
                        tool_feedback=tool_feedback
                    )
                else:
                    # Fresh execution for subsequent nodes
                    accessible_inputs = agent_config.get('accessible_inputs', {})
                    agent_input = {}
                    input_keys = accessible_inputs.get('input_keys', ['all']) if isinstance(accessible_inputs, dict) else accessible_inputs
                    if isinstance(input_keys, list) and len(input_keys) == 1 and input_keys[0] == 'all':
                        agent_input = input_dict
                    elif isinstance(input_keys, list):
                        for key in input_keys:
                            if key in input_dict:
                                agent_input[key] = input_dict[key]
                    else:
                        agent_input = input_dict
                    
                    updated_query_with_input = input_query + "\n" + "\n".join([f"{k}: {v}" for k, v in agent_input.items() if k != 'query'])
                    
                    inference_request = AgentInferenceRequest(
                        query=updated_query_with_input,
                        agentic_application_id=agent_id,
                        session_id=node_thread_id,
                        model_name=model_name,
                        reset_conversation=True,
                        response_formatting_flag=True,
                        enable_streaming_flag=False,
                        context_flag=context_flag,
                        tool_verifier_flag=tool_verifier,
                        plan_verifier_flag=plan_verifier
                    )
                
                async for response in self.centralized_agent_inference.run(
                    inference_request,
                    role=role
                ):
                    agent_response = response
                
                # Check for new plan verification pause
                if isinstance(agent_response, dict) and plan_verifier and agent_response.get('plan'):
                    node_states[current_node_id] = {
                        'thread_id': node_thread_id,
                        'status': 'paused_plan_verifier',
                        'pending_plan': agent_response.get('plan')
                    }
                    yield {
                        'event_type': 'plan_verification_required',
                        'execution_id': execution_id,
                        'node_id': current_node_id,
                        'agent_id': agent_id,
                        'pending_plan': agent_response.get('plan'),
                        'node_states': node_states,
                        'input_dict': input_dict,
                        'message': f"Plan verification required for agent node '{current_node_id}'."
                    }
                    return
                
                # Check for new tool verification pause
                if isinstance(agent_response, dict) and tool_verifier:
                    executor_messages = agent_response.get('executor_messages', [])
                    if executor_messages:
                        last_message = executor_messages[-1]
                        additional_details = last_message.get('additional_details', [])
                        
                        pending_tool_calls = []
                        for detail in additional_details:
                            if detail.get('type') == 'ai' and detail.get('additional_kwargs', {}).get('tool_calls'):
                                pending_tool_calls = detail['additional_kwargs']['tool_calls']
                                break
                        
                        if pending_tool_calls and not agent_response.get('response'):
                            node_states[current_node_id] = {
                                'thread_id': node_thread_id,
                                'status': 'paused_tool_verifier',
                                'pending_tool_calls': pending_tool_calls
                            }
                            yield {
                                'event_type': 'tool_verification_required',
                                'execution_id': execution_id,
                                'node_id': current_node_id,
                                'agent_id': agent_id,
                                'pending_tool_calls': pending_tool_calls,
                                'node_states': node_states,
                                'input_dict': input_dict,
                                'message': f"Tool verification required for agent node '{current_node_id}'."
                            }
                            return
                
                # Node completed successfully
                final_response = agent_response.get('response', '') if isinstance(agent_response, dict) else str(agent_response)
                input_dict[current_node_id] = final_response
                node_states[current_node_id] = {
                    'thread_id': node_thread_id,
                    'status': 'completed',
                    'output': final_response
                }
                # Record step entry for resumed execution
                try:
                    # Get latest step order from service
                    latest_step_order = await self.pipeline_service.get_latest_step_order(execution_id)
                    step_order_val = latest_step_order + 1
                    step_payload = {
                        "node_type": "agent",
                        "node_id": current_node_id,
                        "agent_id": agent_id,
                        "response": final_response,
                        "status": "completed",
                        "resumed": True
                    }
                    if isinstance(agent_response, dict) and agent_response.get('executor_messages'):
                        step_payload["executor_messages"] = _serialize_messages(agent_response.get('executor_messages'))
                    await self.pipeline_service.add_pipeline_step(
                        run_id=execution_id,
                        step_order=step_order_val,
                        agent_id=agent_id,
                        step_data=step_payload
                    )
                except Exception:
                    pass
            
            # Find next node
            next_node_ids = []
            condition_met = ""
            for edge in pipeline['pipeline_definition'].get('edges', []):
                if edge['source_node_id'] == current_node_id:
                    next_node_ids = edge['target_node_id']
                    condition_met = edge.get('condition', "")
                    break
            
            if len(next_node_ids) == 0:
                # No more nodes, return final response
                try:
                    safe_final = final_response if isinstance(final_response, str) else json.dumps(final_response)
                    await self.pipeline_service.update_pipeline_run_status(execution_id, status="completed", final_response=safe_final)
                except Exception:
                    pass
                yield {
                    'event_type': 'pipeline_completed',
                    'execution_id': execution_id,
                    'response': final_response,
                    'node_states': node_states,
                    'input_dict': input_dict
                }
                return
            
            if len(next_node_ids) > 1:
                nxt_node_id = await get_next_node(condition_met, next_node_ids, llm)
                next_node_id = next_node_ids[0]
                for node_id in next_node_ids:
                    if nxt_node_id in node_id:
                        next_node_id = node_id
                        break
            else:
                next_node_id = next_node_ids[0]
            
            # Find the next node object
            for node in pipeline['pipeline_definition'].get('nodes', []):
                if node['node_id'] == next_node_id:
                    start_node = node
                    break