"""
IAF-Agent-Skills: Skill-based routing and generic agent framework.

Built on top of IAF-Agent-OS, this package provides:
- SkillRouter: Match user queries to skills using _index.yaml
- SkillLoader: Load and parse SKILL.md files with YAML frontmatter
- SkillAgent: Generic ReAct agent that uses skills from filesystem
- Execution Engines: Workflow, Parallel, and Supervisor patterns

Usage:
    from iaf_agent_skills import SkillAgent, SkillRouter, SkillLoader
    from agent_os import SafeKernel
    
    kernel = SafeKernel(data_root="./data", tenant_id="company", agent_id="assistant")
    agent = SkillAgent(kernel=kernel, skills_path="./skills")
    response = agent.run("log my day")  # Auto-routes to dilo skill
"""

__version__ = "1.2.0"

from .router import SkillRouter
from .loader import SkillLoader, Skill
from .agent import SkillAgent
from .memory import AgentMemory, MemoryEntry, OptimisticLockError
from . import memory_md
from .automation import AutomationEngine, AutomationRunResult
from .execution import (
    ExecutionMode, 
    Step, 
    StepResult, 
    WorkflowEngine, 
    ParallelEngine, 
    SupervisorEngine,
    get_execution_mode
)
from .session_store import (
    AgentStateSnapshot,
    RedisSessionStore,
    get_session_store,
    init_session_store,
)

__all__ = [
    "SkillRouter",
    "SkillLoader", 
    "Skill",
    "SkillAgent",
    "AutomationEngine",
    "AutomationRunResult",
    "AgentMemory",
    "MemoryEntry",
    "OptimisticLockError",
    "ExecutionMode",
    "Step",
    "StepResult",
    "WorkflowEngine",
    "ParallelEngine",
    "SupervisorEngine",
    "get_execution_mode",
    "AgentStateSnapshot",
    "RedisSessionStore",
    "get_session_store",
    "init_session_store",
    "__version__",
]
