# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import json
from typing import Any, Dict, List, Union, Callable

from fastmcp import Client as FastMCPClient
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport
from mcp.types import Tool as MCPTool, TextContent, Content # Import Content for broader response handling

from telemetry_wrapper import logger as log


class MCPToolAdapter:
    """
    An adapter class to manage and interact with individual MCP tools exposed by an MCP server.
    It adapts the MCP tool's interface for internal use within the agent framework.
    """

    def __init__(self, tool: MCPTool, client: FastMCPClient):
        """
        Initializes the MCPToolAdapter.

        Args:
            tool (MCPTool): The raw MCPTool object (definition) from the MCP server.
            client (FastMCPClient): An initialized FastMCPClient instance connected to the MCP server.
        """
        self.tool = tool
        self.client = client
        log.debug(f"Initialized MCPToolAdapter for tool: {self.tool.name}")


    @staticmethod
    async def create_mcp_client(mcp_config: Dict[str, Any]) -> FastMCPClient:
        """
        Creates and returns a FastMCPClient instance based on the provided MCP configuration.

        Args:
            mcp_config (Dict[str, Any]): A dictionary containing the MCP server configuration.
                                         Expected keys: "transport" ("stdio" or "streamable_http"),
                                         and transport-specific keys like "command", "args", "url", "headers".

        Returns:
            FastMCPClient: An initialized FastMCPClient instance.

        Raises:
            ValueError: If the MCP configuration is invalid or unsupported.
        """
        transport_type = mcp_config.get("transport")
        
        if transport_type == "stdio":
            command = mcp_config.get("command")
            args = mcp_config.get("args", [])
            if not command:
                raise ValueError("Command is required for stdio transport.")
            transport = StdioTransport(command=command, args=args)
            log.debug(f"Created StdioTransport for command: {command} {args}")

        elif transport_type == "streamable_http":
            url = mcp_config.get("url")
            headers = mcp_config.get("headers", None)
            if not url:
                raise ValueError("URL is required for streamable_http transport.")
            transport = StreamableHttpTransport(url=url, headers=headers)
            log.debug(f"Created StreamableHttpTransport for URL: {url}")

        else:
            raise ValueError(f"Unsupported MCP transport type: {transport_type}")
        
        return FastMCPClient(transport=transport)

    @staticmethod
    def get_ai_tool_schema(mcp_tool: MCPTool) -> Dict[str, Any]:
        """
        Converts an mcp.types.Tool object into an AI-compatible JSON schema format.

        Args:
            mcp_tool (MCPTool): The raw MCPTool object.

        Returns:
            Dict[str, Any]: The tool's schema in OpenAI's function tool format.
        """
        # Ensure inputSchema is a dictionary, as expected by OpenAI
        parameters_schema = mcp_tool.inputSchema if mcp_tool.inputSchema else {"type": "object", "properties": {}}
        
        return {
            "type": "function",
            "function": {
                "name": mcp_tool.name,
                "description": mcp_tool.description,
                "parameters": parameters_schema
            }
        }

    @staticmethod
    async def list_mcp_tools(
        client: FastMCPClient,
        return_adapter_objects: bool = False,
        return_callable_functions: bool = False
    ) -> Union[List[MCPTool], List['MCPToolAdapter'], List[Callable]]:
        """
        Lists all tools exposed by an MCP server via the provided client.

        Args:
            client (FastMCPClient): An initialized FastMCPClient instance.
            return_adapter_objects (bool): If True, returns a list of MCPToolAdapter instances.
            return_callable_functions (bool): If True, returns a list of callable Python functions
                                              that wrap the MCP tools. This takes precedence over
                                              `return_adapter_objects`.

        Returns:
            Union[List[MCPTool], List[MCPToolAdapter], List[Callable]]:
                A list of raw MCPTool objects, MCPToolAdapter instances, or callable functions.
        """
        try:
            async with client:
                tools = await client.list_tools()
            log.debug(f"Listed {len(tools)} tools from MCP client.")

            if return_callable_functions:
                callable_tools = []
                for t in tools:
                    adapter_instance = MCPToolAdapter(tool=t, client=client)
                    callable_tools.append(MCPToolAdapter.create_callable_wrapper(adapter_instance))
                return callable_tools

            elif return_adapter_objects:
                return [MCPToolAdapter(tool=t, client=client) for t in tools]

            else:
                return tools
        except Exception as e:
            log.error(f"Error listing tools from MCP client: {e}")
            return []

    @staticmethod
    def create_callable_wrapper(mcp_tool_adapter_instance: 'MCPToolAdapter') -> Callable:
        """
        Creates a callable (async) wrapper function for an MCP tool.
        This wrapper function can be invoked like a regular Python function,
        and it will internally call the MCP tool via the FastMCPClient.

        Args:
            mcp_tool_adapter_instance (MCPToolAdapter): An instance of MCPToolAdapter.

        Returns:
            Callable: An asynchronous function that wraps the MCP tool call.
        """
        tool_name = mcp_tool_adapter_instance.tool.name
        client = mcp_tool_adapter_instance.client
        tool_description = mcp_tool_adapter_instance.tool.description
        
        async def wrapper_function(**kwargs) -> str:
            """
            Wrapper for the MCP tool.
            Accepts arguments as keyword arguments and calls the MCP tool.
            """
            log.info(f"  [MCPToolAdapter] Calling MCP tool '{tool_name}' with arguments: {kwargs}")
            try:
                async with client:
                    mcp_response = await client.call_tool(name=tool_name, arguments=kwargs)
                
                if isinstance(mcp_response, list) and all(isinstance(item, Content) for item in mcp_response):
                    full_text_content = ""
                    for item in mcp_response:
                        if isinstance(item, TextContent) and item.text:
                            full_text_content += item.text + "\n"
                        elif isinstance(item, dict):
                            full_text_content += json.dumps(item) + "\n"
                        else:
                            full_text_content += str(item) + "\n"
                    return full_text_content.strip()

                elif isinstance(mcp_response, Content):
                    if isinstance(mcp_response, TextContent) and mcp_response.text:
                        return mcp_response.text
                    elif isinstance(mcp_response, dict):
                        return json.dumps(mcp_response)
                    else:
                        return str(mcp_response)

                else:
                    log.warning(f"  [MCPToolAdapter] Unexpected MCP tool response type for '{tool_name}': {type(mcp_response)}. Attempting JSON serialization.")
                    try:
                        return json.dumps(mcp_response)
                    except TypeError:
                        return str(mcp_response)

            except Exception as e:
                log.error(f"  [MCPToolAdapter] Error calling MCP tool '{tool_name}': {e}")
                return f"Error calling MCP tool '{tool_name}': {str(e)}"
        
        # Dynamically set __name__ and __doc__ for better introspection
        wrapper_function.__name__ = tool_name
        wrapper_function.__doc__ = tool_description

        return wrapper_function

