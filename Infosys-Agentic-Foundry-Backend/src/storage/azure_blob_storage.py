import os
from typing import IO
from fastapi import File
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient
from src.utils.secrets_handler import get_user_secrets
from telemetry_wrapper import logger as log
from .base import StorageInterface  

load_dotenv()

class AzureBlobStorage(StorageInterface):
    def __init__(self):
        try:
            log.info('Fetching Azure connection string from vault...')
            self.connection_string = get_user_secrets("AZURE_CONNECTION_STRING")
            if not self.connection_string:
                raise ValueError("AZURE_CONNECTION_STRING secret is missing or empty.")
            log.info('Successfully fetched connection string.')

            log.info('Fetching Azure container name from vault...')
            self.container_name = get_user_secrets("AZURE_BLOB_CONTAINER_NAME")
            if not self.container_name:
                # Fallback to environment variable if secret_data is not found
                log.info('AZURE_BLOB_CONTAINER_NAME is not present in vault..checking in .env')
                self.container_name = os.getenv("AZURE_BLOB_CONTAINER_NAME")
            if not self.container_name:
                log.info('AZURE_BLOB_CONTAINER_NAME is not present anywhere')
                raise ValueError("AZURE_BLOB_CONTAINER_NAME secret or environment variable is missing or empty.")
            
            log.info(f'Successfully fetched container name: {self.container_name}')

            self.blob_service_client = BlobServiceClient.from_connection_string(self.connection_string)
            log.info("Azure BlobServiceClient initialized successfully.")

            self.container_client = self.blob_service_client.get_container_client(self.container_name)
            log.info("Azure BlobServiceClient initialized successfully.")


        except ValueError as ve:
            log.error(f"Configuration Error for AzureBlobStorage: {ve}")
            raise  # Re-raise the ValueError to prevent silent failure
        except Exception as e:
            log.error(f"Failed to initialize Azure BlobServiceClient: {e}", exc_info=True)
            # Wrap the original exception in a new one to provide context
            raise RuntimeError(f"Could not initialize AzureBlobStorage due to an unexpected error: {e}")

    def upload_file(self, file_obj: IO, file_name: str) -> str:
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=file_name
            )
            blob_client.upload_blob(file_obj, overwrite=True)
            return blob_client.url
        except Exception as e:
            log.error(f"Error uploading to Azure Blob: {e}")
            raise

    def download_file(self, object_key: str) -> IO:
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=object_key
            )
            return blob_client.download_blob()
        except Exception as e:
            log.error(f"Error downloading from Azure Blob: {e}")
            raise

    def delete_file(self, object_key: str) -> bool:
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=object_key
            )
            blob_client.delete_blob()
            return True
        except Exception as e:
            log.error(f"Error deleting from Azure Blob: {e}")
            return False
        
    def file_exists(self, blob_name: str) -> bool:
        """
        Check if a file (blob) exists in the Azure Blob container.

        Args:
            blob_name: The name of the blob to check.

        Returns:
            bool: True if the blob exists, False otherwise.
        """
        try:
            blob_client = self.container_client.get_blob_client(blob_name)
            exists=blob_client.exists()
            log.debug(f"File exists check for '{blob_name}': {exists}")
            return exists
        except Exception as e:
            # Log the error if needed, but return False for non-existent files
            log.error(f"Error checking if file exists '{blob_name}': {e}")
            return False   
        
    def list_files(self, prefix: str) -> list[str]:
        """
        Lists all files in the container with a given prefix.

        Args:
            prefix (str): The prefix (folder path) to filter by.

        Returns:
            list[str]: A list of blob names (file keys).
        """
        try:
            container_client = self.blob_service_client.get_container_client(self.container_name)
            blob_list = container_client.list_blobs(name_starts_with=prefix)
            return [blob.name for blob in blob_list]
        except Exception as e:
            log.error(f"Error listing files with prefix '{prefix}' from Azure Blob: {e}", exc_info=True)  
            return []