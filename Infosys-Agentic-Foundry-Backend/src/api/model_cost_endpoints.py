# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.

"""
Model Cost Management Endpoints

Admin API endpoints for managing model pricing without dependency on LiteLLM.
Allows manual CRUD operations on model_costs table for complete pricing control.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from decimal import Decimal

from src.auth.dependencies import get_current_user
from src.auth.models import User, UserRole
from src.api.dependencies import ServiceProvider
from src.config.constants import DatabaseName
from telemetry_wrapper import logger as log

router = APIRouter(prefix="/admin/model-costs", tags=["Admin - Model Costs"])


# ==========================================
# REQUEST/RESPONSE MODELS
# ==========================================

class ModelCostCreate(BaseModel):
    """Schema for creating a new model cost entry"""
    name: str = Field(..., description="Model identifier (e.g., 'gpt-4o', 'gpt-4o-mini')")
    model_name: str = Field(..., description="Display name of the model")
    model_version: Optional[str] = Field(None, description="Model version (e.g., '2024-11-20')")
    provider_key: str = Field(..., description="Provider identifier (e.g., 'openai', 'azure')")
    input_cost_per_token: Decimal = Field(..., description="Cost per input token (e.g., 0.00000015 for $0.15/1M tokens)")
    output_cost_per_token: Decimal = Field(..., description="Cost per output token")
    cache_read_input_token_cost: Optional[Decimal] = Field(0, description="Cost per cached input token")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "gpt-4o-mini",
                "model_name": "GPT-4o Mini",
                "model_version": "2024-07-18",
                "provider_key": "azure/gpt-4o-mini",
                "input_cost_per_token": 0.00000015,
                "output_cost_per_token": 0.0000006,
                "cache_read_input_token_cost": 0.000000075
            }
        }


class ModelCostUpdate(BaseModel):
    """Schema for updating an existing model cost entry"""
    model_name: Optional[str] = None
    model_version: Optional[str] = None
    provider_key: Optional[str] = None
    input_cost_per_token: Optional[Decimal] = None
    output_cost_per_token: Optional[Decimal] = None
    cache_read_input_token_cost: Optional[Decimal] = None


class ModelCostResponse(BaseModel):
    """Schema for model cost response"""
    id: int
    name: str
    model_name: str
    model_version: Optional[str]
    provider_key: str
    input_cost_per_token: float
    output_cost_per_token: float
    cache_read_input_token_cost: float
    created_at: datetime
    updated_at: datetime


class BulkModelCostCreate(BaseModel):
    """Schema for bulk creating model costs"""
    models: List[ModelCostCreate] = Field(..., description="List of model cost entries to create")





# ==========================================
# AUTHORIZATION HELPER
# ==========================================

async def require_admin(current_user: User = Depends(get_current_user)):
    """Ensure user has admin privileges"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN, "Admin", "SuperAdmin"]:
        raise HTTPException(
            status_code=403,
            detail="Admin privileges required to manage model costs"
        )
    return current_user


# ==========================================
# SIMPLIFIED CRUD ENDPOINTS - CREATE, UPDATE, DELETE ONLY
# ==========================================

@router.post("", response_model=ModelCostResponse, summary="Create or Update Model Cost")
async def create_or_update_model_cost(
    cost_data: ModelCostCreate,
    current_user: User = Depends(require_admin)
):
    """
    Create a new model cost entry or update if it already exists.
    
    **Admin only** - Allows manual configuration of model pricing.
    """
    try:
        db_manager = ServiceProvider.get_database_manager()
        db_pool = await db_manager.get_pool(DatabaseName.MAIN.db_name)
        async with db_pool.acquire() as conn:
            # Check if model already exists
            existing = await conn.fetchrow(
                "SELECT id FROM model_costs WHERE name = $1",
                cost_data.name
            )
            
            # Validate required fields are not None
            if not cost_data.model_name or not cost_data.provider_key:
                raise HTTPException(
                    status_code=400,
                    detail="model_name and provider_key are required fields"
                )
            
            # Ensure cost values are not None (use 0 as default)
            input_cost = cost_data.input_cost_per_token if cost_data.input_cost_per_token is not None else 0
            output_cost = cost_data.output_cost_per_token if cost_data.output_cost_per_token is not None else 0
            cache_cost = cost_data.cache_read_input_token_cost if cost_data.cache_read_input_token_cost is not None else 0
            
            if existing:
                # Update existing entry
                row = await conn.fetchrow("""
                    UPDATE model_costs
                    SET model_name = $2, model_version = $3, provider_key = $4,
                        input_cost_per_token = $5, output_cost_per_token = $6, 
                        cache_read_input_token_cost = $7, updated_at = CURRENT_TIMESTAMP
                    WHERE name = $1
                    RETURNING id, name, model_name, model_version, provider_key,
                              input_cost_per_token, output_cost_per_token, 
                              cache_read_input_token_cost, updated_at
                """, cost_data.name, cost_data.model_name, cost_data.model_version,
                     cost_data.provider_key, input_cost, output_cost, cache_cost)
                
                log.info(f"✅ Admin '{current_user.username}' updated model cost: {cost_data.name}")
            else:
                # Insert new model cost
                row = await conn.fetchrow("""
                    INSERT INTO model_costs (
                        name, model_name, model_version, provider_key,
                        input_cost_per_token, output_cost_per_token, cache_read_input_token_cost
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING id, name, model_name, model_version, provider_key,
                              input_cost_per_token, output_cost_per_token, 
                              cache_read_input_token_cost, updated_at
                """, cost_data.name, cost_data.model_name, cost_data.model_version,
                     cost_data.provider_key, input_cost, output_cost, cache_cost)
                
                log.info(f"✅ Admin '{current_user.username}' created model cost: {cost_data.name}")
            
            # Reload cost cache so GET /get/models reflects changes immediately
            from litellm_standalone_tracker import reload_cost_cache
            await reload_cost_cache()

            return ModelCostResponse(
                id=row['id'],
                name=row['name'],
                model_name=row['model_name'] or '',
                model_version=row['model_version'],
                provider_key=row['provider_key'] or '',
                input_cost_per_token=float(row['input_cost_per_token']) if row['input_cost_per_token'] is not None else 0.0,
                output_cost_per_token=float(row['output_cost_per_token']) if row['output_cost_per_token'] is not None else 0.0,
                cache_read_input_token_cost=float(row['cache_read_input_token_cost']) if row['cache_read_input_token_cost'] is not None else 0.0,
                created_at=row['updated_at'],
                updated_at=row['updated_at']
            )
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error creating/updating model cost: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create model cost: {str(e)}")


@router.get("", response_model=List[ModelCostResponse], summary="Get All Model Costs")
async def get_all_model_costs(
    current_user: User = Depends(require_admin)
):
    """
    Retrieve all model cost entries from the database.
    
    **Admin only** - View all configured model pricing.
    """
    try:
        db_manager = ServiceProvider.get_database_manager()
        db_pool = await db_manager.get_pool(DatabaseName.MAIN.db_name)
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, name, model_name, model_version, provider_key,
                       input_cost_per_token, output_cost_per_token, 
                       cache_read_input_token_cost, updated_at
                FROM model_costs
                ORDER BY id ASC
            """)
            
            models = []
            for row in rows:
                models.append(ModelCostResponse(
                    id=row['id'],
                    name=row['name'],
                    model_name=row['model_name'] or '',
                    model_version=row['model_version'],
                    provider_key=row['provider_key'] or '',
                    input_cost_per_token=float(row['input_cost_per_token']) if row['input_cost_per_token'] is not None else 0.0,
                    output_cost_per_token=float(row['output_cost_per_token']) if row['output_cost_per_token'] is not None else 0.0,
                    cache_read_input_token_cost=float(row['cache_read_input_token_cost']) if row['cache_read_input_token_cost'] is not None else 0.0,
                    created_at=row['updated_at'],  # Use updated_at for both
                    updated_at=row['updated_at']
                ))
            
            log.info(f"✅ Admin '{current_user.username}' retrieved {len(models)} model costs")
            return models
    
    except Exception as e:
        log.error(f"❌ Error retrieving model costs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve model costs: {str(e)}")


@router.put("/{model_name:path}", response_model=ModelCostResponse, summary="Update Model Cost")
@router.post("/update/{model_name:path}", response_model=ModelCostResponse, summary="Update Model Cost")
async def update_model_cost(
    model_name: str,
    cost_data: ModelCostUpdate,
    current_user: User = Depends(require_admin)
):
    """
    Update an existing model cost entry.
    
    **Admin only** - Update pricing for a model.
    """
    try:
        db_manager = ServiceProvider.get_database_manager()
        db_pool = await db_manager.get_pool(DatabaseName.MAIN.db_name)
        
        # Build update query dynamically
        updates = []
        params = [model_name]
        param_count = 1
        
        if cost_data.model_name is not None:
            if not cost_data.model_name:  # Empty string validation
                raise HTTPException(status_code=400, detail="model_name cannot be empty")
            param_count += 1
            updates.append(f"model_name = ${param_count}")
            params.append(cost_data.model_name)
        
        if cost_data.model_version is not None:
            param_count += 1
            updates.append(f"model_version = ${param_count}")
            params.append(cost_data.model_version)
        
        if cost_data.provider_key is not None:
            if not cost_data.provider_key:  # Empty string validation
                raise HTTPException(status_code=400, detail="provider_key cannot be empty")
            param_count += 1
            updates.append(f"provider_key = ${param_count}")
            params.append(cost_data.provider_key)
        
        if cost_data.input_cost_per_token is not None:
            param_count += 1
            updates.append(f"input_cost_per_token = ${param_count}")
            params.append(cost_data.input_cost_per_token)
        
        if cost_data.output_cost_per_token is not None:
            param_count += 1
            updates.append(f"output_cost_per_token = ${param_count}")
            params.append(cost_data.output_cost_per_token)
        
        if cost_data.cache_read_input_token_cost is not None:
            param_count += 1
            updates.append(f"cache_read_input_token_cost = ${param_count}")
            params.append(cost_data.cache_read_input_token_cost)
        
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        updates.append("updated_at = CURRENT_TIMESTAMP")
        
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(f"""
                UPDATE model_costs
                SET {', '.join(updates)}
                WHERE name = $1
                RETURNING id, name, model_name, model_version, provider_key,
                          input_cost_per_token, output_cost_per_token, 
                          cache_read_input_token_cost, updated_at
            """, *params)
            
            if not row:
                raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")
            
            log.info(f"Admin '{current_user.username}' updated model cost: {model_name}")
            
            from litellm_standalone_tracker import reload_cost_cache
            await reload_cost_cache()

            return ModelCostResponse(
                id=row['id'],
                name=row['name'],
                model_name=row['model_name'] or '',
                model_version=row['model_version'],
                provider_key=row['provider_key'] or '',
                input_cost_per_token=float(row['input_cost_per_token']) if row['input_cost_per_token'] is not None else 0.0,
                output_cost_per_token=float(row['output_cost_per_token']) if row['output_cost_per_token'] is not None else 0.0,
                cache_read_input_token_cost=float(row['cache_read_input_token_cost']) if row['cache_read_input_token_cost'] is not None else 0.0,
                created_at=row['updated_at'],
                updated_at=row['updated_at']
            )
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error updating model cost: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update model cost: {str(e)}")


@router.delete("/{model_name:path}", summary="Delete Model Cost")
@router.post("/delete/{model_name:path}", summary="Delete Model Cost")
async def delete_model_cost(
    model_name: str,
    current_user: User = Depends(require_admin)
):
    """
    Delete a model cost entry.
    
    **Admin only** - Remove a model from pricing configuration.
    """
    try:
        db_manager = ServiceProvider.get_database_manager()
        db_pool = await db_manager.get_pool(DatabaseName.MAIN.db_name)
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM model_costs WHERE name = $1",
                model_name
            )
            
            if result == "DELETE 0":
                raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")
            
            log.info(f"Admin '{current_user.username}' deleted model cost: {model_name}")
            
            from litellm_standalone_tracker import reload_cost_cache
            await reload_cost_cache()

            return {
                "deleted": True,
                "model_name": model_name,
                "message": f"Model cost '{model_name}' deleted successfully"
            }
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error deleting model cost: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete model cost: {str(e)}")
