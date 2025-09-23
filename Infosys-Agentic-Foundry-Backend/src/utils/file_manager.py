# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import shutil
from typing import Dict
from pathlib import Path
from fastapi import UploadFile, HTTPException
from fastapi.responses import FileResponse

from telemetry_wrapper import logger as log


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

    async def save_uploaded_file(self, uploaded_file: UploadFile, subdirectory: str = "") -> str:
        save_path = await self._validate_path(subdirectory)

        if uploaded_file.filename in os.listdir(save_path):
            raise HTTPException(status_code=400, detail="File already exists!")

        file_location = os.path.join(save_path, uploaded_file.filename)

        with open(file_location, "wb") as f:
            shutil.copyfileobj(uploaded_file.file, f)

        log.info(f"Saved uploaded file to: {file_location}")
        return file_location

    async def generate_file_structure(self) -> Dict:
        file_struct = {}
        for root, dirs, files in os.walk(self.base_dir):
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
        base_path = Path(self.base_dir)

        # Compose the path safely
        if subdirectory:
            file_path = base_path / subdirectory / filename
        else:
            file_path = base_path / filename

        log.info(f"Download request for file: {file_path}")

        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path, media_type='application/octet-stream', filename=filename)
        else:
            return {"error": f"File not found: {file_path}"}

    async def delete_file(self, file_path: str) -> str:
        # Sanitize subdirectory path
        file_path = file_path.strip().lstrip("/\\") # Remove leading slashes
        full_path = os.path.join(self.base_dir, file_path)
        if os.path.exists(full_path):
            if os.path.isfile(full_path):
                os.remove(full_path)
                log.info(f"File '{file_path}' deleted successfully.")
                return {"info": f"File '{file_path}' deleted successfully."}
            else:
                log.info(f"Attempted to delete a directory: '{file_path}'")
                raise HTTPException(status_code=400, detail="The specified path is a directory. Only files can be deleted.")
        else:
            log.info(f"File '{file_path}' not found.")
            raise HTTPException(status_code=404, detail="No such file or directory.")


