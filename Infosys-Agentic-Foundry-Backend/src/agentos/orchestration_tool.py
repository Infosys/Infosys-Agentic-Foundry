# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Orchestration Tool - LangChain tool that exposes the full SkillAgent pipeline.

This tool can be given to any IAF agent, allowing it to:
- Route queries to specialized skills
- Execute skill-based workflows
- Manage approvals
- Query enterprise context

It acts as a bridge between existing IAF agents and the AgentOS skill system.
"""

from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field

try:
    from langchain_core.tools import StructuredTool, BaseTool
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ============================================================================
# Tool Input Schemas
# ============================================================================

class InvokeSkillInput(BaseModel):
    """Input for invoking a skill."""
    query: str = Field(description="The user query or task to route to a skill.")
    skill_name: Optional[str] = Field(
        None,
        description="Optional: force a specific skill instead of auto-routing. "
                    "Use list_skills first to see available options."
    )


class ListSkillsInput(BaseModel):
    """Input for listing available skills."""
    category: Optional[str] = Field(
        None,
        description="Optional: filter by category (operations, platform, general, etc.)"
    )


class GetEnterpriseContextInput(BaseModel):
    """Input for fetching enterprise context."""
    skill_name: Optional[str] = Field(
        None,
        description="Optional: get context specific to a skill."
    )
    include_policies: bool = Field(
        True,
        description="Whether to include policy documents in the context."
    )


class CheckApprovalInput(BaseModel):
    """Input for checking if a tool call needs approval."""
    tool_name: str = Field(description="The tool to check approval for.")
    tool_args: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments that will be passed to the tool."
    )
    skill_name: str = Field(description="The current skill name.")


class ApprovalActionInput(BaseModel):
    """Input for approving or rejecting a pending action."""
    request_id: str = Field(description="The approval request ID.")
    action: str = Field(description="Either 'approve' or 'reject'.")
    note: Optional[str] = Field(None, description="Optional note for the decision.")


class GetPendingApprovalsInput(BaseModel):
    """Input for listing pending approvals."""
    pass


# ============================================================================
# Tool Factory
# ============================================================================

def create_skill_orchestration_tools(
    skill_agent,
    user_email: str = "",
    session_id: str = "",
    agent_id: str = "",
) -> List["BaseTool"]:
    """
    Create LangChain tools for skill orchestration.
    
    Returns a list of tools that can be added to any IAF agent,
    giving it skill-based routing and execution capabilities.
    
    Args:
        skill_agent: A SkillAgent instance.
        user_email: Current user's email.
        session_id: Current session ID.
        agent_id: Current agent ID.
        
    Returns:
        List of LangChain StructuredTool objects.
    """
    if not LANGCHAIN_AVAILABLE:
        raise ImportError("LangChain is required. pip install langchain-core")

    tools = []

    # ---- 1. Invoke Skill Tool ----
    import asyncio

    def invoke_skill(query: str, skill_name: Optional[str] = None) -> str:
        """Route and execute a query through the skill-based agent system."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        skill_agent.run(
                            query=query,
                            user_email=user_email,
                            session_id=session_id,
                            agent_id=agent_id,
                            skill_name=skill_name,
                        )
                    ).result()
            else:
                result = loop.run_until_complete(
                    skill_agent.run(
                        query=query,
                        user_email=user_email,
                        session_id=session_id,
                        agent_id=agent_id,
                        skill_name=skill_name,
                    )
                )
            
            response = result.get("response", "No response")
            skill_used = result.get("routing", {}).get("skill", "unknown")
            method = result.get("routing", {}).get("method", "unknown")
            return f"[Skill: {skill_used} (via {method})]\n\n{response}"
        except Exception as e:
            return f"Error invoking skill: {str(e)}"

    tools.append(StructuredTool.from_function(
        func=invoke_skill,
        name="invoke_skill",
        description=(
            "Route a user query to a specialized skill agent and return the result. "
            "Use this when the query requires domain-specific expertise (e.g., invoice lookup, "
            "HR policies, IT helpdesk). Optionally specify a skill_name to bypass auto-routing."
        ),
        args_schema=InvokeSkillInput,
    ))

    # ---- 2. List Skills Tool ----
    def list_skills(category: Optional[str] = None) -> str:
        """List all available skills."""
        skills = skill_agent.list_skills()
        if category:
            skills = [s for s in skills if s.get("category") == category]
        
        if not skills:
            return "No skills available."
        
        lines = ["Available skills:\n"]
        for s in skills:
            status = "✅" if s.get("status") == "active" else "⏸️"
            lines.append(f"{status} **{s['name']}**: {s.get('description', 'No description')}")
            if s.get("keywords"):
                lines.append(f"   Keywords: {', '.join(s['keywords'])}")
        return "\n".join(lines)

    tools.append(StructuredTool.from_function(
        func=list_skills,
        name="list_skills",
        description="List all available agent skills with their descriptions and keywords.",
        args_schema=ListSkillsInput,
    ))

    # ---- 3. Enterprise Context Tool ----
    def get_enterprise_context(
        skill_name: Optional[str] = None,
        include_policies: bool = True,
    ) -> str:
        """Fetch enterprise context for background knowledge."""
        if not skill_agent.enterprise_context:
            return "Enterprise context is not configured."
        
        return skill_agent.enterprise_context.build_context_for_skill(
            skill_name=skill_name or "general",
            user_email=user_email,
            include_policies=include_policies,
        )

    tools.append(StructuredTool.from_function(
        func=get_enterprise_context,
        name="get_enterprise_context",
        description=(
            "Fetch enterprise context (company info, terminology, policies, business rules). "
            "Use this when you need background knowledge about the organization."
        ),
        args_schema=GetEnterpriseContextInput,
    ))

    # ---- 4. Check Approval Tool ----
    def check_approval(
        tool_name: str,
        tool_args: Dict[str, Any] = {},
        skill_name: str = "general",
    ) -> str:
        """Check if a tool call requires human approval."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        skill_agent.run_with_approval_check(
                            tool_name=tool_name,
                            tool_args=tool_args,
                            skill_name=skill_name,
                            agent_id=agent_id,
                            session_id=session_id,
                            user_email=user_email,
                        )
                    ).result()
            else:
                result = loop.run_until_complete(
                    skill_agent.run_with_approval_check(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        skill_name=skill_name,
                        agent_id=agent_id,
                        session_id=session_id,
                        user_email=user_email,
                    )
                )

            if result.get("approval_required"):
                return (
                    f"⏸️ APPROVAL REQUIRED\n"
                    f"Request ID: {result['request_id']}\n"
                    f"Reason: {result['reason']}\n"
                    f"Urgency: {result['urgency']}\n"
                    f"The action '{tool_name}' has been paused and requires human approval."
                )
            return f"✅ No approval needed for '{tool_name}'. Proceed with execution."
        except Exception as e:
            return f"Error checking approval: {str(e)}"

    tools.append(StructuredTool.from_function(
        func=check_approval,
        name="check_approval",
        description=(
            "Check if a tool call requires human-in-the-loop approval before execution. "
            "Use this before performing sensitive actions like deletions, payments, or updates."
        ),
        args_schema=CheckApprovalInput,
    ))

    # ---- 5. Manage Approval Tool ----
    def manage_approval(
        request_id: str,
        action: str = "approve",
        note: Optional[str] = None,
    ) -> str:
        """Approve or reject a pending approval request."""
        if action.lower() == "approve":
            result = skill_agent.approval_manager.approve(
                request_id=request_id,
                approved_by=user_email,
                note=note,
            )
        elif action.lower() == "reject":
            result = skill_agent.approval_manager.reject(
                request_id=request_id,
                rejected_by=user_email,
                note=note,
            )
        else:
            return f"Invalid action '{action}'. Use 'approve' or 'reject'."
        
        if result:
            return f"✅ Request {request_id} has been {result.status}."
        return f"❌ Request {request_id} not found or already resolved."

    tools.append(StructuredTool.from_function(
        func=manage_approval,
        name="manage_approval",
        description="Approve or reject a pending HITL approval request.",
        args_schema=ApprovalActionInput,
    ))

    # ---- 6. List Pending Approvals Tool ----
    def get_pending_approvals() -> str:
        """List all pending approval requests."""
        pending = skill_agent.approval_manager.get_pending(user_email=user_email)
        if not pending:
            return "No pending approvals."
        
        lines = [f"**{len(pending)} pending approval(s):**\n"]
        for req in pending:
            lines.append(
                f"- **{req.request_id[:12]}...** | Tool: `{req.tool_name}` | "
                f"Skill: {req.skill_name} | Urgency: {req.urgency}\n"
                f"  Reason: {req.reason}\n"
                f"  Created: {req.created_at}"
            )
        return "\n".join(lines)

    tools.append(StructuredTool.from_function(
        func=get_pending_approvals,
        name="get_pending_approvals",
        description="List all pending human-in-the-loop approval requests.",
        args_schema=GetPendingApprovalsInput,
    ))

    log.info(f"Created {len(tools)} skill orchestration tools for agent_id={agent_id}")
    return tools


# ============================================================================
# Code Executor Tool Factory (Phase 5)
# ============================================================================

def create_code_executor_orchestration_tools(
    executor=None,
    tenant_id: str = "default",
) -> List["BaseTool"]:
    """
    Create LangChain tools for code execution capabilities.

    These can be combined with skill orchestration tools to give any agent
    the ability to generate and execute code from natural-language goals.

    Args:
        executor: Optional SmartCodeExecutor instance. If None, creates one.
        tenant_id: Tenant ID for workspace isolation.

    Returns:
        List of LangChain StructuredTool objects (execute_task, execute_code, etc.)
    """
    if not LANGCHAIN_AVAILABLE:
        raise ImportError("LangChain is required. pip install langchain-core")

    from src.agentos.code_executor.tool import create_code_executor_tools
    from src.agentos.code_executor.executor import SmartCodeExecutor

    if executor is None:
        executor = SmartCodeExecutor()

    return create_code_executor_tools(executor=executor, tenant_id=tenant_id)
