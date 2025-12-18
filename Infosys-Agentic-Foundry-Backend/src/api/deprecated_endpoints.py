# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import Literal, Optional, List, Union
from fastapi import APIRouter, Depends, Request, Query, UploadFile, File, BackgroundTasks, Form

from src.schemas import (
    ToolData, UpdateToolRequest, DeleteToolRequest, AgentOnboardingRequest,
    AgentInferenceRequest, TempAgentInferenceRequest, TempAgentInferenceHITLRequest,
    UpdateAgentRequest, DeleteAgentRequest, ChatSessionRequest, OldChatSessionsRequest,
    GroundTruthEvaluationRequest, ApprovalRequest, DBDisconnectRequest, QueryExecutionRequest,
    QueryGenerationRequest, MONGODBOperation
)
from src.database.services import ToolService, AgentService, ChatService, FeedbackLearningService, EvaluationService, ModelService
from src.database.core_evaluation_service import CoreEvaluationService
from src.inference.centralized_agent_inference import CentralizedAgentInference
from src.utils.file_manager import FileManager
from src.api.dependencies import ServiceProvider
from MultiDBConnection_Manager import MultiDBConnectionRepository


# Create an APIRouter instance for deprecated endpoints
router = APIRouter(tags=["Deprecated"], deprecated=True)


## ========================================= Tools Deprecated Endpoints =========================================

@router.post("/add-tool", summary="Deprecated: Use [ /tools/add ] instead")
async def temporary_add_tool_endpoint(fastapi_request: Request,
    tool_data: ToolData,
    tool_service: ToolService = Depends(ServiceProvider.get_tool_service)
):
    from src.api.tool_endpoints import add_tool_endpoint
    return await add_tool_endpoint(fastapi_request, tool_data, tool_service)

@router.get("/get-tools-search-paginated/", summary="Deprecated: Use [ /tools/get/search-paginated/ ] instead")
async def temporary_get_tools_by_search_paginated(fastapi_request: Request, search_value: str = None, page_number: int = 1, page_size: int = 10, tool_service: ToolService = Depends(ServiceProvider.get_tool_service)):
    from src.api.tool_endpoints import search_paginated_tools_endpoint
    return await search_paginated_tools_endpoint(fastapi_request, search_value, page_number, page_size, tool_service)

@router.post("/get-tools-by-list", summary="Deprecated: Use [ /tools/get/by-list ] instead")
async def temporary_get_tools_by_list(fastapi_request: Request, tool_ids: list[str], tool_service: ToolService = Depends(ServiceProvider.get_tool_service)):
    from src.api.tool_endpoints import get_tools_by_list_endpoint
    return await get_tools_by_list_endpoint(fastapi_request, tool_ids, tool_service)

@router.put("/update-tool/{tool_id}", summary="Deprecated: Use [ /tools/update/{tool_id} ] instead")
async def temporary_update_tool_endpoint(fastapi_request: Request, tool_id: str, request: UpdateToolRequest, tool_service: ToolService = Depends(ServiceProvider.get_tool_service)):
    from src.api.tool_endpoints import update_tool_endpoint
    return await update_tool_endpoint(fastapi_request, tool_id, request, tool_service=tool_service)

@router.delete("/delete-tool/{tool_id}", summary="Deprecated: Use [ /tools/delete/{tool_id} ] instead")
async def temporary_delete_tool_endpoint(fastapi_request: Request,tool_id: str, request: DeleteToolRequest, tool_service: ToolService = Depends(ServiceProvider.get_tool_service)):
    from src.api.tool_endpoints import delete_tool_endpoint
    return await delete_tool_endpoint(fastapi_request, tool_id, request, tool_service=tool_service)

## ==============================================================================================================================


## ========================================= Agents Deprecated Endpoints =========================================

@router.post("/onboard-agent", summary="Deprecated: Use [ /agents/onboard ] instead")
async def temporary_onboard_agent_endpoint(fastapi_request: Request, request: AgentOnboardingRequest):
    from src.api.agent_endpoints import onboard_agent_endpoint
    return await onboard_agent_endpoint(fastapi_request, request)

@router.get("/get-agent/{agent_id}", summary="Deprecated: Use [ /agents/get/{agent_id} ] instead")
async def temporary_get_agent_by_id_endpoint(fastapi_request: Request,agent_id: str, agent_service: AgentService = Depends(ServiceProvider.get_agent_service)):
    from src.api.agent_endpoints import get_agent_by_id_endpoint
    return await get_agent_by_id_endpoint(fastapi_request, agent_id, agent_service)

@router.post("/get-agents-by-list", summary="Deprecated: Use [ /agents/get/by-list ] instead")
async def temporary_get_agents_by_list(fastapi_request: Request, agent_ids: list[str], agent_service: AgentService = Depends(ServiceProvider.get_agent_service)):
    from src.api.agent_endpoints import get_agents_by_list_endpoint
    return await get_agents_by_list_endpoint(fastapi_request, agent_ids, agent_service)

@router.get("/get-agents-search-paginated/", summary="Deprecated: Use [ /agents/get/search-paginated/ ] instead")
async def temporary_get_agents_by_search_paginated(fastapi_request: Request, 
    agentic_application_type=None,
    search_value: str = None,
    page_number: int = 1,
    page_size: int = 10,
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service)
):
    from src.api.agent_endpoints import search_paginated_agents_endpoint
    return await search_paginated_agents_endpoint(
                            request=fastapi_request,
                            agentic_application_type=agentic_application_type,
                            search_value=search_value,
                            page_number=page_number,
                            page_size=page_size,
                            created_by=None,
                            agent_service=agent_service
                        )

@router.get("/get-agents-details-for-chat", summary="Deprecated: Use [ /agents/get/details-for-chat-interface ] instead")
async def temporary_get_agents_details(fastapi_request: Request, agent_service: AgentService = Depends(ServiceProvider.get_agent_service)):
    from src.api.agent_endpoints import get_agents_details_for_chat_interface_endpoint
    return await get_agents_details_for_chat_interface_endpoint(fastapi_request, agent_service)

@router.put("/update-agent", summary="Deprecated: Use [ /agents/update ] instead")
async def temporary_update_agent_endpoint(fastapi_request: Request, request: UpdateAgentRequest, agent_service: AgentService = Depends(ServiceProvider.get_agent_service)):
    from src.api.agent_endpoints import update_agent_endpoint
    return await update_agent_endpoint(fastapi_request, request, agent_service)

@router.delete("/react-agent/delete-agent/{agent_id}", summary="Deprecated: Use [ /agents/delete/{agent_id} ] instead")
@router.delete("/delete-agent/{agent_id}", summary="Deprecated: Use [ /agents/delete/{agent_id} ] instead")
async def temporary_delete_agent(fastapi_request: Request, agent_id: str, request: DeleteAgentRequest, agent_service: AgentService = Depends(ServiceProvider.get_agent_service)):
    from src.api.agent_endpoints import delete_agent_endpoint
    return await delete_agent_endpoint(
        request=fastapi_request,
        agent_id=agent_id,
        delete_request=request,
        agent_service=agent_service
    )

@router.get("/export-agents", summary="Deprecated: Use [ /agents/export ] instead")
async def temporary_export_agents_endpoint(
        request: Request,
        agent_ids: List[str] = Query(..., description="List of agent IDs to export"),
        user_email: Optional[str] = Query(None, description="Email of the user requesting the export"),
        background_tasks: BackgroundTasks = BackgroundTasks(),
    ):
    from src.api.agent_endpoints import export_agents_endpoint
    return await export_agents_endpoint(
        request=request,
        agent_ids=agent_ids,
        user_email=user_email,
        background_tasks=background_tasks
    )

## ==============================================================================================================================


## ========================================= Recycle Bin Deprecated Endpoints =========================================

@router.get("/recycle-bin/{param}", summary="Deprecated: Use [ /tools/recycle-bin/get ] for param=tool and [ /agents/recycle-bin/get ] for param=agent instead")
async def temporary_get_all_recycle_bin_tools_endpoint(fastapi_request: Request, param:Literal["tools", "agents"], user_email_id: str, agent_service: AgentService = Depends(ServiceProvider.get_agent_service)):
    if param == "tools":
        from src.api.tool_endpoints import get_all_tools_from_recycle_bin_endpoint
        return await get_all_tools_from_recycle_bin_endpoint(fastapi_request, user_email_id=user_email_id, tool_service=agent_service.tool_service)
    else:
        from src.api.agent_endpoints import get_all_agents_from_recycle_bin_endpoint
        return await get_all_agents_from_recycle_bin_endpoint(fastapi_request, user_email_id=user_email_id, agent_service=agent_service)

@router.post("/restore/{param}", summary="Deprecated: Use [ /tools/recycle-bin/restore/{tool_id} ] for param=tool and [ /agents/recycle-bin/restore/{agent_id} ] for param=agent instead")
async def temporary_restore_from_recycle_bin(fastapi_request: Request, param: Literal["tools", "agents"], item_id: str, user_email_id: str, agent_service: AgentService = Depends(ServiceProvider.get_agent_service)):
    if param == "tools":
        from src.api.tool_endpoints import restore_tool_endpoint
        return await restore_tool_endpoint(fastapi_request, tool_id=item_id, user_email_id=user_email_id, tool_service=agent_service.tool_service)
    else:
        from src.api.agent_endpoints import restore_agent_endpoint
        return await restore_agent_endpoint(fastapi_request, agent_id=item_id, user_email_id=user_email_id, agent_service=agent_service)

@router.delete("/delete/{param}", summary="Deprecated: Use [ /tools/recycle-bin/permanent-delete/{tool_id} ] for param=tool and [ /agents/recycle-bin/permanent-delete/{agent_id} ] for param=agent instead")
async def temporary_delete_from_recycle_bin(fastapi_request: Request, param: Literal["tools", "agents"], item_id: str, user_email_id: str, agent_service: AgentService = Depends(ServiceProvider.get_agent_service)):
    if param == "tools":
        from src.api.tool_endpoints import delete_tool_from_recycle_bin_endpoint
        return await delete_tool_from_recycle_bin_endpoint(fastapi_request, tool_id=item_id, user_email_id=user_email_id, tool_service=agent_service.tool_service)
    else:
        from src.api.agent_endpoints import delete_agent_from_recycle_bin_endpoint
        return await delete_agent_from_recycle_bin_endpoint(fastapi_request, agent_id=item_id, user_email_id=user_email_id, agent_service=agent_service)

## ==============================================================================================================================


## ========================================= Chats Deprecated Endpoints =========================================

@router.post("/planner-meta-agent/get-query-response", summary="Deprecated: Use [ /chat/inference ] instead")
@router.post("/meta-agent/get-query-response", summary="Deprecated: Use [ /chat/inference ] instead")
@router.post("/get-query-response", summary="Deprecated: Use [ /chat/inference ] instead || NOTE: Requires changes in payload's keys (interrupt_flag -> tool_verifier_flag, feedback -> tool_feedback)")
async def temporary_get_agent_response_endpoint(
                                fastapi_request: Request,
                                request: TempAgentInferenceRequest,
                                agent_inference: CentralizedAgentInference = Depends(ServiceProvider.get_centralized_agent_inference)
                            ):
    inference_request = AgentInferenceRequest(
        query=request.query,
        agentic_application_id=request.agentic_application_id,
        session_id=request.session_id,
        model_name=request.model_name,
        reset_conversation=request.reset_conversation,
        tool_verifier_flag=request.interrupt_flag,
        tool_feedback=request.feedback,
        prev_response=request.prev_response,
        knowledgebase_name=request.knowledgebase_name
    )
    from src.api.chat_endpoints import run_agent_inference_endpoint
    return await run_agent_inference_endpoint(
        request=fastapi_request,
        inference_request=inference_request,
        inference_service=agent_inference,
        feedback_learning_service=None
    )

@router.post("/planner-executor-agent/get-query-response-hitl-replanner", summary="Deprecated: Use [ /chat/inference ] instead || NOTE: Requires changes in payload's keys (interrupt_flag -> tool_verifier_flag, approval -> is_plan_approved, feedback -> plan_feedback) and addition of (plan_verifier_flag=True) key")
@router.post("/planner-executor-critic-agent/get-query-response-hitl-replanner", summary="Deprecated: Use [ /chat/inference ] instead || NOTE: Requires changes in payload's keys (interrupt_flag -> tool_verifier_flag, approval -> is_plan_approved, feedback -> plan_feedback) and addition of (plan_verifier_flag=True) key")
async def temporary_generate_response_with_hilt_endpoint(
                                                fastapi_request: Request,
                                                request: TempAgentInferenceHITLRequest,
                                                inference_service: CentralizedAgentInference = Depends(ServiceProvider.get_centralized_agent_inference),
                                                feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service)
                                            ):
    inference_request = AgentInferenceRequest(
        query=request.query,
        agentic_application_id=request.agentic_application_id,
        session_id=request.session_id,
        model_name=request.model_name,
        reset_conversation=request.reset_conversation,
        tool_verifier_flag=request.interrupt_flag,
        tool_feedback=request.tool_feedback,
        plan_verifier_flag=True,
        is_plan_approved=request.approval,
        plan_feedback=request.feedback,
        prev_response=request.prev_response,
    )
    from src.api.chat_endpoints import run_agent_inference_endpoint
    return await run_agent_inference_endpoint(
        request=fastapi_request,
        inference_request=inference_request,
        inference_service=inference_service,
        feedback_learning_service=feedback_learning_service
    )

@router.post("/react-agent/get-feedback-response/{feedback}", summary="Deprecated: Use [ /chat/get/feedback-response/{feedback_type} ] instead || NOTE: Requires changes in payload's keys (feedback -> final_response_feedback) and in the endpoint url (/react-agent/get-feedback-response/feedback -> /chat/get/feedback-response/submit_feedback - *note here that feedback is replaced with submit_feedback*)")
async def temporary_get_feedback_response_endpoint(
                            fastapi_request: Request,
                            feedback: str,
                            request: TempAgentInferenceRequest,
                            chat_service: ChatService = Depends(ServiceProvider.get_chat_service),
                            agent_inference: CentralizedAgentInference = Depends(ServiceProvider.get_centralized_agent_inference),
                            feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service)
                        ):
    if feedback == "feedback":
        feedback = "submit_feedback"
    inference_request = AgentInferenceRequest(
        query=request.query,
        agentic_application_id=request.agentic_application_id,
        session_id=request.session_id,
        model_name=request.model_name,
        reset_conversation=request.reset_conversation,
        final_response_feedback=request.feedback,
        prev_response=request.prev_response,
        knowledgebase_name=request.knowledgebase_name
    )
    from src.api.chat_endpoints import send_feedback_endpoint
    return await send_feedback_endpoint(
        request=fastapi_request,
        feedback_type=feedback,
        inference_request=inference_request,
        chat_service=chat_service,
        inference_service=agent_inference,
        feedback_learning_service=feedback_learning_service
    )

@router.post("/meta-agent/get-chat-history", summary="Deprecated: Use [ /chat/get/history ] instead")
@router.post("/react-agent/get-chat-history", summary="Deprecated: Use [ /chat/get/history ] instead")
@router.post("/get-chat-history", summary="Deprecated: Use [ /chat/get/history ] instead")
async def temporary_get_history_endpoint(fastapi_request: Request, request: ChatSessionRequest, chat_service: ChatService = Depends(ServiceProvider.get_chat_service)):
    from src.api.chat_endpoints import get_chat_history_endpoint
    return await get_chat_history_endpoint(fastapi_request, request, chat_service)

@router.delete("/react-agent/clear-chat-history", summary="Deprecated: Use [ /chat/clear-history ] instead")
@router.delete("/clear-chat-history", summary="Deprecated: Use [ /chat/clear-history ] instead")
async def temporary_clear_chat_history_endpoint(fastapi_request: Request, request: ChatSessionRequest, chat_service: ChatService = Depends(ServiceProvider.get_chat_service)):
    from src.api.chat_endpoints import clear_chat_history_endpoint
    return await clear_chat_history_endpoint(fastapi_request, request, chat_service)

@router.post("/old-chats", summary="Deprecated: Use [ /chat/get/old-conversations ] instead")
async def temporary_get_old_chats_endpoint(fastapi_request: Request, request: OldChatSessionsRequest, chat_service: ChatService = Depends(ServiceProvider.get_chat_service)):
    from src.api.chat_endpoints import get_old_conversations_endpoint
    return await get_old_conversations_endpoint(fastapi_request, request, chat_service)

@router.get("/new_chat/{email}", summary="Deprecated: Use [ /chat/get/new-session-id/{email} ] instead")
async def temporary_new_chat_endpoint(fastapi_request: Request, email:str, chat_service: ChatService = Depends(ServiceProvider.get_chat_service)):
    from src.api.chat_endpoints import create_new_session_endpoint
    return await create_new_session_endpoint(fastapi_request, email, chat_service)

## ==============================================================================================================================


## ========================================= Evaluation Deprecated Endpoints =========================================

@router.post('/evaluate', summary="Deprecated: Use [ /evaluation/process-unprocessed ] instead")
async def temporary_evaluate_endpoint(
            fastapi_request: Request,
            evaluating_model1,
            evaluating_model2,
            core_evaluation_service: CoreEvaluationService = Depends(ServiceProvider.get_core_evaluation_service)
        ):
    from src.api.evaluation_endpoints import process_unprocessed_evaluations_endpoint
    return await process_unprocessed_evaluations_endpoint(fastapi_request, evaluating_model1, evaluating_model2, core_evaluation_service)

@router.get("/evaluations", summary="Deprecated: Use [ /evaluation/get/data ] instead")
async def temporary_get_evaluation_data_endpoint(
        fastapi_request: Request,
        agent_names: Optional[List[str]] = Query(default=None),
        page: int = Query(default=1, ge=1),
        limit: int = Query(default=10, ge=1, le=100),
        evaluation_service: EvaluationService = Depends(ServiceProvider.get_evaluation_service)
    ):
    from src.api.evaluation_endpoints import get_evaluation_data_endpoint
    return await get_evaluation_data_endpoint(fastapi_request, agent_names, page, limit, evaluation_service)

@router.get("/tool-metrics", summary="Deprecated: Use [ /evaluation/get/tool-metrics ] instead")
async def temporary_get_tool_metrics_endpoint(
        fastapi_request: Request,
        agent_names: Optional[List[str]] = Query(default=None),
        page: int = Query(default=1, ge=1, description="Page number (starts from 1)"),
        limit: int = Query(default=10, ge=1, le=100, description="Number of records per page (max 100)"),
        evaluation_service: EvaluationService = Depends(ServiceProvider.get_evaluation_service)
    ):
    from src.api.evaluation_endpoints import get_tool_metrics_endpoint
    return await get_tool_metrics_endpoint(fastapi_request, agent_names, page, limit, evaluation_service)

@router.get("/agent-metrics", summary="Deprecated: Use [ /evaluation/get/agent-metrics ] instead")
async def temporary_get_agent_metrics_endpoint(
        fastapi_request: Request,
        agent_names: Optional[List[str]] = Query(default=None),
        page: int = Query(default=1, ge=1),
        limit: int = Query(default=10, ge=1, le=100),
        evaluation_service: EvaluationService = Depends(ServiceProvider.get_evaluation_service)
    ):
    from src.api.evaluation_endpoints import get_agent_metrics_endpoint
    return await get_agent_metrics_endpoint(fastapi_request, agent_names, page, limit, evaluation_service)

@router.get("/download-evaluation-result", summary="Deprecated: Use [ /evaluation/download-result ] instead")
async def temporary_download_evaluation_result_endpoint(fastapi_request: Request, file_name: str):
    from src.api.evaluation_endpoints import download_evaluation_result_endpoint
    return await download_evaluation_result_endpoint(fastapi_request, file_name)

@router.post("/upload-and-evaluate/", summary="Deprecated: Use [ /evaluation/upload-and-evaluate ] instead")
async def temporary_upload_and_evaluate_endpoint(fastapi_request: Request, file: UploadFile = File(...), subdirectory: str = "", request: GroundTruthEvaluationRequest = Depends()):
    from src.api.evaluation_endpoints import upload_and_evaluate_endpoint
    return await upload_and_evaluate_endpoint(fastapi_request, file, subdirectory, request)

@router.post("/upload-and-evaluate-json/", summary="Deprecated: Use [ /evaluation/upload-and-evaluate-json ] instead")
async def temporary_upload_and_evaluate_json_endpoint(fastapi_request: Request, file: UploadFile = File(...), subdirectory: str = "", request: GroundTruthEvaluationRequest = Depends()):
    from src.api.evaluation_endpoints import upload_and_evaluate_json_endpoint
    return await upload_and_evaluate_json_endpoint(fastapi_request, file, subdirectory, request)

## ==============================================================================================================================


## ========================================= Feedback Learning Deprecated Endpoints =========================================

@router.get("/get-approvals-list", summary="Deprecated: Use [ /feedback-learning/get/approvals-list ] instead")
async def temporary_get_approvals_list(fastapi_request: Request, feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service)):
    from src.api.feedback_learning_endpoints import get_approvals_list_endpoint
    return await get_approvals_list_endpoint(fastapi_request, feedback_learning_service)

@router.get("/get-responses-data/{response_id}", summary="Deprecated: Use [ /feedback-learning/get/responses-data/{response_id} ] instead")
async def temporary_get_responses_data_endpoint(fastapi_request: Request, response_id: str, feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service)):
    from src.api.feedback_learning_endpoints import get_responses_data_endpoint
    return await get_responses_data_endpoint(fastapi_request, response_id, feedback_learning_service)

@router.get("/get-approvals-by-id/{agent_id}", summary="Deprecated: Use [ /feedback-learning/get/approvals-by-agent/{agent_id} ] instead")
async def temporary_get_approval_by_id(fastapi_request: Request, agent_id: str, feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service)):
    from src.api.feedback_learning_endpoints import get_approval_by_agent_id_endpoint
    return await get_approval_by_agent_id_endpoint(fastapi_request, agent_id, feedback_learning_service)

@router.post("/update-approval-response", summary="Deprecated: Use [ /feedback-learning/update/approval-response ] instead || NOTE: that the request type is changed from 'POST' to 'PUT' in the new endpoint")
async def temporary_update_approval_response(
        fastapi_request: Request,
        request: ApprovalRequest,
        feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service)
    ):
    from src.api.feedback_learning_endpoints import update_approval_response_endpoint
    return await update_approval_response_endpoint(fastapi_request, request, feedback_learning_service)

## ==============================================================================================================================


## ========================================= Utility Deprecated Endpoints =========================================

@router.get('/get-models', summary="Deprecated: Use [ /utility/get/models ] instead")
async def temporary_get_available_models(fastapi_request: Request, model_service: ModelService = Depends(ServiceProvider.get_model_service)):
    from src.api.utility_endpoints import get_available_models_endpoint
    return await get_available_models_endpoint(fastapi_request, model_service)

@router.get('/get-version', summary="Deprecated: Use [ /utility/get/version ] instead || NOTE: Response format is changed to return dictionary with 'version' key in the new endpoint")
async def temporary_get_version(fastapi_request: Request):
    from src.api.utility_endpoints import get_version_endpoint
    return (await get_version_endpoint(fastapi_request)).get("version", "Version not found")

@router.post("/files/user-uploads/upload-file/", summary="Deprecated: Use [ /utility/files/user-uploads/upload/ ] instead")
async def temporary_upload_file_endpoint(fastapi_request: Request, file: UploadFile = File(...), subdirectory: str = "", file_manager: FileManager = Depends(ServiceProvider.get_file_manager)):
    from src.api.utility_endpoints import upload_file_endpoint
    return await upload_file_endpoint(fastapi_request, files=[file], subdirectory=subdirectory, file_manager=file_manager)

@router.get("/files/user-uploads/get-file-structure/", summary="Deprecated: Use [ /utility/files/user-uploads/get-file-structure/ ] instead")
async def temporary_get_file_structure_endpoint(fastapi_request: Request, file_manager: FileManager = Depends(ServiceProvider.get_file_manager)):
    from src.api.utility_endpoints import get_file_structure_endpoint
    return await get_file_structure_endpoint(fastapi_request, file_manager=file_manager)

@router.get('/download', summary="Deprecated: Use [ /utility/files/user-uploads/download ] instead")
async def temporary_download_endpoint(fastapi_request: Request, filename: str = Query(...), sub_dir_name: str = Query(None), file_manager: FileManager = Depends(ServiceProvider.get_file_manager)):
    from src.api.utility_endpoints import download_file_endpoint
    return await download_file_endpoint(fastapi_request, filename=filename, sub_dir_name=sub_dir_name, file_manager=file_manager)

@router.delete("/files/user-uploads/delete-file/", summary="Deprecated: Use [ /utility/files/user-uploads/delete/ ] instead")
async def temporary_delete_file_endpoint(fastapi_request: Request, file_path: str, file_manager: FileManager = Depends(ServiceProvider.get_file_manager)):
    from src.api.utility_endpoints import delete_file_endpoint
    return await delete_file_endpoint(fastapi_request, file_path=file_path, file_manager=file_manager)

@router.post("/kbdocuments", summary="Deprecated: Use [ /utility/knowledge-base/documents/upload ] instead")
async def temporary_upload_kb_files(fastapi_request: Request, session_id: str = Form(...), kb_name:str = 'temp', files: List[UploadFile] = File(...)):
    from src.api.utility_endpoints import upload_knowledge_base_documents_endpoint
    return await upload_knowledge_base_documents_endpoint(fastapi_request, session_id=session_id, kb_name=kb_name, files=files)

@router.get("/kb_list", summary="Deprecated: Use [ /utility/knowledge-base/list ] instead")
async def temporary_list_kb_directories(fastapi_request: Request):
    from src.api.utility_endpoints import list_knowledge_base_directories_endpoint
    return await list_knowledge_base_directories_endpoint(fastapi_request)

@router.post("/transcribe/", summary="Deprecated: Use [ /utility/transcribe/ ] instead")
async def temporary_transcribe_audio(fastapi_request: Request, file: UploadFile = File(...)):
    from src.api.utility_endpoints import transcribe_audio_endpoint
    return await transcribe_audio_endpoint(request=fastapi_request, file=file)

@router.get("/list_markdown_files/", summary="Deprecated: Use [ /utility/docs/list-all-markdown-files ] instead")
async def temporary_list_all_files(fastapi_request: Request):
    from src.api.utility_endpoints import list_all_docs_files_endpoint
    return await list_all_docs_files_endpoint(fastapi_request)

@router.get("/list_markdown_files/{dir_name}", summary="Deprecated: Use [ /utility/docs/list-markdown-files-in-directory/{dir_name} ] instead")
async def temporary_list_files_in_directory(fastapi_request: Request, dir_name: str):
    from src.api.utility_endpoints import list_docs_files_in_directory_endpoint
    return await list_docs_files_in_directory_endpoint(fastapi_request, dir_name)

## ==============================================================================================================================


## ========================================= Data Connector Deprecated Endpoints =========================================

@router.post("/connect", summary="Deprecated: Use [ /data-connector/connect ] instead")
async def temporary_connect_to_database(
        fastapi_request: Request,
        name: str = Form(...),
        db_type: str = Form(...),
        host: Optional[str] = Form(None),
        port: Optional[int] = Form(None),
        username: Optional[str] = Form(None),
        password: Optional[str] = Form(None),
        database: Optional[str] = Form(None),
        flag_for_insert_into_db_connections_table: str = Form(None),
        # created_by: str = Form(...),  # <--- make sure to include this
        sql_file: Union[UploadFile, str, None] = File(None),
        db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager)
    ):
    from src.api.data_connector_endpoints import connect_to_database_endpoint
    return await connect_to_database_endpoint(fastapi_request, name, db_type, host, port, username, password, database,
                                flag_for_insert_into_db_connections_table, sql_file, db_connection_manager)

@router.post("/disconnect", summary="Deprecated: Use [ /data-connector/disconnect ] instead")
async def temporary_disconnect_database(fastapi_request: Request, req: DBDisconnectRequest, db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager)):
    from src.api.data_connector_endpoints import disconnect_database_endpoint
    return await disconnect_database_endpoint(fastapi_request, req, db_connection_manager)

@router.post("/generate_query", summary="Deprecated: Use [ /data-connector/generate-query ] instead")
async def temporary_generate_query(fastapi_request: Request, req: QueryGenerationRequest):
    from src.api.data_connector_endpoints import generate_query_endpoint
    return await generate_query_endpoint(fastapi_request, req, ServiceProvider.get_model_service())

@router.post("/run_query", summary="Deprecated: Use [ /data-connector/run-query ] instead")
async def temporary_run_query(fastapi_request: Request, req: QueryExecutionRequest, db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager)):
    from src.api.data_connector_endpoints import run_query_endpoint
    return await run_query_endpoint(fastapi_request, req, db_connection_manager)

@router.get("/connections", summary="Deprecated: Use [ /data-connector/connections ] instead")
async def temporary_get_connections_endpoint(fastapi_request: Request, db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager)):
    from src.api.data_connector_endpoints import get_connections_endpoint
    return await get_connections_endpoint(fastapi_request, db_connection_manager)

@router.get("/connection/{connection_name}", summary="Deprecated: Use [ /data-connector/connection/{connection_name} ] instead")
async def temporary_get_connection_config_endpoint(fastapi_request: Request, connection_name: str, db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager)):
    from src.api.data_connector_endpoints import get_connection_config_endpoint
    return await get_connection_config_endpoint(fastapi_request, connection_name, db_connection_manager)

@router.get("/connections_sql", summary="Deprecated: Use [ /data-connector/connections/sql ] instead")
async def temporary_get_connections_sql_endpoint(fastapi_request: Request, db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager)):
    from src.api.data_connector_endpoints import get_sql_connections_endpoint
    return await get_sql_connections_endpoint(fastapi_request, db_connection_manager)

@router.get("/connections_mongodb", summary="Deprecated: Use [ /data-connector/connections/mongodb ] instead")
async def temporary_get_connections_mongodb_endpoint(fastapi_request: Request, db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager)):
    from src.api.data_connector_endpoints import get_mongodb_connections_endpoint
    return await get_mongodb_connections_endpoint(fastapi_request, db_connection_manager)

@router.post("/mongodb-operation/", summary="Deprecated: Use [ /data-connector/mongodb-operation/ ] instead")
async def temporary_mongodb_operation(fastapi_request: Request, op: MONGODBOperation, db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager)):
    from src.api.data_connector_endpoints import mongodb_operation_endpoint
    return await mongodb_operation_endpoint(fastapi_request, op, db_connection_manager)

@router.get("/get-active-connection-names", summary="Deprecated: Use [ /data-connector/get/active-connection-names ] instead")
async def temporary_get_active_connection_names(fastapi_request: Request, db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager)):
    from src.api.data_connector_endpoints import get_active_connection_names_endpoint
    return await get_active_connection_names_endpoint(fastapi_request, db_connection_manager)

## ==============================================================================================================================


