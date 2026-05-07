# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Agent Worker Runner - Entry point for starting the Kafka agent worker.

Usage:
    python run_agent_worker.py
    python run_agent_worker.py --port 8101
    python run_agent_worker.py --workers 4
"""

import os
import sys
import asyncio
import uvicorn
import argparse

if __name__ == "__main__":
    app = "agent_worker.main:app"

    parser = argparse.ArgumentParser(description="Run Kafka agent worker with custom event loop policy on Windows.")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8102, help="Port to bind to (default: 8101)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--workers", type=int, help="Number of worker processes")
    parser.add_argument("--kafka-servers", default=None,
                        help="Kafka bootstrap servers (default: from KAFKA_BOOTSTRAP_SERVERS env var)")
    parser.add_argument("--max-concurrent", type=int, default=None,
                        help="Max concurrent requests per worker (default: from MAX_CONCURRENT_REQUESTS env var)")

    args = parser.parse_args()

    # Set environment variables from command line args if provided
    if args.kafka_servers:
        os.environ["KAFKA_BOOTSTRAP_SERVERS"] = args.kafka_servers
    if args.max_concurrent:
        os.environ["MAX_CONCURRENT_REQUESTS"] = str(args.max_concurrent)

    # Override port in env if provided via CLI
    os.environ["AGENT_WORKER_PORT"] = str(args.port)
    os.environ["AGENT_WORKER_HOST"] = args.host

    # Fix for Windows: Psycopg/asyncpg requires WindowsSelectorEventLoopPolicy
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Define directories to exclude from reloading
    reload_excludes_list = [
        os.path.join("sdlc", "*"),
        os.path.join("evaluation_uploads", "*"),
        os.path.join("uploaded_sqlite_dbs", "*"),
        os.path.join("user_uploads", "*"),
        os.path.join("Hugging_face", "*"),
        os.path.join("onboarded_tools", "*"),
        os.path.join("outputs", "*"),
        os.path.join("responses_temp", "*"),
        os.path.join("temp_previews", "*"),
        os.path.join("agent_workspaces", "*"),
        ".gitignore",
        "run_worker.py",
        "run_server.py",
        "run_agent_worker.py"
    ] if args.reload else None

    print(f"Starting Kafka agent worker on {args.host}:{args.port}")
    
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers,
        reload_dirs=["agent_worker", "src"] if args.reload else None,
        reload_excludes=reload_excludes_list
    )
