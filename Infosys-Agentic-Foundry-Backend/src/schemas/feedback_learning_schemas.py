# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from pydantic import BaseModel, Field
from typing import Optional

class ApprovalRequest(BaseModel):
    """Schema for updating the approval status of a feedback entry."""
    response_id: str = Field(..., description="The ID of the feedback response entry.")
    # query: str = Field(..., description="The original user query associated with the feedback.")
    # old_final_response: str = Field(..., description="The agent's original final response.")
    # old_steps: str = Field(..., description="The agent's original execution steps.")
    # old_response: str = Field(..., description="The agent's original raw response (if different from final).")
    # feedback: str = Field(..., description="The user's feedback text.")
    # new_final_response: str = Field(..., description="The agent's new/corrected final response after feedback.")
    # new_steps: str = Field(..., description="The agent's new/corrected execution steps after feedback.")
    lesson: str | None = Field(None, description="The agent's lesson")
    approved: bool | None = Field(None, description="Boolean indicating if the new response is approved.")

