import asyncpg
import hashlib
from typing import List, Dict, Any, Optional
from src.auth.models import UserRole
from telemetry_wrapper import logger as log

class UserRepository:
    """Repository for user-related database operations using login_credential table"""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.table_name = "login_credential"

    async def create_table_if_not_exists(self):
        """Create login_credential table if it doesn't exist"""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            mail_id TEXT PRIMARY KEY,
            user_name TEXT NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user'
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
            log.info(f"Table '{self.table_name}' created or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            raise

    async def create_user(self, email: str, username: str, password: str, role: str) -> Optional[str]:
        """Create a new user and return mail_id"""
        insert_query = f"""
        INSERT INTO {self.table_name} (mail_id, user_name, password, role)
        VALUES ($1, $2, $3, $4)
        RETURNING mail_id
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchrow(insert_query, email, username, password, role)
                return result['mail_id'] if result else None
        except asyncpg.UniqueViolationError:
            log.warning(f"User with email {email} already exists")
            return None
        except Exception as e:
            log.error(f"Error creating user: {e}")
            raise

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by mail_id"""
        query = f"SELECT * FROM {self.table_name} WHERE mail_id = $1"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchrow(query, email)
                return dict(result) if result else None
        except Exception as e:
            log.error(f"Error fetching user by email: {e}")
            raise

    async def update_user_password(self, email: str, new_password: str) -> bool:
        """Update user PWD"""
        query = f"UPDATE {self.table_name} SET password = $1 WHERE mail_id = $2"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, new_password, email)
                return result != "UPDATE 0"
        except Exception as e:
            log.error(f"Error updating user password: {e}")
            return False

    async def update_user_role(self, email: str, new_role: str) -> bool:
        """Update user role"""
        query = f"UPDATE {self.table_name} SET role = $1 WHERE mail_id = $2"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, new_role, email)
                return result != "UPDATE 0"
        except Exception as e:
            log.error(f"Error updating user role: {e}")
            return False

    async def get_all_users(self) -> List[Dict[str, Any]]:
        """Get all users"""
        query = f"SELECT * FROM {self.table_name}"
        try:
            async with self.pool.acquire() as conn:
                results = await conn.fetch(query)
                return [dict(row) for row in results]
        except Exception as e:
            log.error(f"Error fetching all users: {e}")
            raise


class ApprovalPermissionRepository:
    """Repository for approval permission management"""
    
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.table_name = "approval_permissions"
    
    async def create_table_if_not_exists(self):
        """Create approval permissions table if it doesn't exist"""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            admin_user_mail_id TEXT REFERENCES login_credential(mail_id) ON DELETE CASCADE,
            granted_by_mail_id TEXT REFERENCES login_credential(mail_id) ON DELETE CASCADE,
            permission_type VARCHAR(50) NOT NULL,
            granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE,
            UNIQUE(admin_user_mail_id, permission_type)
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
            log.info(f"Table '{self.table_name}' created or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            raise
    
    async def grant_approval_permission(self, admin_user_mail_id: str, granted_by_mail_id: str, permission_type: str) -> Optional[str]:
        """Grant approval permission to an admin"""
        insert_query = f"""
        INSERT INTO {self.table_name} (admin_user_mail_id, granted_by_mail_id, permission_type)
        VALUES ($1, $2, $3)
        ON CONFLICT (admin_user_mail_id, permission_type) 
        DO UPDATE SET 
            granted_by_mail_id = EXCLUDED.granted_by_mail_id,
            granted_at = CURRENT_TIMESTAMP,
            is_active = TRUE
        RETURNING id
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchrow(insert_query, admin_user_mail_id, granted_by_mail_id, permission_type)
                return str(result['id']) if result else None
        except Exception as e:
            log.error(f"Error granting approval permission: {e}")
            raise
    
    async def revoke_approval_permission(self, admin_user_mail_id: str, permission_type: str) -> bool:
        """Revoke approval permission from an admin"""
        query = f"UPDATE {self.table_name} SET is_active = FALSE WHERE admin_user_mail_id = $1 AND permission_type = $2"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, admin_user_mail_id, permission_type)
                return result != "UPDATE 0"
        except Exception as e:
            log.error(f"Error revoking approval permission: {e}")
            return False
    
    async def has_approval_permission(self, admin_user_mail_id: str, permission_type: str) -> bool:
        """Check if admin has approval permission"""
        query = f"SELECT COUNT(*) FROM {self.table_name} WHERE admin_user_mail_id = $1 AND permission_type = $2 AND is_active = TRUE"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval(query, admin_user_mail_id, permission_type)
                return result > 0
        except Exception as e:
            log.error(f"Error checking approval permission: {e}")
            return False
    
    async def get_admin_approval_permissions(self, admin_user_mail_id: str) -> List[Dict[str, Any]]:
        """Get all approval permissions for an admin"""
        query = f"SELECT * FROM {self.table_name} WHERE admin_user_mail_id = $1 AND is_active = TRUE"
        try:
            async with self.pool.acquire() as conn:
                results = await conn.fetch(query, admin_user_mail_id)
                return [dict(row) for row in results]
        except Exception as e:
            log.error(f"Error fetching admin approval permissions: {e}")
            raise
    
    async def get_all_approval_permissions(self) -> List[Dict[str, Any]]:
        """Get all approval permissions"""
        query = f"""
        SELECT ap.*, u.user_name as admin_username, u.mail_id as admin_mail_id,
               gb.user_name as granted_by_username, gb.mail_id as granted_by_mail_id
        FROM {self.table_name} ap
        JOIN login_credential u ON ap.admin_user_mail_id = u.mail_id
        JOIN login_credential gb ON ap.granted_by_mail_id = gb.mail_id
        WHERE ap.is_active = TRUE
        ORDER BY ap.granted_at DESC
        """
        try:
            async with self.pool.acquire() as conn:
                results = await conn.fetch(query)
                return [dict(row) for row in results]
        except Exception as e:
            log.error(f"Error fetching all approval permissions: {e}")
            raise


class AuditLogRepository:
    """Repository for audit log management"""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.table_name = "audit_logs_iaf"

    async def create_table_if_not_exists(self):
        """Create audit logs table if it doesn't exist. user_id refers to mail_id from login_credential."""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id TEXT PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id TEXT REFERENCES login_credential(mail_id) ON DELETE SET NULL,
            action VARCHAR(100) NOT NULL,
            resource_type VARCHAR(50) NOT NULL,
            resource_id VARCHAR(255),
            old_value TEXT,
            new_value TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ip_address INET,
            user_agent TEXT
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
            log.info(f"Table '{self.table_name}' created or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            raise

    async def log_action(self, user_id: str, action: str, resource_type: str, 
                        resource_id: str = None, old_value: str = None, new_value: str = None,
                        ip_address: str = None, user_agent: str = None) -> Optional[str]:
        """Log an action"""
        insert_query = f"""
        INSERT INTO {self.table_name} (user_id, action, resource_type, resource_id, old_value, new_value, ip_address, user_agent)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchrow(insert_query, user_id, action, resource_type, resource_id, old_value, new_value, ip_address, user_agent)
                return str(result['id']) if result else None
        except Exception as e:
            log.error(f"Error logging action: {e}")
            raise

    async def get_audit_logs(self, limit: int = 100, offset: int = 0, 
                           user_id: str = None, resource_type: str = None) -> List[Dict[str, Any]]:
        """Get audit logs with optional filtering"""
        query = f"""
        SELECT * FROM {self.table_name}
        WHERE 1=1
        """
        params = []
        param_count = 0

        if user_id:
            param_count += 1
            query += f" AND user_id = ${param_count}"
            params.append(user_id)

        if resource_type:
            param_count += 1
            query += f" AND resource_type = ${param_count}"
            params.append(resource_type)

        query += " ORDER BY timestamp DESC"

        if limit:
            param_count += 1
            query += f" LIMIT ${param_count}"
            params.append(limit)

        if offset:
            param_count += 1
            query += f" OFFSET ${param_count}"
            params.append(offset)

        try:
            async with self.pool.acquire() as conn:
                results = await conn.fetch(query, *params)
                return [dict(row) for row in results]
        except Exception as e:
            log.error(f"Error fetching audit logs: {e}")
            raise


class RefreshTokenRepository:
    """Repository for managing refresh tokens (stateful)"""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.table_name = "refresh_tokens"
        self._columns = None  # cache of existing columns

    async def _load_columns(self, conn=None):
        if self._columns is not None:
            return self._columns
        close_conn = False
        if conn is None:
            conn = await self.pool.acquire()
            close_conn = True
        try:
            rows = await conn.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_name = $1", self.table_name
            )
            self._columns = {r['column_name'] for r in rows}
            return self._columns
        finally:
            if close_conn:
                await self.pool.release(conn)

    async def create_table_if_not_exists(self):
        """Create refresh token table; does not modify existing auth tables."""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_mail_id TEXT NOT NULL REFERENCES login_credential(mail_id) ON DELETE CASCADE,
            refresh_token TEXT NOT NULL UNIQUE,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            revoked_at TIMESTAMP,
            user_agent TEXT,
            ip_address INET
        );
        CREATE INDEX IF NOT EXISTS idx_{self.table_name}_user_mail_id ON {self.table_name}(user_mail_id);
        CREATE INDEX IF NOT EXISTS idx_{self.table_name}_expires_at ON {self.table_name}(expires_at);
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
                # Defensive migration: ensure all expected columns exist (for earlier partial versions)
                expected_columns = {
                    'user_mail_id': "TEXT NOT NULL REFERENCES login_credential(mail_id) ON DELETE CASCADE",
                    'refresh_token': "TEXT UNIQUE",
                    'expires_at': "TIMESTAMP NOT NULL",
                    'created_at': "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                    'revoked_at': "TIMESTAMP",
                    'user_agent': "TEXT",
                    'ip_address': "INET"
                }
                # Fetch existing columns
                existing_cols_rows = await conn.fetch(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = $1", self.table_name
                )
                existing_cols = {r['column_name'] for r in existing_cols_rows}
                for col, ddl in expected_columns.items():
                    if col not in existing_cols:
                        try:
                            await conn.execute(f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS {col} {ddl}")
                            log.info(f"Added missing column '{col}' to {self.table_name}")
                        except Exception as mig_e:
                            log.error(f"Failed adding column {col} to {self.table_name}: {mig_e}")
                # Ensure unique index on refresh_token (if not already via constraint)
                await conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{self.table_name}_refresh_token ON {self.table_name}(refresh_token)")
            log.info(f"Table '{self.table_name}' created or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            raise

    async def store_token(self, user_mail_id: str, refresh_token: str, expires_at, user_agent: str = None, ip_address: str = None):
        async with self.pool.acquire() as conn:
            cols = await self._load_columns(conn)
            token_hash = hashlib.sha256(refresh_token.encode('utf-8')).hexdigest()
            # Determine insert strategy based on existing columns
            if 'token_hash' in cols and 'refresh_token' in cols:
                query = f"""
                INSERT INTO {self.table_name} (user_mail_id, refresh_token, token_hash, expires_at, user_agent, ip_address)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """
                row = await conn.fetchrow(query, user_mail_id, refresh_token, token_hash, expires_at, user_agent, ip_address)
            elif 'token_hash' in cols:  # hashed only storage
                query = f"""
                INSERT INTO {self.table_name} (user_mail_id, token_hash, expires_at, user_agent, ip_address)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """
                row = await conn.fetchrow(query, user_mail_id, token_hash, expires_at, user_agent, ip_address)
            else:  # legacy plain token storage
                query = f"""
                INSERT INTO {self.table_name} (user_mail_id, refresh_token, expires_at, user_agent, ip_address)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """
                row = await conn.fetchrow(query, user_mail_id, refresh_token, expires_at, user_agent, ip_address)
            return str(row['id']) if row else None

    async def get_token(self, refresh_token: str):
        async with self.pool.acquire() as conn:
            cols = await self._load_columns(conn)
            if 'token_hash' in cols:  # prefer hashed lookup
                token_hash = hashlib.sha256(refresh_token.encode('utf-8')).hexdigest()
                query = f"SELECT * FROM {self.table_name} WHERE token_hash = $1"
                row = await conn.fetchrow(query, token_hash)
            else:
                query = f"SELECT * FROM {self.table_name} WHERE refresh_token = $1"
                row = await conn.fetchrow(query, refresh_token)
            return dict(row) if row else None

    async def revoke_token(self, refresh_token: str):
        async with self.pool.acquire() as conn:
            cols = await self._load_columns(conn)
            if 'token_hash' in cols:
                token_hash = hashlib.sha256(refresh_token.encode('utf-8')).hexdigest()
                query = f"UPDATE {self.table_name} SET revoked_at = CURRENT_TIMESTAMP WHERE token_hash = $1 AND revoked_at IS NULL"
                result = await conn.execute(query, token_hash)
            else:
                query = f"UPDATE {self.table_name} SET revoked_at = CURRENT_TIMESTAMP WHERE refresh_token = $1 AND revoked_at IS NULL"
                result = await conn.execute(query, refresh_token)
            return result != "UPDATE 0"

    async def revoke_all_tokens_for_user(self, user_mail_id: str):
        query = f"UPDATE {self.table_name} SET revoked_at = CURRENT_TIMESTAMP WHERE user_mail_id = $1 AND revoked_at IS NULL"
        async with self.pool.acquire() as conn:
            await conn.execute(query, user_mail_id)

    async def delete_expired(self):
        query = f"DELETE FROM {self.table_name} WHERE expires_at < CURRENT_TIMESTAMP OR revoked_at IS NOT NULL"
        async with self.pool.acquire() as conn:
            await conn.execute(query)
