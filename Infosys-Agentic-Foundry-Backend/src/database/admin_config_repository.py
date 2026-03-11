# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import asyncpg
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from src.config.constants import TableNames
from src.database.repositories import BaseRepository
from src.schemas.admin_config_schemas import AdminConfigLimits
from telemetry_wrapper import logger as log


class AdminConfigRepository(BaseRepository):
    """
    Repository for admin-configurable system limits.
    Single-row table storing global configuration.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.ADMIN_CONFIG.value):
        super().__init__(pool, login_pool, table_name)
        self._defaults = AdminConfigLimits()


    async def create_table_if_not_exists(self):
        """Creates the admin_config table with default values."""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            config_key VARCHAR(50) PRIMARY KEY,
            
            -- Critic Settings
            critic_score_threshold REAL NOT NULL DEFAULT {self._defaults.critic_score_threshold},
            max_critic_epochs INTEGER NOT NULL DEFAULT {self._defaults.max_critic_epochs},
            
            -- Evaluation Settings
            evaluation_score_threshold REAL NOT NULL DEFAULT {self._defaults.evaluation_score_threshold},
            max_evaluation_epochs INTEGER NOT NULL DEFAULT {self._defaults.max_evaluation_epochs},
            
            -- Validation Settings
            validation_score_threshold REAL NOT NULL DEFAULT {self._defaults.validation_score_threshold},
            max_validation_epochs INTEGER NOT NULL DEFAULT {self._defaults.max_validation_epochs},
            
            -- LangGraph Settings
            langgraph_recursion_limit INTEGER NOT NULL DEFAULT {self._defaults.langgraph_recursion_limit},
            
            -- Chat Settings
            chat_summary_interval INTEGER NOT NULL DEFAULT {self._defaults.chat_summary_interval},
            
            -- Audit Fields
            updated_by VARCHAR(255),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            
            -- Constraints
            CONSTRAINT chk_critic_threshold CHECK (critic_score_threshold >= 0.0 AND critic_score_threshold <= 1.0),
            CONSTRAINT chk_evaluation_threshold CHECK (evaluation_score_threshold >= 0.0 AND evaluation_score_threshold <= 1.0),
            CONSTRAINT chk_validation_threshold CHECK (validation_score_threshold >= 0.0 AND validation_score_threshold <= 1.0),
            CONSTRAINT chk_critic_epochs CHECK (max_critic_epochs >= 1 AND max_critic_epochs <= 10),
            CONSTRAINT chk_evaluation_epochs CHECK (max_evaluation_epochs >= 1 AND max_evaluation_epochs <= 10),
            CONSTRAINT chk_validation_epochs CHECK (max_validation_epochs >= 1 AND max_validation_epochs <= 10),
            CONSTRAINT chk_recursion_limit CHECK (langgraph_recursion_limit >= 1 AND langgraph_recursion_limit <= 200),
            CONSTRAINT chk_chat_summary_interval CHECK (chat_summary_interval >= 1 AND chat_summary_interval <= 100)
        );
        """

        insert_default_query = f"""
        INSERT INTO {self.table_name} (
            config_key,
            critic_score_threshold, max_critic_epochs,
            evaluation_score_threshold, max_evaluation_epochs,
            validation_score_threshold, max_validation_epochs,
            langgraph_recursion_limit, chat_summary_interval,
            updated_by, updated_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11
        )
        ON CONFLICT (config_key) DO NOTHING;
        """
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
                await conn.execute(
                    insert_default_query,
                    AdminConfigLimits.CONFIG_KEY,
                    self._defaults.critic_score_threshold,
                    self._defaults.max_critic_epochs,
                    self._defaults.evaluation_score_threshold,
                    self._defaults.max_evaluation_epochs,
                    self._defaults.validation_score_threshold,
                    self._defaults.max_validation_epochs,
                    self._defaults.langgraph_recursion_limit,
                    self._defaults.chat_summary_interval,
                    AdminConfigLimits.SYSTEM_USER,
                    datetime.now(timezone.utc)
                )
            log.info(f"Table '{self.table_name}' created/verified with default configuration.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            raise

    async def get_config(self) -> Optional[Dict[str, Any]]:
        """Retrieves the current admin configuration."""
        query = f"SELECT * FROM {self.table_name} WHERE config_key = $1"
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, AdminConfigLimits.CONFIG_KEY)
                if row:
                    result = dict(row)
                    result.pop('config_key', None)
                    return result
                return None
        except Exception as e:
            log.error(f"Error fetching admin config: {e}")
            return None

    async def update_config(self, updated_by: str, **config_updates) -> bool:
        """
        Updates the admin configuration with provided values.
        Only updates fields that are explicitly provided (not None).
        """
        updates = {k: v for k, v in config_updates.items() if v is not None}
        
        if not updates:
            log.warning("No valid updates provided to update_config")
            return False
        
        set_clauses = []
        values = []
        param_idx = 1
        
        for key, value in updates.items():
            set_clauses.append(f"{key} = ${param_idx}")
            values.append(value)
            param_idx += 1
        
        # Add audit fields
        set_clauses.append(f"updated_by = ${param_idx}")
        values.append(updated_by)
        param_idx += 1
        
        set_clauses.append(f"updated_at = ${param_idx}")
        values.append(datetime.now(timezone.utc))
        param_idx += 1
        
        values.append(AdminConfigLimits.CONFIG_KEY)
        
        query = f"""
        UPDATE {self.table_name}
        SET {', '.join(set_clauses)}
        WHERE config_key = ${param_idx}
        """
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, *values)
                success = result == "UPDATE 1"
                if success:
                    log.info(f"Admin config updated by {updated_by}: {updates}")
                return success
        except Exception as e:
            log.error(f"Error updating admin config: {e}")
            return False

    async def reset_to_defaults(self, updated_by: str) -> bool:
        """Resets all configuration values to defaults."""
        return await self.update_config(
            updated_by=updated_by,
            critic_score_threshold=self._defaults.critic_score_threshold,
            max_critic_epochs=self._defaults.max_critic_epochs,
            evaluation_score_threshold=self._defaults.evaluation_score_threshold,
            max_evaluation_epochs=self._defaults.max_evaluation_epochs,
            validation_score_threshold=self._defaults.validation_score_threshold,
            max_validation_epochs=self._defaults.max_validation_epochs,
            langgraph_recursion_limit=self._defaults.langgraph_recursion_limit,
            chat_summary_interval=self._defaults.chat_summary_interval
        )

