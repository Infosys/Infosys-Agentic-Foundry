# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
User Secrets Management System for Agentic Foundry
Securely manages user-specific environment variables and credentials
"""

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
    
    def store_user_secret(self, user_email: str, secret_name: str, secret_value: str) -> bool:
        """
        Store an encrypted secret for a user
        
        Args:
            user_email: User's email (unique identifier)
            secret_name: Name of the secret (e.g., 'notion_token', 'openai_key')
            secret_value: The actual secret value
            
        Returns:
            bool: Success status
        """
        try:
            encrypted_value = self._encrypt_value(secret_value)
            
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO user_secrets (user_email, secret_name, encrypted_value)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (user_email, secret_name)
                        DO UPDATE SET 
                            encrypted_value = EXCLUDED.encrypted_value,
                            updated_at = CURRENT_TIMESTAMP
                    """, (user_email, secret_name, encrypted_value))
                    conn.commit()
            return True
        except Exception as e:
            print(f"Error storing secret: {e}")
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
    Manages user-specific environment contexts for agents
    """
    
    def __init__(self, secrets_manager: UserSecretsManager):
        self.secrets_manager = secrets_manager
    
    def create_user_env_context(self, user_email: str, required_secrets: list = None) -> Dict[str, str]:
        """
        Create an environment context for a user's agent execution
        
        Args:
            user_email: User's email
            required_secrets: List of required secret names
            
        Returns:
            Dict[str, str]: Environment variables for the user
        """
        user_secrets = self.secrets_manager.get_user_secrets(user_email, required_secrets)
        
        # Create environment context
        env_context = {
            'USER_EMAIL': user_email,
            **user_secrets  # Add all user secrets to environment
        }
        
        return env_context
    
    def execute_with_user_context(self, user_email: str, func, required_secrets: list = None, **kwargs):
        """
        Execute a function with user-specific environment context
        
        Args:
            user_email: User's email
            func: Function to execute
            required_secrets: Required secrets for this execution
            **kwargs: Additional arguments for the function
        """
        # Get user's environment context
        user_env = self.create_user_env_context(user_email, required_secrets)
        
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

