# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os # For file operations
import ast # For safely evaluating stringified lists
import uuid # For unique filenames
import time
import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Query, UploadFile, File
from fastapi.responses import FileResponse
from typing import List, Dict, Optional

from src.schemas import GroundTruthEvaluationRequest
from src.database.services import EvaluationService
from src.database.core_evaluation_service import CoreEvaluationService
from src.api.dependencies import ServiceProvider # Dependency provider

from groundtruth import evaluate_ground_truth_file
from phoenix.otel import register
from phoenix.trace import using_project
from telemetry_wrapper import logger as log, update_session_context


router = APIRouter(prefix="/evaluation", tags=["Evaluation"])


# Base directory for uploads
BASE_DIR = "user_uploads"
TRUE_BASE_DIR = os.path.dirname(BASE_DIR)  # This will now point to the folder that contains both `user_uploads` and `evaluation_uploads`
EVALUATION_UPLOAD_DIR = os.path.join(TRUE_BASE_DIR, "evaluation_uploads")
os.makedirs(EVALUATION_UPLOAD_DIR, exist_ok=True) # Ensure directory exists on startup


# Helper functions

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

async def _evaluate_agent_performance(evaluation_request: GroundTruthEvaluationRequest, file_path: str):
    """
    Internal function to evaluate an agent against a ground truth file.
    Returns evaluation results, file paths, and summary.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    if not file_path.lower().endswith((".csv", ".xlsx", ".xls")):
        raise ValueError("File must be a CSV or Excel file.")

    model_service = ServiceProvider.get_model_service()
    inference_service = ServiceProvider.get_centralized_agent_inference()
    llm = await model_service.get_llm_model(evaluation_request.model_name)

    avg_scores, summary, excel_path = await evaluate_ground_truth_file(
        model_name=evaluation_request.model_name,
        agent_type=evaluation_request.agent_type,
        file_path=file_path,  #  Use here
        agentic_application_id=evaluation_request.agentic_application_id,
        session_id=evaluation_request.session_id,
        inference_service=inference_service,
        llm=llm,
        use_llm_grading=evaluation_request.use_llm_grading
    )

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
    API endpoint to process all unprocessed evaluation records.

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
    update_session_context(user_session=user_session, user_id=user_id)

    register(
            project_name='evaluation-metrics',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
    with using_project('evaluation-metrics'):
        result = await core_evaluation_service.process_unprocessed_evaluations(
            model1=evaluating_model1,
            model2=evaluating_model2
        )
    return result


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

    # Use InferenceUtils to parse agent names
    parsed_names = await _parse_agent_names(agent_names)
    data = await evaluation_service.get_evaluation_data(parsed_names, page, limit)
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

    parsed_names = await _parse_agent_names(agent_names)
    data = await evaluation_service.get_tool_metrics(parsed_names, page, limit)
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

    parsed_names = await _parse_agent_names(agent_names)
    data = await evaluation_service.get_agent_metrics(parsed_names, page, limit)
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

@router.post("/upload-and-evaluate")
async def upload_and_evaluate_endpoint(
        fastapi_request: Request,
        file: UploadFile = File(...),
        subdirectory: str = "",
        evaluation_request: GroundTruthEvaluationRequest = Depends()
    ):
    """
    API endpoint to upload an evaluation file and trigger evaluation.

    Parameters:
    - fastapi_request: The FastAPI Request object.
    - file: The uploaded evaluation file.
    - subdirectory: Optional subdirectory within the evaluation uploads directory.
    - evaluation_request: Pydantic model containing evaluation parameters.

    Returns:
    - FileResponse: The generated Excel evaluation report.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    # Step 1: Upload file using the internal helper
    upload_resp = await _upload_evaluation_file(file, subdirectory)

    if "file_path" not in upload_resp:
        raise HTTPException(status_code=400, detail="File upload failed.")

    file_path = upload_resp["file_path"]

    try:
        avg_scores, summary, excel_path = await _evaluate_agent_performance(
            evaluation_request=evaluation_request,
            file_path=file_path
        )

        file_name = os.path.basename(excel_path)

        # Return the Excel file as response with custom headers
        summary_safe = summary.encode("ascii", "ignore").decode().replace("\n", " ")
        log.info(f"Evaluation completed successfully. Download URL: {file_name}")
        return FileResponse(
            path=excel_path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=file_name,
            headers={
                "X-Message": "Evaluation completed successfully",
                "X-Average-Scores": str(avg_scores),
                "X-Diagnostic-Summary": summary_safe
            }
        )

    except Exception as e:
        log.error(f"Evaluation failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(e)}")


@router.post("/upload-and-evaluate-json")
async def upload_and_evaluate_json_endpoint(
        fastapi_request: Request,
        file: UploadFile = File(...),
        subdirectory: str = "",
        evaluation_request: GroundTruthEvaluationRequest = Depends()
    ):
    """
    API endpoint to upload an evaluation file and trigger evaluation, returning JSON response.

    Parameters:
    - fastapi_request: The FastAPI Request object.
    - file: The uploaded evaluation file.
    - subdirectory: Optional subdirectory within the evaluation uploads directory.
    - evaluation_request: Pydantic model containing evaluation parameters.

    Returns:
    - Dict[str, Any]: JSON response with evaluation summary and download URL.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    # Upload the file using the internal helper
    upload_resp = await _upload_evaluation_file(file, subdirectory)

    if "file_path" not in upload_resp:
        raise HTTPException(status_code=400, detail="File upload failed.")

    file_path = upload_resp["file_path"]

    try:
        avg_scores, summary, excel_path = await _evaluate_agent_performance(
            evaluation_request=evaluation_request,
            file_path=file_path
        )

        file_name = os.path.basename(excel_path)
        download_url = f"{fastapi_request.base_url}evaluation/download-result?file_name={file_name}"
        log.info(f"Evaluation completed successfully. Download URL: {download_url}")
        return {
            "message": "Evaluation completed successfully",
            "download_url": download_url,
            "average_scores": avg_scores,
            "diagnostic_summary": summary
        }

    except Exception as e:
        log.error(f"Evaluation failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(e)}")


