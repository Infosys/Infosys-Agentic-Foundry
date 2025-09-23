# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import sys
import asyncio
import uvicorn
import argparse

if __name__ == "__main__":
    app = "main:app"

    parser = argparse.ArgumentParser(description="Run FastAPI app with custom event loop policy on Windows.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--workers", type=int, help="Number of worker processes")
    parser.add_argument("--reload-excludes", nargs='*', default=[],
                        help="Paths (files or directories with glob patterns) to exclude from reload watching (e.g., --reload-excludes 'user_uploads/*' '.env')")

    args = parser.parse_args()

    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Define the directories and files to exclude from reloading
    # Using glob patterns for directories to explicitly ignore all contents
    # For files, just the filename is fine.
    default_excludes = [
        os.path.join("sdlc", "*"),
        os.path.join("evaluation_uploads", "*"),
        os.path.join("uploaded_sqlite_dbs", "*"),
        os.path.join("user_uploads", "*"),
        os.path.join("Hugging_face", "*"),
        ".gitignore",
        "run_server.py",
        "user_interface.py"
    ]

    # Combine default excludes with any user-provided excludes
    reload_excludes_list = list(set(default_excludes + args.reload_excludes)) if args.reload else None

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers,
        reload_dirs=["."] if args.reload else None, # Explicitly watch the current directory
        reload_excludes=reload_excludes_list
    )

