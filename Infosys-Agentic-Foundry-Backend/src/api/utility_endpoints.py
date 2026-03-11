# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import json
import shutil
import asyncpg
import psycopg2
import requests
import re
from typing import List, Dict
from pathlib import Path
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Query, BackgroundTasks
from fastapi.responses import JSONResponse

import azure.cognitiveservices.speech as speechsdk
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import TextLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain_pymupdf4llm import PyMuPDF4LLMLoader

from src.auth.authorization_service import AuthorizationService
from src.database.services import KnowledgebaseService, ModelService, VMManagementService
from src.utils.file_manager import FileManager
from src.utils.tool_file_manager import ToolFileManager
from src.api.dependencies import ServiceProvider # The dependency provider
from telemetry_wrapper import logger as log, update_session_context
from dotenv import load_dotenv

load_dotenv()

STORAGE_PROVIDER=os.getenv("STORAGE_PROVIDER","")


from src.utils.secrets_handler import current_user_department
from src.auth.models import UserRole, User
from src.auth.dependencies import get_current_user

from src.utils.secrets_handler import current_user_department
from src.auth.models import UserRole, User
from src.auth.dependencies import get_current_user


from src.schemas import VMConnectionRequest
from src.utils.tool_code_dependency_analyzer import ToolCodeDependencyExtractor
from dotenv import load_dotenv
load_dotenv()

router = APIRouter(prefix="/utility", tags=["Utility - (Upload / Download Files | Knowledge Base | Speech-To-Text | Markdown Documentation)"])


STORAGE_PROVIDER=os.getenv('STORAGE_PROVIDER',"")
KB_SERVER_ENDPOINT=os.getenv('KB_SERVER_ENDPOINT', None)

@router.get("/get/version")
async def get_version_endpoint(request: Request):
    """
    API endpoint to retrieve the application version.

    Parameters:
    - request: The FastAPI Request object.

    Returns:
    - Dict[str, str]: A dictionary containing the application version.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Assuming VERSION file is in the same directory as the main app file
        version_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'VERSION')
        with open(version_file_path) as f:
            version = f.read().strip()
        return {"version": version}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="VERSION file not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving version: {e}")


@router.get('/get/models')
async def get_available_models_endpoint(
    request: Request, 
    temperature: float = Query(default=0.0, ge=0.0, le=1.0, description="Temperature for model inference (0.0 to 1.0)"),
    model_service: ModelService = Depends(ServiceProvider.get_model_service)
):
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    try:
        data = await model_service.get_all_available_model_names()
        log.debug(f"Models retrieved successfully: {data}, Temperature: {temperature}")
        default_model_name = data[0] if data else None
        return JSONResponse(content={"models": data, "temperature": temperature, "default_model_name": default_model_name})

    except asyncpg.PostgresError as e:
        log.error(f"Database error while fetching models: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    except Exception as e:
        # Handle other unforeseen errors
        log.error(f"Unexpected error while fetching models: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


## ============ User Uploaded Files Endpoints ============

@router.post("/files/user-uploads/upload/")
async def upload_file_endpoint(request: Request, files: List[UploadFile] = File(...), subdirectory: str = "", file_manager: FileManager = Depends(ServiceProvider.get_file_manager)):
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    # Get user's department and create department-specific subdirectory
    user_department = current_user_department.get()
    if not user_department:
        raise HTTPException(status_code=400, detail="User department not found")
    
    # Combine department with any additional subdirectory
    department_subdirectory = user_department
    if subdirectory:
        department_subdirectory = os.path.join(user_department, subdirectory)

    file_names = []

    if STORAGE_PROVIDER=="":
        # Handle local file storage
        for file in files:
            file_location = await file_manager.save_uploaded_file(uploaded_file=file, subdirectory=department_subdirectory)
            log.info(f"File '{file.filename}' uploaded successfully to '{file_location}' for department '{user_department}'")
            file_names.append(file.filename)

        return {"info": f"Files {file_names} saved successfully to department '{user_department}'."}
    else:
        status={}

        for uploaded_file in files:
            status[uploaded_file.filename] = await file_manager.upload_file_to_storage(file=uploaded_file, storage_provider=STORAGE_PROVIDER)
            file_names.append(uploaded_file.filename)

        return status


@router.get("/files/user-uploads/get-file-structure/")
async def get_file_structure_endpoint(request: Request, file_manager: FileManager = Depends(ServiceProvider.get_file_manager)):
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    # Get user's department to filter department-specific files
    user_department = current_user_department.get()
    if not user_department:
        raise HTTPException(status_code=400, detail="User department not found")

    # Show user's department files + universal files (root-level files outside any department folder)
    file_structure = await file_manager.generate_file_structure(department_filter=user_department, include_universal=True)
    log.info(f"File structure retrieved for department '{user_department}' with universal files")
    return JSONResponse(content=file_structure)

@router.get('/files/user-uploads/download')
async def download_file_endpoint(request: Request, filename: str = Query(...), sub_dir_name: str = Query(None), file_manager: FileManager = Depends(ServiceProvider.get_file_manager), user_data: User = Depends(get_current_user)):
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    
    if STORAGE_PROVIDER=="":
        # Get user's department and restrict access to their department folder only
        user_department = user_data.department_name
        if not user_department:
            raise HTTPException(status_code=400, detail="User department not found")
        
        # Validate filename
        if not filename or filename.strip() == "":
            raise HTTPException(status_code=400, detail="Filename cannot be empty")
        
        # Combine department with any additional subdirectory
        if sub_dir_name and sub_dir_name.strip():
            # Sanitize subdirectory name
            sub_dir_name = sub_dir_name.strip().lstrip("/\\")
            
            # Check if sub_dir_name already starts with the department name
            if sub_dir_name.startswith(user_department + "/") or sub_dir_name.startswith(user_department + "\\"):
                # Use sub_dir_name as-is since it already includes the department
                department_subdirectory = sub_dir_name.replace("\\", "/")  # Normalize path separators
            elif sub_dir_name == user_department:
                # If sub_dir_name is exactly the department name, just use department
                department_subdirectory = user_department
            else:
                # Sub_dir_name is a subdirectory within the department
                department_subdirectory = os.path.join(user_department, sub_dir_name)
        else:
            # No subdirectory specified, use department root
            department_subdirectory = user_department
        
        # Also allow downloading universal files (root-level files outside any department folder)
        # Check if the file exists at root level when not found in department directory
        try:
            return await file_manager.get_file(filename=filename, subdirectory=department_subdirectory)
        except HTTPException as he:
            # If file not found in department folder, try root level (universal files)
            if he.status_code == 404 or "not found" in str(he.detail).lower():
                if not sub_dir_name or not sub_dir_name.strip():
                    try:
                        return await file_manager.get_file(filename=filename, subdirectory="")
                    except Exception:
                        pass  # Fall through to original error
            raise
        except Exception as e:
            log.error(f"Error downloading file '{filename}' for department '{user_department}': {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error downloading file: {str(e)}")
    else:
        return await file_manager.download_file_from_storage(filename=filename, storage_provider=STORAGE_PROVIDER)

@router.delete("/files/user-uploads/delete/")
async def delete_file_endpoint(request: Request, file_path: str, file_manager: FileManager = Depends(ServiceProvider.get_file_manager)):
    user_id = request.cookies.get("user_id")
    
    user_session = request.cookies.get("user_session")
    
    file_name=Path(file_path).name

    update_session_context(user_session=user_session, user_id=user_id)
    
    file_name=Path(file_path).name

    if STORAGE_PROVIDER=="":
        user_department = current_user_department.get()
        if not user_department:
            raise HTTPException(status_code=400, detail="User department not found")
        
        # Normalize the file path and ensure it's within the user's department
        file_path = file_path.strip().lstrip("/\\")  # Remove leading slashes
        
        # Block deletion of root-level (universal) files — they are shared across all departments
        # A root-level file has no path separator (e.g. "report.csv" vs "dept/report.csv")
        if os.sep not in file_path and "/" not in file_path:
            raise HTTPException(
                status_code=403,
                detail="Access denied: Universal files (root-level files shared across departments) cannot be deleted."
            )
        
        # Always ensure the file path is within the user's department
        if not file_path.startswith(user_department):
            # Prepend department if not already there
            department_file_path = os.path.join(user_department, file_path)
        else:
            department_file_path = file_path
        
        # Additional security check - ensure the final path still starts with department
        if not department_file_path.startswith(user_department):
            raise HTTPException(status_code=403, detail="Access denied: Cannot delete files outside your department")
        
        return await file_manager.delete_file(file_path=department_file_path)
    else:
        return await file_manager.delete_file_from_storage(file_name=file_name, storage_provider=STORAGE_PROVIDER)

## ==========================================================


## ============ Knowledge Base Endpoints ============

KB_DIR = "KB_DIR"
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", None)
GOOGLE_EMBEDDING_MODEL = os.environ.get("GOOGLE_EMBEDDING_MODEL", "models/text-embedding-004")


async def check_kb_server_health() -> bool:
    """
    Check if the KB server is online and healthy.
    
    Returns:
    - bool: True if server is healthy, False otherwise
    """
    if not KB_SERVER_ENDPOINT:
        log.error("KB_SERVER_ENDPOINT is not configured")
        return False
    
    try:
        response = requests.get(
            f"{KB_SERVER_ENDPOINT}/health",
            timeout=5
        )
        response.raise_for_status()
        health_data = response.json()
        
        if health_data.get("status") == "healthy":
            log.info(f"KB server is healthy: {health_data}")
            return True
        else:
            log.warning(f"KB server reports unhealthy status: {health_data}")
            return False
            
    except requests.exceptions.RequestException as e:
        log.error(f"Failed to connect to KB server health endpoint: {e}")
        return False
    except Exception as e:
        log.error(f"Unexpected error checking KB server health: {e}")
        return False
 

@router.post("/knowledge-base/documents/upload")
async def upload_knowledge_base_documents_endpoint(
        request: Request,
        background_tasks: BackgroundTasks,
        session_id: str = Form(...),
        kb_name: str = Form(...),
        user_email: str = Form(...),
        is_public: bool = Form(False),
        shared_with_departments: str = Form(None),
        files: List[UploadFile] = File(...),
        file_manager: FileManager = Depends(ServiceProvider.get_file_manager),
        knowledgebase_service: KnowledgebaseService = Depends(ServiceProvider.get_knowledgebase_service),
        user_data: User = Depends(get_current_user),
        authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
    ):
    """
    Upload documents for a knowledge base by forwarding to KB server endpoint.

    Parameters:
    - session_id: Session ID for tracking
    - kb_name: Knowledge base name
    - user_email: Email of the user uploading the documents
    - is_public: Whether the KB should be publicly accessible to all departments (default: false)
    - shared_with_departments: Comma-separated list of department names to share the KB with
    - files: List of uploaded documents (PDF, DOCX, PPTX, TXT, HTML, XLSX)

    Returns:
    - Status message with KB ID and processing status
    """
    # Check knowledgebase access permission
    user_department = user_data.department_name
    has_access = await authorization_service.check_knowledgebase_access(user_data.role, user_department)
    if not has_access:
        raise HTTPException(status_code=403, detail="You don't have permission to access knowledge base endpoints.")

    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    # Check if KB server is online before proceeding
    is_kb_server_healthy = await check_kb_server_health()
    if not is_kb_server_healthy:
        raise HTTPException(
            status_code=503,
            detail="KB server is not available. Please try again later."
        )
    
    try:
        # Sanitize all filenames before processing
        sanitized_filenames = []
        for f in files:
            safe_name = f.filename
            # Remove path separators and parent directory references
            safe_name = safe_name.replace('..', '').replace('/', '_').replace('\\', '_')
            # Extract basename to remove any remaining path components
            safe_name = os.path.basename(safe_name)
            # Replace other dangerous characters
            safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', safe_name)
            # Ensure filename doesn't start with dot (hidden files)
            if safe_name.startswith('.'):
                safe_name = 'file' + safe_name
            # Fallback for empty filename
            if not safe_name:
                safe_name = "unnamed_file.bin"
            sanitized_filenames.append(safe_name)
        
        # Parse shared_with_departments from comma-separated string to list
        departments_list = None
        if shared_with_departments:
            departments_list = [d.strip() for d in shared_with_departments.split(',') if d.strip()]
        
        # Validate: is_public and shared_with_departments are mutually exclusive
        if is_public and departments_list:
            raise HTTPException(
                status_code=400,
                detail="Cannot set both 'is_public' and 'shared_with_departments'. A public knowledge base is already accessible to all departments."
            )
        
        kb_status = await knowledgebase_service.create_knowledgebase(
            kb_name=kb_name,
            list_of_documents=sanitized_filenames,
            created_by=user_email,
            department_name=user_data.department_name,
            is_public=is_public,
            shared_with_departments=departments_list
        )
        kb_id = kb_status.get("knowledgebase_id", "")
        
        upload_results = []
        for idx, file in enumerate(files):
            try:
                await file.seek(0)
                
                file_content = await file.read()
                
                # Use already sanitized filename
                safe_filename = sanitized_filenames[idx]
                
                files_payload = {
                    'file': (safe_filename, file_content, file.content_type or 'application/octet-stream')
                }
                
                params = {
                    'kb_id': kb_id,
                    'created_by': user_email
                }
                
                response = requests.post(
                    f"{KB_SERVER_ENDPOINT}/upload-documents",
                    files=files_payload,
                    params=params,
                    timeout=300
                )
                
                response.raise_for_status()
                result = response.json()
                upload_results.append({
                    "filename": safe_filename,
                    "original_filename": file.filename,
                    "status": "success",
                    "result": result
                })
                log.info(f"Successfully uploaded {safe_filename} (original: {file.filename}) to KB server for kb_id: {kb_id}")
                
            except requests.exceptions.RequestException as e:
                log.error(f"Error uploading {file.filename} to KB server: {e}")
                upload_results.append({
                    "filename": file.filename,
                    "status": "failed",
                    "error": str(e)
                })
            except Exception as e:
                log.error(f"Unexpected error uploading {file.filename}: {e}")
                upload_results.append({
                    "filename": file.filename,
                    "status": "failed",
                    "error": str(e)
                })
        
        if STORAGE_PROVIDER!='':
            background_tasks.add_task(
                upload_kb_files,
                files=files,
                kb_name=kb_name,
                file_manager=file_manager
            )
        
        log.info(f"KB documents uploaded to server: '{kb_name}' (ID: {kb_id})")
        
        return {
            "message": f"Documents uploaded to KB server for '{kb_name}'",
            "kb_name": kb_name,
            "kb_id": kb_id,
            "department_name": user_data.department_name,
            "is_public": is_public,
            "shared_with_departments": departments_list or [],
            "upload_results": upload_results,
            "is_new": kb_status.get("is_created", False)
        }
        
    except Exception as e:
        log.error(f"Error uploading KB documents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to upload documents: {str(e)}")


class UpdateKBSharingRequest(BaseModel):
    """Request model for updating KB visibility and sharing settings."""
    is_public: bool = None
    shared_with_departments: List[str] = None


@router.put("/knowledge-base/{kb_id}/sharing")
async def update_kb_sharing_endpoint(
    request: Request,
    kb_id: str,
    body: UpdateKBSharingRequest,
    knowledgebase_service: KnowledgebaseService = Depends(ServiceProvider.get_knowledgebase_service),
    user_data: User = Depends(get_current_user),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Update the visibility (is_public) and/or department sharing for a knowledge base.
    Only the owning department's admin/super_admin can update sharing settings.

    Parameters:
    - kb_id: The knowledge base ID
    - is_public: Whether the KB should be publicly accessible to all departments
    - shared_with_departments: List of department names to share the KB with (replaces existing sharing)

    Returns:
    - Updated sharing information
    """
    # Check knowledgebase access permission
    user_department = user_data.department_name
    has_access = await authorization_service.check_knowledgebase_access(user_data.role, user_department)
    if not has_access:
        raise HTTPException(status_code=403, detail="You don't have permission to access knowledge base endpoints.")

    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    if body.is_public is None and body.shared_with_departments is None:
        raise HTTPException(status_code=400, detail="At least one of 'is_public' or 'shared_with_departments' must be provided.")

    # Validate: is_public and shared_with_departments are mutually exclusive
    if body.is_public and body.shared_with_departments:
        raise HTTPException(
            status_code=400,
            detail="Cannot set both 'is_public' and 'shared_with_departments'. A public knowledge base is already accessible to all departments."
        )

    try:
        result = await knowledgebase_service.update_kb_sharing(
            kb_id=kb_id,
            user_email=user_data.email,
            department_name=user_data.department_name,
            is_public=body.is_public,
            shared_with_departments=body.shared_with_departments
        )

        return {
            "message": f"Knowledge base sharing settings updated successfully",
            **result
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error updating KB sharing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error updating KB sharing: {str(e)}")


@router.get("/knowledge-base/list")
async def list_knowledge_base_endpoint(
    request: Request,
    knowledgebase_service: KnowledgebaseService = Depends(ServiceProvider.get_knowledgebase_service),
    user_data: User = Depends(get_current_user),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    List all knowledge bases from database.
    Returns KB records with metadata including original email addresses.
    Also includes knowledge bases shared with the user's department.

    Returns:
    - Dictionary with knowledge_bases list and count
    """
    # Check knowledgebase access permission
    user_department = user_data.department_name
    has_access = await authorization_service.check_knowledgebase_access(user_data.role, user_department)
    if not has_access:
        raise HTTPException(status_code=403, detail="You don't have permission to access knowledge base endpoints.")

    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    try:
        kb_records = await knowledgebase_service.get_all_knowledgebases(department_name=user_data.department_name)
        
        # Enrich records with shared_with_departments info
        kb_sharing_repo = None
        try:
            kb_sharing_repo = ServiceProvider.get_kb_sharing_repo()
        except Exception:
            pass
        
        enriched_kbs = []
        for kb in kb_records:
            kb_entry = {
                "kb_id": kb.get("knowledgebase_id"),
                "kb_name": kb.get("knowledgebase_name"),
                "list_of_documents": kb.get("list_of_documents", "").split(",") if kb.get("list_of_documents") else [],
                "created_by": kb.get("created_by"),
                "created_on": str(kb.get("created_on")) if kb.get("created_on") else None,
                "department_name": kb.get("department_name", "General"),
                "is_public": kb.get("is_public", False),
                "is_shared": kb.get("is_shared", False),
                "shared_with_departments": []
            }
            
            # Only fetch shared departments for KBs the user owns (not shared ones)
            if not kb.get("is_shared", False) and kb_sharing_repo:
                try:
                    shared_depts = await kb_sharing_repo.get_shared_departments_for_kb(kb.get("knowledgebase_id"))
                    kb_entry["shared_with_departments"] = [d.get("target_department") for d in shared_depts]
                except Exception:
                    pass
            
            enriched_kbs.append(kb_entry)
        
        return {
            "knowledge_bases": enriched_kbs,
            "count": len(enriched_kbs)
        }
    except Exception as e:
        log.error(f"Error listing knowledge bases: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error listing knowledge bases: {str(e)}")


@router.get("/knowledge-base/get/{kb_id}")
async def get_knowledge_base_by_id_endpoint(
    request: Request,
    kb_id: str,
    knowledgebase_service: KnowledgebaseService = Depends(ServiceProvider.get_knowledgebase_service),
    user_data: User = Depends(get_current_user),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Get knowledge base details by ID.

    Parameters:
    - kb_id: Knowledge base ID

    Returns:
    - Dictionary with KB details including id, name, documents, creator email, and creation date
    """
    # Check knowledgebase access permission
    user_department = user_data.department_name
    has_access = await authorization_service.check_knowledgebase_access(user_data.role, user_department)
    if not has_access:
        raise HTTPException(status_code=403, detail="You don't have permission to access knowledge base endpoints.")

    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    try:
        # Fetch using repository method without email-to-username transformation
        kb_dict = await knowledgebase_service.knowledgebase_repo.get_knowledgebase_by_id_with_email(kb_id=kb_id)
        
        if not kb_dict:
            raise HTTPException(status_code=404, detail=f"Knowledge base with ID '{kb_id}' not found")
        return {
            "kb_id": kb_dict.get("knowledgebase_id"),
            "kb_name": kb_dict.get("knowledgebase_name"),
            "list_of_documents": kb_dict.get("list_of_documents", "").split(",") if kb_dict.get("list_of_documents") else [],
            "created_by": kb_dict.get("created_by"),
            "created_on": str(kb_dict.get("created_on")) if kb_dict.get("created_on") else None,
            "department_name": kb_dict.get("department_name", "General")
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error fetching knowledge base {kb_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list knowledge bases: {str(e)}")


@router.post("/knowledge-base/get/by-list")
async def get_knowledgebases_by_list_endpoint(
    request: Request,
    kb_ids: List[str],
    knowledgebase_service: KnowledgebaseService = Depends(ServiceProvider.get_knowledgebase_service),
    user_data: User = Depends(get_current_user),
    authorization_service:AuthorizationService  = Depends(ServiceProvider.get_authorization_service)
):
    """Retrieves knowledgebases by a list of IDs with original email addresses in a single query."""
    # Check knowledgebase access permission
    user_department = user_data.department_name
    has_access = await authorization_service.check_knowledgebase_access(user_data.role, user_department)
    if not has_access:
        raise HTTPException(status_code=403, detail="You don't have permission to access knowledge base endpoints.")

    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    try:
        # Fetch all knowledgebases in a single database query
        kb_records = await knowledgebase_service.knowledgebase_repo.get_knowledgebases_by_ids_with_email(kb_ids=kb_ids)
        
        knowledgebases = [
            {
                "kb_id": kb.get("knowledgebase_id"),
                "kb_name": kb.get("knowledgebase_name"),
                "list_of_documents": kb.get("list_of_documents", "").split(",") if kb.get("list_of_documents") else [],
                "created_by": kb.get("created_by"),
                "created_on": str(kb.get("created_on")) if kb.get("created_on") else None,
                "department_name": kb.get("department_name", "General")
            }
            for kb in kb_records
        ]
        
        return knowledgebases
    except Exception as e:
        log.error(f"Error retrieving knowledgebases by list: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error retrieving knowledgebases: {str(e)}")


@router.post("/knowledge-base/get/by-list-for-agent")
async def get_knowledgebases_by_list_summary_endpoint(
    request: Request,
    kb_ids: List[str],
    knowledgebase_service: KnowledgebaseService = Depends(ServiceProvider.get_knowledgebase_service)
):
    """
    Retrieves knowledgebases by a list of IDs, returning only summary/limited fields.
    Similar to /tools/get/by-list which returns limited tool info (id, name, tags).

    Parameters:
    ----------
    kb_ids : List[str]
        List of knowledgebase IDs to retrieve.

    Returns:
    -------
    dict
        A dictionary containing:
        - knowledgebases: List of summary objects with kb_id, kb_name, and document_count.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    knowledgebases = []
    for kb_id in kb_ids:
        try:
            kb_dict = await knowledgebase_service.knowledgebase_repo.get_knowledgebase_by_id_with_email(kb_id=kb_id)
            if kb_dict:
                knowledgebases.append({
                    "kb_id": kb_dict.get("knowledgebase_id"),
                    "kb_name": kb_dict.get("knowledgebase_name")
                })
        except Exception as e:
            log.warning(f"Error fetching KB {kb_id} in summary list: {e}")
            continue

    return {
        "knowledgebases": knowledgebases
    }


class DeleteKnowledgebasesRequest(BaseModel):
    kb_ids: List[str]
    user_email: str

@router.delete("/remove-knowledgebases")
async def delete_knowledgebases(
    request: Request,
    delete_request: DeleteKnowledgebasesRequest,
    knowledgebase_service: KnowledgebaseService = Depends(ServiceProvider.get_knowledgebase_service),
    user_data: User = Depends(get_current_user),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Delete knowledgebases by their IDs.
    
    Access Control:
    - SuperAdmin is not allowed to delete knowledgebases
    - Admins can delete any knowledgebase within their department
    - Non-admin users can only delete knowledgebases they created within their department
    - Cannot delete knowledgebases that are mapped to any agent
    
    Parameters:
    - kb_ids: List of knowledgebase IDs to delete
    - user_email: Email of the user requesting deletion
    
    Returns:
    - Dictionary with deleted and failed knowledgebases
    """
    # SuperAdmin cannot delete knowledgebases
    if user_data.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to delete knowledgebases.")
    
    # Check knowledgebase access permission
    user_department = user_data.department_name
    has_access = await authorization_service.check_knowledgebase_access(user_data.role, user_department)
    if not has_access:
        raise HTTPException(status_code=403, detail="You don't have permission to access knowledge base endpoints.")
    
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    # Check if user is admin in their department
    is_admin = await authorization_service.has_role(
        user_email=user_id, 
        required_role=UserRole.ADMIN, 
        department_name=user_data.department_name
    )
    
    deleted_kbs = []
    failed_kbs = []
    
    for kb_id in delete_request.kb_ids:
        try:
            # Get KB details from database with original email
            kb_data = await knowledgebase_service.knowledgebase_repo.get_knowledgebase_by_id(kb_id=kb_id)
            
            if not kb_data:
                failed_kbs.append({
                    "kb_id": kb_id,
                    "kb_name": "Unknown",
                    "error": "Knowledgebase not found"
                })
                continue
            
            kb_name = kb_data.get("knowledgebase_name", "Unknown")
            kb_department = kb_data.get("department_name", "General")
            kb_creator = kb_data.get("created_by", "")
            
            # Check if user's department owns this knowledgebase
            if kb_department != user_data.department_name:
                failed_kbs.append({
                    "kb_id": kb_id,
                    "kb_name": kb_name,
                    "error": f"You cannot delete this knowledgebase. It belongs to department '{kb_department}'. Only users from the owning department can delete it."
                })
                log.warning(f"User {user_id} from department '{user_data.department_name}' attempted to delete KB {kb_id} from department '{kb_department}'")
                continue
            
            # Check if knowledgebase is being used by any agents
            agents_using_kb = await knowledgebase_service.agent_kb_mapping_repo.get_agents_using_knowledgebase(kb_id=kb_id)
            
            if agents_using_kb:
                agent_count = len(agents_using_kb)
                agent_names = [agent.get("agentic_application_name", "Unknown") for agent in agents_using_kb[:3]]
                agent_list = ", ".join(agent_names)
                if agent_count > 3:
                    agent_list += f" and {agent_count - 3} more"
                
                failed_kbs.append({
                    "kb_id": kb_id,
                    "kb_name": kb_name,
                    "error": f"This knowledgebase is being used by {agent_count} application(s): {agent_list}. Please remove it from these applications before deleting."
                })
                log.warning(f"Cannot delete KB {kb_id}: used by {agent_count} agent(s)")
                continue
            
            # Check permissions - admin or creator
            is_creator = (kb_creator == user_data.username)
            if not (is_admin or is_creator):
                log.warning(f"User {user_id} attempted to delete KB {kb_id} without admin privileges or creator access")
                failed_kbs.append({
                    "kb_id": kb_id,
                    "kb_name": kb_name,
                    "error": "Admin privileges or knowledgebase creator access required to delete this knowledgebase"
                })
                continue
            
            # Delete from database
            delete_result = await knowledgebase_service.delete_knowledgebase(kb_id=kb_id)
            
            if delete_result.get("deleted"):
                deleted_kbs.append({
                    "kb_id": kb_id,
                    "kb_name": kb_name
                })
                log.info(f"Successfully deleted knowledgebase {kb_id} ({kb_name}) by {user_id}")
            else:
                failed_kbs.append({
                    "kb_id": kb_id,
                    "kb_name": kb_name,
                    "error": "Failed to delete from database"
                })
                
        except Exception as e:
            log.error(f"Error deleting knowledgebase {kb_id}: {e}", exc_info=True)
            failed_kbs.append({
                "kb_id": kb_id,
                "kb_name": kb_data.get("knowledgebase_name", "Unknown") if kb_data else "Unknown",
                "error": str(e)
            })
    
    # If all deletions failed, return 400 or appropriate error
    if len(failed_kbs) == len(delete_request.kb_ids) and len(failed_kbs) > 0:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "All knowledgebase deletions failed",
                "failed_kbs": failed_kbs,
                "total_requested": len(delete_request.kb_ids),
                "total_failed": len(failed_kbs)
            }
        )
    
    # If some failed, return 400 error with details
    if len(failed_kbs) > 0:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Some knowledgebases could not be deleted",
                "deleted_kbs": deleted_kbs,
                "failed_kbs": failed_kbs,
                "total_requested": len(delete_request.kb_ids),
                "total_deleted": len(deleted_kbs),
                "total_failed": len(failed_kbs)
            }
        )
    
    # All successful
    return {
        "message": "All knowledgebases deleted successfully",
        "deleted_kbs": deleted_kbs,
        "failed_kbs": failed_kbs,
        "total_requested": len(delete_request.kb_ids),
        "total_deleted": len(deleted_kbs),
        "total_failed": len(failed_kbs)
    }
 
## ==========================================================


## ============ speech-to-text ============

@router.post("/transcribe/")
async def transcribe_audio_endpoint(file: UploadFile = File(...)) -> Dict[str, str]:
    STT_ENDPOINT = os.getenv("STT_ENDPOINT")
    SPEECH_KEY = os.getenv("SPEECH_KEY")
    HTTP_PROXY = os.getenv("HTTP_PROXY", "")
    HTTPS_PROXY = os.getenv("HTTPS_PROXY", "")
    
    # Set environment proxy variables
    os.environ['HTTP_PROXY'] = HTTP_PROXY
    os.environ['HTTPS_PROXY'] = HTTPS_PROXY

    # Sanitize filename before processing
    safe_name = file.filename
    # Remove path separators and parent directory references
    safe_name = safe_name.replace('..', '').replace('/', '_').replace('\\', '_')
    # Extract basename to remove any remaining path components
    safe_name = os.path.basename(safe_name)
    # Replace other dangerous characters
    safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', safe_name)
    # Ensure filename doesn't start with dot (hidden files)
    if safe_name.startswith('.'):
        safe_name = 'file' + safe_name
    # Fallback for empty filename
    if not safe_name:
        safe_name = "unnamed_audio.wav"

    os.makedirs('audios', exist_ok=True)
    file_location = os.path.join("audios", safe_name)
    file_content_bytes: bytes = await file.read()
    file_path_obj = Path(file_location)
    file_path_obj.write_bytes(file_content_bytes)

    url = f"{STT_ENDPOINT}/speech/recognition/conversation/cognitiveservices/v1?language=en-US"
    
    headers = {
        'Ocp-Apim-Subscription-Key': SPEECH_KEY,
        'Content-Type': 'audio/wav; codecs=audio/pcm; samplerate=16000'
    }
    
    definition = {
        "displayText": True,
        "diarizationEnabled": False
    }

    proxies = {
        'http': HTTP_PROXY,
        'https': HTTPS_PROXY
    } if HTTP_PROXY or HTTPS_PROXY else None

    try:
        with open(file_location, 'rb') as audio_file:
            files = {
                'audio': (safe_name, audio_file, 'audio/wav'),
                'definition': (None, json.dumps(definition), 'application/json')
            }

            response = requests.post(
                url,
                headers=headers,
                files=files,
                proxies=proxies,
                timeout=300
            )

        response.raise_for_status()
        result = response.json()

        if 'combinedPhrases' in result and len(result['combinedPhrases']) > 0:
            transcription = result['combinedPhrases'][0]['text']
        elif 'phrases' in result and len(result['phrases']) > 0:
            transcription = ' '.join([phrase['text'] for phrase in result['phrases']])
        else:
            transcription = "No speech could be recognized."

        os.remove(file_location)
        return {"transcription": transcription}

    except requests.exceptions.HTTPError as e:
        error_detail = e.response.text
        try:
            error_json = e.response.json()
            error_detail = json.dumps(error_json, indent=2)
        except:
            pass

        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"HTTP Error: {e.response.status_code} - {error_detail}"
        )
    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=500,
            detail=f"Request Error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal Server Error: {str(e)}"
        )

## ==========================================================

async def upload_kb_files(files:List[UploadFile],kb_name:str,file_manager):
    """
    Upload knowledge base files to cloud storage (Azure Blob/S3).
    Sanitizes filenames and creates blob paths.
    """
    if STORAGE_PROVIDER!='':
        upload_status={}
        for file in files:
            try:
                await file.seek(0)
                # Sanitize filename to prevent path traversal
                safe_filename = file.filename
                # Remove path separators and parent directory references
                safe_filename = safe_filename.replace('..', '').replace('/', '_').replace('\\', '_')
                # Extract basename to remove any remaining path components
                safe_filename = os.path.basename(safe_filename)
                # Replace other dangerous characters
                safe_filename = re.sub(r'[^a-zA-Z0-9._-]', '_', safe_filename)
                # Ensure filename doesn't start with dot (hidden files)
                if safe_filename.startswith('.'):
                    safe_filename = 'file' + safe_filename
                # Fallback for empty filename
                if not safe_filename:
                    safe_filename = "unnamed_file.bin"
                
                blob_name=f"{kb_name}/{safe_filename}"
                upload_result=await file_manager.upload_kb_files_to_storage(file=file,storage_provider=STORAGE_PROVIDER,blob_name=blob_name)
                upload_status[safe_filename]=upload_result
            except Exception as e:
                log.error(f"Error uploading {file.filename}: {e}")
        return upload_status


## ============ Documentation Files Endpoints ============

DOCS_ROOT = Path(r"C:\Agentic_foundary_documentation\docs")

async def _list_markdown_files_helper(directory: Path) -> List[str]:
    """
    Recursively lists all Markdown (.md) files in the given directory and its subdirectories.
    """
    log.debug(f"Listing markdown files in directory: {directory.resolve()}")

    if not directory.exists() or not directory.is_dir():
        raise HTTPException(status_code=404, detail=f"Directory not found at {directory.resolve()}")

    # Ensure path is within DOCS_ROOT to prevent directory traversal
    abs_directory = directory.resolve()
    if not abs_directory.startswith(DOCS_ROOT.resolve()):
        raise HTTPException(status_code=400, detail="Invalid directory path. Must be within documentation root.")

    files = [str(file.relative_to(DOCS_ROOT)) for file in directory.rglob("*.md")]
    return files

@router.get("/docs/list-all-markdown-files")
async def list_all_docs_files_endpoint(request: Request):
    """
    API endpoint to list all Markdown files in the documentation root (including subfolders).

    Parameters:
    - request: The FastAPI Request object.

    Returns:
    - Dict[str, List[str]]: A dictionary containing the list of files.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        files = await _list_markdown_files_helper(DOCS_ROOT)
        return {"files": files}
    except HTTPException:
        raise # Re-raise HTTPExceptions
    except Exception as e:
        log.error(f"Error listing all documentation files: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@router.get("/docs/list-markdown-files-in-directory/{dir_name}")
async def list_docs_files_in_directory_endpoint(request: Request, dir_name: str):
    """
    API endpoint to list all Markdown files in a specific subdirectory under the documentation root.

    Parameters:
    - request: The FastAPI Request object.
    - dir_name: The name of the subdirectory.

    Returns:
    - Dict[str, Any]: A dictionary containing the directory name and list of files.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    target_dir = DOCS_ROOT / dir_name
    
    try:
        files = await _list_markdown_files_helper(target_dir)
        return {"directory": dir_name, "files": files}
    except HTTPException:
        raise # Re-raise HTTPExceptions
    except Exception as e:
        log.error(f"Error listing documentation files in directory '{dir_name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

## ==========================================================


@router.get("/sync-tool-files")
async def sync_tool_files(
    request: Request,
    service_provider: ServiceProvider = Depends()
):
    """
    Sync existing database tools to .py files (one-time operation).
    Skips tools that already have files - only creates missing ones.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    try:
        # Use the injected tool_file_manager from service provider
        tool_file_manager = service_provider.get_tool_file_manager()
        result = await tool_file_manager.sync_existing_tools_from_db()
        
        if result.get("success"):
            return {
                "success": True,
                "message": f"Sync complete: {result['created']} files created, {result['skipped']} skipped",
                "total_tools": result['total'],
                "files_created": result['created'],
                "files_skipped": result['skipped']
            }
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Unknown error"))
            
    except Exception as e:
        log.error(f"Error syncing tool files: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


## ==========================================================



## ============ VM Management Endpoints ============

@router.get("/get-missing-dependencies")
async def get_missing_dependencies(request: Request):
    """
    Analyze tool code dependencies and identify missing packages.
    
    This endpoint analyzes all tool code snippets in the database, extracts their
    dependencies, validates them against the local/remote environment and requirements.txt,
    and returns only the packages that need to be installed and those installed but not in requirements.txt.

    Args:
        request: FastAPI Request object

    Returns:
        Dict containing:
            - modules_to_install: List of PyPI package names that need installation
            - modules_installed_not_in_requirements: List of packages installed but not in requirements.txt
            - count_to_install: Number of packages needing installation
            - count_installed_not_in_requirements: Number of packages installed but not in requirements.txt
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    try:
        db_config = {
            'host': os.getenv('POSTGRESQL_HOST'),
            'database': os.getenv('DATABASE'),
            'user': os.getenv('POSTGRESQL_USER'),
            'password': os.getenv('POSTGRESQL_PASSWORD'),
            'port': os.getenv('POSTGRESQL_PORT')
        }
        
        requirements_file = Path(__file__).parent.parent.parent / "requirements.txt"
        
        extractor = ToolCodeDependencyExtractor(
            db_config=db_config,
            requirements_file=str(requirements_file)
        )
        
        modules_to_install = await extractor.run()
        modules_installed_not_in_requirements = extractor.stats.get('installed_not_in_requirements', [])
        
        return {
            "modules_to_install": modules_to_install,
            "modules_installed_not_in_requirements": modules_installed_not_in_requirements,
            "count_to_install": len(modules_to_install),
            "count_installed_not_in_requirements": len(modules_installed_not_in_requirements)
        }
        
    except Exception as e:
        log.error(f"Dependency analysis error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# @router.post("/vm/install-dependencies")
# async def install_dependencies_on_vm_endpoint(
#         request: Request,
#         vm_request: VMConnectionRequest,
#         vm_service: "VMManagementService" = Depends(ServiceProvider.get_vm_management_service)
#     ):
#     """Install Python modules on a remote VM"""

#     user_id = request.cookies.get("user_id")
#     user_session = request.cookies.get("user_session")
#     update_session_context(user_session=user_session, user_id=user_id)
#     try:
#         result = await vm_service.install_dependencies(modules=vm_request.modules)
#         if result["success"]:
#             return JSONResponse(content=result, status_code=200)
#         else:
#             return JSONResponse(content=result, status_code=400)
#     except Exception as e:
#         log.error(f"VM management endpoint error: {str(e)}", exc_info=True)
#         raise HTTPException(status_code=500, detail=str(e))

@router.get("/get/installed-packages")
async def get_installed_packages_endpoint(
    request: Request,
    vm_service: VMManagementService = Depends(ServiceProvider.get_vm_management_service)
):
    """
    API endpoint to get all installed packages with their versions from the specified environment.
    
    Parameters:
    - request: The FastAPI Request object
    - environment_path: Optional path to virtual environment. If not provided, uses VM_VENV_DIR from .env
    
    Returns:
    - Dict containing success status, message, and list of packages with their versions
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    try:
        log.info("Getting installed packages from environment")
        result = await vm_service.get_installed_packages()
        
        if result["success"]:
            packages = result["packages"]
            log.info(f"Successfully retrieved {len(packages)} installed packages")
            return {
                "success": True,
                "message": result["message"],
                "count": len(packages),
                "packages": packages
            }
        else:
            log.warning(f"Failed to get packages: {result['message']}")
            return {
                "success": False,
                "message": result["message"],
                "count": 0,
                "packages": []
            }
            
    except Exception as e:
        log.error(f"Error getting installed packages: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to get installed packages: {str(e)}"
        )

## ==========================================================