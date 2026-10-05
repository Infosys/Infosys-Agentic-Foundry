# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import asyncio
import asyncpg

from typing import List, Dict, Callable, TypeVar
from src.config.constants import TableNames

from telemetry_wrapper import logger as log


# Type variable for generic return types
T = TypeVar('T')

# Database operation configuration
DB_TIMEOUT_SECONDS = float(os.getenv('DB_TIMEOUT_SECONDS', '30'))  # Default 30 seconds timeout
DB_MAX_RETRIES = int(os.getenv('DB_MAX_RETRIES', '3'))  # Default 3 retries
DB_RETRY_DELAY_SECONDS = float(os.getenv('DB_RETRY_DELAY_SECONDS', '10'))  # Default 10 seconds delay between retries


class BaseRepository:
    """
    Base class for all repositories.
    Provides the database connection pool to subclasses.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str):
        """
        Initializes the BaseRepository with a database connection pool.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
        """
        if not pool:
            raise ValueError("Connection pool is not provided.")
        if not login_pool:
            raise ValueError("Login connection pool is not provided.")
        self.pool = pool
        self.login_pool = login_pool
        self.table_name = table_name

    async def _execute_with_retry(
        self,
        operation: Callable,
        *args,
        timeout: float = DB_TIMEOUT_SECONDS,
        max_retries: int = DB_MAX_RETRIES,
        retry_delay: float = DB_RETRY_DELAY_SECONDS,
        operation_name: str = "database operation",
        **kwargs
    ) -> T:
        """
        Execute a database operation with timeout and retry mechanism.
        
        Args:
            operation: The async callable to execute (e.g., conn.fetch, conn.execute)
            *args: Positional arguments to pass to the operation
            timeout: Timeout in seconds for each attempt (default: DB_TIMEOUT_SECONDS)
            max_retries: Maximum number of retry attempts (default: DB_MAX_RETRIES)
            retry_delay: Delay in seconds between retries (default: DB_RETRY_DELAY_SECONDS)
            operation_name: Name of the operation for logging purposes
            **kwargs: Keyword arguments to pass to the operation
            
        Returns:
            The result of the database operation
            
        Raises:
            asyncio.TimeoutError: If all retry attempts fail due to timeout
            Exception: If all retry attempts fail due to other errors
        """
        last_exception = None
        
        for attempt in range(1, max_retries + 1):
            try:
                result = await asyncio.wait_for(
                    operation(*args, **kwargs),
                    timeout=timeout
                )
                return result
            except asyncio.TimeoutError as e:
                last_exception = e
                log.warning(
                    f"[DB Timeout] {operation_name} timed out after {timeout}s "
                    f"(attempt {attempt}/{max_retries})"
                )
            except (asyncpg.PostgresConnectionError, asyncpg.InterfaceError, ConnectionError) as e:
                last_exception = e
                log.warning(
                    f"[DB Connection Error] {operation_name} failed with connection error: {str(e)} "
                    f"(attempt {attempt}/{max_retries})"
                )
            except Exception as e:
                # For non-retryable errors, raise immediately
                if not isinstance(e, (asyncpg.PostgresError,)):
                    raise
                last_exception = e
                log.warning(
                    f"[DB Error] {operation_name} failed: {str(e)} "
                    f"(attempt {attempt}/{max_retries})"
                )
            
            # Wait before retrying (but not after the last attempt)
            if attempt < max_retries:
                log.info(f"[DB Retry] Waiting {retry_delay}s before retry...")
                await asyncio.sleep(retry_delay)
        
        # All retries exhausted
        log.error(
            f"[DB Failed] {operation_name} failed after {max_retries} attempts. "
            f"Last error: {str(last_exception)}"
        )
        raise last_exception

    # Convenience wrapper methods for database operations with retry
    async def _fetch(self, conn, query: str, *args, operation_name: str = "fetch", **kwargs):
        """Execute conn.fetch with retry mechanism."""
        return await self._execute_with_retry(conn.fetch, query, *args, operation_name=operation_name, **kwargs)
    
    async def _fetchrow(self, conn, query: str, *args, operation_name: str = "fetchrow", **kwargs):
        """Execute conn.fetchrow with retry mechanism."""
        return await self._execute_with_retry(conn.fetchrow, query, *args, operation_name=operation_name, **kwargs)
    
    async def _fetchval(self, conn, query: str, *args, operation_name: str = "fetchval", **kwargs):
        """Execute conn.fetchval with retry mechanism."""
        return await self._execute_with_retry(conn.fetchval, query, *args, operation_name=operation_name, **kwargs)
    
    async def _db_execute(self, conn, query: str, *args, operation_name: str = "execute", **kwargs):
        """Execute conn.execute with retry mechanism."""
        return await self._execute_with_retry(conn.execute, query, *args, operation_name=operation_name, **kwargs)

    async def _transform_emails_to_usernames(self, rows: List[Dict], email_fields: List[str]) -> List[Dict]:
        """
        Batch-transforms email addresses to usernames for specified fields.
        
        Args:
            rows: List of row dictionaries to transform
            email_fields: List of field names containing email addresses to transform
            
        Returns:
            List of transformed row dictionaries with emails replaced by usernames
        """
        if not rows:
            return rows
            
        # Collect unique emails from all specified fields
        emails = set()
        for row in rows:
            for field in email_fields:
                if row.get(field):
                    emails.add(row[field])
        
        # Fetch all usernames in one query
        email_to_username = {}
        if emails:
            async with self.login_pool.acquire() as conn:
                user_records = await self._execute_with_retry(
                    conn.fetch,
                    f"SELECT mail_id, user_name FROM {TableNames.LOGIN_CREDENTIAL.value} WHERE mail_id = ANY($1)",
                    list(emails),
                    operation_name="transform_emails_to_usernames"
                )
                email_to_username = {r['mail_id']: r['user_name'] for r in user_records}
        
        # Transform rows
        for row in rows:
            for field in email_fields:
                if row.get(field):
                    username = email_to_username.get(row[field])
                    if username:
                        row[field] = username
                    elif '@' in row[field]:
                        row[field] = row[field].split('@')[0]
        return rows

