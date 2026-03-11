# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import Literal, Union
from fastapi import HTTPException

# Import the global app_container instance
from src.api.app_container import app_container
from src.config.constants import AgentType, FrameworkType

from src.auth.auth_service import AuthService
from src.auth.authorization_service import AuthorizationService
from src.database.services import (
    TagService, McpToolService, ToolService, AgentService, ChatService, ModelService,
    FeedbackLearningService, EvaluationService, ExportService, ConsistencyService, PipelineService, VMManagementService,
    KnowledgebaseService, UserAgentAccessService, 
    GroupService, GroupSecretsService, ConsistencyService, RoleAccessService, DepartmentService
)
from src.database.admin_config_service import AdminConfigService
from src.database.core_evaluation_service import CoreEvaluationService, CoreConsistencyEvaluationService, CoreRobustnessEvaluationService
# EXPORT:EXCLUDE:START
from src.agent_templates.base_agent_onboard import BaseAgentOnboard, BaseMetaTypeAgentOnboard
# EXPORT:EXCLUDE:END
from src.inference.base_agent_inference import BaseAgentInference, BaseMetaTypeAgentInference
from src.inference.python_based_inference.base_python_based_agent_inference import BasePythonBasedAgentInference
from src.inference.google_adk_inference.base_agent_gadk_inference import BaseAgentGADKInference
from src.inference.pipeline_inference import PipelineInference
from src.inference.centralized_agent_inference import CentralizedAgentInference
from src.tools.tool_export_import_service import ToolExportImportService
from src.utils.file_manager import FileManager
from MultiDBConnection_Manager import MultiDBConnectionRepository

from enum import Enum
from telemetry_wrapper import logger as log



class ServiceProvider:
    """
    Provides access to initialized application service instances.
    These methods are intended to be used as FastAPI dependencies.
    """
    @staticmethod
    def get_database_manager():
        if app_container.db_manager is None:
            raise HTTPException(status_code=500, detail="DatabaseManager not initialized.")
        return app_container.db_manager
    
    @staticmethod
    def get_tag_service() -> TagService:
        if app_container.tag_service is None:
            raise HTTPException(status_code=500, detail="TagService not initialized.")
        return app_container.tag_service

    @staticmethod
    def get_mcp_tool_service() -> McpToolService:
        if app_container.mcp_tool_service is None:
            raise HTTPException(status_code=500, detail="McpToolService not initialized.")
        return app_container.mcp_tool_service

    @staticmethod
    def get_tool_service() -> ToolService:
        if app_container.tool_service is None:
            raise HTTPException(status_code=500, detail="ToolService not initialized.")
        return app_container.tool_service

    @staticmethod
    def get_agent_service() -> AgentService:
        if app_container.agent_service is None:
            raise HTTPException(status_code=500, detail="AgentService not initialized.")
        return app_container.agent_service

    @staticmethod
    def get_chat_service() -> ChatService:
        if app_container.chat_service is None:
            raise HTTPException(status_code=500, detail="ChatService not initialized.")
        return app_container.chat_service

    @staticmethod
    def get_model_service() -> ModelService:
        if app_container.model_service is None:
            raise HTTPException(status_code=500, detail="ModelService not initialized.")
        return app_container.model_service

    @staticmethod
    def get_feedback_learning_service() -> FeedbackLearningService:
        if app_container.feedback_learning_service is None:
            raise HTTPException(status_code=500, detail="FeedbackLearningService not initialized.")
        return app_container.feedback_learning_service

    @staticmethod
    def get_evaluation_service() -> EvaluationService:
        if app_container.evaluation_service is None:
            raise HTTPException(status_code=500, detail="EvaluationService not initialized.")
        return app_container.evaluation_service
    

    @staticmethod
    def get_consistency_service()  -> ConsistencyService:
        if app_container.consistency_service is None:
            raise HTTPException(status_code=500, detail="Consistencyservice not initialized.")
        return app_container.consistency_service
    
    @staticmethod
    def get_core_consistency_service() -> CoreConsistencyEvaluationService:
        if app_container.core_consistency_service is None: 
            raise HTTPException(status_code=500, detail="CoreConsistencyEvaluationService not initialized.") 
        return app_container.core_consistency_service
    

    @staticmethod
    def get_core_robustness_service() -> CoreRobustnessEvaluationService:
        if app_container.core_robustness_service is None:
            raise HTTPException(status_code=500, detail="CoreRobustnessEvaluationService not initialized.")
        return app_container.core_robustness_service

    @staticmethod
    def get_core_evaluation_service() -> CoreEvaluationService:
        if app_container.core_evaluation_service is None:
            raise HTTPException(status_code=500, detail="CoreEvaluationService not initialized.")
        return app_container.core_evaluation_service

    @staticmethod
    def get_centralized_agent_inference() -> CentralizedAgentInference:
        if app_container.centralized_agent_inference is None:
            raise HTTPException(status_code=500, detail="CentralizedAgentInference not initialized.")
        return app_container.centralized_agent_inference

    # EXPORT:EXCLUDE:START
    @staticmethod
    def get_export_service() -> ExportService:
        if app_container.export_service is None:
            raise HTTPException(status_code=500, detail="ExportService not initialized.")
        return app_container.export_service
    # EXPORT:EXCLUDE:END

    @staticmethod
    def get_multi_db_connection_manager() -> MultiDBConnectionRepository:
        if app_container.multi_db_connection_repo is None:
            raise HTTPException(status_code=500, detail="MultiDBConnectionRepository not initialized.")
        return app_container.multi_db_connection_repo

    @staticmethod
    def get_admin_config_service() -> AdminConfigService:
        if app_container.admin_config_service is None:
            raise HTTPException(status_code=500, detail="AdminConfigService not initialized.")
        return app_container.admin_config_service

    # EXPORT:EXCLUDE:START
    @staticmethod
    def get_specialized_agent_service(agent_type: Union[AgentType, str]) -> BaseAgentOnboard | BaseMetaTypeAgentOnboard:
        if agent_type == AgentType.REACT_AGENT:
            return app_container.react_agent_service
        if agent_type == AgentType.PLANNER_EXECUTOR_CRITIC_AGENT:
            return app_container.multi_agent_service
        if agent_type == AgentType.PLANNER_EXECUTOR_AGENT:
            return app_container.planner_executor_agent_service
        if agent_type == AgentType.REACT_CRITIC_AGENT:
            return app_container.react_critic_agent_service
        if agent_type == AgentType.META_AGENT:
            return app_container.meta_agent_service
        if agent_type == AgentType.PLANNER_META_AGENT:
            return app_container.planner_meta_agent_service
        if agent_type == AgentType.HYBRID_AGENT:
            return app_container.hybrid_agent_service
        raise HTTPException(status_code=400, detail=f"Unsupported agent type: {agent_type}")
    # EXPORT:EXCLUDE:END

    @staticmethod
    def get_specialized_inference_service(agent_type: str, framework_type: FrameworkType = FrameworkType.LANGGRAPH) -> BaseAgentInference | BaseMetaTypeAgentInference | BasePythonBasedAgentInference | BaseAgentGADKInference:
        """
        Returns the specialized inference service for the given agent type.
        This is used to handle inference requests for specific agent types.
        """
        try:
            return app_container.centralized_agent_inference.get_specialized_agent_inference(agent_type=agent_type, framework_type=framework_type)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error getting specialized inference service: {str(e)}")

    @staticmethod
    def get_file_manager() -> FileManager:
        """
        Returns the FileManager instance for file operations.
        This is used to handle file uploads, downloads, and other file-related tasks.
        """
        if app_container.file_manager is None:
            raise HTTPException(status_code=500, detail="FileManager not initialized.")
        return app_container.file_manager

    @staticmethod
    def get_auth_service() -> AuthService:
        """
        Returns the AuthService instance for authentication-related operations.
        This is used to handle user login, registration, and other auth tasks.
        """
        if app_container.auth_service is None:
            raise HTTPException(status_code=500, detail="AuthService not initialized.")
        return app_container.auth_service
    
    @staticmethod
    def get_authorization_service() -> AuthorizationService:
        """
        Returns the AuthorizationService instance for authorization-related operations.
        This is used to handle permission management, role checks, and other authz tasks.
        """
        if app_container.authorization_service is None:
            raise HTTPException(status_code=500, detail="AuthorizationService not initialized.")
        return app_container.authorization_service

    def get_embedding_model():
        """
        Returns the embedding model instance.
        This is used for generating embeddings for text data.
        """
        if app_container.embedding_model is None:
            raise HTTPException(status_code=500, detail="Embedding model not initialized.")
        return app_container.embedding_model
    
    @staticmethod
    def get_cross_encoder():
        """
        Returns the cross-encoder instance.
        This is used for tasks that require cross-encoding of text data.
        """
        if app_container.cross_encoder is None:
            raise HTTPException(status_code=500, detail="Cross-encoder not initialized.")
        return app_container.cross_encoder

    @staticmethod
    def get_tool_file_manager():
        """
        Returns the ToolFileManager instance.
        This is used for managing tool .py files (create, update, delete, restore, sync).
        """
        if app_container.tool_file_manager is None:
            raise HTTPException(status_code=500, detail="ToolFileManager not initialized.")
        return app_container.tool_file_manager

    @staticmethod
    def get_tool_export_import_service() -> ToolExportImportService:
        if app_container.tool_export_import_service is None:
            raise HTTPException(status_code=500, detail="ToolExportImportService not initialized.")
        return app_container.tool_export_import_service

    @staticmethod
    def get_vm_management_service() -> VMManagementService:
        """
        Returns the VMManagementService instance for VM operations.
        This is used to handle VM connections, dependency installation, and server restarts.
        """
        if app_container.vm_management_service is None:
            raise HTTPException(status_code=500, detail="VMManagementService not initialized.")
        return app_container.vm_management_service

    @staticmethod
    def get_pipeline_service() -> PipelineService:
        """
        Returns the PipelineService instance for pipeline management operations.
        This is used to handle pipeline CRUD and execution management.
        """
        if app_container.pipeline_service is None:
            raise HTTPException(status_code=500, detail="PipelineService not initialized.")
        return app_container.pipeline_service

    @staticmethod
    def get_pipeline_inference() -> PipelineInference:
        """
        Returns the PipelineInference instance for executing pipelines.
        This is used to orchestrate agent pipeline execution with HITL support.
        """
        if app_container.pipeline_inference is None:
            raise HTTPException(status_code=500, detail="PipelineInference not initialized.")
        return app_container.pipeline_inference

    @staticmethod
    def get_tool_generation_code_version_service():
        """
        Returns the ToolGenerationCodeVersionService instance for managing code version history.
        This is used to save, retrieve, and switch between code versions in tool generation.
        """
        if app_container.tool_generation_code_version_service is None:
            raise HTTPException(status_code=500, detail="ToolGenerationCodeVersionService not initialized.")
        return app_container.tool_generation_code_version_service

    @staticmethod
    def get_tool_generation_conversation_history_service():
        """
        Returns the ToolGenerationConversationHistoryService instance for managing conversation history.
        This is used to save, retrieve, and clear conversation messages in tool generation chat.
        """
        if app_container.tool_generation_conversation_history_service is None:
            raise HTTPException(status_code=500, detail="ToolGenerationConversationHistoryService not initialized.")
        return app_container.tool_generation_conversation_history_service

    @staticmethod
    def get_knowledgebase_service():
        """
        Returns the KnowledgebaseService instance.
        Used for KB CRUD and agent-KB mappings.
        """
        if app_container.knowledgebase_service is None:
            raise HTTPException(status_code=500, detail="KnowledgebaseService not initialized.")
        return app_container.knowledgebase_service
    
    @staticmethod
    def get_user_agent_access_service() -> UserAgentAccessService:
        """
        Returns the UserAgentAccessService instance for user agent access management.
        This is used to handle granting/revoking agent access for users.
        """
        if app_container.user_agent_access_service is None:
            raise HTTPException(status_code=500, detail="UserAgentAccessService not initialized.")
        return app_container.user_agent_access_service

    @staticmethod
    def get_group_service() -> GroupService:
        """
        Returns the GroupService instance for group management operations.
        This is used to handle creating groups, managing users and agents within groups.
        """
        if app_container.group_service is None:
            raise HTTPException(status_code=500, detail="GroupService not initialized.")
        return app_container.group_service

    @staticmethod
    def get_group_secrets_service() -> GroupSecretsService:
        """
        Returns the GroupSecretsService instance for group secrets management operations.
        This is used to handle creating, reading, updating and deleting encrypted secrets within groups.
        """
        if app_container.group_secrets_service is None:
            raise HTTPException(status_code=500, detail="GroupSecretsService not initialized.")
        return app_container.group_secrets_service
    
    @staticmethod
    def get_role_access_service() -> RoleAccessService:
        """
        Returns the RoleAccessService instance for role and permission management operations.
        This is used to handle creating roles, setting permissions, and checking user access rights.
        """
        if app_container.role_access_service is None:
            raise HTTPException(status_code=500, detail="RoleAccessService not initialized.")
        return app_container.role_access_service

    @staticmethod
    def get_department_service() -> DepartmentService:
        """
        Returns the DepartmentService instance for department management operations.
        This is used to handle creating, listing, and deleting departments.
        """
        if app_container.department_service is None:
            raise HTTPException(status_code=500, detail="DepartmentService not initialized.")
        return app_container.department_service

    @staticmethod
    def get_user_access_key_repository():
        """
        Returns the UserAccessKeyRepository instance for user resource access management.
        This is used to manage access keys and their allowed values for tool access control.
        """
        if app_container.user_access_key_repo is None:
            raise HTTPException(status_code=500, detail="UserAccessKeyRepository not initialized.")
        return app_container.user_access_key_repo

    @staticmethod
    def get_tool_access_key_mapping_repository():
        """
        Returns the ToolAccessKeyMappingRepository instance for tool-to-access-key mapping.
        This is used to track which tools require which access keys.
        """
        if app_container.tool_access_key_mapping_repo is None:
            raise HTTPException(status_code=500, detail="ToolAccessKeyMappingRepository not initialized.")
        return app_container.tool_access_key_mapping_repo
    
    @staticmethod
    def get_access_key_definitions_repository():
        """
        Returns the AccessKeyDefinitionsRepository instance for master access key definitions.
        This is used to manage the master list of access keys in the system.
        """
        if app_container.access_key_definitions_repo is None:
            raise HTTPException(status_code=500, detail="AccessKeyDefinitionsRepository not initialized.")
        return app_container.access_key_definitions_repo

    @staticmethod
    def get_user_department_mapping_repository():
        """
        Returns the UserDepartmentMappingRepository instance for user-department mapping.
        This is used to manage user assignments to departments and their roles.
        """
        if app_container.user_dept_mapping_repo is None:
            raise HTTPException(status_code=500, detail="UserDepartmentMappingRepository not initialized.")
        return app_container.user_dept_mapping_repo

    @staticmethod
    def get_tool_sharing_repo():
        """
        Returns the ToolDepartmentSharingRepository instance for tool sharing across departments.
        This is used to manage sharing tools between different departments.
        """
        if app_container.tool_sharing_repo is None:
            raise HTTPException(status_code=500, detail="ToolDepartmentSharingRepository not initialized.")
        return app_container.tool_sharing_repo

    @staticmethod
    def get_agent_sharing_repo():
        """
        Returns the AgentDepartmentSharingRepository instance for agent sharing across departments.
        This is used to manage sharing agents between different departments.
        """
        if app_container.agent_sharing_repo is None:
            raise HTTPException(status_code=500, detail="AgentDepartmentSharingRepository not initialized.")
        return app_container.agent_sharing_repo

    @staticmethod
    def get_mcp_tool_sharing_repo():
        """
        Returns the McpToolDepartmentSharingRepository instance for MCP tool sharing across departments.
        This is used to manage sharing MCP tools between different departments.
        """
        if app_container.mcp_tool_sharing_repo is None:
            raise HTTPException(status_code=500, detail="McpToolDepartmentSharingRepository not initialized.")
        return app_container.mcp_tool_sharing_repo

    @staticmethod
    def get_kb_sharing_repo():
        """
        Returns the KbDepartmentSharingRepository instance for knowledge base sharing across departments.
        This is used to manage sharing knowledge bases between different departments.
        """
        if app_container.kb_sharing_repo is None:
            raise HTTPException(status_code=500, detail="KbDepartmentSharingRepository not initialized.")
        return app_container.kb_sharing_repo

