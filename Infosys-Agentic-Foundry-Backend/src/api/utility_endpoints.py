# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import shutil
import asyncpg
import speech_recognition as sr
from typing import List
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse

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
async def get_available_models_endpoint(request: Request, model_service: ModelService = Depends(ServiceProvider.get_model_service)):
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    try:
        data = await model_service.get_all_available_model_names()
        log.debug(f"Models retrieved successfully: {data}")
        return JSONResponse(content={"models": data})

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

## ==========================================================


## ============ speech-to-text ============

@router.post("/transcribe/")
async def transcribe_audio_endpoint(request: Request, file: UploadFile = File(...)):
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    # Define the path to save the uploaded file
    os.makedirs('audios', exist_ok=True)
    file_location = os.path.join("audios", file.filename)

    # Save the file to the 'audios' directory
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Initialize recognizer and perform transcription
    recognizer = sr.Recognizer()
    try:
        with sr.AudioFile(file_location) as source:
            audio_data = recognizer.record(source)
        transcription = recognizer.recognize_google(audio_data)
    except sr.UnknownValueError:
        transcription = "Sorry, could not understand the audio."
    except sr.RequestError as e:
        transcription = f"Google API error: {e}"
    finally:
        # Optionally delete the file after transcription
        os.remove(file_location)

    return {"transcription": transcription}

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


