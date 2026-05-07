# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
IAF Cleanup Service
===================
Provides functionality to:
1. Fetch items (agents, tools, MCP tools, workflows) matching cleanup criteria
2. Send notification emails to users about items to be deleted
3. Execute deletion with proper unbinding and related data cleanup
4. Generate reports for audit purposes

Cleanup Criteria:
- Items with test/demo/sample in name (anywhere in name)
- Orphan items (not bound to anything)
"""

import os
import re
import json
import asyncpg
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict
from dataclasses import dataclass, field

from src.config.application_config import app_config
from src.config.constants import DatabaseName
from telemetry_wrapper import logger as log

try:
    import win32com.client
    OUTLOOK_AVAILABLE = True
except ImportError:
    OUTLOOK_AVAILABLE = False
    log.warning("win32com not available - email functionality will be disabled")


# ============================================================================
# CONFIGURATION
# ============================================================================

# ============================================================================
# TESTING MODE - Set to True during testing, False for production
# When True: All emails will be sent to TEST_EMAIL_RECIPIENT only
# ============================================================================
TESTING_MODE = False  # SET TO FALSE FOR PRODUCTION
TEST_EMAIL_RECIPIENT = "pallavi.sharma25@infosys.com"  # Only used when TESTING_MODE = True
TEST_EMAIL_SENDER = "pallavi.sharma25@infosys.com"  # Only used when TESTING_MODE = True
# ============================================================================

# ============================================================================
# EXCLUDED EMAILS - Emails to skip during cleanup notification (for testing)
# Add emails here that should NOT receive cleanup notification emails
# ============================================================================
EXCLUDED_EMAILS = [
    # Add emails to exclude here, e.g.: "user@example.com"
]
# ============================================================================


def get_backup_repo_url() -> str:
    """
    Construct the backup repository URL with SERVER_NAME appended.
    Base URL: https://github.com/Infosys-Generative-AI/IAF-Agents/tree/Backup
    Returns URL in format: https://github.com/Infosys-Generative-AI/IAF-Agents/tree/Backup/{SERVER_NAME}
    """
    SERVER_NAME = os.getenv('SERVER_NAME', 'default')
    return f"https://github.com/Infosys-Generative-AI/IAF-Agents/tree/Backup/{SERVER_NAME}"


# Test/Demo/Sample patterns - matches as whole words or with common separators
# Using word boundaries to avoid false positives like "latest" matching "test"
TEST_PATTERNS = [
    r'(?:^|[_\s\-])test(?:[_\s\-]|$)', r'(?:^|[_\s\-])demo(?:[_\s\-]|$)', 
    r'(?:^|[_\s\-])sample(?:[_\s\-]|$)', r'(?:^|[_\s\-])example(?:[_\s\-]|$)', 
    r'(?:^|[_\s\-])dummy(?:[_\s\-]|$)', r'(?:^|[_\s\-])trial(?:[_\s\-]|$)', 
    r'(?:^|[_\s\-])mock(?:[_\s\-]|$)', r'(?:^|[_\s\-])fake(?:[_\s\-]|$)',
    r'(?:^|[_\s\-])tmp(?:[_\s\-]|$)', r'(?:^|[_\s\-])temp(?:[_\s\-]|$)',
    r'^untitled', r'^foo(?:[_\s\-]|$)', r'^bar(?:[_\s\-]|$)', r'^hello(?:[_\s\-]|$)', r'^world(?:[_\s\-]|$)',
    r'^experiment', r'^playground', r'^scratch', r'^sandbox',
]

# Report folders
CLEANUP_REPORTS_FOLDER = "cleanup_reports"
DELETION_REPORTS_FOLDER = "deletion_reports"


def matches_test_pattern(name: str) -> bool:
    """Check if name matches any test/demo/sample pattern"""
    name_lower = (name or '').lower().strip()
    for pattern in TEST_PATTERNS:
        if re.search(pattern, name_lower):
            return True
    return False


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class CleanupItem:
    """Represents an item to be cleaned up"""
    id: str
    name: str
    item_type: str  # 'agent', 'tool', 'mcp_tool', 'workflow'
    sub_type: str = ""
    created_by: str = ""
    created_on: Optional[datetime] = None
    is_orphan: bool = False
    is_test_pattern: bool = False
    reason: str = ""
    bound_to: str = ""
    # Version-level tracking for tools
    all_versions: List[str] = field(default_factory=list)  # All versions: ['v1', 'v2', 'v3', 'v4', 'v5']
    bound_versions: List[str] = field(default_factory=list)  # Bound to agents: ['v1', 'v3', 'v5']
    orphan_versions: List[str] = field(default_factory=list)  # Not bound: ['v2', 'v4']
    is_partial_orphan: bool = False  # True if some versions orphan, some bound
    delete_all_versions: bool = True  # True = delete entire tool, False = delete only orphan versions


@dataclass
class CleanupSummary:
    """Summary of cleanup operation"""
    agents: List[CleanupItem] = field(default_factory=list)
    tools: List[CleanupItem] = field(default_factory=list)
    mcp_tools: List[CleanupItem] = field(default_factory=list)
    workflows: List[CleanupItem] = field(default_factory=list)
    
    @property
    def total_count(self) -> int:
        return len(self.agents) + len(self.tools) + len(self.mcp_tools) + len(self.workflows)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agents": [vars(item) for item in self.agents],
            "tools": [vars(item) for item in self.tools],
            "mcp_tools": [vars(item) for item in self.mcp_tools],
            "workflows": [vars(item) for item in self.workflows],
            "total_count": self.total_count,
            "summary": {
                "agents": len(self.agents),
                "tools": len(self.tools),
                "mcp_tools": len(self.mcp_tools),
                "workflows": len(self.workflows)
            }
        }


@dataclass
class DeletionResult:
    """Result of deletion operation"""
    deleted_agents: int = 0
    deleted_tools: int = 0
    deleted_mcp_tools: int = 0
    deleted_workflows: int = 0
    unbinding_operations: Dict[str, int] = field(default_factory=dict)
    related_cleanup: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    report_path: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "deleted": {
                "agents": self.deleted_agents,
                "tools": self.deleted_tools,
                "mcp_tools": self.deleted_mcp_tools,
                "workflows": self.deleted_workflows,
                "total": self.deleted_agents + self.deleted_tools + self.deleted_mcp_tools + self.deleted_workflows
            },
            "unbinding_operations": self.unbinding_operations,
            "related_cleanup": self.related_cleanup,
            "errors": self.errors,
            "report_path": self.report_path
        }


# ============================================================================
# CLEANUP SERVICE
# ============================================================================

class CleanupService:
    """
    Service for cleaning up test/demo and orphan items from IAF database.
    """
    
    def __init__(self):
        self.db_config = app_config.postgres_db
        self.conn: Optional[asyncpg.Connection] = None
        self.feedback_conn: Optional[asyncpg.Connection] = None
        self.evaluation_conn: Optional[asyncpg.Connection] = None
        self.outlook = None
        
        # Get base path for reports
        self.base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.cleanup_reports_path = os.path.join(self.base_path, CLEANUP_REPORTS_FOLDER)
        self.deletion_reports_path = os.path.join(self.base_path, DELETION_REPORTS_FOLDER)
        
        # Path to onboarded_tools folder for file deletion
        self.onboarded_tools_path = Path(self.base_path) / "onboarded_tools"
        
        # Ensure folders exist
        os.makedirs(self.cleanup_reports_path, exist_ok=True)
        os.makedirs(self.deletion_reports_path, exist_ok=True)
        
        # Deletion records for report
        self.deletion_records: List[Dict] = []
        self.unbind_records: List[Dict] = []
        
        # Load existing deletion records from previous report (for persistence)
        self._load_existing_deletion_records()
        
        # Stats
        self.stats = {
            "agents": {"found": 0, "deleted": 0, "errors": 0},
            "tools": {"found": 0, "deleted": 0, "errors": 0},
            "workflows": {"found": 0, "deleted": 0, "errors": 0},
            "mcp_tools": {"found": 0, "deleted": 0, "errors": 0},
            "unbinding": {
                "tools_from_agents": 0,
                "agents_from_meta": 0,
                "agents_from_workflows": 0,
                "mcp_from_agents": 0
            },
            "related_cleanup": {
                "feedback_records": 0,
                "evaluation_records": 0,
                "ltm_tables": 0
            }
        }
    
    def _load_existing_deletion_records(self):
        """Load existing deletion records from previous report file for persistence"""
        try:
            # Find existing deletion report
            existing_reports = [f for f in os.listdir(self.deletion_reports_path) 
                              if f.startswith("DELETION_REPORT_") and f.endswith(".xlsx")]
            
            if existing_reports:
                # Sort to get the latest one
                existing_reports.sort(reverse=True)
                latest_report = os.path.join(self.deletion_reports_path, existing_reports[0])
                
                # Read existing records
                try:
                    df = pd.read_excel(latest_report, sheet_name='Deleted Items')
                    self.deletion_records = df.to_dict('records')
                    log.info(f"Loaded {len(self.deletion_records)} existing deletion records from {existing_reports[0]}")
                except Exception as e:
                    log.warning(f"Could not read Deleted Items sheet: {e}")
                
                # Read existing unbind records if they exist
                try:
                    df_unbind = pd.read_excel(latest_report, sheet_name='Unbinding Operations')
                    self.unbind_records = df_unbind.to_dict('records')
                    log.info(f"Loaded {len(self.unbind_records)} existing unbind records")
                except:
                    pass  # Unbinding sheet may not exist
                    
        except Exception as e:
            log.warning(f"Could not load existing deletion records: {e}")
    
    # ========================================================================
    # DATABASE CONNECTION
    # ========================================================================
    
    async def connect(self) -> bool:
        """Connect to all databases"""
        try:
            # Main database
            main_url = self.db_config.connection_string(DatabaseName.MAIN)
            self.conn = await asyncpg.connect(main_url, timeout=30)
            log.info(f"Connected to main database: {DatabaseName.MAIN.db_name}")
            
            # Feedback learning database
            try:
                feedback_url = self.db_config.connection_string(DatabaseName.FEEDBACK_LEARNING)
                self.feedback_conn = await asyncpg.connect(feedback_url, timeout=30)
                log.info(f"Connected to feedback database: {DatabaseName.FEEDBACK_LEARNING.db_name}")
            except Exception as e:
                log.warning(f"Could not connect to feedback database: {e}")
                self.feedback_conn = None
            
            # Evaluation logs database
            try:
                eval_url = self.db_config.connection_string(DatabaseName.EVALUATION_LOGS)
                self.evaluation_conn = await asyncpg.connect(eval_url, timeout=30)
                log.info(f"Connected to evaluation database: {DatabaseName.EVALUATION_LOGS.db_name}")
            except Exception as e:
                log.warning(f"Could not connect to evaluation database: {e}")
                self.evaluation_conn = None
            
            return True
            
        except Exception as e:
            log.error(f"Failed to connect to databases: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from all databases"""
        if self.conn:
            await self.conn.close()
            self.conn = None
        if self.feedback_conn:
            await self.feedback_conn.close()
            self.feedback_conn = None
        if self.evaluation_conn:
            await self.evaluation_conn.close()
            self.evaluation_conn = None
        log.info("Disconnected from all databases")
    
    async def ensure_connection(self):
        """Ensure connection is alive, reconnect if needed"""
        try:
            if self.conn is None or self.conn.is_closed():
                await self.connect()
            else:
                await self.conn.execute("SELECT 1")
        except Exception:
            await self.reconnect()
    
    async def reconnect(self):
        """Reconnect to databases"""
        log.info("Reconnecting to databases...")
        await self.disconnect()
        await self.connect()
    
    # ========================================================================
    # FETCH CLEANUP ITEMS
    # ========================================================================
    
    async def fetch_cleanup_items(self) -> CleanupSummary:
        """
        Fetch all items that match cleanup criteria:
        - Test/demo/sample in name
        - Orphan items (not bound to anything)
        
        Returns:
            CleanupSummary with all items to be cleaned up
        """
        if not self.conn:
            await self.connect()
        
        summary = CleanupSummary()
        
        # Fetch all data
        all_agents = await self.conn.fetch('''
            SELECT agentic_application_id as id, agentic_application_name as name,
                   agentic_application_type as type, created_by, created_on, tools_id
            FROM agent_table
        ''')
        
        all_tools = await self.conn.fetch('''
            SELECT tool_id as id, tool_name as name, created_by, created_on
            FROM tool_table
        ''')
        
        try:
            all_workflows = await self.conn.fetch('''
                SELECT workflow_id as id, workflow_name as name, created_by, 
                       created_at as created_on, workflow_definition
                FROM workflows_table
            ''')
        except:
            all_workflows = []
        
        try:
            all_mcp_tools = await self.conn.fetch('''
                SELECT tool_id as id, tool_name as name, created_by, created_on
                FROM mcp_tool_table
            ''')
        except:
            all_mcp_tools = []
        
        # Get tool-agent mappings WITH version info
        mappings = await self.conn.fetch('SELECT tool_id, agentic_application_id, tool_version FROM tool_agent_mapping_table')
        
        # Fetch all tool versions from tool_versions_table
        try:
            all_tool_versions = await self.conn.fetch('SELECT tool_id, version FROM tool_versions_table')
        except:
            all_tool_versions = []
        
        # Build lookup maps
        tool_to_agents = defaultdict(list)
        agent_to_tools = defaultdict(list)
        # Version-level mappings: {(tool_id, version): [agent_ids]}
        tool_version_to_agents = defaultdict(list)
        for m in mappings:
            tool_to_agents[m['tool_id']].append(m['agentic_application_id'])
            agent_to_tools[m['agentic_application_id']].append(m['tool_id'])
            # Track which version is bound to which agents
            version = m.get('tool_version') or 'v1'
            tool_version_to_agents[(m['tool_id'], version)].append(m['agentic_application_id'])
        
        # Build tool -> all versions mapping
        tool_all_versions_map = defaultdict(list)
        for tv in all_tool_versions:
            tool_all_versions_map[tv['tool_id']].append(tv['version'])
        
        agent_names = {a['id']: a['name'] for a in all_agents}
        tool_names = {t['id']: t['name'] for t in all_tools}
        
        # Build MCP tool to agent mappings
        mcp_tool_to_agents = defaultdict(list)
        for m in mappings:
            if str(m['tool_id']).startswith('mcp_'):
                mcp_tool_to_agents[m['tool_id']].append(m['agentic_application_id'])
        
        # Build meta agent references
        agent_used_by_meta = defaultdict(list)
        for a in all_agents:
            if a['type'] in ('meta_agent', 'multi_agent', 'planner_meta_agent'):
                for w in (a['tools_id'] or []):
                    if isinstance(w, str):
                        agent_used_by_meta[w].append(a['name'])
        
        # Build workflow references
        agent_in_workflow = defaultdict(list)
        for p in all_workflows:
            defn = p['workflow_definition']
            if isinstance(defn, str):
                try:
                    defn = json.loads(defn)
                except:
                    defn = {}
            if isinstance(defn, dict):
                for node in defn.get('nodes', []):
                    if isinstance(node, dict) and node.get('node_type') == 'agent':
                        config = node.get('config', {})
                        if isinstance(config, dict) and config.get('agent_id'):
                            agent_id = config['agent_id']
                            agent_in_workflow[agent_id].append(p['name'])
        
        # ================================================================
        # Find AGENTS to cleanup
        # ================================================================
        for a in all_agents:
            # Skip items created by system
            if (a['created_by'] or '').lower() == 'system':
                continue
                
            is_test = matches_test_pattern(a['name'])
            tool_ids = agent_to_tools.get(a['id'], [])
            is_orphan = (len(tool_ids) == 0 and 
                        a['id'] not in agent_used_by_meta and 
                        a['id'] not in agent_in_workflow)
            
            if is_test or is_orphan:
                bindings = []
                if tool_ids:
                    bindings.extend([f"Tool: {tool_names.get(t, t)}" for t in tool_ids])
                if a['id'] in agent_used_by_meta:
                    bindings.extend([f"Meta: {n}" for n in agent_used_by_meta[a['id']]])
                if a['id'] in agent_in_workflow:
                    bindings.extend([f"workflow: {n}" for n in agent_in_workflow[a['id']]])
                
                reason_parts = []
                if is_test:
                    reason_parts.append('Test/Demo/Sample name')
                if is_orphan:
                    reason_parts.append('Orphan')
                
                summary.agents.append(CleanupItem(
                    id=str(a['id']),
                    name=a['name'],
                    item_type='agent',
                    sub_type=a['type'] or '',
                    created_by=a['created_by'] or '',
                    created_on=a['created_on'],
                    is_orphan=is_orphan,
                    is_test_pattern=is_test,
                    reason='; '.join(reason_parts),
                    bound_to=', '.join(bindings) if bindings else 'None'
                ))
        
        # ================================================================
        # Find TOOLS to cleanup (with version-level orphan detection)
        # ================================================================
        for t in all_tools:
            # Skip items created by system
            if (t['created_by'] or '').lower() == 'system':
                continue
            
            tool_id = t['id']
            is_test = matches_test_pattern(t['name'])
            
            # Get all versions for this tool (default to ['v1'] if no versions found)
            all_versions = tool_all_versions_map.get(tool_id, ['v1'])
            if not all_versions:
                all_versions = ['v1']
            
            # Find which versions are bound to agents
            bound_versions = []
            orphan_versions = []
            version_agent_bindings = {}  # {version: [agent_names]}
            
            for version in all_versions:
                agents_for_version = tool_version_to_agents.get((tool_id, version), [])
                if agents_for_version:
                    bound_versions.append(version)
                    version_agent_bindings[version] = [agent_names.get(a, a) for a in agents_for_version]
                else:
                    orphan_versions.append(version)
            
            # Determine cleanup action based on scenario
            # Scenario 1: Test/Demo/Sample name → Delete entire tool regardless of bindings
            # Scenario 2: All versions orphan → Delete entire tool
            # Scenario 3: Some versions orphan, some bound → Delete only orphan versions (partial cleanup)
            # Scenario 4: No versions orphan → Tool fully bound, skip
            
            is_full_orphan = len(bound_versions) == 0  # All versions are orphan
            is_partial_orphan = len(orphan_versions) > 0 and len(bound_versions) > 0  # Some orphan, some bound
            
            # Only process if it's test pattern OR has some orphan versions
            if is_test or is_full_orphan or is_partial_orphan:
                # Build human-readable bindings string
                bindings = []
                for version, agents in version_agent_bindings.items():
                    for agent in agents:
                        bindings.append(f"Agent: {agent} ({version})")
                
                # Determine reason and action
                reason_parts = []
                delete_all = True
                
                if is_test:
                    reason_parts.append('Test/Demo/Sample name')
                    delete_all = True  # Always delete entire tool for test patterns
                elif is_full_orphan:
                    reason_parts.append('Orphan (all versions unbound)')
                    delete_all = True  # Delete entire tool if all versions orphan
                elif is_partial_orphan:
                    reason_parts.append(f'Partial orphan: versions {orphan_versions} unbound')
                    delete_all = False  # Only delete orphan versions
                
                summary.tools.append(CleanupItem(
                    id=str(tool_id),
                    name=t['name'],
                    item_type='tool',
                    created_by=t['created_by'] or '',
                    created_on=t['created_on'],
                    is_orphan=is_full_orphan,
                    is_test_pattern=is_test,
                    reason='; '.join(reason_parts),
                    bound_to=', '.join(bindings) if bindings else 'None',
                    # Version-level tracking
                    all_versions=all_versions,
                    bound_versions=bound_versions,
                    orphan_versions=orphan_versions,
                    is_partial_orphan=is_partial_orphan,
                    delete_all_versions=delete_all
                ))
        
        # ================================================================
        # Find workflows to cleanup
        # ================================================================
        for p in all_workflows:
            # Skip items created by system
            if (p['created_by'] or '').lower() == 'system':
                continue
                
            is_test = matches_test_pattern(p['name'])
            
            defn = p['workflow_definition']
            if isinstance(defn, str):
                try:
                    defn = json.loads(defn)
                except:
                    defn = {}
            
            agent_ids_in_workflow = []
            agent_bindings = []
            if isinstance(defn, dict):
                for node in defn.get('nodes', []):
                    if isinstance(node, dict) and node.get('node_type') == 'agent':
                        config = node.get('config', {})
                        if isinstance(config, dict) and config.get('agent_id'):
                            agent_id = config['agent_id']
                            agent_ids_in_workflow.append(agent_id)
                            agent_bindings.append(f"Agent: {agent_names.get(agent_id, agent_id)}")
            
            is_orphan = len(agent_ids_in_workflow) == 0
            
            if is_test or is_orphan:
                reason_parts = []
                if is_test:
                    reason_parts.append('Test/Demo/Sample name')
                if is_orphan:
                    reason_parts.append('Orphan (no agents)')
                
                summary.workflows.append(CleanupItem(
                    id=str(p['id']),
                    name=p['name'],
                    item_type='workflow',
                    created_by=p['created_by'] or '',
                    created_on=p['created_on'],
                    is_orphan=is_orphan,
                    is_test_pattern=is_test,
                    reason='; '.join(reason_parts),
                    bound_to=', '.join(agent_bindings) if agent_bindings else 'None'
                ))
        
        # ================================================================
        # Find MCP TOOLS to cleanup
        # ================================================================
        for m in all_mcp_tools:
            # Skip items created by system
            if (m['created_by'] or '').lower() == 'system':
                continue
                
            is_test = matches_test_pattern(m['name'])
            is_orphan = m['id'] not in mcp_tool_to_agents
            
            if is_test or is_orphan:
                bindings = [f"Agent: {a}" for a in mcp_tool_to_agents.get(m['id'], [])]
                
                reason_parts = []
                if is_test:
                    reason_parts.append('Test/Demo/Sample name')
                if is_orphan:
                    reason_parts.append('Orphan')
                
                summary.mcp_tools.append(CleanupItem(
                    id=str(m['id']),
                    name=m['name'],
                    item_type='mcp_tool',
                    created_by=m['created_by'] or '',
                    created_on=m['created_on'],
                    is_orphan=is_orphan,
                    is_test_pattern=is_test,
                    reason='; '.join(reason_parts),
                    bound_to=', '.join(bindings) if bindings else 'None'
                ))
        
        # Update stats
        self.stats["agents"]["found"] = len(summary.agents)
        self.stats["tools"]["found"] = len(summary.tools)
        self.stats["workflows"]["found"] = len(summary.workflows)
        self.stats["mcp_tools"]["found"] = len(summary.mcp_tools)
        
        log.info(f"Found cleanup items - Agents: {len(summary.agents)}, Tools: {len(summary.tools)}, "
                 f"workflows: {len(summary.workflows)}, MCP Tools: {len(summary.mcp_tools)}")
        
        return summary
    
    # ========================================================================
    # REPORT GENERATION
    # ========================================================================
    
    def _convert_datetime_for_excel(self, dt: Optional[datetime]) -> Optional[datetime]:
        """Convert timezone-aware datetime to timezone-naive for Excel compatibility"""
        if dt is None:
            return None
        if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt
    
    def create_cleanup_report(self, summary: CleanupSummary) -> str:
        """
        Create Excel report of items to be cleaned up.
        
        Returns:
            Path to the created report file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"CLEANUP_PREVIEW_{timestamp}.xlsx"
        filepath = os.path.join(self.cleanup_reports_path, filename)
        
        # Prepare data for Excel
        all_items = []
        
        for item in summary.agents:
            all_items.append({
                'type': 'Agent',
                'id': item.id,
                'name': item.name,
                'sub_type': item.sub_type,
                'created_by': item.created_by,
                'created_on': self._convert_datetime_for_excel(item.created_on),
                'reason': item.reason,
                'bound_to': item.bound_to
            })
        
        for item in summary.tools:
            all_items.append({
                'type': 'Tool',
                'id': item.id,
                'name': item.name,
                'sub_type': 'partial_cleanup' if item.is_partial_orphan else 'full_deletion',
                'created_by': item.created_by,
                'created_on': self._convert_datetime_for_excel(item.created_on),
                'reason': item.reason,
                'bound_to': item.bound_to,
                'all_versions': ', '.join(item.all_versions) if item.all_versions else '',
                'bound_versions': ', '.join(item.bound_versions) if item.bound_versions else '',
                'orphan_versions': ', '.join(item.orphan_versions) if item.orphan_versions else '',
                'action': 'Delete orphan versions only' if item.is_partial_orphan else 'Delete entire tool'
            })
        
        for item in summary.workflows:
            all_items.append({
                'type': 'workflow',
                'id': item.id,
                'name': item.name,
                'sub_type': '',
                'created_by': item.created_by,
                'created_on': self._convert_datetime_for_excel(item.created_on),
                'reason': item.reason,
                'bound_to': item.bound_to
            })
        
        for item in summary.mcp_tools:
            all_items.append({
                'type': 'MCP Tool',
                'id': item.id,
                'name': item.name,
                'sub_type': '',
                'created_by': item.created_by,
                'created_on': self._convert_datetime_for_excel(item.created_on),
                'reason': item.reason,
                'bound_to': item.bound_to
            })
        
        # Create DataFrame and save
        df = pd.DataFrame(all_items)
        
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Items to Delete', index=False)
            
            # Summary sheet
            summary_data = {
                'Category': ['Agents', 'Tools', 'workflows', 'MCP Tools', 'TOTAL'],
                'Count': [
                    len(summary.agents),
                    len(summary.tools),
                    len(summary.workflows),
                    len(summary.mcp_tools),
                    summary.total_count
                ]
            }
            pd.DataFrame(summary_data).to_excel(writer, sheet_name='Summary', index=False)
        
        log.info(f"Created cleanup report: {filepath}")
        return filepath
    
    def create_deletion_report(self) -> str:
        """
        Create Excel report of deleted items.
        Deletes old deletion reports since new one contains all cumulative data.
        
        Returns:
            Path to the created report file
        """
        # First, delete old deletion reports (new one will have all data)
        self._clear_old_deletion_reports()
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"DELETION_REPORT_{timestamp}.xlsx"
        filepath = os.path.join(self.deletion_reports_path, filename)
        
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            # Deletion records
            if self.deletion_records:
                df = pd.DataFrame(self.deletion_records)
                df.to_excel(writer, sheet_name='Deleted Items', index=False)
            
            # Unbinding records
            if self.unbind_records:
                df = pd.DataFrame(self.unbind_records)
                df.to_excel(writer, sheet_name='Unbinding Operations', index=False)
            
            # Summary
            summary_data = {
                'Category': ['Agents Deleted', 'Tools Deleted', 'workflows Deleted', 
                            'MCP Tools Deleted', 'Total Deleted',
                            'Tools Unbound from Agents', 'Agents Unbound from Meta',
                            'Agents Unbound from workflows', 'MCP Unbound from Agents',
                            'Feedback Records Cleaned', 'Evaluation Records Cleaned',
                            'LTM Tables Dropped'],
                'Count': [
                    self.stats["agents"]["deleted"],
                    self.stats["tools"]["deleted"],
                    self.stats["workflows"]["deleted"],
                    self.stats["mcp_tools"]["deleted"],
                    self.stats["agents"]["deleted"] + self.stats["tools"]["deleted"] + 
                    self.stats["workflows"]["deleted"] + self.stats["mcp_tools"]["deleted"],
                    self.stats["unbinding"]["tools_from_agents"],
                    self.stats["unbinding"]["agents_from_meta"],
                    self.stats["unbinding"]["agents_from_workflows"],
                    self.stats["unbinding"]["mcp_from_agents"],
                    self.stats["related_cleanup"]["feedback_records"],
                    self.stats["related_cleanup"]["evaluation_records"],
                    self.stats["related_cleanup"]["ltm_tables"]
                ]
            }
            pd.DataFrame(summary_data).to_excel(writer, sheet_name='Summary', index=False)
        
        log.info(f"Created deletion report: {filepath}")
        return filepath
    
    def _clear_old_deletion_reports(self):
        """Clear old deletion reports since new one contains cumulative data"""
        try:
            for filename in os.listdir(self.deletion_reports_path):
                if filename.startswith("DELETION_REPORT_") and filename.endswith(".xlsx"):
                    filepath = os.path.join(self.deletion_reports_path, filename)
                    try:
                        os.remove(filepath)
                        log.info(f"Removed old deletion report: {filename}")
                    except PermissionError:
                        log.warning(f"Could not delete {filename} - file may be open in Excel. Please close it.")
                    except Exception as e:
                        log.warning(f"Could not delete {filename}: {e}")
        except Exception as e:
            log.warning(f"Error clearing old deletion reports: {e}")

    def clear_cleanup_reports(self):
        """Clear all cleanup preview reports after deletion"""
        try:
            for filename in os.listdir(self.cleanup_reports_path):
                if filename.startswith("CLEANUP_PREVIEW_"):
                    filepath = os.path.join(self.cleanup_reports_path, filename)
                    try:
                        os.remove(filepath)
                        log.info(f"Removed cleanup report: {filename}")
                    except PermissionError:
                        log.warning(f"Could not delete {filename} - file may be open in Excel. Please close it.")
                    except Exception as e:
                        log.warning(f"Could not delete {filename}: {e}")
        except Exception as e:
            log.warning(f"Error clearing cleanup reports: {e}")
    
    # ========================================================================
    # EMAIL FUNCTIONALITY
    # ========================================================================
    
    def connect_outlook(self) -> bool:
        """Connect to Outlook for sending emails"""
        if not OUTLOOK_AVAILABLE:
            log.warning("Outlook not available on this system")
            return False
        
        try:
            self.outlook = win32com.client.Dispatch("Outlook.Application")
            log.info("Connected to Outlook")
            return True
        except Exception as e:
            log.error(f"Failed to connect to Outlook: {e}")
            return False
    
    def is_valid_outlook_recipient(self, email: str) -> bool:
        """
        Validate email address using Outlook's MAPI namespace.
        Only accepts emails that exist as real Exchange users in the corporate GAL.
        
        Args:
            email: Email address to validate
            
        Returns:
            True if email is a real Exchange user in organization,
            False if it's fake/external/unresolvable
        """
        if not email or '@' not in email:
            log.info(f"Invalid email format: {email}")
            return False
        
        if not self.outlook:
            if not self.connect_outlook():
                log.warning(f"Cannot validate email - Outlook not available")
                return False
        
        try:
            # Use MAPI namespace for recipient validation
            namespace = self.outlook.GetNamespace("MAPI")
            recipient = namespace.CreateRecipient(email)
            
            # Resolve against Global Address List
            recipient.Resolve()
            
            if not recipient.Resolved:
                log.info(f"Email could not be resolved by Outlook, skipping: {email}")
                return False
            
            # Get the address entry
            address_entry = recipient.AddressEntry
            if not address_entry:
                log.info(f"No AddressEntry for email, skipping: {email}")
                return False
            
            # Check AddressEntry Type - only accept Exchange users
            # Type 0 = olExchangeUserAddressEntry (Exchange user)
            # Type 1 = olExchangeDistributionListAddressEntry (Exchange DL)
            # Type 10 = olSmtpAddressEntry (external SMTP - this is what fake emails get!)
            try:
                entry_type = address_entry.Type
                log.info(f"Email {email} has AddressEntry.Type = {entry_type}")
                
                # Only accept Exchange user types (0 for user, 1 for distribution list)
                if entry_type in [0, 1]:
                    log.info(f"Email validated as Exchange user/DL: {email}")
                    return True
                elif entry_type == 10:
                    # SMTP address - external/fake email
                    log.info(f"Email is external SMTP (not in org), skipping: {email}")
                    return False
                else:
                    # Other types - try GetExchangeUser as fallback
                    try:
                        exchange_user = address_entry.GetExchangeUser()
                        if exchange_user:
                            log.info(f"Email validated via GetExchangeUser: {email}")
                            return True
                    except:
                        pass
                    
                    log.info(f"Email type {entry_type} not recognized as valid, skipping: {email}")
                    return False
                    
            except Exception as type_error:
                log.warning(f"Could not get AddressEntry.Type for {email}: {type_error}")
                # Fallback - try GetExchangeUser only (strict check)
                try:
                    exchange_user = address_entry.GetExchangeUser()
                    if exchange_user:
                        log.info(f"Email validated via GetExchangeUser fallback: {email}")
                        return True
                except:
                    pass
                
                log.info(f"Could not validate email as Exchange user, skipping: {email}")
                return False
                
        except Exception as e:
            log.warning(f"Error validating email {email} via Outlook: {e}")
            return False
    
    def send_notification_email(
        self, 
        to_email: str, 
        admin_email: str,
        items: List[CleanupItem],
        attachment_path: str
    ) -> bool:
        """
        Send notification email to user about items being deleted.
        
        Args:
            to_email: User's email address
            admin_email: Admin who initiated the cleanup
            items: List of items belonging to this user
            attachment_path: Path to Excel file with item details
            
        Returns:
            True if email sent successfully
        """
        if not self.outlook:
            if not self.connect_outlook():
                return False
        
        # TESTING MODE: Override recipient and track original
        original_recipient = to_email
        if TESTING_MODE:
            to_email = TEST_EMAIL_RECIPIENT
            admin_email = TEST_EMAIL_SENDER
            log.info(f"TESTING MODE: Redirecting email from {original_recipient} to {to_email}")
        
        try:
            mail = self.outlook.CreateItem(0)
            mail.Subject = "IAF Cleanup Notification - Items Scheduled for Deletion"
            mail.To = to_email
            
            # Get backup URL dynamically (same pattern as backup endpoint)
            backup_repo_url = get_backup_repo_url()
            
            # Build item summary for email
            item_summary = []
            for item in items:
                item_summary.append(f"• {item.item_type.upper()}: {item.name} (Reason: {item.reason})")
            
            # Add testing mode notice to email body
            testing_notice = ""
            if TESTING_MODE:
                testing_notice = f"""
                <div style="background-color: #fff3cd; padding: 10px; border: 1px solid #ffc107; border-radius: 5px; margin-bottom: 15px;">
                    <strong>⚠️ TESTING MODE</strong><br>
                    This email was originally intended for: <strong>{original_recipient}</strong><br>
                    Redirected to: <strong>{to_email}</strong>
                </div>
                """
            
            html_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6;">
                <h2 style="color: #333;">IAF Cleanup Notification</h2>
                
                {testing_notice}
                
                <p>Dear User,</p>
                
                <p>This is to inform you that the following items created by you are scheduled for deletion 
                as part of our periodic cleanup of test/demo/sample and orphan items:</p>
                
                <div style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin: 15px 0;">
                    <strong>Items to be deleted ({len(items)} total):</strong><br>
                    {'<br>'.join(item_summary[:10])}
                    {f'<br>... and {len(items) - 10} more items' if len(items) > 10 else ''}
                </div>
                
                <p><strong>Deletion Criteria:</strong></p>
                <ul>
                    <li>Items with test/demo/sample in name</li>
                    <li>Orphan items (not bound to any other item)</li>
                </ul>
                
                <p><strong>Backup Available:</strong><br>
                A backup of all deleted items is available at:<br>
                <a href="{backup_repo_url}">{backup_repo_url}</a></p>
                
                <p>Please find the attached Excel file for the complete list of items being deleted.</p>
                
                <p style="color: #666; font-size: 12px;">
                    This cleanup was initiated by: {admin_email}<br>
                    Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                </p>
                
                <p>Best regards,<br>IAF Admin Team</p>
            </body>
            </html>
            """
            
            mail.HTMLBody = html_body
            
            # Add attachment
            if attachment_path and os.path.exists(attachment_path):
                mail.Attachments.Add(attachment_path)
            
            mail.Send()
            log.info(f"Sent notification email to: {to_email}")
            return True
            
        except Exception as e:
            log.error(f"Failed to send email to {to_email}: {e}")
            return False
    
    def send_emails_to_users(
        self, 
        summary: CleanupSummary, 
        admin_email: str,
        report_path: str
    ) -> Dict[str, Any]:
        """
        Send notification emails to all users whose items will be deleted.
        
        Args:
            summary: CleanupSummary with items to delete
            admin_email: Email of admin who initiated cleanup
            report_path: Path to the cleanup report Excel file
            
        Returns:
            Dictionary with email sending results
        """
        # Connect to Outlook first for email validation and sending
        if not self.outlook:
            if not self.connect_outlook():
                log.error("Cannot send emails - Outlook not available")
                return {
                    "total_users": 0,
                    "emails_sent": 0,
                    "emails_failed": 0,
                    "emails_skipped": 0,
                    "users_notified": [],
                    "users_failed": [],
                    "users_skipped": [],
                    "error": "Outlook not available"
                }
        
        # TESTING MODE notice
        if TESTING_MODE:
            log.info(f"="*50)
            log.info(f"⚠️ TESTING MODE ACTIVE")
            log.info(f"All emails will be sent to: {TEST_EMAIL_RECIPIENT}")
            log.info(f"Sender will be: {TEST_EMAIL_SENDER}")
            log.info(f"="*50)
        
        # Group items by creator
        items_by_user = defaultdict(list)
        
        for item in summary.agents + summary.tools + summary.workflows + summary.mcp_tools:
            if item.created_by:
                items_by_user[item.created_by].append(item)
        
        results = {
            "total_users": len(items_by_user),
            "emails_sent": 0,
            "emails_failed": 0,
            "emails_skipped": 0,  # Fake/unresolvable emails
            "users_notified": [],
            "users_failed": [],
            "users_skipped": []  # Users with fake emails
        }
        
        for user_email, user_items in items_by_user.items():
            # Check if email is in excluded list (for testing purposes)
            if user_email.lower() in [e.lower() for e in EXCLUDED_EMAILS]:
                log.info(f"Skipping excluded email (testing): {user_email}")
                results["emails_skipped"] += 1
                results["users_skipped"].append(user_email)
                continue
            
            # Pre-validate email using Outlook resolution (skip fake emails early)
            if not TESTING_MODE and not self.is_valid_outlook_recipient(user_email):
                log.info(f"Skipping fake/unresolvable email: {user_email}")
                results["emails_skipped"] += 1
                results["users_skipped"].append(user_email)
                continue
            
            # Create user-specific Excel file
            user_report_path = self._create_user_report(user_email, user_items)
            
            if self.send_notification_email(user_email, admin_email, user_items, user_report_path):
                results["emails_sent"] += 1
                results["users_notified"].append(user_email)
            else:
                results["emails_failed"] += 1
                results["users_failed"].append(user_email)
            
            # Clean up user-specific report
            try:
                if user_report_path and os.path.exists(user_report_path):
                    os.remove(user_report_path)
            except:
                pass
        
        log.info(f"Email results: {results['emails_sent']} sent, {results['emails_failed']} failed, {results['emails_skipped']} skipped (fake/unresolvable)")
        return results
    
    def _create_user_report(self, user_email: str, items: List[CleanupItem]) -> str:
        """Create a user-specific Excel report"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_email = user_email.replace('@', '_at_').replace('.', '_')
        filename = f"CLEANUP_{safe_email}_{timestamp}.xlsx"
        filepath = os.path.join(self.cleanup_reports_path, filename)
        
        data = []
        for item in items:
            data.append({
                'type': item.item_type,
                'id': item.id,
                'name': item.name,
                'sub_type': item.sub_type,
                'created_on': self._convert_datetime_for_excel(item.created_on),
                'reason': item.reason,
                'bound_to': item.bound_to
            })
        
        df = pd.DataFrame(data)
        df.to_excel(filepath, index=False)
        
        return filepath
    
    # ========================================================================
    # UNBINDING OPERATIONS
    # ========================================================================
    
    async def unbind_tool_from_agents(self, tool_id: str, tool_name: str) -> int:
        """Unbind a tool from all agents that use it"""
        unbind_count = 0
        try:
            agents_using = await self.conn.fetch("""
                SELECT a.agentic_application_id, a.agentic_application_name, a.tools_id
                FROM agent_table a
                JOIN tool_agent_mapping_table tam ON tam.agentic_application_id = a.agentic_application_id
                WHERE tam.tool_id = $1
            """, tool_id)
            
            for agent in agents_using:
                agent_id = agent['agentic_application_id']
                agent_name = agent['agentic_application_name']
                
                # Update tools_id array
                current_tools = agent['tools_id']
                if current_tools:
                    tool_list = current_tools if isinstance(current_tools, list) else json.loads(current_tools)
                    if tool_id in tool_list:
                        tool_list.remove(tool_id)
                        await self.conn.execute("""
                            UPDATE agent_table SET tools_id = $1::jsonb
                            WHERE agentic_application_id = $2
                        """, json.dumps(tool_list), agent_id)
                
                # Delete from mapping table
                await self.conn.execute("""
                    DELETE FROM tool_agent_mapping_table 
                    WHERE tool_id = $1 AND agentic_application_id = $2
                """, tool_id, agent_id)
                
                unbind_count += 1
                self.unbind_records.append({
                    "action": "unbind_tool",
                    "tool_id": tool_id,
                    "tool_name": tool_name,
                    "agent_id": str(agent_id),
                    "agent_name": agent_name,
                    "timestamp": datetime.now().isoformat()
                })
            
            self.stats["unbinding"]["tools_from_agents"] += unbind_count
            
        except Exception as e:
            log.error(f"Error unbinding tool {tool_name}: {e}")
        
        return unbind_count
    
    async def unbind_agent_from_meta_agents(self, agent_id: str, agent_name: str) -> int:
        """Unbind an agent from meta agents that use it"""
        unbind_count = 0
        try:
            meta_agents = await self.conn.fetch("""
                SELECT agentic_application_id, agentic_application_name, tools_id
                FROM agent_table
                WHERE agentic_application_type IN ('meta_agent', 'multi_agent', 'planner_meta_agent')
                AND tools_id IS NOT NULL
            """)
            
            for meta in meta_agents:
                tools_id = meta['tools_id']
                if isinstance(tools_id, str):
                    tools_id = json.loads(tools_id)
                
                if agent_id in tools_id:
                    tools_id.remove(agent_id)
                    await self.conn.execute("""
                        UPDATE agent_table SET tools_id = $1::jsonb
                        WHERE agentic_application_id = $2
                    """, json.dumps(tools_id), meta['agentic_application_id'])
                    
                    unbind_count += 1
                    self.unbind_records.append({
                        "action": "unbind_from_meta",
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "meta_agent_id": str(meta['agentic_application_id']),
                        "meta_agent_name": meta['agentic_application_name'],
                        "timestamp": datetime.now().isoformat()
                    })
            
            self.stats["unbinding"]["agents_from_meta"] += unbind_count
            
        except Exception as e:
            log.error(f"Error unbinding agent {agent_name} from meta agents: {e}")
        
        return unbind_count
    
    async def unbind_agent_from_workflows(self, agent_id: str, agent_name: str) -> int:
        """Unbind an agent from workflows"""
        unbind_count = 0
        try:
            workflows = await self.conn.fetch("""
                SELECT workflow_id, workflow_name, workflow_definition
                FROM workflows_table
                WHERE workflow_definition::text LIKE $1
            """, f'%{agent_id}%')
            
            for workflow in workflows:
                defn = workflow['workflow_definition']
                if isinstance(defn, str):
                    defn = json.loads(defn)
                
                modified = False
                if 'nodes' in defn:
                    new_nodes = []
                    for node in defn['nodes']:
                        if isinstance(node, dict) and node.get('node_type') == 'agent':
                            config = node.get('config', {})
                            if config.get('agent_id') == agent_id:
                                modified = True
                                continue
                        new_nodes.append(node)
                    
                    if modified:
                        defn['nodes'] = new_nodes
                        await self.conn.execute("""
                            UPDATE workflows_table SET workflow_definition = $1::jsonb
                            WHERE workflow_id = $2
                        """, json.dumps(defn), workflow['workflow_id'])
                        
                        unbind_count += 1
                        self.unbind_records.append({
                            "action": "unbind_from_workflow",
                            "agent_id": agent_id,
                            "agent_name": agent_name,
                            "workflow_id": str(workflow['workflow_id']),
                            "workflow_name": workflow['workflow_name'],
                            "timestamp": datetime.now().isoformat()
                        })
            
            self.stats["unbinding"]["agents_from_workflows"] += unbind_count
            
        except Exception as e:
            log.error(f"Error unbinding agent {agent_name} from workflows: {e}")
        
        return unbind_count
    
    async def unbind_mcp_from_agents(self, mcp_id: str, mcp_name: str) -> int:
        """Unbind MCP tool from agents"""
        unbind_count = 0
        try:
            agents_using = await self.conn.fetch("""
                SELECT a.agentic_application_id, a.agentic_application_name, a.tools_id
                FROM agent_table a
                JOIN tool_agent_mapping_table tam ON tam.agentic_application_id = a.agentic_application_id
                WHERE tam.tool_id = $1
            """, mcp_id)
            
            for agent in agents_using:
                agent_id = agent['agentic_application_id']
                agent_name = agent['agentic_application_name']
                
                current_tools = agent['tools_id']
                if current_tools:
                    tool_list = current_tools if isinstance(current_tools, list) else json.loads(current_tools)
                    if mcp_id in tool_list:
                        tool_list.remove(mcp_id)
                        await self.conn.execute("""
                            UPDATE agent_table SET tools_id = $1::jsonb
                            WHERE agentic_application_id = $2
                        """, json.dumps(tool_list), agent_id)
                
                await self.conn.execute("""
                    DELETE FROM tool_agent_mapping_table 
                    WHERE tool_id = $1 AND agentic_application_id = $2
                """, mcp_id, agent_id)
                
                unbind_count += 1
                self.unbind_records.append({
                    "action": "unbind_mcp",
                    "mcp_id": mcp_id,
                    "mcp_name": mcp_name,
                    "agent_id": str(agent_id),
                    "agent_name": agent_name,
                    "timestamp": datetime.now().isoformat()
                })
            
            self.stats["unbinding"]["mcp_from_agents"] += unbind_count
            
        except Exception as e:
            log.error(f"Error unbinding MCP {mcp_name}: {e}")
        
        return unbind_count
    
    # ========================================================================
    # DELETION OPERATIONS
    # ========================================================================
    
    async def delete_agent(self, item: CleanupItem) -> bool:
        """Delete an agent with all related data"""
        try:
            await self.ensure_connection()
            agent_id = item.id
            
            # Unbind from meta agents and workflows first
            await self.unbind_agent_from_meta_agents(agent_id, item.name)
            await self.unbind_agent_from_workflows(agent_id, item.name)
            
            # Delete from tool_agent_mapping_table
            await self.conn.execute(
                "DELETE FROM tool_agent_mapping_table WHERE agentic_application_id = $1", 
                agent_id
            )
            
            # Delete from agent_tag_mapping_table
            try:
                await self.conn.execute(
                    "DELETE FROM agent_tag_mapping_table WHERE agent_id = $1", 
                    agent_id
                )
            except:
                pass
            
            # Delete from evaluation_config_table
            try:
                await self.conn.execute(
                    "DELETE FROM evaluation_config_table WHERE agent_id = $1", 
                    agent_id
                )
            except:
                pass
            
            # Delete from feedback_learning database
            if self.feedback_conn:
                try:
                    await self.feedback_conn.execute(
                        "DELETE FROM feedback WHERE agent_id = $1", agent_id
                    )
                    self.stats["related_cleanup"]["feedback_records"] += 1
                except:
                    pass
            
            # Delete from evaluation_logs database
            if self.evaluation_conn:
                try:
                    result = await self.evaluation_conn.execute(
                        "DELETE FROM evaluation_runs WHERE agent_id = $1", agent_id
                    )
                    count = int(result.split()[-1]) if result else 0
                    self.stats["related_cleanup"]["evaluation_records"] += count
                except:
                    pass
            
            # Drop LTM tables
            safe_id = agent_id.replace('-', '_')
            for table_prefix in ['table_', 'robustness_']:
                try:
                    await self.conn.execute(f'DROP TABLE IF EXISTS "{table_prefix}{safe_id}" CASCADE')
                    self.stats["related_cleanup"]["ltm_tables"] += 1
                except:
                    pass
            
            # Delete the agent
            await self.conn.execute(
                "DELETE FROM agent_table WHERE agentic_application_id = $1", 
                agent_id
            )
            
            self.stats["agents"]["deleted"] += 1
            self.deletion_records.append({
                "type": "Agent",
                "id": item.id,
                "name": item.name,
                "sub_type": item.sub_type,
                "created_by": item.created_by,
                "reason": item.reason,
                "deleted_at": datetime.now().isoformat()
            })
            
            log.info(f"Deleted agent: {item.name}")
            return True
            
        except Exception as e:
            log.error(f"Error deleting agent {item.name}: {e}")
            self.stats["agents"]["errors"] += 1
            return False
    
    async def delete_tool(self, item: CleanupItem) -> bool:
        """
        Delete a tool with unbinding and version file cleanup.
        
        Supports two modes:
        1. Full deletion (delete_all_versions=True): Delete entire tool and all versions
        2. Partial deletion (delete_all_versions=False): Delete only orphan versions, keep bound versions
        """
        try:
            await self.ensure_connection()
            tool_id = item.id
            tool_name = item.name
            sanitized_name = self._sanitize_tool_filename(tool_name)
            
            # Check if this is partial deletion (only orphan versions) or full deletion
            if not item.delete_all_versions and item.is_partial_orphan:
                # ==============================================================
                # PARTIAL DELETION: Only delete orphan versions, keep bound ones
                # ==============================================================
                orphan_versions = item.orphan_versions
                bound_versions = item.bound_versions
                
                if not orphan_versions:
                    log.info(f"Tool '{tool_name}' has no orphan versions to delete, skipping.")
                    return True
                
                log.info(f"Partial cleanup for tool '{tool_name}': deleting orphan versions {orphan_versions}, keeping bound versions {bound_versions}")
                
                deleted_files = []
                failed_files = []
                deleted_version_records = []
                
                # Delete orphan version files from filesystem
                for version in orphan_versions:
                    version_filename = f"{sanitized_name}_{version}.py"
                    version_file_path = self.onboarded_tools_path / version_filename
                    try:
                        if version_file_path.exists():
                            version_file_path.unlink()
                            deleted_files.append(version_filename)
                            log.info(f"Deleted orphan version file: {version_file_path}")
                    except Exception as e:
                        failed_files.append(version_filename)
                        log.warning(f"Failed to delete orphan version file {version_file_path}: {e}")
                
                # Delete orphan version records from tool_versions_table
                for version in orphan_versions:
                    try:
                        result = await self.conn.execute(
                            "DELETE FROM tool_versions_table WHERE tool_id = $1 AND version = $2",
                            tool_id, version
                        )
                        deleted_version_records.append(version)
                        log.info(f"Deleted orphan version record: tool='{tool_name}', version='{version}'")
                    except Exception as e:
                        log.warning(f"Failed to delete version record for tool '{tool_name}' version '{version}': {e}")
                
                # Record partial deletion
                self.stats["tools"]["deleted"] += 1  # Count as one tool operation
                self.deletion_records.append({
                    "type": "Tool (Partial - Orphan Versions Only)",
                    "id": item.id,
                    "name": item.name,
                    "sub_type": "partial_cleanup",
                    "created_by": item.created_by,
                    "reason": item.reason,
                    "deleted_at": datetime.now().isoformat(),
                    "orphan_versions_deleted": orphan_versions,
                    "bound_versions_kept": bound_versions,
                    "files_deleted": deleted_files,
                    "files_failed": failed_files
                })
                
                log.info(f"Partial cleanup completed for tool '{tool_name}': deleted versions {orphan_versions}, kept versions {bound_versions}")
                return True
            
            else:
                # ==============================================================
                # FULL DELETION: Delete entire tool and all versions
                # ==============================================================
                log.info(f"Full deletion for tool '{tool_name}' (reason: {item.reason})")
                
                # Unbind from agents first
                await self.unbind_tool_from_agents(tool_id, tool_name)
                
                # Delete from tool_tag_mapping_table
                try:
                    await self.conn.execute(
                        "DELETE FROM tool_tag_mapping_table WHERE tool_id = $1", 
                        tool_id
                    )
                except:
                    pass
                
                # Get all versions for this tool before deleting (for file cleanup)
                versions_to_delete = []
                try:
                    versions = await self.conn.fetch(
                        "SELECT version FROM tool_versions_table WHERE tool_id = $1",
                        tool_id
                    )
                    versions_to_delete = [v['version'] for v in versions]
                    log.info(f"Found {len(versions_to_delete)} versions for tool '{tool_name}': {versions_to_delete}")
                except Exception as e:
                    log.warning(f"Could not fetch versions for tool '{tool_name}': {e}")
                
                # Delete version files from filesystem
                deleted_files = []
                failed_files = []
                
                # Delete each version file (e.g., tool_name_v1.py, tool_name_v2.py)
                for version in versions_to_delete:
                    version_filename = f"{sanitized_name}_{version}.py"
                    version_file_path = self.onboarded_tools_path / version_filename
                    try:
                        if version_file_path.exists():
                            version_file_path.unlink()
                            deleted_files.append(version_filename)
                            log.info(f"Deleted version file: {version_file_path}")
                    except Exception as e:
                        failed_files.append(version_filename)
                        log.warning(f"Failed to delete version file {version_file_path}: {e}")
                
                # Also delete the base tool file (tool_name.py) for backwards compatibility
                base_filename = f"{sanitized_name}.py"
                base_file_path = self.onboarded_tools_path / base_filename
                try:
                    if base_file_path.exists():
                        base_file_path.unlink()
                        deleted_files.append(base_filename)
                        log.info(f"Deleted base tool file: {base_file_path}")
                except Exception as e:
                    failed_files.append(base_filename)
                    log.warning(f"Failed to delete base tool file {base_file_path}: {e}")
                
                if deleted_files:
                    log.info(f"Deleted {len(deleted_files)} tool files for '{tool_name}': {deleted_files}")
                if failed_files:
                    log.warning(f"Failed to delete {len(failed_files)} files for '{tool_name}': {failed_files}")
                
                # Delete from tool_table (CASCADE will auto-delete from tool_versions_table)
                await self.conn.execute(
                    "DELETE FROM tool_table WHERE tool_id = $1", 
                    tool_id
                )
                
                self.stats["tools"]["deleted"] += 1
                self.deletion_records.append({
                    "type": "Tool (Full Deletion)",
                    "id": item.id,
                    "name": item.name,
                    "sub_type": "full_deletion",
                    "created_by": item.created_by,
                    "reason": item.reason,
                    "deleted_at": datetime.now().isoformat(),
                    "versions_deleted": versions_to_delete,
                    "files_deleted": deleted_files,
                    "files_failed": failed_files
                })
                
                log.info(f"Deleted tool: {tool_name} (versions: {len(versions_to_delete)}, files: {len(deleted_files)})")
                return True
            
        except Exception as e:
            log.error(f"Error deleting tool {item.name}: {e}")
            self.stats["tools"]["errors"] += 1
            return False
    
    def _sanitize_tool_filename(self, tool_name: str) -> str:
        """
        Convert tool_name to valid filename (without extension).
        Same logic as ToolFileManager._sanitize_filename for consistency.
        """
        return "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in tool_name)
    
    async def delete_workflow(self, item: CleanupItem) -> bool:
        """Delete a workflow"""
        try:
            await self.ensure_connection()
            
            await self.conn.execute(
                "DELETE FROM workflows_table WHERE workflow_id = $1", 
                item.id
            )
            
            self.stats["workflows"]["deleted"] += 1
            self.deletion_records.append({
                "type": "workflow",
                "id": item.id,
                "name": item.name,
                "sub_type": "",
                "created_by": item.created_by,
                "reason": item.reason,
                "deleted_at": datetime.now().isoformat()
            })
            
            log.info(f"Deleted workflow: {item.name}")
            return True
            
        except Exception as e:
            log.error(f"Error deleting workflow {item.name}: {e}")
            self.stats["workflows"]["errors"] += 1
            return False
    
    async def delete_mcp_tool(self, item: CleanupItem) -> bool:
        """Delete an MCP tool with unbinding"""
        try:
            await self.ensure_connection()
            
            # Unbind from agents first
            await self.unbind_mcp_from_agents(item.id, item.name)
            
            # Delete the MCP tool
            await self.conn.execute(
                "DELETE FROM mcp_tool_table WHERE tool_id = $1", 
                item.id
            )
            
            self.stats["mcp_tools"]["deleted"] += 1
            self.deletion_records.append({
                "type": "MCP Tool",
                "id": item.id,
                "name": item.name,
                "sub_type": "",
                "created_by": item.created_by,
                "reason": item.reason,
                "deleted_at": datetime.now().isoformat()
            })
            
            log.info(f"Deleted MCP tool: {item.name}")
            return True
            
        except Exception as e:
            log.error(f"Error deleting MCP tool {item.name}: {e}")
            self.stats["mcp_tools"]["errors"] += 1
            return False
    
    async def execute_deletion(self, summary: CleanupSummary) -> DeletionResult:
        """
        Execute deletion of all items in the summary.
        
        Args:
            summary: CleanupSummary with items to delete
            
        Returns:
            DeletionResult with deletion statistics
        """
        result = DeletionResult()
        
        if not self.conn:
            await self.connect()
        
        # Delete agents first (they may be bound to tools)
        for item in summary.agents:
            if await self.delete_agent(item):
                result.deleted_agents += 1
        
        # Delete tools
        for item in summary.tools:
            if await self.delete_tool(item):
                result.deleted_tools += 1
        
        # Delete workflows
        for item in summary.workflows:
            if await self.delete_workflow(item):
                result.deleted_workflows += 1
        
        # Delete MCP tools
        for item in summary.mcp_tools:
            if await self.delete_mcp_tool(item):
                result.deleted_mcp_tools += 1
        
        # Create deletion report
        result.report_path = self.create_deletion_report()
        
        # Clear cleanup preview reports
        self.clear_cleanup_reports()
        
        # Update result with stats
        result.unbinding_operations = self.stats["unbinding"].copy()
        result.related_cleanup = self.stats["related_cleanup"].copy()
        
        log.info(f"Deletion complete - Agents: {result.deleted_agents}, Tools: {result.deleted_tools}, "
                 f"workflows: {result.deleted_workflows}, MCP Tools: {result.deleted_mcp_tools}")
        
        return result


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_cleanup_service: Optional[CleanupService] = None

def get_cleanup_service() -> CleanupService:
    """Get or create the cleanup service singleton"""
    global _cleanup_service
    if _cleanup_service is None:
        _cleanup_service = CleanupService()
    return _cleanup_service
