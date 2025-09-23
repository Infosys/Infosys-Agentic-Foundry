# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from fastapi import HTTPException

# Import the global app_container instance
from src.api.app_container import app_container

from src.auth.auth_service import AuthService
from src.auth.authorization_service import AuthorizationService
from src.database.services import (
    TagService, McpToolService, ToolService, AgentService, ChatService, ModelService,
    FeedbackLearningService, EvaluationService, ExportService
)
from src.database.core_evaluation_service import CoreEvaluationService
from src.agent_templates.base_agent_onboard import BaseAgentOnboard, BaseMetaTypeAgentOnboard
from src.inference.base_agent_inference import BaseAgentInference, BaseMetaTypeAgentInference
from src.inference.centralized_agent_inference import CentralizedAgentInference
from src.utils.file_manager import FileManager
from MultiDBConnection_Manager import MultiDBConnectionRepository



class ServiceProvider:
    """
    Provides access to initialized application service instances.
    These methods are intended to be used as FastAPI dependencies.
    """

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
    def get_export_service() -> ExportService:
        if app_container.export_service is None:
            raise HTTPException(status_code=500, detail="ExportService not initialized.")
        return app_container.export_service

    @staticmethod
    def get_multi_db_connection_manager() -> MultiDBConnectionRepository:
        if app_container.multi_db_connection_repo is None:
            raise HTTPException(status_code=500, detail="MultiDBConnectionRepository not initialized.")
        return app_container.multi_db_connection_repo

    @staticmethod
    def get_specialized_agent_service(agent_type: str) -> BaseAgentOnboard | BaseMetaTypeAgentOnboard:
        if agent_type == "react_agent":
            return app_container.react_agent_service
        elif agent_type == "multi_agent":
            return app_container.multi_agent_service
        elif agent_type == "planner_executor_agent":
            return app_container.planner_executor_agent_service
        elif agent_type == "react_critic_agent":
            return app_container.react_critic_agent_service
        elif agent_type == "meta_agent":
            return app_container.meta_agent_service
        elif agent_type == "planner_meta_agent":
            return app_container.planner_meta_agent_service
        raise HTTPException(status_code=400, detail=f"Unsupported agent type: {agent_type}")

    @staticmethod
    def get_specialized_inference_service(agent_type: str) -> BaseAgentInference | BaseMetaTypeAgentInference:
        """
        Returns the specialized inference service for the given agent type.
        This is used to handle inference requests for specific agent types.
        """
        if agent_type == "react_agent":
            return app_container.react_agent_inference
        elif agent_type == "multi_agent":
            return app_container.multi_agent_inference
        elif agent_type == "planner_executor_agent":
            return app_container.planner_executor_agent_inference
        elif agent_type == "react_critic_agent":
            return app_container.react_critic_agent_inference
        elif agent_type == "meta_agent":
            return app_container.meta_agent_inference
        elif agent_type == "planner_meta_agent":
            return app_container.planner_meta_agent_inference
        raise HTTPException(status_code=400, detail=f"Unsupported inference service for agent type: {agent_type}")

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

