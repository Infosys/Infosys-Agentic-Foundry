# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import json
import asyncio
from typing import Dict, Optional, Any
from cryptography.fernet import Fernet
import psycopg2
from psycopg2.extras import RealDictCursor
import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
from telemetry_wrapper import logger as log

current_user_email: ContextVar[str] = ContextVar("current_user_email")
current_user_department:  ContextVar[str] = ContextVar("current_user_department")
current_user_role : ContextVar[str] = ContextVar("current_user_role")

class PublicKeysManager:
    """
    Manages encrypted public keys accessible to all users
    """
    
    def __init__(self, db_config: Dict[str, str], master_key: Optional[str] = None):
        self.db_config = db_config
        # Use master key from environment or generate one
        self.master_key = master_key or os.getenv('SECRETS_MASTER_KEY')
        if not self.master_key:
            raise ValueError("SECRETS_MASTER_KEY must be set in environment")
        
        self.cipher_suite = Fernet(self.master_key.encode()[:44].ljust(44, b'='))
        self._init_database()
    
    def _init_database(self):
        """Initialize the public keys table"""
        with self._get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS public_keys (
                        id SERIAL PRIMARY KEY,
                        key_name VARCHAR(100) NOT NULL,
                        encrypted_value TEXT NOT NULL,
                        description TEXT,
                        department_name TEXT DEFAULT 'General',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        created_by VARCHAR(255),
                        UNIQUE(key_name, department_name)
                    );
                    
                    CREATE INDEX IF NOT EXISTS idx_public_keys_name 
                    ON public_keys(key_name);
                """)
                
                # Add department_name column if it doesn't exist (for existing tables)
                try:
                    cur.execute("ALTER TABLE public_keys ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General';")
                except Exception as e:
                    # Column may already exist, ignore the error
                    pass
                
                # Drop old unique constraint if it exists and add new one
                try:
                    cur.execute("ALTER TABLE public_keys DROP CONSTRAINT IF EXISTS public_keys_key_name_key;")
                    cur.execute("ALTER TABLE public_keys ADD CONSTRAINT unique_key_department UNIQUE (key_name, department_name);")
                except Exception as e:
                    # Constraint may not exist or already be correct, ignore the error
                    pass
                
                conn.commit()
    
    @contextmanager
    def _get_db_connection(self):
        """Database connection context manager"""
        conn = psycopg2.connect(**self.db_config)
        try:
            yield conn
        finally:
            conn.close()
    
    def _encrypt_value(self, value: str) -> str:
        """Encrypt a key value"""
        return self.cipher_suite.encrypt(value.encode()).decode()
    
    def _decrypt_value(self, encrypted_value: str) -> str:
        """Decrypt a key value"""
        return self.cipher_suite.decrypt(encrypted_value.encode()).decode()
    
    def create_public_key(self, key_name: str, key_value: str, description: str = None, created_by: str = None, department_name: str = None) -> bool:
        """
        Create a new encrypted public key
        
        Args:
            key_name: Name of the public key (e.g., 'shared_api_key', 'common_token')
            key_value: The actual key value
            description: Optional description of the key
            created_by: Email of the user who created this key
            department_name: Department name for the key (optional)
            
        Returns:
            bool: Success status
            
        Raises:
            ValueError: If public key already exists for the department
        """
        try:
            encrypted_value = self._encrypt_value(key_value)
            
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO public_keys (key_name, encrypted_value, description, created_by, department_name)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (key_name, encrypted_value, description, created_by, department_name))
                    conn.commit()
            return True
        except Exception as e:
            # Check if it's a duplicate key error
            if "duplicate key" in str(e).lower() or "unique constraint" in str(e).lower():
                dept_info = f" in department '{department_name}'" if department_name else ""
                raise ValueError(f"Public key '{key_name}' already exists{dept_info}")
            log.error(f"Error creating public key: {e}")
            return False

    def update_public_key(self, key_name: str, key_value: str, description: str = None, updated_by: str = None, department_name: str = None) -> bool:
        """
        Update an existing encrypted public key
        
        Args:
            key_name: Name of the public key (e.g., 'shared_api_key', 'common_token')
            key_value: The new key value
            description: Optional description of the key
            updated_by: Email of the user who updated this key
            department_name: Department name for the key (optional)
            
        Returns:
            bool: Success status
            
        Raises:
            ValueError: If public key doesn't exist for the department
        """
        try:
            encrypted_value = self._encrypt_value(key_value)
            
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    # Build dynamic query based on provided parameters
                    update_fields = ["encrypted_value = %s", "updated_at = CURRENT_TIMESTAMP"]
                    params = [encrypted_value]
                    
                    if description is not None:
                        update_fields.append("description = %s")
                        params.append(description)
                    
                    
                    params.extend([key_name, department_name, department_name])  # For WHERE clause
                    
                    cur.execute(f"""
                        UPDATE public_keys 
                        SET {', '.join(update_fields)}
                        WHERE key_name = %s AND 
                              (department_name = %s OR (department_name IS NULL AND %s IS NULL))
                    """, params)
                    
                    if cur.rowcount == 0:
                        dept_info = f" in department '{department_name}'" if department_name else ""
                        raise ValueError(f"Public key '{key_name}' not found{dept_info}")
                        
                    conn.commit()
            return True
        except ValueError:
            # Re-raise ValueError as is
            raise
        except Exception as e:
            log.error(f"Error updating public key: {e}")
            return False
        
    def get_public_key(self, key_name: str, department_name: str = None) -> Optional[str]:
        """
        Retrieve and decrypt a public key
        
        Args:
            key_name: Name of the public key
            department_name: Department name for the key (optional)
            
        Returns:
            Optional[str]: Decrypted key value or None if not found
        """
        try:
            with self._get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT encrypted_value 
                        FROM public_keys 
                        WHERE key_name = %s AND 
                              (department_name = %s OR (department_name IS NULL AND %s IS NULL))
                    """, (key_name, department_name, department_name))
                    
                    result = cur.fetchone()
                    if result:
                        return self._decrypt_value(result['encrypted_value'])
            return None
        except Exception as e:
            log.error(f"Error retrieving public key: {e}")
            return None
    
    def get_public_keys(self, key_names: Optional[list] = None, department_name: str = None) -> Dict[str, str]:
        """
        Get multiple public keys
        
        Args:
            key_names: Optional list of specific key names to retrieve
            department_name: Department name to filter keys (optional)
            
        Returns:
            Dict[str, str]: Dictionary of key_name -> decrypted_value
        """
        keys = {}
        
        try:
            with self._get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    if key_names:
                        placeholders = ','.join(['%s'] * len(key_names))
                        cur.execute(f"""
                            SELECT key_name, encrypted_value 
                            FROM public_keys 
                            WHERE key_name IN ({placeholders}) AND 
                                  (department_name = %s OR (department_name IS NULL AND %s IS NULL))
                        """, key_names + [department_name, department_name])
                    else:
                        cur.execute("""
                            SELECT key_name, encrypted_value 
                            FROM public_keys
                            WHERE (department_name = %s OR (department_name IS NULL AND %s IS NULL))
                        """, (department_name, department_name))
                    
                    results = cur.fetchall()
                    for row in results:
                        try:
                            keys[row['key_name']] = self._decrypt_value(row['encrypted_value'])
                        except Exception as decrypt_error:
                            log.error(f"Error decrypting {row['key_name']}: {decrypt_error}")
                            continue
                            
        except Exception as e:
            log.error(f"Error retrieving public keys: {e}")
        
        return keys
    
    def delete_public_key(self, key_name: str, department_name: str = None) -> bool:
        """Delete a specific public key"""
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        DELETE FROM public_keys 
                        WHERE key_name = %s AND 
                              (department_name = %s OR (department_name IS NULL AND %s IS NULL))
                    """, (key_name, department_name, department_name))
                    conn.commit()
                    return cur.rowcount > 0
        except Exception as e:
            log.error(f"Error deleting public key: {e}")
            return False
    
    def list_public_key_names(self, department_name: str = None) -> list:
        """List all public key names (without values)"""
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT key_name, description, created_by, created_at, department_name
                        FROM public_keys 
                        WHERE (department_name = %s OR (department_name IS NULL AND %s IS NULL))
                        ORDER BY key_name
                    """, (department_name, department_name))
                    return [{'name': row[0], 'description': row[1], 'created_by': row[2], 'created_at': row[3], 'department': row[4]} for row in cur.fetchall()]
        except Exception as e:
            log.error(f"Error listing public keys: {e}")
            return []


class UserSecretsManager:
    """
    Manages encrypted user secrets with database storage
    """
    
    def __init__(self, db_config: Dict[str, str], master_key: Optional[str] = None):
        self.db_config = db_config
        # Use master key from environment or generate one
        self.master_key = master_key or os.getenv('SECRETS_MASTER_KEY')
        if not self.master_key:
            raise ValueError("SECRETS_MASTER_KEY must be set in environment")
        
        self.cipher_suite = Fernet(self.master_key.encode()[:44].ljust(44, b'='))
        
        self._init_database()
    
    def _get_user_role_sync(self, user_email: str, department_name: str) -> Optional[str]:
        """Get user role from user_email using direct database query"""
        try:
            with self._get_login_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT role FROM userdepartmentmapping WHERE mail_id = %s AND department_name = %s
                    """, (user_email,department_name))
                    result = cur.fetchone()
                    return result['role'] if result else None
        except Exception as e:
            log.error(f"Error getting user role for {user_email}: {e}")
            return None
    
    def _check_vault_access_sync(self, role: str, department_name: str) -> bool:
        """Check if user has access to vault/secrets endpoints using direct database query
        
        Args:
            role: Role name of the user
            department_name: Department name (defaults to "General")
            
        Returns:
            bool: True if user can access vault endpoints, False otherwise
        """
        try:
            # SuperAdmin bypass - no permission checks needed
            if role == 'SuperAdmin':
                log.info(f"SuperAdmin bypass - granted vault access without permission check")
                return True
            
            # Get role permissions from role_access table for the specific department
            with self._get_login_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT vault_access FROM role_access 
                        WHERE department_name = %s AND role_name = %s
                    """, (department_name, role))
                    result = cur.fetchone()
                    
                    if not result:
                        log.warning(f"No permissions found for role '{role}' in department '{department_name}'")
                        return False
                    
                    # Get vault_access permission
                    vault_access = result.get('vault_access', False)
                    
                    log.info(f"Role '{role}' in department '{department_name}' vault access: {vault_access}")
                    return vault_access
                    
        except Exception as e:
            log.error(f"Vault access check error for role '{role}': {e}")
            return False
    
    def _init_database(self):
        """Initialize the user secrets table"""
        with self._get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_secrets (
                        id SERIAL PRIMARY KEY,
                        user_email VARCHAR(255) NOT NULL,
                        secret_name VARCHAR(100) NOT NULL,
                        encrypted_value TEXT NOT NULL,
                        department_name TEXT DEFAULT 'General',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(user_email, secret_name, department_name)
                    );
                    
                    CREATE INDEX IF NOT EXISTS idx_user_secrets_email 
                    ON user_secrets(user_email);
                    
                """)
                
                # Add department_name column if it doesn't exist (for existing tables)
                try:
                    cur.execute("ALTER TABLE user_secrets ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General';")
                except Exception as e:
                    # Column may already exist, ignore the error
                    pass
                
                # Drop old unique constraint if it exists and add new one
                try:
                    cur.execute("ALTER TABLE user_secrets DROP CONSTRAINT IF EXISTS user_secrets_user_email_secret_name_key;")
                    cur.execute("ALTER TABLE user_secrets ADD CONSTRAINT unique_user_secret_department UNIQUE (user_email, secret_name, department_name);")
                except Exception as e:
                    # Constraint may not exist or already be correct, ignore the error
                    pass
                
                conn.commit()
    
    @contextmanager
    def _get_db_connection(self):
        """Database connection context manager"""
        conn = psycopg2.connect(**self.db_config)
        try:
            yield conn
        finally:
            conn.close()
    
    @contextmanager
    def _get_login_db_connection(self):
        """Get database connection for login database to check user roles and permissions"""
        conn = None
        try:
            # Create login database config by copying main config and changing database name
            login_db_config = self.db_config.copy()
            login_db_config['database'] = os.getenv('LOGIN_DB_NAME', 'login')  # Dynamically get login database name
            
            conn = psycopg2.connect(**login_db_config)
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if conn:
                conn.close()
    
    def _encrypt_value(self, value: str) -> str:
        """Encrypt a secret_data value"""
        return self.cipher_suite.encrypt(value.encode()).decode()
    
    def _decrypt_value(self, encrypted_value: str) -> str:
        """Decrypt a secret_data value"""
        return self.cipher_suite.decrypt(encrypted_value.encode()).decode()
    
    def create_user_secret(self, user_email: str, key_name: str, key_value: str, department_name: str = None) -> bool:
        """
        Create a new encrypted secret_data for a user
        
        Args:
            user_email: User's email (unique identifier)
            key_name: Name of the secret_record (e.g., 'notion_token', 'openai_key')
            key_value: The actual secret_value
            department_name: Department name for the secret_record (optional)
            
        Returns:
            bool: Success status
            
        Raises:
            ValueError: If secret_record already exists for this user and department
        """
        try:
            encrypted_value = self._encrypt_value(key_value)
            
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO user_secrets (user_email, secret_name, encrypted_value, department_name)
                        VALUES (%s, %s, %s, %s)
                    """, (user_email, key_name, encrypted_value, department_name))
                    conn.commit()
            return True
        except Exception as e:
            # Check if it's a duplicate key error
            if "duplicate key" in str(e).lower() or "unique constraint" in str(e).lower():
                dept_info = f" and department '{department_name}'" if department_name else ""
                raise ValueError(f"Secret '{key_name}' already exists for user '{user_email}'{dept_info}")
            log.error(f"Error creating secret: {e}")
            return False

    def update_user_secret(self, user_email: str, key_name: str, key_value: str, department_name: str = None) -> bool:
        """
        Update an existing encrypted secret_data for a user
        
        Args:
            user_email: User's email (unique identifier)
            key_name: Name of the secret_record (e.g., 'notion_token', 'openai_key')
            key_value: The new secret_value
            department_name: Department name for the secret_record (optional)
            
        Returns:
            bool: Success status
            
        Raises:
            ValueError: If secret_record doesn't exist for this user and department
        """
        try:
            encrypted_value = self._encrypt_value(key_value)
            
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE user_secrets 
                        SET encrypted_value = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE user_email = %s AND secret_name = %s AND 
                              (department_name = %s OR (department_name IS NULL AND %s IS NULL))
                    """, (encrypted_value, user_email, key_name, department_name, department_name))
                    
                    if cur.rowcount == 0:
                        dept_info = f" and department '{department_name}'" if department_name else ""
                        raise ValueError(f"Secret '{key_name}' not found for user '{user_email}'{dept_info}")
                        
                    conn.commit()
            return True
        except ValueError:
            # Re-raise ValueError as is
            raise
        except Exception as e:
            log.error(f"Error updating secret: {e}")
            return False
    
    def get_user_secret(self, user_email: str, key_name: str, department_name: str = None) -> Optional[str]:
        """
        Retrieve and decrypt a user's secret_data
        
        Args:
            user_email: User's email
            key_name: Name of the secret_record
            department_name: Department name for the secret_record (optional)
            
        Returns:
            Optional[str]: Decrypted secret_data value or None if not found
        """
        try:
            with self._get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT encrypted_value 
                        FROM user_secrets 
                        WHERE user_email = %s AND secret_name = %s AND 
                              (department_name = %s OR (department_name IS NULL AND %s IS NULL))
                    """, (user_email, key_name, department_name, department_name))
                    
                    result = cur.fetchone()
                    if result:
                        return self._decrypt_value(result['encrypted_value'])
            return None
        except Exception as e:
            log.error(f"Error retrieving secret: {e}")
            return None
    
    def get_user_secrets(self, user_email: str, key_names: Optional[list] = None, department_name: str = None) -> Dict[str, str]:
        """
        Get multiple secret_records for a user (your main function)
        
        Args:
            user_email: User's email
            key_names: Optional list of specific secret_names to retrieve
            department_name: Department name to filter secret_records (optional)
            
        Returns:
            Dict[str, str]: Dictionary of key_name -> decrypted_value
        """
        secrets = {}
        
        try:
            with self._get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    if key_names:
                        placeholders = ','.join(['%s'] * len(key_names))
                        cur.execute(f"""
                            SELECT secret_name, encrypted_value 
                            FROM user_secrets 
                            WHERE user_email = %s AND secret_name IN ({placeholders}) AND 
                                  (department_name = %s OR (department_name IS NULL AND %s IS NULL))
                        """, [user_email] + key_names + [department_name, department_name])
                    else:
                        cur.execute("""
                            SELECT secret_name, encrypted_value 
                            FROM user_secrets 
                            WHERE user_email = %s AND 
                                  (department_name = %s OR (department_name IS NULL AND %s IS NULL))
                        """, (user_email, department_name, department_name))
                    
                    results = cur.fetchall()
                    for row in results:
                        try:
                            secrets[row['secret_name']] = self._decrypt_value(row['encrypted_value'])
                        except Exception as decrypt_error:
                            log.error(f"Error decrypting {row['secret_name']}: {decrypt_error}")
                            continue
                            
        except Exception as e:
            log.error(f"Error retrieving secrets: {e}")
        
        return secrets
    
    def delete_user_secret(self, user_email: str, key_name: str, department_name: str = None) -> bool:
        """Delete a specific user secret_record"""
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        DELETE FROM user_secrets 
                        WHERE user_email = %s AND secret_name = %s AND 
                              (department_name = %s OR (department_name IS NULL AND %s IS NULL))
                    """, (user_email, key_name, department_name, department_name))
                    conn.commit()
                    return cur.rowcount > 0
        except Exception as e:
            log.error(f"Error deleting secret: {e}")
            return False
    
    def list_user_secret_names(self, user_email: str, department_name: str = None) -> list:
        """List all secret_names for a user (without values)"""
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT secret_name 
                        FROM user_secrets 
                        WHERE user_email = %s AND 
                              (department_name = %s OR (department_name IS NULL AND %s IS NULL))
                        ORDER BY secret_name
                    """, (user_email, department_name, department_name))
                    return [row[0] for row in cur.fetchall()]
        except Exception as e:
            log.error(f"Error listing secrets: {e}")
            return []


class UserEnvironmentManager:
    """
    Manages user-specific environment contexts for agents with public keys support
    """
    
    def __init__(self, secrets_manager: UserSecretsManager, public_keys_manager: PublicKeysManager):
        self.secrets_manager = secrets_manager
        self.public_keys_manager = public_keys_manager
    
    def create_user_env_context(self, user_email: str, required_secrets: list = None, required_public_keys: list = None, department_name: str = None) -> Dict[str, str]:
        """
        Create an environment context for a user's agent execution
        
        Args:
            user_email: User's email
            required_secrets: List of required user secret_data names
            required_public_keys: List of required public key names
            department_name: Department name for context-specific secrets
            
        Returns:
            Dict[str, str]: Environment variables for the user
        """
        # Get user-specific secrets
        user_secrets = self.secrets_manager.get_user_secrets(user_email, required_secrets, department_name)
        
        # Get public keys (available to all users)
        public_keys = self.public_keys_manager.get_public_keys(required_public_keys, department_name)
        
        # Create environment context
        env_context = {
            'USER_EMAIL': user_email,
            'USER_DEPARTMENT': department_name,
            **user_secrets,  # Add user-specific secrets
            **public_keys    # Add public keys (accessible to all users)
        }
        
        return env_context
    
    def execute_with_user_context(self, user_email: str, func, required_secrets: list = None, required_public_keys: list = None, department_name: str = None, **kwargs):
        """
        Execute a function with user-specific environment context including public keys
        
        Args:
            user_email: User's email
            func: Function to execute
            required_secrets: Required user secrets for this execution
            required_public_keys: Required public keys for this execution
            department_name: Department name for context-specific secrets
            **kwargs: Additional arguments for the function
        """
        # Get user's environment context (including public keys)
        user_env = self.create_user_env_context(user_email, required_secrets, required_public_keys, department_name)
        
        # Store original environment
        original_env = {}
        for key, value in user_env.items():
            original_env[key] = os.environ.get(key)
            os.environ[key] = value
        
        try:
            # Execute function with user context
            return func(**kwargs)
        finally:
            # Restore original environment
            for key, original_value in original_env.items():
                if original_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = original_value


# Utility functions for public keys
def create_public_key(key_name: str, key_value: str, description: str = None, department_name: str = None) -> bool:
    """Store a public key accessible to all users"""
    db_config = {
        'host': os.getenv('POSTGRESQL_HOST', 'localhost'),
        'database': os.getenv('DATABASE', 'secrets_db'),
        'user': os.getenv('POSTGRESQL_USER', 'postgres'),
        'password': os.getenv('POSTGRESQL_PASSWORD', ''),
        'port': os.getenv('POSTGRESQL_PORT', 5432)
    }
    if key_name=="":
        raise ValueError(f"Please provide valid key name")
    public_keys_manager = PublicKeysManager(db_config)
    current_user = current_user_email.get(None)
    return public_keys_manager.create_public_key(key_name, key_value, description, current_user, department_name=department_name)

def update_public_key(key_name: str, key_value: str, description: str = None, department_name: str = None) -> bool:
    """Store a public key accessible to all users"""
    db_config = {
        'host': os.getenv('POSTGRESQL_HOST', 'localhost'),
        'database': os.getenv('DATABASE', 'secrets_db'),
        'user': os.getenv('POSTGRESQL_USER', 'postgres'),
        'password': os.getenv('POSTGRESQL_PASSWORD', ''),
        'port': os.getenv('POSTGRESQL_PORT', 5432)
    }
    if key_value=="":
        raise ValueError(f"Please provide valid key name")
    public_keys_manager = PublicKeysManager(db_config)
    current_user = current_user_email.get(None)
    return public_keys_manager.update_public_key(key_name, key_value, description, current_user, department_name)

def get_public_key(key_name: str, default="", department_name: str= None) -> Optional[str]:
    """Get a public key value
    
    Args:
        key_name: The name of the public key to retrieve
        default: Default value if key is not found
        department_name: Department name (if None, uses current user's department)
        
    Returns:
        str: The public key value or default value
        
    Raises:
        ValueError: If current user email is not set in context
        PermissionError: If user doesn't have vault access permission
    """
    # Get current user context
    user_email = current_user_email.get()
    user_department = current_user_department.get()
    
    if not user_email:
        raise ValueError("Current user email is not set in context")
    
    # Use provided department_name or fall back to user's department
    dept_name = user_department
    
    # Setup secrets manager to access vault permission checking methods
    secrets_manager = setup_secrets_manager()
    
    # Check vault access permission
    user_role = secrets_manager._get_user_role_sync(user_email, department_name= dept_name)
    if not user_role:
        log.error(f"Could not determine role for user: {user_email}")
        raise PermissionError("Access denied: Could not determine user role")
    
    has_access = secrets_manager._check_vault_access_sync(user_role, dept_name)
    if not has_access:
        log.warning(f"Vault access denied for user {user_email} with role {user_role} in department {dept_name}")
        raise PermissionError("Access denied: You don't have permission to access vault endpoints")
    
    log.info(f"Vault access granted for user {user_email} with role {user_role} in department {dept_name}")
    
    # Setup public keys manager and retrieve key
    db_config = {
        'host': os.getenv('POSTGRESQL_HOST', 'localhost'),
        'database': os.getenv('DATABASE', 'secrets_db'),
        'user': os.getenv('POSTGRESQL_USER', 'postgres'),
        'password': os.getenv('POSTGRESQL_PASSWORD', ''),
        'port': os.getenv('POSTGRESQL_PORT', 5432)
    }
    
    public_keys_manager = PublicKeysManager(db_config)
    value = public_keys_manager.get_public_key(key_name, dept_name)
    
    log.info(f"Retrieved public key '{key_name}': {'[FOUND]' if value else '[NOT FOUND]'}")
    return value if value else default

def get_all_public_keys(department_name: str = None) -> Dict[str, str]:
    """Get all public keys as a dictionary"""
    db_config = {
        'host': os.getenv('POSTGRESQL_HOST', 'localhost'),
        'database': os.getenv('DATABASE', 'secrets_db'),
        'user': os.getenv('POSTGRESQL_USER', 'postgres'),
        'password': os.getenv('POSTGRESQL_PASSWORD', ''),
        'port': os.getenv('POSTGRESQL_PORT', 5432)
    }
    
    public_keys_manager = PublicKeysManager(db_config)
    return public_keys_manager.get_public_keys(department_name=department_name)

def delete_public_key(key_name: str, department_name: str = None) -> bool:
    """Delete a public key"""
    db_config = {
        'host': os.getenv('POSTGRESQL_HOST', 'localhost'),
        'database': os.getenv('DATABASE', 'secrets_db'),
        'user': os.getenv('POSTGRESQL_USER', 'postgres'),
        'password': os.getenv('POSTGRESQL_PASSWORD', ''),
        'port': os.getenv('POSTGRESQL_PORT', 5432)
    }
    
    public_keys_manager = PublicKeysManager(db_config)
    return public_keys_manager.delete_public_key(key_name, department_name)

def list_public_keys(department_name: str = None) -> list:
    """List all public key names with metadata"""
    db_config = {
        'host': os.getenv('POSTGRESQL_HOST', 'localhost'),
        'database': os.getenv('DATABASE', 'secrets_db'),
        'user': os.getenv('POSTGRESQL_USER', 'postgres'),
        'password': os.getenv('POSTGRESQL_PASSWORD', ''),
        'port': os.getenv('POSTGRESQL_PORT', 5432)
    }
    
    public_keys_manager = PublicKeysManager(db_config)
    return public_keys_manager.list_public_key_names(department_name)


# Enhanced utility functions for combined access
def get_user_environment(user_email: str, required_secrets: list = None, required_public_keys: list = None, department_name: str = None) -> Dict[str, str]:
    """
    Get complete environment for a user including both private secrets and public keys
    
    Args:
        user_email: User's email
        required_secrets: List of required user secret_data names
        required_public_keys: List of required public key names
        department_name: Department name for context-specific secrets
        
    Returns:
        Dict[str, str]: Combined environment variables
    """
    db_config = {
        'host': os.getenv('POSTGRESQL_HOST', 'localhost'),
        'database': os.getenv('DATABASE', 'secrets_db'),
        'user': os.getenv('POSTGRESQL_USER', 'postgres'),
        'password': os.getenv('POSTGRESQL_PASSWORD', ''),
        'port': os.getenv('POSTGRESQL_PORT', 5432)
    }
    
    secrets_manager = UserSecretsManager(db_config)
    public_keys_manager = PublicKeysManager(db_config)
    env_manager = UserEnvironmentManager(secrets_manager, public_keys_manager)
    
    return env_manager.create_user_env_context(user_email, required_secrets, required_public_keys, department_name)


# Convenience function for current user context
def get_current_user_environment(required_secrets: list = None, required_public_keys: list = None, department_name: str = None) -> Dict[str, str]:
    """Get environment for current user from context"""
    current_user = current_user_email.get(None)
    if not current_user:
        raise ValueError("No current user context set")
    
    return get_user_environment(current_user, required_secrets, required_public_keys, department_name)

def setup_secrets_manager():
    """Setup the secrets manager with database configuration"""
    
    # Database configuration
    db_config = {
        'host': os.getenv('POSTGRESQL_HOST', 'localhost'),
        'database': os.getenv('DATABASE', 'agentic_workflow_as_service_database'),
        'user': os.getenv('POSTGRESQL_USER', 'postgres'),
        'password': os.getenv('POSTGRESQL_PASSWORD', 'postgres'),
        'port': int(os.getenv('POSTGRESQL_PORT', 5432))
    }
    
    # Generate master key if not exists (do this once and store securely)
    if not os.getenv('SECRETS_MASTER_KEY'):
        master_key = Fernet.generate_key().decode()
        log.error(f"Generated master key (store this securely): {master_key}")
        os.environ['SECRETS_MASTER_KEY'] = master_key
    
    return UserSecretsManager(db_config)

def get_user_secrets(look_up_key, default_value=None):
    """
    Retrieve user secrets based on a lookup key.
    
    Args:
        look_up_key: The key to look up the user's secret_data.
        default_value: Default value if the secret_data is not found.
        
    Returns:
        str: The user's secret_data or default value.
    """
    secrets_manager = setup_secrets_manager()
    
    # Get current user email from context variable
    log.info('fetching user_email')
    user_email = current_user_email.get()
    user_department = current_user_department.get()
    
    if not user_email:
        raise ValueError("Current user email is not set in context")
    
    user_role = secrets_manager._get_user_role_sync(user_email, department_name= user_department)
    if not user_role:
        log.error(f"Could not determine role for user: {user_email}")
        raise PermissionError("Access denied: Could not determine user role")
    
    dept_name = user_department 
    
    # Check vault access permission
    has_access = secrets_manager._check_vault_access_sync(user_role, dept_name)
    if not has_access:
        log.warning(f"Vault access denied for user {user_email} with role {user_role} in department {dept_name}")
        raise PermissionError("Access denied: You don't have permission to access vault endpoints")
    
    log.info(f"Vault access granted for user {user_email} with role {user_role} in department {dept_name}")
    
    # Retrieve the secret_record
    key_value = secrets_manager.get_user_secret(user_email, look_up_key, department_name=user_department)
    log.error(f"Retrieved secret for {look_up_key}: {key_value}")
    return key_value if key_value else default_value

def set_user_secret(look_up_key, value):
    """
    Set or update a user secret_data.
    """
    secrets_manager = setup_secrets_manager()

    # Get current user email from context variable
    user_email = current_user_email.get()

    if not user_email:
        raise ValueError("Current user email is not set in context")

    # Set the secret_data
    secrets_manager.set_user_secret(user_email, look_up_key, value)
    return f"Set secret for {look_up_key}: {value}"

def delete_user_secret(look_up_key):
    """
    Delete a user secret_data.
    """
    secrets_manager = setup_secrets_manager()

    # Get current user email from context variable
    user_email = current_user_email.get()

    if not user_email:
        raise ValueError("Current user email is not set in context")

    # Delete the secret_data
    success = secrets_manager.delete_user_secret(user_email, look_up_key)
    return f"Deleted secret for {look_up_key}: {'Success' if success else 'Not found'}"

def list_user_secrets():
    """List all user secrets for the current user.
    """
    secrets_manager = setup_secrets_manager()

    # Get current user email from context variable
    user_email = current_user_email.get()

    if not user_email:
        raise ValueError("Current user email is not set in context")

    # List all secrets
    key_names = secrets_manager.list_user_secret_names(user_email)
    return f"User secrets for {user_email}: {key_names}" if key_names else "No secrets found for the user."

def get_user_secrets_dict():
    """Retrieve all user secrets as a dictionary.
    """
    secrets_manager = setup_secrets_manager()

    # Get current user email from context variable
    user_email = current_user_email.get()

    if not user_email:
        raise ValueError("Current user email is not set in context")

    # Get all secrets
    secrets_dict = secrets_manager.get_user_secrets(user_email)
    return secrets_dict if secrets_dict else "No secrets found for the user."

def get_user_secrets_as_json():
    """Retrieve all user secrets as a JSON string.
    
    Returns:
        str: JSON string of user secrets.
    """
    secrets_dict = get_user_secrets_dict()
    return json.dumps(secrets_dict, indent=2) if isinstance(secrets_dict, dict) else secrets_dict






# === NEW GROUP SECRETS FUNCTIONS ===


def _get_db_config():
    """Get database configuration for synchronous connections"""
    return {
        'host': os.getenv('POSTGRESQL_HOST', 'localhost'),
        'database': os.getenv('DATABASE', 'agentic_workflow_as_service_database'),
        'user': os.getenv('POSTGRESQL_USER', 'postgres'),
        'password': os.getenv('POSTGRESQL_PASSWORD', 'postgres'),
        'port': int(os.getenv('POSTGRESQL_PORT', 5432))
    }

def group_exists_sync(group_name: str, department_name: str = None) -> bool:
    """
    Synchronously check if a group exists in the specified department.
    
    Args:
        group_name (str): The group name to check.
        department_name (str): The department context for the group.
        
    Returns:
        bool: True if group exists, False otherwise.
    """
    try:
        db_config = _get_db_config()
        
        with psycopg2.connect(**db_config) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) FROM groups 
                    WHERE group_name = %s AND department_name = %s
                """, (group_name, department_name))
                
                result = cur.fetchone()
                exists = result[0] > 0 if result else False
                
                log.info(f"Group '{group_name}' in department '{department_name}': {'exists' if exists else 'not found'}")
                return exists
                
    except Exception as e:
        log.error(f"Error checking if group '{group_name}' exists in department '{department_name}': {e}")
        return False

def check_user_group_access_sync(user_email: str, group_name: str, department_name: str = None) -> bool:
    """
    Synchronously check if a user has access to a specific group.
    
    Args:
        user_email (str): User's email address.
        group_name (str): The group name to check access for.
        department_name (str): The department context for the group.
        
    Returns:
        bool: True if user has access to the group, False otherwise.
    """
    try:
        db_config = _get_db_config()
        
        with psycopg2.connect(**db_config) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Check if user email is in the group's user_emails array
                cur.execute("""
                    SELECT user_emails
                    FROM groups 
                    WHERE group_name = %s 
                    AND department_name = %s 
                """, (group_name, department_name))
                
                result = cur.fetchone()
                
                if not result:
                    return False
            
                # Check if user is a group member
                return bool(result['user_emails'] and user_email in result['user_emails'])
                
    except Exception as e:
        log.error(f"Error checking user '{user_email}' access to group '{group_name}' in department '{department_name}': {e}")
        return False

def get_group_secret_sync(group_name: str, key_name: str, user_email: str, department_name: str = None) -> Optional[str]:
    """
    Synchronously retrieve a specific group secret_record for an authorized user.
    
    Args:
        group_name (str): The group name.
        key_name (str): The secret_key name.
        user_email (str): User's email address.
        department_name (str): The department context for the group.
        
    Returns:
        Optional[str]: The decrypted secret_value or None if not found/unauthorized.
    """
    try:
        db_config = _get_db_config()
        
        with psycopg2.connect(**db_config) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get the group secret_record
                cur.execute("""
                    SELECT encrypted_value 
                    FROM group_secrets 
                    WHERE group_name = %s 
                    AND department_name = %s
                    AND key_name = %s
                """, (group_name, department_name, key_name))
                
                secret_result = cur.fetchone()
                if not secret_result:
                    log.warning(f"Group secret '{key_name}' not found for group '{group_name}' in department '{department_name}'")
                    return None
                
                # Decrypt the secret_value
                from cryptography.fernet import Fernet
                master_key = os.getenv('SECRETS_MASTER_KEY')
                if not master_key:
                    log.error("SECRETS_MASTER_KEY not found for decrypting group secrets")
                    return None
                
                cipher_suite = Fernet(master_key.encode()[:44].ljust(44, b'='))
                decrypted_value = cipher_suite.decrypt(secret_result['encrypted_value'].encode()).decode()
                
                log.info(f"Retrieved group secret '{key_name}' for group '{group_name}' for user '{user_email}'")
                return decrypted_value
                
    except Exception as e:
        log.error(f"Error retrieving group secret '{key_name}' from group '{group_name}' for user '{user_email}': {e}")
        return None

def get_group_secrets(group_name: str, key_name: str, default_value=None):
    """
    Retrieve group secrets based on group name and key name.
    
    Args:
        group_name: The name of the group containing the secret_record.
        key_name: The key to look up the group secret_record.
        default_value: Default value if the secret_record is not found.
        
    Returns:
        str: The group secret_record or default value.
        
    Example:
        # In agent code:
        api_key = get_group_secrets('weather_group', 'api_key', 'default_key')
    """
    user_email = current_user_email.get()
    user_department = current_user_department.get()
    
    # Use provided department_name or fall back to user's department
    dept_name = user_department
    
    # Setup secrets manager to access vault permission checking methods
    secrets_manager = setup_secrets_manager()
    
    # Check vault access permission
    user_role = secrets_manager._get_user_role_sync(user_email, department_name= dept_name)
    
    if not user_email or not user_department:
        log.error("User context not properly set for group secrets")
        return default_value if default_value is not None else ""
    
    if not user_role:
        log.error(f"Could not determine role for user: {user_email}")
        raise PermissionError("Access denied: Could not determine user role")
    
    has_access = secrets_manager._check_vault_access_sync(user_role, dept_name)
    if not has_access:
        log.warning(f"Vault access denied for user {user_email} with role {user_role} in department {dept_name}")
        raise PermissionError("Access denied: You don't have permission to access vault endpoints")
    
    log.info(f"Vault access granted for user {user_email} with role {user_role} in department {dept_name}")
    
    
    try:
        # Step 1: Check if group exists
        if not group_exists_sync(group_name, user_department):
            log.warning(f"Group '{group_name}' does not exist in department '{user_department}'")
            return default_value if default_value is not None else ""
        
        # Step 2: Check if user has access to the group
        if not check_user_group_access_sync(user_email, group_name, user_department):
            log.warning(f"User '{user_email}' does not have access to group '{group_name}' in department '{user_department}'")
            return default_value if default_value is not None else ""
        
        # Step 3: Get the group secret_record
        secret_value = get_group_secret_sync(group_name, key_name, user_email, user_department)
        
        if secret_value is not None:
            log.info(f"Successfully retrieved group secret '{key_name}' from group '{group_name}'")
            return secret_value
        else:
            log.warning(f"Group secret '{key_name}' not found in group '{group_name}'")
            return default_value if default_value is not None else ""
        
    except Exception as e:
        log.error(f"Error in get_group_secrets for {group_name}.{key_name}: {e}")
        return default_value if default_value is not None else "" 
    

