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
from src.database.services import ToolService, AgentService, ModelService, PipelineService
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
                    "created_on": datetime.now(timezone.utc).replace(tzinfo=None)
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
            
            agent_data = {
                "agentic_application_name": agent["agentic_application_name"],
                "agentic_application_description": agent["agentic_application_description"],
                "agentic_application_workflow_description": agent["agentic_application_workflow_description"],
                "agentic_application_type": agent.get("agentic_application_type"),
                "model_name": agent.get("model_name", default_model),
                "system_prompt": agent["system_prompt"],
                "tools_id": tools_id,
                "created_by": "system",
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


async def _ensure_pipeline_tools_exist(tool_service: ToolService, tool_names: list, all_tools: list):
    """Ensure specific tools exist in the DB, creating them from sample_data if missing.
    
    This is used to guarantee pipeline-dependent tools are always present
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
            log.warning(f"Pipeline dependency tool '{tool_name}' not found in sample_data.json")
            continue

        tool_data = {
            "tool_id": str(uuid.uuid4()),
            "tool_name": tool_def["tool_name"],
            "tool_description": tool_def["tool_description"],
            "code_snippet": tool_def["code_snippet"],
            "model_name": tool_def.get("model_name", default_model),
            "created_by": "system",
            "created_on": datetime.now(timezone.utc).replace(tzinfo=None)
        }

        if await tool_service.tool_repo.save_tool_record(tool_data):
            await tool_service.tool_repo.approve_tool(tool_id=tool_data["tool_id"], approved_by="system")
            file_result = await tool_file_manager.create_tool_file(tool_data)
            if file_result.get("success"):
                log.info(f"Pipeline dep tool '{tool_name}' created (file: {file_result.get('file_path')})")
            else:
                log.warning(f"Pipeline dep tool '{tool_name}' saved but file creation failed")
        else:
            log.error(f"Failed to save pipeline dep tool '{tool_name}'")


async def _ensure_pipeline_agent_exists(agent_service: AgentService, agent_name: str, all_agents: list):
    """Ensure a specific agent exists in the DB, creating it from sample_data if missing.
    
    This is used to guarantee pipeline-dependent agents are always present
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
        log.warning(f"Pipeline dependency agent '{agent_name}' not found in sample_data.json")
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
        log.info(f"Pipeline dep agent '{agent_name}' created")
    else:
        log.error(f"Failed to create pipeline dep agent '{agent_name}'")


async def insert_sample_pipelines(pipeline_service: PipelineService):
    """Insert sample pipelines from sample_data.json into database.
    
    Pipelines marked with ``always_onboard = True`` and their specific
    dependencies (tools + agent) are onboarded regardless of ENABLE_ONBOARDING.
    Other pipelines follow the ENABLE_ONBOARDING flag.
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

    pipelines = data.get("pipelines", [])
    if not pipelines:
        log.info("No sample pipelines configured. Skipping pipeline insertion.")
        return True

    all_tools = data.get("tools", [])
    all_agents = data.get("agents", [])
    agent_service = pipeline_service.agent_service
    tool_service = agent_service.tool_service
    inserted, skipped, failed = 0, 0, 0

    # Fetch existing pipeline names once before the loop
    existing_pipelines = await pipeline_service.get_all_pipelines()
    existing_names = {p.get("pipeline_name") for p in existing_pipelines}

    for pipeline in pipelines:
        try:
            pipeline_name = pipeline["pipeline_name"]

            # Only always_onboard pipelines bypass ENABLE_ONBOARDING
            if not ENABLE_ONBOARDING and not pipeline.get("always_onboard", False):
                skipped += 1
                continue

            if pipeline_name in existing_names:
                skipped += 1
                continue

            # --- Ensure pipeline dependencies (tools & agent) exist ---
            import copy
            pipeline_def = copy.deepcopy(pipeline["pipeline_definition"])

            for node in pipeline_def.get("nodes", []):
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
                        await _ensure_pipeline_tools_exist(
                            tool_service, agent_def.get("tool_names", []), all_tools
                        )
                        # 2) Ensure the agent itself exists
                        await _ensure_pipeline_agent_exists(
                            agent_service, agent_name, all_agents
                        )

            # Resolve agent_name -> agent_id in agent nodes
            for node in pipeline_def.get("nodes", []):
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
                            log.warning(f"Agent '{agent_name}' not found for pipeline '{pipeline_name}'. Skipping.")
                            failed += 1
                            continue

            result = await pipeline_service.create_pipeline(
                pipeline_name=pipeline_name,
                pipeline_description=pipeline.get("pipeline_description", ""),
                pipeline_definition=pipeline_def,
                created_by="system"
            )
            if result.get("is_created"):
                inserted += 1
            else:
                failed += 1
                log.warning(f"Pipeline '{pipeline_name}' creation failed: {result.get('message')}")
        except Exception as e:
            failed += 1
            log.error(f"Failed to insert pipeline '{pipeline.get('pipeline_name', 'unknown')}': {e}")

    if failed > 0:
        log.warning(f"Sample pipelines: {inserted} inserted, {skipped} already exist, {failed} failed")
    elif inserted > 0:
        log.info(f"Sample pipelines: {inserted} inserted, {skipped} already exist")
    elif skipped > 0:
        log.info(f"Sample pipelines: All {skipped} already exist")
