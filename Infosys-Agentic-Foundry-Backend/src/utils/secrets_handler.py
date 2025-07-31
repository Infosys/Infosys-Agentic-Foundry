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

current_user_email: ContextVar[str] = ContextVar("current_user_email")

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
                        key_name VARCHAR(100) NOT NULL UNIQUE,
                        encrypted_value TEXT NOT NULL,
                        description TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        created_by VARCHAR(255)
                    );
                    
                    CREATE INDEX IF NOT EXISTS idx_public_keys_name 
                    ON public_keys(key_name);
                """)
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
    
    def create_public_key(self, key_name: str, key_value: str, description: str = None, created_by: str = None) -> bool:
        """
        Create a new encrypted public key
        
        Args:
            key_name: Name of the public key (e.g., 'shared_api_key', 'common_token')
            key_value: The actual key value
            description: Optional description of the key
            created_by: Email of the user who created this key
            
        Returns:
            bool: Success status
            
        Raises:
            ValueError: If public key already exists
        """
        try:
            encrypted_value = self._encrypt_value(key_value)
            
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO public_keys (key_name, encrypted_value, description, created_by)
                        VALUES (%s, %s, %s, %s)
                    """, (key_name, encrypted_value, description, created_by))
                    conn.commit()
            return True
        except Exception as e:
            # Check if it's a duplicate key error
            if "duplicate key" in str(e).lower() or "unique constraint" in str(e).lower():
                raise ValueError(f"Public key '{key_name}' already exists")
            print(f"Error creating public key: {e}")
            return False

    def update_public_key(self, key_name: str, key_value: str, description: str = None, updated_by: str = None) -> bool:
        """
        Update an existing encrypted public key
        
        Args:
            key_name: Name of the public key (e.g., 'shared_api_key', 'common_token')
            key_value: The new key value
            description: Optional description of the key
            updated_by: Email of the user who updated this key
            
        Returns:
            bool: Success status
            
        Raises:
            ValueError: If public key doesn't exist
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
                    
                    if updated_by is not None:
                        update_fields.append("updated_by = %s")
                        params.append(updated_by)
                    
                    params.append(key_name)  # For WHERE clause
                    
                    cur.execute(f"""
                        UPDATE public_keys 
                        SET {', '.join(update_fields)}
                        WHERE key_name = %s
                    """, params)
                    
                    if cur.rowcount == 0:
                        raise ValueError(f"Public key '{key_name}' not found")
                        
                    conn.commit()
            return True
        except ValueError:
            # Re-raise ValueError as is
            raise
        except Exception as e:
            print(f"Error updating public key: {e}")
            return False
        
    def get_public_key(self, key_name: str) -> Optional[str]:
        """
        Retrieve and decrypt a public key
        
        Args:
            key_name: Name of the public key
            
        Returns:
            Optional[str]: Decrypted key value or None if not found
        """
        try:
            with self._get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT encrypted_value 
                        FROM public_keys 
                        WHERE key_name = %s
                    """, (key_name,))
                    
                    result = cur.fetchone()
                    if result:
                        return self._decrypt_value(result['encrypted_value'])
            return None
        except Exception as e:
            print(f"Error retrieving public key: {e}")
            return None
    
    def get_public_keys(self, key_names: Optional[list] = None) -> Dict[str, str]:
        """
        Get multiple public keys
        
        Args:
            key_names: Optional list of specific key names to retrieve
            
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
                            WHERE key_name IN ({placeholders})
                        """, key_names)
                    else:
                        cur.execute("""
                            SELECT key_name, encrypted_value 
                            FROM public_keys
                        """)
                    
                    results = cur.fetchall()
                    for row in results:
                        try:
                            keys[row['key_name']] = self._decrypt_value(row['encrypted_value'])
                        except Exception as decrypt_error:
                            print(f"Error decrypting {row['key_name']}: {decrypt_error}")
                            continue
                            
        except Exception as e:
            print(f"Error retrieving public keys: {e}")
        
        return keys
    
    def delete_public_key(self, key_name: str) -> bool:
        """Delete a specific public key"""
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        DELETE FROM public_keys 
                        WHERE key_name = %s
                    """, (key_name,))
                    conn.commit()
                    return cur.rowcount > 0
        except Exception as e:
            print(f"Error deleting public key: {e}")
            return False
    
    def list_public_key_names(self) -> list:
        """List all public key names (without values)"""
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT key_name, description, created_by, created_at
                        FROM public_keys 
                        ORDER BY key_name
                    """)
                    return [{'name': row[0], 'description': row[1], 'created_by': row[2], 'created_at': row[3]} for row in cur.fetchall()]
        except Exception as e:
            print(f"Error listing public keys: {e}")
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
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(user_email, secret_name)
                    );
                    
                    CREATE INDEX IF NOT EXISTS idx_user_secrets_email 
                    ON user_secrets(user_email);
                """)
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
        """Encrypt a secret value"""
        return self.cipher_suite.encrypt(value.encode()).decode()
    
    def _decrypt_value(self, encrypted_value: str) -> str:
        """Decrypt a secret value"""
        return self.cipher_suite.decrypt(encrypted_value.encode()).decode()
    
    def create_user_secret(self, user_email: str, secret_name: str, secret_value: str) -> bool:
        """
        Create a new encrypted secret for a user
        
        Args:
            user_email: User's email (unique identifier)
            secret_name: Name of the secret (e.g., 'notion_token', 'openai_key')
            secret_value: The actual secret value
            
        Returns:
            bool: Success status
            
        Raises:
            ValueError: If secret already exists for this user
        """
        try:
            encrypted_value = self._encrypt_value(secret_value)
            
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO user_secrets (user_email, secret_name, encrypted_value)
                        VALUES (%s, %s, %s)
                    """, (user_email, secret_name, encrypted_value))
                    conn.commit()
            return True
        except Exception as e:
            # Check if it's a duplicate key error
            if "duplicate key" in str(e).lower() or "unique constraint" in str(e).lower():
                raise ValueError(f"Secret '{secret_name}' already exists for user '{user_email}'")
            print(f"Error creating secret: {e}")
            return False

    def update_user_secret(self, user_email: str, secret_name: str, secret_value: str) -> bool:
        """
        Update an existing encrypted secret for a user
        
        Args:
            user_email: User's email (unique identifier)
            secret_name: Name of the secret (e.g., 'notion_token', 'openai_key')
            secret_value: The new secret value
            
        Returns:
            bool: Success status
            
        Raises:
            ValueError: If secret doesn't exist for this user
        """
        try:
            encrypted_value = self._encrypt_value(secret_value)
            
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE user_secrets 
                        SET encrypted_value = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE user_email = %s AND secret_name = %s
                    """, (encrypted_value, user_email, secret_name))
                    
                    if cur.rowcount == 0:
                        raise ValueError(f"Secret '{secret_name}' not found for user '{user_email}'")
                        
                    conn.commit()
            return True
        except ValueError:
            # Re-raise ValueError as is
            raise
        except Exception as e:
            print(f"Error updating secret: {e}")
            return False
    
    def get_user_secret(self, user_email: str, secret_name: str) -> Optional[str]:
        """
        Retrieve and decrypt a user's secret
        
        Args:
            user_email: User's email
            secret_name: Name of the secret
            
        Returns:
            Optional[str]: Decrypted secret value or None if not found
        """
        try:
            with self._get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT encrypted_value 
                        FROM user_secrets 
                        WHERE user_email = %s AND secret_name = %s
                    """, (user_email, secret_name))
                    
                    result = cur.fetchone()
                    if result:
                        return self._decrypt_value(result['encrypted_value'])
            return None
        except Exception as e:
            print(f"Error retrieving secret: {e}")
            return None
    
    def get_user_secrets(self, user_email: str, secret_names: Optional[list] = None) -> Dict[str, str]:
        """
        Get multiple secrets for a user (your main function)
        
        Args:
            user_email: User's email
            secret_names: Optional list of specific secret names to retrieve
            
        Returns:
            Dict[str, str]: Dictionary of secret_name -> decrypted_value
        """
        secrets = {}
        
        try:
            with self._get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    if secret_names:
                        placeholders = ','.join(['%s'] * len(secret_names))
                        cur.execute(f"""
                            SELECT secret_name, encrypted_value 
                            FROM user_secrets 
                            WHERE user_email = %s AND secret_name IN ({placeholders})
                        """, [user_email] + secret_names)
                    else:
                        cur.execute("""
                            SELECT secret_name, encrypted_value 
                            FROM user_secrets 
                            WHERE user_email = %s
                        """, (user_email,))
                    
                    results = cur.fetchall()
                    for row in results:
                        try:
                            secrets[row['secret_name']] = self._decrypt_value(row['encrypted_value'])
                        except Exception as decrypt_error:
                            print(f"Error decrypting {row['secret_name']}: {decrypt_error}")
                            continue
                            
        except Exception as e:
            print(f"Error retrieving secrets: {e}")
        
        return secrets
    
    def delete_user_secret(self, user_email: str, secret_name: str) -> bool:
        """Delete a specific user secret"""
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        DELETE FROM user_secrets 
                        WHERE user_email = %s AND secret_name = %s
                    """, (user_email, secret_name))
                    conn.commit()
                    return cur.rowcount > 0
        except Exception as e:
            print(f"Error deleting secret: {e}")
            return False
    
    def list_user_secret_names(self, user_email: str) -> list:
        """List all secret names for a user (without values)"""
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT secret_name 
                        FROM user_secrets 
                        WHERE user_email = %s
                        ORDER BY secret_name
                    """, (user_email,))
                    return [row[0] for row in cur.fetchall()]
        except Exception as e:
            print(f"Error listing secrets: {e}")
            return []


class UserEnvironmentManager:
    """
    Manages user-specific environment contexts for agents with public keys support
    """
    
    def __init__(self, secrets_manager: UserSecretsManager, public_keys_manager: PublicKeysManager):
        self.secrets_manager = secrets_manager
        self.public_keys_manager = public_keys_manager
    
    def create_user_env_context(self, user_email: str, required_secrets: list = None, required_public_keys: list = None) -> Dict[str, str]:
        """
        Create an environment context for a user's agent execution
        
        Args:
            user_email: User's email
            required_secrets: List of required user secret names
            required_public_keys: List of required public key names
            
        Returns:
            Dict[str, str]: Environment variables for the user
        """
        # Get user-specific secrets
        user_secrets = self.secrets_manager.get_user_secrets(user_email, required_secrets)
        
        # Get public keys (available to all users)
        public_keys = self.public_keys_manager.get_public_keys(required_public_keys)
        
        # Create environment context
        env_context = {
            'USER_EMAIL': user_email,
            **user_secrets,  # Add user-specific secrets
            **public_keys    # Add public keys (accessible to all users)
        }
        
        return env_context
    
    def execute_with_user_context(self, user_email: str, func, required_secrets: list = None, required_public_keys: list = None, **kwargs):
        """
        Execute a function with user-specific environment context including public keys
        
        Args:
            user_email: User's email
            func: Function to execute
            required_secrets: Required user secrets for this execution
            required_public_keys: Required public keys for this execution
            **kwargs: Additional arguments for the function
        """
        # Get user's environment context (including public keys)
        user_env = self.create_user_env_context(user_email, required_secrets, required_public_keys)
        
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
def create_public_key(key_name: str, key_value: str, description: str = None) -> bool:
    """Store a public key accessible to all users"""
    db_config = {
        'host': os.getenv('POSTGRESQL_HOST', 'localhost'),
        'database': os.getenv('DATABASE', 'secrets_db'),
        'user': os.getenv('POSTGRESQL_USER', 'postgres'),
        'password': os.getenv('POSTGRESQL_PASSWORD', ''),
        'port': os.getenv('DB_PORT', 5432)
    }
    
    public_keys_manager = PublicKeysManager(db_config)
    current_user = current_user_email.get(None)
    return public_keys_manager.create_public_key(key_name, key_value, description, current_user)

def update_public_key(key_name: str, key_value: str, description: str = None) -> bool:
    """Store a public key accessible to all users"""
    db_config = {
        'host': os.getenv('POSTGRESQL_HOST', 'localhost'),
        'database': os.getenv('DATABASE', 'secrets_db'),
        'user': os.getenv('POSTGRESQL_USER', 'postgres'),
        'password': os.getenv('POSTGRESQL_PASSWORD', ''),
        'port': os.getenv('DB_PORT', 5432)
    }
    
    public_keys_manager = PublicKeysManager(db_config)
    current_user = current_user_email.get(None)
    return public_keys_manager.update_public_key(key_name, key_value, description, current_user)

def get_public_key(key_name: str, default="") -> Optional[str]:
    """Get a public key value"""
    db_config = {
        'host': os.getenv('POSTGRESQL_HOST', 'localhost'),
        'database': os.getenv('DATABASE', 'secrets_db'),
        'user': os.getenv('POSTGRESQL_USER', 'postgres'),
        'password': os.getenv('POSTGRESQL_PASSWORD', ''),
        'port': os.getenv('DB_PORT', 5432)
    }
    
    public_keys_manager = PublicKeysManager(db_config)
    value = public_keys_manager.get_public_key(key_name)
    if value:
        return value
    return default

def get_all_public_keys() -> Dict[str, str]:
    """Get all public keys as a dictionary"""
    db_config = {
        'host': os.getenv('POSTGRESQL_HOST', 'localhost'),
        'database': os.getenv('DATABASE', 'secrets_db'),
        'user': os.getenv('POSTGRESQL_USER', 'postgres'),
        'password': os.getenv('POSTGRESQL_PASSWORD', ''),
        'port': os.getenv('DB_PORT', 5432)
    }
    
    public_keys_manager = PublicKeysManager(db_config)
    return public_keys_manager.get_public_keys()

def delete_public_key(key_name: str) -> bool:
    """Delete a public key"""
    db_config = {
        'host': os.getenv('POSTGRESQL_HOST', 'localhost'),
        'database': os.getenv('DATABASE', 'secrets_db'),
        'user': os.getenv('POSTGRESQL_USER', 'postgres'),
        'password': os.getenv('POSTGRESQL_PASSWORD', ''),
        'port': os.getenv('DB_PORT', 5432)
    }
    
    public_keys_manager = PublicKeysManager(db_config)
    return public_keys_manager.delete_public_key(key_name)

def list_public_keys() -> list:
    """List all public key names with metadata"""
    db_config = {
        'host': os.getenv('POSTGRESQL_HOST', 'localhost'),
        'database': os.getenv('DATABASE', 'secrets_db'),
        'user': os.getenv('POSTGRESQL_USER', 'postgres'),
        'password': os.getenv('POSTGRESQL_PASSWORD', ''),
        'port': os.getenv('DB_PORT', 5432)
    }
    
    public_keys_manager = PublicKeysManager(db_config)
    return public_keys_manager.list_public_key_names()


# Enhanced utility functions for combined access
def get_user_environment(user_email: str, required_secrets: list = None, required_public_keys: list = None) -> Dict[str, str]:
    """
    Get complete environment for a user including both private secrets and public keys
    
    Args:
        user_email: User's email
        required_secrets: List of required user secret names
        required_public_keys: List of required public key names
        
    Returns:
        Dict[str, str]: Combined environment variables
    """
    db_config = {
        'host': os.getenv('POSTGRESQL_HOST', 'localhost'),
        'database': os.getenv('DATABASE', 'secrets_db'),
        'user': os.getenv('POSTGRESQL_USER', 'postgres'),
        'password': os.getenv('POSTGRESQL_PASSWORD', ''),
        'port': os.getenv('DB_PORT', 5432)
    }
    
    secrets_manager = UserSecretsManager(db_config)
    public_keys_manager = PublicKeysManager(db_config)
    env_manager = UserEnvironmentManager(secrets_manager, public_keys_manager)
    
    return env_manager.create_user_env_context(user_email, required_secrets, required_public_keys)


# Convenience function for current user context
def get_current_user_environment(required_secrets: list = None, required_public_keys: list = None) -> Dict[str, str]:
    """Get environment for current user from context"""
    current_user = current_user_email.get(None)
    if not current_user:
        raise ValueError("No current user context set")
    
    return get_user_environment(current_user, required_secrets, required_public_keys)

def setup_secrets_manager():
    """Setup the secrets manager with database configuration"""
    
    # Database configuration
    db_config = {
        'host': os.getenv('POSTGRESQL_HOST', 'localhost'),
        'database': os.getenv('DATABASE', 'agentic_workflow_as_service_database'),
        'user': os.getenv('POSTGRESQL_USER', 'postgres'),
        'password': os.getenv('POSTGRESQL_PASSWORD', 'postgres'),
        'port': int(os.getenv('DB_PORT', 5432))
    }
    
    # Generate master key if not exists (do this once and store securely)
    if not os.getenv('SECRETS_MASTER_KEY'):
        master_key = Fernet.generate_key().decode()
        print(f"Generated master key (store this securely): {master_key}")
        os.environ['SECRETS_MASTER_KEY'] = master_key
    
    return UserSecretsManager(db_config)

def get_user_secrets(look_up_key, default_value=None):
    """
    Retrieve user secrets based on a lookup key.
    
    Args:
        look_up_key: The key to look up the user's secret.
        default_value: Default value if the secret is not found.
        
    Returns:
        str: The user's secret or default value.
    """
    secrets_manager = setup_secrets_manager()
    
    # Get current user email from context variable
    user_email = current_user_email.get()
    
    if not user_email:
        raise ValueError("Current user email is not set in context")
    
    # Retrieve the secret
    secret_value = secrets_manager.get_user_secret(user_email, look_up_key)
    print(f"Retrieved secret for {look_up_key}: {secret_value}")
    return secret_value if secret_value else default_value

def set_user_secret(look_up_key, value):
    """
    Set or update a user secret.
    """
    secrets_manager = setup_secrets_manager()

    # Get current user email from context variable
    user_email = current_user_email.get()

    if not user_email:
        raise ValueError("Current user email is not set in context")

    # Set the secret
    secrets_manager.set_user_secret(user_email, look_up_key, value)
    return f"Set secret for {look_up_key}: {value}"

def delete_user_secret(look_up_key):
    """
    Delete a user secret.
    """
    secrets_manager = setup_secrets_manager()

    # Get current user email from context variable
    user_email = current_user_email.get()

    if not user_email:
        raise ValueError("Current user email is not set in context")

    # Delete the secret
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
    secret_names = secrets_manager.list_user_secret_names(user_email)
    return f"User secrets for {user_email}: {secret_names}" if secret_names else "No secrets found for the user."

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