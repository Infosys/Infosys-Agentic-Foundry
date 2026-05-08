# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Independent File Server Module

This module provides a standalone file server for browsing and downloading 
files from user_uploads directory without authentication.
"""

from src.file_server.file_server import create_file_server_app, start_file_server_thread

__all__ = ["create_file_server_app", "start_file_server_thread"]
