# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import uuid
import uuid
from typing import Dict,IO, List
from pathlib import Path
from fastapi import UploadFile, HTTPException
from fastapi.responses import FileResponse,StreamingResponse


from telemetry_wrapper import logger as log
from src.storage import get_storage_client

from src.storage import get_storage_client

class FileManager:
    BASE_DIR = "user_uploads"

    def __init__(self, base_dir: str = None):
        self.base_dir = base_dir or self.BASE_DIR


    @staticmethod
    async def _ensure_directory_exists(path: str):
        if not os.path.exists(path):
            os.makedirs(path)

    async def _validate_path(self, subdirectory: str) -> str:
        # Sanitize subdirectory path
        subdirectory = subdirectory.strip().lstrip("/\\") # Remove leading slashes

        if ".." in subdirectory or ":" in subdirectory:
            raise HTTPException(status_code=400, detail="Invalid Path File")

        save_path = os.path.join(self.base_dir, subdirectory) if subdirectory else self.base_dir

        # Before creating the directory, check if the save_path is valid and within the allowed directory
        abs_save_path = os.path.abspath(save_path)

        # Ensure that the absolute save path is inside the BASE_DIR and prevent directory traversal
        if not abs_save_path.startswith(os.path.abspath(self.base_dir)):
            raise HTTPException(status_code=400, detail="Invalid Path File")

        await self._ensure_directory_exists(abs_save_path)
        return abs_save_path
    
    async def upload_kb_files_to_storage(self, file: UploadFile, storage_provider: str, blob_name: str = None):
        """
        Uploads a file to the specified cloud storage provider.

        - **storage_provider**: The cloud to upload to ('aws', 'azure', or 'gcp').
        - **file**: The file to upload.
        - **blob_name**: Optional. The full path including filename for the blob in the storage.
                         If not provided, a unique name will be generated.
        """
        try:
            # 1. Get the correct storage client using our factory
            storage_client = get_storage_client(storage_provider)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            # Catches errors if environment variables for a provider are not set
            raise HTTPException(status_code=500, detail=f"Configuration error for {storage_provider}: {e}")

        # 2. Determine the object key (blob name)
        if blob_name:
            object_key = blob_name
        else:
            # Generate a unique object key if not provided
            file_extension = Path(file.filename).suffix
            object_key = f"uploads/{uuid.uuid4()}{file_extension}"

        try:
            # 3. Use the client to upload the file stream directly
            # The file.file is the file-like object
            upload_identifier = storage_client.upload_file(file.file, object_key)

            return {
                "message": "File uploaded successfully!",
                "provider": storage_provider,
                "filename": file.filename,
                "object_key": object_key,
                "location": upload_identifier,
            }
        except Exception as e:
            # This catches errors during the actual upload process
            log.error(f"Failed to upload file to {storage_provider}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to upload file: {e}")


    


    async def upload_file_to_storage(self,file: UploadFile, storage_provider:str):
        """
        Uploads a file to the specified cloud storage provider.

        - **storage_provider**: The cloud to upload to ('aws', 'azure', or 'gcp').
        - **file**: The file to upload.
        """
        try:
        # 1. Get the correct storage client using our factory
            storage_client = get_storage_client(storage_provider)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
        # Catches errors if environment variables for a provider are not set
            raise HTTPException(status_code=500, detail=f"Configuration error for {storage_provider}: {e}")

    # 2. Generate a unique object key to prevent filename collisions
        file_extension = file.filename.split('.')[-1]
        unique_key = f"uploads/{uuid.uuid4()}.{file_extension}"

        try:
        # 3. Use the client to upload the file stream directly
        # The file.file is the file-like object
            upload_identifier = storage_client.upload_file(file.file, file.filename)
        
        # --- BEST PRACTICE ---
        # Here, you would save the metadata to your PostgreSQL database:
        # db.save_file_metadata(
        #   original_filename=file.filename,
        #   object_key=unique_key,
        #   provider=storage_provider.value,
        #   upload_identifier=upload_identifier
        # )
        
            return {
            "message": "File uploaded successfully!",
            "provider": storage_provider,
            "filename": file.filename,
            "object_key": unique_key,
            "location": upload_identifier,
            }
        except Exception as e:
        # This catches errors during the actual upload process
            raise HTTPException(status_code=500, detail=f"Failed to upload file: {e}")    


    async def download_file_from_storage(self,filename:str,storage_provider:str):
        """
        Downloads a file from the specified cloud storage provider.

        - **storage_provider**: The cloud to download from ('aws', 'azure', or 'gcp').
        - **filename**: The name of the file to download.
        """
        try:
        # 1. Get the correct storage client using our factory
            log.info('creating storage client...')
            storage_client = get_storage_client(storage_provider)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
        # Catches errors if environment variables for a provider are not set
            raise HTTPException(status_code=500, detail=f"Configuration error for {storage_provider}: {e}")

        try:
        # 2. Use the client to download the file stream directly
            file_stream = storage_client.download_file(filename)
            def universal_chunk_reader(stream: IO, chunk_size: int = 8192):
                """
                Reads a file-like stream in chunks of a specified size.
                """
                while True:
                    chunk = stream.read(chunk_size)
                    if not chunk:
                        # When .read() returns an empty byte string, the file is fully read.
                        break
                    yield chunk

            return StreamingResponse(universal_chunk_reader(file_stream), media_type='application/octet-stream', headers={"Content-Disposition": f"attachment; filename={filename}"})
           # return FileResponse(file_stream, media_type='application/octet-stream', filename=filename)
        except Exception as e:
        # This catches errors during the actual download process
            raise HTTPException(status_code=500, detail=f"Failed to download file: {e}")




    async def upload_file_to_storage(self,file: UploadFile, storage_provider:str):
        """
        Uploads a file to the specified cloud storage provider.

        - **storage_provider**: The cloud to upload to ('aws', 'azure', or 'gcp').
        - **file**: The file to upload.
        """
        try:
        # 1. Get the correct storage client using our factory
            storage_client = get_storage_client(storage_provider)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
        # Catches errors if environment variables for a provider are not set
            raise HTTPException(status_code=500, detail=f"Configuration error for {storage_provider}: {e}")

    # 2. Generate a unique object key to prevent filename collisions
        file_extension = file.filename.split('.')[-1]
        unique_key = f"uploads/{uuid.uuid4()}.{file_extension}"

        try:
        # 3. Use the client to upload the file stream directly
        # The file.file is the file-like object
            upload_identifier = storage_client.upload_file(file.file, file.filename)
        
        # --- BEST PRACTICE ---
        # Here, you would save the metadata to your PostgreSQL database:
        # db.save_file_metadata(
        #   original_filename=file.filename,
        #   object_key=unique_key,
        #   provider=storage_provider.value,
        #   upload_identifier=upload_identifier
        # )
        
            return {
            "message": "File uploaded successfully!",
            "provider": storage_provider,
            "filename": file.filename,
            "object_key": unique_key,
            "location": upload_identifier,
            }
        except Exception as e:
        # This catches errors during the actual upload process
            raise HTTPException(status_code=500, detail=f"Failed to upload file: {e}")    


    async def download_file_from_storage(self,filename:str,storage_provider:str):
        """
        Downloads a file from the specified cloud storage provider.

        - **storage_provider**: The cloud to download from ('aws', 'azure', or 'gcp').
        - **filename**: The name of the file to download.
        """
        try:
        # 1. Get the correct storage client using our factory
            log.info('creating storage client...')
            storage_client = get_storage_client(storage_provider)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
        # Catches errors if environment variables for a provider are not set
            raise HTTPException(status_code=500, detail=f"Configuration error for {storage_provider}: {e}")

        try:
        # 2. Use the client to download the file stream directly
            file_stream = storage_client.download_file(filename)
            def universal_chunk_reader(stream: IO, chunk_size: int = 8192):
                """
                Reads a file-like stream in chunks of a specified size.
                """
                while True:
                    chunk = stream.read(chunk_size)
                    if not chunk:
                        # When .read() returns an empty byte string, the file is fully read.
                        break
                    yield chunk

            return StreamingResponse(universal_chunk_reader(file_stream), media_type='application/octet-stream', headers={"Content-Disposition": f"attachment; filename={filename}"})
           # return FileResponse(file_stream, media_type='application/octet-stream', filename=filename)
        except Exception as e:
        # This catches errors during the actual download process
            raise HTTPException(status_code=500, detail=f"Failed to download file: {e}")


            
    async def save_uploaded_file(self, uploaded_file: UploadFile, subdirectory: str = "") -> str:
        save_path = await self._validate_path(subdirectory)

        if uploaded_file.filename in os.listdir(save_path):
            raise HTTPException(status_code=400, detail="File already exists!")

        file_location = os.path.join(save_path, uploaded_file.filename)

        file_content_bytes: bytes = await uploaded_file.read()
        file_path_obj = Path(file_location)
        file_path_obj.write_bytes(file_content_bytes)

        log.info(f"Saved uploaded file to: {file_location}")
        return file_location

    async def generate_file_structure(self, department_filter: str = None, include_universal: bool = False) -> Dict:
        file_struct = {}
        
        # If department filter is provided, start from department subdirectory
        if department_filter:
            walk_path = os.path.join(self.base_dir, department_filter)
            # Check if department directory exists
            if os.path.exists(walk_path):
                for root, dirs, files in os.walk(walk_path):
                    path_parts = root.split(os.sep)
                    current_level = file_struct
                    for part in path_parts:
                        if part not in current_level:
                            current_level[part] = {}
                        current_level = current_level[part]
                    if files:
                        current_level["__files__"] = files
            else:
                log.info(f"Department directory '{department_filter}' not found")
            
            # Include universal files (files directly in user_uploads root, outside any department folder)
            if include_universal and os.path.exists(self.base_dir):
                root_files = [f for f in os.listdir(self.base_dir)
                              if os.path.isfile(os.path.join(self.base_dir, f))]
                if root_files:
                    # Navigate to the base_dir level in file_struct and add root files
                    base_parts = self.base_dir.split(os.sep)
                    current_level = file_struct
                    for part in base_parts:
                        if part not in current_level:
                            current_level[part] = {}
                        current_level = current_level[part]
                    if "__files__" in current_level:
                        current_level["__files__"].extend(root_files)
                    else:
                        current_level["__files__"] = root_files
            
            log.info(f"File structure generated successfully for department '{department_filter}' (include_universal={include_universal})")
        else:
            walk_path = self.base_dir
            for root, dirs, files in os.walk(walk_path):
                path_parts = root.split(os.sep)
                current_level = file_struct
                for part in path_parts:
                    if part not in current_level:
                        current_level[part] = {}
                    current_level = current_level[part]
                if files:
                    current_level["__files__"] = files
            log.info("File structure generated successfully")
        
        return file_struct

    async def get_file(self, filename: str, subdirectory: str = ""):
        # Sanitize inputs
        if filename:
            filename = filename.strip().lstrip("/\\")
        if subdirectory:
            subdirectory = subdirectory.strip().lstrip("/\\")
        
        # Security validation
        if ".." in (subdirectory or "") or ".." in (filename or ""):
            raise HTTPException(status_code=400, detail="Invalid file path")
        if ":" in (subdirectory or "") or ":" in (filename or ""):
            raise HTTPException(status_code=400, detail="Invalid file path")
        
        base_path = Path(self.base_dir)

        # Compose the path safely
        if subdirectory:
            file_path = base_path / subdirectory / filename
        else:
            file_path = base_path / filename

        # Ensure the resolved path is within base directory
        abs_file_path = file_path.resolve()
        abs_base_path = base_path.resolve()
        
        if not str(abs_file_path).startswith(str(abs_base_path)):
            raise HTTPException(status_code=400, detail="Invalid file path - outside allowed directory")

        log.info(f"Download request for file: {file_path}")

        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path, media_type='application/octet-stream', filename=filename)
        else:
            raise HTTPException(status_code=404, detail=f"File not found: {filename}")


    async def delete_file(self, file_path: str) -> str:
        # Sanitize subdirectory path
        file_path = file_path.strip().lstrip("/\\") # Remove leading slashes
        
        # Validate path for security
        if ".." in file_path or ":" in file_path:
            raise HTTPException(status_code=400, detail="Invalid file path")
        
        full_path = os.path.join(self.base_dir, file_path)
        
        # Ensure that the absolute path is inside the BASE_DIR to prevent directory traversal
        abs_full_path = os.path.abspath(full_path)
        if not abs_full_path.startswith(os.path.abspath(self.base_dir)):
            raise HTTPException(status_code=400, detail="Invalid file path - outside allowed directory")
        
        if os.path.exists(abs_full_path):
            if os.path.isfile(abs_full_path):
                os.remove(abs_full_path)
                log.info(f"File '{file_path}' deleted successfully.")
                return {"info": f"File '{file_path}' deleted successfully."}
            else:
                log.info(f"Attempted to delete a directory: '{file_path}'")
                raise HTTPException(status_code=400, detail="The specified path is a directory. Only files can be deleted.")
        else:
            log.info(f"File '{file_path}' not found.")
            raise HTTPException(status_code=404, detail="No such file or directory.")

    async def save_chat_file(self, uploaded_file: UploadFile, session_id: str, subdirectory: str = "") -> str:
        """
        Save uploaded file for chat with unique naming: <filename>_<session_id>.<ext>
        Files are stored in department-specific subdirectory under user_uploads/
        """
        save_path = await self._validate_path(subdirectory)
        name, ext = os.path.splitext(uploaded_file.filename)
        stored_filename = f"{name}_{session_id}{ext}"
        file_location = os.path.join(save_path, stored_filename)
        
        file_content_bytes: bytes = await uploaded_file.read()
        file_path_obj = Path(file_location)
        file_path_obj.write_bytes(file_content_bytes)
        
        log.info(f"Saved chat file: {file_location}")
        # Return path including subdirectory so delete endpoint receives a department-scoped path
        if subdirectory:
            return f"{subdirectory}/{stored_filename}"
        return stored_filename

    async def list_chat_files(self, session_id: str = None, subdirectory: str = "") -> List[str]:
        """List files in user_uploads department subdirectory, optionally filtered by session."""
        if subdirectory:
            list_path = os.path.join(self.base_dir, subdirectory)
        else:
            list_path = self.base_dir
        
        if not os.path.exists(list_path):
            return []
        
        files = []
        for filename in os.listdir(list_path):
            if os.path.isfile(os.path.join(list_path, filename)):
                if session_id is None or f"_{session_id}." in filename:
                    files.append(filename)
        return files

    async def delete_file_from_storage(self,file_name:str,storage_provider: str):
        try:
            storage_client = get_storage_client(storage_provider)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Configuration error for {storage_provider}: {e}")
        
        try:
            log.info(f"Attempting to delete file '{file_name}' from {storage_provider} storage.")
            success_storage=storage_client.delete_file(file_name)
            if success_storage:
                log.info(f"File '{file_name}' deleted successfully from {storage_provider} storage.")
                return {"info": f"File '{file_name}' deleted successfully from {storage_provider} storage."}
            else:
                log.error(f"Failed to delete file '{file_name}' from {storage_provider} storage.")
                return {"info": f"File '{file_name}' deletion failed from {storage_provider} storage."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete file: {e}")



    async def cloud_file_search(self, filename: str, storage_provider: str) -> bool:
        """
        Searches for a file in the specified cloud storage provider.

        - **filename**: The name of the file to search for.
        - **storage_provider**: The cloud to search in ('aws', 'azure', or 'gcp').
        
        Returns:
            bool: True if file exists, False otherwise.
        """
        try:
            storage_client = get_storage_client(storage_provider)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Configuration error for {storage_provider}: {e}")

        try:
            exists = storage_client.file_exists(filename)
            log.info(f"File '{filename}' {'found' if exists else 'not found'} in {storage_provider} storage.")
            return exists
        except Exception as e:
            log.error(f"Failed to search for file in {storage_provider}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to search for file: {e}")
