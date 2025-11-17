# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import ast
import uuid
import time
import json
import asyncio
import json
import tempfile
import pandas as pd
from pathlib import Path
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request, Query, UploadFile, File, Form , Form
from fastapi.responses import FileResponse, StreamingResponse
from typing import List, Dict, Optional, Callable,Awaitable, Union
from datetime import datetime
from pytz import timezone

from src.schemas import GroundTruthEvaluationRequest
from src.database.services import EvaluationService
from src.database.core_evaluation_service import CoreEvaluationService
from src.api.dependencies import ServiceProvider # Dependency provider
from src.schemas import GroundTruthEvaluationRequest, AgentInferenceRequest
from src.database.services import EvaluationService, ConsistencyService
from src.database.core_evaluation_service import CoreEvaluationService, CoreConsistencyEvaluationService, CoreRobustnessEvaluationService
from src.inference import CentralizedAgentInference

from groundtruth import evaluate_ground_truth_file
from phoenix.otel import register
from phoenix.trace import using_project
from telemetry_wrapper import logger as log, update_session_context
from src.auth.dependencies import get_user_info_from_request

router = APIRouter(prefix="/evaluation", tags=["Evaluation"])
ist = timezone("Asia/Kolkata")


# Base directory for uploads
BASE_DIR = "user_uploads"
TRUE_BASE_DIR = os.path.dirname(BASE_DIR)  # This will now point to the folder that contains both `user_uploads` and `evaluation_uploads`
EVALUATION_UPLOAD_DIR = os.path.join(TRUE_BASE_DIR, "evaluation_uploads")
os.makedirs(EVALUATION_UPLOAD_DIR, exist_ok=True) # Ensure directory exists on startup

RESPONSES_TEMP_DIR = Path("responses_temp")
OUTPUT_DIR = Path("outputs")

RESPONSES_TEMP_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

PREVIEW_DIR = Path("temp_previews")
PREVIEW_DIR.mkdir(exist_ok=True)

# Helper functions

def get_temp_paths(agentic_application_id: str):
    """Returns paths for temporary xlsx and meta files."""
    base = RESPONSES_TEMP_DIR / f"{agentic_application_id}"
    xlsx_path = base.with_suffix(".xlsx")
    meta_path = base.with_suffix(".meta.json")
    return xlsx_path, meta_path

def get_robustness_preview_path(agentic_id: str) -> Path:
    """Returns the path for a temporary robustness preview file."""
    return PREVIEW_DIR / f"robustness_preview_{agentic_id}.json"

async def _parse_agent_names(agent_input: Optional[List[str]]) -> Optional[List[str]]:
    if not agent_input:
        return None
 
    if len(agent_input) == 1:
        raw = agent_input[0]
        try:
            # Try parsing stringified list format: "['Agent1','Agent2']"
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed]
        except Exception:
            if ',' in raw:
                return [x.strip() for x in raw.split(',')]
 
    return agent_input

async def _upload_evaluation_file(file: UploadFile = File(...), subdirectory: str = "") -> Dict[str, str]:
    """
    Internal helper to save an uploaded evaluation file.
    """
    if subdirectory.startswith("/") or subdirectory.startswith("\\"):
        subdirectory = subdirectory[1:]

    save_path = os.path.join(EVALUATION_UPLOAD_DIR, subdirectory) if subdirectory else EVALUATION_UPLOAD_DIR
    os.makedirs(save_path, exist_ok=True)

    # Ensure unique filename using UUID
    name, ext = os.path.splitext(file.filename)
    safe_filename = f"{name}_{uuid.uuid4().hex[:8]}{ext}"
    full_file_path = os.path.join(save_path, safe_filename)

    # Save file
    try:
        with open(full_file_path, "wb") as f:
            f.write(await file.read())

        log.info(f"Evaluation file '{file.filename}' uploaded as '{safe_filename}' at '{full_file_path}'")

        relative_path = os.path.relpath(full_file_path, start=os.getcwd())
        return {
            "info": f"File '{file.filename}' saved as '{safe_filename}' at '{relative_path}'",
            "file_path": relative_path
        }
    except Exception as e:
        log.error(f"Error saving evaluation file '{file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

async def _evaluate_agent_performance(
    evaluation_request: GroundTruthEvaluationRequest,
    file_path: str,
    progress_callback: Optional[Callable[[str], Awaitable[None]]] = None
):
    """
    Wrapper function to evaluate an agent against a ground truth file.
    Supports optional progress_callback for SSE streaming.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    if not file_path.lower().endswith((".csv", ".xlsx", ".xls")):
        raise ValueError("File must be a CSV or Excel file.")

    if progress_callback:
        await progress_callback("Initializing model and inference service...")

    model_service = ServiceProvider.get_model_service()
    inference_service = ServiceProvider.get_centralized_agent_inference()
    llm = await model_service.get_llm_model(evaluation_request.model_name)

    if progress_callback:
        await progress_callback("Starting evaluation of ground truth file...")

    avg_scores, summary, excel_path = await evaluate_ground_truth_file(
        model_name=evaluation_request.model_name,
        agent_type=evaluation_request.agent_type,
        file_path=file_path,
        agentic_application_id=evaluation_request.agentic_application_id,
        session_id=evaluation_request.session_id,
        inference_service=inference_service,
        llm=llm,
        use_llm_grading=evaluation_request.use_llm_grading,
        progress_callback=progress_callback  # ✅ Pass callback here
    )

    if progress_callback:
        await progress_callback("Evaluation completed successfully.")

    return avg_scores, summary, excel_path

async def cleanup_old_files(directories=["outputs", "evaluation_uploads"], expiration_hours=24):
    log.debug("Starting cleanup task for old files...")
    while True:
        try:
            now = time.time()
            cutoff = now - (expiration_hours * 60 * 60)

            for directory in directories:
                abs_path = os.path.abspath(directory)
                deleted_files = []

                log.debug(f"[Cleanup Task] Scanning '{abs_path}' for files older than {expiration_hours} hours...")

                if not os.path.exists(abs_path):
                    log.warning(f"[Cleanup Task] Directory does not exist: {abs_path}")
                    continue

                for filename in os.listdir(abs_path):
                    file_path = os.path.join(abs_path, filename)
                    if os.path.isfile(file_path):
                        file_mtime = os.path.getmtime(file_path)
                        if file_mtime < cutoff:
                            try:
                                os.remove(file_path)
                                deleted_files.append(filename)
                                log.debug(f"[Cleanup Task] Deleted expired file: {filename}")
                            except Exception as e:
                                log.error(f"[Cleanup Task] Failed to delete '{filename}': {e}")

                if not deleted_files:
                    log.info(f"[Cleanup Task] No expired files found in '{abs_path}'.")
                else:
                    log.info(f"[Cleanup Task] Deleted {len(deleted_files)} file(s) from '{abs_path}': {deleted_files}")

        except Exception as e:
            log.error(f"[Cleanup Task] Error during cleanup: {e}")

        await asyncio.sleep(3600)  # Wait 1 hour before next cleanup cycle


# Endpoints

@router.post("/process-unprocessed")
async def process_unprocessed_evaluations_endpoint(
    fastapi_request: Request,
    evaluating_model1: str = Query(..., description="Model name for comparison (e.g., 'gpt-4o')"),
    evaluating_model2: str = Query(..., description="Another model name for comparison (e.g., 'gpt-35-turbo')"),
    core_evaluation_service: CoreEvaluationService = Depends(ServiceProvider.get_core_evaluation_service)
):
    """
    API endpoint to stream progress of unprocessed evaluation records.

    Parameters:
    - fastapi_request: The FastAPI Request object.
    - evaluating_model1: First model name for evaluation comparison.
    - evaluating_model2: Second model name for evaluation comparison.
    - core_evaluation_service: Dependency-injected CoreEvaluationService instance.

    Returns:
    - Dict[str, str]: A message indicating the status of the processing.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    user = await get_user_info_from_request(fastapi_request)
    update_session_context(user_session=user_session, user_id=user_id)

    register(
        project_name='evaluation-metrics',
        auto_instrument=True,
        set_global_tracer_provider=False,
        batch=True
    )

    async def event_stream():
        with using_project('evaluation-metrics'):
            async for update in core_evaluation_service.process_unprocessed_evaluations(
                model1=evaluating_model1,
                model2=evaluating_model2,
                user=user
            ):
                yield f"data: {json.dumps(update)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")



@router.get("/get/data")
async def get_evaluation_data_endpoint(
        fastapi_request: Request,
        agent_names: Optional[List[str]] = Query(default=None),
        page: int = Query(default=1, ge=1),
        limit: int = Query(default=10, ge=1, le=100),
        evaluation_service: EvaluationService = Depends(ServiceProvider.get_evaluation_service)
    ):
    """
    API endpoint to retrieve raw evaluation data records.

    Parameters:
    - fastapi_request: The FastAPI Request object.
    - agent_names: Optional list of agent names to filter by.
    - page: Page number for pagination.
    - limit: Number of records per page.
    - evaluation_service: Dependency-injected EvaluationService instance.

    Returns:
    - List[Dict[str, Any]]: A list of evaluation data records.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    user = await get_user_info_from_request(fastapi_request)

    # Use InferenceUtils to parse agent names
    parsed_names = await _parse_agent_names(agent_names)
    data = await evaluation_service.get_evaluation_data(user,parsed_names, page, limit)
    if not data:
        raise HTTPException(status_code=404, detail="No evaluation data found")
    return data


@router.get("/get/tool-metrics")
async def get_tool_metrics_endpoint(
        fastapi_request: Request,
        agent_names: Optional[List[str]] = Query(default=None),
        page: int = Query(default=1, ge=1, description="Page number (starts from 1)"),
        limit: int = Query(default=10, ge=1, le=100, description="Number of records per page (max 100)"),
        evaluation_service: EvaluationService = Depends(ServiceProvider.get_evaluation_service),
    ):
    """
    API endpoint to retrieve tool evaluation metrics.

    Parameters:
    - fastapi_request: The FastAPI Request object.
    - agent_names: Optional list of agent names to filter by.
    - page: Page number for pagination.
    - limit: Number of records per page.
    - evaluation_service: Dependency-injected EvaluationService instance.

    Returns:
    - List[Dict[str, Any]]: A list of tool metrics records.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    user = await get_user_info_from_request(fastapi_request)

    parsed_names = await _parse_agent_names(agent_names)
    data = await evaluation_service.get_tool_metrics(user,parsed_names, page, limit)
    if not data:
        raise HTTPException(status_code=404, detail="No tool metrics found")
    return data


@router.get("/get/agent-metrics")
async def get_agent_metrics_endpoint(
        fastapi_request: Request,
        agent_names: Optional[List[str]] = Query(default=None),
        page: int = Query(default=1, ge=1),
        limit: int = Query(default=10, ge=1, le=100),
        evaluation_service: EvaluationService = Depends(ServiceProvider.get_evaluation_service)
    ):
    """
    API endpoint to retrieve agent evaluation metrics.

    Parameters:
    - fastapi_request: The FastAPI Request object.
    - agent_names: Optional list of agent names to filter by.
    - page: Page number for pagination.
    - limit: Number of records per page.
    - evaluation_service: Dependency-injected EvaluationService instance.

    Returns:
    - List[Dict[str, Any]]: A list of agent metrics records.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    user = await get_user_info_from_request(fastapi_request)

    parsed_names = await _parse_agent_names(agent_names)
    data = await evaluation_service.get_agent_metrics(user,parsed_names, page, limit)
    if not data:
        raise HTTPException(status_code=404, detail="No agent metrics found")
    return data


@router.get("/download-result")
async def download_evaluation_result_endpoint(fastapi_request: Request, file_name: str):
    """
    API endpoint to download the evaluation result file.

    Parameters:
    - fastapi_request: The FastAPI Request object.
    - file_name: The name of the result file to download.

    Returns:
    - FileResponse: Returns the file as a downloadable response.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    # Full path to file (assuming 'outputs' is a subdirectory in the current working directory)
    file_path = os.path.join(Path.cwd(), 'outputs', file_name)

    if not os.path.exists(file_path):
        log.error(f"File not found: {file_path}")
        raise HTTPException(status_code=404, detail="File not found")
    log.info(f"Downloading evaluation result file: {file_path}")
    return FileResponse(path=file_path, filename=file_name, media_type="application/octet-stream")


@router.get("/download-groundtruth-template")
async def download_groundtruth_template_endpoint(fastapi_request: Request, file_name: str='Groundtruth_template.xlsx'):
    """
    API endpoint to download sample upload file for groundtruth evaluation.

    Parameters:
    - fastapi_request: The FastAPI Request object.
    - file_name: The name of the template file to download (default is 'Groundtruth_template.xlsx').
    
    Returns:
    - FileResponse: Returns the file as a downloadable response.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    file_path = os.path.join(Path.cwd(), 'src/file_templates', file_name)

    if not os.path.exists(file_path):
        log.error(f"File not found: {file_path}")
        raise HTTPException(status_code=404, detail="File not found")
    log.info(f"Downloading sample upload file for groundtruth evaluation: {file_path}")
    return FileResponse(path=file_path, filename=file_name, media_type="application/octet-stream")



@router.post("/upload-and-evaluate-json")
async def upload_and_evaluate_json(
    fastapi_request: Request,
    file: UploadFile = File(...),
    subdirectory: str = "",
    evaluation_request: GroundTruthEvaluationRequest = Depends()
):
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    upload_resp = await _upload_evaluation_file(file, subdirectory)

    if "file_path" not in upload_resp:
        raise HTTPException(status_code=400, detail="File upload failed.")
    file_path = upload_resp["file_path"]

    async def event_stream():
        queue = asyncio.Queue()

        async def progress_callback(message: str):
            await queue.put(json.dumps({"progress": message}) + "\n")

        async def run_evaluation():
            try:
                await queue.put(json.dumps({"status": "Starting evaluation..."}) + "\n")

                avg_scores, summary, excel_path = await _evaluate_agent_performance(
                    evaluation_request=evaluation_request,
                    file_path=file_path,
                    progress_callback=progress_callback
                )

                summary_safe = summary.encode("ascii", "ignore").decode().replace("\n", " ")
                file_name = os.path.basename(excel_path)
                download_url = f"{fastapi_request.base_url}evaluation/download-result?file_name={file_name}"

                result_payload = {
                    "message": "Evaluation completed successfully",
                    "download_url": download_url,
                    "average_scores": avg_scores,
                    "diagnostic_summary": summary_safe
                }

                await queue.put(json.dumps({"result": result_payload}) + "\n")
            except Exception as e:
                await queue.put(json.dumps({"error": f"Evaluation failed: {str(e)}"}) + "\n")

        asyncio.create_task(run_evaluation())

        while True:
            message = await queue.get()
            yield message
            if message.startswith("{\"result\":") or message.startswith("{\"error\":"):
                break

    return StreamingResponse(event_stream(), media_type="application/json")

#-----------------Consistency and Robustness-------------------------#




@router.get("/download-consistency-template")
async def download_consistency_template_endpoint(fastapi_request: Request, file_name: str='Consistency_template.xlsx'):
    """
    API endpoint to download sample upload file for Consistency and robustness evaluation.

    Parameters:
    - fastapi_request: The FastAPI Request object.
    - file_name: The name of the template file to download (default is 'Consistency_template.xlsx').
    
    Returns:
    - FileResponse: Returns the file as a downloadable response.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    file_path = os.path.join(Path.cwd(), 'src/file_templates', file_name)

    if not os.path.exists(file_path):
        log.error(f"File not found: {file_path}")
        raise HTTPException(status_code=404, detail="File not found")
    log.info(f"Downloading sample upload file for Consistency evaluation: {file_path}")
    return FileResponse(path=file_path, filename=file_name, media_type="application/octet-stream")




@router.post("/consistency/preview-responses", summary="Preview Agent Responses for Consistency")
async def preview_agent_responses(
    file: Union[UploadFile, str, None] = File(None, description="Upload an Excel file with a 'queries' column"),
    queries: Optional[str] = Form(None, description='Enter queries as a JSON list of strings, e.g. ["Query1", "Query2"]'),
    agent_id: str = Form(...),
    agent_name: str = Form(...),
    agent_type: str = Form(...),
    model_name: str = Form(...),
    session_id: str = Form(...),
    consistency_service: ConsistencyService = Depends(ServiceProvider.get_consistency_service),
    core_consistency_service: CoreConsistencyEvaluationService = Depends(ServiceProvider.get_core_consistency_service)
):
    """
    Handles the initial 'preview' step. Checks if an agent exists,
    generates responses for a query file or manual input, and saves temporary results.
    """
    if isinstance(file, str):
        file = None
    # Validate input source
    if not file and not queries:
        raise HTTPException(status_code=400, detail="Either a file or manual queries must be provided.")
    if file and queries:
        raise HTTPException(status_code=400, detail="Provide either a file or manual queries, not both.")
 
    # Check if the agent already exists
    existing_agent = await consistency_service.get_agent_by_id(agent_id)
    if existing_agent:
        return {
            "status": "agent_exists",
            "message": f"Agent ID '{agent_id}' is already registered.",
            "update_url": f"/evaluation/generate-update-preview/{agent_id}"
        }
 
    # ✅ FIXED: Do NOT create agent record during preview - only create temp files
    # Agent record will be created only during approval step
    log.info(f"📋 Generating preview for agent_id: {agent_id} (no DB changes yet)")
 
    # Extract queries
    if file:
        try:
            df = pd.read_excel(file.file)
            df.columns = [c.strip().lower() for c in df.columns]
            if "queries" not in df.columns:
                raise HTTPException(status_code=400, detail="File must contain a 'queries' column.")
            queries_list = df["queries"].tolist()
        except HTTPException:
            raise  # Re-raise HTTP exceptions as-is
        except Exception as e:
            log.error(f"Error processing uploaded file: {e}", exc_info=True)
            raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")
        finally:
            await file.close()
    else:
        try:
            queries_list = json.loads(queries)
            if not isinstance(queries_list, list):
                raise ValueError("Queries must be a list of strings.")
            queries_list = [q.strip() for q in queries_list if isinstance(q, str) and q.strip()]
        except json.JSONDecodeError as e:
            # If JSON parsing fails, try comma-separated format
            log.info(f"⚠️ JSON parsing failed: {str(e)}")
            try:
                log.info(f"🔄 Trying comma-separated format for queries: {queries}")
                queries_list = [q.strip() for q in queries.split(',') if q.strip()]
                if not queries_list:
                    raise ValueError("No valid queries found.")
                log.info(f"✅ Successfully parsed {len(queries_list)} queries from comma-separated format: {queries_list}")
            except Exception as e:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Invalid queries format. Use JSON array format like [\"query1\", \"query2\"] or comma-separated like \"query1,query2\". Error: {str(e)}"
                )
        except Exception as e:
            log.error(f"❌ Error parsing queries: {str(e)}")
            raise HTTPException(status_code=400, detail=f"Invalid queries format: {str(e)}")
 
        df = pd.DataFrame({"queries": queries_list})
 
    # Generate responses
    responses = []
    timestamp = datetime.now(ist).strftime("%Y-%m-%d_%H-%M-%S")
    response_col = f"{timestamp}_response"
 
    for i, query in enumerate(queries_list):
        session = f"{session_id}_{i}"
        try:
            res = await core_consistency_service.call_agent(query, model_name, agent_id, session)
            responses.append(res)
        except Exception as e:
            log.error(f"Error calling agent for query {i+1}: {e}", exc_info=True)
            responses.append(f"Error: {str(e)}")
 
    df[response_col] = responses
 
    # Save temporary files
    temp_xlsx_path, temp_meta_path = get_temp_paths(agent_id)
    try:
        df.to_excel(temp_xlsx_path, index=False)
        meta = {
            "agentic_application_id": agent_id,
            "agent_name": agent_name,
            "agent_type": agent_type,
            "model_name": model_name,
            "session_id": session_id,
            "timestamp": timestamp,
            "response_column": response_col,
            "is_update_approval": False
        }
        with open(temp_meta_path, "w") as f:
            json.dump(meta, f)
    except Exception as e:
        log.error(f"Error saving temporary files for {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save temporary files: {str(e)}")
 
    # Return response
    return {
        "status": "preview_generated",
        "message": "Preview generated and saved successfully.",
        "filename": temp_xlsx_path.name,
        "response_column": response_col,
        "agentic_application_id": agent_id,
        "agent_name": agent_name,
        "queries": queries_list,
        "responses": responses,
        "rerun_url": f"/evaluation/consistency/rerun-response/?agentic_application_id={agent_id}",
        "approve_url": f"/evaluation/consistency/approve-responses/?agentic_application_id={agent_id}"
    }


@router.post("/consistency/rerun-response", summary="Re-run Agent for Consistency")
async def rerun_agent_responses(
    # Parameters from user request
    agent_id: str = Form(...),
    # Inject the service needed
    core_consistency_service: CoreConsistencyEvaluationService = Depends(ServiceProvider.get_core_consistency_service)
):
    """
    Re-runs the agent on existing queries from a temporary session file.
    """
    temp_xlsx_path, temp_meta_path = get_temp_paths(agent_id)
    if not temp_xlsx_path.exists() or not temp_meta_path.exists():
        raise HTTPException(status_code=404, detail="Session files not found. Cannot re-run.")

    try:
        with open(temp_meta_path, "r") as f:
            meta = json.load(f)

        response_col = meta.get("response_column")
        df = pd.read_excel(temp_xlsx_path)
        queries = df["queries"].tolist()
    except Exception as e:
        log.error(f"Error reading session files for {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read session files: {str(e)}")

    # Re-run the agent for all queries
    new_responses = []
    for i, query in enumerate(queries):
        session = f"{meta['session_id']}_{i}"
        try:
            # --- FIX: Call the method on the INJECTED OBJECT, not the class ---
            res = await core_consistency_service.call_agent(
                query, meta['model_name'], agent_id, session
            )
            new_responses.append(res)
        except Exception as e:
            log.error(f"Error re-running agent for query {i+1}: {e}", exc_info=True)
            new_responses.append(f"Error: {str(e)}")

    df[response_col] = new_responses
    
    try:
        df.to_excel(temp_xlsx_path, index=False)
        meta["last_rerun"] = datetime.now(ist).isoformat()
        with open(temp_meta_path, "w") as f:
            json.dump(meta, f)
    except Exception as e:
        log.error(f"Error saving updated files for {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save updated files: {str(e)}")

    # Your return value logic is unchanged
    return {
        "message": "Re-run completed and file updated.",
        "filename": temp_xlsx_path.name,
        "response_column": response_col,
        "agentic_application_id": agent_id,
        "agent_name": meta.get("agent_name"),
        "queries": queries,
        "responses": new_responses,
        "rerun_url": f"/evaluation/consistency/rerun-response/?agentic_application_id={agent_id}",
        "approve_url": f"/evaluation/consistency/approve-responses/?agentic_application_id={agent_id}"
    }

DB_OPERATION_LOCK = asyncio.Lock()
@router.post("/consistency/approve-responses", summary="Approve and Save Consistency Data")
async def approve_responses_endpoint(
    agentic_application_id: str = Form(...),
    # Inject the service needed for database operations
    consistency_service: ConsistencyService = Depends(ServiceProvider.get_consistency_service)
):
    """
    Approves the current set of responses and saves the data permanently.
    This finalizes the consistency benchmark for a new agent or an update.
    """
    temp_xlsx_path, temp_meta_path = get_temp_paths(agentic_application_id)
    if not temp_xlsx_path.exists() or not temp_meta_path.exists():
        raise HTTPException(status_code=404, detail="Approval files not found. The session may have expired.")

    # This lock prevents race conditions if two approvals for the same agent happen at once.
    async with DB_OPERATION_LOCK:
        log.info(f"Approval process for '{agentic_application_id}' has acquired the database lock.")
        try:
            try:
                with open(temp_meta_path, "r") as f:
                    metadata = json.load(f)
            except Exception as e:
                raise HTTPException(status_code=422, detail=f"Failed to read metadata file: {str(e)}")

            # Read Excel file
            try:
                df_from_temp = pd.read_excel(temp_xlsx_path)
                df_from_temp = df_from_temp.fillna("") 
            except Exception as e:
                raise HTTPException(status_code=422, detail=f"Failed to read Excel file: {str(e)}")

            is_update_approval = metadata.get("is_update_approval", False)

            if is_update_approval:
                # --- LOGIC FOR UPDATE APPROVAL ---
                log.info(f"Processing UPDATE approval for agent: {agentic_application_id}")
                timestamp = metadata['update_timestamp']
                
                # Use the service for all database calls
                latest_response_col = await consistency_service.get_latest_response_column_name(agentic_application_id)
                if latest_response_col:
                    await consistency_service.rename_column_with_timestamp(agentic_application_id, "queries", timestamp, "queries")
                    await consistency_service.rename_column_with_timestamp(agentic_application_id, latest_response_col, timestamp, "response")

                await consistency_service.add_column_to_agent_table(agentic_application_id, "queries", "TEXT")
                await consistency_service.add_column_to_agent_table(agentic_application_id, "reference_response", "TEXT")
                
                await consistency_service.update_column_by_row_id(agentic_application_id, "queries", df_from_temp['queries'].tolist())
                await consistency_service.update_column_by_row_id(agentic_application_id, "reference_response", df_from_temp['reference_response'].tolist())
                
                await consistency_service.update_agent_model_in_db(agentic_application_id, metadata['model_name'])
            else:
                # --- LOGIC FOR NEW AGENT APPROVAL ---
                log.info(f"Processing NEW agent approval for: {agentic_application_id}")
                
                # ✅ FIXED: Create agent record only during approval (not preview)
                agent_name = metadata.get("agent_name", "Unknown Agent")
                model_name = metadata.get("model_name", "gpt-4o")
                log.info(f"🗃️ Creating agent record for: {agentic_application_id}")
                try:
                    agent_type = metadata.get("agent_type", "Unknown Type")
                    await consistency_service.upsert_agent_record(agentic_application_id, agent_name, agent_type, model_name)
                except Exception as e:
                    log.error(f"Error creating agent record for {agentic_application_id}: {e}", exc_info=True)
                    raise HTTPException(status_code=500, detail=f"Failed to create agent record: {str(e)}")
                
                response_col = metadata.get("response_column")
                if not response_col:
                    raise ValueError("Metadata is missing the original response column name.")

                df_from_temp.rename(columns={response_col: "reference_response"}, inplace=True)
                
                # Use the service for the database call
                await consistency_service.create_and_insert_initial_data(
                    table_name=agentic_application_id,
                    df=df_from_temp,
                    col_name="reference_response"
                )

            # --- COMMON FINAL STEPS ---
            await consistency_service.update_queries_timestamp(agentic_application_id)
            await consistency_service.update_evaluation_timestamp(agentic_application_id)
            
            log.info(f"Database operations for '{agentic_application_id}' committed successfully.")

        except Exception as e:
            log.error(f"Error during approval process for {agentic_application_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="An internal server error occurred during approval.")
        finally:
            # Cleanup temporary files regardless of success or failure
            if temp_xlsx_path.exists(): os.remove(temp_xlsx_path)
            if temp_meta_path.exists(): os.remove(temp_meta_path)
            log.info(f"Approval process for '{agentic_application_id}' has released lock.")
    
    # Your original return value is preserved
    return {
        "approved": True,
        "message": f"Data for agent '{agentic_application_id}' has been successfully saved."
    }



def get_robustness_preview_path(agentic_id: str) -> Path:
    """Returns the path for a temporary robustness preview file."""
    return PREVIEW_DIR / f"robustness_preview_{agentic_id}.json"

@router.post("/robustness/preview-queries/{agentic_application_id}", summary="Preview Robustness Queries")
async def preview_robustness_queries(
    agentic_application_id: str,
    core_robustness_service: CoreRobustnessEvaluationService = Depends(ServiceProvider.get_core_robustness_service)
):
    """
    Generates a new set of robustness queries for preview.
    Does NOT run the agent or save to the main database.
    """
    log.info(f"Received request to generate robustness query preview for: {agentic_application_id}")
    try:
        # Step 1: Generate queries using the modular helper
        categories = [
            "Unexpected Input (Out-of-Scope Requests)",
            "Tool Error Simulation (Missing Specific Capability)",
            "Adversarial Input (Deceptive Details)"
        ]
        dataset = []
        for cat in categories:
            dataset += await core_robustness_service.generate_contextual_queries(agentic_application_id, cat)

        # Step 2: Save the queries to a temporary file
        preview_path = get_robustness_preview_path(agentic_application_id)
        with open(preview_path, "w") as f:
            json.dump(dataset, f)
        log.info(f"Saved preview queries for agent '{agentic_application_id}' to {preview_path}")

        # Step 3: Return the response
        return {
            "status": "preview_generated",
            "agent_id": agentic_application_id,
            "message": "Robustness queries have been generated for your review.",
            "generated_queries": [item['query'] for item in dataset],
            "rerun_url": f"/evaluation/robustness/preview-queries/{agentic_application_id}",
            "approve_url": f"/evaluation/robustness/approve-evaluation/{agentic_application_id}"
        }
    except ValueError as e:
        log.error(f"Validation error during query generation for '{agentic_application_id}': {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error(f"An unexpected error occurred during query generation for '{agentic_application_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal server error occurred.")


def get_robustness_preview_path(agentic_id: str) -> Path:
    """Returns the path for a temporary robustness preview file."""
    PREVIEW_DIR = Path("temp_previews")
    PREVIEW_DIR.mkdir(exist_ok=True)
    return PREVIEW_DIR / f"robustness_preview_{agentic_id}.json"



@router.post("/approve-robustness-evaluation/{agentic_application_id}", summary="Approve and Run Robustness Evaluation")
async def approve_robustness_evaluation(
    agentic_application_id: str,
    # Inject the core service that has the pipeline logic
    core_robustness_service: CoreRobustnessEvaluationService = Depends(ServiceProvider.get_core_robustness_service)
):
    """
    Approves the previewed queries, runs the full evaluation pipeline,
    and saves the results to the database.
    """
    log.info(f"Received request to approve and run robustness evaluation for: {agentic_application_id}")
    
    preview_path = get_robustness_preview_path(agentic_application_id)
    if not preview_path.exists():
        raise HTTPException(status_code=404, detail="No preview queries found. Please generate queries before approving.")

    with open(preview_path, "r") as f:
        dataset = json.load(f)

    try:
      
        await core_robustness_service.execute_and_save_robustness_run(
            agent_id=agentic_application_id,
            dataset=dataset
        )
        
        os.remove(preview_path)

        return {
            "status": "success",
            "agent_id": agentic_application_id,
            "message": "Robustness evaluation has been completed successfully and results are saved to the database."
        }
    except Exception as e:
        log.error(f"An unexpected error occurred during the approved robustness run for '{agentic_application_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal server error occurred during the evaluation.")


@router.get("/available_agents/", summary="Get All Agent Evaluation Records")
async def get_all_agents_from_consistency_robustness_details_table(
    consistency_service: ConsistencyService = Depends(ServiceProvider.get_consistency_service)
):
    """
    Retrieves a list of all agent evaluation records from the database.
    """
    log.info("Received request to fetch all agent evaluation records.")
    try:
       
        all_agents = await consistency_service.get_all_agents()
        if not all_agents:
            log.info("No agent evaluation records found in the database.")
            return []
        return all_agents
    except Exception as e:
        log.error(f"An unexpected error occurred while fetching agent records: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal server error occurred while fetching data.")
    

class UpdateEvaluationRequest(BaseModel):
    model_name: str
    queries: List[str]


def get_temp_paths(agentic_application_id: str):
    base = RESPONSES_TEMP_DIR / f"{agentic_application_id}"
    xlsx_path = base.with_suffix(".xlsx")
    meta_path = base.with_suffix(".meta.json")
    return xlsx_path, meta_path

@router.put("/generate-update-preview/{agentic_application_id}", summary="Generate a Preview for an Agent Update")
async def generate_update_preview(
    agentic_application_id: str,
    request: UpdateEvaluationRequest,
    consistency_service: ConsistencyService = Depends(ServiceProvider.get_consistency_service),
    inference_service: CentralizedAgentInference = Depends(ServiceProvider.get_centralized_agent_inference)
):
    """
    Takes updated model/queries, runs a new evaluation, and returns a temporary preview.
    This does NOT permanently alter the database structure yet.
    """
    log.info(f"Generating an UPDATE PREVIEW for agent: {agentic_application_id}")
    
    model_name = request.model_name
    queries = [q.strip() for q in request.queries if q.strip()]
    if not queries:
        raise HTTPException(status_code=400, detail="Queries cannot be empty.")

    responses = []
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session_id = f"update_preview_{timestamp}"

    for i, query in enumerate(queries):
        try:
            req = AgentInferenceRequest(
                agentic_application_id=agentic_application_id,
                query=query, session_id=f"{session_id}_{i}", model_name=model_name, reset_conversation=True
            )
            res = await inference_service.run(req, insert_into_eval_flag=False)
            responses.append(res.get("response", "") if isinstance(res, dict) else str(res))
        except Exception as e:
            log.error(f"Error running inference for query {i+1} in update preview: {e}", exc_info=True)
            responses.append(f"Error: {str(e)}")

    df = pd.DataFrame({
        "queries": queries,
        "reference_response": responses
    })

    temp_xlsx_path, temp_meta_path = get_temp_paths(agentic_application_id)
    try:
        df.to_excel(temp_xlsx_path, index=False)

        meta = {
            "agentic_application_id": agentic_application_id,
            "model_name": model_name,
            "session_id": session_id,
            "response_column": "reference_response",
            "is_update_approval": True,
            "update_timestamp": timestamp
        }
        with open(temp_meta_path, "w") as f:
            json.dump(meta, f)
    except Exception as e:
        log.error(f"Error saving update preview files for {agentic_application_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save update preview files: {str(e)}")

    return {
        "message": "Update preview generated. Please review and approve the new responses.",
        "agentic_application_id": agentic_application_id,
        "queries": queries,
        "responses": responses,
        "rerun_url": f"/evaluation/consistency/rerun-responses/?agentic_application_id={agentic_application_id}",
        "approve_url": f"/evaluation/consistency/approve-responses/?agentic_application_id={agentic_application_id}"
    }


@router.delete("/delete-agent/{agentic_application_id}", summary="Delete Agent and All Associated Data")
async def delete_agent_details(
    agentic_application_id: str,
    consistency_service: ConsistencyService = Depends(ServiceProvider.get_consistency_service)
):
    """
    Completely deletes an agent and all of its associated data, including its
    consistency and robustness result tables. This is a destructive action.
    """
    log.warning(f"Received DELETE request for agent '{agentic_application_id}'.")
    try:
       
        await consistency_service.drop_agent_results_table(agentic_application_id)
        
        robustness_table_name = f"robustness_{agentic_application_id}"
        await consistency_service.drop_agent_results_table(robustness_table_name)
        
        await consistency_service.delete_agent_record_from_main_table(agentic_application_id)

        log.info(f"Successfully deleted all data for agent '{agentic_application_id}'.")

        return {
            "deleted": True,
            "agent_id": agentic_application_id,
            "message": "The agent and all of its associated data have been successfully deleted."
        }
    except Exception as e:
        log.error(f"An unexpected error occurred while deleting agent '{agentic_application_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal server error occurred while deleting the agent.")



@router.get("/agent/{agent_id}/recent_consistency_scores", summary="Get recent consistency scores for a specific agent")
async def get_consistency_scores(
    agent_id: str,
    consistency_service: ConsistencyService = Depends(ServiceProvider.get_consistency_service)
):
    try:
        # Step 1: Fetch agent metadata
        agent = await consistency_service.get_agent_by_id(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent with ID {agent_id} not found.")

        # Step 2: Fetch recent scores from the agent's table
        recent_scores = await consistency_service.data_repo.get_recent_consistency_scores(agent_id)

        # Step 3: Combine and return
        agent["recent_scores"] = await consistency_service.get_last_5_consistency_rows(recent_scores)
        return agent

    except Exception as e:
        log.error(f"Error fetching consistency scores for agent {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch recent consistency scores.")
    


@router.get("/agent/{agent_id}/recent_robustness_scores", summary="Get recent robustness scores for a specific agent")
async def get_robustness_scores(
    agent_id: str,
    consistency_service: ConsistencyService = Depends(ServiceProvider.get_consistency_service)
):
    try:
        # Step 1: Fetch agent metadata
        agent = await consistency_service.get_agent_by_id(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent with ID {agent_id} not found.")

        # Step 2: Fetch recent robustness scores from the robustness_<agent_id> table
        robustness_table = f"robustness_{agent_id}"
        recent_scores = await consistency_service.data_repo.get_recent_consistency_scores(robustness_table)

        # Step 3: Filter last 5 rows based on timestamped score columns
        agent["recent_robustness_scores"] = await consistency_service.get_last_5_robustness_rows(recent_scores)
        return agent

    except Exception as e:
        log.error(f"Error fetching robustness scores for agent {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch recent robustness scores.")
    




def write_consistency_to_csv(records: List[Dict], file_path: str):
    df = pd.DataFrame(records)
    df.to_csv(file_path, index=False)




@router.get("/agent/{agent_id}/download_consistency_record", summary="Download consistency records as CSV")
async def download_consistency_records(
    agent_id: str,
    consistency_service: ConsistencyService = Depends(ServiceProvider.get_consistency_service)
):
    try:
        table_name = agent_id  # assuming table name = agent_id
        records = await consistency_service.get_all_consistency_records(table_name)

        # Create temporary file with proper cross-platform path
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, f"{agent_id}_consistency.csv")
        write_consistency_to_csv(records, file_path)

        return FileResponse(file_path, filename=f"{agent_id}_consistency.csv", media_type="application/octet-stream")

    except Exception as e:
        log.error(f"Error generating consistency file for agent {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate consistency file.")
    


@router.get("/agent/{agent_id}/download_robustness_record", summary="Download robustness records as CSV")
async def download_robustness_records(
    agent_id: str,
    consistency_service: ConsistencyService = Depends(ServiceProvider.get_consistency_service)
):
    try:
        table_name = f"robustness_{agent_id}"  
        records = await consistency_service.get_all_robustness_records(table_name)

        # Create temporary file with proper cross-platform path
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, f"{agent_id}_robustness.csv")
        write_consistency_to_csv(records, file_path)

        return FileResponse(file_path, filename=f"{agent_id}_robustness.csv", media_type="application/octet-stream")

    except Exception as e:
        log.error(f"Error generating robustness file for agent {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate robustness file.")
