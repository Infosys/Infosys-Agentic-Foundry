"""
Sample data insertion module for InfyAgentFramework.

This module reads sample tools and agents from src/onboard/sample_data.json
and inserts them into the database on server startup.

To add new tools or agents, edit src/onboard/sample_data.json - no code changes needed.
"""
import os
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from telemetry_wrapper import logger as log
from src.utils.tool_file_manager import ToolFileManager
from src.database.services import ToolService, AgentService, ModelService, WorkflowService, McpToolService
from src.config.constants import AgentType

ENABLE_ONBOARDING = os.getenv("ENABLE_ONBOARDING", "true").lower() == "true"

def get_sample_data_path():
    """Get the path to sample_data.json file."""
    return Path(__file__).parent / "sample_data.json"

async def insert_sample_tools(tool_service: ToolService):
    """Insert sample tools from sample_data.json into database."""
    
    if not ENABLE_ONBOARDING:
        log.info("Default onboarding disabled.")
        return False
    
    json_path = get_sample_data_path()
    if not json_path.exists():
        log.info("Sample data file not found. Skipping sample data insertion.")
        return False
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log.error(f"Failed to load sample_data.json: {e}")
        return False
    
    tools = data.get("tools", [])
    agents = data.get("agents", [])

    if not tools and not agents:
        log.info("Sample data file is empty. Skipping sample data insertion.")
        return False
    
    if not tools:
        log.info("No sample tools configured. Skipping tool insertion.")
        return True

    default_model = tool_service.model_service.default_model_name
    tool_file_manager = ToolFileManager()
    inserted, skipped, failed = 0, 0, 0
    
    for tool in tools:
        try:
            existing = await tool_service.tool_repo.get_tool_record(tool_name=tool["tool_name"])
            
            if existing:
                skipped += 1
            else:
                tool_data = {
                    "tool_id": str(uuid.uuid4()),
                    "tool_name": tool["tool_name"],
                    "tool_description": tool["tool_description"],
                    "code_snippet": tool["code_snippet"],
                    "model_name": tool.get("model_name", default_model),
                    "created_by": "system",
                    "created_on": datetime.now(timezone.utc).replace(tzinfo=None),
                    "department_name": tool.get("department_name", "General")
                }
                
                if await tool_service.tool_repo.save_tool_record(tool_data):
                    await tool_service.tool_repo.approve_tool(tool_id=tool_data["tool_id"], approved_by="system")
                    file_creation_result = await tool_file_manager.create_tool_file(tool_data)
                    if file_creation_result.get("success"):
                        log.info(f"Tool file created at: {file_creation_result.get('file_path')}")
                    else:
                        log.warning(f"Failed to create tool file for '{tool_data['tool_name']}': {file_creation_result.get('message')}")
                    inserted += 1
                else:
                    failed += 1
        except Exception as e:
            failed += 1
            log.error(f"Failed to insert tool '{tool.get('tool_name', 'unknown')}': {e}")
    
    if failed > 0:
        log.warning(f"Sample tools: {inserted} inserted, {skipped} already exist, {failed} failed")
    elif inserted > 0:
        log.info(f"Sample tools: {inserted} inserted, {skipped} already exist")
    elif skipped > 0:
        log.info(f"Sample tools: All {skipped} already exist")
    
    return True

async def insert_sample_agents(agent_service: AgentService):
    """Insert sample agents from sample_data.json into database."""
    
    if not ENABLE_ONBOARDING:
        return False
    
    json_path = get_sample_data_path()
    if not json_path.exists():
        return False
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False
    
    agents = data.get("agents", [])
    if not agents:
        if data.get("tools", []):
            log.info("No sample agents configured. Skipping agent insertion.")
        return
    
    tool_service = agent_service.tool_service
    general_tag = await agent_service.tag_service.get_tag(tag_name="General")
    tag_ids = [general_tag["tag_id"]] if general_tag else []
    default_model = tool_service.model_service.default_model_name
    inserted, skipped, failed = 0, 0, 0

    for agent in agents:
        try:
            existing = await agent_service.agent_repo.get_agent_record(
                agentic_application_name=agent["agentic_application_name"]
            )
            if existing:
                skipped += 1
                continue
            
            agent_type = agent.get("agentic_application_type", "")
            tools_id = []
            
            # For meta_agent/planner_meta_agent
            for name in agent.get("tool_names", []):
                if AgentType(agent_type).is_meta_type:
                    worker_agents = await agent_service.agent_repo.get_agent_record(
                        agentic_application_name=name
                    )
                    if worker_agents:
                        tools_id.append(worker_agents[0]["agentic_application_id"])
                        continue
                tool_records = await tool_service.tool_repo.get_tool_record(tool_name=name)
                if tool_records:
                    tools_id.append(tool_records[0]["tool_id"])
            
            # Resolve MCP tool names to IDs
            mcp_tool_service = agent_service.mcp_tool_service
            for mcp_name in agent.get("mcp_tool_names", []):
                mcp_records = await mcp_tool_service.mcp_tool_repo.get_mcp_tool_record(tool_name=mcp_name)
                if mcp_records:
                    tools_id.append(mcp_records[0]["tool_id"])
                else:
                    log.warning(f"MCP tool '{mcp_name}' not found for agent '{agent.get('agentic_application_name', 'unknown')}'")
            
            agent_data = {
                "agentic_application_name": agent["agentic_application_name"],
                "agentic_application_description": agent["agentic_application_description"],
                "agentic_application_workflow_description": agent["agentic_application_workflow_description"],
                "agentic_application_type": agent.get("agentic_application_type"),
                "model_name": agent.get("model_name", default_model),
                "system_prompt": agent["system_prompt"],
                "tools_id": tools_id,
                "created_by": "system",
                "department_name": agent.get("department_name", "General"),
                "validation_criteria": agent.get("validation_criteria", []),
                "welcome_message": agent.get("welcome_message", "Hello, how can I help you?"),
                "tag_ids": tag_ids
            }
            
            result = await agent_service._save_agent_data(agent_data)
            if result.get("is_created"):
                await agent_service.agent_repo.approve_agent(
                    agentic_application_id=result["agentic_application_id"],
                    approved_by="system"
                )
                inserted += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            log.error(f"Failed to insert agent '{agent.get('agentic_application_name', 'unknown')}': {e}")

    if failed > 0:
        log.warning(f"Sample agents: {inserted} inserted, {skipped} already exist, {failed} failed")
    elif inserted > 0:
        log.info(f"Sample agents: {inserted} inserted, {skipped} already exist")
    elif skipped > 0:
        log.info(f"Sample agents: All {skipped} already exist")


async def _ensure_workflow_tools_exist(tool_service: ToolService, tool_names: list, all_tools: list):
    """Ensure specific tools exist in the DB, creating them from sample_data if missing.
    
    This is used to guarantee workflow-dependent tools are always present
    regardless of ENABLE_ONBOARDING.
    """
    default_model = tool_service.model_service.default_model_name
    tool_file_manager = ToolFileManager()

    for tool_name in tool_names:
        existing = await tool_service.tool_repo.get_tool_record(tool_name=tool_name)
        if existing:
            continue

        # Find tool definition in sample_data
        tool_def = next((t for t in all_tools if t["tool_name"] == tool_name), None)
        if not tool_def:
            log.warning(f"Workflow dependency tool '{tool_name}' not found in sample_data.json")
            continue

        tool_data = {
            "tool_id": str(uuid.uuid4()),
            "tool_name": tool_def["tool_name"],
            "tool_description": tool_def["tool_description"],
            "code_snippet": tool_def["code_snippet"],
            "model_name": tool_def.get("model_name", default_model),
            "created_by": "system",
            "created_on": datetime.now(timezone.utc).replace(tzinfo=None),
            "department_name": tool_def.get("department_name", "General")
        }

        if await tool_service.tool_repo.save_tool_record(tool_data):
            await tool_service.tool_repo.approve_tool(tool_id=tool_data["tool_id"], approved_by="system")
            file_result = await tool_file_manager.create_tool_file(tool_data)
            if file_result.get("success"):
                log.info(f"Workflow dep tool '{tool_name}' created (file: {file_result.get('file_path')})")
            else:
                log.warning(f"Workflow dep tool '{tool_name}' saved but file creation failed")
        else:
            log.error(f"Failed to save workflow dep tool '{tool_name}'")


async def _ensure_workflow_agent_exists(agent_service: AgentService, agent_name: str, all_agents: list):
    """Ensure a specific agent exists in the DB, creating it from sample_data if missing.
    
    This is used to guarantee workflow-dependent agents are always present
    regardless of ENABLE_ONBOARDING.
    """
    existing = await agent_service.agent_repo.get_agent_record(
        agentic_application_name=agent_name
    )
    if existing:
        return

    # Find agent definition in sample_data
    agent_def = next((a for a in all_agents if a["agentic_application_name"] == agent_name), None)
    if not agent_def:
        log.warning(f"Workflow dependency agent '{agent_name}' not found in sample_data.json")
        return

    tool_service = agent_service.tool_service
    default_model = tool_service.model_service.default_model_name

    # Resolve tool names to IDs
    tools_id = []
    agent_type = agent_def.get("agentic_application_type", "")
    for name in agent_def.get("tool_names", []):
        if AgentType(agent_type).is_meta_type:
            worker = await agent_service.agent_repo.get_agent_record(agentic_application_name=name)
            if worker:
                tools_id.append(worker[0]["agentic_application_id"])
                continue
        tool_records = await tool_service.tool_repo.get_tool_record(tool_name=name)
        if tool_records:
            tools_id.append(tool_records[0]["tool_id"])

    # Resolve MCP tool names to IDs
    mcp_tool_service = agent_service.mcp_tool_service
    for mcp_name in agent_def.get("mcp_tool_names", []):
        mcp_records = await mcp_tool_service.mcp_tool_repo.get_mcp_tool_record(tool_name=mcp_name)
        if mcp_records:
            tools_id.append(mcp_records[0]["tool_id"])
        else:
            log.warning(f"MCP tool '{mcp_name}' not found for workflow agent '{agent_name}'")

    general_tag = await agent_service.tag_service.get_tag(tag_name="General")
    tag_ids = [general_tag["tag_id"]] if general_tag else []

    agent_data = {
        "agentic_application_name": agent_def["agentic_application_name"],
        "agentic_application_description": agent_def["agentic_application_description"],
        "agentic_application_workflow_description": agent_def["agentic_application_workflow_description"],
        "agentic_application_type": agent_def.get("agentic_application_type"),
        "model_name": agent_def.get("model_name", default_model),
        "system_prompt": agent_def["system_prompt"],
        "tools_id": tools_id,
        "created_by": "system",
        "department_name": agent_def.get("department_name", "General"),
        "validation_criteria": agent_def.get("validation_criteria", []),
        "welcome_message": agent_def.get("welcome_message", "Hello, how can I help you?"),
        "tag_ids": tag_ids
    }

    result = await agent_service._save_agent_data(agent_data)
    if result.get("is_created"):
        await agent_service.agent_repo.approve_agent(
            agentic_application_id=result["agentic_application_id"],
            approved_by="system"
        )
        log.info(f"Workflow dep agent '{agent_name}' created")
    else:
        log.error(f"Failed to create workflow dep agent '{agent_name}'")


async def insert_sample_workflows(workflow_service: WorkflowService):
    """Insert sample workflows from sample_data.json into database.
    
    Workflows marked with ``always_onboard = True`` and their specific
    dependencies (tools + agent) are onboarded regardless of ENABLE_ONBOARDING.
    Other workflows follow the ENABLE_ONBOARDING flag.
    """

    json_path = get_sample_data_path()
    if not json_path.exists():
        return False
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log.error(f"Failed to load sample_data.json: {e}")
        return False

    workflows = data.get("workflows", [])
    if not workflows:
        log.info("No sample workflows configured. Skipping workflow insertion.")
        return True

    all_tools = data.get("tools", [])
    all_agents = data.get("agents", [])
    agent_service = workflow_service.agent_service
    tool_service = agent_service.tool_service
    inserted, skipped, failed = 0, 0, 0

    # Fetch existing workflow names once before the loop
    existing_workflows = await workflow_service.get_all_workflows()
    existing_names = {p.get("workflow_name") for p in existing_workflows}

    for workflow in workflows:
        try:
            workflow_name = workflow["workflow_name"]

            # Only always_onboard workflows bypass ENABLE_ONBOARDING
            if not ENABLE_ONBOARDING and not workflow.get("always_onboard", False):
                skipped += 1
                continue

            if workflow_name in existing_names:
                skipped += 1
                continue

            # --- Ensure workflow dependencies (tools & agent) exist ---
            import copy
            workflow_def = copy.deepcopy(workflow["workflow_definition"])

            for node in workflow_def.get("nodes", []):
                if node.get("node_type") == "agent":
                    config = node.get("config", {})
                    agent_name = config.get("agent_name")
                    if not agent_name:
                        continue

                    # Find the agent definition to discover its tool dependencies
                    agent_def = next(
                        (a for a in all_agents if a["agentic_application_name"] == agent_name), None
                    )
                    if agent_def:
                        # 1) Ensure the agent's tools exist first
                        await _ensure_workflow_tools_exist(
                            tool_service, agent_def.get("tool_names", []), all_tools
                        )
                        # 2) Ensure the agent itself exists
                        await _ensure_workflow_agent_exists(
                            agent_service, agent_name, all_agents
                        )

            # Resolve agent_name -> agent_id in agent nodes
            for node in workflow_def.get("nodes", []):
                if node.get("node_type") == "agent":
                    config = node.get("config", {})
                    agent_name = config.pop("agent_name", None)
                    if agent_name and not config.get("agent_id"):
                        agent_records = await agent_service.agent_repo.get_agent_record(
                            agentic_application_name=agent_name
                        )
                        if agent_records:
                            config["agent_id"] = agent_records[0]["agentic_application_id"]
                        else:
                            log.warning(f"Agent '{agent_name}' not found for workflow '{workflow_name}'. Skipping.")
                            failed += 1
                            continue

            result = await workflow_service.create_workflow(
                workflow_name=workflow_name,
                workflow_description=workflow.get("workflow_description", ""),
                workflow_definition=workflow_def,
                created_by="system",
                department_name=workflow.get("department_name", "General"),
                is_public=True
            )
            if result.get("is_created"):
                inserted += 1
            else:
                failed += 1
                log.warning(f"Workflow '{workflow_name}' creation failed: {result.get('message')}")
        except Exception as e:
            failed += 1
            log.error(f"Failed to insert workflow '{workflow.get('workflow_name', 'unknown')}': {e}")

    if failed > 0:
        log.warning(f"Sample workflows: {inserted} inserted, {skipped} already exist, {failed} failed")
    elif inserted > 0:
        log.info(f"Sample workflows: {inserted} inserted, {skipped} already exist")
    elif skipped > 0:
        log.info(f"Sample workflows: All {skipped} already exist")


async def insert_sample_mcp_tools(mcp_tool_service: McpToolService):
    """Insert sample MCP tools from sample_data.json into database.
    
    This function loads MCP server definitions from sample_data.json and inserts
    them into the mcp_tool_table. Currently only supports 'file' type (local) MCPs
    as remote URL-based MCPs require internal network access.
    """
    
    if not ENABLE_ONBOARDING:
        log.info("Default onboarding disabled. Skipping MCP tool insertion.")
        return False
    
    json_path = get_sample_data_path()
    if not json_path.exists():
        log.info("Sample data file not found. Skipping MCP tool insertion.")
        return False
    
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log.error(f"Failed to load sample_data.json: {e}")
        return False
    
    mcp_tools = data.get("mcp_tools", [])
    
    if not mcp_tools:
        log.info("No sample MCP tools configured. Skipping MCP tool insertion.")
        return True
    
    inserted, skipped, failed = 0, 0, 0
    
    for mcp_tool in mcp_tools:
        try:
            tool_name = mcp_tool.get("tool_name")
            mcp_type = mcp_tool.get("mcp_type", "file")
            
            # Check if MCP tool already exists
            existing = await mcp_tool_service.mcp_tool_repo.get_mcp_tool_record(tool_name=tool_name)
            
            if existing:
                skipped += 1
                continue
            
            # Create MCP tool based on type
            if mcp_type == "file":
                result = await mcp_tool_service.create_mcp_tool(
                    tool_name=tool_name,
                    tool_description=mcp_tool.get("tool_description", ""),
                    mcp_type="file",
                    code_content=mcp_tool.get("code_content", ""),
                    created_by="system",
                    department_name=mcp_tool.get("department_name", "General")
                )
            elif mcp_type == "url":
                result = await mcp_tool_service.create_mcp_tool(
                    tool_name=tool_name,
                    tool_description=mcp_tool.get("tool_description", ""),
                    mcp_type="url",
                    mcp_url=mcp_tool.get("mcp_url", ""),
                    headers=mcp_tool.get("headers"),
                    created_by="system",
                    department_name=mcp_tool.get("department_name", "General")
                )
            elif mcp_type == "module":
                result = await mcp_tool_service.create_mcp_tool(
                    tool_name=tool_name,
                    tool_description=mcp_tool.get("tool_description", ""),
                    mcp_type="module",
                    mcp_module_name=mcp_tool.get("mcp_module_name", ""),
                    created_by="system",
                    mcp_command=mcp_tool.get("mcp_command", ""),
                    department_name=mcp_tool.get("department_name", "General")
                )
            else:
                log.warning(f"Unsupported MCP type '{mcp_type}' for tool '{tool_name}'")
                failed += 1
                continue
            
            if result.get("is_created"):
                # Auto-approve the MCP tool
                tool_id = result.get("tool_id")
                await mcp_tool_service.approve_mcp_tool(
                    tool_id=tool_id,
                    approved_by="system",
                    comments="Auto-approved sample MCP tool"
                )
                inserted += 1
                log.info(f"Sample MCP tool '{tool_name}' inserted and approved")
            else:
                failed += 1
                log.warning(f"Failed to create MCP tool '{tool_name}': {result.get('message')}")
                
        except Exception as e:
            failed += 1
            log.error(f"Failed to insert MCP tool '{mcp_tool.get('tool_name', 'unknown')}': {e}")
    
    if failed > 0:
        log.warning(f"Sample MCP tools: {inserted} inserted, {skipped} already exist, {failed} failed")
    elif inserted > 0:
        log.info(f"Sample MCP tools: {inserted} inserted, {skipped} already exist")
    elif skipped > 0:
        log.info(f"Sample MCP tools: All {skipped} already exist")
    
    return True
