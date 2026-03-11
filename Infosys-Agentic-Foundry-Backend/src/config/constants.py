import os
from enum import StrEnum
from urllib.parse import quote_plus
from typing import Set, Final, Optional, NamedTuple, List
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


# ============================================================================
# Fixed Limits
# ============================================================================

class Limits:
    # Chat Constants
    LANGGRAPH_LONG_TERM_MEMORY_LIMIT: Final[int] = 8
    LANGGRAPH_EXECUTOR_MESSAGES_LIMIT: Final[int] = 30
    PYTHON_BASED_AGENT_CHAT_HISTORY_LOOKBACK: Final[Optional[int]] = 30
    # Cache TTL for admin config service (seconds)
    ADMIN_CONFIG_CACHE_TTL_SECONDS: Final[int] = 60
    # Configurable Epochs Limit
    MAX_CONFIGURABLE_EPOCHS: Final[int] = 5
    # Episodic Memory Manager Constants
    MAX_EXAMPLES: Final[int] = 3
    MAX_QUEUE_SIZE: Final[int] = 30
    RETENTION_DAYS: Final[int] = 30
    RELEVANCE_THRESHOLD: Final[float] = 0.65
    CLEANUP_USAGE_THRESHOLD: Final[int] = 3
    LOW_PERFORMER_THRESHOLD: Final[float] = 0.2


# ============================================================================
# Connection Pool Size Configuration
# ============================================================================

class PoolSizeConfig(NamedTuple):
    """Named tuple for pool size configuration"""
    min_size: int
    max_size: int
    main_db_min_size: Optional[int] = None  # Custom size for main DB, None means use default
    main_db_max_size: Optional[int] = None


class ConnectionPoolSize(StrEnum):
    """Connection pool size presets with associated configurations"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def config(self) -> PoolSizeConfig:
        """Get the pool size configuration for this preset"""
        configs = {
            ConnectionPoolSize.LOW: PoolSizeConfig(
                min_size=2,
                max_size=3,
                main_db_min_size=None,
                main_db_max_size=None
            ),
            ConnectionPoolSize.MEDIUM: PoolSizeConfig(
                min_size=12,
                max_size=15,
                main_db_min_size=17,
                main_db_max_size=20
            ),
            ConnectionPoolSize.HIGH: PoolSizeConfig(
                min_size=18,
                max_size=20,
                main_db_min_size=25,
                main_db_max_size=30
            ),
        }
        return configs[self]

    @classmethod
    def from_env(cls) -> "ConnectionPoolSize":
        """Get pool size from environment variable"""
        default = cls.LOW
        env_value = os.getenv("CONNECTION_POOL_SIZE", default.value).lower()
        try:
            return cls(env_value)
        except ValueError:
            return default


# ============================================================================
# Database Names Configuration
# ============================================================================

class DatabaseName(StrEnum):
    """
    Enum for all database names used in the application.
    Each value corresponds to the environment variable name that holds the actual DB name.
    """
    MAIN = "DATABASE"
    FEEDBACK_LEARNING = "FEEDBACK_LEARNING_DB_NAME"
    EVALUATION_LOGS = "EVALUATION_LOGS_DB_NAME"
    RECYCLE = "RECYCLE_DB_NAME"
    LOGIN = "LOGIN_DB_NAME"
    ARIZE_TRACES = "ARIZE_TRACES_DB_NAME"
    
    @property
    def db_name(self) -> str:
        """Get the actual database name from environment variable"""
        defaults = {
            DatabaseName.MAIN: "agentic_workflow_as_service_database",
            DatabaseName.FEEDBACK_LEARNING: "feedback_learning",
            DatabaseName.EVALUATION_LOGS: "evaluation_logs",
            DatabaseName.RECYCLE: "recycle",
            DatabaseName.LOGIN: "login",
            DatabaseName.ARIZE_TRACES: "arize_traces",
        }
        return os.getenv(self.value, defaults[self])

    @classmethod
    def all_db_names(cls) -> List[str]:
        """Get list of all actual database names"""
        return [db.db_name for db in cls]

    @classmethod
    def required_databases(cls, exclude: Optional[List["DatabaseName"]] = None) -> List[str]:
        """
        Get list of required database names, optionally excluding some.
        
        Args:
            exclude: List of DatabaseName enums to exclude
            
        Returns:
            List of actual database name strings
        """
        exclude = exclude or []
        return [db.db_name for db in cls if db not in exclude]
    
    @classmethod
    def primary_databases(cls) -> List[str]:
        """Get the primary databases used in app_container (first 5)"""
        primary = [
            cls.MAIN,
            cls.FEEDBACK_LEARNING,
            cls.EVALUATION_LOGS,
            cls.RECYCLE,
            cls.LOGIN,
        ]
        return [db.db_name for db in primary]


# ============================================================================
# Framework Types
# ============================================================================

class FrameworkType(StrEnum):
    LANGGRAPH = "langgraph"
    PURE_PYTHON = "pure_python"
    GOOGLE_ADK = "google_adk"

    @classmethod
    def get_default(cls) -> "FrameworkType":
        return cls.LANGGRAPH


# ============================================================================
# Agent Template Types
# ============================================================================

class AgentType(StrEnum):
    # Basic Agent Types
    REACT_AGENT = "react_agent"
    PLANNER_EXECUTOR_CRITIC_AGENT = "multi_agent"
    PLANNER_EXECUTOR_AGENT = "planner_executor_agent"
    REACT_CRITIC_AGENT = "react_critic_agent"
    # Python Based Agent Types
    HYBRID_AGENT = "hybrid_agent"
    # Meta Agent Types
    META_AGENT = "meta_agent"
    PLANNER_META_AGENT = "planner_meta_agent"

    @classmethod
    def basic_types(cls) -> Set["AgentType"]:
        """Returns set of basic (non-meta) agent types"""
        return {
            cls.REACT_AGENT,
            cls.PLANNER_EXECUTOR_CRITIC_AGENT,
            cls.PLANNER_EXECUTOR_AGENT,
            cls.REACT_CRITIC_AGENT,
            cls.HYBRID_AGENT,
        }

    @classmethod
    def meta_types(cls) -> Set["AgentType"]:
        """Returns set of meta agent types"""
        return {
            cls.META_AGENT,
            cls.PLANNER_META_AGENT,
        }

    @classmethod
    def python_based_types(cls) -> Set["AgentType"]:
        """Returns set of Python-based agent types"""
        return {
            cls.HYBRID_AGENT,
        }

    @property
    def is_meta_type(self) -> bool:
        """Check if this agent type is a meta agent"""
        return self in self.meta_types()

    @property
    def is_basic_type(self) -> bool:
        """Check if this agent type is a basic agent"""
        return self in self.basic_types()

    @property
    def is_python_based(self) -> bool:
        """Check if this agent type is Python-based"""
        return self in self.python_based_types()

    @property
    def code(self) -> str:
        """Returns a three-letter code for this agent type"""
        code_mapping = {
            AgentType.REACT_AGENT: "rea",
            AgentType.PLANNER_EXECUTOR_CRITIC_AGENT: "pec",
            AgentType.PLANNER_EXECUTOR_AGENT: "pex",
            AgentType.REACT_CRITIC_AGENT: "rec",
            AgentType.HYBRID_AGENT: "hyb",
            AgentType.META_AGENT: "met",
            AgentType.PLANNER_META_AGENT: "pme",
        }
        return code_mapping.get(self)


# ============================================================================
# Table Names
# ============================================================================

class TableNames(StrEnum):
    # Tags
    TAG = "tags_table"
    # Tools
    TOOL = "tool_table"
    MCP_TOOL = "mcp_tool_table"
    RECYCLE_TOOL = "recycle_tool"
    RECYCLE_MCP_TOOL= "recycle_mcp_tool"
    # Agents
    AGENT = "agent_table"
    RECYCLE_AGENT = "recycle_agent"
    # Mappings
    TAG_TOOL_MAPPING = "tag_tool_mapping_table"
    TAG_AGENTIC_APP_MAPPING = "tag_agentic_app_mapping_table"
    TOOL_AGENT_MAPPING = "tool_agent_mapping_table"
    AGENT_PIPELINE_MAPPING = "agent_pipeline_mapping_table"
    # Langgraph State Memory Tables
    CHECKPOINTS = "checkpoints"
    CHECKPOINT_BLOBS = "checkpoint_blobs"
    CHECKPOINT_WRITES = "checkpoint_writes"
    # Langgraph State Memory Recycle Bin Tables
    RECYCLE_CHECKPOINTS = "recycle_checkpoints"
    RECYCLE_CHECKPOINT_BLOBS = "recycle_checkpoint_blobs"
    RECYCLE_CHECKPOINT_WRITES = "recycle_checkpoint_writes"
    # Feedback Learning
    FEEDBACK_LEARNING = "feedback_response"
    AGENT_FEEDBACK = "agent_feedback"
    # Evaluations
    EVALUATION_DATA = "evaluation_data"
    TOOL_EVALUATION_METRICS = "tool_evaluation_metrics"
    AGENT_EVALUATION_METRICS = "agent_evaluation_metrics"
    # Export Agent
    EXPORT_AGENT = "export_agent"
    # Python Based Agents State Memory Tables
    AGENT_CHAT_STATE_HISTORY = "agent_chat_state_history_table"
    # Pipelines
    PIPELINES = "pipelines_table"
    PIPELINES_RUN = "pipelines_run"
    PIPELINE_STEPS = "pipeline_steps"
    # Knowledge Base
    KNOWLEDGEBASE = "knowledgebase_table"
    AGENT_KNOWLEDGEBASE_MAPPING = "agent_knowledgebase_mapping_table"
    # Logins
    LOGIN_CREDENTIAL = "login_credential"
    APPROVAL_PERMISSIONS = "approval_permissions"
    AUDIT_LOGS_IAF = "audit_logs_iaf"
    REFRESH_TOKENS = "refresh_tokens"
    # Tool Generation
    TOOL_GENERATION_CODE_VERSIONS = "tool_generation_code_versions"
    TOOL_GENERATION_CONVERSATION_HISTORY = "tool_generation_conversation_history"
    # Admin Configuration
    ADMIN_CONFIG = "admin_config"
    # Sharing
    TOOL_DEPARTMENT_SHARING = "tool_department_sharing"
    AGENT_DEPARTMENT_SHARING = "agent_department_sharing"
    MCP_TOOL_DEPARTMENT_SHARING = "mcp_tool_department_sharing"
    KB_DEPARTMENT_SHARING = "kb_department_sharing"


# ============================================================================
# Model Names
# ============================================================================

class ModelNames(StrEnum):
    GPT_4O = "gpt-4o"
    GPT_5_CHAT = "gpt-5-chat"


