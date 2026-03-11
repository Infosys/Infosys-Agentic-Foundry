# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import json
from datetime import datetime, timezone
from src.database.repositories import (
    ToolRepository, McpToolRepository, AgentRepository,
    TagToolMappingRepository, TagAgentMappingRepository, TagRepository
)
from telemetry_wrapper import logger as log
from dotenv import load_dotenv

load_dotenv()


async def load_exported_data(
    tool_repo: ToolRepository,
    mcp_tool_repo: McpToolRepository,
    agent_repo: AgentRepository,
    tag_repo: TagRepository,
    tag_tool_mapping_repo: TagToolMappingRepository,
    tag_agent_mapping_repo: TagAgentMappingRepository,
):
    """
    Reads the exported config files (agent_config.py, tools_config.py,
    worker_agents_config.py) and inserts all data into the database using the
    *original* repository objects.  This avoids duplicating table schemas.

    Missing columns that are not present in the export files are filled with
    sensible defaults:
        department_name  -> 'General'
        is_public        -> True
        created_on       -> current UTC time
        updated_on       -> current UTC time
        status           -> 'approved'

    Order of operations:
        1. Regular tools  (from tools_config)
        2. MCP tools      (from tools_config, prefixed mcp_file_/mcp_url_/mcp_module_)
        3. Worker agents  (from worker_agents_config)
        4. Agents         (from agent_config)
        5. Tag-tool mappings
        6. Tag-agent mappings (agents + worker agents)
    """
    from tools_config import tools_data
    from agent_config import agent_data
    from worker_agents_config import worker_agents

    tools_data: dict = tools_data
    agent_data: dict = agent_data
    worker_agents: dict = worker_agents

    now = datetime.now(timezone.utc)
    mcp_prefixes = ("mcp_file_", "mcp_url_", "mcp_module_")

    # ── 1 & 2. Insert tools (regular + MCP) ──────────────────────────────
    for tool_id, tool_info in tools_data.items():
        if tool_info is None:
            continue
        try:
            if tool_id.startswith(mcp_prefixes):
                # MCP tool
                mcp_config = tool_info.get("mcp_config", {})
                if isinstance(mcp_config, str):
                    mcp_config = json.loads(mcp_config)

                mcp_data = {
                    "tool_id": tool_info.get("tool_id", tool_id),
                    "tool_name": tool_info.get("tool_name"),
                    "tool_description": tool_info.get("tool_description", ""),
                    "mcp_config": json.dumps(mcp_config),
                    "is_public": True,
                    "status": "approved",
                    "comments": None,
                    "approved_at": now.replace(tzinfo=None),
                    "approved_by": "system",
                    "created_by": tool_info.get("created_by", ""),
                    "created_on": now.replace(tzinfo=None),
                    "updated_on": now.replace(tzinfo=None),
                    "department_name": "General",
                }
                await mcp_tool_repo.save_mcp_tool_record(mcp_data)
                log.info(f"Loaded MCP tool: {mcp_data['tool_name']}")
            else:
                # Regular tool — resolve code_snippet from file if needed
                code_snippet = tool_info.get("code_snippet", "")
                if code_snippet and not _looks_like_code(code_snippet):
                    # It's a relative path like 'tools_codes/my_tool.py'
                    if os.path.exists(code_snippet):
                        with open(code_snippet, "r", encoding="utf-8") as f:
                            code_snippet = f.read()
                    else:
                        log.warning(f"Tool code file not found: {code_snippet}")

                tool_data = {
                    "tool_id": tool_info.get("tool_id", tool_id),
                    "tool_name": tool_info.get("tool_name"),
                    "tool_description": tool_info.get("tool_description", ""),
                    "code_snippet": code_snippet,
                    "model_name": tool_info.get("model_name", ""),
                    "created_by": tool_info.get("created_by", ""),
                    "created_on": now,
                    "department_name": "General",
                    "is_public": True,
                }
                await tool_repo.save_tool_record(tool_data)
                log.info(f"Loaded tool: {tool_data['tool_name']}")
        except Exception as e:
            log.error(f"Error loading tool '{tool_id}': {e}")

    # ── 3. Insert worker agents ──────────────────────────────────────────
    if worker_agents:
        for agent_id, agent_info in worker_agents.items():
            if agent_info is None:
                continue
            try:
                await _insert_agent(agent_repo, agent_info, agent_id, now)
                log.info(f"Loaded worker agent: {agent_info.get('agentic_application_name')}")
            except Exception as e:
                log.error(f"Error loading worker agent '{agent_id}': {e}")

    # ── 4. Insert agents ─────────────────────────────────────────────────
    for agent_id, agent_info in agent_data.items():
        if agent_info is None:
            continue
        try:
            await _insert_agent(agent_repo, agent_info, agent_id, now)
            log.info(f"Loaded agent: {agent_info.get('agentic_application_name')}")
        except Exception as e:
            log.error(f"Error loading agent '{agent_id}': {e}")

    # ── 5. Tag-tool mappings ──────────────────────────────────────────────
    for tool_id, tool_info in tools_data.items():
        if tool_info is None:
            continue
        tags = tool_info.get("tags", [])
        for tag in tags:
            tag_name = tag.get("tag_name")
            if not tag_name:
                continue
            try:
                tag_record = await tag_repo.get_tag_record(tag_name=tag_name)
                if tag_record:
                    await tag_tool_mapping_repo.assign_tag_to_tool_record(
                        tag_id=tag_record["tag_id"],
                        tool_id=tool_info.get("tool_id", tool_id),
                    )
                else:
                    log.warning(f"Tag '{tag_name}' not found in DB, skipping tool mapping.")
            except Exception as e:
                log.error(f"Error mapping tag '{tag_name}' to tool '{tool_id}': {e}")

    # ── 6. Tag-agent mappings (agents + worker agents) ────────────────────
    all_agents = {}
    all_agents.update(agent_data or {})
    all_agents.update(worker_agents or {})

    for agent_id, agent_info in all_agents.items():
        if agent_info is None:
            continue
        tags = agent_info.get("tags", [])
        for tag in tags:
            tag_name = tag.get("tag_name")
            if not tag_name:
                continue
            try:
                tag_record = await tag_repo.get_tag_record(tag_name=tag_name)
                if tag_record:
                    await tag_agent_mapping_repo.assign_tag_to_agent_record(
                        tag_id=tag_record["tag_id"],
                        agentic_application_id=agent_info.get(
                            "agentic_application_id", agent_id
                        ),
                    )
                else:
                    log.warning(f"Tag '{tag_name}' not found in DB, skipping agent mapping.")
            except Exception as e:
                log.error(f"Error mapping tag '{tag_name}' to agent '{agent_id}': {e}")

    log.info("load_exported_data: All exported data loaded successfully.")


# ── Private helpers ───────────────────────────────────────────────────────

async def _insert_agent(agent_repo: AgentRepository, agent_info: dict, agent_id: str, now: datetime):
    """Build the data dict expected by AgentRepository.save_agent_record and insert."""
    system_prompt = agent_info.get("system_prompt", {})
    if not isinstance(system_prompt, str):
        system_prompt = json.dumps(system_prompt)

    tools_id = agent_info.get("tools_id", [])
    if not isinstance(tools_id, str):
        tools_id = json.dumps(tools_id)

    validation_criteria = agent_info.get("validation_criteria", [])
    if not isinstance(validation_criteria, str):
        validation_criteria = json.dumps(validation_criteria)

    record = {
        "agentic_application_id": agent_info.get("agentic_application_id", agent_id),
        "agentic_application_name": agent_info.get("agentic_application_name"),
        "agentic_application_description": agent_info.get("agentic_application_description", ""),
        "agentic_application_workflow_description": agent_info.get("agentic_application_workflow_description", ""),
        "agentic_application_type": agent_info.get("agentic_application_type", ""),
        "model_name": agent_info.get("model_name", ""),
        "system_prompt": system_prompt,
        "tools_id": tools_id,
        "created_by": agent_info.get("created_by", ""),
        "department_name": "General",
        "created_on": now,
        "updated_on": now,
        "validation_criteria": validation_criteria,
        "welcome_message": agent_info.get("welcome_message", "Hello, how can I help you?"),
        "is_public": True,
    }
    await agent_repo.save_agent_record(record)


def _looks_like_code(text: str) -> bool:
    """Heuristic: return True if the text looks like actual Python code rather than a file path."""
    stripped = text.strip()
    return (
        stripped.startswith("def ")
        or stripped.startswith("async def ")
        or stripped.startswith("import ")
        or stripped.startswith("from ")
        or stripped.startswith("#")
        or "\n" in stripped
    )
