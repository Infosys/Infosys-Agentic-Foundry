from abc import ABC, abstractmethod
from typing import IO,ContextManager
from contextlib import AbstractContextManager

class StorageInterface(ABC):
    """
    Abstract Base Class (Interface) for a storage provider.
    This defines the contract that all storage implementations must follow.
    """
    @abstractmethod
    def upload_file(self, file_obj: IO, object_key: str) -> str:
        """
        Uploads a file-like object to the storage provider.
        
        Args:
            file_obj: The file-like object (stream) to upload.
            object_key: The unique key (path/filename) for the object in storage.
            
        Returns:
            The public URL or a unique identifier for the uploaded file.
        """
        pass

    @abstractmethod
    def download_file(self, object_key: str) -> IO:
        """Downloads a file as a stream."""
        pass
    
    @abstractmethod
    def delete_file(self, object_key: str) -> bool:
        """Deletes a file."""
        pass

    @abstractmethod
    def file_exists(self, object_key: str) -> bool:
        """Checks if a file exists."""
        pass

    # @abstractmethod
    # def open(self, file_name: str, mode: str = 'rb') -> AbstractContextManager[IO]:
    #     """
    #     Opens a remote object in a manner similar to Python's built-in open().
    #     This method should be usable as a context manager (in a 'with' statement).
        
    #     Args:
    #         file_name (str): The name/path of the object in storage.
    #         mode (str): The mode to open the file in ('rb' for read-binary, 
    #                     'wb' for write-binary).
                        
    #     Returns:
    #         A context manager yielding a file-like object.
    #     """
    #     pass