# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from pydantic import BaseModel, Field
from typing import List, Optional

class SecretCreateRequest(BaseModel):
    """Schema for creating a new user-specific secret_data."""
    user_email: str = Field(..., description="The email of the user for whom the secret is created.")
    key_name: str = Field(..., description="The name of the secret (e.g., 'API_KEY').")
    key_value: str = Field(..., description="The value of the secret.")

class PublicSecretCreateRequest(BaseModel):
    """Schema for creating a new public secret_data."""
    key_name: str = Field(..., description="The name of the public secret.")
    key_value: str = Field(..., description="The value of the public secret.")

class SecretUpdateRequest(BaseModel):
    """Schema for updating an existing user-specific secret_data."""
    user_email: str = Field(..., description="The email of the user whose secret is updated.")
    key_name: str = Field(..., description="The name of the secret to update.")
    key_value: str = Field(..., description="The new value of the secret.")

class PublicSecretUpdateRequest(BaseModel):
    """Schema for updating an existing public secret_data."""
    key_name: str = Field(..., description="The name of the public secret to update.")
    key_value: str = Field(..., description="The new value of the public secret.")

class SecretDeleteRequest(BaseModel):
    """Schema for deleting a user-specific secret_data."""
    user_email: str = Field(..., description="The email of the user whose secret is deleted.")
    key_name: str = Field(..., description="The name of the secret to delete.")

class PublicSecretDeleteRequest(BaseModel):
    """Schema for deleting a public secret_data."""
    key_name: str = Field(..., description="The name of the public secret to delete.")

class SecretGetRequest(BaseModel):
    """Schema for retrieving user-specific secrets."""
    user_email: str = Field(..., description="The email of the user whose secrets are requested.")
    key_name: Optional[str] = Field(None, description="Optional: The name of a specific secret to retrieve.")
    key_names: Optional[List[str]] = Field(None, description="Optional: A list of specific secret names to retrieve.")

class PublicSecretGetRequest(BaseModel):
    """Schema for retrieving a public secret_data."""
    key_name: Optional[str] = Field(None, description="The name of the public secret to retrieve.")

class SecretListRequest(BaseModel):
    """Schema for listing user-specific secret_data names."""
    user_email: str = Field(..., description="The email of the user whose secret names are requested.")

