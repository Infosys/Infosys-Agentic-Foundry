
from .aws_s3_storage import S3Storage
from .azure_blob_storage import AzureBlobStorage
from .google_cloud_storage import GCSStorage
from .base import StorageInterface
from enum import Enum
from telemetry_wrapper import logger as log


# A mapping from the string name to the class
PROVIDER_MAP = {
    "aws": S3Storage,
    "azure": AzureBlobStorage,
    "gcp": GCSStorage,
}

class StorageProvider(str, Enum):
    aws = "aws"
    azure = "azure"
    gcp = "gcp"

def get_storage_client(provider_name: str) -> StorageInterface:
    """
    Factory function to get an instance of a storage provider.
    """
    provider_class = PROVIDER_MAP.get(provider_name.lower())
    log.info('entered in get_storage_client_function')
    if not provider_class:
        raise ValueError(f"Unsupported storage provider: {provider_name}. Supported providers are: {list(PROVIDER_MAP.keys())}")
    
    # This creates an instance of the chosen class (e.g., S3Storage())
    log.info('get_storage_client working fine...')
    try:
        print(provider_class)
        log.info(f'{provider_class}')
        obj = provider_class()

        log.info(f"Initialized storage provider {provider_name}: {obj}")
        return obj
    except Exception as e:
        log.error(f"Error initializing storage provider {provider_name}: {e}")
        return None
    