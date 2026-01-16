import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import asyncpg
from telemetry_wrapper import logger as log

class ToolFileManager:
    """
    Manages tool .py files - creates, updates, deletes, and restores files.
    """

    def __init__(self, base_directory: Optional[str] = None, pool: Optional[asyncpg.Pool] = None):
        """Initialize ToolFileManager with storage directory and database pool."""
        if base_directory is None:
            project_root = Path(__file__).parent.parent.parent
            self.base_directory = project_root / "onboarded_tools"
        else:
            self.base_directory = Path(base_directory)
        self.base_directory.mkdir(parents=True, exist_ok=True)
        self.pool = pool
        log.info(f"ToolFileManager initialized with base directory: {self.base_directory}")
    
    def _sanitize_filename(self, tool_name: str) -> str:
        """Convert tool_name to valid filename with .py extension."""
        sanitized = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in tool_name)
        return f"{sanitized}.py"
    
    def _format_datetime(self, dt: Optional[datetime]) -> str:
        """Format datetime for Python file (returns 'None' or ISO string)."""
        if dt is None:
            return "None"
        if isinstance(dt, str):
            return f"'{dt}'"
        return f"'{dt.isoformat()}'"
    
    def _escape_string(self, s: Optional[str]) -> str:
        """Escape special characters for Python code (returns 'None' or triple-quoted string)."""
        if s is None:
            return "None"
        if '\n' in s or "'''" in s or '"""' in s:
            return repr(s)
        return f'"""{s}"""'
    
    async def create_tool_file(self, tool_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a .py file for the tool with code.
        """
        try:
            tool_name = tool_data.get('tool_name')
            if not tool_name:
                return {
                    "success": False,
                    "file_path": "",
                    "message": "tool_name is required to create tool file"
                }
            filename = self._sanitize_filename(tool_name)
            file_path = self.base_directory / filename
            file_content = self._generate_file_content(tool_data)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(file_content)
            log.info(f"Successfully created tool file: {file_path}")
            return {
                "success": True,
                "file_path": str(file_path),
                "message": f"Tool file created successfully at {file_path}"
            }
        except Exception as e:
            log.error(f"Error creating tool file for tool_name {tool_data.get('tool_name')}: {e}")
            return {
                "success": False,
                "file_path": "",
                "message": f"Failed to create tool file: {str(e)}"
            }
    
    def _generate_file_content(self, tool_data: Dict[str, Any]) -> str:
        """
        Generate Python file content with code_snippet.
        """
        code_snippet = tool_data.get('code_snippet', '')
        content = f'''{code_snippet}'''
        return content
    
    async def update_tool_file(self, tool_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update existing tool file by overwriting with new data.
        If file doesn't exist (old tools), create it during update.
        """
        tool_name = tool_data.get('tool_name')
        if not tool_name:
            return {
                "success": False,
                "file_path": "",
                "message": "tool_name is required to update tool file"
            }
        file_exists = await self.tool_file_exists(tool_name)
        result = await self.create_tool_file(tool_data)
        if result.get("success"):
            if not file_exists:
                log.info(f"Created file for tool '{tool_name}' during update")
                result["message"] = f"Tool file created for tool during update at {result.get('file_path')}"
            else:
                log.info(f"Updated existing file for tool '{tool_name}'")
                result["message"] = f"Tool file updated successfully at {result.get('file_path')}"
        
        return result
    
    async def delete_tool_file(self, tool_name: str) -> Dict[str, Any]:
        """
        Delete tool file by tool_name. Called when tool is deleted and moved to recycle bin.
        """
        try:
            filename = self._sanitize_filename(tool_name)
            file_path = self.base_directory / filename
            if file_path.exists():
                file_path.unlink()
                log.info(f"Successfully deleted tool file: {file_path}")
                return {
                    "success": True,
                    "file_path": str(file_path),
                    "message": f"Tool file deleted successfully"
                }
            else:
                log.warning(f"Tool file not found: {file_path}")
                return {
                    "success": False,
                    "file_path": str(file_path),
                    "message": f"Tool file not found"
                }
        except Exception as e:
            log.error(f"Error deleting tool file for tool_name {tool_name}: {e}")
            return {
                "success": False,
                "file_path": "",
                "message": f"Failed to delete tool file: {str(e)}"
            }
    
    async def restore_tool_file(self, tool_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Restore tool file when tool is restored from recycle bin.
        Fetches data from database and recreates the .py file.
        """
        try:
            tool_name = tool_data.get('tool_name')
            if not tool_name:
                return {
                    "success": False,
                    "file_path": "",
                    "message": "tool_name is required to restore tool file"
                }
            result = await self.create_tool_file(tool_data)
            
            if result.get("success"):
                log.info(f"Successfully restored tool file for: {tool_name}")
                return {
                    "success": True,
                    "file_path": result.get("file_path", ""),
                    "message": f"Tool file restored successfully from database"
                }
            else:
                log.error(f"Failed to restore tool file for: {tool_name}")
                return result
                
        except Exception as e:
            log.error(f"Error restoring tool file for tool_name {tool_data.get('tool_name')}: {e}")
            return {
                "success": False,
                "file_path": "",
                "message": f"Failed to restore tool file: {str(e)}"
            }
    
    async def get_tool_file_path(self, tool_name: str) -> Optional[str]:
        """Get file path for tool's .py file (returns None if doesn't exist)."""
        filename = self._sanitize_filename(tool_name)
        file_path = self.base_directory / filename
        
        if file_path.exists():
            return str(file_path)
        return None
    
    async def tool_file_exists(self, tool_name: str) -> bool:
        """Check if tool file exists by tool_name."""
        filename = self._sanitize_filename(tool_name)
        file_path = self.base_directory / filename
        return file_path.exists()
    
    async def sync_existing_tools_from_db(self, force: bool = False) -> Dict[str, Any]:
        """
        Sync all existing tools from database to .py files.
        Call this once to create files for tools that were added before this feature.
        
        Args:
            force: If True, recreate all files even if they exist
        """
        if not self.pool:
            return {"success": False, "error": "Database pool not initialized"}
        
        try:
            query = """
                SELECT tool_name, code_snippet
                FROM tool_table
            """
            
            async with self.pool.acquire() as conn:
                tools = await conn.fetch(query)
            if not tools:
                log.info("No tools found in database")
                return {"success": True, "total": 0, "created": 0, "skipped": 0}
            log.info(f"Found {len(tools)} active tools in database")
            files_created = 0
            files_skipped = 0
            for tool in tools:
                tool_data = {
                    "tool_name": tool['tool_name'],
                    "code_snippet": tool['code_snippet']
                }
                
                tool_name = tool_data["tool_name"]
                if not force and await self.tool_file_exists(tool_name):
                    files_skipped += 1
                    continue
                result = await self.create_tool_file(tool_data)
                if result.get("success"):
                    files_created += 1
                    log.info(f"Created file for '{tool_name}'")
            log.info(f"Sync complete: {files_created} created, {files_skipped} skipped")
            return {
                "success": True,
                "total": len(tools),
                "created": files_created,
                "skipped": files_skipped
            }  
        except Exception as e:
            log.error(f"Error syncing tools from database: {e}")
            return {"success": False, "error": str(e)}