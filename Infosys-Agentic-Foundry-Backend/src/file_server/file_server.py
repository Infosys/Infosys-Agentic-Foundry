# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Independent File Server for User Uploads

A standalone FastAPI application that provides read-only access to user_uploads
directory. Runs in a separate thread and can be enabled via FILE_SERVER_ENABLED env var.

Features:
- Browse file structure by department/subdirectory
- Download files without authentication
- Web-based file browser UI
- Configurable allowed hosts for security
"""

import os
import threading
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from dotenv import load_dotenv

from telemetry_wrapper import logger as log

load_dotenv()

# Configuration from environment
FILE_SERVER_ENABLED = os.getenv("FILE_SERVER_ENABLED", "false").lower() == "true"
FILE_SERVER_HOST = os.getenv("FILE_SERVER_HOST", "127.0.0.1")
FILE_SERVER_PORT = int(os.getenv("FILE_SERVER_PORT", "8001"))
FILE_SERVER_BASE_DIR = os.getenv("FILE_SERVER_BASE_DIR", "user_uploads")
FILE_SERVER_ALLOWED_HOSTS = os.getenv("FILE_SERVER_ALLOWED_HOSTS", "*")  # Comma-separated or "*" for all


class AllowedHostsMiddleware(BaseHTTPMiddleware):
    """Middleware to restrict access to specific hosts/IPs."""
    
    def __init__(self, app, allowed_hosts: str = "*"):
        super().__init__(app)
        self.allowed_hosts = self._parse_allowed_hosts(allowed_hosts)
    
    def _parse_allowed_hosts(self, hosts_str: str) -> List[str]:
        """Parse comma-separated hosts string into a list."""
        if hosts_str.strip() == "*":
            return ["*"]
        return [h.strip() for h in hosts_str.split(",") if h.strip()]
    
    async def dispatch(self, request: Request, call_next):
        if "*" not in self.allowed_hosts:
            client_host = request.client.host if request.client else None
            forwarded_for = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            request_host = request.headers.get("Host", "").split(":")[0]
            
            # Check if any of the identifiers match allowed hosts
            allowed = False
            for check_host in [client_host, forwarded_for, request_host]:
                if check_host and check_host in self.allowed_hosts:
                    allowed = True
                    break
            
            # Also check localhost variants
            localhost_variants = ["127.0.0.1", "localhost", "::1"]
            if not allowed:
                for variant in localhost_variants:
                    if variant in self.allowed_hosts and client_host in localhost_variants:
                        allowed = True
                        break
            
            if not allowed:
                return JSONResponse(
                    status_code=403,
                    content={"detail": f"Access denied. Host '{client_host}' is not in the allowed hosts list."}
                )
        
        return await call_next(request)


def create_file_server_app() -> FastAPI:
    """Create and configure the file server FastAPI application."""
    
    app = FastAPI(
        title="Infosys Agentic Foundry - File Server",
        description="Read-only file server for browsing and downloading user uploads",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc"
    )
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
    )
    
    # Add allowed hosts middleware
    app.add_middleware(AllowedHostsMiddleware, allowed_hosts=FILE_SERVER_ALLOWED_HOSTS)
    
    base_dir = FILE_SERVER_BASE_DIR
    
    # Ensure base directory exists
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)
    
    @app.get("/", response_class=HTMLResponse)
    async def file_browser_ui():
        """Serve the file browser HTML interface."""
        return get_file_browser_html()
    
    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "service": "file-server",
            "base_dir": base_dir,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    @app.get("/files/structure")
    async def get_full_file_structure():
        """
        Get the complete file structure of user_uploads directory.
        Returns a nested dictionary representing the directory tree.
        """
        try:
            structure = await generate_file_structure_async(base_dir)
            return JSONResponse(content={
                "base_dir": base_dir,
                "structure": structure
            })
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error reading file structure: {str(e)}")
    
    @app.get("/files/browse")
    async def browse_directory(path: str = Query("", description="Relative path to browse")):
        """
        Browse a specific directory path.
        Returns list of files and subdirectories at the given path.
        
        Parameters:
        - path: Relative path within user_uploads (e.g., "Engineering/reports")
        """
        try:
            # Sanitize path
            sanitized_path = sanitize_path(path)
            full_path = os.path.join(base_dir, sanitized_path) if sanitized_path else base_dir
            
            # Validate path is within base_dir
            abs_full_path = os.path.abspath(full_path)
            abs_base_path = os.path.abspath(base_dir)
            
            if not abs_full_path.startswith(abs_base_path):
                raise HTTPException(status_code=400, detail="Invalid path - outside allowed directory")
            
            if not os.path.exists(full_path):
                raise HTTPException(status_code=404, detail=f"Path not found: {path}")
            
            if not os.path.isdir(full_path):
                raise HTTPException(status_code=400, detail=f"Path is not a directory: {path}")
            
            items = []
            for item in os.listdir(full_path):
                item_path = os.path.join(full_path, item)
                item_stat = os.stat(item_path)
                
                items.append({
                    "name": item,
                    "type": "directory" if os.path.isdir(item_path) else "file",
                    "size": item_stat.st_size if os.path.isfile(item_path) else None,
                    "modified": datetime.fromtimestamp(item_stat.st_mtime).isoformat(),
                    "path": os.path.join(sanitized_path, item).replace("\\", "/") if sanitized_path else item
                })
            
            # Sort: directories first, then files, both alphabetically
            items.sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"].lower()))
            
            return {
                "current_path": sanitized_path or "/",
                "parent_path": os.path.dirname(sanitized_path) if sanitized_path else None,
                "items": items,
                "count": len(items)
            }
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error browsing directory: {str(e)}")
    
    @app.get("/files/download")
    async def download_file(
        filename: str = Query(..., description="Name of the file to download"),
        path: str = Query("", description="Subdirectory path where the file is located")
    ):
        """
        Download a specific file.
        
        Parameters:
        - filename: Name of the file to download
        - path: Subdirectory path (relative to user_uploads)
        """
        try:
            # Sanitize inputs
            sanitized_filename = sanitize_filename(filename)
            sanitized_path = sanitize_path(path)
            
            if not sanitized_filename:
                raise HTTPException(status_code=400, detail="Filename cannot be empty")
            
            # Construct full path
            if sanitized_path:
                file_path = os.path.join(base_dir, sanitized_path, sanitized_filename)
            else:
                file_path = os.path.join(base_dir, sanitized_filename)
            
            # Validate path is within base_dir
            abs_file_path = os.path.abspath(file_path)
            abs_base_path = os.path.abspath(base_dir)
            
            if not abs_file_path.startswith(abs_base_path):
                raise HTTPException(status_code=400, detail="Invalid path - outside allowed directory")
            
            if not os.path.exists(file_path):
                raise HTTPException(status_code=404, detail=f"File not found: {filename}")
            
            if not os.path.isfile(file_path):
                raise HTTPException(status_code=400, detail=f"Path is not a file: {filename}")
            
            return FileResponse(
                path=file_path,
                filename=sanitized_filename,
                media_type="application/octet-stream"
            )
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error downloading file: {str(e)}")
    
    @app.get("/files/info")
    async def get_file_info(
        filename: str = Query(..., description="Name of the file"),
        path: str = Query("", description="Subdirectory path where the file is located")
    ):
        """
        Get information about a specific file.
        
        Parameters:
        - filename: Name of the file
        - path: Subdirectory path (relative to user_uploads)
        """
        try:
            # Sanitize inputs
            sanitized_filename = sanitize_filename(filename)
            sanitized_path = sanitize_path(path)
            
            if not sanitized_filename:
                raise HTTPException(status_code=400, detail="Filename cannot be empty")
            
            # Construct full path
            if sanitized_path:
                file_path = os.path.join(base_dir, sanitized_path, sanitized_filename)
            else:
                file_path = os.path.join(base_dir, sanitized_filename)
            
            # Validate path is within base_dir
            abs_file_path = os.path.abspath(file_path)
            abs_base_path = os.path.abspath(base_dir)
            
            if not abs_file_path.startswith(abs_base_path):
                raise HTTPException(status_code=400, detail="Invalid path - outside allowed directory")
            
            if not os.path.exists(file_path):
                raise HTTPException(status_code=404, detail=f"File not found: {filename}")
            
            stat_info = os.stat(file_path)
            
            return {
                "filename": sanitized_filename,
                "path": os.path.join(sanitized_path, sanitized_filename).replace("\\", "/") if sanitized_path else sanitized_filename,
                "size": stat_info.st_size,
                "size_human": format_file_size(stat_info.st_size),
                "modified": datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
                "created": datetime.fromtimestamp(stat_info.st_ctime).isoformat(),
                "is_file": os.path.isfile(file_path),
                "is_directory": os.path.isdir(file_path),
                "extension": os.path.splitext(sanitized_filename)[1].lower()
            }
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error getting file info: {str(e)}")
    
    @app.get("/files/search")
    async def search_files(
        query: str = Query(..., min_length=1, description="Search query (filename pattern)"),
        path: str = Query("", description="Subdirectory to search within (optional)")
    ):
        """
        Search for files matching a pattern.
        
        Parameters:
        - query: Search query (case-insensitive, partial match)
        - path: Optional subdirectory to limit search scope
        """
        try:
            sanitized_path = sanitize_path(path)
            search_root = os.path.join(base_dir, sanitized_path) if sanitized_path else base_dir
            
            # Validate path is within base_dir
            abs_search_root = os.path.abspath(search_root)
            abs_base_path = os.path.abspath(base_dir)
            
            if not abs_search_root.startswith(abs_base_path):
                raise HTTPException(status_code=400, detail="Invalid path - outside allowed directory")
            
            if not os.path.exists(search_root):
                raise HTTPException(status_code=404, detail=f"Search path not found: {path}")
            
            results = []
            query_lower = query.lower()
            
            for root, dirs, files in os.walk(search_root):
                for filename in files:
                    if query_lower in filename.lower():
                        rel_path = os.path.relpath(root, base_dir)
                        file_path = os.path.join(root, filename)
                        stat_info = os.stat(file_path)
                        
                        results.append({
                            "filename": filename,
                            "path": rel_path.replace("\\", "/") if rel_path != "." else "",
                            "full_path": os.path.join(rel_path, filename).replace("\\", "/") if rel_path != "." else filename,
                            "size": stat_info.st_size,
                            "size_human": format_file_size(stat_info.st_size),
                            "modified": datetime.fromtimestamp(stat_info.st_mtime).isoformat()
                        })
                        
                        # Limit results to prevent overwhelming responses
                        if len(results) >= 100:
                            break
                
                if len(results) >= 100:
                    break
            
            return {
                "query": query,
                "search_path": sanitized_path or "/",
                "results": results,
                "count": len(results),
                "truncated": len(results) >= 100
            }
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error searching files: {str(e)}")
    
    return app


def sanitize_path(path: str) -> str:
    """Sanitize a directory path to prevent directory traversal."""
    if not path:
        return ""
    
    # Remove leading/trailing whitespace and slashes
    path = path.strip().strip("/\\")
    
    # Block dangerous patterns
    if ".." in path or ":" in path:
        raise HTTPException(status_code=400, detail="Invalid path characters")
    
    # Normalize path separators
    path = path.replace("\\", "/")
    
    return path


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename to prevent path traversal."""
    if not filename:
        return ""
    
    # Remove leading/trailing whitespace and slashes
    filename = filename.strip().strip("/\\")
    
    # Block dangerous patterns
    if ".." in filename or ":" in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    return filename


def format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


async def generate_file_structure_async(base_dir: str) -> Dict[str, Any]:
    """Generate a nested dictionary representing the file structure."""
    structure = {}
    
    for root, dirs, files in os.walk(base_dir):
        # Get relative path from base_dir
        rel_path = os.path.relpath(root, base_dir)
        
        # Navigate to the correct level in the structure
        if rel_path == ".":
            current_level = structure
        else:
            parts = rel_path.split(os.sep)
            current_level = structure
            for part in parts:
                if part not in current_level:
                    current_level[part] = {}
                current_level = current_level[part]
        
        # Add files to current level
        if files:
            current_level["__files__"] = files
    
    return structure


def get_file_browser_html() -> str:
    """Return the HTML for the file browser UI."""
    return '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>File Browser - Infosys Agentic Foundry</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e0e0e0;
            min-height: 100vh;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        header {
            background: rgba(255,255,255,0.05);
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        header h1 {
            font-size: 1.5rem;
            color: #00d4ff;
        }
        .breadcrumb {
            background: rgba(255,255,255,0.05);
            padding: 12px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }
        .breadcrumb a {
            color: #00d4ff;
            text-decoration: none;
            padding: 4px 8px;
            border-radius: 4px;
            transition: background 0.2s;
        }
        .breadcrumb a:hover {
            background: rgba(0, 212, 255, 0.1);
        }
        .breadcrumb span {
            color: #666;
        }
        .search-box {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }
        .search-box input {
            flex: 1;
            padding: 12px 16px;
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px;
            background: rgba(255,255,255,0.05);
            color: #e0e0e0;
            font-size: 1rem;
        }
        .search-box input:focus {
            outline: none;
            border-color: #00d4ff;
        }
        .search-box button {
            padding: 12px 24px;
            background: #00d4ff;
            color: #1a1a2e;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .search-box button:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 212, 255, 0.3);
        }
        .file-list {
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            overflow: hidden;
        }
        .file-item {
            display: flex;
            align-items: center;
            padding: 16px 20px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            transition: background 0.2s;
            cursor: pointer;
        }
        .file-item:hover {
            background: rgba(255,255,255,0.08);
        }
        .file-item:last-child {
            border-bottom: none;
        }
        .file-icon {
            width: 40px;
            height: 40px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: rgba(0, 212, 255, 0.1);
            border-radius: 8px;
            margin-right: 16px;
            font-size: 1.2rem;
        }
        .file-icon.folder {
            background: rgba(255, 193, 7, 0.1);
            color: #ffc107;
        }
        .file-icon.file {
            background: rgba(0, 212, 255, 0.1);
            color: #00d4ff;
        }
        .file-info {
            flex: 1;
        }
        .file-name {
            font-weight: 500;
            margin-bottom: 4px;
            color: #fff;
        }
        .file-meta {
            font-size: 0.85rem;
            color: #888;
        }
        .file-actions {
            display: flex;
            gap: 8px;
        }
        .file-actions a {
            padding: 8px 16px;
            background: rgba(0, 212, 255, 0.1);
            color: #00d4ff;
            text-decoration: none;
            border-radius: 6px;
            font-size: 0.85rem;
            transition: background 0.2s;
        }
        .file-actions a:hover {
            background: rgba(0, 212, 255, 0.2);
        }
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #666;
        }
        .empty-state svg {
            width: 80px;
            height: 80px;
            margin-bottom: 20px;
            opacity: 0.5;
        }
        .loading {
            text-align: center;
            padding: 40px;
            color: #888;
        }
        .error {
            background: rgba(255, 87, 87, 0.1);
            border: 1px solid rgba(255, 87, 87, 0.3);
            color: #ff5757;
            padding: 16px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📁 File Browser</h1>
            <span style="color: #888;">Infosys Agentic Foundry</span>
        </header>
        
        <div class="breadcrumb" id="breadcrumb">
            <a href="#" onclick="browse('')">🏠 Home</a>
        </div>
        
        <div class="search-box">
            <input type="text" id="searchInput" placeholder="Search files..." onkeypress="if(event.key==='Enter') searchFiles()">
            <button onclick="searchFiles()">Search</button>
        </div>
        
        <div id="content" class="file-list">
            <div class="loading">Loading...</div>
        </div>
    </div>
    
    <script>
        let currentPath = '';
        
        async function browse(path) {
            currentPath = path;
            updateBreadcrumb(path);
            
            const content = document.getElementById('content');
            content.innerHTML = '<div class="loading">Loading...</div>';
            
            try {
                const response = await fetch(`/files/browse?path=${encodeURIComponent(path)}`);
                const data = await response.json();
                
                if (!response.ok) {
                    throw new Error(data.detail || 'Failed to load directory');
                }
                
                renderItems(data.items);
            } catch (error) {
                content.innerHTML = `<div class="error">${error.message}</div>`;
            }
        }
        
        function renderItems(items) {
            const content = document.getElementById('content');
            
            if (items.length === 0) {
                content.innerHTML = `
                    <div class="empty-state">
                        <svg viewBox="0 0 24 24" fill="currentColor">
                            <path d="M20 6h-8l-2-2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2z"/>
                        </svg>
                        <p>This folder is empty</p>
                    </div>
                `;
                return;
            }
            
            content.innerHTML = items.map(item => `
                <div class="file-item" onclick="${item.type === 'directory' ? `browse('${item.path}')` : ''}">
                    <div class="file-icon ${item.type}">
                        ${item.type === 'directory' ? '📁' : getFileIcon(item.name)}
                    </div>
                    <div class="file-info">
                        <div class="file-name">${item.name}</div>
                        <div class="file-meta">
                            ${item.type === 'directory' ? 'Folder' : formatSize(item.size)}
                            &bull; Modified: ${new Date(item.modified).toLocaleDateString()}
                        </div>
                    </div>
                    ${item.type === 'file' ? `
                        <div class="file-actions">
                            <a href="/files/download?filename=${encodeURIComponent(item.name)}&path=${encodeURIComponent(currentPath)}" onclick="event.stopPropagation()">
                                ⬇️ Download
                            </a>
                        </div>
                    ` : ''}
                </div>
            `).join('');
        }
        
        function updateBreadcrumb(path) {
            const breadcrumb = document.getElementById('breadcrumb');
            let html = '<a href="#" onclick="browse(\\'\\')">🏠 Home</a>';
            
            if (path) {
                const parts = path.split('/');
                let currentBreadcrumbPath = '';
                
                parts.forEach((part, index) => {
                    currentBreadcrumbPath += (index > 0 ? '/' : '') + part;
                    html += ` <span>/</span> <a href="#" onclick="browse('${currentBreadcrumbPath}')">${part}</a>`;
                });
            }
            
            breadcrumb.innerHTML = html;
        }
        
        async function searchFiles() {
            const query = document.getElementById('searchInput').value.trim();
            if (!query) return;
            
            const content = document.getElementById('content');
            content.innerHTML = '<div class="loading">Searching...</div>';
            
            try {
                const response = await fetch(`/files/search?query=${encodeURIComponent(query)}&path=${encodeURIComponent(currentPath)}`);
                const data = await response.json();
                
                if (!response.ok) {
                    throw new Error(data.detail || 'Search failed');
                }
                
                if (data.results.length === 0) {
                    content.innerHTML = `
                        <div class="empty-state">
                            <p>No files found matching "${query}"</p>
                        </div>
                    `;
                    return;
                }
                
                content.innerHTML = data.results.map(item => `
                    <div class="file-item">
                        <div class="file-icon file">${getFileIcon(item.filename)}</div>
                        <div class="file-info">
                            <div class="file-name">${item.filename}</div>
                            <div class="file-meta">
                                ${item.size_human} &bull; Path: ${item.path || '/'} &bull; Modified: ${new Date(item.modified).toLocaleDateString()}
                            </div>
                        </div>
                        <div class="file-actions">
                            <a href="/files/download?filename=${encodeURIComponent(item.filename)}&path=${encodeURIComponent(item.path)}">
                                ⬇️ Download
                            </a>
                        </div>
                    </div>
                `).join('');
                
                if (data.truncated) {
                    content.innerHTML += '<div class="loading">Results limited to 100 items</div>';
                }
            } catch (error) {
                content.innerHTML = `<div class="error">${error.message}</div>`;
            }
        }
        
        function getFileIcon(filename) {
            const ext = filename.split('.').pop().toLowerCase();
            const icons = {
                'pdf': '📄',
                'doc': '📝', 'docx': '📝',
                'xls': '📊', 'xlsx': '📊', 'csv': '📊',
                'ppt': '📽️', 'pptx': '📽️',
                'txt': '📃', 'md': '📃',
                'py': '🐍',
                'js': '⚡', 'ts': '⚡',
                'json': '📋',
                'html': '🌐', 'css': '🎨',
                'jpg': '🖼️', 'jpeg': '🖼️', 'png': '🖼️', 'gif': '🖼️', 'svg': '🖼️',
                'zip': '📦', 'tar': '📦', 'gz': '📦', 'rar': '📦',
                'db': '🗄️', 'sqlite': '🗄️', 'sql': '🗄️'
            };
            return icons[ext] || '📄';
        }
        
        function formatSize(bytes) {
            if (bytes === null || bytes === undefined) return '';
            const units = ['B', 'KB', 'MB', 'GB', 'TB'];
            let i = 0;
            while (bytes >= 1024 && i < units.length - 1) {
                bytes /= 1024;
                i++;
            }
            return bytes.toFixed(1) + ' ' + units[i];
        }
        
        // Initial load
        browse('');
    </script>
</body>
</html>
'''


def start_file_server_thread(host: str = None, port: int = None) -> Optional[threading.Thread]:
    """
    Start the file server in a separate thread.
    
    Args:
        host: Host to bind to (defaults to FILE_SERVER_HOST env var)
        port: Port to bind to (defaults to FILE_SERVER_PORT env var)
    
    Returns:
        Thread object if server started, None if disabled
    """
    import sys
    import time
    
    if not FILE_SERVER_ENABLED:
        return None
    
    host = host or FILE_SERVER_HOST
    port = port or FILE_SERVER_PORT
    
    app = create_file_server_app()
    
    def run_server():
        # Configure uvicorn with minimal logging to avoid noise
        config = uvicorn.Config(
            app=app,
            host=host,
            port=port,
            log_level="error",  # Only show errors, not warnings
            access_log=False
        )
        server = uvicorn.Server(config)
        server.run()
    
    thread = threading.Thread(target=run_server, daemon=True, name="FileServerThread")
    thread.start()
    
    # Small delay to let the thread start, then print info
    time.sleep(0.1)
    
    # Print startup info with flush to ensure proper output ordering
    log.info(f"[File Server] Running on http://{host}:{port}")
    log.info(f"[File Server] Base directory: {FILE_SERVER_BASE_DIR}")
    log.info(f"[File Server] Allowed hosts: {FILE_SERVER_ALLOWED_HOSTS}")
    sys.stdout.flush()
    
    return thread


# Allow running directly for testing
if __name__ == "__main__":
    import sys
    
    # Override enabled flag when running directly
    FILE_SERVER_ENABLED = True
    
    host = sys.argv[1] if len(sys.argv) > 1 else FILE_SERVER_HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else FILE_SERVER_PORT
    
    log.info(f"Starting file server on http://{host}:{port}")
    app = create_file_server_app()
    uvicorn.run(app, host=host, port=port)
