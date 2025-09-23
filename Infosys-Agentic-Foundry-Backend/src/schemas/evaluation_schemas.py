# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from pydantic import BaseModel, Field
from typing import Optional, Literal

class GroundTruthEvaluationRequest(BaseModel):
    """Schema for requesting a ground truth evaluation."""
    model_name: str = Field(..., description="The name of the LLM model used by the agent being evaluated.")
    agent_type: str = Field(..., description="The type of the agent being evaluated (e.g., 'react_agent', 'multi_agent').")
    agent_name: str = Field(..., description="The name of the agent being evaluated.")
    agentic_application_id: str = Field(..., description="The ID of the agentic application being evaluated.")
    session_id: str = Field(..., description="A session ID to use for the evaluation runs (can be temporary).")
    use_llm_grading: Optional[bool] = Field(False, description="If true, uses LLM for grading instead of rule-based.")

