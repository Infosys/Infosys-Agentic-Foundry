import os
from typing import IO
from google.cloud import storage
from .base import StorageInterface
from telemetry_wrapper import logger as log

class GCSStorage(StorageInterface):
    def __init__(self):
        # GOOGLE_APPLICATION_CREDENTIALS env var should point to your service account JSON file
        self.bucket_name = os.environ.get("GCP_STORAGE_BUCKET_NAME")
        if not self.bucket_name:
            raise ValueError("GCP_STORAGE_BUCKET_NAME environment variable not set.")
        
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(self.bucket_name)

    def upload_file(self, file_obj: IO, object_key: str) -> str:
        try:
            blob = self.bucket.blob(object_key)
            blob.upload_from_file(file_obj)
            return blob.public_url
        except Exception as e:
            log.error(f"Error uploading to GCS: {e}")
            raise

    # ... implement download_file and delete_file ...