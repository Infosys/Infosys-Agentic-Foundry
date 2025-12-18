# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal

class GroundTruthEvaluationRequest(BaseModel):
    """Schema for requesting a ground truth evaluation."""
    model_name: str = Field(..., description="The name of the LLM model used by the agent being evaluated.")
    agent_type: str = Field(..., description="The type of the agent being evaluated (e.g., 'react_agent', 'multi_agent').")
    agent_name: str = Field(..., description="The name of the agent being evaluated.")
    agentic_application_id: str = Field(..., description="The ID of the agentic application being evaluated.")
    use_llm_grading: Optional[bool] = Field(False, description="If true, uses LLM for grading instead of rule-based.")
    temperature: Optional[float] = Field(0.0, description="Temperature parameter for LLM model (0.0-1.0) - for evaluation, lower is better for consistency")
    
    @field_validator('temperature')
    @classmethod
    def validate_temperature(cls, v):
        if v is not None and (v < 0.0 or v > 1.0):
            raise ValueError('Temperature must be between 0.0 and 1.0')
        return v

