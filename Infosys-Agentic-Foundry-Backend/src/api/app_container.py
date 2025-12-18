# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
from dotenv import load_dotenv
from src.auth.auth_service import AuthService
from src.auth.authorization_service import AuthorizationService
from src.auth.repositories import ApprovalPermissionRepository, AuditLogRepository, UserRepository, RefreshTokenRepository
from src.utils.remote_model_client import RemoteCrossEncoder as CrossEncoder

from src.database.database_manager import DatabaseManager, REQUIRED_DATABASES
from src.database.repositories import (
    TagRepository, TagToolMappingRepository, TagAgentMappingRepository,
    ToolRepository, McpToolRepository, ToolAgentMappingRepository, RecycleToolRepository,
    AgentRepository, RecycleAgentRepository, ChatHistoryRepository,
    FeedbackLearningRepository, EvaluationDataRepository,
    ToolEvaluationMetricsRepository, AgentEvaluationMetricsRepository,
    ExportAgentRepository, AgentMetadataRepository, AgentDataTableRepository, ChatStateHistoryManagerRepository
)
from src.tools.tool_code_processor import ToolCodeProcessor
from src.database.services import (
    TagService, McpToolService, ToolService, AgentServiceUtils, AgentService, ChatService,
    FeedbackLearningService, EvaluationService, ExportService, ConsistencyService
)
from src.database.core_evaluation_service import CoreEvaluationService, CoreConsistencyEvaluationService, CoreRobustnessEvaluationService
from src.models.model_service import ModelService
from src.agent_templates import (
    ReactAgentOnboard, MultiAgentOnboard, PlannerExecutorAgentOnboard,
    ReactCriticAgentOnboard, MetaAgentOnboard, PlannerMetaAgentOnboard
)
from src.agent_templates.simple_ai_agent_onboard import SimpleAIAgentOnboard
from src.agent_templates.hybrid_agent_onboard import HybridAgentOnboard
from src.inference import (
    InferenceUtils, ReactAgentInference, MultiAgentInference, PlannerExecutorAgentInference,
    ReactCriticAgentInference, MetaAgentInference, PlannerMetaAgentInference, CentralizedAgentInference
)
from src.inference.python_based_inference.simple_ai_agent_inference import SimpleAIAgentInference
from src.inference.python_based_inference.hybrid_agent_inference import HybridAgentInference

from src.utils.file_manager import FileManager
from MultiDBConnection_Manager import MultiDBConnectionRepository

from telemetry_wrapper import logger as log

from src.inference.inference_utils import EpisodicMemoryManager
from src.utils.remote_model_client import RemoteSentenceTransformer as SentenceTransformer
from src.utils.remote_model_client import get_remote_models_and_utils, ModelServerClient


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
        # Specialized Agent Onboarding Services (these are typically exposed via Depends for endpoints)
        self.react_agent_service: ReactAgentOnboard = None
        self.multi_agent_service: MultiAgentOnboard = None
        self.planner_executor_agent_service: PlannerExecutorAgentOnboard = None
        self.react_critic_agent_service: ReactCriticAgentOnboard = None
        self.meta_agent_service: MetaAgentOnboard = None
        self.planner_meta_agent_service: PlannerMetaAgentOnboard = None
        self.simple_ai_agent_service: SimpleAIAgentOnboard = None
        self.hybrid_agent_service: HybridAgentOnboard = None

        # Inference Services (these are typically exposed via Depends for endpoints)

        # Langgraph based Template Inferences
        self.react_agent_inference: ReactAgentInference = None
        self.multi_agent_inference: MultiAgentInference = None
        self.planner_executor_agent_inference: PlannerExecutorAgentInference = None
        self.react_critic_agent_inference: ReactCriticAgentInference = None
        self.meta_agent_inference: MetaAgentInference = None
        self.planner_meta_agent_inference: PlannerMetaAgentInference = None

        # Python based Template Inferences
        self.simple_ai_agent_inference: SimpleAIAgentInference = None
        self.hybrid_agent_inference: HybridAgentInference = None

        # Google ADK based Template Inferences

        self.centralized_agent_inference: CentralizedAgentInference = None
        # Authentication repositories
        self.user_repo: UserRepository = None
        self.approval_permission_repo: ApprovalPermissionRepository = None
        self.audit_log_repo: AuditLogRepository = None
        self.refresh_token_repo: RefreshTokenRepository = None
        self.multi_db_connection_manager: MultiDBConnectionRepository = None

        # Initialize the file manager with default base directory
        self.file_manager: FileManager = None

        self.embedding_model: SentenceTransformer = None
        self.cross_encoder: CrossEncoder = None
        self.episodic_memory_manager: EpisodicMemoryManager = None


    async def initialize_services(self):
        """
        Initializes all database connections, repositories, and services.
        This method is called once during application startup.
        """
        log.info("AppContainer: Initializing all services and repositories.")

        # 1. Initialize DatabaseManager
        # The alias 'db_main' is used for the primary database pool, so both alias or main database
        # name can be used to connect, get or close the connection pool for main database.
        self.db_manager = DatabaseManager(alias_to_main_db='db_main')

        # 2. Check and Create Databases (Administrative Task)
        # This ensures the databases exist before we try to connect pools to them.
        await self.db_manager.check_and_create_databases(required_db_names=REQUIRED_DATABASES)
        log.info("AppContainer: All required databases checked/created.")

        # 3. Connect to all required database pools
        # Pass the list of all databases to connect to.
        connection_pool_size = os.getenv("CONNECTION_POOL_SIZE", "low")
        min_size, max_size, db_main_min_size, db_main_max_size = 2, 3, None, None
        if connection_pool_size == "medium":
            min_size, max_size, db_main_min_size, db_main_max_size = 12, 15, 17, 20
        elif connection_pool_size == "high":
            min_size, max_size, db_main_min_size, db_main_max_size = 20, 25, None, None

        DB_USED = REQUIRED_DATABASES[:5]
        await self.db_manager.connect(db_names=DB_USED,
                                      min_size=min_size, max_size=max_size, # Default pool sizes
                                      db_main_min_size=db_main_min_size, db_main_max_size=db_main_max_size) # Custom sizes for main DB or agentic_workflow_as_service_database
        log.info("AppContainer: All database connection pools established.")

        # Get pools for initialization
        # Repositories only handle raw DB operations.
        main_pool = await self.db_manager.get_pool(DB_USED[0])
        feedback_learning_pool = await self.db_manager.get_pool(DB_USED[1])
        logs_pool = await self.db_manager.get_pool(DB_USED[2])
        recycle_pool = await self.db_manager.get_pool(DB_USED[3])
        login_pool = await self.db_manager.get_pool(DB_USED[4])

        # Migrating the data from different database to current
        # 4. Initialize Repositories
        self.tag_repo = TagRepository(pool=main_pool, login_pool=login_pool)
        self.tag_tool_mapping_repo = TagToolMappingRepository(pool=main_pool, login_pool=login_pool)
        self.tag_agent_mapping_repo = TagAgentMappingRepository(pool=main_pool, login_pool=login_pool)
        self.tool_repo = ToolRepository(pool=main_pool, login_pool=login_pool)
        self.mcp_tool_repo = McpToolRepository(pool=main_pool, login_pool=login_pool)
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
        self.export_repo = ExportAgentRepository(pool=main_pool, login_pool=login_pool)
        self.chat_state_history_manager_repo = ChatStateHistoryManagerRepository(pool=main_pool, login_pool=login_pool)
        
        # Initialize authentication repositories
        self.user_repo = UserRepository(pool=login_pool)
        self.approval_permission_repo = ApprovalPermissionRepository(pool=login_pool)
        self.audit_log_repo = AuditLogRepository(pool=login_pool)
        self.refresh_token_repo = RefreshTokenRepository(pool=login_pool)
        log.info("AppContainer: All repositories initialized.")

        # 5. Initialize Utility Processors
        self.tool_code_processor = ToolCodeProcessor()
        log.info("AppContainer: Utility processors initialized.")

        # 6. Initialize Services (Order matters for dependencies)
        # Services contain business logic and orchestrate repository calls.
        self.export_service = ExportService(export_repo=self.export_repo)
        self.model_service = ModelService(chat_state_history_manager=self.chat_state_history_manager_repo)
        self.tag_service = TagService(
            tag_repo=self.tag_repo,
            tag_tool_mapping_repo=self.tag_tool_mapping_repo,
            tag_agent_mapping_repo=self.tag_agent_mapping_repo
        )
        self.mcp_tool_service = McpToolService( # Initialize McpToolService
            mcp_tool_repo=self.mcp_tool_repo,
            tag_service=self.tag_service,
            tool_agent_mapping_repo=self.tool_agent_mapping_repo,
            agent_repo=self.agent_repo
        )
        self.tool_service = ToolService(
            tool_repo=self.tool_repo,
            recycle_tool_repo=self.recycle_tool_repo,
            tool_agent_mapping_repo=self.tool_agent_mapping_repo,
            tag_service=self.tag_service,
            tool_code_processor=self.tool_code_processor,
            agent_repo=self.agent_repo,
            model_service=self.model_service,
            mcp_tool_service=self.mcp_tool_service
        )
        self.agent_service_utils = AgentServiceUtils(
            agent_repo=self.agent_repo,
            recycle_agent_repo=self.recycle_agent_repo,
            tool_service=self.tool_service,
            tag_service=self.tag_service,
            model_service=self.model_service
        )

        self.agent_service = AgentService(agent_service_utils=self.agent_service_utils)
        # Initialize Specialized Agent Onboarding Services
        self.react_agent_service = ReactAgentOnboard(agent_service_utils=self.agent_service_utils)
        self.multi_agent_service = MultiAgentOnboard(agent_service_utils=self.agent_service_utils)
        self.planner_executor_agent_service = PlannerExecutorAgentOnboard(agent_service_utils=self.agent_service_utils)
        self.react_critic_agent_service = ReactCriticAgentOnboard(agent_service_utils=self.agent_service_utils)
        self.meta_agent_service = MetaAgentOnboard(agent_service_utils=self.agent_service_utils)
        self.planner_meta_agent_service = PlannerMetaAgentOnboard(agent_service_utils=self.agent_service_utils)
        self.simple_ai_agent_service = SimpleAIAgentOnboard(agent_service_utils=self.agent_service_utils)
        self.hybrid_agent_service = HybridAgentOnboard(agent_service_utils=self.agent_service_utils)
        log.info("AppContainer: Specialized agent onboarding services initialized.")

        self.chat_service = ChatService(
            chat_history_repo=self.chat_history_repo,
            chat_state_history_manager=self.chat_state_history_manager_repo,
            embedding_model = None,
            cross_encoder = None,
            tool_repo=self.tool_repo,
            agent_repo = self.agent_repo
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
        # Initialize authentication services
        self.auth_service = AuthService(
            user_repo=self.user_repo,
            audit_repo=self.audit_log_repo,
            refresh_repo=self.refresh_token_repo
        )
        self.authorization_service = AuthorizationService(
            user_repo=self.user_repo,
            approval_repo=self.approval_permission_repo,
            audit_repo=self.audit_log_repo
        )

        log.info("AppContainer: Services initialized.")

        # Initialize Embeddings and Encoders using remote model server
        model_server_url = os.getenv("MODEL_SERVER_URL", "").strip()
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
        self.simple_ai_agent_inference = SimpleAIAgentInference(inference_utils=self.inference_utils)
        self.hybrid_agent_inference = HybridAgentInference(inference_utils=self.inference_utils)

        # Google ADK based Template Inferences

        self.centralized_agent_inference = CentralizedAgentInference(
            # Langgraph
            react_agent_inference=self.react_agent_inference,
            multi_agent_inference=self.multi_agent_inference,
            planner_executor_agent_inference=self.planner_executor_agent_inference,
            react_critic_agent_inference=self.react_critic_agent_inference,
            meta_agent_inference=self.meta_agent_inference,
            planner_meta_agent_inference=self.planner_meta_agent_inference,

            # Python
            simple_ai_agent_inference=self.simple_ai_agent_inference,
            hybrid_agent_inference=self.hybrid_agent_inference,

            # Google ADK

            inference_utils=self.inference_utils
        )
        log.info("AppContainer: Inference services initialized.")

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

        # 8. Create Tables (if they don't exist)
        # Call create_tables_if_not_exists for each service/repository that manages tables.
        # Order matters for foreign key dependencies.
        await self.user_repo.create_table_if_not_exists()
        await self.refresh_token_repo.create_table_if_not_exists()

        #Creating a guest Account
        try:
            await self.user_repo.create_user("guest@example.com", "Guest", "User")
            log.info(f"Guest User created")
        except Exception as e:
            log.info(f"Guest User already exists")

        await self.approval_permission_repo.create_table_if_not_exists()
        await self.audit_log_repo.create_table_if_not_exists()
        await self.tag_repo.create_table_if_not_exists()
        await self.tool_repo.create_table_if_not_exists()
        await self.mcp_tool_repo.create_table_if_not_exists()
        await self.agent_repo.create_table_if_not_exists()
        await self.chat_history_repo.create_agent_conversation_summary_table()
        await self.feedback_learning_repo.create_tables_if_not_exists()
        await self.evaluation_service.create_evaluation_tables_if_not_exists()
        await self.consistency_service.create_evaluation_table_if_not_exists()
        await self.multi_db_connection_repo.create_db_connections_table_if_not_exists() # Create multi-DB connections table
        await self.export_repo.create_table_if_not_exists()
        await self.chat_state_history_manager_repo.create_table_if_not_exists()

        # Mapping tables (depend on main tables)
        await self.tag_tool_mapping_repo.create_table_if_not_exists()
        await self.tag_agent_mapping_repo.create_table_if_not_exists()
        await self.tool_agent_mapping_repo.create_table_if_not_exists()

        # Recycle tables (depend on nothing but their pool)
        await self.recycle_tool_repo.create_table_if_not_exists()
        await self.recycle_agent_repo.create_table_if_not_exists()

        # 9. Load all models into cache (optional, for pre-warming)

        await self.model_service.load_all_models_into_cache()
        log.info("AppContainer: All models loaded into cache.")

        log.info("AppContainer: All database tables checked/created.")

        # 10. Running necessary data migrations/fixes
        # Delete the 'models' table from main_pool if it exists
        # async with main_pool.acquire() as conn:
        #     await conn.execute("DROP TABLE IF EXISTS models;")
        # log.info("AppContainer: 'models' table dropped from main database if it existed.")

        await self.tag_tool_mapping_repo.drop_tool_id_fk_constraint()
        await self.tool_service.fix_tool_agent_mapping_for_meta_agents()
        await self.feedback_learning_repo.migrate_agent_ids_to_hyphens()
        await self.mcp_tool_repo.migrate_file_mcp_tools_config()
        await self.agent_service.migrate_agent_ids_and_references()
        log.info("AppContainer: Database data migrations/fixes completed.")

    async def shutdown_services(self):
        """
        Shuts down all services and closes database connections.
        This method is called once during application shutdown.
        """
        log.info("AppContainer: Shutting down all services and closing database connections.")
        if self.db_manager:
            await self.db_manager.close()

        log.info("AppContainer: Shutdown complete. Database connections closed.")


# Create a single, global instance of the AppContainer
app_container = AppContainer()

