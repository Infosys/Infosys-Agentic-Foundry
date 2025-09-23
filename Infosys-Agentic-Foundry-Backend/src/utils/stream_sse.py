import asyncio
import json
from typing import Dict
from fastapi import Request
import datetime
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.messages.base import message_to_dict

# How often to send a "keep-alive" message to prevent network timeouts.
KEEP_ALIVE_INTERVAL_SECONDS = 15
class MessageEncoder(json.JSONEncoder):
    def default(self, obj):
        # Check if obj is one of the message types supported
        if isinstance(obj, (HumanMessage, AIMessage, ToolMessage)):
            return message_to_dict(obj)
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        # Otherwise, use the default serializer (no action needed)
        return super().default(obj)
    
class SSEConnection:
    """Represents a single client's SSE connection."""
    def __init__(self):
        # A queue to hold the messages to be sent to this specific client.
        self.queue = asyncio.Queue()

    async def send(self, data: dict):
        """Puts a message into the queue to be sent to the client."""
        await self.queue.put(data)

    async def event_stream(self, request: Request):
        """
        The main generator that yields SSE events. This is the heart of the logic.
        It runs our asynchronous "race" to handle data, heartbeats, and disconnects.
        """
        # Runner 1: The Message Runner. Waits for data in the queue.
        get_message_task = asyncio.create_task(self.queue.get())
        
        # Runner 2: The Disconnect Runner. Waits for the client to close the connection.
        # We shield it to ensure we can detect the disconnect even if the server tries to cancel tasks.
        is_disconnected_task = asyncio.shield(request.is_disconnected())
        
        # Runner 3: The Heartbeat Runner. A simple timer.
        sleep_task = asyncio.create_task(asyncio.sleep(KEEP_ALIVE_INTERVAL_SECONDS))

        try:
            # This is our main "game loop"
            while True:
                # The "Race Director": waits for the FIRST task to complete.
                done, pending = await asyncio.wait(
                    [get_message_task, is_disconnected_task, sleep_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # --- Check which runner won the race ---

                # WINNER: Disconnect Runner. The user has closed their browser.
                if is_disconnected_task in done:
                    if is_disconnected_task.result():
                        print("Client disconnected. Breaking event stream loop.")
                        break

                # WINNER: Message Runner. We have new data to send.
                if get_message_task in done:
                    data = get_message_task.result()
                    json_data = json.dumps(data, cls=MessageEncoder)
                    yield f"data: {json_data}\n\n"
                    
                    # Restart the race: create a new message task and reset the heartbeat timer.
                    get_message_task = asyncio.create_task(self.queue.get())
                    sleep_task.cancel()
                    sleep_task = asyncio.create_task(asyncio.sleep(KEEP_ALIVE_INTERVAL_SECONDS))

                # WINNER: Heartbeat Runner. The connection is idle, send a keep-alive.
                if sleep_task in done:
                    yield ": keep-alive\n\n"
                    
                    # Restart the timer for the next interval.
                    sleep_task = asyncio.create_task(asyncio.sleep(KEEP_ALIVE_INTERVAL_SECONDS))
        
        except asyncio.CancelledError:
            # This exception is raised when the server shuts down.
            print("Event stream cancelled (server shutdown).")
        
        finally:
            # The "Cleanup Crew": This runs no matter how the loop exits.
            # We cancel all our runners to prevent them from running forever in the background.
            get_message_task.cancel()
            is_disconnected_task.cancel()
            sleep_task.cancel()


class SSEManager:
    """Manages all active SSE connections, identified by a session_id."""
    def __init__(self):
        self.connections: Dict[str, SSEConnection] = {}

    def register(self, session_id: str) -> SSEConnection:
        """Creates and stores a new connection for a given session_id."""
        conn = SSEConnection()
        self.connections[session_id] = conn
        print(f"Session '{session_id}' registered. Total connections: {len(self.connections)}")
        return conn

    def unregister(self, session_id: str):
        """Removes a connection, freeing up its resources."""
        if self.connections.pop(session_id, None):
            print(f"Session '{session_id}' unregistered. Total connections: {len(self.connections)}")

    async def send(self, session_id: str, data: dict):
        """Sends data to a specific client by their session_id."""
        conn = self.connections.get(session_id)
        if conn:
            await conn.send(data)
        else:
             print(f"Attempted to send to non-existent session '{session_id}'.")

