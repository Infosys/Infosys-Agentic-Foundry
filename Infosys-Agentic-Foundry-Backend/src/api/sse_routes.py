import uuid
import asyncio
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from telemetry_wrapper import logger as log

router = APIRouter(tags=["SSE Streaming"])

@router.get("/stream/{session_id}")
async def stream(request: Request, session_id: str, response: Response):
    """The public API endpoint that clients connect to."""
    # We need a unique ID for each client to manage their connection.
    # A cookie is a standard way to persist this ID across requests from the same browser.
    
    if not session_id:
        session_id = str(uuid.uuid4())
        response.set_cookie(key="user_session", value=session_id, httponly=True)
    log.info(f"New SSE connection established with session ID: {session_id}")
    # Get the shared SSEManager instance from the application state.
    sse_manager = request.app.state.sse_manager
    
    # Register this new client connection with the manager.
    conn = sse_manager.register(session_id)

    async def event_generator():
        """
        This inner generator handles the lifecycle for a single request.
        It runs the core event_stream logic and ensures cleanup happens.
        """
        try:
            # Start yielding events from our main logic.
            async for event in conn.event_stream(request):
                yield event
        finally:
            # This is the crucial cleanup step for the manager.
            # It runs when the client disconnects or the server shuts down.
            sse_manager.unregister(session_id)

    return StreamingResponse(event_generator(), media_type="text/event-stream")