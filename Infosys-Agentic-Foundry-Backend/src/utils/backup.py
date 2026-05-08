import asyncio
import os
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from src.database.repositories import (
    ToolRepository, AgentRepository, RecycleToolRepository, ToolAgentMappingRepository, TagRepository, TagToolMappingRepository, TagAgentMappingRepository, RecycleAgentRepository, McpToolRepository, RecycleMcpToolRepository, ChatStateHistoryManagerRepository, WorkflowRepository, WorkflowRunRepository, WorkflowStepsRepository, ToolVersionRepository
)
from src.database.services import (
    ToolService, AgentService, AgentServiceUtils, ModelService, TagService, McpToolService, WorkflowService
)
from src.tools.tool_code_processor import ToolCodeProcessor
from src.utils.tool_file_manager import ToolFileManager
from src.config.constants import TableNames
import asyncpg
from src.config.constants import AgentType

def _sanitize_name(name: str) -> str:
    """Sanitize a string for safe folder creation."""
    if not name:
        return "Unnamed"
    safe = "".join(c for c in name if c.isalnum() or c in ("_", "-", " ")).strip()
    return safe.replace(" ", "_") or "Unnamed"

def serialize_dict(data_dict: Dict, exclude_keys: List[str] = None, tool_id_to_info_map: Dict[str, Dict] = None) -> Dict:
    """
    Generic serialization for dictionaries, filtering out unnecessary fields
    and converting datetime objects to ISO format strings.
    If tool_id_to_info_map is provided, replaces tools_id list with enriched tools list
    containing tool_id, tool_name, bound_version, and version information.
    
    Args:
        data_dict: Dictionary to serialize
        exclude_keys: List of keys to exclude from serialization
        tool_id_to_info_map: Optional mapping of tool_id -> {tool_name, version_count, versions}
        
    Returns:
        Dict: Serialized dictionary
    """
    if exclude_keys is None:
        exclude_keys = ["db_connection_name", "is_public", "status", "comments", "approved_at", "approved_by"]
    
    # Build tool_id -> bound_version mapping from tools_with_versions
    tool_bound_versions = {}
    if "tools_with_versions" in data_dict:
        for item in data_dict.get("tools_with_versions", []):
            if isinstance(item, dict):
                tool_bound_versions[item.get("tool_id")] = item.get("tool_version", "v1")
    
    serialized = {}
    for key, value in data_dict.items():
        if key not in exclude_keys:
            if key == "tools_id" and tool_id_to_info_map is not None:
                tool_ids = value if isinstance(value, list) else []
                enriched_tools = []
                for tool_id in tool_ids:
                    tool_info = tool_id_to_info_map.get(tool_id, {})
                    enriched_tool = {
                        "tool_id": tool_id,
                        "tool_name": tool_info.get("tool_name", "unknown"),
                        "bound_version": tool_bound_versions.get(tool_id, "v1"),
                        "version_count": tool_info.get("version_count", 0),
                        "versions": tool_info.get("versions", [])
                    }
                    enriched_tools.append(enriched_tool)
                serialized["tools"] = enriched_tools
            elif key == "tools_with_versions":
                # Skip this key as we've already processed it into the tools array
                continue
            elif isinstance(value, datetime):
                serialized[key] = value.isoformat()
            else:
                serialized[key] = value
    return serialized

def extract_tag_folder_name(tags: List[Dict]) -> str:
    """
    Extract the appropriate tag name for folder organization.
    Args:
        tags: List of tag dictionaries with 'tag_name' key
        
    Returns:
        str: The tag name to use for folder organization
    """
    if not tags or not isinstance(tags, list):
        return "General"
    tag_names = [tag.get("tag_name", "").strip() for tag in tags if tag.get("tag_name")]
    
    if not tag_names:
        return "General"
    if len(tag_names) == 1:
        return tag_names[0]
    
    non_general_tags = [tag for tag in tag_names if tag.lower() != "general"]
    
    if non_general_tags:
        return non_general_tags[0]
    else:
        return "General"

def format_code_with_black(raw_code: str) -> str:
    """
    Format Python code using Black formatter.
    
    Args:
        raw_code: Raw Python code string
        
    Returns:
        str: Formatted code, or original code if Black is unavailable or fails
    """
    try:
        import black
        mode = black.Mode(line_length=88)
        return black.format_str(raw_code, mode=mode)
    except (ImportError, Exception):
        return raw_code

async def extract_and_save_tool(tool_id: str, tool_service: ToolService, output_folder: str) -> Optional[Dict]:
    """
    Extract a tool from database, format its code, and save it to a file.
    
    Args:
        tool_id: The tool ID to extract
        tool_service: The tool service instance
        output_folder: Directory to save the tool code
        
    Returns:
        Dict: Tool dictionary if successful, None otherwise
    """
    tool_data = await tool_service.get_tool(tool_id=tool_id)
    if not tool_data or not isinstance(tool_data, list) or not tool_data:
        return None
    
    tool_dict = tool_data[0]
    tool_name = _sanitize_name(tool_dict.get("tool_name", tool_id))
    raw_code = tool_dict.get("code_snippet", "")
    
    formatted_code = format_code_with_black(raw_code)
    
    tool_code_path = os.path.join(output_folder, f"{tool_name}.py")
    with open(tool_code_path, "w", encoding="utf-8") as tf:
        tf.write(formatted_code)
    
    return tool_dict

def save_tool_with_config(tool_dict: Dict, root_folder: str, versions: List[Dict] = None):
    """
    Save a tool/validator with its config file, code file, and all versions.
    
    Args:
        tool_dict: Tool dictionary containing all tool information
        root_folder: Root folder where tool folder will be created
        versions: Optional list of version records from tool_versions_table
    """
    tool_id = tool_dict.get("tool_id")
    tool_name = _sanitize_name(tool_dict.get("tool_name", tool_id))
    
    tool_folder = os.path.join(root_folder, tool_name)
    os.makedirs(tool_folder, exist_ok=True)
    tool_config = serialize_dict(tool_dict, exclude_keys=["db_connection_name", "comments", "approved_at", "approved_by"])
    tool_config["code_file"] = f"{tool_name}.py"
    
    # Add versioning metadata to config
    if versions and len(versions) > 0:
        versions_metadata = []
        versions_folder = os.path.join(tool_folder, "versions")
        os.makedirs(versions_folder, exist_ok=True)
        
        for ver in versions:
            version_str = ver.get("version", "v1")
            version_code = ver.get("code_snippet", "")
            version_description = ver.get("tool_description", "")
            version_model = ver.get("model_name", "")
            version_updated_by = ver.get("updated_by", "")
            version_updated_date = ver.get("updated_date")
            version_created_at = ver.get("created_at")
            
            # Save version code file
            version_filename = f"{version_str}.py"
            version_file_path = os.path.join(versions_folder, version_filename)
            formatted_version_code = format_code_with_black(version_code) if version_code else ""
            with open(version_file_path, "w", encoding="utf-8") as vf:
                vf.write(formatted_version_code)
            
            # Build version metadata
            version_meta = {
                "version": version_str,
                "code_file": f"versions/{version_filename}",
                "tool_description": version_description,
                "model_name": version_model,
                "updated_by": version_updated_by
            }
            if version_updated_date:
                version_meta["updated_date"] = version_updated_date.isoformat() if isinstance(version_updated_date, datetime) else str(version_updated_date)
            if version_created_at:
                version_meta["created_at"] = version_created_at.isoformat() if isinstance(version_created_at, datetime) else str(version_created_at)
            
            versions_metadata.append(version_meta)
        
        tool_config["versions"] = versions_metadata
        tool_config["version_count"] = len(versions_metadata)
        print(f"    Saved {len(versions_metadata)} versions for tool: {tool_name}")
    else:
        tool_config["versions"] = []
        tool_config["version_count"] = 0

    config_path = os.path.join(tool_folder, "config.json")
    with open(config_path, "w", encoding="utf-8") as cf:
        json.dump(tool_config, cf, indent=2)

    raw_code = tool_dict.get("code_snippet", "")
    formatted_code = format_code_with_black(raw_code)
    
    tool_code_path = os.path.join(tool_folder, f"{tool_name}.py")
    with open(tool_code_path, "w", encoding="utf-8") as tcf:
        tcf.write(formatted_code)

async def extract_agent_and_tool_data(agent_id_list: list = None):
    """
    Extract agent configurations and tool data using AgentExporter functions
    If agent_id_list is None, extracts all agents from the database
    """

    # Create main database pool
    pool = await asyncpg.create_pool(
        host=os.getenv('POSTGRESQL_HOST', 'localhost'),
        database=os.getenv('DATABASE', 'agentic_workflow_as_service_database'),
        user=os.getenv('POSTGRESQL_USER', 'postgres'),
        password=os.getenv('POSTGRESQL_PASSWORD', 'postgres'),
        min_size=1,
        max_size=5
    )
    
    # Create separate login database pool
    login_pool = await asyncpg.create_pool(
        host=os.getenv('POSTGRESQL_HOST', 'localhost'),
        database=os.getenv('LOGIN_DB_NAME', 'login'),
        user=os.getenv('POSTGRESQL_USER', 'postgres'),
        password=os.getenv('POSTGRESQL_PASSWORD', 'postgres'),
        min_size=1,
        max_size=3
    )
    
    try:
        tool_repo = ToolRepository(pool, login_pool, TableNames.TOOL.value)
        agent_repo = AgentRepository(pool, login_pool, TableNames.AGENT.value)
        recycle_tool_repo = RecycleToolRepository(pool, login_pool, TableNames.RECYCLE_TOOL.value)
        tool_agent_mapping_repo = ToolAgentMappingRepository(pool, login_pool, TableNames.TOOL_AGENT_MAPPING.value)
        recycle_agent_repo = RecycleAgentRepository(pool, login_pool, TableNames.RECYCLE_AGENT.value)
        tag_repo = TagRepository(pool, login_pool, TableNames.TAG.value)
        tag_tool_mapping_repo = TagToolMappingRepository(pool, login_pool, TableNames.TAG_TOOL_MAPPING.value)
        tag_agent_mapping_repo = TagAgentMappingRepository(pool, login_pool, TableNames.TAG_AGENTIC_APP_MAPPING.value)
        mcp_tool_repo = McpToolRepository(pool, login_pool, TableNames.MCP_TOOL.value)
        recycle_mcp_tool_repo = RecycleMcpToolRepository(pool, login_pool, TableNames.RECYCLE_MCP_TOOL.value)
        chat_state_history_manager_repo = ChatStateHistoryManagerRepository(pool, login_pool, TableNames.AGENT_CHAT_STATE_HISTORY.value)
        workflow_repo = WorkflowRepository(pool, login_pool, TableNames.WORKFLOWS.value)
        workflow_run_repo = WorkflowRunRepository(pool, login_pool, TableNames.WORKFLOWS_RUN.value)
        workflow_steps_repo = WorkflowStepsRepository(pool, login_pool, TableNames.WORKFLOW_STEPS.value)
        tool_version_repo = ToolVersionRepository(pool, login_pool, TableNames.TOOL_VERSIONS.value)

        tag_service = TagService(
            tag_repo=tag_repo,
            tag_tool_mapping_repo=tag_tool_mapping_repo,
            tag_agent_mapping_repo=tag_agent_mapping_repo
        )

        model_service = ModelService(chat_state_history_manager=chat_state_history_manager_repo)
        tool_code_processor = ToolCodeProcessor()
        tool_file_manager = ToolFileManager(pool=pool)
        
        # Initialize McpToolService
        mcp_tool_service = McpToolService(
            mcp_tool_repo=mcp_tool_repo,
            recycle_mcp_tool_repo=recycle_mcp_tool_repo,
            tag_service=tag_service,
            tool_agent_mapping_repo=tool_agent_mapping_repo,
            agent_repo=agent_repo
        )
        
        tool_service = ToolService(
            tool_repo=tool_repo,
            recycle_tool_repo=recycle_tool_repo,
            tool_agent_mapping_repo=tool_agent_mapping_repo,
            tag_service=tag_service,
            tool_code_processor=tool_code_processor,
            agent_repo=agent_repo,
            model_service=model_service,
            mcp_tool_service=mcp_tool_service,
            tool_file_manager=tool_file_manager
        )
        
        agent_service_utils = AgentServiceUtils(
            agent_repo=agent_repo,
            recycle_agent_repo=recycle_agent_repo,
            tool_service=tool_service,
            tag_service=tag_service,
            model_service=model_service
        )
        agent_service = AgentService(agent_service_utils=agent_service_utils)

        if agent_id_list is None or len(agent_id_list) == 0:
            print("No agent IDs provided. Fetching all agents from database...")
            all_agents_data = await agent_repo.get_all_agent_records()
            if all_agents_data:
                agent_ids = [agent['agentic_application_id'] for agent in all_agents_data]
                print(f"Found {len(agent_ids)} agents in database")
            else:
                print("No agents found in database")
                return None
        else:
            agent_ids = agent_id_list
        
        # Step 1: Gather agent configurations directly from agent_service
        print(f"\nFetching configurations for {len(agent_ids)} agents...")
        agent_configs = {}
        for agent_id in agent_ids:
            agent_data = await agent_service.get_agent(agentic_application_id=agent_id)
            if agent_data and isinstance(agent_data, list) and agent_data:
                agent_dict = agent_data[0]
                agent_configs[agent_id] = agent_dict
        
        print(f"Retrieved configurations for {len(agent_configs)} agents")
        
        # Build tool_id -> info map with version information
        all_tools_for_mapping = await tool_repo.get_all_tool_records()
        tool_id_to_info_map = {}
        if all_tools_for_mapping:
            for tool in all_tools_for_mapping:
                tid = tool.get("tool_id", "")
                tname = tool.get("tool_name", "")
                if tid and tname:
                    # Fetch version info for this tool
                    versions = await tool_version_repo.get_all_versions(tid)
                    version_list = [v.get("version", "") for v in versions] if versions else []
                    
                    tool_id_to_info_map[tid] = {
                        "tool_name": tname,
                        "version_count": len(version_list),
                        "versions": version_list
                    }
        print(f"Built tool_id -> info mapping for {len(tool_id_to_info_map)} tools (with version info)")

        print("\nSerializing agent data and extracting tag information...")
        serialized_agents: Dict[str, Dict] = {}
        for agent_id in agent_ids:
            if agent_id in agent_configs:
                agent_dict = agent_configs[agent_id]
                serialized_agents[agent_id] = serialize_dict(agent_dict)
                tags = serialized_agents[agent_id].get('tags', [])
                tag_folder = extract_tag_folder_name(tags)
                print(f"  - Agent: {serialized_agents[agent_id].get('agentic_application_name', 'Unknown')} | Tag: {tag_folder}")
        
        # Build folder structure using temp directory (similar to Export_Agent)
        backup_root = tempfile.mkdtemp(prefix='IAF_Backup_')
        usecase_root = os.path.join(backup_root, "Agents")
        os.makedirs(usecase_root, exist_ok=True)
        
        for agent_id, agent_config in agent_configs.items():
            serialized_info = serialized_agents.get(agent_id, {})
            tags = serialized_info.get('tags', [])
            tag_name = extract_tag_folder_name(tags)
            tag_folder = _sanitize_name(tag_name)
            
            agent_name = _sanitize_name(agent_config.get("agentic_application_name", agent_id))
            print(f"Processing agent {agent_name} under tag {tag_folder}")
            
            tag_folder_path = os.path.join(usecase_root, tag_folder)
            agent_folder = os.path.join(tag_folder_path, agent_name)
            os.makedirs(agent_folder, exist_ok=True)

            # Check if this is a meta agent
            agent_type = agent_config.get("agentic_application_type", "")
            if AgentType(agent_type).is_meta_type:
                serialized_config = serialize_dict(agent_config)
                worker_agent_ids = serialized_config.pop("tools_id", [])
                ordered_config = {}
                for key, value in serialized_config.items():
                    ordered_config[key] = value
                    if key == "system_prompt":
                        ordered_config["worker_agents"] = worker_agent_ids
                
                worker_agents_data = []
                
                print(f"  Meta agent detected. Processing {len(worker_agent_ids)} worker agents...")
                
                for worker_id in worker_agent_ids:
                    worker_data = await agent_service.get_agent(agentic_application_id=worker_id)
                    if worker_data and isinstance(worker_data, list) and worker_data:
                        worker_dict = worker_data[0]
                        serialized_worker = serialize_dict(worker_dict, tool_id_to_info_map=tool_id_to_info_map)
                        worker_agents_data.append(serialized_worker)
                
                meta_config = {
                    "meta_agent": ordered_config,
                    "worker_agents": worker_agents_data
                }
                
                agent_config_path = os.path.join(agent_folder, "agent_config.json")
                with open(agent_config_path, "w", encoding="utf-8") as f:
                    json.dump(meta_config, f, indent=2)
            else:
                serialized_config = serialize_dict(agent_config, tool_id_to_info_map=tool_id_to_info_map)
                agent_config_path = os.path.join(agent_folder, "agent_config.json")
                with open(agent_config_path, "w", encoding="utf-8") as f:
                    json.dump(serialized_config, f, indent=2)

        print("\nExtraction completed successfully!")
        print(f"Domain-based agent folders created under: {usecase_root}")
        
        # Step 2: Extract all tools separately into a Tools folder
        # Separate validators from regular tools
        
        tools_root = os.path.join(backup_root, "Tools")
        validators_root = os.path.join(backup_root, "Validators")
        os.makedirs(tools_root, exist_ok=True)
        os.makedirs(validators_root, exist_ok=True)
        all_tools_data = await tool_repo.get_all_tool_records()
        if all_tools_data:
            regular_tools = []
            validator_tools = []
            
            for tool_dict in all_tools_data:
                tool_id = tool_dict.get("tool_id", "")
                # Validators have tool_id starting with '_validator'
                if tool_id.startswith("_validator"):
                    validator_tools.append(tool_dict)
                else:
                    regular_tools.append(tool_dict)
            
            print(f"\nFound {len(all_tools_data)} total tools in database:")
            print(f"  - Regular Tools: {len(regular_tools)}")
            print(f"  - Validators: {len(validator_tools)}")
            
            # Backup regular tools with their versions
            print("\nBacking up regular tools with versions...")
            for tool_dict in regular_tools:
                tool_id = tool_dict.get("tool_id", "")
                tool_name = tool_dict.get("tool_name", tool_id)
                # Fetch all versions for this tool from tool_versions_table
                versions = await tool_version_repo.get_all_versions(tool_id)
                if versions:
                    print(f"  - Tool '{tool_name}': {len(versions)} version(s)")
                save_tool_with_config(tool_dict, tools_root, versions=versions)
            
            print(f"Tools folder created at: {tools_root}")
            
            # Backup validators with their versions
            print("\nBacking up validators with versions...")
            for validator_dict in validator_tools:
                validator_id = validator_dict.get("tool_id", "")
                validator_name = validator_dict.get("tool_name", validator_id)
                # Fetch all versions for this validator
                versions = await tool_version_repo.get_all_versions(validator_id)
                if versions:
                    print(f"  - Validator '{validator_name}': {len(versions)} version(s)")
                save_tool_with_config(validator_dict, validators_root, versions=versions)
            
            print(f"Validators folder created at: {validators_root}")
        else:
            print("No tools found in database")
        
        # Step 3: Extract all MCP servers separately into an MCP_Servers folder
        mcp_servers_root = os.path.join(backup_root, "MCP_Servers")
        os.makedirs(mcp_servers_root, exist_ok=True)
        all_mcp_servers_data = await mcp_tool_service.get_all_mcp_tools()
        
        if all_mcp_servers_data:
            print(f"\nFound {len(all_mcp_servers_data)} MCP servers in database")
            for mcp_dict in all_mcp_servers_data:
                mcp_id = mcp_dict.get("tool_id")
                mcp_name = _sanitize_name(mcp_dict.get("tool_name", mcp_id))
                tags = mcp_dict.get('tags', [])
                tag_name = extract_tag_folder_name(tags)
                tag_folder = _sanitize_name(tag_name)
                print(f"  - MCP Server: {mcp_name} | Tag: {tag_folder}")
                tag_folder_path = os.path.join(mcp_servers_root, tag_folder)
                mcp_folder = os.path.join(tag_folder_path, mcp_name)
                os.makedirs(mcp_folder, exist_ok=True)
                mcp_config_data = mcp_dict.get("mcp_config", {})
                args = mcp_config_data.get("args", [])
                code_content = None
                if args and len(args) > 1 and args[0] == "-c":
                    code_content = args[1]
                elif args and len(args) == 1:
                    code_content = args[0]
                if code_content:
                    formatted_code = format_code_with_black(code_content)
                    code_file_path = os.path.join(mcp_folder, f"{mcp_name}.py")
                    with open(code_file_path, "w", encoding="utf-8") as code_file:
                        code_file.write(formatted_code)
                    mcp_config = serialize_dict(mcp_dict)
                    mcp_config["code_file"] = f"{mcp_name}.py"
                else:
                    mcp_config = serialize_dict(mcp_dict)
                
                config_path = os.path.join(mcp_folder, "mcp_config.json")
                with open(config_path, "w", encoding="utf-8") as cf:
                    json.dump(mcp_config, cf, indent=2)
            
            print(f"MCP Servers folder created at: {mcp_servers_root}")
        else:
            print("No MCP servers found in database")
        
        # Step 4: Extract all workflows separately into a Workflows folder
        workflows_root = os.path.join(backup_root, "Workflows")
        os.makedirs(workflows_root, exist_ok=True)
        all_workflows_data = await workflow_repo.get_all_workflows()
        
        if all_workflows_data:
            print(f"\nFound {len(all_workflows_data)} workflows in database")
            for workflow_dict in all_workflows_data:
                workflow_id = workflow_dict.get("workflow_id")
                workflow_name = _sanitize_name(workflow_dict.get("workflow_name", workflow_id))
                print(f"  - workflow: {workflow_name}")
                workflow_folder = os.path.join(workflows_root, workflow_name)
                os.makedirs(workflow_folder, exist_ok=True)
                workflow_definition = workflow_dict.get("workflow_definition", {})
                nodes = workflow_definition.get("nodes", [])
                agent_ids_in_workflow = []
                for node in nodes:
                    if node.get("node_type") == "agent":
                        config = node.get("config", {})
                        agent_id = config.get("agent_id")
                        if agent_id:
                            agent_ids_in_workflow.append(agent_id)
                workflow_agents_data = []
                if agent_ids_in_workflow:
                    print(f"    workflow contains {len(agent_ids_in_workflow)} agents. Fetching agent data...")
                    for agent_id in agent_ids_in_workflow:
                        agent_data = await agent_service.get_agent(agentic_application_id=agent_id)
                        if agent_data and isinstance(agent_data, list) and agent_data:
                            agent_dict = agent_data[0]
                            serialized_agent = serialize_dict(agent_dict, tool_id_to_info_map=tool_id_to_info_map)
                            workflow_agents_data.append(serialized_agent)
                
                workflow_config = serialize_dict(workflow_dict, exclude_keys=["db_connection_name", "comments"])
                complete_workflow_config = {
                    "workflow": workflow_config,
                    "agents": workflow_agents_data
                }
                
                config_path = os.path.join(workflow_folder, "workflow_config.json")
                with open(config_path, "w", encoding="utf-8") as cf:
                    json.dump(complete_workflow_config, cf, indent=2)
            
            print(f"workflows folder created at: {workflows_root}")
        else:
            print("No workflows found in database")
        
        # Return the backup root path
        return backup_root
    
    finally:
        await pool.close()
        await login_pool.close()

if __name__ == "__main__":
    if sys.platform.startswith('win'):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    agent_id_list = None  # Set to None to extract all agents from database
    
    print("Starting agent and tool extraction...")
    export_path = asyncio.run(extract_agent_and_tool_data(agent_id_list))
    print(f"\nExtraction complete. Data saved to: {export_path}") 