# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from pydantic import BaseModel, Field
from typing import List, Optional, Union

class TagIdName(BaseModel):
    """Schema for filtering by tag IDs or names."""
    tag_ids: Optional[Union[str, List[str]]] = Field(None, description="A list of tag IDs to filter by.")
    tag_names: Optional[Union[str, List[str]]] = Field(None, description="A list of tag names to filter by.")

class TagData(BaseModel):
    """Schema for creating a new tag."""
    tag_name: str = Field(..., description="The name of the tag.")
    created_by: str = Field(..., description="The email ID of the user who created the tag.")

class UpdateTagData(BaseModel):
    """Schema for updating an existing tag."""
    tag_id: Optional[str] = Field(None, description="The ID of the tag to update.")
    tag_name: Optional[str] = Field(None, description="The current name of the tag to update.")
    new_tag_name: str = Field(..., description="The new name for the tag.")
    created_by: str = Field(..., description="The email ID of the user performing the update.")

class DeleteTagData(BaseModel):
    """Schema for deleting a tag."""
    tag_id: Optional[str] = Field(None, description="The ID of the tag to delete.")
    tag_name: Optional[str] = Field(None, description="The name of the tag to delete.")
    created_by: str = Field(..., description="The email ID of the user performing the deletion.")

