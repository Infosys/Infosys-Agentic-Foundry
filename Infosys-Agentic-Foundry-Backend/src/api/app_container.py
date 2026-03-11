# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
from dotenv import load_dotenv
from src.auth.auth_service import AuthService
from src.auth.authorization_service import AuthorizationService
from src.auth.repositories import ApprovalPermissionRepository, AuditLogRepository, UserRepository, RefreshTokenRepository, RoleRepository, DepartmentRepository, UserDepartmentMappingRepository
from src.utils.remote_model_client import RemoteCrossEncoder as CrossEncoder
from src.auth.repositories import UserAccessKeyRepository
from src.database.repositories import AccessKeyDefinitionsRepository
from src.database.repositories import ToolAccessKeyMappingRepository
from src.database.database_manager import DatabaseManager
from src.database.repositories import (
    TagRepository, TagToolMappingRepository, TagAgentMappingRepository,
    ToolRepository, McpToolRepository, ToolAgentMappingRepository, RecycleToolRepository, RecycleMcpToolRepository,
    AgentRepository, RecycleAgentRepository, ChatHistoryRepository,
    FeedbackLearningRepository, EvaluationDataRepository,
    ToolEvaluationMetricsRepository, AgentEvaluationMetricsRepository,
    ExportAgentRepository, AgentMetadataRepository, AgentDataTableRepository, ChatStateHistoryManagerRepository,
    PipelineRepository, PipelineRunRepository, PipelineStepsRepository, AgentPipelineMappingRepository,
    ToolGenerationCodeVersionRepository,
    ToolGenerationConversationHistoryRepository, KnowledgebaseRepository, AgentKnowledgebaseMappingRepository, UserAgentAccessRepository,
    GroupRepository, GroupSecretsRepository,
    ToolDepartmentSharingRepository, AgentDepartmentSharingRepository, McpToolDepartmentSharingRepository,
    KbDepartmentSharingRepository
)
from src.database.admin_config_repository import AdminConfigRepository
from src.database.admin_config_service import AdminConfigService
from src.tools.tool_code_processor import ToolCodeProcessor
from src.database.services import (
    TagService, McpToolService, ToolService, AgentServiceUtils, AgentService, ChatService,
    FeedbackLearningService, EvaluationService, ExportService, UserAgentAccessService,
    GroupService, GroupSecretsService, ConsistencyService, PipelineService, VMManagementService,
    ToolGenerationCodeVersionService, ToolGenerationConversationHistoryService, KnowledgebaseService, RoleAccessService, DepartmentService
)
from src.database.core_evaluation_service import CoreEvaluationService, CoreConsistencyEvaluationService, CoreRobustnessEvaluationService
from src.models.model_service import ModelService
# EXPORT:EXCLUDE:START
from src.agent_templates import (
    ReactAgentOnboard, MultiAgentOnboard, PlannerExecutorAgentOnboard,
    ReactCriticAgentOnboard, MetaAgentOnboard, PlannerMetaAgentOnboard
)
from src.agent_templates.hybrid_agent_onboard import HybridAgentOnboard
# EXPORT:EXCLUDE:END
# Langgraph based Inference Imports
from src.inference import (
    InferenceUtils, ReactAgentInference, MultiAgentInference, PlannerExecutorAgentInference,
    ReactCriticAgentInference, MetaAgentInference, PlannerMetaAgentInference, CentralizedAgentInference
)
from src.inference.pipeline_inference import PipelineInference
from src.inference.python_based_inference.hybrid_agent_inference import HybridAgentInference
# Google ADK based Inference Imports
from src.inference.google_adk_inference.react_agent_gadk_inference import ReactAgentGADKInference
from src.inference.google_adk_inference.planner_executor_critic_agent_gadk_inference import PlannerExecutorCriticAgentGADKInference
from src.inference.google_adk_inference.planner_executor_agent_gadk_inference import PlannerExecutorAgentGADKInference
from src.inference.google_adk_inference.react_critic_agent_gadk_inference import ReactCriticAgentGADKInference
from src.inference.google_adk_inference.meta_agent_gadk_inference import MetaAgentGADKInference
from src.inference.google_adk_inference.planner_meta_agent_gadk_inference import PlannerMetaAgentGADKInference

from src.utils.file_manager import FileManager
from src.utils.tool_file_manager import ToolFileManager
from src.utils.postgres_vector_store_jsonb import PostgresVectorStoreJSONB
from src.config.constants import DatabaseName
from src.config.application_config import app_config
from MultiDBConnection_Manager import MultiDBConnectionRepository
from src.tools.tool_export_import_service import ToolExportImportService

from telemetry_wrapper import logger as log

from src.inference.inference_utils import EpisodicMemoryManager
from src.utils.remote_model_client import RemoteSentenceTransformer as SentenceTransformer
from src.utils.remote_model_client import get_remote_models_and_utils, ModelServerClient

# EXPORT:EXCLUDE:START
from src.onboard.tools_agents_onboarding import insert_sample_tools, insert_sample_agents, insert_sample_pipelines
from Export_Agent.AgentsExport import AgentExporter
# EXPORT:EXCLUDE:END
# EXPORT:INCLUDE:START
# from db_load import load_exported_data
# EXPORT:INCLUDE:END

load_dotenv()


class AppContainer:
    """
    Central container for all initialized application services and repositories.
    Manages their creation and provides access to them.
    """

    def __init__(self):
        """
        Initializes the AppContainer with all necessary services and repositories.
        """
        # These will hold the single instances of managers and services.
        # Database Manager
        self.db_manager: DatabaseManager = None

        # Repositories (usually not directly exposed via Depends, but used by services)
        self.tag_repo: TagRepository = None
        self.tag_tool_mapping_repo: TagToolMappingRepository = None
        self.tag_agent_mapping_repo: TagAgentMappingRepository = None
        self.tool_repo: ToolRepository = None
        self.mcp_tool_repo: McpToolRepository = None
        self.recycle_mcp_tool_repo: RecycleMcpToolRepository = None
        self.tool_agent_mapping_repo: ToolAgentMappingRepository = None
        self.recycle_tool_repo: RecycleToolRepository = None
        self.agent_repo: AgentRepository = None
        self.recycle_agent_repo: RecycleAgentRepository = None
        self.chat_history_repo: ChatHistoryRepository = None
        self.feedback_learning_repo: FeedbackLearningRepository = None
        self.evaluation_data_repo: EvaluationDataRepository = None
        self.tool_evaluation_metrics_repo: ToolEvaluationMetricsRepository = None
        self.agent_evaluation_metrics_repo: AgentEvaluationMetricsRepository = None
        self.export_repo: ExportAgentRepository = None
        self.chat_state_history_manager_repo: ChatStateHistoryManagerRepository = None
        self.user_agent_access_repo: UserAgentAccessRepository = None
        self.group_repo: GroupRepository = None
        self.group_secrets_repo: GroupSecretsRepository = None
        self.user_access_key_repo: UserAccessKeyRepository = None  # UserAccessKeyRepository for tool access control
        self.tool_access_key_mapping_repo: ToolAccessKeyMappingRepository = None  # ToolAccessKeyMappingRepository for tool-to-access-key mapping
        self.access_key_definitions_repo: AccessKeyDefinitionsRepository = None  # AccessKeyDefinitionsRepository for master access key list
        self.tool_sharing_repo: ToolDepartmentSharingRepository = None  # Tool sharing across departments
        self.agent_sharing_repo: AgentDepartmentSharingRepository = None  # Agent sharing across departments
        self.mcp_tool_sharing_repo: McpToolDepartmentSharingRepository = None  # MCP tool sharing across departments
        self.kb_sharing_repo: KbDepartmentSharingRepository = None  # KB sharing across departments

        # Utility Processors
        self.tool_code_processor: ToolCodeProcessor = None
        self.inference_utils: InferenceUtils = None

        # Services (these are typically exposed via Depends for endpoints)
        self.export_service: ExportService = None
        self.model_service: ModelService = None
        self.tag_service: TagService = None
        self.mcp_tool_service: McpToolService = None
        self.tool_service: ToolService = None
        self.agent_service_utils: AgentServiceUtils = None # AgentServiceUtils is a dependency for AgentService
        self.agent_service: AgentService = None
        self.chat_service: ChatService = None
        self.feedback_learning_service: FeedbackLearningService = None
        self.evaluation_service: EvaluationService = None
        self.core_evaluation_service: CoreEvaluationService = None
        self.user_agent_access_service: UserAgentAccessService = None
        self.group_service: GroupService = None
        self.group_secrets_service: GroupSecretsService = None

        # EXPORT:EXCLUDE:START
        # Specialized Agent Onboarding Services (these are typically exposed via Depends for endpoints)
        self.react_agent_service: ReactAgentOnboard = None
        self.multi_agent_service: MultiAgentOnboard = None
        self.planner_executor_agent_service: PlannerExecutorAgentOnboard = None
        self.react_critic_agent_service: ReactCriticAgentOnboard = None
        self.meta_agent_service: MetaAgentOnboard = None
        self.planner_meta_agent_service: PlannerMetaAgentOnboard = None
        self.hybrid_agent_service: HybridAgentOnboard = None
        # EXPORT:EXCLUDE:END

        # Inference Services (these are typically exposed via Depends for endpoints)

        # Langgraph based Template Inferences
        self.react_agent_inference: ReactAgentInference = None
        self.multi_agent_inference: MultiAgentInference = None
        self.planner_executor_agent_inference: PlannerExecutorAgentInference = None
        self.react_critic_agent_inference: ReactCriticAgentInference = None
        self.meta_agent_inference: MetaAgentInference = None
        self.planner_meta_agent_inference: PlannerMetaAgentInference = None

        # Python based Template Inferences
        self.hybrid_agent_inference: HybridAgentInference = None

        # Google ADK based Template Inferences
        self.gadk_react_agent_inference: ReactAgentGADKInference = None
        self.gadk_planner_executor_critic_agent_inference: PlannerExecutorCriticAgentGADKInference = None
        self.gadk_planner_executor_agent_inference : PlannerExecutorAgentGADKInference = None
        self.gadk_react_critic_agent_inference : ReactCriticAgentGADKInference = None
        self.gadk_meta_agent_inference : MetaAgentGADKInference = None
        self.gadk_planner_meta_agent_inference : PlannerMetaAgentGADKInference = None

        self.centralized_agent_inference: CentralizedAgentInference = None
        
        # Pipeline repositories and services
        self.pipeline_repo: PipelineRepository = None
        self.pipeline_run_repo: PipelineRunRepository = None
        self.pipeline_steps_repo: PipelineStepsRepository = None
        self.pipeline_service: PipelineService = None
        self.pipeline_inference: PipelineInference = None
        self.agent_pipeline_mapping_repo: AgentPipelineMappingRepository = None
        # Tool generation code versioning
        self.tool_generation_code_version_repo: ToolGenerationCodeVersionRepository = None
        self.tool_generation_code_version_service: ToolGenerationCodeVersionService = None
        
        # Tool generation conversation history
        self.tool_generation_conversation_history_repo: ToolGenerationConversationHistoryRepository = None
        self.tool_generation_conversation_history_service: ToolGenerationConversationHistoryService = None
        # Knowledgebase repositories and service
        self.knowledgebase_repo = None
        self.agent_kb_mapping_repo = None
        self.knowledgebase_service = None
        self.postgres_vector_store = None
        
        # Authentication repositories
        self.user_repo: UserRepository = None
        self.role_repo: RoleRepository = None
        self.department_repo: DepartmentRepository = None
        self.user_dept_mapping_repo: UserDepartmentMappingRepository = None
        self.approval_permission_repo: ApprovalPermissionRepository = None
        self.audit_log_repo: AuditLogRepository = None
        self.refresh_token_repo: RefreshTokenRepository = None
        self.multi_db_connection_manager: MultiDBConnectionRepository = None

        # Admin Configuration
        self.admin_config_repo: AdminConfigRepository = None
        self.admin_config_service: AdminConfigService = None

        # Authentication services
        self.auth_service: AuthService = None
        self.authorization_service: AuthorizationService = None
        self.role_access_service: RoleAccessService = None

        # Initialize the file manager with default base directory
        self.file_manager: FileManager = None
        self.tool_file_manager: ToolFileManager = None
        
        # Secrets and keys handlers
        self.secrets_handler = None
        self.public_keys_handler = None

        self.embedding_model: SentenceTransformer = None
        self.cross_encoder: CrossEncoder = None
        self.episodic_memory_manager: EpisodicMemoryManager = None
       # self.storage_provider: str = os.getenv("STORAGE_PROVIDER", "")
        self.vm_management_service: VMManagementService = None

        # Tool Export/Import
        self.tool_export_import_service: ToolExportImportService = None


    async def initialize_services(self):
        """
        Initializes all database connections, repositories, and services.
        This method is called once during application startup.
        """
        log.info("AppContainer: Initializing all services and repositories.")

        # 1. Initialize DatabaseManager
        self.db_manager = DatabaseManager()

        # 2. Check and Create Databases (Administrative Task)
        # This ensures the databases exist before we try to connect pools to them.
        await self.db_manager.check_and_create_databases(required_db_names=app_config.postgres_db.required_databases)
        log.info("AppContainer: All required databases checked/created.")

        # 3. Connect to all required database pools
        # Pass the list of all databases to connect to.
        pool_config = app_config.postgres_db.pool_config

        await self.db_manager.connect(
                        db_names=app_config.postgres_db.primary_databases,
                        min_size=pool_config.min_size,
                        max_size=pool_config.max_size, # Default pool sizes
                        db_main_min_size=pool_config.main_db_min_size,
                        db_main_max_size=pool_config.main_db_max_size       # Custom sizes for main DB or agentic_workflow_as_service_database
                    )
        log.info("AppContainer: All database connection pools established.")

        # Get pools for initialization
        # Repositories only handle raw DB operations.
        main_pool = await self.db_manager.get_pool(DatabaseName.MAIN.db_name)
        # EXPORT:EXCLUDE:START
        feedback_learning_pool = await self.db_manager.get_pool(DatabaseName.FEEDBACK_LEARNING.db_name)
        recycle_pool = await self.db_manager.get_pool(DatabaseName.RECYCLE.db_name)
        # EXPORT:EXCLUDE:END
        # EXPORT:INCLUDE:START
        # feedback_learning_pool = recycle_pool = main_pool
        # EXPORT:INCLUDE:END
        logs_pool = await self.db_manager.get_pool(DatabaseName.EVALUATION_LOGS.db_name)
        login_pool = await self.db_manager.get_pool(DatabaseName.LOGIN.db_name)

        # Migrating the data from different database to current
        # 4. Initialize Repositories
        self.tag_repo = TagRepository(pool=main_pool, login_pool=login_pool)
        self.tag_tool_mapping_repo = TagToolMappingRepository(pool=main_pool, login_pool=login_pool)
        self.tag_agent_mapping_repo = TagAgentMappingRepository(pool=main_pool, login_pool=login_pool)
        self.tool_repo = ToolRepository(pool=main_pool, login_pool=login_pool)
        self.mcp_tool_repo = McpToolRepository(pool=main_pool, login_pool=login_pool)
        self.recycle_mcp_tool_repo = RecycleMcpToolRepository(pool=recycle_pool, login_pool=login_pool)
        self.tool_agent_mapping_repo = ToolAgentMappingRepository(pool=main_pool, login_pool=login_pool)
        self.recycle_tool_repo = RecycleToolRepository(pool=recycle_pool, login_pool=login_pool)
        self.agent_repo = AgentRepository(pool=main_pool, login_pool=login_pool)
        self.recycle_agent_repo = RecycleAgentRepository(pool=recycle_pool, login_pool=login_pool)
        self.chat_history_repo = ChatHistoryRepository(pool=main_pool, login_pool=login_pool)
        self.feedback_learning_repo = FeedbackLearningRepository(pool=feedback_learning_pool, login_pool=login_pool)
        self.evaluation_data_repo = EvaluationDataRepository(pool=logs_pool, login_pool=login_pool, agent_repo=self.agent_repo)
        self.tool_evaluation_metrics_repo = ToolEvaluationMetricsRepository(pool=logs_pool, login_pool=login_pool, agent_repo= self.agent_repo)
        self.agent_evaluation_metrics_repo = AgentEvaluationMetricsRepository(pool=logs_pool, login_pool=login_pool, agent_repo= self.agent_repo)
        self.agent_metadata_repo = AgentMetadataRepository(pool=logs_pool, login_pool=login_pool)
        self.agent_data_repo = AgentDataTableRepository(pool=logs_pool, login_pool=login_pool)
        # EXPORT:EXCLUDE:START
        self.export_repo = ExportAgentRepository(pool=main_pool, login_pool=login_pool)
        # EXPORT:EXCLUDE:END
        self.chat_state_history_manager_repo = ChatStateHistoryManagerRepository(pool=main_pool, login_pool=login_pool)
        
        # Initialize pipeline repositories
        self.pipeline_repo = PipelineRepository(pool=main_pool, login_pool=login_pool)
        self.pipeline_run_repo = PipelineRunRepository(pool=main_pool, login_pool=login_pool)
        self.pipeline_steps_repo = PipelineStepsRepository(pool=main_pool, login_pool=login_pool)
        self.agent_pipeline_mapping_repo = AgentPipelineMappingRepository(pool=main_pool, login_pool=login_pool)
        await self.agent_pipeline_mapping_repo.migrate_pipelines_to_agent_mappings()
        # Initialize tool generation code version repository
        self.tool_generation_code_version_repo = ToolGenerationCodeVersionRepository(pool=main_pool, login_pool=login_pool)
        
        # Initialize tool generation conversation history repository
        self.tool_generation_conversation_history_repo = ToolGenerationConversationHistoryRepository(pool=main_pool, login_pool=login_pool)
        # Initialize knowledgebase repositories
        self.knowledgebase_repo = KnowledgebaseRepository(pool=main_pool, login_pool=login_pool)
        self.agent_kb_mapping_repo = AgentKnowledgebaseMappingRepository(pool=main_pool, login_pool=login_pool)
        
        # Initialize PostgresVectorStoreJSONB for vector embeddings
        self.postgres_vector_store = PostgresVectorStoreJSONB(pool=main_pool)
        # self.user_agent_access_repo = UserAgentAccessRepository(pool=main_pool, login_pool=login_pool)
        self.group_repo = GroupRepository(pool=main_pool, login_pool=login_pool)
        self.group_secrets_repo = GroupSecretsRepository(pool=main_pool, login_pool=login_pool)

        # Initialize authentication repositories
        self.user_repo = UserRepository(pool=login_pool)
        self.role_repo = RoleRepository(pool=login_pool)
        self.department_repo = DepartmentRepository(pool=login_pool)
        self.user_dept_mapping_repo = UserDepartmentMappingRepository(pool=login_pool)
        self.approval_permission_repo = ApprovalPermissionRepository(pool=login_pool)
        self.audit_log_repo = AuditLogRepository(pool=login_pool)
        self.refresh_token_repo = RefreshTokenRepository(pool=login_pool)

        # Initialize admin configuration repository and service
        self.admin_config_repo = AdminConfigRepository(pool=main_pool, login_pool=login_pool)
        self.admin_config_service = AdminConfigService(admin_config_repo=self.admin_config_repo)
        
        
        # Initialize tool access control repository (in login database)
        self.user_access_key_repo = UserAccessKeyRepository(pool=login_pool)
        
        # Initialize access key definitions repository (in main database)
        self.access_key_definitions_repo = AccessKeyDefinitionsRepository(pool=main_pool)
        
        # Initialize tool access key mapping repository (in main database)
        self.tool_access_key_mapping_repo = ToolAccessKeyMappingRepository(pool=main_pool, login_pool=login_pool)
        
        # Initialize sharing repositories (in main database)
        self.tool_sharing_repo = ToolDepartmentSharingRepository(pool=main_pool, login_pool=login_pool)
        self.agent_sharing_repo = AgentDepartmentSharingRepository(pool=main_pool, login_pool=login_pool)
        self.mcp_tool_sharing_repo = McpToolDepartmentSharingRepository(pool=main_pool, login_pool=login_pool)
        self.kb_sharing_repo = KbDepartmentSharingRepository(pool=main_pool, login_pool=login_pool)
        # Set tool sharing repos on agent sharing repo for cascade sharing (when agent is shared, its tools and KBs are shared too)
        self.agent_sharing_repo.set_tool_sharing_repo(self.tool_sharing_repo)
        self.agent_sharing_repo.set_mcp_tool_sharing_repo(self.mcp_tool_sharing_repo)
        self.agent_sharing_repo.set_kb_sharing_repo(self.kb_sharing_repo)
        
        log.info("AppContainer: All repositories initialized.")

        # 5. Initialize Utility Processors
        self.tool_code_processor = ToolCodeProcessor()
        self.tool_file_manager = ToolFileManager(pool=main_pool) 
        log.info("AppContainer: Utility processors initialized.")

        # 6. Initialize Services (Order matters for dependencies)
        # Services contain business logic and orchestrate repository calls.
        # EXPORT:EXCLUDE:START
        self.export_service = ExportService(export_repo=self.export_repo)
        # EXPORT:EXCLUDE:END
        self.model_service = ModelService(chat_state_history_manager=self.chat_state_history_manager_repo)
        self.tag_service = TagService(
            tag_repo=self.tag_repo,
            tag_tool_mapping_repo=self.tag_tool_mapping_repo,
            tag_agent_mapping_repo=self.tag_agent_mapping_repo
        )
        self.mcp_tool_service = McpToolService( # Initialize McpToolService
            mcp_tool_repo=self.mcp_tool_repo,
            recycle_mcp_tool_repo=self.recycle_mcp_tool_repo,
            tag_service=self.tag_service,
            tool_agent_mapping_repo=self.tool_agent_mapping_repo,
            agent_repo=self.agent_repo,
            mcp_tool_sharing_repo=self.mcp_tool_sharing_repo
        )
        self.tool_service = ToolService(
            tool_repo=self.tool_repo,
            recycle_tool_repo=self.recycle_tool_repo,
            tool_agent_mapping_repo=self.tool_agent_mapping_repo,
            tag_service=self.tag_service,
            tool_code_processor=self.tool_code_processor,
            agent_repo=self.agent_repo,
            model_service=self.model_service,
            mcp_tool_service=self.mcp_tool_service,
            tool_file_manager=self.tool_file_manager,
            tool_access_key_mapping_repo=self.tool_access_key_mapping_repo,
            access_key_definitions_repo=self.access_key_definitions_repo,
            tool_sharing_repo=self.tool_sharing_repo,
            department_repo=self.department_repo
        )
        
        # Initialize knowledgebase service before agent service (needed by AgentServiceUtils)
        self.knowledgebase_service = KnowledgebaseService(
            knowledgebase_repo=self.knowledgebase_repo,
            agent_kb_mapping_repo=self.agent_kb_mapping_repo,
            vector_store=self.postgres_vector_store,
            kb_sharing_repo=self.kb_sharing_repo
        )
        
        self.tool_export_import_service = ToolExportImportService(
            tool_service=self.tool_service,
            mcp_tool_service=self.mcp_tool_service,
            model_service=self.model_service,
            tag_service=self.tag_service,
        )
        log.info("AppContainer: ToolExportImportService initialized.")

        self.agent_service_utils = AgentServiceUtils(
            agent_repo=self.agent_repo,
            recycle_agent_repo=self.recycle_agent_repo,
            tool_service=self.tool_service,
            tag_service=self.tag_service,
            model_service=self.model_service,
            knowledgebase_service=self.knowledgebase_service,
            agent_pipeline_mapping_repo=self.agent_pipeline_mapping_repo,
            pipeline_repo=self.pipeline_repo,
            agent_sharing_repo=self.agent_sharing_repo,
            department_repo=self.department_repo
        )

        # Initialize authentication services FIRST (before ChatService needs it)
        self.auth_service = AuthService(
            user_repo=self.user_repo,
            audit_repo=self.audit_log_repo,
            refresh_repo=self.refresh_token_repo,
            department_repo=self.department_repo,
            user_dept_mapping_repo=self.user_dept_mapping_repo
        )
        self.authorization_service = AuthorizationService(
            user_repo=self.user_repo,
            approval_repo=self.approval_permission_repo,
            audit_repo=self.audit_log_repo,
            role_repo=self.role_repo
        )
        self.role_access_service = RoleAccessService(
            role_repo=self.role_repo,
            user_repo=self.user_repo,
            audit_repo=self.audit_log_repo,
            department_repo=self.department_repo
        )
        self.department_service = DepartmentService(
            department_repo=self.department_repo,
            user_repo=self.user_repo,
            audit_repo=self.audit_log_repo,
            login_pool=login_pool,
            main_pool=main_pool,
            recycle_pool=recycle_pool,
            logs_pool=logs_pool,
            feedback_learning_pool=feedback_learning_pool
        )
        log.info("AppContainer: Authentication services initialized.")

        self.agent_service = AgentService(agent_service_utils=self.agent_service_utils)

        # EXPORT:EXCLUDE:START
        # Initialize Specialized Agent Onboarding Services
        self.react_agent_service = ReactAgentOnboard(agent_service_utils=self.agent_service_utils)
        self.multi_agent_service = MultiAgentOnboard(agent_service_utils=self.agent_service_utils)
        self.planner_executor_agent_service = PlannerExecutorAgentOnboard(agent_service_utils=self.agent_service_utils)
        self.react_critic_agent_service = ReactCriticAgentOnboard(agent_service_utils=self.agent_service_utils)
        self.meta_agent_service = MetaAgentOnboard(agent_service_utils=self.agent_service_utils)
        self.planner_meta_agent_service = PlannerMetaAgentOnboard(agent_service_utils=self.agent_service_utils)
        self.hybrid_agent_service = HybridAgentOnboard(agent_service_utils=self.agent_service_utils)
        # EXPORT:EXCLUDE:END
        log.info("AppContainer: Specialized agent onboarding services initialized.")

        self.chat_service = ChatService(
            chat_history_repo=self.chat_history_repo,
            chat_state_history_manager=self.chat_state_history_manager_repo,
            admin_config_service=self.admin_config_service,
            embedding_model = None,
            cross_encoder = None,
            tool_repo=self.tool_repo,
            agent_repo = self.agent_repo,
            authorization_service=self.authorization_service
        )
        self.feedback_learning_service = FeedbackLearningService(
            feedback_learning_repo=self.feedback_learning_repo,
            agent_service=self.agent_service
        )
        self.evaluation_service = EvaluationService(
            evaluation_data_repo=self.evaluation_data_repo,
            agent_evaluation_metrics_repo=self.agent_evaluation_metrics_repo,
            tool_evaluation_metrics_repo=self.tool_evaluation_metrics_repo,
            agent_service=self.agent_service,
            tool_service=self.tool_service
        )
        self.consistency_service = ConsistencyService(
            metadata_repo=self.agent_metadata_repo,
            data_repo=self.agent_data_repo,
            
        )
        
        self.user_agent_access_service = UserAgentAccessService(
            user_agent_access_repo=self.user_agent_access_repo
        )
        self.group_service = GroupService(
            group_repo=self.group_repo
        )
        
        # Initialize group secrets service
        # Note: secrets_handler import needed when available
        try:
            from src.utils.secrets_handler import UserSecretsManager, PublicKeysManager
            # Use the same db_config as used for other database connections
            secrets_db_config = {
                'host': os.getenv('POSTGRESQL_HOST', 'localhost'),
                'port': int(os.getenv('POSTGRESQL_PORT', 5432)),
                'database': os.getenv('DATABASE', 'iaf_database_3_latest'),  # Use main database for secrets
                'user': os.getenv('POSTGRESQL_USER'),
                'password': os.getenv('POSTGRESQL_PASSWORD')
            }
            secrets_handler = UserSecretsManager(secrets_db_config)
            public_keys_handler = PublicKeysManager(secrets_db_config)
            
            # Store handlers in class variables for global access
            self.secrets_handler = secrets_handler
            self.public_keys_handler = public_keys_handler
            
            self.group_secrets_service = GroupSecretsService(
                group_secrets_repo=self.group_secrets_repo,
                group_repo=self.group_repo,
                secrets_handler=secrets_handler
            )
        except ImportError:
            log.warning("Could not import keys_handler. Group secrets service will be limited.")
            self.secrets_handler = None
            self.public_keys_handler = None
            self.group_secrets_service = None
                
        # Initialize pipeline service
        self.pipeline_service = PipelineService(
            pipeline_repo=self.pipeline_repo,
            pipeline_run_repo=self.pipeline_run_repo,
            pipeline_steps_repo=self.pipeline_steps_repo,
            agent_pipeline_mapping_repo=self.agent_pipeline_mapping_repo,
            agent_service=self.agent_service
        )
        
        # Initialize tool generation code version service
        self.tool_generation_code_version_service = ToolGenerationCodeVersionService(
            code_version_repo=self.tool_generation_code_version_repo
        )
        
        # Initialize tool generation conversation history service
        self.tool_generation_conversation_history_service = ToolGenerationConversationHistoryService(
            conversation_repo=self.tool_generation_conversation_history_repo
        )

        log.info("AppContainer: Services initialized.")

        # Initialize Embeddings and Encoders using remote model server
        model_server_url = app_config.model_server_url
        self.embedding_model = None
        self.cross_encoder = None
        
        # Handle empty or None model server URL
        if not model_server_url or model_server_url.lower() == "none":
            log.info("MODEL_SERVER_URL not configured. Remote model features (embeddings, cross-encoder) will be unavailable.")
        else:
            try:
                client = ModelServerClient(model_server_url)
                if client.server_available:
                    remote_components = get_remote_models_and_utils(model_server_url)
                    self.embedding_model = remote_components["embedding_model"]
                    self.cross_encoder = remote_components["cross_encoder"]
                    log.info("Remote embeddings and cross-encoder initialized successfully.")
                else:
                    log.warning("Model server is not available. Remote embeddings and cross-encoder features will be unavailable.")
            except Exception as e:
                log.error(f"Failed to initialize remote models: {e}")

            self.chat_service.embedding_model = self.embedding_model
            self.chat_service.cross_encoder = self.cross_encoder

        # 7. Initialize Inference Services
        self.inference_utils = InferenceUtils(
            chat_service=self.chat_service,
            tool_service=self.tool_service,
            agent_service=self.agent_service,
            model_service=self.model_service,
            feedback_learning_service=self.feedback_learning_service,
            evaluation_service=self.evaluation_service,
            embedding_model=self.embedding_model,
            cross_encoder=self.cross_encoder,
            consistency_service=None
        )

        # Langgraph based Template Inferences
        self.react_agent_inference = ReactAgentInference(inference_utils=self.inference_utils)
        self.multi_agent_inference = MultiAgentInference(inference_utils=self.inference_utils)
        self.planner_executor_agent_inference = PlannerExecutorAgentInference(inference_utils=self.inference_utils)
        self.react_critic_agent_inference = ReactCriticAgentInference(inference_utils=self.inference_utils)
        self.meta_agent_inference = MetaAgentInference(inference_utils=self.inference_utils)
        self.planner_meta_agent_inference = PlannerMetaAgentInference(inference_utils=self.inference_utils)

        # Python based Template Inferences
        self.hybrid_agent_inference = HybridAgentInference(inference_utils=self.inference_utils)

        # Google ADK based Template Inferences
        self.gadk_react_agent_inference = ReactAgentGADKInference(inference_utils=self.inference_utils)
        self.gadk_planner_executor_critic_agent_inference = PlannerExecutorCriticAgentGADKInference(inference_utils=self.inference_utils)
        self.gadk_planner_executor_agent_inference = PlannerExecutorAgentGADKInference(inference_utils=self.inference_utils)
        self.gadk_react_critic_agent_inference = ReactCriticAgentGADKInference(inference_utils=self.inference_utils)
        self.gadk_meta_agent_inference = MetaAgentGADKInference(inference_utils=self.inference_utils)
        self.gadk_planner_meta_agent_inference = PlannerMetaAgentGADKInference(inference_utils=self.inference_utils)

        self.centralized_agent_inference = CentralizedAgentInference(
            # Langgraph
            react_agent_inference=self.react_agent_inference,
            multi_agent_inference=self.multi_agent_inference,
            planner_executor_agent_inference=self.planner_executor_agent_inference,
            react_critic_agent_inference=self.react_critic_agent_inference,
            meta_agent_inference=self.meta_agent_inference,
            planner_meta_agent_inference=self.planner_meta_agent_inference,

            # Python
            hybrid_agent_inference=self.hybrid_agent_inference,

            # Google ADK
            gadk_react_agent_inference=self.gadk_react_agent_inference,
            gadk_planner_executor_critic_agent_inference=self.gadk_planner_executor_critic_agent_inference,
            gadk_planner_executor_agent_inference=self.gadk_planner_executor_agent_inference,
            gadk_react_critic_agent_inference=self.gadk_react_critic_agent_inference,
            gadk_meta_agent_inference=self.gadk_meta_agent_inference,
            gadk_planner_meta_agent_inference=self.gadk_planner_meta_agent_inference,

            inference_utils=self.inference_utils
        )
        log.info("AppContainer: Inference services initialized.")
        
        # Initialize Pipeline Inference
        self.pipeline_inference = PipelineInference(
            inference_utils=self.inference_utils,
            pipeline_service=self.pipeline_service,
            centralized_agent_inference=self.centralized_agent_inference
        )
        log.info("AppContainer: Pipeline inference initialized.")

        self.core_evaluation_service = CoreEvaluationService(
            evaluation_service=self.evaluation_service,
            centralized_agent_inference=self.centralized_agent_inference,
            model_service=self.model_service
        )
        self.core_consistency_service = CoreConsistencyEvaluationService(
            consistency_service=self.consistency_service,
            model_service=self.model_service,
            centralized_agent_inference=self.centralized_agent_inference
        )

        self.core_robustness_service = CoreRobustnessEvaluationService(
            consistency_service=self.consistency_service,
            model_service=self.model_service,
            centralized_agent_inference=self.centralized_agent_inference,
            react_agent_inference=self.react_agent_inference
        )

        self.multi_db_connection_repo = MultiDBConnectionRepository(pool=main_pool)

        self.file_manager = FileManager()
        
        self.vm_management_service = VMManagementService()

        # 8. Create Tables (if they don't exist)
        # Call create_tables_if_not_exists for each service/repository that manages tables.
        # Order matters for foreign key dependencies.
        
        # Create departments table first (required for foreign key references)
        try:
            await self.department_repo.create_table_if_not_exists()
            log.info("Departments table created successfully")
            await self.department_repo.initialize_default_department("SYSTEM")
            log.info("Default department initialized successfully")
        except Exception as e:
            log.error(f"Error initializing departments: {e}")
            raise

        # Create login_credential table BEFORE userdepartmentmapping (FK dependency)
        await self.user_repo.create_table_if_not_exists()
        await self.refresh_token_repo.create_table_if_not_exists()

        # Now create user-department mapping table (has FK to login_credential and departments)
        try:
            await self.user_dept_mapping_repo.create_table_if_not_exists()
            log.info("User-department mapping table created successfully")
        except Exception as e:
            log.error(f"Error initializing user-department mapping: {e}")
            raise

        # Initialize default roles for departments using clean department-based design
        try:
            await self.department_repo.initialize_default_department_roles("SYSTEM")
            log.info("Default department roles initialized successfully")
        except Exception as e:
            log.error(f"Error initializing department roles: {e}")
            raise

        # Create role management tables and initialize default data
        try:
            await self.role_repo.create_tables_if_not_exists()
            log.info("Role tables created successfully")
            await self.role_repo.initialize_default_roles_and_permissions("SYSTEM")
            log.info("Default roles and permissions initialized successfully")
        except Exception as e:
            log.error(f"Error initializing roles: {e}")
            raise

        await self.approval_permission_repo.create_table_if_not_exists()
        await self.audit_log_repo.create_table_if_not_exists()
        await self.admin_config_repo.create_table_if_not_exists()
        await self.tag_repo.create_table_if_not_exists()
        await self.tool_repo.create_table_if_not_exists()
        await self.mcp_tool_repo.create_table_if_not_exists()
        await self.agent_repo.create_table_if_not_exists()
        await self.chat_history_repo.create_agent_conversation_summary_table()
        await self.feedback_learning_repo.create_tables_if_not_exists()
        await self.evaluation_service.create_evaluation_tables_if_not_exists()
        await self.consistency_service.create_evaluation_table_if_not_exists()
        await self.multi_db_connection_repo.create_db_connections_table_if_not_exists() # Create multi-DB connections table
        # EXPORT:EXCLUDE:START
        await self.export_repo.create_table_if_not_exists()
        # EXPORT:EXCLUDE:END
        await self.chat_state_history_manager_repo.create_table_if_not_exists()
        
        # Pipeline tables
        await self.pipeline_repo.create_table_if_not_exists()
        
        # Tool generation code version table
        await self.tool_generation_code_version_repo.create_table_if_not_exists()
        
        # Tool generation conversation history table
        await self.tool_generation_conversation_history_repo.create_table_if_not_exists()
        # Knowledgebase tables
        await self.knowledgebase_repo.create_table_if_not_exists()
        await self.postgres_vector_store.create_table()  # Create vector_embeddings_jsonb table
        # await self.user_agent_access_repo.create_table_if_not_exists()
        await self.group_repo.create_table_if_not_exists()
        await self.group_secrets_repo.create_table_if_not_exists()
        await self.user_access_key_repo.create_table_if_not_exists()  # Tool access control table
        await self.tool_access_key_mapping_repo.create_table_if_not_exists()  # Tool-to-access-key mapping table
        await self.access_key_definitions_repo.create_table_if_not_exists()  # Master access key definitions table
        await self.tool_sharing_repo.create_table_if_not_exists()  # Tool sharing across departments
        await self.agent_sharing_repo.create_table_if_not_exists()  # Agent sharing across departments
        await self.mcp_tool_sharing_repo.create_table_if_not_exists()  # MCP tool sharing across departments
        await self.kb_sharing_repo.create_table_if_not_exists()  # KB sharing across departments

        # Mapping tables (depend on main tables)
        await self.tag_tool_mapping_repo.create_table_if_not_exists()
        await self.tag_agent_mapping_repo.create_table_if_not_exists()
        await self.tool_agent_mapping_repo.create_table_if_not_exists()
        await self.agent_pipeline_mapping_repo.create_table_if_not_exists()  # Agent-Pipeline mapping table
        await self.agent_kb_mapping_repo.create_table_if_not_exists()  # Agent-KB mapping table

        # EXPORT:EXCLUDE:START
        await insert_sample_tools(self.tool_service)
        await insert_sample_agents(self.agent_service)
        await insert_sample_pipelines(self.pipeline_service)
        # EXPORT:EXCLUDE:END
        # EXPORT:INCLUDE:START
        # await load_exported_data(
        #     tool_repo=self.tool_repo,
        #     agent_repo=self.agent_repo,
        #     mcp_tool_repo=self.mcp_tool_repo,
        #     tag_tool_mapping_repo=self.tag_tool_mapping_repo,
        #     tag_agent_mapping_repo=self.tag_agent_mapping_repo,
        #     tag_repo=self.tag_repo,
        # )
        # EXPORT:INCLUDE:END

        # Recycle tables (depend on nothing but their pool)
        await self.recycle_tool_repo.create_table_if_not_exists()
        await self.recycle_mcp_tool_repo.create_table_if_not_exists()
        await self.recycle_agent_repo.create_table_if_not_exists()

        # 9. Load all models into cache (optional, for pre-warming)

        await self.model_service.load_all_models_into_cache()
        log.info("AppContainer: All models loaded into cache.")

        log.info("AppContainer: All database tables checked/created.")

        # EXPORT:EXCLUDE:START
        # 10. Extract frontend code from bundled ZIP for agent exports
        AgentExporter.extract_frontend_from_zip()
        log.info("AppContainer: Frontend extraction completed.")

        # 11. Running necessary data migrations/fixes
        # Delete the 'models' table from main_pool if it exists
        # async with main_pool.acquire() as conn:
        #     await conn.execute("DROP TABLE IF EXISTS models;")
        # log.info("AppContainer: 'models' table dropped from main database if it existed.")

        await self.tag_tool_mapping_repo.drop_tool_id_fk_constraint()
        await self.tool_service.fix_tool_agent_mapping_for_meta_agents()
        # EXPORT:EXCLUDE:END
        log.info("AppContainer: Database data migrations/fixes completed.")

    async def shutdown_services(self):
        """
        Shuts down all services and closes database connections.
        This method is called once during application shutdown.
        """
        log.info("AppContainer: Shutting down all services and closing database connections.")
        if self.db_manager:
            await self.db_manager.close()
        if self.chat_service and self.chat_service.gadk_session_service:
            self.chat_service.gadk_session_service.db_engine.dispose(close=True)
            log.info("AppContainer: Google ADK database connections closed.")

        log.info("AppContainer: Shutdown complete. Database connections closed.")


# Create a single, global instance of the AppContainer
app_container = AppContainer()

