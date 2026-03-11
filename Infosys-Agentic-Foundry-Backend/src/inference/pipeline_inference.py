from src.inference.abstract_base_inference import AbstractBaseInference
from src.inference.inference_utils import InferenceUtils
from src.database.services import PipelineService
from typing import Dict, List, Any, Optional, AsyncGenerator, Tuple, Literal, Set
from dataclasses import dataclass, field
from fastapi import HTTPException
from src.utils.secrets_handler import current_user_email
from src.schemas import AgentInferenceRequest
from src.prompts.prompts import CONDITION_EVALUATION_PROMPT, OUTPUT_FORMATTING_PROMPT
import json
import time
import re
import asyncio
from src.inference.centralized_agent_inference import CentralizedAgentInference
import uuid
from enum import Enum
from telemetry_wrapper import logger as log


# =============================================================================
# ENUMS AND DATA CLASSES FOR PIPELINE EXECUTION
# =============================================================================

class NodeStatus(Enum):
    """Status of a node in the pipeline execution."""
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class NodeState:
    """Unified state class for any node - simplified from multiple classes."""
    node_id: str
    node_name: str
    node_type: str
    status: NodeStatus = NodeStatus.PENDING
    output: Any = None
    error: Optional[str] = None
    incoming: Set[str] = field(default_factory=set)  # predecessor node IDs
    received: Dict[str, Any] = field(default_factory=dict)  # inputs from predecessors
    
    @property
    def is_ready(self) -> bool:
        """Ready when all predecessors have sent their output."""
        if not self.incoming:
            return True
        return self.incoming.issubset(self.received.keys())
    
    @property
    def is_completed(self) -> bool:
        """Check if node execution is finished."""
        return self.status in (NodeStatus.COMPLETED, NodeStatus.FAILED, NodeStatus.SKIPPED)
    
    @property
    def is_failed(self) -> bool:
        """Check if node failed."""
        return self.status == NodeStatus.FAILED
    
    def receive(self, from_node: str, data: Any):
        """Receive input from a predecessor node."""
        self.received[from_node] = data
        
    def complete(self, output: Any):
        """Mark this node as completed with the given output."""
        self.status = NodeStatus.COMPLETED
        self.output = output
        
    def fail(self, error: str):
        """Mark this node as failed with an error message."""
        self.status = NodeStatus.FAILED
        self.error = error
        self.output = f"[ERROR: {error}]"
    
    def skip(self):
        """Mark this node as skipped."""
        self.status = NodeStatus.SKIPPED
    
    def get_merged_input(self) -> Dict[str, Any]:
        """Get all inputs received from predecessors."""
        return self.received.copy()


@dataclass
class PipelineState:
    """Single state container for entire pipeline - simplified."""
    nodes: Dict[str, NodeState] = field(default_factory=dict)
    edges: Dict[str, List[str]] = field(default_factory=dict)  # source -> [targets]
    input_dict: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def completed_nodes(self) -> Set[str]:
        """Get set of completed node IDs."""
        return {nid for nid, n in self.nodes.items() if n.status == NodeStatus.COMPLETED}
    
    @property
    def failed_nodes(self) -> Set[str]:
        """Get set of failed node IDs."""
        return {nid for nid, n in self.nodes.items() if n.status == NodeStatus.FAILED}
    
    @property
    def skipped_nodes(self) -> Set[str]:
        """Get set of skipped node IDs."""
        return {nid for nid, n in self.nodes.items() if n.status == NodeStatus.SKIPPED}
    
    def get_ready_nodes(self) -> List[str]:
        """Get all nodes ready to execute."""
        return [
            nid for nid, node in self.nodes.items()
            if node.status == NodeStatus.PENDING and node.is_ready
        ]
    
    def propagate(self, from_node: str, output: Any):
        """Send output to all successor nodes."""
        for target_id in self.edges.get(from_node, []):
            target = self.nodes.get(target_id)
            if target and target.status != NodeStatus.SKIPPED:
                target.receive(from_node, output)
    
    def mark_completed(self, node_id: str, output: Any):
        """Mark a node as completed and store its output."""
        node = self.nodes.get(node_id)
        if node:
            node.complete(output)
        self.input_dict[node_id] = output
    
    def mark_failed(self, node_id: str, error: str):
        """Mark a node as failed."""
        node = self.nodes.get(node_id)
        if node:
            node.fail(error)
        self.input_dict[node_id] = f"[ERROR: {error}]"
    
    def mark_skipped(self, node_id: str):
        """Mark a node as skipped."""
        node = self.nodes.get(node_id)
        if node:
            node.skip()
    
    def skip_branch(self, node_id: str):
        """Recursively skip a branch starting from node_id."""
        node = self.nodes.get(node_id)
        if not node or node.is_completed:
            return
        node.skip()
        for successor in self.edges.get(node_id, []):
            self.skip_branch(successor)


# Keep for backward compatibility and parallel streaming
@dataclass
class ParallelStreamEvent:
    """Event from a parallel streaming execution."""
    node_id: str
    node_name: str
    event: Dict[str, Any]
    is_final: bool = False
    output: Any = None
    error: Optional[str] = None


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
    """
    Pipeline inference engine with parallel execution support.
    
    Execution Rules:
    - Condition node with multiple outgoing edges → LLM picks ONE path
    - Agent/Input node with multiple outgoing edges → ALL paths run in PARALLEL
    - Node with multiple incoming edges → Waits for ALL predecessors (fan-in)
    
    Parallel Execution Limits:
    - Maximum 4 concurrent agent executions (controlled by semaphore)
    - If more than 4 parallel branches, they execute in batches of 4
    - Example: 10 parallel branches → first 4 run, as each completes next starts
    """
    
    # Parallel execution limits
    MAX_PARALLEL_AGENTS = 4       # Hard limit - maximum concurrent executions
    DEFAULT_PARALLEL_AGENTS = 3   # Default concurrent agents for safety
    
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
            tuple: (node_map, node_name_map, edges_by_source, edges_by_target)
                - node_map: Dict mapping node_id to node object
                - node_name_map: Dict mapping node_id to node_name
                - edges_by_source: Dict mapping source_node_id to list of target_node_ids
                - edges_by_target: Dict mapping target_node_id to list of source_node_ids
        """
        nodes = pipeline_definition.get('nodes', [])
        edges = pipeline_definition.get('edges', [])
        
        node_map = {node['node_id']: node for node in nodes}
        node_name_map = {node['node_id']: node.get('node_name', node['node_id']) for node in nodes}
        
        edges_by_source = {}
        edges_by_target = {}
        
        for edge in edges:
            source_id = edge.get('source_node_id')
            target_id = edge.get('target_node_id')
            
            if not source_id or not target_id:
                continue
            
            if source_id not in edges_by_source:
                edges_by_source[source_id] = []
            edges_by_source[source_id].append(target_id)
            
            if target_id not in edges_by_target:
                edges_by_target[target_id] = []
            edges_by_target[target_id].append(source_id)
        
        return node_map, node_name_map, edges_by_source, edges_by_target

    def _initialize_execution_context(
        self,
        node_map: Dict,
        edges_by_source: Dict[str, List[str]],
        edges_by_target: Dict[str, List[str]],
        input_query: str
    ) -> PipelineState:
        """Initialize execution context with node states for parallel execution."""
        ctx = PipelineState()
        ctx.input_dict["query"] = input_query
        ctx.edges = edges_by_source  # Store edges for propagation
        
        for node_id, node in node_map.items():
            incoming = set(edges_by_target.get(node_id, []))
            ctx.nodes[node_id] = NodeState(
                node_id=node_id,
                node_name=node.get('node_name', node_id),
                node_type=node['node_type'],
                incoming=incoming
            )
        
        return ctx

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

    def _find_node_by_type(self, pipeline_definition: Dict, node_type: str) -> Optional[Dict]:
        """
        Find the first node of a given type in the pipeline definition.
        
        Args:
            pipeline_definition: The pipeline definition containing nodes
            node_type: The type of node to find ('input', 'output', 'agent', 'condition')
            
        Returns:
            Optional[Dict]: The node dict if found, None otherwise
        """
        for node in pipeline_definition.get('nodes', []):
            if node.get('node_type') == node_type:
                return node
        return None

    async def _record_step(
        self,
        execution_id: str,
        step_order: int,
        agent_id: Optional[str],
        step_data: Dict[str, Any]
    ) -> None:
        """
        Record a pipeline step with error handling.
        
        Args:
            execution_id: The execution/run ID
            step_order: The order of this step
            agent_id: The agent ID if applicable
            step_data: The step data to record
        """
        try:
            await self.pipeline_service.add_pipeline_step(
                run_id=execution_id,
                step_order=step_order,
                agent_id=agent_id,
                step_data=step_data
            )
        except Exception as e:
            log.warning(f"Failed to record step {step_order}: {e}")

    async def _update_run_status(
        self,
        execution_id: str,
        status: str,
        final_response: Any = None,
        response_time: float = None,
        error: str = None
    ) -> None:
        """
        Update pipeline run status with error handling.
        
        Args:
            execution_id: The execution/run ID
            status: The new status ('pending', 'running', 'completed', 'completed_with_errors', 'failed')
            final_response: The final response (for completed status)
            response_time: The response time in seconds (for completed status)
            error: Error message (for failed status)
        """
        try:
            kwargs = {"status": status}
            if final_response is not None:
                safe_final = final_response if isinstance(final_response, str) else json.dumps(final_response) if final_response else ""
                kwargs["final_response"] = safe_final
            if response_time is not None:
                kwargs["response_time"] = response_time
            if error is not None:
                kwargs["error"] = error
            
            await self.pipeline_service.update_pipeline_run_status(execution_id, **kwargs)
        except Exception as e:
            log.warning(f"Failed to update run status to '{status}': {e}")

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
        role: str = "user",
        max_parallel_agents: int = None
        ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Run the pipeline with parallel execution support.
        
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
            max_parallel_agents (int): Max concurrent agent executions (default: 3, max: 5)
            
        Yields:
            AsyncGenerator[Dict[str, Any], None]: Yields output data from the pipeline execution.
        
        Execution Rules:
            - Condition node → LLM picks ONE path (conditional)
            - Agent/Input node with multiple edges → ALL run in parallel
            - Multiple incoming edges → Wait for ALL (fan-in merge)
        """
        start_time = time.monotonic()
        execution_id = str(uuid.uuid4())
        
        # Validate and set parallel limit
        if max_parallel_agents is None:
            max_parallel_agents = self.DEFAULT_PARALLEL_AGENTS
        max_parallel_agents = min(max_parallel_agents, self.MAX_PARALLEL_AGENTS)
        
        log.info(f"Starting pipeline {pipeline_id} with max_parallel_agents={max_parallel_agents}")
        
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
        
        # Build efficient lookup maps (now includes edges_by_target for fan-in)
        node_map, node_name_map, edges_by_source, edges_by_target = self._build_pipeline_maps(
            pipeline['pipeline_definition']
        )
        
        # Find the input node using helper method
        input_node = self._find_node_by_type(pipeline['pipeline_definition'], 'input')
        if not input_node:
            raise HTTPException(status_code=400, detail="Pipeline has no input node defined.")
        
        # Initialize execution context for parallel execution
        ctx = self._initialize_execution_context(node_map, edges_by_source, edges_by_target, input_query)
        
        # Semaphore for parallel execution limiting
        semaphore = asyncio.Semaphore(max_parallel_agents)
        
        step_order = 0
        
        # Mark run as running
        await self._update_run_status(execution_id, status="running")

        try:
            # === STEP 1: Process Input Node ===
            input_node_id = input_node['node_id']
            ctx.mark_completed(input_node_id, input_query)
            
            step_order += 1
            await self._record_step(execution_id, step_order, None, {
                "node_type": "input",
                "node_id": input_node_id,
                "input_query": input_query,
                "status": "completed"
            })
            
            yield {"Node Name": "Input", "Status": "Completed", "step_order": step_order}
            
            # Propagate to successors of input using new method
            ctx.propagate(input_node_id, input_query)
            
            # === STEP 2: Main Execution Loop ===
            iteration_count = 0
            max_iterations = len(node_map) * 2  # Safety limit
            final_response = None
            
            while iteration_count < max_iterations:
                iteration_count += 1
                
                # Get nodes ready to execute
                ready_nodes = ctx.get_ready_nodes()
                
                if not ready_nodes:
                    # Check completion status
                    output_nodes = [n for n in node_map.values() if n['node_type'] == 'output']
                    completed_outputs = [
                        n['node_id'] for n in output_nodes 
                        if n['node_id'] in ctx.completed_nodes
                    ]
                    
                    if completed_outputs:
                        log.info(f"Pipeline completed. Outputs reached: {completed_outputs}")
                        break
                    
                    # Check for stuck state
                    pending = [
                        nid for nid, state in ctx.nodes.items()
                        if not state.is_completed and nid not in ctx.skipped_nodes
                    ]
                    if pending:
                        log.warning(f"Pipeline may be stuck. Pending nodes: {pending}")
                    break
                
                # Separate condition nodes from others
                condition_nodes = [nid for nid in ready_nodes if node_map[nid]['node_type'] == 'condition']
                execution_nodes = [nid for nid in ready_nodes if node_map[nid]['node_type'] != 'condition']
                
                # === Process Condition Nodes First (Sequential) ===
                for node_id in condition_nodes:
                    async for event in self._execute_condition_node(
                        node_id=node_id,
                        ctx=ctx,
                        node_map=node_map,
                        edges_by_source=edges_by_source,
                        llm=llm,
                        input_query=input_query,
                        execution_id=execution_id,
                        step_order=step_order
                    ):
                        yield event
                        if isinstance(event, dict) and "step_order" in event:
                            step_order = event["step_order"]
                
                # Refresh ready nodes after conditions
                execution_nodes = [
                    nid for nid in ctx.get_ready_nodes()
                    if node_map[nid]['node_type'] != 'condition'
                ]
                
                if not execution_nodes:
                    continue
                
                # === Execute Agent/Output Nodes ===
                if len(execution_nodes) == 1:
                    # Single node - execute with streaming
                    node_id = execution_nodes[0]
                    async for event in self._execute_node_streaming(
                        node_id=node_id,
                        ctx=ctx,
                        node_map=node_map,
                        edges_by_source=edges_by_source,
                        llm=llm,
                        session_id=session_id,
                        execution_id=execution_id,
                        model_name=model_name,
                        input_query=input_query,
                        step_order=step_order,
                        role=role,
                        reset_conversation=reset_conversation,
                        context_flag=context_flag,
                        evaluation_flag=evaluation_flag,
                        validator_flag=validator_flag,
                        tool_interrupt_flag=tool_interrupt_flag,
                        tool_feedback=tool_feedback,
                        plan_verifier_flag=plan_verifier_flag,
                        is_plan_approved=is_plan_approved,
                        plan_feedback=plan_feedback
                    ):
                        yield event
                        if isinstance(event, dict) and "step_order" in event:
                            step_order = event["step_order"]
                        if isinstance(event, dict) and "final_response" in event:
                            final_response = event["final_response"]
                
                else:
                    # Multiple nodes - PARALLEL execution WITH STREAMING
                    parallel_node_names = [
                        ctx.nodes[nid].node_name for nid in execution_nodes
                    ]
                    
                    # Calculate batching info for logging
                    total_parallel = len(execution_nodes)
                    batch_info = ""
                    if total_parallel > max_parallel_agents:
                        batch_info = f" (executing in batches of {max_parallel_agents})"
                    
                    yield {
                        "Node Name": "Parallel Execution",
                        "Status": "Started",
                        "parallel_count": total_parallel,
                        "max_concurrent": max_parallel_agents,
                        "nodes": parallel_node_names
                    }
                    
                    log.info(f"Executing {total_parallel} nodes in parallel with streaming{batch_info}: {parallel_node_names}")
                    
                    # Use queue for streaming events from parallel nodes
                    event_queue: asyncio.Queue[ParallelStreamEvent] = asyncio.Queue()
                    
                    async def execute_node_streaming_to_queue(nid: str, node_index: int):
                        """Execute a node with streaming and push events to queue."""
                        async with semaphore:
                            node_name = ctx.nodes[nid].node_name
                            node = node_map[nid]
                            node_type = node['node_type']
                            
                            log.debug(f"Starting parallel streaming node {node_index + 1}/{total_parallel}: {node_name}")
                            
                            # Push start event
                            await event_queue.put(ParallelStreamEvent(
                                node_id=nid,
                                node_name=node_name,
                                event={"Node Name": f"[Parallel] {node_name}", "Status": "Started", "_parallel_node": node_name, "_parallel_node_id": nid}
                            ))
                            
                            merged_inputs = ctx.nodes[nid].get_merged_input()
                            
                            try:
                                if node_type == 'output':
                                    # Output nodes - execute and complete
                                    output = await self._execute_output_node(node, merged_inputs, ctx.input_dict, llm)
                                    
                                    await event_queue.put(ParallelStreamEvent(
                                        node_id=nid,
                                        node_name=node_name,
                                        event={"Node Name": f"[Parallel] {node_name}", "Status": "Completed", "_parallel_node": node_name, "_parallel_node_id": nid},
                                        is_final=True,
                                        output=output
                                    ))
                                    
                                elif node_type == 'agent':
                                    # Agent nodes - stream intermediate events
                                    output = None
                                    executor_msgs = []
                                    async for event in self._execute_agent_node_streaming(
                                        node=node,
                                        merged_inputs=merged_inputs,
                                        input_dict=ctx.input_dict,
                                        input_query=input_query,
                                        session_id=session_id,
                                        execution_id=execution_id,
                                        model_name=model_name,
                                        role=role,
                                        reset_conversation=reset_conversation,
                                        context_flag=context_flag,
                                        evaluation_flag=evaluation_flag,
                                        validator_flag=validator_flag,
                                        tool_interrupt_flag=tool_interrupt_flag,
                                        tool_feedback=tool_feedback,
                                        plan_verifier_flag=plan_verifier_flag,
                                        is_plan_approved=is_plan_approved,
                                        plan_feedback=plan_feedback
                                    ):
                                        # Check for final output marker
                                        if isinstance(event, dict) and "_agent_output" in event:
                                            output = event["_agent_output"]
                                            executor_msgs = event.get("_executor_messages", [])
                                        else:
                                            # Tag event with node info and push to queue
                                            tagged_event = event.copy() if isinstance(event, dict) else {"data": event}
                                            tagged_event["_parallel_node"] = node_name
                                            tagged_event["_parallel_node_id"] = nid
                                            
                                            await event_queue.put(ParallelStreamEvent(
                                                node_id=nid,
                                                node_name=node_name,
                                                event=tagged_event
                                            ))
                                    
                                    await event_queue.put(ParallelStreamEvent(
                                        node_id=nid,
                                        node_name=node_name,
                                        event={"Node Name": f"[Parallel] {node_name}", "Status": "Completed", "_parallel_node": node_name, "_parallel_node_id": nid, "_executor_messages": executor_msgs},
                                        is_final=True,
                                        output=output
                                    ))
                                else:
                                    # Other node types - just pass through
                                    output = list(merged_inputs.values())[0] if merged_inputs else None
                                    await event_queue.put(ParallelStreamEvent(
                                        node_id=nid,
                                        node_name=node_name,
                                        event={"Node Name": f"[Parallel] {node_name}", "Status": "Completed", "_parallel_node": node_name, "_parallel_node_id": nid},
                                        is_final=True,
                                        output=output
                                    ))
                                    
                            except Exception as e:
                                error_msg = str(e)
                                log.error(f"Parallel streaming node {node_name} failed: {error_msg}")
                                await event_queue.put(ParallelStreamEvent(
                                    node_id=nid,
                                    node_name=node_name,
                                    event={"Node Name": f"[Parallel] {node_name}", "Status": "Failed", "Error": error_msg, "_parallel_node": node_name, "_parallel_node_id": nid},
                                    is_final=True,
                                    error=error_msg
                                ))
                            
                            log.debug(f"Completed parallel streaming node {node_index + 1}/{total_parallel}: {node_name}")
                    
                    # Start all tasks
                    tasks = [
                        asyncio.create_task(execute_node_streaming_to_queue(nid, idx))
                        for idx, nid in enumerate(execution_nodes)
                    ]
                    
                    # Collect events from queue while tasks are running
                    completed_nodes_in_batch: Set[str] = set()
                    node_outputs: Dict[str, Any] = {}
                    node_errors: Dict[str, str] = {}
                    node_executor_messages: Dict[str, Any] = {}
                    
                    while len(completed_nodes_in_batch) < len(execution_nodes):
                        try:
                            # Wait for event with timeout to check task status
                            stream_event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                            
                            # Yield the event to endpoint (real-time streaming)
                            yield stream_event.event
                            
                            if stream_event.is_final:
                                completed_nodes_in_batch.add(stream_event.node_id)
                                if stream_event.error:
                                    node_errors[stream_event.node_id] = stream_event.error
                                else:
                                    node_outputs[stream_event.node_id] = stream_event.output
                                    # Capture executor_messages from the event
                                    if isinstance(stream_event.event, dict) and "_executor_messages" in stream_event.event:
                                        node_executor_messages[stream_event.node_id] = stream_event.event["_executor_messages"]
                                    
                        except asyncio.TimeoutError:
                            # Check if all tasks are done
                            if all(task.done() for task in tasks):
                                # Drain remaining events from queue
                                while not event_queue.empty():
                                    stream_event = await event_queue.get()
                                    yield stream_event.event
                                    if stream_event.is_final:
                                        completed_nodes_in_batch.add(stream_event.node_id)
                                        if stream_event.error:
                                            node_errors[stream_event.node_id] = stream_event.error
                                        else:
                                            node_outputs[stream_event.node_id] = stream_event.output
                                            # Capture executor_messages from the event
                                            if isinstance(stream_event.event, dict) and "_executor_messages" in stream_event.event:
                                                node_executor_messages[stream_event.node_id] = stream_event.event["_executor_messages"]
                                break
                    
                    # Wait for all tasks to complete (they should be done by now)
                    await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # Process results and update context
                    for node_id in execution_nodes:
                        node_name = ctx.nodes[node_id].node_name
                        step_order += 1
                        
                        if node_id in node_errors:
                            # NODE LEVEL FAILURE HANDLING
                            error_msg = node_errors[node_id]
                            ctx.mark_failed(node_id, error_msg)
                            
                            # Record failed step
                            await self._record_step(execution_id, step_order, 
                                node_map[node_id].get('config', {}).get('agent_id'), {
                                "node_type": node_map[node_id]['node_type'],
                                "node_id": node_id,
                                "node_name": node_name,
                                "status": "failed",
                                "error": error_msg,
                                "parallel_execution": True
                            })
                            
                            # Propagate error to successors
                            ctx.propagate(node_id, f"[ERROR from {node_name}: {error_msg}]")
                        
                        else:
                            # Successful execution
                            output = node_outputs.get(node_id)
                            
                            ctx.mark_completed(node_id, output)
                            ctx.propagate(node_id, output)
                            
                            # Store output if this is an output node
                            if node_map[node_id]['node_type'] == 'output':
                                # output_key = node_map[node_id].get('config', {}).get('output_key', node_id)
                                ctx.outputs[node_name] = output
                                final_response = output
                            
                            # Build step data with executor_messages if available
                            step_data = {
                                "node_type": node_map[node_id]['node_type'],
                                "node_id": node_id,
                                "node_name": node_name,
                                "response": output if isinstance(output, str) else json.dumps(output) if output else "",
                                "status": "completed",
                                "parallel_execution": True
                            }
                            
                            # Include executor_messages if available for agent nodes
                            if node_id in node_executor_messages:
                                step_data["executor_messages"] = _serialize_messages(node_executor_messages[node_id])
                            
                            # Record step
                            await self._record_step(execution_id, step_order, 
                                node_map[node_id].get('config', {}).get('agent_id'), step_data)
                    
                    yield {"Node Name": "Parallel Execution", "Status": "Completed"}
            
            # === STEP 3: Build Final Response ===
            elapsed_time = time.monotonic() - start_time
            response_time = round(elapsed_time, 2)
            
            # Get final response from outputs or last completed agent
            if ctx.outputs:
                if len(ctx.outputs) == 1:
                    final_response = list(ctx.outputs.values())[0]
                else:
                    final_response = ctx.outputs
            elif final_response is None:
                # Use last agent output
                for node_id in reversed(list(ctx.completed_nodes)):
                    state = ctx.nodes.get(node_id)
                    if state and state.node_type == 'agent' and state.output and not state.is_failed:
                        final_response = state.output
                        break
            
            # Update run status
            status = "completed_with_errors" if ctx.failed_nodes else "completed"
            await self._update_run_status(
                execution_id, 
                status=status,
                final_response=final_response,
                response_time=response_time
            )
            
            # Build response with parts
            current_response = self._build_response_with_parts_extended(
                input_query, final_response, ctx
            )
            
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
                
        except Exception as e:
            log.error(f"Pipeline execution error: {e}", exc_info=True)
            await self._update_run_status(execution_id, status="failed", error=str(e))
            raise HTTPException(status_code=500, detail=f"Pipeline execution failed: {str(e)}")

    # =========================================================================
    # CONDITION NODE EXECUTION
    # =========================================================================
    
    async def _execute_condition_node(
        self,
        node_id: str,
        ctx: PipelineState,
        node_map: Dict,
        edges_by_source: Dict,
        llm: Any,
        input_query: str,
        execution_id: str,
        step_order: int
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Execute a condition node - LLM selects ONE path from multiple options.
        Marks unselected paths as skipped.
        """
        node = node_map[node_id]
        condition = node.get('config', {}).get('condition', "")
        next_node_ids = edges_by_source.get(node_id, [])
        node_name_map = {n['node_id']: n.get('node_name', n['node_id']) for n in node_map.values()}
        
        yield {"Node Name": "Evaluating Condition", "Status": "Started"}
        
        # Get input for condition evaluation
        merged_inputs = ctx.nodes[node_id].get_merged_input()
        condition_input = ""
        if merged_inputs:
            condition_input = list(merged_inputs.values())[-1]
            if isinstance(condition_input, dict):
                condition_input = json.dumps(condition_input)
        
        selected_node_id = None
        
        try:
            if len(next_node_ids) > 1:
                # Build options with node names
                options = [f"{nid} {node_name_map.get(nid, nid)}" for nid in next_node_ids]
                
                # Ask LLM to select
                nxt_response = await self._get_next_node(
                    condition=condition,
                    next_node_ids=options,
                    llm=llm,
                    agent_response=condition_input,
                    input_query=input_query
                )
                
                # Extract reasoning
                reasoning = self._extract_reasoning_from_response(nxt_response)
                if reasoning:
                    yield {"content": reasoning}
                
                # Parse selected node
                selected_node_id = self._select_next_node_id(nxt_response, options)
                
            elif len(next_node_ids) == 1:
                selected_node_id = next_node_ids[0]
        
        except Exception as e:
            log.error(f"Condition evaluation failed: {e}")
            # On failure, default to first option
            if next_node_ids:
                selected_node_id = next_node_ids[0]
            yield {"Node Name": "Evaluating Condition", "Status": "Failed", "Error": str(e)}
        
        # Mark condition as completed
        ctx.mark_completed(node_id, condition_input)
        
        # Mark unselected paths as skipped
        for nid in next_node_ids:
            if nid != selected_node_id:
                self._mark_branch_skipped(nid, ctx, node_map, edges_by_source)
        
        # Propagate to selected node only
        if selected_node_id:
            ctx.nodes[selected_node_id].receive(node_id, condition_input)
            
            # Override incoming to just this condition
            selected_state = ctx.nodes.get(selected_node_id)
            if selected_state:
                selected_state.incoming = {node_id}
        
        step_order += 1
        
        # Record step using helper
        await self._record_step(execution_id, step_order, None, {
            "node_type": "condition",
            "node_id": node_id,
            "condition": condition,
            "selected_node_id": selected_node_id,
            "all_options": next_node_ids,
            "status": "completed"
        })
        
        selected_name = node_map.get(selected_node_id, {}).get('node_name', selected_node_id) if selected_node_id else None
        
        yield {
            "Node Name": "Evaluating Condition",
            "Status": "Completed",
            "selected_path": selected_name,
            "step_order": step_order
        }
    
    def _mark_branch_skipped(
        self,
        node_id: str,
        ctx: PipelineState,
        node_map: Dict,
        edges_by_source: Dict
    ):
        """Recursively mark a branch as skipped (not selected by condition)."""
        if node_id in ctx.skipped_nodes or node_id in ctx.completed_nodes:
            return
        
        ctx.mark_skipped(node_id)
        
        # Also skip all descendants
        for successor_id in edges_by_source.get(node_id, []):
            self._mark_branch_skipped(successor_id, ctx, node_map, edges_by_source)

    # =========================================================================
    # NODE EXECUTION (STREAMING - for single node)
    # =========================================================================
    
    async def _execute_node_streaming(
        self,
        node_id: str,
        ctx: PipelineState,
        node_map: Dict,
        edges_by_source: Dict,
        llm: Any,
        session_id: str,
        execution_id: str,
        model_name: str,
        input_query: str,
        step_order: int,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute a single node with streaming output."""
        node = node_map[node_id]
        node_name = node.get('node_name', node_id)
        node_type = node['node_type']
        
        merged_inputs = ctx.nodes[node_id].get_merged_input()
        
        try:
            if node_type == 'output':
                yield {"Node Name": f"Output: {node_name}", "Status": "Started"}
                
                output = await self._execute_output_node(node, merged_inputs, ctx.input_dict, llm)
                
                output_key = node.get('config', {}).get('output_key', node_id)
                ctx.outputs[output_key] = output
                ctx.mark_completed(node_id, output)
                
                step_order += 1
                
                await self._record_step(execution_id, step_order, None, {
                    "node_type": "output",
                    "node_id": node_id,
                    "node_name": node_name,
                    "output_key": output_key,
                    "response": output if isinstance(output, str) else json.dumps(output) if output else "",
                    "status": "completed"
                })
                
                yield {
                    "Node Name": f"Output: {node_name}",
                    "Status": "Completed",
                    "output_key": output_key,
                    "step_order": step_order,
                    "final_response": output
                }
            
            elif node_type == 'agent':
                yield {"Node Name": f"Agent: {node_name}", "Status": "Started"}
                
                output = None
                async for event in self._execute_agent_node_streaming(
                    node=node,
                    merged_inputs=merged_inputs,
                    input_dict=ctx.input_dict,
                    input_query=input_query,
                    session_id=session_id,
                    execution_id=execution_id,
                    model_name=model_name,
                    **kwargs
                ):
                    if isinstance(event, dict) and "_agent_output" in event:
                        output = event["_agent_output"]
                    else:
                        yield event
                
                ctx.mark_completed(node_id, output)
                
                # Propagate to successors
                ctx.propagate(node_id, output)
                
                step_order += 1
                
                await self._record_step(execution_id, step_order, node.get('config', {}).get('agent_id'), {
                    "node_type": "agent",
                    "node_id": node_id,
                    "node_name": node_name,
                    "response": output if isinstance(output, str) else json.dumps(output) if output else "",
                    "status": "completed"
                })
                
                yield {
                    "Node Name": f"Agent: {node_name}",
                    "Status": "Completed",
                    "step_order": step_order,
                    "final_response": output
                }
        
        except Exception as e:
            # NODE LEVEL FAILURE HANDLING
            error_msg = str(e)
            log.error(f"Node {node_name} execution failed: {error_msg}")
            
            ctx.mark_failed(node_id, error_msg)
            
            step_order += 1
            
            await self._record_step(execution_id, step_order, 
                node.get('config', {}).get('agent_id') if node_type == 'agent' else None, {
                "node_type": node_type,
                "node_id": node_id,
                "node_name": node_name,
                "status": "failed",
                "error": error_msg
            })
            
            yield {
                "Node Name": node_name,
                "Status": "Failed",
                "Error": error_msg,
                "step_order": step_order
            }
            
            # Propagate error to successors
            ctx.propagate(node_id, f"[ERROR from {node_name}: {error_msg}]")

    # =========================================================================
    # NODE EXECUTION (PARALLEL - non-streaming)
    # =========================================================================
    
    async def _execute_node_parallel(
        self,
        node_id: str,
        ctx: PipelineState,
        node_map: Dict,
        edges_by_source: Dict,
        llm: Any,
        session_id: str,
        execution_id: str,
        model_name: str,
        input_query: str,
        **kwargs
    ) -> Tuple[Any, List[Dict]]:
        """
        Execute a node for parallel execution (non-streaming).
        Returns (output, list_of_events).
        """
        events = []
        node = node_map[node_id]
        node_name = node.get('node_name', node_id)
        node_type = node['node_type']
        
        merged_inputs = ctx.nodes[node_id].get_merged_input()
        
        events.append({"Node Name": node_name, "Status": "Started"})
        
        try:
            if node_type == 'output':
                output = await self._execute_output_node(node, merged_inputs, ctx.input_dict, llm)
            
            elif node_type == 'agent':
                output = await self._execute_agent_node(
                    node=node,
                    merged_inputs=merged_inputs,
                    input_dict=ctx.input_dict,
                    input_query=input_query,
                    session_id=session_id,
                    execution_id=execution_id,
                    model_name=model_name,
                    **kwargs
                )
            else:
                output = list(merged_inputs.values())[0] if merged_inputs else None
            
            return output, events
        
        except Exception as e:
            # Re-raise to be handled by asyncio.gather with return_exceptions=True
            raise

    # =========================================================================
    # OUTPUT NODE EXECUTION
    # =========================================================================
    
    async def _execute_output_node(
        self,
        node: Dict,
        merged_inputs: Dict[str, Any],
        input_dict: Dict[str, Any],
        llm: Any
    ) -> Any:
        """Execute an output node - format and return response."""
        config = node.get('config', {})
        output_schema = config.get('output_schema')
        
        # Combine inputs
        if len(merged_inputs) == 0:
            response = ""
        elif len(merged_inputs) == 1:
            response = list(merged_inputs.values())[0]
        else:
            # Multiple inputs from parallel branches - merge them
            parts = []
            for source_id, value in merged_inputs.items():
                if isinstance(value, str):
                    parts.append(f"## From {source_id}\n{value}")
                else:
                    parts.append(f"## From {source_id}\n{json.dumps(value, indent=2)}")
            response = "\n\n".join(parts)
        
        # Format if schema specified
        if output_schema:
            response = await self._format_output(response, output_schema, llm)
        
        return response

    # =========================================================================
    # AGENT NODE EXECUTION
    # =========================================================================
    
    async def _execute_agent_node(
        self,
        node: Dict,
        merged_inputs: Dict[str, Any],
        input_dict: Dict[str, Any],
        input_query: str,
        session_id: str,
        execution_id: str,
        model_name: str,
        role: str = "user",
        **kwargs
    ) -> str:
        """Execute an agent node (non-streaming for parallel execution)."""
        config = node.get('config', {})
        agent_id = config.get('agent_id', '')
        accessible_inputs = config.get('accessible_inputs', {})
        tool_verifier = config.get('tool_verifier', False)
        plan_verifier = config.get('plan_verifier', False)
        
        # Build agent input
        agent_input = self._build_agent_input(accessible_inputs, input_dict)
        updated_query = self._build_query_with_inputs_extended(input_query, agent_input, merged_inputs)
        
        # Build unique thread ID (stable across pipeline runs for conversation continuity)
        node_thread_id = f"{session_id}_{node['node_id']}"
        
        inference_request = AgentInferenceRequest(
            query=updated_query,
            agentic_application_id=agent_id,
            session_id=node_thread_id,
            model_name=model_name,
            reset_conversation=kwargs.get('reset_conversation', False),
            response_formatting_flag=False,
            enable_streaming_flag=False,
            context_flag=kwargs.get('context_flag', True),
            tool_verifier_flag=tool_verifier,
            plan_verifier_flag=plan_verifier,
            evaluation_flag=kwargs.get('evaluation_flag', False),
            validator_flag=kwargs.get('validator_flag', False)
        )
        
        # Execute (non-streaming)
        response = None
        async for resp in self.centralized_agent_inference.run(inference_request, role=role):
            response = resp
            
        
        if isinstance(response, dict):
            return response.get('response', '') or response.get('final_response', '')
        return str(response) if response else ""
    
    async def _execute_agent_node_streaming(
        self,
        node: Dict,
        merged_inputs: Dict[str, Any],
        input_dict: Dict[str, Any],
        input_query: str,
        session_id: str,
        execution_id: str,
        model_name: str,
        role: str = "user",
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute an agent node with streaming."""
        config = node.get('config', {})
        agent_id = config.get('agent_id', '')
        accessible_inputs = config.get('accessible_inputs', {})
        tool_verifier = config.get('tool_verifier', False)
        plan_verifier = config.get('plan_verifier', False)
        
        # Build agent input
        agent_input = self._build_agent_input(accessible_inputs, input_dict)
        updated_query = self._build_query_with_inputs_extended(input_query, agent_input, merged_inputs)
        
        # Build unique thread ID (stable across pipeline runs for conversation continuity)
        node_thread_id = f"{session_id}_{node['node_id']}"
        
        inference_request = AgentInferenceRequest(
            query=updated_query,
            agentic_application_id=agent_id,
            session_id=node_thread_id,
            model_name=model_name,
            reset_conversation=kwargs.get('reset_conversation', False),
            response_formatting_flag=False,
            enable_streaming_flag=True,
            context_flag=kwargs.get('context_flag', True),
            tool_verifier_flag=tool_verifier,
            plan_verifier_flag=plan_verifier,
            is_plan_approved=kwargs.get('is_plan_approved'),
            plan_feedback=kwargs.get('plan_feedback'),
            tool_interrupt_flag=kwargs.get('tool_interrupt_flag', False),
            tool_feedback=kwargs.get('tool_feedback'),
            evaluation_flag=kwargs.get('evaluation_flag', False),
            validator_flag=kwargs.get('validator_flag', False)
        )
        
        agent_response = None
        async for response in self.centralized_agent_inference.run(inference_request, role=role):
            if isinstance(response, dict) and "query" not in response:
                yield response
            agent_response = response
        
        # Extract final response and executor_messages
        if isinstance(agent_response, dict):
            final_response = agent_response.get('response', '') or agent_response.get('final_response', '')
            executor_messages = agent_response.get('executor_messages', [])
        else:
            final_response = str(agent_response) if agent_response else ""
            executor_messages = []
        
        yield {"_agent_output": final_response, "_executor_messages": executor_messages}

    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    
    def _build_query_with_inputs_extended(
        self,
        original_query: str,
        agent_input: Dict,
        merged_inputs: Dict[str, Any]
    ) -> str:
        """Build query with accessible inputs and merged parallel inputs."""
        parts = [original_query]
        
        # Add context from accessible inputs
        context_parts = []
        for key, value in agent_input.items():
            if key in ("query", "_merged_inputs"):
                continue
            if isinstance(value, str):
                context_parts.append(f"[{key}]: {value}")
            else:
                context_parts.append(f"[{key}]: {json.dumps(value)}")
        
        if context_parts:
            parts.append("\n\n--- Context from Previous Steps ---")
            parts.extend(context_parts)
            parts.append("--- End Context ---")
        
        # Add merged inputs from parallel branches
        if len(merged_inputs) > 1:
            parts.append("\n\n--- Merged Inputs from Parallel Branches ---")
            for source_id, value in merged_inputs.items():
                if isinstance(value, str):
                    parts.append(f"\n[From {source_id}]:\n{value}")
                else:
                    parts.append(f"\n[From {source_id}]:\n{json.dumps(value)}")
            parts.append("\n--- End Parallel Inputs ---")
            parts.append("\nPlease synthesize the above inputs from parallel branches into a coherent response.")
        
        return "\n".join(parts)
    
    def _build_response_with_parts_extended(
        self,
        input_query: str,
        final_response: Any,
        ctx: PipelineState
    ) -> Dict[str, Any]:
        """Build response with parts and execution metadata."""
        # Handle multiple outputs
        if ctx.outputs and len(ctx.outputs) > 1:
            parts = []
            for output_key, response in ctx.outputs.items():
                parts.append({
                    "type": "text" if isinstance(response, str) else "json",
                    "output_key": output_key,
                    "data": {"content": response} if isinstance(response, str) else response,
                    "metadata": {"output_key": output_key}
                })
            
            return {
                "query": input_query,
                "outputs": ctx.outputs,
                "response": final_response,
                "executor_messages": [],
                "parts": parts,
                "failed_nodes": list(ctx.failed_nodes) if ctx.failed_nodes else []
            }
        
        # Single output or no explicit outputs
        response_dict = {
            "query": input_query,
            "response": final_response,
            "executor_messages": [],
        }
        
        if ctx.failed_nodes:
            response_dict["failed_nodes"] = list(ctx.failed_nodes)
        
        if isinstance(final_response, str):
            response_dict["parts"] = [{
                "type": "text",
                "data": {"content": final_response},
                "metadata": {}
            }]
        else:
            response_dict["parts"] = [{
                "type": "json",
                "data": final_response,
                "metadata": {}
            }]
        
        return response_dict

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
                
                node_thread_id = node_states.get(current_node_id, {}).get('thread_id') or f"{session_id}_{current_node_id}"
                
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