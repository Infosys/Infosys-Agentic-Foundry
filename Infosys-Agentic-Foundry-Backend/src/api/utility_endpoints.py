# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import json
import shutil
import asyncpg
import requests
from typing import List, Dict
from pathlib import Path
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse

import azure.cognitiveservices.speech as speechsdk
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import TextLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain_pymupdf4llm import PyMuPDF4LLMLoader

from src.database.services import ModelService
from src.utils.file_manager import FileManager
from src.api.dependencies import ServiceProvider # The dependency provider
from telemetry_wrapper import logger as log, update_session_context


router = APIRouter(prefix="/utility", tags=["Utility - (Upload / Download Files | Knowledge Base | Speech-To-Text | Markdown Documentation)"])


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
        return JSONResponse(content={"models": data, "temperature": temperature})

    except asyncpg.PostgresError as e:
        log.error(f"Database error while fetching models: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    except Exception as e:
        # Handle other unforeseen errors
        log.error(f"Unexpected error while fetching models: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


## ============ User Uploaded Files Endpoints ============

@router.post("/files/user-uploads/upload/")
async def upload_file_endpoint(request: Request, file: UploadFile = File(...), subdirectory: str = "", file_manager: FileManager = Depends(ServiceProvider.get_file_manager)):
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    file_location = await file_manager.save_uploaded_file(uploaded_file=file, subdirectory=subdirectory)

    log.info(f"File '{file.filename}' uploaded successfully to '{file_location}'")
    return {"info": f"File '{file.filename}' saved at '{file_location}'"}

@router.get("/files/user-uploads/get-file-structure/")
async def get_file_structure_endpoint(request: Request, file_manager: FileManager = Depends(ServiceProvider.get_file_manager)):
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    file_structure = await file_manager.generate_file_structure()
    log.info("File structure retrieved successfully")
    return JSONResponse(content=file_structure)

@router.get('/files/user-uploads/download')
async def download_file_endpoint(request: Request, filename: str = Query(...), sub_dir_name: str = Query(None), file_manager: FileManager = Depends(ServiceProvider.get_file_manager)):
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    return await file_manager.get_file(filename=filename, subdirectory=sub_dir_name)

@router.delete("/files/user-uploads/delete/")
async def delete_file_endpoint(request: Request, file_path: str, file_manager: FileManager = Depends(ServiceProvider.get_file_manager)):
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    return await file_manager.delete_file(file_path=file_path)

## ==========================================================


## ============ Knowledge Base Endpoints ============

KB_DIR = "KB_DIR"
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", None)
GOOGLE_EMBEDDING_MODEL = os.environ.get("GOOGLE_EMBEDDING_MODEL", "models/text-embedding-004")
 

@router.post("/knowledge-base/documents/upload")
async def upload_knowledge_base_documents_endpoint(
        request: Request,
        session_id: str = Form(...),
        kb_name: str = 'temp',
        files: List[UploadFile] = File(...)
    ):
    """
    API endpoint to upload documents for a knowledge base, create embeddings, and store them.

    Parameters:
    - request: The FastAPI Request object.
    - session_id: A session ID for temporary file storage during upload.
    - kb_name: The name of the knowledge base to create/update.
    - files: List of uploaded document files.

    Returns:
    - Dict[str, str]: Status message and storage path.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    

    if not GOOGLE_API_KEY:
        raise HTTPException(status_code=500, detail="GOOGLE_API_KEY environment variable is not set for embeddings.")

    embeddings = GoogleGenerativeAIEmbeddings(
        model=GOOGLE_EMBEDDING_MODEL,
        google_api_key=GOOGLE_API_KEY
    )

    # Create temp directory
    TEMPFILE_DIR = "TEMPFILE_DIR"
    temp_dir = os.path.join(TEMPFILE_DIR, f"session_{session_id}")
    os.makedirs(temp_dir, exist_ok=True)

    file_paths = []
    for file in files:
        file_path = os.path.join(temp_dir, file.filename)
        try:
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            file_paths.append(file_path)
        except Exception as e:
            log.error(f"Error saving uploaded file {file.filename}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to save file {file.filename}: {e}")

    # Load text files and split into documents
    documents = []
    for path in file_paths:
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".txt":
                loader = TextLoader(path, encoding='utf-8')
            elif ext == ".pdf":
                loader = PyMuPDF4LLMLoader(path)
            else:
                log.warning(f"Unsupported file type for KB upload: {ext} for file {os.path.basename(path)}. Skipping.")
                continue
            documents.extend(loader.load())
        except Exception as e:
            log.error(f"Failed to load document {os.path.basename(path)}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to load document {os.path.basename(path)}: {e}")

    # Split documents
    text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=300)
    docs = text_splitter.split_documents(documents)

    faiss_path = os.path.join(KB_DIR, kb_name)
    
    try:
        # Create vector store
        vectorstore = FAISS.from_documents(docs, embeddings)
        # Save vector store to session-specific FAISS index folder
        vectorstore.save_local(faiss_path)
        log.info(f"Embeddings created and stored for KB '{kb_name}' at '{faiss_path}'.")
    except Exception as e:
        log.error(f"Error creating/saving vector store for KB '{kb_name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create/save knowledge base: {e}")

    return {
        "message": f"Uploaded {len(files)} files. Embeddings created and stored for knowledge base '{kb_name}'.",
        "storage_path": faiss_path
    }

@router.get("/knowledge-base/list")
async def list_knowledge_base_directories_endpoint(request: Request):
    """
    API endpoint to list available knowledge base directories (vectorstores).

    Parameters:
    - request: The FastAPI Request object.

    Returns:
    - Dict[str, Any]: A dictionary containing a list of knowledge base names.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    kb_path = Path(KB_DIR)

    if not kb_path.exists():
        return {"message": "No knowledge bases found."}

    directories = [d.name for d in kb_path.iterdir() if d.is_dir()]

    if not directories:
        return {"message": "No knowledge bases found."}

    return {"knowledge_bases": directories}

class DeleteFoldersRequest(BaseModel):
    knowledgebase_names: list[str]

@router.delete("/remove-knowledgebases")
async def delete_folders(request: DeleteFoldersRequest):
    deleted_folders = []
    failed_folders = []

    for knowledgebase_name in request.knowledgebase_names:
        folder_path = Path(KB_DIR) / knowledgebase_name

        if not folder_path.exists():
            failed_folders.append({"KnowledgeBase": knowledgebase_name, "error": "KnowledgeBase not found"})
            continue

        if not folder_path.is_dir():
            failed_folders.append({"KnowledgeBase": knowledgebase_name, "error": "Not a KnowledgeBase"})
            continue

        try:
            shutil.rmtree(folder_path)
            deleted_folders.append(knowledgebase_name)
        except Exception as e:
            failed_folders.append({"folder": knowledgebase_name, "error": str(e)})

    return {
        "deleted_kbs": deleted_folders,
        "failed_kbs": failed_folders
    }
 
## ==========================================================


## ============ speech-to-text ============

@router.post("/transcribe/")
async def transcribe_audio_endpoint(file: UploadFile = File(...)) -> Dict[str, str]:
    STT_ENDPOINT = os.getenv("STT_ENDPOINT")
    SPEECH_KEY = os.getenv("SPEECH_KEY")
    os.environ['HTTP_PROXY'] = ''
    os.environ['HTTPS_PROXY'] = 'http://blrproxy.ad.infosys.com:443'

    os.makedirs('audios', exist_ok=True)
    file_location = os.path.join("audios", file.filename)
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    url = f"{STT_ENDPOINT}speechtotext/transcriptions:transcribe?api-version=2024-05-15-preview"
    headers = {
        "Ocp-Apim-Subscription-Key": SPEECH_KEY,
        "Accept": "application/json"
    }
    definition = {
        "locales": ["en-US"],
        "profanityFilterMode": "Masked",
        "channels": [0]
    }

    proxies = {
        'http': 'http://blrproxy.ad.infosys.com:443',
        'https': 'http://blrproxy.ad.infosys.com:443'
    }

    try:
        with open(file_location, 'rb') as audio_file:
            files = {
                'audio': (file.filename, audio_file, 'audio/wav'),
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


