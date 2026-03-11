import os
import boto3
from typing import IO,ContextManager,Iterator
from contextlib import contextmanager
import io

from fastapi import File
from .base import StorageInterface
from dotenv import load_dotenv
from telemetry_wrapper import logger as log
from src.utils.secrets_handler import get_user_secrets

load_dotenv()


class S3Storage(StorageInterface):
    def __init__(self):
        self.bucket_name = get_user_secrets("AWS_S3_BUCKET_NAME")
        if not self.bucket_name:
            self.bucket_name=os.getenv("AWS_S3_BUCKET_NAME")
            log.info(f'aws bucket:{self.bucket_name}')
        if not self.bucket_name:
            raise ValueError("AWS_S3_BUCKET_NAME environment variable not set.")
        self.s3_client = boto3.client("s3")

    def upload_file(self, file_obj: IO, object_key: str) -> str:
        try:
            self.s3_client.upload_fileobj(file_obj, self.bucket_name, object_key)
            # For S3, a common identifier is the object key itself within the bucket.
            return f"s3://{self.bucket_name}/{object_key}"
        except Exception as e:
            log.error(f"Error uploading to S3: {e}")
            raise

    def download_file(self, object_key: str) -> IO:
        try:
            file_obj = self.s3_client.get_object(Bucket=self.bucket_name, Key=object_key)
            return file_obj['Body']
        except Exception as e:
            log.error(f"Error downloading from S3: {e}")
            raise

    def delete_file(self, object_key: str) -> bool:
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=object_key)
            return True
        except Exception as e:
            log.error(f"Error deleting from S3: {e}")
            return False


    def file_exists(self, object_key: str) -> bool:
        """
        Check if a file (object) exists in the S3 bucket.

        Args:
            object_key: The key of the object to check.

        Returns:
            bool: True if the object exists, False otherwise.
        """
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=object_key)
            return True
        except self.s3_client.exceptions.ClientError as e:
            # If the error code is 404, the file doesn't exist
            if e.response['Error']['Code'] == '404':
                return False
            # Re-raise for other errors
            raise
        except Exception as e:
            log.error(f"Error checking if file exists in S3: {e}")
            return False


    @contextmanager
    def open(self, object_key: str, mode: str = 'rb') -> Iterator[IO]:
        """Opens a file on S3 for reading or writing."""
        if mode == 'rb':
            # --- READING ---
            try:
                s3_object = self.s3_client.get_object(Bucket=self.bucket_name, Key=object_key)
                # The 'Body' is a file-like stream. Yield it and ensure it's closed.
                stream = s3_object['Body']
                yield stream
            finally:
                stream.close() # Ensure the connection is closed
        elif mode == 'wb':
            # --- WRITING ---
            # For writing, we'll stream to an in-memory buffer first.
            buffer = io.BytesIO()
            yield buffer
            # After the 'with' block is finished, the buffer is full. Now we upload it.
            buffer.seek(0) # Rewind the buffer to the beginning
            self.s3_client.put_object(Bucket=self.bucket_name, Key=object_key, Body=buffer)
        else:
            raise ValueError(f"Unsupported mode: '{mode}'. Use 'rb' or 'wb'.")    