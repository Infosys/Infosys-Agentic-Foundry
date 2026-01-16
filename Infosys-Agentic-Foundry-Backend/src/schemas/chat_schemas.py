# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional, Dict, List,Any

_DEFAULT_FRAMEWORK_TYPE = "langgraph"

class AgentInferenceRequest(BaseModel):
    """
    Pydantic model representing a unified agent inference request.
    This model captures all necessary details for invoking an agent,
    including options for Human-In-The-Loop (HITL) interactions and knowledge base integration.
    """
    query: str = Field("", description="The user's primary query or a modified query for agent processing.")
    agentic_application_id: str = Field(..., description="The unique ID of the agentic application to invoke.")
    session_id: str = Field(..., description="The unique session identifier for the ongoing conversation.")
    model_name: str = Field(..., description="The name of the LLM model to be used for this inference run.")
    reset_conversation: bool = Field(False, description="If true, the conversation history for this session will be reset before inference.")

    # --- Tool Verification / Interruption Flags ---
    tool_verifier_flag: bool = Field(False, description="If true, enables human verification/interruption after a tool call. The agent will pause for user input.")
    tool_feedback: Optional[str] = Field(None, description="Optional JSON string containing modified tool arguments provided by the user during a tool interruption.")

    # --- Plan Verification / HITL Flags ---
    plan_verifier_flag: bool = Field(False, description="If true, enables human verification/interruption after the agent generates a plan. The agent will pause for user input.")
    is_plan_approved: Optional[Literal[None, "yes", "no"]] = Field(None, description="User's approval status for a generated plan: 'yes' to proceed, 'no' to provide feedback.")
    plan_feedback: Optional[str] = Field(None, description="Text feedback from the user regarding a disapproved plan, used for replanning.")

    framework_type: Literal["langgraph"] = Field(_DEFAULT_FRAMEWORK_TYPE, description="The framework type of the agent (e.g., 'langgraph').")

    # --- Evaluation Flag ---
    evaluation_flag: bool = Field(False, description="If true, enables post-response evaluation of the agent's output.")
    
    # --- Validation Flag ---
    validator_flag: bool = Field(False, description="If true, enables response validation using agent's validation criteria or general relevancy check.")

    # --- Final Response Feedback ---
    final_response_feedback: Optional[str] = Field(None, description="Text feedback from the user regarding the agent's final response (e.g., for 'submit_feedback' action).")

    # --- Context and Knowledge Base ---
    prev_response: Optional[Dict[str, Any]] = Field(None, description="The agent's previous response, provided by the frontend for context in feedback loops (e.g., for 'regenerate' or 'submit_feedback' actions).")
    knowledgebase_name: Optional[str] = Field(None, description="Optional name of a knowledge base for the agent to use (primarily for React agents).")

    # --- Enable and Disable Formatting ---
    response_formatting_flag: Optional[bool] = True
    enable_streaming_flag: Optional[bool] = False
    context_flag: Optional[bool] = True
    
    # --- Model Parameters ---
    temperature: Optional[float] = Field(0, description="Temperature parameter for LLM model (0.0-1.0) - controls randomness in responses")
    mentioned_agentic_application_id: Optional[str] = None
    
    # --- Interrupt Items ---
    interrupt_items: Optional[List[str]] = Field(None, description="List of tool names or node names to interrupt at during agent execution. When specified, the agent will pause execution at these points for human review.")
    
    @field_validator('temperature')
    @classmethod
    def validate_temperature(cls, v):
        if v is not None and (v < 0.0 or v > 1.0):
            raise ValueError('Temperature must be between 0.0 and 1.0')
        return v

class ChatSessionRequest(BaseModel):
    """Schema for retrieving previous chat conversations."""
    agent_id: str = Field(..., description="The ID of the agent the user is interacting with.")
    session_id: str = Field(..., description="The unique session ID for the conversation.")
    framework_type: Literal["langgraph"] = Field(_DEFAULT_FRAMEWORK_TYPE, description="The framework type of the agent (e.g., 'langgraph').")

class OldChatSessionsRequest(BaseModel): # This is the new class for get_old_chats
    """Schema for requesting a list of old chat sessions for a user and agent."""
    user_email: str = Field(..., description="The email ID of the user whose old chat sessions are requested.")
    agent_id: str = Field(..., description="The ID of the agent for which old chat sessions are requested.")
    framework_type: Literal["langgraph"] = Field(_DEFAULT_FRAMEWORK_TYPE, description="The framework type of the agent (e.g., 'langgraph').")

class StoreExampleRequest(BaseModel):
    agent_id: str
    query: str
    response: str
    label: Literal["positive", "negative"]
    tool_calls: Optional[List[str]]


class StoreExampleResponse(BaseModel):
    success: bool
    message: str
    stored_as: Optional[str]

class TempAgentInferenceRequest(BaseModel):
    """Schema for a standard agent inference request."""
    query: str = Field(..., description="The user's primary query or a modified query for agent processing.")
    agentic_application_id: str = Field(..., description="The unique ID of the agentic application to invoke.")
    session_id: str = Field(..., description="The unique session identifier for the ongoing conversation.")
    model_name: str = Field(..., description="The name of the LLM model to be used for this inference run.")
    reset_conversation: bool = Field(False, description="If true, the conversation history for this session will be reset before inference.")
    interrupt_flag: bool = Field(False, description="If true, enables human verification/interruption after a tool call. The agent will pause for user input.")
    feedback: Optional[str] = Field(None, description="General final response feedback OR optional JSON string containing modified tool arguments provided by the user during a tool interruption.")
    prev_response: Optional[Dict[str, Any]] = Field(None, description="The agent's previous response, provided by the frontend for context in feedback loops (e.g., for 'regenerate' or 'submit_feedback' actions).")
    knowledgebase_name: Optional[str] = Field(None, description="Optional name of a knowledge base for the agent to use (primarily for React agents).")

class TempAgentInferenceHITLRequest(BaseModel):
    """Schema for Human-In-The-Loop (HITL) agent inference requests."""
    query: str = Field(..., description="The user's primary query or a modified query for agent processing.")
    agentic_application_id: str = Field(..., description="The unique ID of the agentic application to invoke.")
    session_id: str = Field(..., description="The unique session identifier for the ongoing conversation.")
    model_name: str = Field(..., description="The name of the LLM model to be used for this inference run.")
    reset_conversation: bool = Field(False, description="If true, the conversation history for this session will be reset before inference.")
    interrupt_flag: bool = Field(False, description="If true, enables human verification/interruption after a tool call. The agent will pause for user input.")
    tool_feedback: Optional[str] = Field(None, description="Optional JSON string containing modified tool arguments provided by the user during a tool interruption.")
    approval: Optional[str] = Field(None, description="User's approval status for a generated plan: 'yes' to proceed, 'no' to provide feedback.")
    feedback: Optional[str] = Field(None, description="Text feedback from the user regarding a disapproved plan, used for replanning.")
    prev_response: Optional[Dict[str, Any]] = Field(None, description="The agent's previous response, provided by the frontend for context in feedback loops (e.g., for 'regenerate' or 'submit_feedback' actions).")

class SDLCAgentInferenceRequest(BaseModel):
    """
    Pydantic model representing a SDLC agent inference request.
    """
    query: str = Field(..., description="The user's primary query for agent.")
    chat_id: str = Field(..., description="The unique chat identifier for the ongoing conversation.")
    model_name: str = Field("gpt-4o", description="The name of the LLM model to be used for this inference.")
    reset_conversation: bool = Field(False, description="If true, the conversation history for this chat_id will be reset before inference.")
    temperature: Optional[float] = Field(0.7, description="Temperature parameter for LLM model (0.0-1.0) - controls randomness in responses")
    
    @field_validator('temperature')
    @classmethod
    def validate_temperature(cls, v):
        if v is not None and (v < 0.0 or v > 1.0):
            raise ValueError('Temperature must be between 0.0 and 1.0')
        return v

class VMConnectionRequest(BaseModel):
    modules: List[str]
