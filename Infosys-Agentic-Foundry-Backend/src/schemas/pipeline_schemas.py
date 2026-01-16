# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Dict, Any, Literal, Union
from datetime import datetime


# --- Node Configuration Models ---

class NodePosition(BaseModel):
    """Position of a node on the canvas."""
    x: float = Field(..., description="X coordinate on canvas")
    y: float = Field(..., description="Y coordinate on canvas")

class AccessibleInputConfig(BaseModel):
    """Configuration for accessible inputs at a node."""
    input_keys: List[str] = Field(..., description="List of input keys accessible at this node")

class AgentNodeConfig(BaseModel):
    """Configuration for an agent node in the pipeline."""
    agent_id: str = Field(..., description="IAF Agent ID to be used at this node")
    tool_verifier: bool = Field(False, description="If true, pipeline pauses before this agent for user confirmation")
    plan_verifier: bool = Field(False, description="If true, pipeline pauses after this agent for user confirmation of plan")
    accessible_inputs: AccessibleInputConfig = Field(["all"], description="Configuration for accessible inputs at this node")
    

FieldType = Literal["integer", "string", "json", "list"]


class InputFieldSchema(BaseModel):
    """
    Structured representation of a single field in the schema.
    Allows known types (integer/string/json/list) or free-form descriptors.
    """
    type: Optional[FieldType] = Field(
        default=None,
        description="Normalized type for the field (integer|string|json|list)."
    )
    raw: Optional[str] = Field(
        default=None,
        description="Original type string when not exactly matching known types."
    )

    @model_validator(mode="before")
    def normalize_type(cls, values):
        # Accept simple strings directly: e.g., "integer", "string", "json/list also goes in the json."
        if isinstance(values, str):
            raw = values.strip().lower()
            if raw in {"integer", "string", "json", "list"}:
                return {"type": raw, "raw": None}
            # Try to infer when someone writes "json/list ..."
            if "json" in raw and "list" in raw:
                return {"type": "json", "raw": raw}
            return {"type": None, "raw": raw}
        return values


class InputFieldDescription(BaseModel):
    """
    Human-readable description of a field.
    """
    text: str = Field(..., description="Human-friendly description of the field.")


class InputConfigSchema(BaseModel):
    """
    Top-level config section holding 'schema' and 'description' maps.
    Supports field names that contain spaces via aliases.
    """
    # Use Dict[str, InputFieldSchema] so arbitrary keys (including 'track id') are preserved.
    input_schema: Dict[str, InputFieldSchema] = Field(
        ..., description="Mapping of field name -> InputFieldSchema"
    )
    description: Dict[str, InputFieldDescription] = Field(
        ..., description="Mapping of field name -> InputFieldDescription"
    )

class OutputConfigSchema(BaseModel):
    """
    Configuration for output schema.
    Holds a JSON mapping or null.
    """
    output_schema: Optional[Dict[str, Any]] = Field(
        None,
        description="JSON mapping of field name -> InputFieldSchema or null"
    )

class ConditionNodeConfig(BaseModel):
    """
    Configuration for condition node schema.
    """
    condition: str = Field(..., description="Text condition for deciding next node")

class PipelineNode(BaseModel):
    """Represents a node in the pipeline graph."""
    node_id: str = Field(..., description="Unique identifier for the node")
    node_type: Literal["input", "agent", "output", "condition"] = Field(..., description="Type of node: 'input' for start, 'agent' for IAF agents")
    node_name: str = Field(..., description="Display name of the node")
    position: NodePosition = Field(..., description="Visual position on canvas")
    
    config: Optional[Union[AgentNodeConfig, InputConfigSchema, OutputConfigSchema, ConditionNodeConfig]] = Field(None, description="Node-specific configuration")


class PipelineEdge(BaseModel):
    """Represents a connection between nodes."""
    edge_id: str = Field(..., description="Unique identifier for the edge")
    source_node_id: str = Field(..., description="ID of the source node")
    target_node_id: str = Field(..., description="ID of the target node")
    

# --- Pipeline Definition Models ---

class PipelineDefinition(BaseModel):
    """Complete pipeline graph definition."""
    nodes: List[PipelineNode] = Field(..., description="List of all nodes in the pipeline")
    edges: List[PipelineEdge] = Field(..., description="List of all edges connecting nodes")


class PipelineCreateRequest(BaseModel):
    """Request schema for creating a new pipeline."""
    pipeline_name: str = Field(..., description="Name of the pipeline")
    pipeline_description: Optional[str] = Field("", description="Description of the pipeline")
    pipeline_definition: PipelineDefinition = Field(..., description="The complete graph definition")
    created_by: str = Field(..., description="Email of the user creating the pipeline")


class PipelineUpdateRequest(BaseModel):
    """Request schema for updating an existing pipeline."""
    pipeline_name: Optional[str] = Field(None, description="New name for the pipeline")
    pipeline_description: Optional[str] = Field(None, description="New description")
    pipeline_definition: Optional[PipelineDefinition] = Field(None, description="Updated graph definition")
    is_active: Optional[bool] = Field(None, description="Active status")



# --- Response Models ---

class PipelineResponse(BaseModel):
    """Response schema for pipeline operations."""
    pipeline_id: str
    pipeline_name: str
    pipeline_description: Optional[str]
    pipeline_definition: PipelineDefinition
    created_by: str
    created_at: datetime
    updated_at: datetime
    is_active: bool


class PipelineListResponse(BaseModel):
    """Response schema for listing pipelines."""
    pipelines: List[PipelineResponse]
    total_count: int

