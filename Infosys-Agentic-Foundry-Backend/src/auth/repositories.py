import asyncpg
import hashlib
import json
from typing import List, Dict, Any, Optional
from src.config.constants import TableNames
from src.auth.models import UserRole
from telemetry_wrapper import logger as log

class UserRepository:
    """Repository for user-related database operations using login_credential table"""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.table_name = TableNames.LOGIN_CREDENTIAL.value

    async def create_table_if_not_exists(self):
        """Create login_credential table if it doesn't exist"""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            mail_id TEXT PRIMARY KEY,
            user_name TEXT NOT NULL,
            password TEXT NOT NULL,
            is_active BOOLEAN DEFAULT TRUE
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
                
                # Add is_active column if it doesn't exist (for existing databases)
                try:
                    await conn.execute(f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
                    log.info("Added is_active column to login_credential table")
                except Exception as e:
                    log.debug(f"Column is_active may already exist: {e}")
                
                # Add must_change_password column for temporary PWD flow
                try:
                    await conn.execute(f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN DEFAULT FALSE")
                    log.info("Added must_change_password column to login_credential table")
                except Exception as e:
                    log.debug(f"Column must_change_password may already exist: {e}")
                
                # NOTE: Do NOT drop 'role' or 'department_name' columns here.
                # They are needed by UserDepartmentMappingRepository._migrate_existing_users()
                # which runs AFTER this method. The columns are dropped there after migration.
                
                try:
                    await conn.execute(f"ALTER TABLE {self.table_name} DROP CONSTRAINT IF EXISTS fk_login_credential_department")
                    log.info("Removed foreign key constraint for department_name")
                except Exception as e:
                    log.debug(f"Foreign key constraint may not exist or already removed: {e}")
                    
            log.info(f"Table '{self.table_name}' created or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            raise

    async def create_user(self, email: str, username: str, password: str) -> Optional[str]:
        """Create a new user and return mail_id. Use UserDepartmentMappingRepository to assign department and role."""
        insert_query = f"""
        INSERT INTO {self.table_name} (mail_id, user_name, password)
        VALUES ($1, $2, $3)
        RETURNING mail_id
        """
        query_params = (email, username, password)
            
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchrow(insert_query, *query_params)
                return result['mail_id'] if result else None
        except asyncpg.UniqueViolationError:
            log.warning(f"User with email {email} already exists")
            return None
        except Exception as e:
            log.error(f"Error creating user: {e}")
            raise

    async def get_user_by_email(self, email: str, department_name: str = None) -> Optional[Dict[str, Any]]:
        """Get user by mail_id with role and department information
        
        Args:
            email: User's email address
            department_name: Specific department to get role for. If None, looks for SuperAdmin with NULL department.
        """
        if department_name is None:
            # When no department specified, look for SuperAdmin with NULL department
            query = """
            SELECT 
                lc.mail_id,
                lc.user_name,
                lc.password,
                lc.is_active,
                udm.role,
                udm.department_name
            FROM login_credential lc
            LEFT JOIN userdepartmentmapping udm ON lc.mail_id = udm.mail_id
            WHERE lc.mail_id = $1 AND udm.department_name IS NULL AND udm.role = 'SuperAdmin'
            LIMIT 1
            """
            params = [email]
        else:
            # Get user's role in specific department
            # Also check for SuperAdmin with NULL department (they can access any department)
            query = """
            SELECT 
                lc.mail_id,
                lc.user_name,
                lc.password,
                lc.is_active,
                udm.role,
                udm.department_name
            FROM login_credential lc
            LEFT JOIN userdepartmentmapping udm ON lc.mail_id = udm.mail_id
            WHERE lc.mail_id = $1 AND (
                udm.department_name = $2 OR 
                (udm.department_name IS NULL AND udm.role = 'SuperAdmin')
            )
            ORDER BY CASE WHEN udm.department_name = $2 THEN 0 ELSE 1 END
            LIMIT 1
            """
            params = [email, department_name]
            
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchrow(query, *params)
                if result:
                    user_dict = dict(result)
                    # If no role/department found, set defaults for new users
                    if user_dict['role'] is None:
                        user_dict['role'] = None  # Default role for users without assignments
                        user_dict['department_name'] = department_name
                    return user_dict
                elif department_name is not None:
                    # If specific department requested but user not found in that department,
                    # check if user exists at all (might not have access to this department)
                    basic_user = await self.get_user_basic_by_email(email)
                    if basic_user:
                        # User exists but not in this department - return None for role
                        # to indicate they don't have access to this department
                        return {
                            'mail_id': basic_user['mail_id'],
                            'user_name': basic_user['user_name'],
                            'password': basic_user['password'],
                            'is_active': basic_user.get('is_active', True),
                            'role': None,  # No role in requested department
                            'department_name': department_name
                        }
                return None
        except Exception as e:
            log.error(f"Error fetching user by email with department {department_name}: {e}")
            raise

    async def get_user_basic_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get basic user info by mail_id (without role/department)"""
        query = f"SELECT * FROM {self.table_name} WHERE mail_id = $1"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchrow(query, email)
                return dict(result) if result else None
        except Exception as e:
            log.error(f"Error fetching basic user by email: {e}")
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

    async def set_temporary_password(self, email: str, new_password: str) -> bool:
        """Set a temporary PWD for a user (sets must_change_password = True)"""
        query = f"UPDATE {self.table_name} SET password = $1, must_change_password = TRUE WHERE mail_id = $2"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, new_password, email)
                return result != "UPDATE 0"
        except Exception as e:
            log.error(f"Error setting temporary password: {e}")
            return False

    async def update_user_password_and_clear_flag(self, email: str, new_password: str) -> bool:
        """Update user PWD and clear must_change_password flag"""
        query = f"UPDATE {self.table_name} SET password = $1, must_change_password = FALSE WHERE mail_id = $2"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, new_password, email)
                return result != "UPDATE 0"
        except Exception as e:
            log.error(f"Error updating user password: {e}")
            return False

    async def get_must_change_password_status(self, email: str) -> Optional[bool]:
        """Check if user must change PWD on next login"""
        query = f"SELECT must_change_password FROM {self.table_name} WHERE mail_id = $1"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval(query, email)
                return result
        except Exception as e:
            log.error(f"Error checking must_change_password status: {e}")
            return None

    # Note: Role management methods removed - use UserDepartmentMappingRepository for role management
    # Note: Department management methods removed - use UserDepartmentMappingRepository for department management

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

    async def enable_user(self, email: str) -> bool:
        """Enable user login access"""
        query = f"UPDATE {self.table_name} SET is_active = TRUE WHERE mail_id = $1"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, email)
                if result != "UPDATE 0":
                    log.info(f"User {email} has been enabled")
                    return True
                log.warning(f"User {email} not found for enabling")
                return False
        except Exception as e:
            log.error(f"Error enabling user {email}: {e}")
            return False

    async def disable_user(self, email: str) -> bool:
        """Disable user login access"""
        query = f"UPDATE {self.table_name} SET is_active = FALSE WHERE mail_id = $1"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, email)
                if result != "UPDATE 0":
                    log.info(f"User {email} has been disabled")
                    return True
                log.warning(f"User {email} not found for disabling")
                return False
        except Exception as e:
            log.error(f"Error disabling user {email}: {e}")
            return False

    async def is_user_active(self, email: str) -> Optional[bool]:
        """Check if user is active. Returns None if user not found."""
        query = f"SELECT is_active FROM {self.table_name} WHERE mail_id = $1"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval(query, email)
                return result  # Returns True, False, or None if not found
        except Exception as e:
            log.error(f"Error checking if user {email} is active: {e}")
            return None

    async def set_user_active_status(self, email: str, is_active: bool) -> bool:
        """Set user active status (enable or disable)"""
        query = f"UPDATE {self.table_name} SET is_active = $1 WHERE mail_id = $2"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, is_active, email)
                if result != "UPDATE 0":
                    status = "enabled" if is_active else "disabled"
                    log.info(f"User {email} has been {status}")
                    return True
                log.warning(f"User {email} not found for status update")
                return False
        except Exception as e:
            log.error(f"Error setting user {email} active status: {e}")
            return False

    async def validate_department_exists(self, department_name: str) -> bool:
        """Validate if department exists in departments table"""
        if not department_name:
            return True  # Allow None/empty department
            
        query = "SELECT COUNT(*) FROM departments WHERE department_name = $1"
        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval(query, department_name)
                return count > 0
        except Exception as e:
            log.error(f"Error validating department existence: {e}")
            return False

    async def has_any_users(self) -> bool:
        """Check if there are any users in the login_credential table"""
        query = f"SELECT COUNT(*) FROM {self.table_name}"
        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval(query)
                return count > 0
        except Exception as e:
            log.error(f"Error checking if users exist: {e}")
            return True  # Return True to be safe and not accidentally grant SuperAdmin


class UserDepartmentMappingRepository:
    """Repository for user-department mapping operations"""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.table_name = "userdepartmentmapping"

    async def create_table_if_not_exists(self):
        """Create userdepartmentmapping table if it doesn't exist"""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id SERIAL PRIMARY KEY,
            mail_id TEXT NOT NULL,
            department_name VARCHAR(50),
            role VARCHAR(50) NOT NULL DEFAULT 'User',
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT,
            FOREIGN KEY (mail_id) REFERENCES login_credential(mail_id) ON DELETE CASCADE,
            FOREIGN KEY (department_name) REFERENCES departments(department_name) ON DELETE CASCADE,
            UNIQUE(mail_id, department_name)
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
                
                # Add role column if it doesn't exist (for existing databases)
                try:
                    await conn.execute(f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'User'")
                    log.info("Added role column to userdepartmentmapping table")
                except Exception as e:
                    log.debug(f"Role column may already exist: {e}")
                
                # Add is_active column if it doesn't exist (for existing databases)
                try:
                    await conn.execute(f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
                    log.info("Added is_active column to userdepartmentmapping table")
                except Exception as e:
                    log.debug(f"is_active column may already exist: {e}")
                
                # Allow NULL values for department_name to support SuperAdmin
                try:
                    await conn.execute(f"ALTER TABLE {self.table_name} ALTER COLUMN department_name DROP NOT NULL")
                    log.info("Modified department_name column to allow NULL values for SuperAdmin")
                except Exception as e:
                    log.debug(f"Department_name column already allows NULL or error: {e}")
                
                # MIGRATION: Migrate existing users from login_credential to userdepartmentmapping
                await self._migrate_existing_users(conn)
                
                log.info(f"Table {self.table_name} created successfully or already exists")
        except Exception as e:
            log.error(f"Error creating {self.table_name} table: {e}")

    async def _migrate_existing_users(self, conn):
        """
        Migrate existing users from login_credential table to userdepartmentmapping.
        This handles the case where login_credential had role column before migration.
        Users are assigned to 'General' department with their existing role (or 'User' as default).
        """
        try:
            # Check if login_credential has role column (old schema)
            check_role_column = """
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'login_credential' AND column_name = 'role'
            """
            role_column_exists = await conn.fetchval(check_role_column)
            
            if role_column_exists:
                log.info("Found 'role' column in login_credential - starting user migration to userdepartmentmapping")
                
                # Ensure 'General' department exists with default roles
                import json
                default_roles = ["Admin", "Developer", "User"]
                ensure_general_dept = """
                INSERT INTO departments (department_name, created_by, roles)
                VALUES ('General', 'SYSTEM_MIGRATION', $1::jsonb)
                ON CONFLICT (department_name) DO UPDATE SET 
                    roles = COALESCE(departments.roles, '[]'::jsonb) || 
                            (SELECT jsonb_agg(r) FROM jsonb_array_elements_text($1::jsonb) r 
                             WHERE r::text NOT IN (SELECT jsonb_array_elements_text(COALESCE(departments.roles, '[]'::jsonb))))
                """
                await conn.execute(ensure_general_dept, json.dumps(default_roles))
                log.info("Ensured 'General' department exists with default roles")
                
                # Migrate users with their existing roles to General department
                # Handle both cases: users with role and users without role
                migrate_query = f"""
                INSERT INTO {self.table_name} (mail_id, department_name, role, created_by)
                SELECT 
                    lc.mail_id,
                    'General',
                    COALESCE(lc.role, 'User'),
                    'SYSTEM_MIGRATION'
                FROM login_credential lc
                WHERE NOT EXISTS (
                    SELECT 1 FROM {self.table_name} udm 
                    WHERE udm.mail_id = lc.mail_id
                )
                """
                result = await conn.execute(migrate_query)
                
                # Parse number of migrated users
                if result:
                    parts = result.split()
                    if len(parts) >= 2:
                        migrated_count = int(parts[1]) if parts[1].isdigit() else 0
                        log.info(f"Migrated {migrated_count} users to userdepartmentmapping with 'General' department")
                
                # Handle SuperAdmin users - they should have NULL department
                superadmin_update = f"""
                UPDATE {self.table_name}
                SET department_name = NULL
                WHERE role = 'SuperAdmin' AND department_name = 'General'
                """
                await conn.execute(superadmin_update)
                log.info("Updated SuperAdmin users to have NULL department for system-wide access")
                
                # Now safe to drop old columns from login_credential since data has been migrated
                try:
                    await conn.execute("ALTER TABLE login_credential DROP COLUMN IF EXISTS role")
                    log.info("Dropped 'role' column from login_credential after migration")
                except Exception as e:
                    log.debug(f"Could not drop role column: {e}")
                try:
                    await conn.execute("ALTER TABLE login_credential DROP COLUMN IF EXISTS department_name")
                    log.info("Dropped 'department_name' column from login_credential after migration")
                except Exception as e:
                    log.debug(f"Could not drop department_name column: {e}")
                
            else:
                # Check if there are users in login_credential without mappings
                orphan_check = f"""
                SELECT COUNT(*) FROM login_credential lc
                WHERE NOT EXISTS (
                    SELECT 1 FROM {self.table_name} udm WHERE udm.mail_id = lc.mail_id
                )
                """
                orphan_count = await conn.fetchval(orphan_check)
                
                if orphan_count and orphan_count > 0:
                    log.info(f"Found {orphan_count} users without department mapping - migrating to 'General' department")
                    
                    # Ensure 'General' department exists with default roles
                    import json
                    default_roles = ["Admin", "Developer", "User"]
                    ensure_general_dept = """
                    INSERT INTO departments (department_name, created_by, roles)
                    VALUES ('General', 'SYSTEM_MIGRATION', $1::jsonb)
                    ON CONFLICT (department_name) DO NOTHING
                    """
                    await conn.execute(ensure_general_dept, json.dumps(default_roles))
                    
                    # Migrate orphan users to General department with 'User' role
                    migrate_orphans = f"""
                    INSERT INTO {self.table_name} (mail_id, department_name, role, created_by)
                    SELECT 
                        lc.mail_id,
                        'General',
                        'User',
                        'SYSTEM_MIGRATION'
                    FROM login_credential lc
                    WHERE NOT EXISTS (
                        SELECT 1 FROM {self.table_name} udm WHERE udm.mail_id = lc.mail_id
                    )
                    """
                    await conn.execute(migrate_orphans)
                    log.info(f"Migrated {orphan_count} orphan users to 'General' department with 'User' role")
                    
        except Exception as e:
            log.error(f"Error during user migration: {e}")
            # Don't raise - migration failure shouldn't block table creation

    async def add_user_to_department(self, mail_id: str, department_name: str, role: str, created_by: str = None) -> bool:
        """Add a user to a department with a specific role"""
        query = f"""
        INSERT INTO {self.table_name} (mail_id, department_name, role, created_by)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (mail_id, department_name) DO NOTHING
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, mail_id, department_name, role, created_by)
                # Check if row was actually inserted (not skipped due to conflict)
                return "INSERT 0 1" in result
        except Exception as e:
            log.error(f"Error adding user {mail_id} to department {department_name} with role {role}: {e}")
            return False

    async def add_superadmin(self, mail_id: str, created_by: str = None) -> bool:
        """Add a SuperAdmin user with NULL department for system-wide access (insert only)."""
        insert_query = f"""
        INSERT INTO {self.table_name} (mail_id, department_name, role, created_by)
        VALUES ($1, NULL, 'SuperAdmin', $2)
        ON CONFLICT (mail_id, department_name) DO NOTHING
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(insert_query, mail_id, created_by)
                return True
        except Exception as e:
            log.error(f"Error adding SuperAdmin {mail_id}: {e}")
            return False

    async def remove_user_from_department(self, mail_id: str, department_name: str) -> bool:
        """Remove a user from a department"""
        query = f"""
        DELETE FROM {self.table_name}
        WHERE mail_id = $1 AND department_name = $2
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, mail_id, department_name)
                return "DELETE 1" in result
        except Exception as e:
            log.error(f"Error removing user {mail_id} from department {department_name}: {e}")
            return False

    async def get_user_departments(self, mail_id: str) -> List[Dict[str, Any]]:
        """Get all departments for a user with their roles and active status"""
        query = f"""
        SELECT department_name, role, is_active FROM {self.table_name}
        WHERE mail_id = $1
        ORDER BY department_name
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, mail_id)
                return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error getting departments for user {mail_id}: {e}")
            return []

    async def get_user_departments_simple(self, mail_id: str) -> List[str]:
        """Get all department names for a user (for backward compatibility)"""
        query = f"""
        SELECT department_name FROM {self.table_name}
        WHERE mail_id = $1
        ORDER BY department_name
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, mail_id)
                return [row['department_name'] for row in rows]
        except Exception as e:
            log.error(f"Error getting departments for user {mail_id}: {e}")
            return []

    async def get_department_users(self, department_name: str) -> List[Dict[str, Any]]:
        """Get all users in a department with their details, roles, and active status"""
        query = f"""
        SELECT udm.mail_id, udm.role, udm.is_active, udm.created_at, udm.created_by, lc.user_name, lc.is_active as global_is_active
        FROM {self.table_name} udm
        JOIN login_credential lc ON udm.mail_id = lc.mail_id
        WHERE udm.department_name = $1
        ORDER BY lc.user_name
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, department_name)
                return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error getting users for department {department_name}: {e}")
            return []

    async def check_user_in_department(self, mail_id: str, department_name: str) -> bool:
        """Check if a user exists in a specific department"""
        query = f"""
        SELECT 1 FROM {self.table_name}
        WHERE mail_id = $1 AND department_name = $2
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchrow(query, mail_id, department_name)
                return result is not None
        except Exception as e:
            log.error(f"Error checking user {mail_id} in department {department_name}: {e}")
            return False

    async def get_user_role_in_department(self, mail_id: str, department_name: str) -> Optional[str]:
        """Get user's role in a specific department"""
        query = f"""
        SELECT role FROM {self.table_name}
        WHERE mail_id = $1 AND department_name = $2
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval(query, mail_id, department_name)
                return result
        except Exception as e:
            log.error(f"Error getting user {mail_id} role in department {department_name}: {e}")
            return None

    async def get_user_role_for_department(self, mail_id: str, department_name: str = None) -> Optional[str]:
        """
        Get user's role for a specific department (including NULL department for SuperAdmin).
        Used for login authentication.
        """
        if department_name is None:
            # Check for SuperAdmin with NULL department
            query = f"""
            SELECT role FROM {self.table_name}
            WHERE mail_id = $1 AND department_name IS NULL
            """
        else:
            # Check for specific department
            query = f"""
            SELECT role FROM {self.table_name}
            WHERE mail_id = $1 AND department_name = $2
            """
        
        try:
            async with self.pool.acquire() as conn:
                if department_name is None:
                    result = await conn.fetchval(query, mail_id)
                else:
                    result = await conn.fetchval(query, mail_id, department_name)
                return result
        except Exception as e:
            log.error(f"Error getting user {mail_id} role for department {department_name}: {e}")
            return None

    async def update_user_role_in_department(self, mail_id: str, department_name: str, new_role: str) -> bool:
        """Update user's role in a specific department"""
        query = f"""
        UPDATE {self.table_name}
        SET role = $3
        WHERE mail_id = $1 AND department_name = $2
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, mail_id, department_name, new_role)
                return "UPDATE 1" in result
        except Exception as e:
            log.error(f"Error updating user {mail_id} role in department {department_name}: {e}")
            return False

    async def get_all_mappings(self) -> List[Dict[str, Any]]:
        """Get all user-department mappings with roles and active status"""
        query = f"""
        SELECT udm.mail_id, udm.department_name, udm.role, udm.is_active, udm.created_at, udm.created_by, 
               lc.user_name, lc.is_active as global_is_active
        FROM {self.table_name} udm
        JOIN login_credential lc ON udm.mail_id = lc.mail_id
        ORDER BY lc.user_name, udm.department_name
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
                return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error getting all user-department mappings: {e}")
            return []

    async def get_user_primary_role(self, mail_id: str) -> Optional[str]:
        """Get user's highest priority role across all departments (for backward compatibility)"""
        role_priority = {'SuperAdmin': 4, 'Admin': 3, 'Developer': 2, 'User': 1}
        
        query = f"""
        SELECT role FROM {self.table_name}
        WHERE mail_id = $1
        ORDER BY CASE role 
            WHEN 'SuperAdmin' THEN 4
            WHEN 'Admin' THEN 3 
            WHEN 'Developer' THEN 2
            WHEN 'User' THEN 1
            ELSE 0
        END DESC
        LIMIT 1
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval(query, mail_id)
                return result
        except Exception as e:
            log.error(f"Error getting primary role for user {mail_id}: {e}")
            return None

    # ─────────────────────────────────────────────────────────────────────────────
    # DEPARTMENT-SPECIFIC ENABLE/DISABLE METHODS
    # ─────────────────────────────────────────────────────────────────────────────

    async def set_user_active_in_department(self, mail_id: str, department_name: str, is_active: bool) -> bool:
        """Enable or disable a user in a specific department"""
        query = f"""
        UPDATE {self.table_name}
        SET is_active = $3
        WHERE mail_id = $1 AND department_name = $2
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, mail_id, department_name, is_active)
                if "UPDATE 1" in result:
                    status = "enabled" if is_active else "disabled"
                    log.info(f"User {mail_id} has been {status} in department {department_name}")
                    return True
                log.warning(f"User {mail_id} not found in department {department_name}")
                return False
        except Exception as e:
            log.error(f"Error setting user {mail_id} active status in department {department_name}: {e}")
            return False

    async def enable_user_in_department(self, mail_id: str, department_name: str) -> bool:
        """Enable a user in a specific department"""
        return await self.set_user_active_in_department(mail_id, department_name, True)

    async def disable_user_in_department(self, mail_id: str, department_name: str) -> bool:
        """Disable a user in a specific department"""
        return await self.set_user_active_in_department(mail_id, department_name, False)

    async def is_user_active_in_department(self, mail_id: str, department_name: str) -> Optional[bool]:
        """Check if user is active in a specific department. Returns None if mapping not found."""
        query = f"""
        SELECT is_active FROM {self.table_name}
        WHERE mail_id = $1 AND department_name = $2
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval(query, mail_id, department_name)
                return result  # Returns True, False, or None if not found
        except Exception as e:
            log.error(f"Error checking if user {mail_id} is active in department {department_name}: {e}")
            return None

    async def get_user_department_status(self, mail_id: str, department_name: str) -> Optional[Dict[str, Any]]:
        """Get user's full status in a department including role and active status"""
        query = f"""
        SELECT role, is_active, created_at, created_by FROM {self.table_name}
        WHERE mail_id = $1 AND department_name = $2
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchrow(query, mail_id, department_name)
                return dict(result) if result else None
        except Exception as e:
            log.error(f"Error getting user {mail_id} status in department {department_name}: {e}")
            return None

    async def has_superadmin_assignment(self) -> bool:
        """Check if there is already a SuperAdmin user in the system"""
        query = f"SELECT COUNT(*) FROM {self.table_name} WHERE role = 'SuperAdmin'"
        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval(query)
                return count > 0
        except Exception as e:
            log.error(f"Error checking if SuperAdmin exists: {e}")
            return True  # Return True to be safe and prevent creating multiple SuperAdmins


    async def search_users_all(
        self,
        search: Optional[str] = None,
        department_name: Optional[str] = None,
        role: Optional[str] = None,
        status: Optional[str] = None,  # "Active" | "Pending"
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        SuperAdmin view. Returns {rows, total}.
        - status="Pending" => users with NO entries in userdepartmentmapping
        - status="Active"/None => users WITH mappings (filtered by dept/role if provided)
        """

        async with self.pool.acquire() as conn:
            # ---- Pending branch: users without any mapping ----
            if status and status.lower() == "pending":
                params_rows: List[Any] = []
                params_count: List[Any] = []

                search_cond = ""
                if search:
                    search_cond = " AND (lc.user_name ILIKE $1 OR lc.mail_id ILIKE $1)"
                    params_rows.append(f"%{search}%")
                    params_count.append(f"%{search}%")

                rows_q = f"""
                    SELECT lc.mail_id, lc.user_name, lc.is_active as global_is_active
                    FROM login_credential lc
                    LEFT JOIN {self.table_name} udm ON lc.mail_id = udm.mail_id
                    WHERE udm.mail_id IS NULL
                    {search_cond}
                    LIMIT ${len(params_rows)+1} OFFSET ${len(params_rows)+2}
                """
                # Add limit/offset only to rows query
                rows = await conn.fetch(rows_q, *params_rows, limit, offset)

                count_q = f"""
                    SELECT COUNT(*) AS total
                    FROM login_credential lc
                    LEFT JOIN {self.table_name} udm ON lc.mail_id = udm.mail_id
                    WHERE udm.mail_id IS NULL
                    {search_cond}
                """
                total = await conn.fetchval(count_q, *params_count)

                return {
                    "rows": [
                        {
                            "email": r["mail_id"],
                            "username": r["user_name"],
                            "global_is_active": r["global_is_active"] if r["global_is_active"] is not None else True,
                            "departments": [],
                            "status": "Pending",
                        }
                        for r in rows
                    ],
                    "total": int(total or 0),
                }

            # ---- Active/mixed branch: users with mappings ----
            params_rows: List[Any] = []
            params_count: List[Any] = []

            where_parts = ["1=1"]
            if department_name:
                where_parts.append(f"udm.department_name = ${len(params_rows)+1}")
                params_rows.append(department_name)
                params_count.append(department_name)

            if role:
                where_parts.append(f"udm.role = ${len(params_rows)+1}")
                params_rows.append(role)
                params_count.append(role)

            search_cond = ""
            if search:
                search_cond = f" AND (lc.user_name ILIKE ${len(params_rows)+1} OR lc.mail_id ILIKE ${len(params_rows)+1})"
                params_rows.append(f"%{search}%")
                params_count.append(f"%{search}%")

            where_sql = " AND ".join(where_parts)

            inner = f"""
                SELECT lc.mail_id, lc.user_name, lc.is_active as global_is_active,
                    udm.department_name, udm.role, udm.is_active as dept_is_active, udm.created_at, udm.created_by
                FROM {self.table_name} udm
                JOIN login_credential lc ON lc.mail_id = udm.mail_id
                WHERE {where_sql} {search_cond}
            """

            rows_q = f"""
                SELECT s.mail_id AS mail_id,
                    MAX(s.user_name) AS user_name,
                    BOOL_AND(s.global_is_active) AS global_is_active,
                    ARRAY_AGG(
                        JSON_BUILD_OBJECT(
                        'department_name', s.department_name,
                        'role', s.role,
                        'is_active', s.dept_is_active,
                        'added_at', s.created_at,
                        'added_by', s.created_by
                        )
                    ) AS departments
                FROM ({inner}) AS s
                GROUP BY s.mail_id
                LIMIT ${len(params_rows)+1} OFFSET ${len(params_rows)+2}
            """
            rows = await conn.fetch(rows_q, *params_rows, limit, offset)

            count_q = f"SELECT COUNT(DISTINCT s.mail_id) FROM ({inner}) AS s"
            total = await conn.fetchval(count_q, *params_count)

            return {
                "rows": [
                    {
                        "email": r["mail_id"],
                        "username": r["user_name"],
                        "global_is_active": r["global_is_active"] if r["global_is_active"] is not None else True,
                        "departments": r["departments"],
                        "status": "Active" if r["departments"] else "Pending",
                    }
                    for r in rows
                ],
                "total": int(total or 0),
            }


    async def search_department_users_for_admin(
        self,
        admin_department: str,
        search: Optional[str] = None,
        role: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Admin view (single-dept): list users in admin_department with search+role filter.
        Returns {rows, total}.
        """

        # Build params separately for rows and count
        params_rows: List[Any] = [admin_department]
        params_count: List[Any] = [admin_department]

        where_parts = ["udm.department_name = $1"]
        next_pos_rows = 2

        if role:
            where_parts.append(f"udm.role = ${next_pos_rows}")
            params_rows.append(role)
            params_count.append(role)
            next_pos_rows += 1

        search_cond = ""
        if search:
            search_cond = f" AND (lc.user_name ILIKE ${next_pos_rows} OR lc.mail_id ILIKE ${next_pos_rows})"
            params_rows.append(f"%{search}%")
            params_count.append(f"%{search}%")

        inner = f"""
            SELECT lc.mail_id, lc.user_name, lc.is_active as global_is_active,
                udm.department_name, udm.role, udm.is_active as dept_is_active, udm.created_at, udm.created_by
            FROM {self.table_name} udm
            JOIN login_credential lc ON lc.mail_id = udm.mail_id
            WHERE {' AND '.join(where_parts)} {search_cond}
        """

        rows_q = f"""
            SELECT s.mail_id AS mail_id,
                MAX(s.user_name) AS user_name,
                BOOL_AND(s.global_is_active) AS global_is_active,
                ARRAY_AGG(
                    JSON_BUILD_OBJECT(
                    'department_name', s.department_name,
                    'role', s.role,
                    'is_active', s.dept_is_active,
                    'added_at', s.created_at,
                    'added_by', s.created_by
                    )
                ) AS departments
            FROM ({inner}) AS s
            GROUP BY s.mail_id
            LIMIT ${len(params_rows)+1} OFFSET ${len(params_rows)+2}
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(rows_q, *params_rows, limit, offset)

            count_q = f"SELECT COUNT(DISTINCT s.mail_id) FROM ({inner}) AS s"
            total = await conn.fetchval(count_q, *params_count)

        return {
            "rows": [
                {
                    "email": r["mail_id"],
                    "username": r["user_name"],
                    "global_is_active": r["global_is_active"] if r["global_is_active"] is not None else True,
                    "departments": r["departments"],
                    "status": "Active",
                }
                for r in rows
            ],
            "total": int(total or 0),
        }


class ApprovalPermissionRepository:
    """Repository for approval permission management"""
    
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.table_name = TableNames.APPROVAL_PERMISSIONS.value
    
    async def create_table_if_not_exists(self):
        """Create approval permissions table if it doesn't exist"""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            admin_user_mail_id TEXT REFERENCES {TableNames.LOGIN_CREDENTIAL.value}(mail_id) ON DELETE CASCADE,
            granted_by_mail_id TEXT REFERENCES {TableNames.LOGIN_CREDENTIAL.value}(mail_id) ON DELETE CASCADE,
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
        JOIN {TableNames.LOGIN_CREDENTIAL.value} u ON ap.admin_user_mail_id = u.mail_id
        JOIN {TableNames.LOGIN_CREDENTIAL.value} gb ON ap.granted_by_mail_id = gb.mail_id
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
        self.table_name = TableNames.AUDIT_LOGS_IAF.value

    async def create_table_if_not_exists(self):
        """Create audit logs table if it doesn't exist. user_id refers to mail_id from login_credential."""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id TEXT PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id TEXT REFERENCES {TableNames.LOGIN_CREDENTIAL.value}(mail_id) ON DELETE SET NULL,
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
        self.table_name = TableNames.REFRESH_TOKENS.value
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
            user_mail_id TEXT NOT NULL REFERENCES {TableNames.LOGIN_CREDENTIAL.value}(mail_id) ON DELETE CASCADE,
            refresh_token TEXT NOT NULL UNIQUE,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            revoked_at TIMESTAMP,
            user_agent TEXT,
            ip_address INET,
            role VARCHAR(50),
            department_name VARCHAR(50)
        );
        CREATE INDEX IF NOT EXISTS idx_{self.table_name}_user_mail_id ON {self.table_name}(user_mail_id);
        CREATE INDEX IF NOT EXISTS idx_{self.table_name}_expires_at ON {self.table_name}(expires_at);
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
                # Defensive migration: ensure all expected columns exist (for earlier partial versions)
                expected_columns = {
                    'user_mail_id': f"TEXT NOT NULL REFERENCES {TableNames.LOGIN_CREDENTIAL.value}(mail_id) ON DELETE CASCADE",
                    'refresh_token': "TEXT UNIQUE",
                    'expires_at': "TIMESTAMP NOT NULL",
                    'created_at': "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                    'revoked_at': "TIMESTAMP",
                    'user_agent': "TEXT",
                    'ip_address': "INET",
                    'role': "VARCHAR(50)",
                    'department_name': "VARCHAR(50)"
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

    async def store_token(self, user_mail_id: str, refresh_token: str, expires_at, user_agent: str = None, ip_address: str = None, role: str = None, department_name: str = None):
        async with self.pool.acquire() as conn:
            cols = await self._load_columns(conn)
            token_hash = hashlib.sha256(refresh_token.encode('utf-8')).hexdigest()
            
            # Check if we have the new columns for role and department
            has_role_cols = 'role' in cols and 'department_name' in cols
            
            # Determine insert strategy based on existing columns
            if 'token_hash' in cols and 'refresh_token' in cols:
                if has_role_cols:
                    query = f"""
                    INSERT INTO {self.table_name} (user_mail_id, refresh_token, token_hash, expires_at, user_agent, ip_address, role, department_name)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING id
                    """
                    row = await conn.fetchrow(query, user_mail_id, refresh_token, token_hash, expires_at, user_agent, ip_address, role, department_name)
                else:
                    query = f"""
                    INSERT INTO {self.table_name} (user_mail_id, refresh_token, token_hash, expires_at, user_agent, ip_address)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING id
                    """
                    row = await conn.fetchrow(query, user_mail_id, refresh_token, token_hash, expires_at, user_agent, ip_address)
            elif 'token_hash' in cols:  # hashed only storage
                if has_role_cols:
                    query = f"""
                    INSERT INTO {self.table_name} (user_mail_id, token_hash, expires_at, user_agent, ip_address, role, department_name)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING id
                    """
                    row = await conn.fetchrow(query, user_mail_id, token_hash, expires_at, user_agent, ip_address, role, department_name)
                else:
                    query = f"""
                    INSERT INTO {self.table_name} (user_mail_id, token_hash, expires_at, user_agent, ip_address)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING id
                    """
                    row = await conn.fetchrow(query, user_mail_id, token_hash, expires_at, user_agent, ip_address)
            else:  # legacy plain token storage
                if has_role_cols:
                    query = f"""
                    INSERT INTO {self.table_name} (user_mail_id, refresh_token, expires_at, user_agent, ip_address, role, department_name)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING id
                    """
                    row = await conn.fetchrow(query, user_mail_id, refresh_token, expires_at, user_agent, ip_address, role, department_name)
                else:
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


class RoleRepository:
    """
    Repository for role-based access control system.
    
    Manages role permissions through the role_access table which stores
    department-specific role permissions. Roles are defined in the 
    departments table as JSONB arrays, and this repository handles
    the permission mappings for those roles.
    """

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.role_access_table = "role_access"

    async def create_tables_if_not_exists(self):
        """
        Create role_access table with department-specific role permissions.
        
        The role_access table stores permissions for roles within departments.
        It references the departments table via foreign key and contains
        detailed permission settings for tools, agents, and various access levels.
        """
        try:
            async with self.pool.acquire() as conn:
                # Create role_access table with JSONB permission fields for tools and agents
                # References departments table as foreign key for clean department-based access control
                # Note: created_by does NOT reference login_credential to allow system-generated entries
                role_access_query = f"""
                CREATE TABLE IF NOT EXISTS {self.role_access_table} (
                    id SERIAL PRIMARY KEY,
                    department_name VARCHAR(50) NOT NULL,
                    role_name VARCHAR(50) NOT NULL,
                    read_access JSONB DEFAULT '{{"tools": false, "agents": false}}'::jsonb,
                    add_access JSONB DEFAULT '{{"tools": false, "agents": false}}'::jsonb,
                    update_access JSONB DEFAULT '{{"tools": false, "agents": false}}'::jsonb,
                    delete_access JSONB DEFAULT '{{"tools": false, "agents": false}}'::jsonb,
                    execute_access JSONB DEFAULT '{{"tools": false, "agents": false}}'::jsonb,
                    execution_steps_access BOOLEAN DEFAULT false,
                    tool_verifier_flag_access BOOLEAN DEFAULT false,
                    plan_verifier_flag_access BOOLEAN DEFAULT false,
                    online_evaluation_flag_access BOOLEAN DEFAULT false,
                    evaluation_access BOOLEAN DEFAULT false,
                    vault_access BOOLEAN DEFAULT false,
                    data_connector_access BOOLEAN DEFAULT false,
                    knowledgebase_access BOOLEAN DEFAULT false,
                    validator_access BOOLEAN DEFAULT false,
                    file_context_access BOOLEAN DEFAULT false,
                    canvas_view_access BOOLEAN DEFAULT false,
                    context_access BOOLEAN DEFAULT false,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT,
                    UNIQUE (department_name, role_name),
                    FOREIGN KEY (department_name) REFERENCES departments(department_name) ON DELETE CASCADE
                );
                """
                await conn.execute(role_access_query)

                # Migration: Drop old FK constraint on created_by if it exists (for existing databases)
                try:
                    await conn.execute(f"ALTER TABLE {self.role_access_table} DROP CONSTRAINT IF EXISTS role_access_created_by_fkey")
                    log.info("Dropped old FK constraint on created_by column")
                except Exception as e:
                    log.debug(f"FK constraint on created_by may not exist: {e}")

                # Add execution_steps_access column if it doesn't exist (for existing databases)
                try:
                    await conn.execute(f"ALTER TABLE {self.role_access_table} ADD COLUMN IF NOT EXISTS execution_steps_access BOOLEAN DEFAULT false")
                    log.info("Added execution_steps_access column to existing table")
                except Exception as e:
                    log.debug(f"Column execution_steps_access may already exist: {e}")

                # Add new verifier flag access columns for dynamic permission control (for existing databases)
                try:
                    await conn.execute(f"ALTER TABLE {self.role_access_table} ADD COLUMN IF NOT EXISTS tool_verifier_flag_access BOOLEAN DEFAULT false")
                    await conn.execute(f"ALTER TABLE {self.role_access_table} ADD COLUMN IF NOT EXISTS plan_verifier_flag_access BOOLEAN DEFAULT false")
                    await conn.execute(f"ALTER TABLE {self.role_access_table} ADD COLUMN IF NOT EXISTS evaluation_access BOOLEAN DEFAULT false")
                    log.info("Added new verifier flag access columns to existing table")
                except Exception as e:
                    log.debug(f"Verifier flag access columns may already exist: {e}")

                # Migration: Rename evaluation_flag_access to online_evaluation_flag_access
                try:
                    # Check if old column exists and new one doesn't
                    old_col_exists = await conn.fetchval("""
                        SELECT COUNT(*) FROM information_schema.columns 
                        WHERE table_name = $1 AND column_name = 'evaluation_flag_access'
                    """, self.role_access_table)
                    
                    new_col_exists = await conn.fetchval("""
                        SELECT COUNT(*) FROM information_schema.columns 
                        WHERE table_name = $1 AND column_name = 'online_evaluation_flag_access'
                    """, self.role_access_table)
                    
                    if old_col_exists and not new_col_exists:
                        # Add new column
                        await conn.execute(f"ALTER TABLE {self.role_access_table} ADD COLUMN online_evaluation_flag_access BOOLEAN DEFAULT false")
                        # Copy data from old column
                        await conn.execute(f"UPDATE {self.role_access_table} SET online_evaluation_flag_access = evaluation_flag_access")
                        # Drop old column
                        await conn.execute(f"ALTER TABLE {self.role_access_table} DROP COLUMN evaluation_flag_access")
                        log.info("Successfully migrated evaluation_flag_access to online_evaluation_flag_access")
                    elif not old_col_exists and not new_col_exists:
                        # Fresh install, add new column
                        await conn.execute(f"ALTER TABLE {self.role_access_table} ADD COLUMN IF NOT EXISTS online_evaluation_flag_access BOOLEAN DEFAULT false")
                        log.info("Added online_evaluation_flag_access column to new table")
                except Exception as e:
                    log.debug(f"Column migration may have already completed: {e}")

                # Add vault and data connector access columns (for existing databases)
                try:
                    await conn.execute(f"ALTER TABLE {self.role_access_table} ADD COLUMN IF NOT EXISTS vault_access BOOLEAN DEFAULT false")
                    await conn.execute(f"ALTER TABLE {self.role_access_table} ADD COLUMN IF NOT EXISTS data_connector_access BOOLEAN DEFAULT false")
                    await conn.execute(f"ALTER TABLE {self.role_access_table} ADD COLUMN IF NOT EXISTS knowledgebase_access BOOLEAN DEFAULT false")
                    log.info("Added vault_access, data_connector_access and knowledgebase_access columns to existing table")
                except Exception as e:
                    log.debug(f"Vault and data connector access columns may already exist: {e}")

                # Add validator, file_context, canvas_view, and context access columns (for existing databases)
                try:
                    await conn.execute(f"ALTER TABLE {self.role_access_table} ADD COLUMN IF NOT EXISTS validator_access BOOLEAN DEFAULT false")
                    await conn.execute(f"ALTER TABLE {self.role_access_table} ADD COLUMN IF NOT EXISTS file_context_access BOOLEAN DEFAULT false")
                    await conn.execute(f"ALTER TABLE {self.role_access_table} ADD COLUMN IF NOT EXISTS canvas_view_access BOOLEAN DEFAULT false")
                    await conn.execute(f"ALTER TABLE {self.role_access_table} ADD COLUMN IF NOT EXISTS context_access BOOLEAN DEFAULT false")
                    log.info("Added validator_access, file_context_access, canvas_view_access, context_access columns to existing table")
                except Exception as e:
                    log.debug(f"New access columns may already exist: {e}")

                # Migration: Clean up any old foreign key constraints from previous implementations
                try:
                    await conn.execute(f"ALTER TABLE {self.role_access_table} DROP CONSTRAINT IF EXISTS role_access_role_name_fkey")
                    await conn.execute(f"ALTER TABLE {self.role_access_table} DROP CONSTRAINT IF EXISTS fk_role_access_role")
                    log.info("Cleaned up old foreign key constraints from previous implementations")
                except Exception as e:
                    log.debug(f"Old constraints may not exist: {e}")

                # Create indexes for better performance
                await conn.execute(f"CREATE INDEX IF NOT EXISTS idx_role_access_name ON {self.role_access_table}(role_name)")
                await conn.execute(f"CREATE INDEX IF NOT EXISTS idx_role_access_dept ON {self.role_access_table}(department_name)")

            log.info(f"Table '{self.role_access_table}' created or already exists.")
        except Exception as e:
            log.error(f"Error creating role access table: {e}")
            raise



    async def role_exists(self, role_name: str, department_name: str) -> bool:
        """Check if role exists in a specific department's roles JSONB array"""
        query = f"SELECT roles FROM departments WHERE department_name = $1"
        try:
            async with self.pool.acquire() as conn:
                department_roles = await conn.fetchval(query, department_name)
                log.info(f"role_exists check - department: {department_name}, role: {role_name}, fetched roles: {department_roles} (type: {type(department_roles).__name__})")
                if department_roles:
                    # Handle different types that JSONB might return
                    if isinstance(department_roles, list):
                        exists = role_name in department_roles
                        log.info(f"role_exists result: {exists}")
                        return exists
                    elif isinstance(department_roles, str):
                        import json
                        try:
                            roles_list = json.loads(department_roles)
                            exists = role_name in roles_list
                            log.info(f"role_exists (parsed str) result: {exists}")
                            return exists
                        except (json.JSONDecodeError, TypeError):
                            log.warning(f"Failed to parse roles as JSON: {department_roles}")
                            return False
                    else:
                        log.warning(f"Unexpected type for department_roles: {type(department_roles)} - {department_roles}")
                        return False
                log.info(f"role_exists - no roles found for department {department_name}")
                return False
        except Exception as e:
            log.error(f"Error checking role existence in department {department_name}: {e}")
            return False



    async def set_role_permissions(self, department_name: str, role_name: str, read_access: Dict[str, bool] = None, 
                                  add_access: Dict[str, bool] = None, update_access: Dict[str, bool] = None,
                                  delete_access: Dict[str, bool] = None, execute_access: Dict[str, bool] = None,
                                  execution_steps_access: bool = None, tool_verifier_flag_access: bool = None,
                                  plan_verifier_flag_access: bool = None, online_evaluation_flag_access: bool = None,
                                  evaluation_access: bool = None, vault_access: bool = None, data_connector_access: bool = None,
                                  knowledgebase_access: bool = None,
                                  validator_access: bool = None, file_context_access: bool = None,
                                  canvas_view_access: bool = None, context_access: bool = None,
                                  created_by: str = None) -> bool:
        """Set permissions for a role in a specific department"""
        # First check if role exists in the department
        if not await self.role_exists(role_name, department_name):
            log.error(f"Role '{role_name}' does not exist in department '{department_name}'")
            return False
            
        # Check if department exists
        dept_exists_query = "SELECT COUNT(*) FROM departments WHERE department_name = $1"
        async with self.pool.acquire() as conn:
            dept_count = await conn.fetchval(dept_exists_query, department_name)
            if dept_count == 0:
                log.error(f"Department '{department_name}' does not exist")
                return False

        # Default permission structure
        default_permission = {"tools": False, "agents": False}
        
        # Use provided permissions or defaults
        read_perm = read_access if read_access else default_permission
        add_perm = add_access if add_access else default_permission
        update_perm = update_access if update_access else default_permission
        delete_perm = delete_access if delete_access else default_permission
        execute_perm = execute_access if execute_access else default_permission
        exec_steps_access = execution_steps_access if execution_steps_access is not None else False
        tool_verifier_access = tool_verifier_flag_access if tool_verifier_flag_access is not None else False
        plan_verifier_access = plan_verifier_flag_access if plan_verifier_flag_access is not None else False
        online_evaluation_flag = online_evaluation_flag_access if online_evaluation_flag_access is not None else False
        evaluation_access_val = evaluation_access if evaluation_access is not None else False
        vault_access_val = vault_access if vault_access is not None else False
        data_connector_access_val = data_connector_access if data_connector_access is not None else False
        knowledgebase_access_val = knowledgebase_access if knowledgebase_access is not None else False
        validator_access_val = validator_access if validator_access is not None else False
        file_context_access_val = file_context_access if file_context_access is not None else False
        canvas_view_access_val = canvas_view_access if canvas_view_access is not None else False
        context_access_val = context_access if context_access is not None else False

        # Insert or update role permissions
        upsert_query = f"""
        INSERT INTO {self.role_access_table} (department_name, role_name, read_access, add_access, update_access, delete_access, execute_access, execution_steps_access, tool_verifier_flag_access, plan_verifier_flag_access, online_evaluation_flag_access, evaluation_access, vault_access, data_connector_access, knowledgebase_access, validator_access, file_context_access, canvas_view_access, context_access, created_by)
        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5::jsonb, $6::jsonb, $7::jsonb, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20)
        ON CONFLICT (department_name, role_name) 
        DO UPDATE SET 
            read_access = EXCLUDED.read_access,
            add_access = EXCLUDED.add_access,
            update_access = EXCLUDED.update_access,
            delete_access = EXCLUDED.delete_access,
            execute_access = EXCLUDED.execute_access,
            execution_steps_access = EXCLUDED.execution_steps_access,
            tool_verifier_flag_access = EXCLUDED.tool_verifier_flag_access,
            plan_verifier_flag_access = EXCLUDED.plan_verifier_flag_access,
            online_evaluation_flag_access = EXCLUDED.online_evaluation_flag_access,
            evaluation_access = EXCLUDED.evaluation_access,
            vault_access = EXCLUDED.vault_access,
            data_connector_access = EXCLUDED.data_connector_access,
            knowledgebase_access = EXCLUDED.knowledgebase_access,
            validator_access = EXCLUDED.validator_access,
            file_context_access = EXCLUDED.file_context_access,
            canvas_view_access = EXCLUDED.canvas_view_access,
            context_access = EXCLUDED.context_access,
            updated_at = CURRENT_TIMESTAMP
        """
        try:
            import json
            async with self.pool.acquire() as conn:
                await conn.execute(upsert_query, department_name, role_name, 
                                 json.dumps(read_perm), json.dumps(add_perm), 
                                 json.dumps(update_perm), json.dumps(delete_perm), 
                                 json.dumps(execute_perm), exec_steps_access, 
                                 tool_verifier_access, plan_verifier_access, online_evaluation_flag,
                                 evaluation_access_val, vault_access_val, data_connector_access_val,
                                 knowledgebase_access_val, validator_access_val, file_context_access_val, canvas_view_access_val,
                                 context_access_val, created_by)
                log.info(f"Permissions set for role '{role_name}' in department '{department_name}'")
                return True
        except Exception as e:
            log.error(f"Error setting permissions for role '{role_name}' in department '{department_name}': {e}")
            return False

    async def update_role_permissions(self, department_name: str, role_name: str, **permissions) -> bool:
        """Update specific permissions for a role in a specific department (partial update)"""
        if not await self.role_exists(role_name, department_name):
            log.error(f"Role '{role_name}' does not exist in department '{department_name}'")
            return False
            
        # Check if department exists
        dept_exists_query = "SELECT COUNT(*) FROM departments WHERE department_name = $1"
        async with self.pool.acquire() as conn:
            dept_count = await conn.fetchval(dept_exists_query, department_name)
            if dept_count == 0:
                log.error(f"Department '{department_name}' does not exist")
                return False

        # Build dynamic query for only provided permissions
        update_fields = []
        params = [department_name, role_name]
        param_count = 2

        import json
        for perm_name, perm_value in permissions.items():
            if perm_value is not None and perm_name.endswith('_access'):
                param_count += 1
                if perm_name in ['execution_steps_access', 'tool_verifier_flag_access', 'plan_verifier_flag_access', 'online_evaluation_flag_access', 'evaluation_access', 'vault_access', 'data_connector_access', 'knowledgebase_access', 'validator_access', 'file_context_access', 'canvas_view_access', 'context_access']:
                    # Handle boolean fields
                    update_fields.append(f"{perm_name} = ${param_count}")
                    params.append(perm_value)
                else:
                    # Handle JSONB fields for other permissions
                    update_fields.append(f"{perm_name} = ${param_count}::jsonb")
                    params.append(json.dumps(perm_value))

        if not update_fields:
            log.warning("No permissions provided for update")
            return True

        update_query = f"""
        UPDATE {self.role_access_table} 
        SET {', '.join(update_fields)}, updated_at = CURRENT_TIMESTAMP
        WHERE department_name = $1 AND role_name = $2
        """

        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(update_query, *params)
                log.info(f"Permissions updated for role '{role_name}' in department '{department_name}'")
                return result != "UPDATE 0"
        except Exception as e:
            log.error(f"Error updating permissions for role '{role_name}' in department '{department_name}': {e}")
            return False

    async def get_role_permissions(self, department_name: str, role_name: str) -> Optional[Dict[str, Any]]:
        """Get permissions for a specific role in a specific department"""
        query = f"SELECT * FROM {self.role_access_table} WHERE department_name = $1 AND role_name = $2"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchrow(query, department_name, role_name)
                return dict(result) if result else None
        except Exception as e:
            log.error(f"Error fetching permissions for role '{role_name}' in department '{department_name}': {e}")
            return None

    async def get_all_role_permissions(self, department_name: str = None) -> List[Dict[str, Any]]:
        """Get all role permissions, optionally filtered by department"""
        if department_name:
            query = f"""
            SELECT ra.department_name, ra.role_name, ra.read_access, ra.add_access, ra.update_access, 
                   ra.delete_access, ra.execute_access, ra.execution_steps_access,
                   ra.tool_verifier_flag_access, ra.plan_verifier_flag_access, ra.online_evaluation_flag_access,
                   ra.evaluation_access, ra.vault_access, ra.data_connector_access, ra.knowledgebase_access,
                   ra.validator_access, ra.file_context_access, ra.canvas_view_access, ra.context_access,
                   ra.created_at, ra.updated_at, ra.created_by
            FROM {self.role_access_table} ra
            WHERE ra.department_name = $1
            ORDER BY ra.department_name, ra.role_name
            """
            params = [department_name]
        else:
            query = f"""
            SELECT ra.department_name, ra.role_name, ra.read_access, ra.add_access, ra.update_access, 
                   ra.delete_access, ra.execute_access, ra.execution_steps_access,
                   ra.tool_verifier_flag_access, ra.plan_verifier_flag_access, ra.online_evaluation_flag_access,
                   ra.evaluation_access, ra.vault_access, ra.data_connector_access, ra.knowledgebase_access,
                   ra.validator_access, ra.file_context_access, ra.canvas_view_access, ra.context_access,
                   ra.created_at, ra.updated_at, ra.created_by
            FROM {self.role_access_table} ra
            ORDER BY ra.department_name, ra.role_name
            """
            params = []
            
        try:
            async with self.pool.acquire() as conn:
                results = await conn.fetch(query, *params)
                return [dict(row) for row in results]
        except Exception as e:
            log.error(f"Error fetching all role permissions: {e}")
            raise

    async def initialize_default_roles_and_permissions(self, system_user: str = "SYSTEM") -> bool:
        """Initialize default roles and their permissions for all departments"""
        try:
            # Default roles with JSON permissions structure
            default_roles_permissions = {
                "User": {
                    "read_access": {"tools": True, "agents": True},
                    "add_access": {"tools": False, "agents": False},
                    "update_access": {"tools": False, "agents": False},
                    "delete_access": {"tools": False, "agents": False},
                    "execute_access": {"tools": False, "agents": False},
                    "execution_steps_access": False,
                    "tool_verifier_flag_access": False,
                    "plan_verifier_flag_access": False,
                    "online_evaluation_flag_access": False,
                    "evaluation_access": False,
                    "vault_access": False,
                    "data_connector_access": False,
                    "knowledgebase_access": False,
                    "validator_access": False,
                    "file_context_access": False,
                    "canvas_view_access": False,
                    "context_access": False
                },
                "Developer": {
                    "read_access": {"tools": True, "agents": True},
                    "add_access": {"tools": True, "agents": True},
                    "update_access": {"tools": True, "agents": True},
                    "delete_access": {"tools": True, "agents": True},
                    "execute_access": {"tools": True, "agents": True},
                    "execution_steps_access": True,
                    "tool_verifier_flag_access": True,
                    "plan_verifier_flag_access": True,
                    "online_evaluation_flag_access": True,
                    "evaluation_access": True,
                    "vault_access": True,
                    "data_connector_access": True,
                    "knowledgebase_access": True,
                    "validator_access": True,
                    "file_context_access": True,
                    "canvas_view_access": True,
                    "context_access": True
                },
                "Admin": {
                    "read_access": {"tools": True, "agents": True},
                    "add_access": {"tools": True, "agents": True},
                    "update_access": {"tools": True, "agents": True},
                    "delete_access": {"tools": True, "agents": True},
                    "execute_access": {"tools": True, "agents": True},
                    "execution_steps_access": True,
                    "tool_verifier_flag_access": True,
                    "plan_verifier_flag_access": True,
                    "online_evaluation_flag_access": True,
                    "evaluation_access": True,
                    "vault_access": True,
                    "data_connector_access": True,
                    "knowledgebase_access": True,
                    "validator_access": True,
                    "file_context_access": True,
                    "canvas_view_access": True,
                    "context_access": True
                },
                "SuperAdmin": {
                    "read_access": {"tools": True, "agents": True},
                    "add_access": {"tools": True, "agents": True},
                    "update_access": {"tools": True, "agents": True},
                    "delete_access": {"tools": True, "agents": True},
                    "execute_access": {"tools": True, "agents": True},
                    "execution_steps_access": True,
                    "tool_verifier_flag_access": True,
                    "plan_verifier_flag_access": True,
                    "online_evaluation_flag_access": True,
                    "evaluation_access": True,
                    "vault_access": True,
                    "data_connector_access": True,
                    "knowledgebase_access": True,
                    "validator_access": True,
                    "file_context_access": True,
                    "canvas_view_access": True,
                    "context_access": True
                }
            }

            # Get all existing departments
            async with self.pool.acquire() as conn:
                departments_result = await conn.fetch("SELECT department_name FROM departments")
                departments = [row['department_name'] for row in departments_result]
            
            # Only initialize permissions for "General" department
            if "General" not in departments:
                log.info("General department not found - skipping default permissions initialization")
                return True
            
            # Only initialize for default roles in General department
            default_roles = ["Admin", "Developer", "User"]

            # Initialize permissions for default roles in General department only
            for role_name in default_roles:
                if role_name not in default_roles_permissions:
                    continue
                    
                permissions = default_roles_permissions[role_name]
                department_name = "General"
                
                # Check if role exists in department
                role_exists = await self.role_exists(role_name, department_name)
                log.debug(f"Checking if role '{role_name}' exists in department '{department_name}': {role_exists}")
                
                if not role_exists:
                    log.info(f"Role '{role_name}' needs to be added to department '{department_name}' - skipping permission setup")
                    continue
                
                # Only set permissions if they don't already exist (to preserve custom settings)
                existing_permissions = await self.get_role_permissions(department_name, role_name)
                if not existing_permissions:
                    # Set default permissions only if no permissions exist yet
                    await self.set_role_permissions(
                        department_name=department_name,
                        role_name=role_name,
                        read_access=permissions["read_access"],
                        add_access=permissions["add_access"],
                        update_access=permissions["update_access"],
                        delete_access=permissions["delete_access"],
                        execute_access=permissions["execute_access"],
                        execution_steps_access=permissions["execution_steps_access"],
                        tool_verifier_flag_access=permissions["tool_verifier_flag_access"],
                        plan_verifier_flag_access=permissions["plan_verifier_flag_access"],
                        online_evaluation_flag_access=permissions["online_evaluation_flag_access"],
                        evaluation_access=permissions["evaluation_access"],
                        vault_access=permissions["vault_access"],
                        data_connector_access=permissions["data_connector_access"],
                        knowledgebase_access=permissions["knowledgebase_access"],
                        validator_access=permissions["validator_access"],
                        file_context_access=permissions["file_context_access"],
                        canvas_view_access=permissions["canvas_view_access"],
                        context_access=permissions["context_access"],
                        created_by=system_user
                    )
                    log.info(f"Default permissions set for role '{role_name}' in department 'General'")
                else:
                    log.info(f"Permissions already exist for role '{role_name}' in department 'General' - preserving existing settings")

            log.info("Default roles and permissions initialized for General department")
            return True

        except Exception as e:
            log.error(f"Failed to initialize default roles and permissions: {e}")
            return False


class DepartmentRepository:
    def __init__(self, pool):
        self.pool = pool
        self.departments_table = "departments"

    async def create_table_if_not_exists(self):
        """Create departments table if it doesn't exist"""
        try:
            async with self.pool.acquire() as conn:
                # Create departments table with department_name, created_at, created_by, admins, and roles
                # Note: created_by is optional (NULL allowed) for system-created departments
                departments_table_query = f"""
                CREATE TABLE IF NOT EXISTS {self.departments_table} (
                    department_name VARCHAR(50) PRIMARY KEY,
                    admins JSONB DEFAULT '[]'::jsonb,
                    roles JSONB DEFAULT '[]'::jsonb,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT
                );
                """
                await conn.execute(departments_table_query)
                
                # Add admins column if it doesn't exist (for existing databases)
                try:
                    await conn.execute(f"ALTER TABLE {self.departments_table} ADD COLUMN IF NOT EXISTS admins JSONB DEFAULT '[]'::jsonb")
                    log.info("Added admins column to existing departments table")
                except Exception as e:
                    log.debug(f"Column admins may already exist: {e}")
                
                # Add roles column if it doesn't exist (for existing databases)
                try:
                    await conn.execute(f"ALTER TABLE {self.departments_table} ADD COLUMN IF NOT EXISTS roles JSONB DEFAULT '[]'::jsonb")
                    log.info("Added roles column to existing departments table")
                except Exception as e:
                    log.debug(f"Column roles may already exist: {e}")
                
                # Drop old foreign key constraint if it exists (to allow SYSTEM user for initialization)
                try:
                    await conn.execute(f"ALTER TABLE {self.departments_table} DROP CONSTRAINT IF EXISTS departments_created_by_fkey")
                    log.info("Dropped old foreign key constraint on created_by")
                except Exception as e:
                    log.debug(f"Foreign key constraint may not exist: {e}")

                # Create index for better performance
                await conn.execute(f"CREATE INDEX IF NOT EXISTS idx_departments_name ON {self.departments_table}(department_name)")
                
            log.info(f"Table '{self.departments_table}' created or already exists.")
            return True
        
        except Exception as e:
            log.error(f"Failed to create {self.departments_table} table: {e}")
            return False

    async def add_department(self, department_name: str, created_by: str = None):
        """Add a new department to the departments table"""
        try:
            # Ensure department name is properly formatted (first letter capitalized)
            department_name = department_name.strip()
            if department_name and not department_name[0].isupper():
                department_name = department_name.capitalize()
            
            # Check if department already exists
            if await self.department_exists(department_name):
                log.warning(f"Department '{department_name}' already exists")
                return False
            
            async with self.pool.acquire() as conn:
                query = f"""
        INSERT INTO {self.departments_table} (department_name, created_by)
        VALUES ($1, $2)
        RETURNING department_name, created_at, created_by
        """
                result = await conn.fetchrow(query, department_name, created_by)
                
                if result:
                    log.info(f"Department '{department_name}' added successfully by {created_by}")
                    return dict(result)
                return None
                
        except Exception as e:
            log.error(f"Failed to add department '{department_name}': {e}")
            return None

    async def get_all_departments(self):
        """Get all departments from the departments table"""
        query = f"SELECT * FROM {self.departments_table} ORDER BY department_name"
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
                departments = []
                for row in rows:
                    dept = dict(row)
                    # Ensure admins is a proper list
                    if isinstance(dept.get('admins'), str):
                        import json
                        try:
                            dept['admins'] = json.loads(dept['admins'])
                        except (json.JSONDecodeError, TypeError):
                            dept['admins'] = []
                    elif dept.get('admins') is None:
                        dept['admins'] = []
                    departments.append(dept)
                return departments
        except Exception as e:
            log.error(f"Failed to fetch departments: {e}")
            return []

    async def department_exists(self, department_name: str) -> bool:
        """Check if a department exists"""
        query = f"SELECT COUNT(*) FROM {self.departments_table} WHERE department_name = $1"
        
        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval(query, department_name)
                return count > 0
        except Exception as e:
            log.error(f"Failed to check if department exists: {e}")
            return False

    async def check_role_in_department(self, department_name: str, role_name: str) -> bool:
        """Check if a role is allowed in a specific department"""
            
        try:
            async with self.pool.acquire() as conn:
                # Check if the role is in the department's allowed roles list
                query = f"SELECT roles FROM {self.departments_table} WHERE department_name = $1"
                result = await conn.fetchrow(query, department_name)
                
                if result and result['roles']:
                    roles_data = result['roles']
                    # Handle JSONB data properly
                    if isinstance(roles_data, str):
                        import json
                        try:
                            allowed_roles = json.loads(roles_data)
                        except (json.JSONDecodeError, TypeError):
                            allowed_roles = []
                    elif isinstance(roles_data, list):
                        allowed_roles = roles_data
                    else:
                        allowed_roles = []
                    
                    return role_name in allowed_roles
                    
                return False
        except Exception as e:
            log.error(f"Failed to check role '{role_name}' in department '{department_name}': {e}")
            # If there's an error, be restrictive except for SuperAdmin
            return role_name == "SuperAdmin"

    async def delete_department(self, department_name: str):
        """Delete a department"""
        query = f"DELETE FROM {self.departments_table} WHERE department_name = $1"
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, department_name)
                
                if result == "DELETE 1":
                    log.info(f"Department '{department_name}' deleted successfully")
                    return True
                else:
                    log.warning(f"Department '{department_name}' not found")
                    return False
        except Exception as e:
            log.error(f"Failed to delete department '{department_name}': {e}")
            return False

    async def get_department_by_name(self, department_name: str):
        """Get a specific department by name"""
        query = f"SELECT * FROM {self.departments_table} WHERE department_name = $1"
        
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, department_name)
                if row:
                    dept = dict(row)
                    # Ensure admins is a proper list
                    if isinstance(dept.get('admins'), str):
                        import json
                        try:
                            dept['admins'] = json.loads(dept['admins'])
                        except (json.JSONDecodeError, TypeError):
                            dept['admins'] = []
                    elif dept.get('admins') is None:
                        dept['admins'] = []
                    return dept
                return None
        except Exception as e:
            log.error(f"Failed to get department '{department_name}': {e}")
            return None

    async def initialize_default_department(self, system_user: str = "SYSTEM"):
        """Initialize default 'General' department with default roles"""
        try:
            import json
            default_department = "General"
            default_roles = ["Admin", "Developer", "User"]
            
            async with self.pool.acquire() as conn:
                # Use UPSERT to always ensure General department exists with proper roles
                upsert_query = f"""
                INSERT INTO {self.departments_table} (department_name, created_by, roles)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (department_name) DO UPDATE SET 
                    roles = CASE 
                        WHEN {self.departments_table}.roles IS NULL OR {self.departments_table}.roles = '[]'::jsonb 
                        THEN $3::jsonb 
                        ELSE {self.departments_table}.roles 
                    END
                RETURNING department_name, (xmax = 0) as inserted
                """
                result = await conn.fetchrow(
                    upsert_query, 
                    default_department, 
                    system_user,
                    json.dumps(default_roles)
                )
                
                if result:
                    if result['inserted']:
                        log.info(f"Default department '{default_department}' created with roles: {default_roles}")
                    else:
                        log.info(f"Default department '{default_department}' already exists, ensured roles are set")
                    return True
                else:
                    log.error(f"Failed to initialize default department '{default_department}'")
                    return False
                
        except Exception as e:
            log.error(f"Failed to initialize default department: {e}")
            return False

    async def get_department_admins(self, department_name: str):
        """Get all admins for a specific department"""
        try:
            async with self.pool.acquire() as conn:
                query = f"SELECT admins FROM {self.departments_table} WHERE department_name = $1"
                result = await conn.fetchrow(query, department_name)
                
                if result:
                    return result['admins'] if result['admins'] else []
                else:
                    return []
                    
        except Exception as e:
            log.error(f"Failed to get department admins: {e}")
            return []

    async def add_role_to_department(self, department_name: str, role_name: str, added_by: str = None):
        """Add a role to a department's allowed roles list"""
        try:
            # Validate role name format - must start with capital letter
            if not role_name or not role_name[0].isupper():
                return {"success": False, "message": "Role name must start with a capital letter"}
            
            # Check if department exists
            if not await self.department_exists(department_name):
                return {"success": False, "message": f"Department '{department_name}' does not exist"}
            
            async with self.pool.acquire() as conn:
                # Get current roles
                check_query = f"SELECT roles FROM {self.departments_table} WHERE department_name = $1"
                result = await conn.fetchrow(check_query, department_name)
                
                if result:
                    roles_raw = result['roles']
                    # Handle JSONB data properly
                    if roles_raw is None:
                        current_roles = []
                    elif isinstance(roles_raw, str):
                        # If it's a string, parse it as JSON
                        import json
                        try:
                            current_roles = json.loads(roles_raw)
                        except (json.JSONDecodeError, TypeError):
                            current_roles = []
                    elif isinstance(roles_raw, list):
                        # If it's already a list, use it directly
                        current_roles = roles_raw
                    else:
                        # Fallback for other types
                        current_roles = []
                    
                    # Check if role already exists
                    if role_name in current_roles:
                        return {"success": False, "message": f"Role '{role_name}' is already allowed in department '{department_name}'"}
                    
                    # Add the role - use COALESCE to handle NULL roles
                    import json
                    update_query = f"""
                    UPDATE {self.departments_table} 
                    SET roles = COALESCE(roles, '[]'::jsonb) || $2::jsonb
                    WHERE department_name = $1
                    """
                    await conn.execute(update_query, department_name, json.dumps([role_name]))
                    
                    log.info(f"Added role '{role_name}' to department '{department_name}' by {added_by}")
                    return {"success": True, "message": f"Role '{role_name}' successfully added to department '{department_name}'"}
                else:
                    return {"success": False, "message": f"Department '{department_name}' not found"}
                
        except Exception as e:
            log.error(f"Failed to add role to department: {e}")
            return {"success": False, "message": f"Failed to add role: {str(e)}"}

    async def remove_role_from_department(self, department_name: str, role_name: str):
        """Remove a role from a department's allowed roles list"""
        try:
            async with self.pool.acquire() as conn:
                update_query = f"""
                UPDATE {self.departments_table} 
                SET roles = roles - $2
                WHERE department_name = $1
                """
                result = await conn.execute(update_query, department_name, role_name)
                
                if result:
                    log.info(f"Removed role '{role_name}' from department '{department_name}'")
                    return {"success": True, "message": f"Role '{role_name}' removed from department '{department_name}'"}
                else:
                    return {"success": False, "message": f"Failed to remove role '{role_name}' from department '{department_name}'"}
                    
        except Exception as e:
            log.error(f"Failed to remove role from department: {e}")
            return {"success": False, "message": f"Failed to remove role: {str(e)}"}

    async def get_department_roles(self, department_name: str):
        """Get all allowed roles for a department"""
        try:
            async with self.pool.acquire() as conn:
                query = f"SELECT roles FROM {self.departments_table} WHERE department_name = $1"
                result = await conn.fetchrow(query, department_name)
                
                if result:
                    roles_raw = result['roles']
                    # Handle JSONB data properly
                    if roles_raw is None:
                        roles = []
                    elif isinstance(roles_raw, str):
                        # If it's a string, parse it as JSON
                        import json
                        try:
                            roles = json.loads(roles_raw)
                        except (json.JSONDecodeError, TypeError):
                            roles = []
                    elif isinstance(roles_raw, list):
                        # If it's already a list, use it directly
                        roles = roles_raw
                    else:
                        # Fallback for other types
                        roles = []
                    
                    return {"success": True, "roles": roles}
                else:
                    return {"success": False, "message": f"Department '{department_name}' not found", "roles": []}
                
        except Exception as e:
            log.error(f"Failed to get department roles: {e}")
            return {"success": False, "message": f"Failed to get roles: {str(e)}", "roles": []}

    async def is_role_allowed_in_department(self, department_name: str, role_name: str) -> bool:
        """Check if a role is allowed in a department"""
        try:
            async with self.pool.acquire() as conn:
                query = f"SELECT roles FROM {self.departments_table} WHERE department_name = $1"
                result = await conn.fetchrow(query, department_name)
                
                if result:
                    roles_raw = result['roles']
                    # Handle JSONB data properly
                    if roles_raw is None:
                        roles = []
                    elif isinstance(roles_raw, str):
                        # If it's a string, parse it as JSON
                        import json
                        try:
                            roles = json.loads(roles_raw)
                        except (json.JSONDecodeError, TypeError):
                            roles = []
                    elif isinstance(roles_raw, list):
                        # If it's already a list, use it directly
                        roles = roles_raw
                    else:
                        # Fallback for other types
                        roles = []
                    
                    return role_name in roles
                return False
                
        except Exception as e:
            log.error(f"Failed to check role in department: {e}")
            return False

    async def initialize_default_department_roles(self, system_user: str = "SYSTEM"):
        """Initialize default roles for existing departments"""
        try:
            # Get all existing departments
            departments = await self.get_all_departments()
            
            # Default roles that should be available in all departments
            default_roles = ["Admin", "Developer", "User"]
            
            for dept in departments:
                department_name = dept['department_name']
                
                # Add default roles to each department if they don't exist
                for role in default_roles:
                    result = await self.add_role_to_department(department_name, role, system_user)
                    if result['success']:
                        log.info(f"Added default role '{role}' to department '{department_name}'")
                    elif "already allowed" in result['message']:
                        log.debug(f"Role '{role}' already exists in department '{department_name}'")
                    else:
                        log.warning(f"Failed to add role '{role}' to department '{department_name}': {result['message']}")
            
            log.info("Default department roles initialization completed")
            return True
            
        except Exception as e:
            log.error(f"Failed to initialize default department roles: {e}")
            return False

    async def cascade_delete_department_data(self, department_name: str, 
                                              main_pool=None, recycle_pool=None, 
                                              logs_pool=None, feedback_learning_pool=None) -> dict:
        """
        Delete all records related to a department from all databases.
        
        This method handles cascade delete from:
        LOGIN DB: userdepartmentmapping, role_access, user_access_keys
        MAIN DB: tool_table, mcp_tool_table, agent_table, tool_department_sharing, agent_department_sharing,
                 access_key_definitions, tool_access_key_mapping, groups, group_secrets, pipelines_table,
                 db_connections_table, public_keys, user_secrets, agent_evaluations, user_agent_access,
                 tag_tool_mapping_table, tag_agentic_app_mapping_table, tool_agent_mapping_table
                 + Dynamic tables: table_{agent_id} (chat history tables for each agent)
        RECYCLE DB: recycle_tool, recycle_mcp_tool, recycle_agent
        EVALUATION_LOGS DB: evaluation_data, tool_evaluation_metrics, agent_evaluation_metrics
                 + Dynamic tables: {agent_id} (consistency tables), robustness_{agent_id} (robustness tables)
        FEEDBACK_LEARNING DB: feedback_response
        
        Note: Tables with FK CASCADE (auto-deleted when parent is deleted):
        - agent_feedback (FK to feedback_response)
        
        Args:
            department_name: Name of the department to delete data for
            main_pool: Connection pool for MAIN database
            recycle_pool: Connection pool for RECYCLE database
            logs_pool: Connection pool for EVALUATION_LOGS database
            feedback_learning_pool: Connection pool for FEEDBACK_LEARNING database
            
        Returns:
            dict: Deletion statistics for each table
        """
        deletion_stats = {}
        agent_id_list = []  # Will be populated from agent_table for dropping dynamic tables
        
        try:
            # 1. DELETE FROM LOGIN DATABASE (self.pool)
            async with self.pool.acquire() as conn:
                # Delete user-department mappings first (FK constraint)
                result = await conn.execute(
                    "DELETE FROM userdepartmentmapping WHERE department_name = $1",
                    department_name
                )
                deletion_stats['userdepartmentmapping'] = result.split()[-1] if result else '0'
                
                # Delete role_access records for this department
                result = await conn.execute(
                    "DELETE FROM role_access WHERE department_name = $1",
                    department_name
                )
                deletion_stats['role_access'] = result.split()[-1] if result else '0'
                
                # Delete user_access_keys records for this department
                result = await conn.execute(
                    "DELETE FROM user_access_keys WHERE department_name = $1",
                    department_name
                )
                deletion_stats['user_access_keys'] = result.split()[-1] if result else '0'
            
            # 2. DELETE FROM MAIN DATABASE
            if main_pool:
                async with main_pool.acquire() as conn:
                    # FIRST: Get agent_ids BEFORE deleting them (needed for dropping dynamic tables)
                    agent_ids = await conn.fetch(
                        "SELECT agentic_application_id FROM agent_table WHERE department_name = $1",
                        department_name
                    )
                    agent_id_list = [row['agentic_application_id'] for row in agent_ids]
                    
                    # Delete tool_access_key_mapping (has department_name column)
                    result = await conn.execute(
                        "DELETE FROM tool_access_key_mapping WHERE department_name = $1",
                        department_name
                    )
                    deletion_stats['tool_access_key_mapping'] = result.split()[-1] if result else '0'
                    
                    # Delete access_key_definitions
                    result = await conn.execute(
                        "DELETE FROM access_key_definitions WHERE department_name = $1",
                        department_name
                    )
                    deletion_stats['access_key_definitions'] = result.split()[-1] if result else '0'
                    
                    # Delete tool_department_sharing (uses source_department and target_department)
                    result = await conn.execute(
                        "DELETE FROM tool_department_sharing WHERE source_department = $1 OR target_department = $1",
                        department_name
                    )
                    deletion_stats['tool_department_sharing'] = result.split()[-1] if result else '0'
                    
                    # Delete agent_department_sharing (uses source_department and target_department)
                    result = await conn.execute(
                        "DELETE FROM agent_department_sharing WHERE source_department = $1 OR target_department = $1",
                        department_name
                    )
                    deletion_stats['agent_department_sharing'] = result.split()[-1] if result else '0'
                    
                    # Delete group_secrets first (references groups)
                    result = await conn.execute(
                        "DELETE FROM group_secrets WHERE department_name = $1",
                        department_name
                    )
                    deletion_stats['group_secrets'] = result.split()[-1] if result else '0'
                    
                    # Delete groups
                    result = await conn.execute(
                        "DELETE FROM groups WHERE department_name = $1",
                        department_name
                    )
                    deletion_stats['groups'] = result.split()[-1] if result else '0'
                    
                    # Delete user_secrets
                    result = await conn.execute(
                        "DELETE FROM user_secrets WHERE department_name = $1",
                        department_name
                    )
                    deletion_stats['user_secrets'] = result.split()[-1] if result else '0'
                    
                    # Delete public_keys
                    result = await conn.execute(
                        "DELETE FROM public_keys WHERE department_name = $1",
                        department_name
                    )
                    deletion_stats['public_keys'] = result.split()[-1] if result else '0'
                    
                    # Delete db_connections_table
                    result = await conn.execute(
                        "DELETE FROM db_connections_table WHERE department_name = $1",
                        department_name
                    )
                    deletion_stats['db_connections_table'] = result.split()[-1] if result else '0'
                    
                    # Delete pipelines_table
                    result = await conn.execute(
                        "DELETE FROM pipelines_table WHERE department_name = $1",
                        department_name
                    )
                    deletion_stats['pipelines_table'] = result.split()[-1] if result else '0'
                    
                    # FIRST: Get tool_ids from both tool_table and mcp_tool_table (needed for tag_tool_mapping_table)
                    tool_ids = await conn.fetch(
                        "SELECT tool_id FROM tool_table WHERE department_name = $1",
                        department_name
                    )
                    mcp_tool_ids = await conn.fetch(
                        "SELECT tool_id FROM mcp_tool_table WHERE department_name = $1",
                        department_name
                    )
                    all_tool_ids = [row['tool_id'] for row in tool_ids] + [row['tool_id'] for row in mcp_tool_ids]
                    
                    # Delete tag_tool_mapping_table entries for these tools (no FK, needs manual deletion)
                    if all_tool_ids:
                        result = await conn.execute(
                            "DELETE FROM tag_tool_mapping_table WHERE tool_id = ANY($1)",
                            all_tool_ids
                        )
                        deletion_stats['tag_tool_mapping_table'] = result.split()[-1] if result else '0'
                    else:
                        deletion_stats['tag_tool_mapping_table'] = '0'
                    
                    # Delete tool_table
                    result = await conn.execute(
                        "DELETE FROM tool_table WHERE department_name = $1",
                        department_name
                    )
                    deletion_stats['tool_table'] = result.split()[-1] if result else '0'
                    
                    # Delete mcp_tool_table
                    result = await conn.execute(
                        "DELETE FROM mcp_tool_table WHERE department_name = $1",
                        department_name
                    )
                    deletion_stats['mcp_tool_table'] = result.split()[-1] if result else '0'
                    
                    # Delete tag_agentic_app_mapping_table entries for agents (manual deletion)
                    if agent_id_list:
                        result = await conn.execute(
                            "DELETE FROM tag_agentic_app_mapping_table WHERE agentic_application_id = ANY($1)",
                            agent_id_list
                        )
                        deletion_stats['tag_agentic_app_mapping_table'] = result.split()[-1] if result else '0'
                    else:
                        deletion_stats['tag_agentic_app_mapping_table'] = '0'
                    
                    # Delete tool_agent_mapping_table entries for agents (manual deletion)
                    if agent_id_list:
                        result = await conn.execute(
                            "DELETE FROM tool_agent_mapping_table WHERE agentic_application_id = ANY($1)",
                            agent_id_list
                        )
                        deletion_stats['tool_agent_mapping_table'] = result.split()[-1] if result else '0'
                    else:
                        deletion_stats['tool_agent_mapping_table'] = '0'
                    
                    # Delete agent_table
                    result = await conn.execute(
                        "DELETE FROM agent_table WHERE department_name = $1",
                        department_name
                    )
                    deletion_stats['agent_table'] = result.split()[-1] if result else '0'
                    
                    
                    # Drop dynamic chat history tables for each deleted agent (table_{agent_id})
                    dropped_chat_tables = 0
                    for agent_id in agent_id_list:
                        safe_table_name = f"table_{agent_id.replace('-', '_')}"
                        try:
                            await conn.execute(f'DROP TABLE IF EXISTS "{safe_table_name}" CASCADE')
                            dropped_chat_tables += 1
                        except Exception as e:
                            log.warning(f"Could not drop chat table '{safe_table_name}': {e}")
                    deletion_stats['dynamic_chat_tables'] = str(dropped_chat_tables)
            
            # 3. DELETE FROM RECYCLE DATABASE
            if recycle_pool:
                async with recycle_pool.acquire() as conn:
                    # Delete recycle_tool
                    result = await conn.execute(
                        "DELETE FROM recycle_tool WHERE department_name = $1",
                        department_name
                    )
                    deletion_stats['recycle_tool'] = result.split()[-1] if result else '0'
                    
                    # Delete recycle_mcp_tool
                    result = await conn.execute(
                        "DELETE FROM recycle_mcp_tool WHERE department_name = $1",
                        department_name
                    )
                    deletion_stats['recycle_mcp_tool'] = result.split()[-1] if result else '0'
                    
                    # Delete recycle_agent
                    result = await conn.execute(
                        "DELETE FROM recycle_agent WHERE department_name = $1",
                        department_name
                    )
                    deletion_stats['recycle_agent'] = result.split()[-1] if result else '0'
            
            # 4. DELETE FROM EVALUATION_LOGS DATABASE
            if logs_pool:
                async with logs_pool.acquire() as conn:
                    # Delete evaluation_data
                    result = await conn.execute(
                        "DELETE FROM evaluation_data WHERE department_name = $1",
                        department_name
                    )
                    deletion_stats['evaluation_data'] = result.split()[-1] if result else '0'
                    
                    # Delete tool_evaluation_metrics
                    result = await conn.execute(
                        "DELETE FROM tool_evaluation_metrics WHERE department_name = $1",
                        department_name
                    )
                    deletion_stats['tool_evaluation_metrics'] = result.split()[-1] if result else '0'
                    
                    # Delete agent_evaluation_metrics
                    result = await conn.execute(
                        "DELETE FROM agent_evaluation_metrics WHERE department_name = $1",
                        department_name
                    )
                    deletion_stats['agent_evaluation_metrics'] = result.split()[-1] if result else '0'
                    
                    # Drop dynamic consistency and robustness tables for each deleted agent
                    # These tables are named: {agent_id} (consistency) and robustness_{agent_id}
                    dropped_consistency_tables = 0
                    dropped_robustness_tables = 0
                    for agent_id in agent_id_list:
                        safe_agent_id = agent_id.replace('-', '_')
                        
                        # Drop consistency table (named same as agent_id)
                        try:
                            await conn.execute(f'DROP TABLE IF EXISTS "{safe_agent_id}" CASCADE')
                            dropped_consistency_tables += 1
                        except Exception as e:
                            log.warning(f"Could not drop consistency table '{safe_agent_id}': {e}")
                        
                        # Drop robustness table
                        robustness_table = f"robustness_{safe_agent_id}"
                        try:
                            await conn.execute(f'DROP TABLE IF EXISTS "{robustness_table}" CASCADE')
                            dropped_robustness_tables += 1
                        except Exception as e:
                            log.warning(f"Could not drop robustness table '{robustness_table}': {e}")
                    
                    deletion_stats['dynamic_consistency_tables'] = str(dropped_consistency_tables)
                    deletion_stats['dynamic_robustness_tables'] = str(dropped_robustness_tables)
            
            # 5. DELETE FROM FEEDBACK_LEARNING DATABASE
            if feedback_learning_pool:
                async with feedback_learning_pool.acquire() as conn:
                    # Delete feedback_response
                    result = await conn.execute(
                        "DELETE FROM feedback_response WHERE department_name = $1",
                        department_name
                    )
                    deletion_stats['feedback_response'] = result.split()[-1] if result else '0'
            
            log.info(f"Cascade delete completed for department '{department_name}'. Stats: {deletion_stats}")
            return deletion_stats
            
        except Exception as e:
            log.error(f"Error during cascade delete for department '{department_name}': {e}")
            raise


class UserAccessKeyRepository:
    """
    Repository for managing user access keys.
    
    This table stores what resource values each user can access.
    Tool creators use @resource_access decorator with access_key,
    and department admins assign allowed values to users here.
    
    Example:
        User "john@company.com" has:
        - access_key: "employees", allowed_values: ["EMP001", "EMP002"]
        - access_key: "projects", allowed_values: ["*"]  (wildcard = all)
    """

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.table_name = "user_access_keys"

    async def create_table_if_not_exists(self):
        """Create user_access_keys table if it doesn't exist"""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(255) NOT NULL,
            access_key VARCHAR(100) NOT NULL,
            allowed_values TEXT[] NOT NULL DEFAULT '{{}}',
            excluded_values TEXT[] NOT NULL DEFAULT '{{}}',
            department_name VARCHAR(255) DEFAULT 'General',
            assigned_by VARCHAR(255),
            assigned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, access_key, department_name)
        );
        
        CREATE INDEX IF NOT EXISTS idx_user_access_keys_user_id 
        ON {self.table_name}(user_id);
        
        CREATE INDEX IF NOT EXISTS idx_user_access_keys_access_key 
        ON {self.table_name}(access_key);
        
        CREATE INDEX IF NOT EXISTS idx_user_access_keys_department 
        ON {self.table_name}(department_name);
        """
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
            log.info(f"Table '{self.table_name}' created or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            raise

    async def get_user_access_keys(self, user_id: str, department_name: str = None) -> Dict[str, List[str]]:
        """
        Get all access keys and their allowed values for a user.
        
        Args:
            user_id: The user's email/ID
            department_name: Optional department filter
            
        Returns:
            Dict mapping access_key to list of allowed values
            Example: {"employees": ["EMP001", "EMP002"], "projects": ["*"]}
        """
        if department_name:
            query = f"""
            SELECT access_key, allowed_values, excluded_values
            FROM {self.table_name} 
            WHERE user_id = $1 AND department_name = $2
            """
            params = (user_id, department_name)
        else:
            query = f"""
            SELECT access_key, allowed_values, excluded_values
            FROM {self.table_name} 
            WHERE user_id = $1
            """
            params = (user_id,)
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
                return {row['access_key']: list(row['allowed_values']) for row in rows}
        except Exception as e:
            log.error(f"Error fetching access keys for user {user_id}: {e}")
            return {}

    async def get_user_excluded_values(self, user_id: str, department_name: str = None) -> Dict[str, List[str]]:
        """
        Get all access keys and their excluded values for a user.
        
        Args:
            user_id: The user's email/ID
            department_name: Optional department filter
            
        Returns:
            Dict mapping access_key to list of excluded values
            Example: {"employees": ["CEO001", "CFO001"]}
        """
        if department_name:
            query = f"""
            SELECT access_key, excluded_values 
            FROM {self.table_name} 
            WHERE user_id = $1 AND department_name = $2
            """
            params = (user_id, department_name)
        else:
            query = f"""
            SELECT access_key, excluded_values 
            FROM {self.table_name} 
            WHERE user_id = $1
            """
            params = (user_id,)
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
                return {row['access_key']: list(row['excluded_values']) for row in rows}
        except Exception as e:
            log.error(f"Error fetching excluded values for user {user_id}: {e}")
            return {}

    async def get_user_access_keys_full(self, user_id: str, department_name: str = None) -> Dict[str, Dict[str, List[str]]]:
        """
        Get all access keys with both allowed and excluded values for a user.
        
        Args:
            user_id: The user's email/ID
            department_name: Optional department filter
            
        Returns:
            Dict mapping access_key to {"allowed": [...], "excluded": [...]}
        """
        if department_name:
            query = f"""
            SELECT access_key, allowed_values, excluded_values 
            FROM {self.table_name} 
            WHERE user_id = $1 AND department_name = $2
            """
            params = (user_id, department_name)
        else:
            query = f"""
            SELECT access_key, allowed_values, excluded_values 
            FROM {self.table_name} 
            WHERE user_id = $1
            """
            params = (user_id,)
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
                return {
                    row['access_key']: {
                        "allowed": list(row['allowed_values']),
                        "excluded": list(row['excluded_values']) if row['excluded_values'] else []
                    }
                    for row in rows
                }
        except Exception as e:
            log.error(f"Error fetching full access keys for user {user_id}: {e}")
            return {}

    async def set_user_access_key(
        self, 
        user_id: str, 
        access_key: str, 
        allowed_values: List[str],
        assigned_by: str = None,
        department_name: str = None
    ) -> bool:
        """
        Set or update access key values for a user.
        
        Args:
            user_id: The user's email/ID
            access_key: Resource type (e.g., "employees", "projects")
            allowed_values: List of allowed values (use ["*"] for all access)
            assigned_by: Who is assigning this access
            department_name: The department this access key belongs to
            
        Returns:
            bool: True if successful
        """
        query = f"""
        INSERT INTO {self.table_name} (user_id, access_key, allowed_values, assigned_by, department_name, updated_at)
        VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
        ON CONFLICT (user_id, access_key, department_name) 
        DO UPDATE SET 
            allowed_values = $3,
            assigned_by = $4,
            updated_at = CURRENT_TIMESTAMP
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, user_id, access_key, allowed_values, assigned_by, department_name)
            log.info(f"Set access key '{access_key}' for user {user_id} in department {department_name}: {allowed_values}")
            return True
        except Exception as e:
            log.error(f"Error setting access key for user {user_id}: {e}")
            return False

    async def add_value_to_access_key(
        self,
        user_id: str,
        access_key: str,
        value: str,
        assigned_by: str = None,
        department_name: str = None
    ) -> bool:
        """
        Add a single value to user's access key (append if key exists).
        
        Args:
            user_id: The user's email/ID
            access_key: Resource type
            value: Value to add
            assigned_by: Who is adding this access
            department_name: The department this access key belongs to
        """
        query = f"""
        INSERT INTO {self.table_name} (user_id, access_key, allowed_values, assigned_by, department_name, updated_at)
        VALUES ($1, $2, ARRAY[$3], $4, $5, CURRENT_TIMESTAMP)
        ON CONFLICT (user_id, access_key, department_name) 
        DO UPDATE SET 
            allowed_values = array_append(
                array_remove({self.table_name}.allowed_values, $3), 
                $3
            ),
            assigned_by = $4,
            updated_at = CURRENT_TIMESTAMP
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, user_id, access_key, value, assigned_by, department_name)
            log.info(f"Added '{value}' to access key '{access_key}' for user {user_id} in department {department_name}")
            return True
        except Exception as e:
            log.error(f"Error adding value to access key for user {user_id}: {e}")
            return False

    async def remove_value_from_access_key(
        self,
        user_id: str,
        access_key: str,
        value: str,
        department_name: str = None
    ) -> bool:
        """Remove a single value from user's access key."""
        if department_name:
            query = f"""
            UPDATE {self.table_name}
            SET allowed_values = array_remove(allowed_values, $3),
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = $1 AND access_key = $2 AND department_name = $4
            """
            params = (user_id, access_key, value, department_name)
        else:
            query = f"""
            UPDATE {self.table_name}
            SET allowed_values = array_remove(allowed_values, $3),
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = $1 AND access_key = $2
            """
            params = (user_id, access_key, value)
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, *params)
            log.info(f"Removed '{value}' from access key '{access_key}' for user {user_id}")
            return True
        except Exception as e:
            log.error(f"Error removing value from access key for user {user_id}: {e}")
            return False

    async def add_excluded_value(
        self,
        user_id: str,
        access_key: str,
        value: str,
        assigned_by: str = None,
        department_name: str = None
    ) -> bool:
        """
        Add a value to user's exclusion list for an access key.
        
        Args:
            user_id: The user's email/ID
            access_key: Resource type
            value: Value to exclude
            assigned_by: Who is adding this exclusion
            department_name: The department this access key belongs to
        """
        query = f"""
        INSERT INTO {self.table_name} (user_id, access_key, allowed_values, excluded_values, assigned_by, department_name, updated_at)
        VALUES ($1, $2, '{{}}', ARRAY[$3], $4, $5, CURRENT_TIMESTAMP)
        ON CONFLICT (user_id, access_key, department_name) 
        DO UPDATE SET 
            excluded_values = array_append(
                array_remove({self.table_name}.excluded_values, $3), 
                $3
            ),
            assigned_by = $4,
            updated_at = CURRENT_TIMESTAMP
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, user_id, access_key, value, assigned_by, department_name)
            log.info(f"Added '{value}' to exclusions for access key '{access_key}' for user {user_id} in department {department_name}")
            return True
        except Exception as e:
            log.error(f"Error adding excluded value for user {user_id}: {e}")
            return False

    async def remove_excluded_value(
        self,
        user_id: str,
        access_key: str,
        value: str,
        department_name: str = None
    ) -> bool:
        """Remove a single value from user's exclusion list."""
        if department_name:
            query = f"""
            UPDATE {self.table_name}
            SET excluded_values = array_remove(excluded_values, $3),
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = $1 AND access_key = $2 AND department_name = $4
            """
            params = (user_id, access_key, value, department_name)
        else:
            query = f"""
            UPDATE {self.table_name}
            SET excluded_values = array_remove(excluded_values, $3),
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = $1 AND access_key = $2
            """
            params = (user_id, access_key, value)
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, *params)
            log.info(f"Removed '{value}' from exclusions for access key '{access_key}' for user {user_id}")
            return True
        except Exception as e:
            log.error(f"Error removing excluded value for user {user_id}: {e}")
            return False

    async def set_excluded_values(
        self,
        user_id: str,
        access_key: str,
        excluded_values: List[str],
        assigned_by: str = None,
        department_name: str = None
    ) -> bool:
        """
        Set/replace all excluded values for a user's access key.
        
        Args:
            user_id: The user's email/ID
            access_key: Resource type
            excluded_values: List of values to exclude
            assigned_by: Who is setting this exclusion
            department_name: The department this access key belongs to
        """
        query = f"""
        INSERT INTO {self.table_name} (user_id, access_key, allowed_values, excluded_values, assigned_by, department_name, updated_at)
        VALUES ($1, $2, '{{}}', $3, $4, $5, CURRENT_TIMESTAMP)
        ON CONFLICT (user_id, access_key, department_name) 
        DO UPDATE SET 
            excluded_values = $3,
            assigned_by = $4,
            updated_at = CURRENT_TIMESTAMP
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, user_id, access_key, excluded_values, assigned_by, department_name)
            log.info(f"Set exclusions for access key '{access_key}' for user {user_id} in department {department_name}: {excluded_values}")
            return True
        except Exception as e:
            log.error(f"Error setting excluded values for user {user_id}: {e}")
            return False

    async def delete_access_key(self, user_id: str, access_key: str, department_name: str = None) -> bool:
        """Remove entire access key for a user."""
        if department_name:
            query = f"DELETE FROM {self.table_name} WHERE user_id = $1 AND access_key = $2 AND department_name = $3"
            params = (user_id, access_key, department_name)
        else:
            query = f"DELETE FROM {self.table_name} WHERE user_id = $1 AND access_key = $2"
            params = (user_id, access_key)
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, *params)
            log.info(f"Deleted access key '{access_key}' for user {user_id}")
            return True
        except Exception as e:
            log.error(f"Error deleting access key for user {user_id}: {e}")
            return False

    async def get_users_with_access_key(self, access_key: str, department_name: str = None) -> List[Dict]:
        """Get all users who have a specific access key with both allowed and excluded values."""
        if department_name:
            query = f"""
            SELECT user_id, allowed_values, excluded_values, department_name
            FROM {self.table_name} 
            WHERE access_key = $1 AND department_name = $2
            """
            params = (access_key, department_name)
        else:
            query = f"""
            SELECT user_id, allowed_values, excluded_values, department_name
            FROM {self.table_name} 
            WHERE access_key = $1
            """
            params = (access_key,)
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
                return [
                    {
                        "user_id": row["user_id"],
                        "allowed_values": list(row["allowed_values"]) if row["allowed_values"] else [],
                        "excluded_values": list(row["excluded_values"]) if row["excluded_values"] else [],
                        "department_name": row["department_name"]
                    }
                    for row in rows
                ]
        except Exception as e:
            log.error(f"Error fetching users with access key {access_key}: {e}")
            return []

    async def check_user_access(self, user_id: str, access_key: str, value: str) -> bool:
        """
        Quick check if user has access to a specific value.
        Exclusions take priority over allowed values.
        
        Args:
            user_id: The user's email/ID
            access_key: Resource type
            value: Value to check
            
        Returns:
            bool: True if user has access (either specific value or wildcard) AND not excluded
        """
        query = f"""
        SELECT 1 FROM {self.table_name}
        WHERE user_id = $1 
        AND access_key = $2
        AND ($3 = ANY(allowed_values) OR '*' = ANY(allowed_values))
        AND NOT ($3 = ANY(excluded_values))
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchrow(query, user_id, access_key, value)
                return result is not None
        except Exception as e:
            log.error(f"Error checking access for user {user_id}: {e}")
            return False

    async def delete_all_for_access_key(self, access_key: str, department_name: str = None) -> int:
        """
        Delete all user entries for a specific access key within a department.
        
        This is used when an access key definition is deleted to clean up
        all user assignments for that key in the department.
        
        Args:
            access_key: The access key to remove from all users
            department_name: The department to filter by
            
        Returns:
            int: Number of user entries deleted
        """
        if department_name:
            query = f"DELETE FROM {self.table_name} WHERE access_key = $1 AND department_name = $2"
            params = (access_key, department_name)
        else:
            query = f"DELETE FROM {self.table_name} WHERE access_key = $1"
            params = (access_key,)
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, *params)
                # Parse result like "DELETE 5" to get count
                deleted_count = int(result.split()[-1]) if result else 0
            log.info(f"Deleted {deleted_count} user entries for access key '{access_key}' in department '{department_name}'")
            return deleted_count
        except Exception as e:
            log.error(f"Error deleting all user entries for access key '{access_key}': {e}")
            return 0