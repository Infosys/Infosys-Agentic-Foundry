# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import asyncpg
from typing import List, Dict, Any, Optional

from src.config.constants import TableNames
from src.auth.models import User, UserRole

from telemetry_wrapper import logger as log

from src.database.repositories import BaseRepository, AgentRepository


# --- EvaluationDataRepository ---

class EvaluationDataRepository(BaseRepository):
    """
    Repository for 'evaluation_data' table. Handles direct database interactions.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, agent_repo: AgentRepository,  table_name: str = TableNames.EVALUATION_DATA.value):
        super().__init__(pool, login_pool, table_name)
        self.agent_repo = agent_repo


    async def create_table_if_not_exists(self):
        """Creates the 'evaluation_data' table if it does not exist."""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id SERIAL PRIMARY KEY,
            time_stamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            session_id TEXT,
            query TEXT,
            response TEXT,
            model_used TEXT,
            agent_id TEXT,
            agent_name TEXT,
            agent_type TEXT,
            agent_goal TEXT,
            workflow_description TEXT,
            tool_prompt TEXT,
            steps JSONB,
            executor_messages JSONB,
            evaluation_status TEXT DEFAULT 'unprocessed',
            department_name TEXT DEFAULT 'General'
        );
        """
        
        # ALTER TABLE statements for existing databases
        alter_statements = [
            f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General';"
        ]
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
                # Execute ALTER statements for existing databases
                for stmt in alter_statements:
                    await conn.execute(stmt)
            log.info(f"Table '{self.table_name}' created or updated successfully.")
        except Exception as e:
            log.error(f"Error creating or updating table '{self.table_name}': {e}")
            raise

    async def insert_evaluation_record(self, data: Dict[str, Any]) -> bool:
        """
        Inserts a new evaluation data record.
        """
        insert_query = f"""
        INSERT INTO {self.table_name} (
            session_id, query, response, model_used,
            agent_id, agent_name, agent_type, agent_goal,
            workflow_description, tool_prompt, steps, executor_messages, department_name
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13);
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_query,
                    data.get("session_id"), data.get("query"), data.get("response"), data.get("model_used"),
                    data.get("agent_id"), data.get("agent_name"), data.get("agent_type"), data.get("agent_goal"),
                    data.get("workflow_description"), data.get("tool_prompt"),
                    data.get("steps"),
                    data.get("executor_messages"),
                    data.get("department_name", "General")
                )
            return True
        except Exception as e:
            log.error(f"Error inserting evaluation record: {e}")
            return False

    async def get_unprocessed_record(self) -> Dict[str, Any] | None:
        """
        Retrieves the next unprocessed evaluation record.
        """
        query = f"""
            SELECT
                id, query, response, agent_goal, agent_name,agent_type,
                workflow_description, steps, executor_messages, tool_prompt, model_used,
                session_id, agent_id, department_name
            FROM {self.table_name}
            WHERE evaluation_status = 'unprocessed'
            ORDER BY time_stamp
            LIMIT 1;
        """
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query)
            return dict(row) if row else None
        except Exception as e:
            log.error(f"Error fetching unprocessed evaluation record: {e}")
            return None
  
    async def get_unprocessed_record_by_department(self, department_name: str) -> Dict[str, Any] | None:
        """
        Retrieves the next unprocessed evaluation record for a specific department.
        Used by Admin users to access records in their department.
        """
        query = f"""
            SELECT
                id, query, response, agent_goal, agent_name, agent_type,
                workflow_description, steps, executor_messages, tool_prompt, model_used,
                session_id, agent_id, department_name
            FROM {self.table_name}
            WHERE evaluation_status = 'unprocessed'
            AND department_name = $1
            ORDER BY time_stamp
            LIMIT 1;
        """
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, department_name)
            return dict(row) if row else None
        except Exception as e:
            log.error(f"Error fetching unprocessed record by department {department_name}: {e}")
            return None

    async def count_unprocessed_records_by_department(self, department_name: str) -> int:
        """
        Counts unprocessed evaluation records for a specific department.
        Used by Admin users to count records in their department.
        """
        query = f"""
            SELECT COUNT(*) FROM {self.table_name}
            WHERE evaluation_status = 'unprocessed'
            AND department_name = $1;
        """
        try:
            async with self.pool.acquire() as conn:
                return await conn.fetchval(query, department_name)
        except Exception as e:
            log.error(f"Error counting unprocessed records by department {department_name}: {e}")
            return 0

    async def get_unprocessed_record_by_creator(self, creator_email: str) -> Dict[str, Any] | None:
        """
        Retrieves the next unprocessed evaluation record for agents created by the given user.
        """
        try:
            # Step 1: Get agent IDs from the agent DB
            log.info(f"Calling get_agent_ids_by_creator for: {creator_email}")
            agent_ids_result = await self.agent_repo.get_agent_ids_by_creator(creator_email)
            log.info(f"Received agent IDs: {[row['agentic_application_id'] for row in agent_ids_result]}")

            # agent_ids_result = await self.agent_repo.get_agent_ids_by_creator(creator_email)
            agent_ids = [row["agentic_application_id"] for row in agent_ids_result]

            if not agent_ids:
                log.info(f"No agents found for user {creator_email}")
                return None

            # Step 2: Query evaluation DB for matching unprocessed records
            query = f"""
                SELECT
                    id, query, response, agent_goal, agent_name, agent_type,
                    workflow_description, steps, executor_messages, tool_prompt, model_used,
                    session_id, agent_id, department_name
                FROM {self.table_name}
                WHERE evaluation_status = 'unprocessed'
                AND agent_id = ANY($1::text[])
                ORDER BY time_stamp
                LIMIT 1;
            """
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, agent_ids)

            return dict(row) if row else None

        except Exception as e:
            log.error(f"Error fetching unprocessed record by creator: {e}")
            return None

    async def count_all_unprocessed_records(self) -> int:
        query = f"""
            SELECT COUNT(*) FROM {self.table_name}
            WHERE evaluation_status = 'unprocessed';
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query)
        

    async def count_unprocessed_records_by_agent_ids(self, agent_ids: List[str]) -> int:
        if not agent_ids:
            return 0
        query = f"""
            SELECT COUNT(*) FROM {self.table_name}
            WHERE evaluation_status = 'unprocessed'
            AND agent_id = ANY($1::text[]);
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, agent_ids)

    async def update_status(self, evaluation_id: int, status: str) -> bool:
        """
        Updates the processing status of an evaluation record.
        """
        update_query = f"""
        UPDATE {self.table_name}
        SET evaluation_status = $1
        WHERE id = $2;
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(update_query, status, evaluation_id)
            return result != "UPDATE 0"
        except Exception as e:
            log.error(f"Error updating evaluation status for ID {evaluation_id}: {e}")
            return False

  
    async def get_records_by_agent_names(
        self,
        user: Optional[User],
        agent_names: Optional[List[str]] = None,
        agent_types: Optional[List[str]] = None,
        page: int = 1,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Retrieves evaluation data records, optionally filtered by agent names and types.
        - SuperAdmin can access all records across all departments
        - Admin can access all records in their department
        - Regular users can only access records for agents they created
        """
        try:
            offset = (page - 1) * limit
            query = f"""
                SELECT id, session_id, query, response, model_used, agent_id, agent_name, agent_type, evaluation_status
                FROM {self.table_name}
            """
            params = []
            conditions = []

            # Apply filtering based on user role and permissions
            if user:
                if user.role == UserRole.SUPER_ADMIN:
                    # SuperAdmin can see all records - no additional filtering
                    log.info(f"SuperAdmin {user.email} accessing all evaluation records")
                    if agent_names:
                        conditions.append(f"agent_name = ANY(${len(params)+1}::text[])")
                        params.append(agent_names)
                    if agent_types:
                        conditions.append(f"agent_type = ANY(${len(params)+1}::text[])")
                        params.append(agent_types)
                        
                elif user.role == UserRole.ADMIN:
                    # Admin can see all records in their department
                    log.info(f"Admin {user.email} accessing department records: {user.department_name}")
                    
                    # Add department filter
                    conditions.append(f"department_name = ${len(params)+1}")
                    params.append(user.department_name)
                    
                    if agent_names:
                        conditions.append(f"agent_name = ANY(${len(params)+1}::text[])")
                        params.append(agent_names)
                    if agent_types:
                        conditions.append(f"agent_type = ANY(${len(params)+1}::text[])")
                        params.append(agent_types)
                    
                else:
                    # Regular users can only see records for agents they created and in their department
                    log.info(f"User {user.email} accessing own agent records")
                    
                    # Add department filter for regular users
                    conditions.append(f"department_name = ${len(params)+1}")
                    params.append(user.department_name)
                    
                    agent_names_result = await self.agent_repo.get_agent_names_by_creator_and_department(
                        user.email, user.department_name
                    )
                    owned_agent_names = [row["agentic_application_name"] for row in agent_names_result]

                    if not owned_agent_names:
                        log.warning(f"No agents found for user {user.email} in department {user.department_name}")
                        return []

                    # If agent_names is provided, filter only those that the user owns
                    if agent_names:
                        filtered_agent_names = list(set(agent_names) & set(owned_agent_names))
                        if not filtered_agent_names:
                            log.warning(f"User {user.email} does not own any of the requested agent names: {agent_names}")
                            return []
                        conditions.append(f"agent_name = ANY(${len(params)+1}::text[])")
                        params.append(filtered_agent_names)
                    else:
                        conditions.append(f"agent_name = ANY(${len(params)+1}::text[])")
                        params.append(owned_agent_names)
                    
                    if agent_types:
                        conditions.append(f"agent_type = ANY(${len(params)+1}::text[])")
                        params.append(agent_types)

            # Build WHERE clause from conditions
            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            # Add pagination
            limit_param_index = len(params) + 1
            offset_param_index = len(params) + 2
            query += f" ORDER BY id DESC LIMIT ${limit_param_index} OFFSET ${offset_param_index};"
            params.extend([limit, offset])

            log.debug(f"Executing query: {query} with params: {params}")

            # Execute query
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)

            return [dict(row) for row in rows]

        except Exception as e:
            log.error(f"Error fetching evaluation data records: {e}")
            return []


# --- ToolEvaluationMetricsRepository ---

class ToolEvaluationMetricsRepository(BaseRepository):
    """
    Repository for 'tool_evaluation_metrics' table. Handles direct database interactions.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, agent_repo: AgentRepository, table_name: str = TableNames.TOOL_EVALUATION_METRICS.value):
        super().__init__(pool, login_pool, table_name)
        self.agent_repo = agent_repo


    async def create_table_if_not_exists(self):
        """Creates the 'tool_evaluation_metrics' table if it does not exist."""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id SERIAL PRIMARY KEY,
            evaluation_id INTEGER REFERENCES {TableNames.EVALUATION_DATA.value}(id) ON DELETE CASCADE,
            user_query TEXT,
            agent_response TEXT,
            model_used TEXT,
            tool_selection_accuracy REAL,
            tool_usage_efficiency REAL,
            tool_call_precision REAL,
            tool_call_success_rate REAL,
            tool_utilization_efficiency REAL,
            tool_utilization_efficiency_category TEXT,
            tool_selection_accuracy_justification TEXT,
            tool_usage_efficiency_justification TEXT,
            tool_call_precision_justification TEXT,
            model_used_for_evaluation TEXT,
            department_name TEXT DEFAULT 'General',
            time_stamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # ALTER TABLE statements for existing databases
        alter_statements = [
            f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General';"
        ]
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
                # Execute ALTER statements for existing databases
                for stmt in alter_statements:
                    await conn.execute(stmt)
            log.info(f"Table '{self.table_name}' created or updated successfully.")
        except Exception as e:
            log.error(f"Error creating or updating table '{self.table_name}': {e}")
            raise

    async def insert_metrics_record(self, metrics_data: Dict[str, Any]) -> bool:
        """
        Inserts a new tool evaluation metrics record.
        """
        insert_query = f"""
        INSERT INTO {self.table_name} (
            evaluation_id, user_query, agent_response, model_used,
            tool_selection_accuracy, tool_usage_efficiency, tool_call_precision,
            tool_call_success_rate, tool_utilization_efficiency,
            tool_utilization_efficiency_category,
            tool_selection_accuracy_justification,
            tool_usage_efficiency_justification,
            tool_call_precision_justification,
            model_used_for_evaluation, department_name
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_query,
                    metrics_data.get("evaluation_id"), metrics_data.get("user_query"), metrics_data.get("agent_response"), metrics_data.get("model_used"),
                    metrics_data.get("tool_selection_accuracy"), metrics_data.get("tool_usage_efficiency"), metrics_data.get("tool_call_precision"),
                    metrics_data.get("tool_call_success_rate"), metrics_data.get("tool_utilization_efficiency"),
                    metrics_data.get("tool_utilization_efficiency_category"),
                    metrics_data.get("tool_selection_accuracy_justification"),
                    metrics_data.get("tool_usage_efficiency_justification"),
                    metrics_data.get("tool_call_precision_justification"),
                    metrics_data.get("model_used_for_evaluation"),
                    metrics_data.get("department_name", "General")
                )
            return True
        except Exception as e:
            log.error(f"Error inserting tool evaluation metrics record: {e}")
            return False

    async def get_metrics_by_agent_names(
        self,
        user: Optional[User],
        agent_names: Optional[List[str]] = None,
        agent_types: Optional[List[str]] = None,
        page: int = 1,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Retrieves tool evaluation metrics records, optionally filtered by agent names and types.
        - SuperAdmin can access all records across all departments
        - Admin can access all records in their department
        - Regular users can only access records for agents they created
        """
        try:
            offset = (page - 1) * limit
            query = f"""
                SELECT tem.*
                FROM {self.table_name} tem
                JOIN {TableNames.EVALUATION_DATA.value} ed ON tem.evaluation_id = ed.id
            """
            params = []
            conditions = []

            # Apply filtering based on user role and permissions
            if user:
                if user.role == UserRole.SUPER_ADMIN:
                    # SuperAdmin can see all records - no additional filtering
                    log.info(f"SuperAdmin {user.email} accessing all tool metrics")
                    if agent_names:
                        conditions.append(f"ed.agent_name = ANY(${len(params)+1}::text[])")
                        params.append(agent_names)
                    if agent_types:
                        conditions.append(f"ed.agent_type = ANY(${len(params)+1}::text[])")
                        params.append(agent_types)
                        
                elif user.role == UserRole.ADMIN:
                    # Admin can see all records in their department
                    log.info(f"Admin {user.email} accessing department tool metrics: {user.department_name}")
                    
                    # Add department filter
                    conditions.append(f"ed.department_name = ${len(params)+1}")
                    params.append(user.department_name)
                    
                    if agent_names:
                        conditions.append(f"ed.agent_name = ANY(${len(params)+1}::text[])")
                        params.append(agent_names)
                    if agent_types:
                        conditions.append(f"ed.agent_type = ANY(${len(params)+1}::text[])")
                        params.append(agent_types)
                    
                else:
                    # Regular users can only see records for agents they created and in their department
                    log.info(f"User {user.email} accessing own agent tool metrics")
                    
                    # Add department filter for regular users
                    conditions.append(f"ed.department_name = ${len(params)+1}")
                    params.append(user.department_name)
                    
                    agent_names_result = await self.agent_repo.get_agent_names_by_creator_and_department(
                        user.email, user.department_name
                    )
                    owned_agent_names = [row["agentic_application_name"] for row in agent_names_result]

                    if not owned_agent_names:
                        log.warning(f"No agents found for user {user.email} in department {user.department_name}")
                        return []

                    # If agent_names is provided, filter only those that the user owns
                    if agent_names:
                        filtered_agent_names = list(set(agent_names) & set(owned_agent_names))
                        if not filtered_agent_names:
                            log.warning(f"User {user.email} does not own any of the requested agent names: {agent_names}")
                            return []
                        conditions.append(f"ed.agent_name = ANY(${len(params)+1}::text[])")
                        params.append(filtered_agent_names)
                    else:
                        conditions.append(f"ed.agent_name = ANY(${len(params)+1}::text[])")
                        params.append(owned_agent_names)
                    
                    if agent_types:
                        conditions.append(f"ed.agent_type = ANY(${len(params)+1}::text[])")
                        params.append(agent_types)
            else:
                # No user provided - this shouldn't happen with proper authentication
                log.warning("No user provided for tool metrics access")
                return []

            # Build WHERE clause from conditions
            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            # Add pagination
            limit_param_index = len(params) + 1
            offset_param_index = len(params) + 2
            query += f" ORDER BY tem.id DESC LIMIT ${limit_param_index} OFFSET ${offset_param_index};"
            params.extend([limit, offset])

            log.debug(f"Executing query: {query} with params: {params}")

            # Step 3: Execute query
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)

            return [dict(row) for row in rows]

        except Exception as e:
            log.error(f"Error fetching tool evaluation metrics records: {e}")
            return []


# --- AgentEvaluationMetricsRepository ---

class AgentEvaluationMetricsRepository(BaseRepository):
    """
    Repository for 'agent_evaluation_metrics' table. Handles direct database interactions.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, agent_repo :AgentRepository, table_name: str = TableNames.AGENT_EVALUATION_METRICS.value):
        super().__init__(pool, login_pool, table_name)
        self.agent_repo = agent_repo

    async def create_table_if_not_exists(self):
        """Creates the 'agent_evaluation_metrics' table if it does not exist, and adds missing columns if needed."""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id SERIAL PRIMARY KEY,
            evaluation_id INTEGER REFERENCES {TableNames.EVALUATION_DATA.value}(id) ON DELETE CASCADE,
            user_query TEXT,
            response TEXT,
            model_used TEXT,
            task_decomposition_efficiency REAL,
            task_decomposition_justification TEXT,
            reasoning_relevancy REAL,
            reasoning_relevancy_justification TEXT,
            reasoning_coherence REAL,
            reasoning_coherence_justification TEXT,
            answer_relevance REAL,
            answer_relevance_justification TEXT,
            groundedness REAL,
            groundedness_justification TEXT,
            response_fluency REAL,
            response_fluency_justification TEXT,
            response_coherence REAL,
            response_coherence_justification TEXT,
            communication_efficiency_score REAL,
            communication_efficiency_justification TEXT,
            efficiency_category TEXT,
            model_used_for_evaluation TEXT,
            department_name TEXT DEFAULT 'General',
            time_stamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        alter_statements = [
            f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS communication_efficiency_score REAL DEFAULT NULL;",
            f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS communication_efficiency_justification TEXT DEFAULT 'NaN';",
            f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General';"
        ]

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
                for stmt in alter_statements:
                    await conn.execute(stmt)
            log.info(f"Table '{self.table_name}' created or updated successfully.")
        except Exception as e:
            log.error(f"Error creating or updating table '{self.table_name}': {e}")
            raise


    async def insert_metrics_record(self, metrics_data: Dict[str, Any]) -> bool:
        """
        Inserts a new agent evaluation metrics record into the database.
        """
        insert_query = f"""
        INSERT INTO {self.table_name} (
            evaluation_id, user_query, response, model_used,
            task_decomposition_efficiency, task_decomposition_justification,
            reasoning_relevancy, reasoning_relevancy_justification,
            reasoning_coherence, reasoning_coherence_justification,
            answer_relevance, answer_relevance_justification,
            groundedness, groundedness_justification,
            response_fluency, response_fluency_justification,
            response_coherence, response_coherence_justification,
            communication_efficiency_score, communication_efficiency_justification,
            efficiency_category, model_used_for_evaluation, department_name
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
            $11, $12, $13, $14, $15, $16, $17, $18,
            $19, $20, $21, $22, $23
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_query,
                    metrics_data.get("evaluation_id"), metrics_data.get("user_query"), metrics_data.get("response"), metrics_data.get("model_used"),
                    metrics_data.get("task_decomposition_efficiency"), metrics_data.get("task_decomposition_justification"),
                    metrics_data.get("reasoning_relevancy"), metrics_data.get("reasoning_relevancy_justification"),
                    metrics_data.get("reasoning_coherence"), metrics_data.get("reasoning_coherence_justification"),
                    metrics_data.get("answer_relevance"), metrics_data.get("answer_relevance_justification"),
                    metrics_data.get("groundedness"), metrics_data.get("groundedness_justification"),
                    metrics_data.get("response_fluency"), metrics_data.get("response_fluency_justification"),
                    metrics_data.get("response_coherence"), metrics_data.get("response_coherence_justification"),
                    metrics_data.get("communication_efficiency_score"),metrics_data.get("communication_efficiency_justification"),
                    metrics_data.get("efficiency_category"), metrics_data.get("model_used_for_evaluation"),
                    metrics_data.get("department_name", "General")
                )
            return True
        except Exception as e:
            log.error(f"Error inserting agent evaluation metrics record: {e}", exc_info=True)
            return False

   
    async def get_metrics_by_agent_names(
        self,
        user: Optional[User],
        agent_names: Optional[List[str]] = None,
        agent_types: Optional[List[str]] = None,
        page: int = 1,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Retrieves agent evaluation metrics records, optionally filtered by agent names and types.
        - SuperAdmin can access all records across all departments
        - Admin can access all records in their department
        - Regular users can only access records for agents they created
        """
        try:
            offset = (page - 1) * limit
            query = f"""
                SELECT aem.*
                FROM {self.table_name} aem
                JOIN {TableNames.EVALUATION_DATA.value} ed ON aem.evaluation_id = ed.id
            """
            params = []
            conditions = []

            # Apply filtering based on user role and permissions
            if user:
                if user.role == UserRole.SUPER_ADMIN:
                    # SuperAdmin can see all records - no additional filtering
                    log.info(f"SuperAdmin {user.email} accessing all agent metrics")
                    if agent_names:
                        conditions.append(f"ed.agent_name = ANY(${len(params)+1}::text[])")
                        params.append(agent_names)
                    if agent_types:
                        conditions.append(f"ed.agent_type = ANY(${len(params)+1}::text[])")
                        params.append(agent_types)
                        
                elif user.role == UserRole.ADMIN:
                    # Admin can see all records in their department
                    log.info(f"Admin {user.email} accessing department agent metrics: {user.department_name}")
                    
                    # Add department filter
                    conditions.append(f"ed.department_name = ${len(params)+1}")
                    params.append(user.department_name)
                    
                    if agent_names:
                        conditions.append(f"ed.agent_name = ANY(${len(params)+1}::text[])")
                        params.append(agent_names)
                    if agent_types:
                        conditions.append(f"ed.agent_type = ANY(${len(params)+1}::text[])")
                        params.append(agent_types)
                    
                else:
                    # Regular users can only see records for agents they created and in their department
                    log.info(f"User {user.email} accessing own agent metrics")
                    
                    # Add department filter for regular users
                    conditions.append(f"ed.department_name = ${len(params)+1}")
                    params.append(user.department_name)
                    
                    agent_names_result = await self.agent_repo.get_agent_names_by_creator_and_department(
                        user.email, user.department_name
                    )
                    owned_agent_names = [row["agentic_application_name"] for row in agent_names_result]

                    if not owned_agent_names:
                        log.warning(f"No agents found for user {user.email} in department {user.department_name}")
                        return []

                    # If agent_names is provided, filter only those that the user owns
                    if agent_names:
                        filtered_agent_names = list(set(agent_names) & set(owned_agent_names))
                        if not filtered_agent_names:
                            log.warning(f"User {user.email} does not own any of the requested agent names: {agent_names}")
                            return []
                        conditions.append(f"ed.agent_name = ANY(${len(params)+1}::text[])")
                        params.append(filtered_agent_names)
                    else:
                        conditions.append(f"ed.agent_name = ANY(${len(params)+1}::text[])")
                        params.append(owned_agent_names)
                    
                    if agent_types:
                        conditions.append(f"ed.agent_type = ANY(${len(params)+1}::text[])")
                        params.append(agent_types)
            else:
                # No user provided - this shouldn't happen with proper authentication
                log.warning("No user provided for agent metrics access")
                return []

            # Build WHERE clause from conditions
            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            # Add pagination
            limit_param_index = len(params) + 1
            offset_param_index = len(params) + 2
            query += f" ORDER BY aem.id DESC LIMIT ${limit_param_index} OFFSET ${offset_param_index};"
            params.extend([limit, offset])

            log.debug(f"Executing query: {query} with params: {params}")

            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)

            return [dict(row) for row in rows]

        except Exception as e:
            log.error(f"Error fetching agent evaluation metrics records: {e}")
            return []

