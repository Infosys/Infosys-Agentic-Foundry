"""
Agent Tool: Fetch Code Version

This module provides tool functions for agents to fetch code versions
from the tool generation system.

Two approaches available:
1. fetch_code_version - Direct service call (no HTTP, requires app_container)
2. fetch_code_version_api - HTTP API call (uses localhost, standalone)

Usage:
    # Direct service call (recommended when running inside IAF)
    from tool_chatbot.tools import fetch_code_version
    result = fetch_code_version("session_id", 1)
    
    # HTTP API call (standalone, requires auth token)
    from tool_chatbot.tools import fetch_code_version_api
    result = fetch_code_version_api("session_id", 1, auth_token="your_token")
"""

from typing import Dict, Any, Optional
import logging
import asyncio
import requests

log = logging.getLogger(__name__)


# ============================================================================
# HTTP API FUNCTION (uses localhost)
# ============================================================================

def fetch_code_version_api(
    session_id: str, 
    version_number: int,
    auth_token: str,
    base_url: str = "http://localhost:8000",
    timeout: int = 30
) -> Dict[str, Any]:
    """
    Fetches a specific code version by calling the API endpoint via HTTP.
    
    This function makes an HTTP GET request to the tool generation API endpoint.
    Use this when you need to call the API from outside the IAF application context.
    
    Args:
        session_id: The session identifier (e.g., "user@email.com_uuid")
        version_number: The version number to fetch (1, 2, 3, etc.)
        auth_token: Bearer token for authentication
        base_url: Base URL of the API server (default: http://localhost:8000)
        timeout: Request timeout in seconds (default: 30)
    
    Returns:
        Dict containing:
        - success: bool indicating if the fetch was successful
        - code_snippet: The code content (if found)
        - version_number: The version number
        - version_id: The version UUID
        - label: Optional label for the version
        - created_at: Timestamp when version was created
        - message: Status or error message
        
    Example:
        result = fetch_code_version_api(
            session_id="user@example.com_abc123",
            version_number=1,
            auth_token="eyJhbGciOiJIUzI1NiIs..."
        )
        if result["success"]:
            code = result["code_snippet"]
    """
    try:
        # Build the API URL
        url = f"{base_url}/tools/generate/versions/get/{session_id}/{version_number}"
        
        # Set up headers with authentication
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json"
        }
        
        # Make the GET request
        response = requests.get(url, headers=headers, timeout=timeout)
        
        # Check response status
        if response.status_code == 200:
            data = response.json()
            version_data = data.get("version", {})
            return {
                "success": True,
                "code_snippet": version_data.get("code_snippet"),
                "version_number": version_data.get("version_number"),
                "version_id": version_data.get("version_id"),
                "label": version_data.get("label"),
                "created_at": version_data.get("created_at"),
                "message": "Code version fetched successfully"
            }
        elif response.status_code == 404:
            return {
                "success": False,
                "code_snippet": None,
                "version_number": version_number,
                "message": f"Version {version_number} not found for session {session_id}"
            }
        elif response.status_code == 401:
            return {
                "success": False,
                "code_snippet": None,
                "version_number": version_number,
                "message": "Authentication failed. Please provide a valid auth token."
            }
        elif response.status_code == 403:
            return {
                "success": False,
                "code_snippet": None,
                "version_number": version_number,
                "message": "Access denied. You don't have permission to access this resource."
            }
        else:
            return {
                "success": False,
                "code_snippet": None,
                "version_number": version_number,
                "message": f"API error: {response.status_code} - {response.text}"
            }
            
    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "code_snippet": None,
            "version_number": version_number,
            "message": f"Connection error: Could not connect to {base_url}. Is the server running?"
        }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "code_snippet": None,
            "version_number": version_number,
            "message": f"Request timed out after {timeout} seconds"
        }
    except Exception as e:
        log.error(f"Error in fetch_code_version_api: {e}", exc_info=True)
        return {
            "success": False,
            "code_snippet": None,
            "version_number": version_number,
            "message": f"Error fetching code version: {str(e)}"
        }


# ============================================================================
# DIRECT SERVICE FUNCTION (no HTTP required)
# ============================================================================

def fetch_code_version(session_id: str, version_number: int) -> Dict[str, Any]:
    """
    Fetches a specific code version by session_id and version_number.
    
    This function is designed to be used as an agent tool. The agent can call this
    function to retrieve a previously generated code snippet by its version number.
    
    Args:
        session_id: The session identifier (e.g., "user@email.com_uuid")
        version_number: The version number to fetch (1, 2, 3, etc.)
    
    Returns:
        Dict containing:
        - success: bool indicating if the fetch was successful
        - code_snippet: The code content (if found)
        - version_number: The version number
        - message: Error message (if failed)
        
    Example:
        result = fetch_code_version("user@example.com_abc123", 1)
        if result["success"]:
            code = result["code_snippet"]
    """
    from src.api.app_container import app_container
    
    async def _fetch_async():
        try:
            # Get the code version service from app_container
            code_version_service = app_container.tool_generation_code_version_service
            
            if code_version_service is None:
                return {
                    "success": False,
                    "code_snippet": None,
                    "version_number": version_number,
                    "message": "Code version service not initialized"
                }
            
            # Fetch the version using the service
            result = await code_version_service.get_version_by_number(session_id, version_number)
            
            if result.get("success"):
                version_data = result.get("version", {})
                return {
                    "success": True,
                    "code_snippet": version_data.get("code_snippet"),
                    "version_number": version_data.get("version_number"),
                    "version_id": version_data.get("version_id"),
                    "label": version_data.get("label"),
                    "created_at": version_data.get("created_at"),
                    "message": "Code version fetched successfully"
                }
            else:
                return {
                    "success": False,
                    "code_snippet": None,
                    "version_number": version_number,
                    "message": result.get("message", "Version not found")
                }
                
        except Exception as e:
            log.error(f"Error in fetch_code_version tool: {e}", exc_info=True)
            return {
                "success": False,
                "code_snippet": None,
                "version_number": version_number,
                "message": f"Error fetching code version: {str(e)}"
            }
    
    # Handle async execution in sync context
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, _fetch_async())
                return future.result()
        else:
            return loop.run_until_complete(_fetch_async())
    except RuntimeError:
        return asyncio.run(_fetch_async())
