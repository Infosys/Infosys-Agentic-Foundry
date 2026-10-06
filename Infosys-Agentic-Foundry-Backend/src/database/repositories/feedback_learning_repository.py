# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import asyncpg
from typing import List, Dict, Any
from src.config.constants import TableNames

from telemetry_wrapper import logger as log

from src.database.repositories import BaseRepository


class FeedbackLearningRepository(BaseRepository):
    """
    Repository for feedback data. Handles direct database interactions for
    'feedback_response' and 'agent_feedback' tables.
    """

    def __init__(self, pool: asyncpg.Pool,
                 login_pool: asyncpg.Pool,
                 feedback_table_name: str = TableNames.FEEDBACK_LEARNING.value,
                 agent_feedback_table_name: str = TableNames.AGENT_FEEDBACK.value):
        super().__init__(pool, login_pool, table_name=feedback_table_name)
        self.feedback_table_name = feedback_table_name
        self.agent_feedback_table_name = agent_feedback_table_name


    async def create_tables_if_not_exists(self):
        """
        Creates the 'feedback_response' and 'agent_feedback' tables if they don't exist.
        If feedback_response table exists, alters it to add the 'lesson' field if missing.
        Also migrates from boolean 'approved' column to text 'status' column if needed.
        Also migrates from boolean 'approved' column to text 'status' column if needed.
        """
        create_feedback_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.feedback_table_name} (
            response_id TEXT PRIMARY KEY,
            query TEXT,
            old_final_response TEXT,
            old_steps TEXT,
            old_response TEXT,
            feedback TEXT,
            new_final_response TEXT,
            new_steps TEXT,
            new_response TEXT,
            lesson TEXT,
            department_name TEXT DEFAULT 'General',
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        create_agent_feedback_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.agent_feedback_table_name} (
            agent_id TEXT,
            response_id TEXT,
            PRIMARY KEY (agent_id, response_id),
            FOREIGN KEY (response_id) REFERENCES {self.feedback_table_name}(response_id) ON DELETE CASCADE
        );
        """
        
        check_column_exists_query = f"""
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = '{self.feedback_table_name}'
            AND column_name = 'lesson'
        );
        """
        
        alter_table_lesson_query = f"""
        ALTER TABLE {self.feedback_table_name}
        ADD COLUMN IF NOT EXISTS lesson TEXT;
        """
        
        alter_table_department_query = f"""
        ALTER TABLE {self.feedback_table_name}
        ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General';
        """
        
        # Migration: Add status column if not exists
        alter_table_add_status_query = f"""
        ALTER TABLE {self.feedback_table_name}
        ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending';
        """
        
        # Migration: Convert approved boolean to status text if approved column exists
        migrate_approved_to_status_query = f"""
        UPDATE {self.feedback_table_name}
        SET status = CASE 
            WHEN approved = TRUE THEN 'approve'
            ELSE 'pending'
        END
        WHERE status IS NULL OR status = 'pending';
        """
        
        try:
            async with self.pool.acquire() as conn:
                # First create tables if they don't exist
                await conn.execute(create_feedback_table_query)
                await conn.execute(create_agent_feedback_table_query)
                
                # Check if the feedback_table exists and if it's missing the lesson column
                table_exists = await conn.fetchval(
                    f"SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = '{self.feedback_table_name}')"
                )
                
                if table_exists:
                    # If table exists, check if lesson column exists and add it if missing
                    await conn.execute(alter_table_lesson_query)
                    await conn.execute(alter_table_department_query)
                    
                    # Add status column and migrate from approved if needed
                    await conn.execute(alter_table_add_status_query)
                    
                    # Check if approved column exists and migrate data
                    approved_col_exists = await conn.fetchval(
                        f"SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_name = '{self.feedback_table_name}' AND column_name = 'approved')"
                    )
                    if approved_col_exists:
                        await conn.execute(migrate_approved_to_status_query)
                        log.info(f"Migrated 'approved' boolean values to 'status' text in {self.feedback_table_name} table.")
                    
                    log.info(f"Added 'lesson', 'department_name', and 'status' columns to {self.feedback_table_name} table if they were missing.")
                    
            log.info("Feedback storage tables created successfully or already exist.")
        except Exception as e:
            log.error(f"Error creating feedback storage tables: {e}")
            raise # Re-raise for service to handle

    async def insert_feedback_record(self, response_id: str, query: str, old_final_response: str, old_steps: str, feedback: str, new_final_response: str, new_steps: str, lesson: str, department_name: str = None, status: str = 'pending') -> bool:
        """
        Inserts a new feedback response record.
        status should be one of: 'pending', 'approve', 'reject'
        """
        insert_query = f"""
        INSERT INTO {self.feedback_table_name} (
            response_id, query, old_final_response, old_steps, feedback, new_final_response, new_steps, status, lesson, department_name
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10);
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(insert_query, response_id, query, old_final_response, old_steps, feedback, new_final_response, new_steps, status, lesson, department_name)
            return True
        except Exception as e:
            log.error(f"Error inserting feedback record for response_id '{response_id}': {e}")
            return False

    async def insert_agent_feedback_mapping(self, agent_id: str, response_id: str) -> bool:
        """
        Inserts a mapping between an agent and a feedback response.
        """
        insert_query = f"""
        INSERT INTO {self.agent_feedback_table_name} (agent_id, response_id)
        VALUES ($1, $2);
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(insert_query, agent_id, response_id)
            return True
        except Exception as e:
            log.error(f"Error inserting agent feedback mapping for agent_id '{agent_id}', response_id '{response_id}': {e}")
            return False

    async def get_approved_feedback_records(self, agent_id: str, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves approved feedback records for a specific agent, optionally filtered by department_name.
        """
        select_query = f"""
        SELECT fr.response_id, fr.query, fr.old_final_response, fr.old_steps, fr.feedback, fr.new_final_response, fr.new_steps, fr.lesson, fr.status, fr.created_at, fr.department_name 
        FROM {self.feedback_table_name} fr
        INNER JOIN {self.agent_feedback_table_name} af ON fr.response_id = af.response_id
        WHERE af.agent_id = $1 AND fr.status = 'approve'"""
        
        params = [agent_id]
        if department_name:
            select_query += " AND fr.department_name = $2"
            params.append(department_name)
        
        select_query += ";"
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(select_query, *params)
            log.info(f"Retrieved {len(rows)} approved feedback records for agent '{agent_id}' in department '{department_name}'")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving approved feedback records for agent '{agent_id}': {e}")
            return []

    async def get_all_feedback_records_by_agent(self, agent_id: str, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves all feedback records (regardless of approval status) for a given agent, optionally filtered by department_name.
        """
        select_query = f"""
        SELECT af.response_id, fr.feedback, fr.status, fr.department_name, fr.lesson
        FROM {self.feedback_table_name} fr
        JOIN {self.agent_feedback_table_name} af ON fr.response_id = af.response_id
        WHERE af.agent_id = $1"""
        
        params = [agent_id]
        if department_name:
            select_query += " AND fr.department_name = $2"
            params.append(department_name)
        
        select_query += ";"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(select_query, *params)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving all feedback records for agent '{agent_id}': {e}")
            return []

    async def get_feedback_record_by_response_id(self, response_id: str, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves a single feedback record by its response_id, optionally filtered by department_name.
        """
        select_query = f"""
        SELECT fr.response_id, fr.query, fr.old_final_response, fr.old_steps, fr.feedback, fr.new_final_response, fr.new_steps, fr.lesson, fr.status, fr.created_at, fr.department_name, af.agent_id FROM {self.feedback_table_name} fr
        JOIN {self.agent_feedback_table_name} af ON fr.response_id = af.response_id
        WHERE fr.response_id = $1"""
        
        params = [response_id]
        if department_name:
            select_query += " AND fr.department_name = $2"
            params.append(department_name)
        
        select_query += ";"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(select_query, *params)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving feedback record for response_id '{response_id}': {e}")
            return []

    async def get_distinct_agents_with_feedback(self, department_name: str = None) -> List[str]:
        """
        Retrieves a list of distinct agent_ids that have associated feedback, optionally filtered by department_name.
        """
        if department_name:
            select_query = f"""
            SELECT DISTINCT af.agent_id 
            FROM {self.agent_feedback_table_name} af
            JOIN {self.feedback_table_name} fr ON af.response_id = fr.response_id
            WHERE fr.department_name = $1;
            """
            params = [department_name]
        else:
            select_query = f"SELECT DISTINCT agent_id FROM {self.agent_feedback_table_name};"
            params = []
            
        try:
            async with self.pool.acquire() as conn:
                if params:
                    rows = await conn.fetch(select_query, *params)
                else:
                    rows = await conn.fetch(select_query)
            return [row['agent_id'] for row in rows]
        except Exception as e:
            log.error(f"Error retrieving distinct agents with feedback: {e}")
            return []

    async def update_feedback_record(self, response_id: str, update_data: Dict[str, Any], department_name: str= None) -> bool:
        """
        Updates fields in a feedback_response record, optionally filtered by department_name.
        `update_data` should be a dictionary of column_name: new_value.
        """
        if not update_data:
            return False

        set_clause = ', '.join([f"{key} = ${i+1}" for i, key in enumerate(update_data.keys())])
        values = list(update_data.values())
        values.append(response_id) # response_id parameter

        where_clause = f"response_id = ${len(values)}"
        if department_name:
            values.append(department_name)
            where_clause += f" AND department_name = ${len(values)}"

        update_query = f"""
        UPDATE {self.feedback_table_name}
        SET {set_clause}
        WHERE {where_clause};
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(update_query, *values)
            return result != "UPDATE 0"
        except Exception as e:
            log.error(f"Error updating feedback record for response_id '{response_id}': {e}")
            return False
        
    async def migrate_agent_ids_to_hyphens(self) -> Dict[str, Any]:
        """
        Migrates agent_id values in the agent_feedback table:
        - Replaces all hyphens with underscores in the prefix (everything before the last 32 characters).
        - Replaces all underscores with hyphens in the last 32 characters (UUID part).

        Returns:
            Dict[str, Any]: A dictionary indicating the status of the migration.
        """
        log.info(f"Starting full migration of agent_id in '{self.agent_feedback_table_name}'.")

        update_query = f"""
        UPDATE {self.agent_feedback_table_name}
        SET agent_id = 
            REPLACE(LEFT(agent_id, LENGTH(agent_id) - 32), '-', '_') || 
            REPLACE(RIGHT(agent_id, 32), '_', '-');
        """

        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(update_query)
                rows_updated = int(result.split()[-1])

                log.info(f"Migration complete for '{self.agent_feedback_table_name}'. {rows_updated} rows updated.")
                return {"status": "success", "message": f"Successfully migrated {rows_updated} agent_id records."}
        except Exception as e:
            log.error(f"Error during agent_id migration in '{self.agent_feedback_table_name}': {e}", exc_info=True)
            return {"status": "error", "message": f"Failed to migrate agent_id records: {e}"}

    async def get_all_feedback_records(self, department_name: str = None, agent_ids: List[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves all feedback records, optionally filtered by department_name and agent_ids.
        When agent_ids is provided, only returns feedback for those agents (e.g. agents that exist in main DB).
        """
        select_query = f"""
        SELECT fr.response_id, fr.query, fr.old_final_response, fr.old_steps, fr.feedback, 
               fr.new_final_response, fr.new_steps, fr.lesson, fr.status, fr.created_at, 
               fr.department_name, af.agent_id 
        FROM {self.feedback_table_name} fr
        JOIN {self.agent_feedback_table_name} af ON fr.response_id = af.response_id"""
        
        params = []
        conditions = []
        param_idx = 1
        if department_name:
            conditions.append(f"fr.department_name = ${param_idx}")
            params.append(department_name)
            param_idx += 1
        if agent_ids:
            conditions.append(f"af.agent_id = ANY(${param_idx}::text[])")
            params.append(agent_ids)
        if conditions:
            select_query += " WHERE " + " AND ".join(conditions)
        select_query += " ORDER BY fr.created_at DESC;"
        
        try:
            async with self.pool.acquire() as conn:
                if params:
                    rows = await conn.fetch(select_query, *params)
                else:
                    rows = await conn.fetch(select_query)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving all feedback records: {e}")
            return []

    async def get_total_feedback_count(self, department_name: str = None, agent_ids: List[str] = None) -> int:
        """
        Returns the total count of feedback records, optionally filtered by department_name and agent_ids.
        """
        if agent_ids is not None and len(agent_ids) == 0:
            return 0
        select_query = f"SELECT COUNT(*) FROM {self.feedback_table_name} fr JOIN {self.agent_feedback_table_name} af ON fr.response_id = af.response_id"
        params = []
        conditions = []
        param_idx = 1
        if department_name:
            conditions.append(f"fr.department_name = ${param_idx}")
            params.append(department_name)
            param_idx += 1
        if agent_ids:
            conditions.append(f"af.agent_id = ANY(${param_idx}::text[])")
            params.append(agent_ids)
        if conditions:
            select_query += " WHERE " + " AND ".join(conditions)
        select_query += ";"
        try:
            async with self.pool.acquire() as conn:
                if params:
                    count = await conn.fetchval(select_query, *params)
                else:
                    count = await conn.fetchval(select_query)
            return count or 0
        except Exception as e:
            log.error(f"Error retrieving total feedback count: {e}")
            return 0

    async def get_approved_feedback_count(self, department_name: str = None, agent_ids: List[str] = None) -> int:
        """
        Returns the count of approved feedback records, optionally filtered by department_name and agent_ids.
        """
        if agent_ids is not None and len(agent_ids) == 0:
            return 0
        select_query = f"SELECT COUNT(*) FROM {self.feedback_table_name} fr JOIN {self.agent_feedback_table_name} af ON fr.response_id = af.response_id WHERE fr.approved = TRUE"
        params = []
        conditions = []
        param_idx = 1
        if department_name:
            conditions.append(f"fr.department_name = ${param_idx}")
            params.append(department_name)
            param_idx += 1
        if agent_ids:
            conditions.append(f"af.agent_id = ANY(${param_idx}::text[])")
            params.append(agent_ids)
        if conditions:
            select_query += " AND " + " AND ".join(conditions)
        select_query += ";"
        try:
            async with self.pool.acquire() as conn:
                if params:
                    count = await conn.fetchval(select_query, *params)
                else:
                    count = await conn.fetchval(select_query)
            return count or 0
        except Exception as e:
            log.error(f"Error retrieving approved feedback count: {e}")
            return 0

    async def get_pending_feedback_count(self, department_name: str = None, agent_ids: List[str] = None) -> int:
        """
        Returns the count of pending (not approved) feedback records, optionally filtered by department_name and agent_ids.
        """
        if agent_ids is not None and len(agent_ids) == 0:
            return 0
        select_query = f"SELECT COUNT(*) FROM {self.feedback_table_name} fr JOIN {self.agent_feedback_table_name} af ON fr.response_id = af.response_id WHERE fr.approved = FALSE"
        params = []
        conditions = []
        param_idx = 1
        if department_name:
            conditions.append(f"fr.department_name = ${param_idx}")
            params.append(department_name)
            param_idx += 1
        if agent_ids:
            conditions.append(f"af.agent_id = ANY(${param_idx}::text[])")
            params.append(agent_ids)
        if conditions:
            select_query += " AND " + " AND ".join(conditions)
        select_query += ";"
        try:
            async with self.pool.acquire() as conn:
                if params:
                    count = await conn.fetchval(select_query, *params)
                else:
                    count = await conn.fetchval(select_query)
            return count or 0
        except Exception as e:
            log.error(f"Error retrieving pending feedback count: {e}")
            return 0

    async def get_rejected_feedback_count(self, department_name: str = None) -> int:
        """
        Returns the count of rejected feedback records, optionally filtered by department_name.
        """
        select_query = f"SELECT COUNT(*) FROM {self.feedback_table_name} WHERE status = 'reject'"
        params = []
        if department_name:
            select_query += " AND department_name = $1"
            params.append(department_name)
        select_query += ";"
        
        try:
            async with self.pool.acquire() as conn:
                if params:
                    count = await conn.fetchval(select_query, *params)
                else:
                    count = await conn.fetchval(select_query)
            return count or 0
        except Exception as e:
            log.error(f"Error retrieving rejected feedback count: {e}")
            return 0

    async def get_rejected_feedback_count(self, department_name: str = None) -> int:
        """
        Returns the count of rejected feedback records, optionally filtered by department_name.
        """
        select_query = f"SELECT COUNT(*) FROM {self.feedback_table_name} WHERE status = 'reject'"
        params = []
        if department_name:
            select_query += " AND department_name = $1"
            params.append(department_name)
        select_query += ";"
        
        try:
            async with self.pool.acquire() as conn:
                if params:
                    count = await conn.fetchval(select_query, *params)
                else:
                    count = await conn.fetchval(select_query)
            return count or 0
        except Exception as e:
            log.error(f"Error retrieving rejected feedback count: {e}")
            return 0

    async def get_agents_with_feedback_count(self, department_name: str = None, agent_ids: List[str] = None) -> int:
        """
        Returns the count of distinct agents that have associated feedback, optionally filtered by department_name and agent_ids.
        """
        if agent_ids is not None and len(agent_ids) == 0:
            return 0
        select_query = f"""
            SELECT COUNT(DISTINCT af.agent_id) 
            FROM {self.agent_feedback_table_name} af
            JOIN {self.feedback_table_name} fr ON af.response_id = fr.response_id"""
        params = []
        conditions = []
        param_idx = 1
        if department_name:
            conditions.append(f"fr.department_name = ${param_idx}")
            params.append(department_name)
            param_idx += 1
        if agent_ids:
            conditions.append(f"af.agent_id = ANY(${param_idx}::text[])")
            params.append(agent_ids)
        if conditions:
            select_query += " WHERE " + " AND ".join(conditions)
        select_query += ";"
        try:
            async with self.pool.acquire() as conn:
                if params:
                    count = await conn.fetchval(select_query, *params)
                else:
                    count = await conn.fetchval(select_query)
            return count or 0
        except Exception as e:
            log.error(f"Error retrieving agents with feedback count: {e}")
            return 0

    async def get_feedback_stats(self, department_name: str = None, agent_ids: List[str] = None) -> Dict[str, Any]:
        """
        Returns aggregated feedback statistics including total, approved, pending, rejected counts and agent count.
        Returns aggregated feedback statistics including total, approved, pending, rejected counts and agent count.
        """
        try:
            total_count = await self.get_total_feedback_count(department_name)
            approved_count = await self.get_approved_feedback_count(department_name)
            pending_count = await self.get_pending_feedback_count(department_name)
            rejected_count = await self.get_rejected_feedback_count(department_name)
            rejected_count = await self.get_rejected_feedback_count(department_name)
            agents_count = await self.get_agents_with_feedback_count(department_name)
            
            return {
                "total_feedback": total_count,
                "approved_feedback": approved_count,
                "pending_feedback": pending_count,
                "rejected_feedback": rejected_count,
                "rejected_feedback": rejected_count,
                "agents_with_feedback": agents_count
            }
        except Exception as e:
            log.error(f"Error retrieving feedback stats: {e}")
            return {
                "total_feedback": 0,
                "approved_feedback": 0,
                "pending_feedback": 0,
                "rejected_feedback": 0,
                "rejected_feedback": 0,
                "agents_with_feedback": 0
            }

    async def delete_feedback_by_agent_id(self, agent_id: str) -> Dict[str, Any]:
        """
        Deletes all feedback/learning records for a specific agent.
        
        This method:
        1. Retrieves all response_ids associated with the agent_id from agent_feedback table
        2. Deletes those records from feedback_response table (cascades to agent_feedback)
        
        Args:
            agent_id (str): The ID of the agent whose feedback records should be deleted.
            
        Returns:
            Dict[str, Any]: A dictionary with status and count of deleted records.
        """
        # First, get all response_ids for this agent
        get_response_ids_query = f"""
        SELECT response_id FROM {self.agent_feedback_table_name}
        WHERE agent_id = $1;
        """
        
        try:
            async with self.pool.acquire() as conn:
                # Get all response_ids for this agent
                rows = await conn.fetch(get_response_ids_query, agent_id)
                response_ids = [row['response_id'] for row in rows]
                
                if not response_ids:
                    log.info(f"No feedback records found for agent_id '{agent_id}'.")
                    return {
                        "status": "success",
                        "message": f"No feedback records found for agent_id '{agent_id}'.",
                        "deleted_count": 0
                    }
                
                # Delete from feedback_response table (CASCADE will handle agent_feedback)
                delete_query = f"""
                DELETE FROM {self.feedback_table_name}
                WHERE response_id = ANY($1);
                """
                result = await conn.execute(delete_query, response_ids)
                deleted_count = int(result.split()[-1])
                
                log.info(f"Successfully deleted {deleted_count} feedback records for agent_id '{agent_id}'.")
                return {
                    "status": "success",
                    "message": f"Successfully deleted {deleted_count} feedback records for agent_id '{agent_id}'.",
                    "deleted_count": deleted_count
                }
        except Exception as e:
            log.error(f"Error deleting feedback records for agent_id '{agent_id}': {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Failed to delete feedback records: {e}",
                "deleted_count": 0
            }

    async def delete_orphaned_feedback_records(self) -> Dict[str, Any]:
        """
        Deletes feedback records where the associated agent_id no longer exists 
        in either the agent table or the recycle_agent table.
        
        This method:
        1. Gets all distinct agent_ids from the agent_feedback table
        2. Identifies orphaned agent_ids (not in agent_table or recycle_agent)
        3. Deletes feedback records for those orphaned agent_ids
        
        Returns:
            Dict[str, Any]: A dictionary with status, message, deleted count, and orphaned agent_ids.
        """
        log.info("Starting cleanup of orphaned feedback records.")
        
        # Query to find orphaned agent_ids (not in agent_table or recycle_agent)
        get_orphaned_agents_query = f"""
        SELECT DISTINCT af.agent_id 
        FROM {self.agent_feedback_table_name} af
        WHERE NOT EXISTS (
            SELECT 1 FROM {TableNames.AGENT.value} a 
            WHERE a.agentic_application_id = af.agent_id
        )
        AND NOT EXISTS (
            SELECT 1 FROM {TableNames.RECYCLE_AGENT.value} ra 
            WHERE ra.agentic_application_id = af.agent_id
        );
        """
        
        try:
            async with self.pool.acquire() as conn:
                # Get all orphaned agent_ids
                rows = await conn.fetch(get_orphaned_agents_query)
                orphaned_agent_ids = [row['agent_id'] for row in rows]
                
                if not orphaned_agent_ids:
                    log.info("No orphaned feedback records found.")
                    return {
                        "status": "success",
                        "message": "No orphaned feedback records found.",
                        "deleted_count": 0,
                        "orphaned_agent_ids": []
                    }
                
                log.info(f"Found {len(orphaned_agent_ids)} orphaned agent_ids: {orphaned_agent_ids}")
                
                # Get all response_ids for orphaned agents
                get_response_ids_query = f"""
                SELECT response_id FROM {self.agent_feedback_table_name}
                WHERE agent_id = ANY($1);
                """
                response_rows = await conn.fetch(get_response_ids_query, orphaned_agent_ids)
                response_ids = [row['response_id'] for row in response_rows]
                
                if not response_ids:
                    log.info("No feedback response records to delete.")
                    return {
                        "status": "success",
                        "message": "No feedback response records to delete.",
                        "deleted_count": 0,
                        "orphaned_agent_ids": orphaned_agent_ids
                    }
                
                # Delete from feedback_response table (CASCADE will handle agent_feedback)
                delete_query = f"""
                DELETE FROM {self.feedback_table_name}
                WHERE response_id = ANY($1);
                """
                result = await conn.execute(delete_query, response_ids)
                deleted_count = int(result.split()[-1])
                
                log.info(f"Successfully deleted {deleted_count} orphaned feedback records for {len(orphaned_agent_ids)} orphaned agents.")
                return {
                    "status": "success",
                    "message": f"Successfully deleted {deleted_count} orphaned feedback records for {len(orphaned_agent_ids)} orphaned agents.",
                    "deleted_count": deleted_count,
                    "orphaned_agent_ids": orphaned_agent_ids
                }
        except Exception as e:
            log.error(f"Error deleting orphaned feedback records: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Failed to delete orphaned feedback records: {e}",
                "deleted_count": 0,
                "orphaned_agent_ids": []
            }

