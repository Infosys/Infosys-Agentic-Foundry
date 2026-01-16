# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import Literal
from fastapi import HTTPException

# Import the global app_container instance
from src.api.app_container import app_container

from src.auth.auth_service import AuthService
from src.auth.authorization_service import AuthorizationService
from src.database.services import (
    TagService, McpToolService, ToolService, AgentService, ChatService, ModelService,
    FeedbackLearningService, EvaluationService, ConsistencyService, PipelineService
)
from src.database.core_evaluation_service import CoreEvaluationService, CoreConsistencyEvaluationService, CoreRobustnessEvaluationService
from src.inference.base_agent_inference import BaseAgentInference, BaseMetaTypeAgentInference
from src.inference.python_based_inference.base_python_based_agent_inference import BasePythonBasedAgentInference
# from src.inference.google_adk_inference.base_agent_gadk_inference import BaseAgentGADKInference
from src.inference.pipeline_inference import PipelineInference
from src.inference.centralized_agent_inference import CentralizedAgentInference
from src.utils.file_manager import FileManager
from MultiDBConnection_Manager import MultiDBConnectionRepository

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


    @staticmethod
    def get_multi_db_connection_manager() -> MultiDBConnectionRepository:
        if app_container.multi_db_connection_repo is None:
            raise HTTPException(status_code=500, detail="MultiDBConnectionRepository not initialized.")
        return app_container.multi_db_connection_repo


    @staticmethod
    def get_specialized_inference_service(agent_type: str, framework_type: Literal["langgraph", "pure_python"] = "langgraph") -> BaseAgentInference | BaseMetaTypeAgentInference | BasePythonBasedAgentInference:
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
