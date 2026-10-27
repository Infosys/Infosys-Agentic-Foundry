#!/usr/bin/env python3
"""
Self-Evolution Analysis System

Analyzes conversation history and codebase to identify gaps and suggest improvements.
Uses LLM-based analysis (not keyword matching) for semantic understanding.

Architecture:
- Tier 1: Session Loading (load & chunk conversations)
- Tier 2: LLM Classification (classify sessions with gpt-4o-mini)
- Tier 3: Code Analysis (analyze skills, kernel, tools)
- Tier 4: Improvement Generation (generate fixes with gpt-4o)

Usage:
    from iaf_agent_skills.self_evolution import SelfEvolutionEngine
    
    engine = SelfEvolutionEngine(
        workspace_root="/path/to/IAF-Agent-Skills",
        llm=azure_openai_client
    )
    
    # Run full analysis
    report = await engine.analyze()
    
    # Get improvements
    for imp in report.improvements:
        print(f"{imp.priority}: {imp.title}")
"""

import logging
import os
import json
import hashlib
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)



class GapType(str, Enum):
    """Types of gaps detected in the system."""
    SKILL_MISSING = "skill_missing"         # User asked for capability we don't have
    SKILL_WEAK = "skill_weak"               # Skill exists but performs poorly
    KNOWLEDGE_GAP = "knowledge_gap"         # Missing domain knowledge
    TOOL_LIMITATION = "tool_limitation"     # Tool exists but fails/limited
    ROUTING_ISSUE = "routing_issue"         # Query routed to wrong skill
    RESPONSE_QUALITY = "response_quality"   # Response was unhelpful
    USER_FRICTION = "user_friction"         # User showed frustration
    ERROR_PATTERN = "error_pattern"         # Repeated errors/failures
    # Enriched signal-based gap types
    PROMPT_GAP = "prompt_gap"               # SKILL.md missing instructions for a scenario
    MISSING_CONTEXT = "missing_context"     # Agent loaded same files repeatedly; should be pre-declared
    MEMORY_GAP = "memory_gap"               # query_memory not called or returned nothing for recurring topic
    TOOL_BLOCKED = "tool_blocked"           # Agent used blocked tool pattern (subprocess etc.)


class Priority(str, Enum):
    """Priority levels for improvements."""
    CRITICAL = "critical"  # Blocking user workflows
    HIGH = "high"          # Significant user friction
    MEDIUM = "medium"      # Nice to have improvement
    LOW = "low"            # Minor enhancement


class AnalysisStatus(str, Enum):
    """Status of analysis job."""
    PENDING = "pending"
    LOADING_SESSIONS = "loading_sessions"
    CLASSIFYING = "classifying"
    ANALYZING_SKILLS = "analyzing_skills"   # Tier 3a — SKILL.md prompt review
    ANALYZING_CODE = "analyzing_code"       # Tier 3b — Python code review
    GENERATING_IMPROVEMENTS = "generating_improvements"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SessionTurn:
    """A single conversation turn."""
    timestamp: str
    user_id: str
    skill: str
    user_input: str
    response: str
    tool_calls: List[dict] = field(default_factory=list)
    # Enriched fields from decision_context
    context_files: List[str] = field(default_factory=list)   # data_sources from context_used
    prior_skill: Optional[str] = None
    routing_confidence: Optional[float] = None
    routing_signals_agree: Optional[bool] = None
    tool_error_count: int = 0
    outcome_status: str = "success"
    user_feedback: Optional[str] = None                      # thumbs up/down from learning_signals

    @classmethod
    def from_dict(cls, data: dict) -> "SessionTurn":
        # Normalize tool_calls — may be strings or dicts
        raw_tools = data.get("tool_calls", [])
        if not isinstance(raw_tools, list):
            raw_tools = []
        tool_calls = [
            t if isinstance(t, dict) else {"tool": str(t)}
            for t in raw_tools
        ]

        context_used = data.get("context_used") or {}
        data_sources = context_used.get("data_sources") or []
        # Filter to meaningful file paths only (strip args like -r, -c etc.)
        context_files = [
            s for s in data_sources
            if isinstance(s, str) and (s.startswith("/") or s.startswith("./"))
        ]

        routing = data.get("routing") or {}
        routing_confidence = routing.get("confidence")
        routing_signals_agree = routing.get("signals_agree")

        # Count tool errors
        tool_error_count = sum(
            1 for t in tool_calls if isinstance(t, dict) and t.get("has_error")
        )

        outcome = data.get("outcome") or {}
        outcome_status = outcome.get("status", "success")

        learning = data.get("learning_signals") or {}
        user_feedback = None
        if isinstance(learning, dict):
            thumbs = learning.get("thumbs") or learning.get("feedback")
            if thumbs:
                user_feedback = str(thumbs)

        return cls(
            timestamp=data.get("timestamp", ""),
            user_id=data.get("user_id", ""),
            skill=data.get("skill", "general"),
            user_input=data.get("user_input", ""),
            response=data.get("response", ""),
            tool_calls=tool_calls,
            context_files=context_files,
            prior_skill=context_used.get("prior_skill"),
            routing_confidence=routing_confidence,
            routing_signals_agree=routing_signals_agree,
            tool_error_count=tool_error_count,
            outcome_status=outcome_status,
            user_feedback=user_feedback,
        )

    def to_text(self, include_metadata: bool = False) -> str:
        """Convert to enriched text block for LLM analysis."""
        skill_tag = f"[{self.skill}] " if self.skill and self.skill != "general" else ""

        if not include_metadata:
            return f"User: {self.user_input}\nAssistant: {self.response}"

        lines = [f"User{skill_tag}: {self.user_input}"]

        # Tool calls — separate query_memory from other tools
        memory_calls = []
        other_tools = []
        for t in self.tool_calls[:6]:
            if not isinstance(t, dict):
                continue
            name = t.get("tool", "unknown")
            inp = (t.get("input") or "")[:120]
            out = (t.get("output_preview") or "")[:200]
            err = " [ERROR]" if t.get("has_error") else ""
            if name == "query_memory":
                memory_calls.append(f"    query_memory({inp!r}){err} → {out[:100]}")
            else:
                other_tools.append(f"    [{name}]{err} {inp}")

        if other_tools:
            lines.append("  Tools: " + "; ".join(t.strip() for t in other_tools))
        if memory_calls:
            lines.append("  Memory lookups:\n" + "\n".join(memory_calls))
        elif not memory_calls and self.tool_calls:
            lines.append("  Memory lookups: (none — query_memory not called)")

        # Context files loaded
        if self.context_files:
            lines.append("  Context files: " + ", ".join(self.context_files[:4]))

        # Routing signal
        if self.routing_confidence is not None:
            agree = ""
            if self.routing_signals_agree is False:
                agree = " [keyword/LLM routing DISAGREED]"
            elif self.routing_signals_agree is None and self.routing_confidence < 0.7:
                agree = " [low confidence]"
            lines.append(f"  Routing confidence: {self.routing_confidence:.2f}{agree}")

        # Errors + feedback
        if self.tool_error_count:
            lines.append(f"  Tool errors: {self.tool_error_count}")
        if self.outcome_status and self.outcome_status != "success":
            lines.append(f"  Outcome: {self.outcome_status}")
        if self.user_feedback:
            lines.append(f"  User feedback: {self.user_feedback}")
        if self.prior_skill:
            lines.append(f"  Prior skill: {self.prior_skill}")

        lines.append(f"Assistant: {self.response[:400]}")
        return "\n".join(lines)


@dataclass
class Session:
    """A conversation session with multiple turns."""
    session_id: str
    user_id: str
    date: str
    turns: List[SessionTurn] = field(default_factory=list)
    file_path: str = ""
    
    @property
    def turn_count(self) -> int:
        return len(self.turns)
    
    @property
    def skills_used(self) -> List[str]:
        return list(set(t.skill for t in self.turns if t.skill))
    
    def to_text(self, max_chars: int = 2000) -> str:
        """Convert session to text for LLM, respecting char limit."""
        text_parts = []
        total_chars = 0
        
        for turn in self.turns:
            turn_text = turn.to_text(include_metadata=True)
            if total_chars + len(turn_text) > max_chars:
                text_parts.append("... [truncated]")
                break
            text_parts.append(turn_text)
            total_chars += len(turn_text)
        
        return f"Session: {self.session_id} | User: {self.user_id}\n" + "\n".join(text_parts)


@dataclass
class Gap:
    """A detected gap in the system."""
    type: GapType
    description: str
    evidence: List[str]  # Session IDs or code locations
    frequency: int = 1   # How many times observed
    severity: str = "medium"
    skill_file: Optional[str] = None          # e.g. "skills/invoice/SKILL.md"
    suggested_addition: Optional[str] = None  # Specific text to add to skill_file

    def to_dict(self) -> dict:
        return {
            "type": self.type.value if isinstance(self.type, GapType) else self.type,
            "description": self.description,
            "evidence": self.evidence,
            "frequency": self.frequency,
            "severity": self.severity,
            "skill_file": self.skill_file,
            "suggested_addition": self.suggested_addition,
        }


@dataclass
class Improvement:
    """A suggested improvement."""
    id: str
    type: str  # new_skill, enhance_skill, add_trigger, fix_code, add_tool
    title: str
    description: str
    priority: Priority
    effort: str  # low, medium, high
    related_gaps: List[str]  # Gap descriptions this addresses
    code_snippet: Optional[str] = None
    file_path: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "description": self.description,
            "priority": self.priority.value if isinstance(self.priority, Priority) else self.priority,
            "effort": self.effort,
            "related_gaps": self.related_gaps,
            "code_snippet": self.code_snippet,
            "file_path": self.file_path
        }


@dataclass
class EvolutionReport:
    """Complete analysis report."""
    job_id: str
    started_at: str
    completed_at: Optional[str] = None
    status: AnalysisStatus = AnalysisStatus.PENDING
    
    # Stats
    sessions_analyzed: int = 0
    code_files_analyzed: int = 0
    
    # Findings
    gaps: List[Gap] = field(default_factory=list)
    improvements: List[Improvement] = field(default_factory=list)
    
    # Errors
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status.value if isinstance(self.status, AnalysisStatus) else self.status,
            "sessions_analyzed": self.sessions_analyzed,
            "code_files_analyzed": self.code_files_analyzed,
            "gaps": [g.to_dict() for g in self.gaps],
            "improvements": [i.to_dict() for i in self.improvements],
            "errors": self.errors
        }



class SessionLoader:
    """
    Loads and chunks conversation sessions from workspace.
    
    Sessions are stored in: workspaces/{tenant}/{agent}/memory/history/{date}/*.jsonl
    
    Chunking Strategy:
    - Max 15 sessions per chunk (to stay within LLM context)
    - Each session truncated to ~2000 chars
    - Yields chunks for progressive processing
    """
    
    # Configuration
    SESSIONS_PER_CHUNK = 15
    CHARS_PER_SESSION = 2000
    MAX_SESSIONS = 200  # Safety limit
    
    def __init__(self, workspace_root: Path, workspaces_dir: Path = None):
        """
        Initialize session loader.
        
        Args:
            workspace_root: Path to IAF-Agent-Skills directory
            workspaces_dir: Override for the workspaces directory (e.g., enterprise_root/tenants)
        """
        self.workspace_root = Path(workspace_root)
        self.workspaces_dir = Path(workspaces_dir) if workspaces_dir else self.workspace_root / "workspaces"

    def _parse_iso_datetime(self, value: Optional[str]) -> Optional[datetime]:
        """Parse ISO timestamp used by evolution request filters."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None

    def _build_time_window(
        self,
        days_back: int,
        lookback_hours: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> Tuple[datetime, datetime]:
        """Build inclusive time window for session discovery."""
        now = datetime.now()
        end_dt = self._parse_iso_datetime(end_time) or now
        if lookback_hours is not None and lookback_hours > 0:
            start_dt = end_dt - timedelta(hours=lookback_hours)
        else:
            start_dt = self._parse_iso_datetime(start_time) or (end_dt - timedelta(days=days_back))

        # Guard against inverted windows from bad input.
        if start_dt > end_dt:
            start_dt, end_dt = end_dt, start_dt

        # Normalize tz-aware timestamps to naive local datetimes for mtime comparison.
        if start_dt.tzinfo is not None:
            start_dt = start_dt.astimezone().replace(tzinfo=None)
        if end_dt.tzinfo is not None:
            end_dt = end_dt.astimezone().replace(tzinfo=None)
        return start_dt, end_dt

    def _is_in_window(self, dt: datetime, start_dt: datetime, end_dt: datetime) -> bool:
        """Return True when datetime falls in inclusive analysis window."""
        return start_dt <= dt <= end_dt
    
    def discover_sessions(
        self,
        days_back: int = 30,
        lookback_hours: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        max_sessions: Optional[int] = None,
    ) -> List[Path]:
        """
        Discover all session files from the past N days.
        
        Args:
            days_back: How many days of history to analyze
            
        Returns:
            List of paths to .jsonl session files
        """
        session_files: List[Path] = []
        start_dt, end_dt = self._build_time_window(
            days_back=days_back,
            lookback_hours=lookback_hours,
            start_time=start_time,
            end_time=end_time,
        )
        
        # Search all workspaces: {tenant}/{agent_or_agents_dir}/memory/history/{date}/*.jsonl
        if not self.workspaces_dir.exists():
            return session_files
        
        for tenant_dir in self.workspaces_dir.iterdir():
            if not tenant_dir.is_dir():
                continue
            
            # Support both flat layout (tenant/agent/) and nested (tenant/agents/agent/)
            agent_dirs = []
            agents_subdir = tenant_dir / "agents"
            if agents_subdir.is_dir():
                agent_dirs.extend([d for d in agents_subdir.iterdir() if d.is_dir()])
            # Also check flat layout (legacy workspaces/tenant/agent/)
            for d in tenant_dir.iterdir():
                if d.is_dir() and d.name != "agents":
                    if (d / "memory").is_dir():
                        agent_dirs.append(d)
            
            for agent_dir in agent_dirs:
                
                history_dir = agent_dir / "memory" / "history"
                if not history_dir.exists():
                    continue
                
                # Each subdirectory is a date: YYYY-MM-DD
                for date_dir in history_dir.iterdir():
                    if not date_dir.is_dir():
                        continue
                    
                    try:
                        dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d")
                        if (dir_date + timedelta(days=1)) < start_dt or dir_date > end_dt:
                            continue  # Skip old sessions
                    except ValueError:
                        continue  # Invalid date format
                    
                    for jsonl_file in date_dir.glob("*.jsonl"):
                        file_dt = datetime.fromtimestamp(jsonl_file.stat().st_mtime)
                        if self._is_in_window(file_dt, start_dt, end_dt):
                            session_files.append(jsonl_file)
        
        # Also check alternative location: outputs/sessions/*.jsonl (if exists)
        alt_sessions = self.workspace_root / "outputs" / "sessions"
        if alt_sessions.exists():
            for jsonl_file in alt_sessions.glob("*.jsonl"):
                file_dt = datetime.fromtimestamp(jsonl_file.stat().st_mtime)
                if self._is_in_window(file_dt, start_dt, end_dt):
                    session_files.append(jsonl_file)

        # Deterministic ordering from newest to oldest.
        session_files.sort(key=lambda p: (p.stat().st_mtime, str(p)), reverse=True)
        
        # Apply safety limit
        limit = max_sessions if max_sessions and max_sessions > 0 else self.MAX_SESSIONS
        if len(session_files) > limit:
            session_files = session_files[:limit]
        
        return session_files
    
    def load_session(self, file_path: Path) -> Optional[Session]:
        """
        Load a single session from JSONL file.
        
        Args:
            file_path: Path to .jsonl session file
            
        Returns:
            Session object or None if failed
        """
        try:
            turns = []
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        turns.append(SessionTurn.from_dict(data))
                    except json.JSONDecodeError:
                        continue
            
            if not turns:
                return None
            
            session_id = file_path.stem
            user_id = turns[0].user_id if turns else "unknown"
            date = file_path.parent.name  # Date directory name
            
            return Session(
                session_id=session_id,
                user_id=user_id,
                date=date,
                turns=turns,
                file_path=str(file_path)
            )
        
        except Exception as e:
            logger.error("⚠️  Failed to load session %s: %s", file_path, e)
            return None
    
    def load_all_sessions(
        self,
        days_back: int = 30,
        lookback_hours: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        max_sessions: Optional[int] = None,
    ) -> List[Session]:
        """
        Load all sessions from the past N days.
        
        Args:
            days_back: How many days of history to analyze
            
        Returns:
            List of Session objects
        """
        session_files = self.discover_sessions(
            days_back=days_back,
            lookback_hours=lookback_hours,
            start_time=start_time,
            end_time=end_time,
            max_sessions=max_sessions,
        )
        sessions = []
        
        for file_path in session_files:
            session = self.load_session(file_path)
            if session and session.turn_count > 0:
                sessions.append(session)
        
        return sessions
    
    def chunk_sessions(self, sessions: List[Session]) -> List[List[Session]]:
        """
        Split sessions into chunks for LLM processing.
        
        Args:
            sessions: List of all sessions
            
        Returns:
            List of session chunks (each chunk has max SESSIONS_PER_CHUNK sessions)
        """
        chunks = []
        for i in range(0, len(sessions), self.SESSIONS_PER_CHUNK):
            chunk = sessions[i:i + self.SESSIONS_PER_CHUNK]
            chunks.append(chunk)
        return chunks
    
    def sessions_to_text(self, sessions: List[Session], max_chars: int = 30000) -> str:
        """
        Convert session chunk to text for LLM analysis.
        
        Args:
            sessions: List of sessions in chunk
            max_chars: Maximum total characters
            
        Returns:
            Formatted text for LLM
        """
        parts = []
        total_chars = 0
        chars_per = max_chars // len(sessions) if sessions else 2000
        
        for session in sessions:
            session_text = session.to_text(max_chars=min(chars_per, self.CHARS_PER_SESSION))
            if total_chars + len(session_text) > max_chars:
                parts.append("... [more sessions truncated]")
                break
            parts.append(session_text)
            parts.append("-" * 40)
            total_chars += len(session_text) + 42
        
        return "\n".join(parts)
    
    def get_stats(self, sessions: List[Session]) -> Dict[str, Any]:
        """
        Calculate statistics about loaded sessions.
        
        Args:
            sessions: List of sessions
            
        Returns:
            Statistics dictionary
        """
        if not sessions:
            return {
                "total_sessions": 0,
                "total_turns": 0,
                "unique_users": 0,
                "skills_used": {},
                "date_range": {"start": None, "end": None}
            }
        
        all_skills = {}
        all_users = set()
        total_turns = 0
        dates = []
        
        for session in sessions:
            total_turns += session.turn_count
            all_users.add(session.user_id)
            if session.date:
                dates.append(session.date)
            
            for skill in session.skills_used:
                all_skills[skill] = all_skills.get(skill, 0) + 1
        
        dates.sort()
        
        return {
            "total_sessions": len(sessions),
            "total_turns": total_turns,
            "unique_users": len(all_users),
            "skills_used": all_skills,
            "date_range": {
                "start": dates[0] if dates else None,
                "end": dates[-1] if dates else None
            }
        }



# Classification prompts
CLASSIFY_SYSTEM_PROMPT = """You are an expert at analyzing AI assistant conversations to identify issues and gaps.

Analyze the provided conversation sessions and classify each one into categories:
- "successful": User request was handled well
- "skill_gap": User asked for capability we don't have
- "routing_issue": Query was routed to wrong skill
- "tool_failure": Tool execution failed
- "user_friction": User showed frustration or confusion
- "quality_issue": Response quality was poor

Return JSON in this exact format:
{
    "classifications": [
        {
            "session_id": "...",
            "category": "successful|skill_gap|routing_issue|tool_failure|user_friction|quality_issue",
            "confidence": 0.0-1.0,
            "evidence": "Brief explanation"
        }
    ],
    "high_value_sessions": ["session_id1", "session_id2"],
    "patterns_observed": ["pattern1", "pattern2"]
}

Focus on identifying sessions that reveal system weaknesses or improvement opportunities.
Mark sessions as "high_value" if they contain clear gaps or issues worth investigating."""

ANALYZE_SYSTEM_PROMPT = """You are an expert at deep analysis of AI assistant conversations.

Each session turn now includes enriched signals beyond just the conversation text:
- Tools: which tools ran and whether they errored
- Memory lookups: query_memory calls and whether they returned results
- Context files: which .md files were loaded by the agent
- Routing confidence: how confident the router was + whether signals agreed
- User feedback: explicit thumbs up/down if captured
- Prior skill: what skill ran before this one

Use ALL of these signals — not just the conversation text — to identify root causes.

Gap types to detect:
- skill_missing: capability doesn't exist at all
- skill_weak: skill exists but prompt is unclear, incomplete, or missing guidance
- prompt_gap: SKILL.md lacks instructions for a specific scenario the agent encountered
- missing_context: agent repeatedly loaded same files manually — should be in skill context_file
- memory_gap: query_memory was not called, or called but returned nothing, for a topic that recurs
- tool_blocked: agent tried a tool pattern that is blocked (e.g. subprocess, network)
- routing_issue: routing confidence low or keyword/LLM signals disagreed
- response_quality: answer was vague, wrong, or user had to re-ask
- user_friction: user showed confusion, repeated themselves, or gave thumbs down
- error_pattern: tool errors appearing consistently across sessions

For each gap, identify which SKILL.md file should be changed and what text to add.

Return JSON:
{
    "gaps": [
        {
            "type": "prompt_gap|missing_context|memory_gap|tool_blocked|routing_issue|skill_missing|skill_weak|response_quality|user_friction|error_pattern",
            "description": "Clear explanation of the root cause",
            "evidence": ["session:id:signal", ...],
            "frequency": 3,
            "severity": "high|medium|low|critical",
            "skill_file": "skills/invoice/SKILL.md",
            "suggested_addition": "Exact text or instruction to add to that skill file"
        }
    ],
    "summary": "Overall assessment of system health"
}

Be specific and actionable. Always populate skill_file and suggested_addition when the fix is a prompt change."""


@dataclass
class ClassificationResult:
    """Result of session classification."""
    session_id: str
    category: str
    confidence: float
    evidence: str
    
    @classmethod
    def from_dict(cls, data: dict) -> "ClassificationResult":
        return cls(
            session_id=data.get("session_id", ""),
            category=data.get("category", "unknown"),
            confidence=data.get("confidence", 0.5),
            evidence=data.get("evidence", "")
        )


class SessionClassifier:
    """
    Classifies sessions using LLM to identify issues.
    
    Two-phase classification:
    1. Light pass with gpt-4o-mini: Quick classification of all sessions
    2. Deep analysis with gpt-4o: Detailed analysis of high-value sessions
    """
    
    def __init__(self, llm=None, light_llm=None, cache=None):
        """
        Initialize classifier.
        
        Args:
            llm: Main LLM (gpt-4o) for deep analysis
            light_llm: Light LLM (gpt-4o-mini) for classification
            cache: EvolutionCache for caching LLM responses
        """
        self.llm = llm
        self.light_llm = light_llm or llm
        self.cache = cache
    
    async def classify_chunk(self, sessions: List[Session], use_light: bool = True) -> List[ClassificationResult]:
        """
        Classify a chunk of sessions.
        
        Args:
            sessions: List of sessions to classify
            use_light: Whether to use light LLM (default True)
            
        Returns:
            List of classification results
        """
        if not self.light_llm and not self.llm:
            # No LLM configured - return mock classifications
            return [
                ClassificationResult(
                    session_id=s.session_id,
                    category="unknown",
                    confidence=0.0,
                    evidence="No LLM configured"
                )
                for s in sessions
            ]
        
        loader = SessionLoader(Path("."))  # Just for text conversion
        session_text = loader.sessions_to_text(sessions, max_chars=25000)
        prompt_content = f"classify_sessions:{session_text}"
        
        if self.cache:
            cached = await self.cache.get_llm_cache(prompt_content)
            if cached:
                return [ClassificationResult.from_dict(c) for c in cached.get("classifications", [])]
        
        llm = self.light_llm if use_light else self.llm
        
        try:
            messages = [
                {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
                {"role": "user", "content": f"Analyze these sessions:\n\n{session_text}"}
            ]
            
            # Handle different LLM client interfaces
            if hasattr(llm, 'invoke'):
                # LangChain style
                response = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: llm.invoke(messages)
                )
                try:
                    import llm_tracker as _lt
                    _lt.record("evolution", response, 0.0, getattr(llm, 'azure_deployment', getattr(llm, 'model_name', '')))
                except Exception:
                    pass
                content = response.content if hasattr(response, 'content') else str(response)
            elif hasattr(llm, 'chat_completion'):
                # Custom async client
                response = await llm.chat_completion(messages)
                content = response if isinstance(response, str) else json.dumps(response)
            else:
                # Callable
                response = llm(messages)
                content = response if isinstance(response, str) else str(response)
            
            # Parse JSON response
            # Extract JSON from response (may have markdown code blocks)
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            data = json.loads(content.strip())
            
            # Cache the result
            if self.cache:
                await self.cache.set_llm_cache(prompt_content, data)
            
            return [
                ClassificationResult.from_dict(c)
                for c in data.get("classifications", [])
            ]
            
        except Exception as e:
            logger.error("⚠️  Classification failed: %s", e)
            return [
                ClassificationResult(
                    session_id=s.session_id,
                    category="error",
                    confidence=0.0,
                    evidence=str(e)
                )
                for s in sessions
            ]
    
    async def classify_all(
        self, 
        sessions: List[Session],
        chunk_size: int = 15
    ) -> Tuple[List[ClassificationResult], List[str]]:
        """
        Classify all sessions, returning classifications and high-value session IDs.
        
        Args:
            sessions: All sessions to classify
            chunk_size: Sessions per LLM call
            
        Returns:
            Tuple of (all classifications, high-value session IDs)
        """
        all_results = []
        high_value = []
        
        # Chunk sessions
        chunks = [sessions[i:i+chunk_size] for i in range(0, len(sessions), chunk_size)]
        
        for i, chunk in enumerate(chunks):
            logger.debug("  📊 Classifying chunk %d/%d...", i+1, len(chunks))
            results = await self.classify_chunk(chunk, use_light=True)
            all_results.extend(results)
            
            # Collect high-value sessions
            for r in results:
                if r.category in ["skill_gap", "routing_issue", "tool_failure", "user_friction"]:
                    high_value.append(r.session_id)
        
        return all_results, high_value
    
    async def deep_analyze(self, sessions: List[Session]) -> List[Gap]:
        """
        Deep analyze high-value sessions to extract specific gaps.
        
        Args:
            sessions: High-value sessions to analyze
            
        Returns:
            List of detected gaps
        """
        if not self.llm:
            return []
        
        if not sessions:
            return []
        
        loader = SessionLoader(Path("."))
        session_text = loader.sessions_to_text(sessions, max_chars=25000)
        prompt_content = f"deep_analyze:{session_text}"
        
        if self.cache:
            cached = await self.cache.get_llm_cache(prompt_content)
            if cached:
                gaps = []
                for g in cached.get("gaps", []):
                    gap_type = g.get("type", "unknown")
                    try:
                        gap_type = GapType(gap_type)
                    except ValueError:
                        gap_type = GapType.SKILL_MISSING
                    gaps.append(Gap(
                        type=gap_type,
                        description=g.get("description", ""),
                        evidence=g.get("evidence", []),
                        frequency=g.get("frequency", 1),
                        severity=g.get("severity", "medium"),
                        skill_file=g.get("skill_file"),
                        suggested_addition=g.get("suggested_addition"),
                    ))
                return gaps

        try:
            messages = [
                {"role": "system", "content": ANALYZE_SYSTEM_PROMPT},
                {"role": "user", "content": f"Deep analyze these sessions:\n\n{session_text}"}
            ]
            
            if hasattr(self.llm, 'invoke'):
                response = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.llm.invoke(messages)
                )
                try:
                    import llm_tracker as _lt
                    _lt.record("evolution", response, 0.0, getattr(self.llm, 'azure_deployment', getattr(self.llm, 'model_name', '')))
                except Exception:
                    pass
                content = response.content if hasattr(response, 'content') else str(response)
            elif hasattr(self.llm, 'chat_completion'):
                response = await self.llm.chat_completion(messages)
                content = response if isinstance(response, str) else json.dumps(response)
            else:
                response = self.llm(messages)
                content = response if isinstance(response, str) else str(response)
            
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            data = json.loads(content.strip())
            
            # Cache the result
            if self.cache:
                await self.cache.set_llm_cache(prompt_content, data)
            
            gaps = []
            for g in data.get("gaps", []):
                gap_type = g.get("type", "unknown")
                try:
                    gap_type = GapType(gap_type)
                except ValueError:
                    gap_type = GapType.SKILL_MISSING  # Default

                gaps.append(Gap(
                    type=gap_type,
                    description=g.get("description", ""),
                    evidence=g.get("evidence", []),
                    frequency=g.get("frequency", 1),
                    severity=g.get("severity", "medium"),
                    skill_file=g.get("skill_file"),
                    suggested_addition=g.get("suggested_addition"),
                ))

            return gaps
            
        except Exception as e:
            logger.error("⚠️  Deep analysis failed: %s", e)
            return []



SKILL_ANALYSIS_PROMPT = """You are an expert at reviewing AI agent skill prompt files (SKILL.md).

Each SKILL.md defines a skill's purpose, routing keywords, context file, tool usage, and instructions.

For each skill file, evaluate:
1. Clarity — are instructions unambiguous and specific enough for the agent to follow?
2. Context file — is context_file declared and pointing to the right .md file?
3. Keywords — are routing keywords comprehensive, specific, and free from ambiguity?
4. Tool guidance — does the prompt tell the agent WHICH tools to use and HOW (e.g. use shell grep, not subprocess)?
5. Edge cases — does it handle common failure scenarios (no results, blocked tools, missing data)?
6. Memory guidance — does it instruct the agent when to call query_memory before falling back to shell?
7. Output format — is expected output format (table, bullet, summary) specified?

Focus on practical prompt engineering gaps — things that would cause the agent to give wrong, incomplete, or inefficient answers.

Return JSON:
{
    "code_issues": [
        {
            "file": "skills/invoice/SKILL.md",
            "issue": "Missing guidance for late payment fee lookups — agent falls back to manual grep instead of query_memory",
            "severity": "high",
            "suggestion": "Add: For vendor payment terms and late fees, always call query_memory first with the vendor name, then grep /local/AP_Policy.md if needed"
        }
    ],
    "skill_coverage": {
        "existing": ["invoice", "ar_ops"],
        "suggested": ["vendor_onboarding", "payment_reconciliation"]
    },
    "summary": "Overall skill prompt quality assessment"
}

Be specific. Every issue must name the exact skill file and provide actionable suggested_addition text."""


CODE_ANALYSIS_PROMPT = """You are an expert code reviewer analyzing an AI agent system.

Review the provided code files from an AI assistant platform and identify:
1. Missing capabilities based on the SKILL.md files
2. Routing logic issues in router.py
3. Error handling gaps in agent.py and execution.py
4. Tool limitations or missing tools
5. Configuration issues

A section labelled "=== RUNTIME ERRORS (server.log) ===" may appear at the end of the
provided content. If present, use it to PRIORITISE issues — errors that are actually
firing in production (high repeat count) should be rated critical or high severity even
if the code looks superficially correct. Static issues not reflected in the runtime log
can still be included but at lower severity.

For each issue found, provide:
- file: The file path
- issue: Description of the problem (reference the log count if relevant, e.g. "firing 47x/day")
- severity: critical, high, medium, low
- suggestion: How to fix it

Return JSON:
{
    "code_issues": [
        {
            "file": "router.py",
            "line_hint": "around line 50",
            "issue": "No fallback for unmatched queries",
            "severity": "medium",
            "suggestion": "Add semantic similarity fallback"
        }
    ],
    "skill_coverage": {
        "existing": ["invoice-analyzer", "email-sender"],
        "suggested": ["forecasting", "reconciliation"]
    },
    "summary": "Overall code health assessment"
}"""


@dataclass
class CodeFile:
    """Represents a code file for analysis."""
    path: str
    relative_path: str
    content: str
    file_type: str  # skill, agent, router, kernel, tool, server
    
    @property
    def char_count(self) -> int:
        return len(self.content)
    
    def get_chunk(self, start: int, max_chars: int) -> str:
        """Get a chunk of the file content."""
        return self.content[start:start + max_chars]


@dataclass
class CodeIssue:
    """A detected code issue."""
    file: str
    issue: str
    severity: str
    suggestion: str
    line_hint: str = ""
    
    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "issue": self.issue,
            "severity": self.severity,
            "suggestion": self.suggestion,
            "line_hint": self.line_hint
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "CodeIssue":
        return cls(
            file=data.get("file", ""),
            issue=data.get("issue", ""),
            severity=data.get("severity", "medium"),
            suggestion=data.get("suggestion", ""),
            line_hint=data.get("line_hint", "")
        )


class CodeAnalyzer:
    """
    Analyzes codebase using LLM to identify issues.
    
    Covers:
    - skills/*.md (SKILL.md files)
    - iaf_agent_skills/*.py (agent, router, memory, execution)
    - agent_os/*.py (kernel, sandbox) if accessible
    - server.py
    - tools/*.py
    """
    
    # Tier 3a — SKILL.md files only
    SKILL_FILE_PATTERNS = {
        "skill": "skills/**/SKILL.md",
    }

    # Tier 3b — core Python code only
    CODE_FILE_PATTERNS = {
        "agent":     "iaf_agent_skills/agent.py",
        "router":    "iaf_agent_skills/router.py",
        "memory":    "iaf_agent_skills/memory.py",
        "execution": "iaf_agent_skills/execution.py",
        "loader":    "iaf_agent_skills/loader.py",
        "queue":     "iaf_agent_skills/queue_manager.py",
        "server":    "server.py",
        "tools":     "iaf_agent_skills/tools/*.py",
    }

    # Default (Tier 3 combined) — both skill + code
    FILE_PATTERNS = {**SKILL_FILE_PATTERNS, **CODE_FILE_PATTERNS}
    
    # Chunking limits
    MAX_CHARS_PER_FILE = 12000  # ~8K tokens
    MAX_CHARS_TOTAL = 50000    # For combined analysis
    
    def __init__(self, workspace_root: Path, llm=None, cache=None, patterns=None):
        """
        Initialize code analyzer.

        Args:
            workspace_root: Path to IAF-Agent-Skills directory
            llm: LLM for code analysis (gpt-4o)
            cache: EvolutionCache for caching LLM responses
            patterns: Optional file pattern dict override (use SKILL_FILE_PATTERNS or CODE_FILE_PATTERNS)
        """
        self.workspace_root = Path(workspace_root)
        self.llm = llm
        self.cache = cache
        if patterns is not None:
            self.FILE_PATTERNS = patterns
    
    def discover_files(self) -> List[CodeFile]:
        """
        Discover all relevant code files.
        
        Returns:
            List of CodeFile objects
        """
        code_files = []
        
        for file_type, pattern in self.FILE_PATTERNS.items():
            if "**" in pattern or "*" in pattern:
                # Glob pattern
                matches = list(self.workspace_root.glob(pattern))
            else:
                # Direct path
                path = self.workspace_root / pattern
                matches = [path] if path.exists() else []
            
            for file_path in matches:
                if not file_path.is_file():
                    continue
                
                try:
                    content = file_path.read_text(encoding='utf-8')
                    relative_path = str(file_path.relative_to(self.workspace_root))
                    
                    code_files.append(CodeFile(
                        path=str(file_path),
                        relative_path=relative_path,
                        content=content,
                        file_type=file_type
                    ))
                except Exception as e:
                    logger.error("⚠️  Failed to read %s: %s", file_path, e)
        
        return code_files
    
    def get_skills_summary(self, code_files: List[CodeFile]) -> str:
        """
        Get a summary of all SKILL.md files.
        
        Args:
            code_files: All code files
            
        Returns:
            Summary text of skills
        """
        skill_files = [f for f in code_files if f.file_type == "skill"]
        
        parts = ["=== SKILLS SUMMARY ===\n"]
        for sf in skill_files:
            skill_name = Path(sf.relative_path).parent.name
            # Extract triggers and description
            content = sf.content[:1000]  # First 1000 chars
            parts.append(f"Skill: {skill_name}\n{content}\n---\n")
        
        return "\n".join(parts)
    
    def chunk_code_files(self, code_files: List[CodeFile]) -> List[List[CodeFile]]:
        """
        Chunk code files to stay within LLM context limits.
        
        Args:
            code_files: All code files
            
        Returns:
            List of file chunks
        """
        chunks = []
        current_chunk = []
        current_size = 0
        
        for cf in code_files:
            file_size = min(cf.char_count, self.MAX_CHARS_PER_FILE)
            
            if current_size + file_size > self.MAX_CHARS_TOTAL:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = [cf]
                current_size = file_size
            else:
                current_chunk.append(cf)
                current_size += file_size
        
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks
    
    def files_to_text(self, code_files: List[CodeFile]) -> str:
        """
        Convert code files to text for LLM analysis.
        
        Args:
            code_files: Files to convert
            
        Returns:
            Formatted text
        """
        parts = []
        
        for cf in code_files:
            truncated = cf.content[:self.MAX_CHARS_PER_FILE]
            if len(cf.content) > self.MAX_CHARS_PER_FILE:
                truncated += "\n... [truncated]"
            
            parts.append(f"=== FILE: {cf.relative_path} ({cf.file_type}) ===")
            parts.append(truncated)
            parts.append("-" * 60)
        
        return "\n".join(parts)
    
    async def analyze(self, code_files: List[CodeFile] = None, prompt: str = None, force_fresh: bool = False) -> Tuple[List[CodeIssue], Dict[str, Any]]:
        """
        Analyze code files for issues.

        Args:
            code_files: Files to analyze (discovers if None)
            prompt: System prompt override (use SKILL_ANALYSIS_PROMPT for Tier 3a)
            force_fresh: If True, bypass LLM response cache and force re-analysis

        Returns:
            Tuple of (issues, skill_coverage)
        """
        if code_files is None:
            code_files = self.discover_files()
        
        if not code_files:
            return [], {}
        
        if not self.llm:
            # No LLM - return basic analysis
            skill_files = [f for f in code_files if f.file_type == "skill"]
            return [], {
                "existing": [Path(f.relative_path).parent.name for f in skill_files],
                "suggested": [],
                "files_analyzed": len(code_files)
            }
        
        all_issues = []
        skill_coverage = {}
        system_prompt = prompt or CODE_ANALYSIS_PROMPT
        cache_prefix = "skill_analysis" if prompt == SKILL_ANALYSIS_PROMPT else "code_analysis"

        # Chunk files
        chunks = self.chunk_code_files(code_files)

        for i, chunk in enumerate(chunks):
            label = "skill" if prompt == SKILL_ANALYSIS_PROMPT else "code"
            logger.debug("  📝 Analyzing %s chunk %d/%d...", label, i+1, len(chunks))

            code_text = self.files_to_text(chunk)
            prompt_content = f"{cache_prefix}:{code_text[:5000]}"  # Hash first 5K

            # Check cache first (skip if force_fresh requested)
            if self.cache and not force_fresh:
                cached = await self.cache.get_llm_cache(prompt_content)
                if cached:
                    for issue in cached.get("code_issues", []):
                        all_issues.append(CodeIssue.from_dict(issue))
                    if "skill_coverage" in cached:
                        for key in ["existing", "suggested"]:
                            if key not in skill_coverage:
                                skill_coverage[key] = []
                            skill_coverage[key].extend(cached["skill_coverage"].get(key, []))
                    continue

            try:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Analyze this code:\n\n{code_text}"}
                ]
                
                if hasattr(self.llm, 'invoke'):
                    response = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: self.llm.invoke(messages)
                    )
                    try:
                        import llm_tracker as _lt
                        _lt.record("evolution", response, 0.0, getattr(self.llm, 'azure_deployment', getattr(self.llm, 'model_name', '')))
                    except Exception:
                        pass
                    content = response.content if hasattr(response, 'content') else str(response)
                elif hasattr(self.llm, 'chat_completion'):
                    response = await self.llm.chat_completion(messages)
                    content = response if isinstance(response, str) else json.dumps(response)
                else:
                    response = self.llm(messages)
                    content = response if isinstance(response, str) else str(response)
                
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]
                
                data = json.loads(content.strip())
                
                # Cache the result
                if self.cache:
                    await self.cache.set_llm_cache(prompt_content, data)
                
                for issue in data.get("code_issues", []):
                    all_issues.append(CodeIssue.from_dict(issue))
                
                if "skill_coverage" in data:
                    for key in ["existing", "suggested"]:
                        if key not in skill_coverage:
                            skill_coverage[key] = []
                        skill_coverage[key].extend(data["skill_coverage"].get(key, []))
                
            except Exception as e:
                logger.error("⚠️  Code analysis chunk %d failed: %s", i+1, e)
        
        # Deduplicate
        skill_coverage["existing"] = list(set(skill_coverage.get("existing", [])))
        skill_coverage["suggested"] = list(set(skill_coverage.get("suggested", [])))
        skill_coverage["files_analyzed"] = len(code_files)
        
        return all_issues, skill_coverage
    
    def get_stats(self, code_files: List[CodeFile]) -> Dict[str, Any]:
        """
        Get statistics about discovered code files.
        
        Args:
            code_files: Code files
            
        Returns:
            Statistics dictionary
        """
        by_type = {}
        total_chars = 0
        
        for cf in code_files:
            if cf.file_type not in by_type:
                by_type[cf.file_type] = []
            by_type[cf.file_type].append(cf.relative_path)
            total_chars += cf.char_count
        
        return {
            "total_files": len(code_files),
            "total_chars": total_chars,
            "by_type": by_type
        }



IMPROVEMENT_PROMPT = """You are an expert at suggesting improvements for AI assistant systems.

Based on the analyzed gaps and code issues, generate specific, actionable improvements.

For each improvement, provide:
- id: Unique ID (IMP-001, IMP-002, etc.)
- type: new_skill, enhance_skill, add_trigger, fix_code, add_tool, improve_routing
- title: Short descriptive title
- description: Detailed explanation
- priority: critical, high, medium, low
- effort: low (< 1 day), medium (1-3 days), high (> 3 days)
- related_gaps: Which gaps this addresses
- code_snippet: Example implementation (if applicable)
- file_path: Where to implement (if applicable)

Return JSON:
{
    "improvements": [
        {
            "id": "IMP-001",
            "type": "new_skill",
            "title": "Add forecasting skill",
            "description": "Create a new skill for cash flow and payment forecasting",
            "priority": "high",
            "effort": "medium",
            "related_gaps": ["Cash flow forecasting requested"],
            "code_snippet": "# skills/forecasting/SKILL.md\\n## Triggers\\n- forecast\\n- predict",
            "file_path": "skills/forecasting/SKILL.md"
        }
    ],
    "summary": "Overall recommendations"
}

Focus on high-impact, practical improvements. Prioritize gaps with high frequency or severity."""


class ImprovementGenerator:
    """
    Generates improvement suggestions from gaps and code issues.
    """
    
    def __init__(self, llm=None, cache=None):
        """
        Initialize improvement generator.
        
        Args:
            llm: LLM for generating improvements (gpt-4o)
            cache: EvolutionCache for caching LLM responses
        """
        self.llm = llm
        self.cache = cache
    
    async def generate(
        self, 
        gaps: List[Gap], 
        code_issues: List[CodeIssue] = None,
        skill_coverage: Dict[str, Any] = None
    ) -> List[Improvement]:
        """
        Generate improvements from gaps and issues.
        
        Args:
            gaps: Detected gaps from sessions
            code_issues: Detected code issues
            skill_coverage: Information about existing skills
            
        Returns:
            List of suggested improvements
        """
        if not self.llm:
            # No LLM - generate basic improvements from gaps
            improvements = []
            for i, gap in enumerate(gaps[:5]):  # Limit to 5
                imp_type = "new_skill" if gap.type == GapType.SKILL_MISSING else "enhance_skill"
                priority = Priority.HIGH if gap.severity == "high" else Priority.MEDIUM
                
                improvements.append(Improvement(
                    id=f"IMP-{i+1:03d}",
                    type=imp_type,
                    title=f"Address: {gap.description[:50]}...",
                    description=gap.description,
                    priority=priority,
                    effort="medium",
                    related_gaps=[gap.description]
                ))
            
            return improvements
        
        context_parts = ["=== GAPS FROM SESSION ANALYSIS ===\n"]
        for gap in gaps:
            context_parts.append(f"- [{gap.severity}] {gap.type}: {gap.description}")
            if gap.evidence:
                context_parts.append(f"  Evidence: {gap.evidence[:3]}")
        
        if code_issues:
            context_parts.append("\n=== CODE ISSUES ===\n")
            for ci in code_issues:
                context_parts.append(f"- [{ci.severity}] {ci.file}: {ci.issue}")
                context_parts.append(f"  Suggestion: {ci.suggestion}")
        
        if skill_coverage:
            context_parts.append("\n=== SKILL COVERAGE ===\n")
            context_parts.append(f"Existing skills: {skill_coverage.get('existing', [])}")
            context_parts.append(f"Suggested skills: {skill_coverage.get('suggested', [])}")
        
        context = "\n".join(context_parts)
        prompt_content = f"generate_improvements:{context[:5000]}"  # Hash first 5K
        
        if self.cache:
            cached = await self.cache.get_llm_cache(prompt_content)
            if cached:
                improvements = []
                for imp in cached.get("improvements", []):
                    priority_str = imp.get("priority", "medium")
                    try:
                        priority = Priority(priority_str)
                    except ValueError:
                        priority = Priority.MEDIUM
                    improvements.append(Improvement(
                        id=imp.get("id", f"IMP-{len(improvements)+1:03d}"),
                        type=imp.get("type", "enhance_skill"),
                        title=imp.get("title", ""),
                        description=imp.get("description", ""),
                        priority=priority,
                        effort=imp.get("effort", "medium"),
                        related_gaps=imp.get("related_gaps", []),
                        code_snippet=imp.get("code_snippet"),
                        file_path=imp.get("file_path")
                    ))
                return improvements
        
        try:
            messages = [
                {"role": "system", "content": IMPROVEMENT_PROMPT},
                {"role": "user", "content": f"Generate improvements based on:\n\n{context}"}
            ]
            
            if hasattr(self.llm, 'invoke'):
                response = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.llm.invoke(messages)
                )
                try:
                    import llm_tracker as _lt
                    _lt.record("evolution", response, 0.0, getattr(self.llm, 'azure_deployment', getattr(self.llm, 'model_name', '')))
                except Exception:
                    pass
                content = response.content if hasattr(response, 'content') else str(response)
            elif hasattr(self.llm, 'chat_completion'):
                response = await self.llm.chat_completion(messages)
                content = response if isinstance(response, str) else json.dumps(response)
            else:
                response = self.llm(messages)
                content = response if isinstance(response, str) else str(response)

            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            data = json.loads(content.strip())
            
            # Cache the result
            if self.cache:
                await self.cache.set_llm_cache(prompt_content, data)
            
            improvements = []
            for imp in data.get("improvements", []):
                priority_str = imp.get("priority", "medium")
                try:
                    priority = Priority(priority_str)
                except ValueError:
                    priority = Priority.MEDIUM
                
                improvements.append(Improvement(
                    id=imp.get("id", f"IMP-{len(improvements)+1:03d}"),
                    type=imp.get("type", "enhance_skill"),
                    title=imp.get("title", ""),
                    description=imp.get("description", ""),
                    priority=priority,
                    effort=imp.get("effort", "medium"),
                    related_gaps=imp.get("related_gaps", []),
                    code_snippet=imp.get("code_snippet"),
                    file_path=imp.get("file_path")
                ))
            
            return improvements
            
        except Exception as e:
            logger.error("⚠️  Improvement generation failed: %s", e)
            return []



class EvolutionCache:
    """
    Redis-based caching for evolution analysis.
    
    Cache Keys:
    - evolution:job:{job_id} - Job status and progress
    - evolution:report:{job_id} - Full report JSON
    - evolution:cache:llm:{hash} - LLM response cache (24h TTL)
    """
    
    CACHE_TTL = 86400  # 24 hours for LLM responses
    JOB_TTL = 604800   # 7 days for job data
    
    def __init__(self, redis_client=None):
        """
        Initialize cache.
        
        Args:
            redis_client: Redis client (async or sync)
        """
        self.redis = redis_client
    
    def _hash_content(self, content: str) -> str:
        """Create hash of content for cache key."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    async def get_llm_cache(self, prompt_content: str) -> Optional[Dict]:
        """
        Get cached LLM response.
        
        Args:
            prompt_content: The prompt content to hash
            
        Returns:
            Cached response or None
        """
        if not self.redis:
            return None
        
        cache_key = f"evolution:cache:llm:{self._hash_content(prompt_content)}"
        
        try:
            if hasattr(self.redis, 'get'):
                # Async or sync Redis
                result = self.redis.get(cache_key)
                if asyncio.iscoroutine(result):
                    result = await result
                
                if result:
                    return json.loads(result)
        except Exception as e:
            logger.error("⚠️  Cache read failed: %s", e)

        return None
    
    async def set_llm_cache(self, prompt_content: str, response: Dict):
        """
        Cache LLM response.
        
        Args:
            prompt_content: The prompt content to hash
            response: Response to cache
        """
        if not self.redis:
            return
        
        cache_key = f"evolution:cache:llm:{self._hash_content(prompt_content)}"
        
        try:
            if hasattr(self.redis, 'set'):
                result = self.redis.set(cache_key, json.dumps(response), ex=self.CACHE_TTL)
                if asyncio.iscoroutine(result):
                    await result
        except Exception as e:
            logger.error("⚠️  Cache write failed: %s", e)
    
    async def save_job(self, job_id: str, status: str, progress: Dict = None):
        """
        Save job status to Redis.
        
        Args:
            job_id: Unique job ID
            status: Current status
            progress: Progress information
        """
        if not self.redis:
            return
        
        job_key = f"evolution:job:{job_id}"
        data = {
            "status": status,
            "progress": progress or {},
            "updated_at": datetime.now().isoformat()
        }
        
        try:
            if hasattr(self.redis, 'set'):
                result = self.redis.set(job_key, json.dumps(data), ex=self.JOB_TTL)
                if asyncio.iscoroutine(result):
                    await result
        except Exception as e:
            logger.error("⚠️  Job save failed: %s", e)
    
    async def get_job(self, job_id: str) -> Optional[Dict]:
        """
        Get job status from Redis.
        
        Args:
            job_id: Job ID
            
        Returns:
            Job data or None
        """
        if not self.redis:
            return None
        
        job_key = f"evolution:job:{job_id}"
        
        try:
            if hasattr(self.redis, 'get'):
                result = self.redis.get(job_key)
                if asyncio.iscoroutine(result):
                    result = await result
                
                if result:
                    return json.loads(result)
        except Exception as e:
            logger.error("⚠️  Job read failed: %s", e)
        
        return None
    
    async def save_report(self, report: EvolutionReport):
        """
        Save full report to Redis.
        
        Args:
            report: Complete evolution report
        """
        if not self.redis:
            return
        
        report_key = f"evolution:report:{report.job_id}"
        
        try:
            if hasattr(self.redis, 'set'):
                result = self.redis.set(report_key, json.dumps(report.to_dict()), ex=self.JOB_TTL)
                if asyncio.iscoroutine(result):
                    await result
        except Exception as e:
            logger.error("⚠️  Report save failed: %s", e)
    
    async def get_report(self, job_id: str) -> Optional[Dict]:
        """
        Get report from Redis.
        
        Args:
            job_id: Job ID
            
        Returns:
            Report dict or None
        """
        if not self.redis:
            return None
        
        report_key = f"evolution:report:{job_id}"
        
        try:
            if hasattr(self.redis, 'get'):
                result = self.redis.get(report_key)
                if asyncio.iscoroutine(result):
                    result = await result
                
                if result:
                    return json.loads(result)
        except Exception as e:
            logger.error("⚠️  Report read failed: %s", e)
        
        return None



class SelfEvolutionEngine:
    """
    Main engine for self-evolution analysis.
    
    Built incrementally:
    - Tier 1: Session loading ✅
    - Tier 2: LLM classification (coming)
    - Tier 3: Code analysis (coming)
    - Tier 4: Improvement generation (coming)
    """
    
    def __init__(
        self,
        workspace_root: str,
        llm = None,
        light_llm = None,
        redis_client = None,
        **kwargs
    ):
        """
        Initialize the evolution engine.
        
        Args:
            workspace_root: Path to IAF-Agent-Skills directory
            llm: Main LLM for deep analysis (gpt-4o)
            light_llm: Light LLM for classification (gpt-4o-mini)
            redis_client: Redis client for caching
        """
        self.workspace_root = Path(workspace_root)
        self.llm = llm
        self.light_llm = light_llm
        self.redis = redis_client

        skills_root = kwargs.get('skills_root')
        self.skills_root = Path(skills_root) if skills_root else self.workspace_root

        # Sub-components — accept optional data_root for enterprise layout
        data_root = kwargs.get('data_root')
        workspaces_dir = Path(data_root) / "tenants" if data_root else None
        self.session_loader = SessionLoader(self.workspace_root, workspaces_dir=workspaces_dir)
        self.cache = EvolutionCache(redis_client) if redis_client else None
        
        # State
        self.current_job_id = None
        self.current_report = None

    @staticmethod
    def _sessions_enabled(sources: Optional[List[str]]) -> bool:
        """Session source stays enabled by default for backward compatibility."""
        if not sources:
            return True
        normalized = {s.strip().lower() for s in sources if isinstance(s, str)}
        return "sessions" in normalized
    
    def generate_job_id(self) -> str:
        """Generate unique job ID."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        random_suffix = hashlib.sha256(os.urandom(8)).hexdigest()[:6]
        return f"evolution_{timestamp}_{random_suffix}"
    
    async def _update_status(self, report: EvolutionReport, status: AnalysisStatus, progress: Dict = None):
        """Update report status and cache to Redis."""
        report.status = status
        if self.cache:
            await self.cache.save_job(report.job_id, status.value, progress)
    
    async def _save_report(self, report: EvolutionReport):
        """Save completed report to Redis."""
        if self.cache:
            await self.cache.save_report(report)
    
    async def analyze_tier1_only(
        self,
        days_back: int = 30,
        lookback_hours: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        max_sessions: Optional[int] = None,
        sources: Optional[List[str]] = None,
        **kwargs,
    ) -> EvolutionReport:
        """
        Run Tier 1 analysis only (session loading).
        
        For testing the session loader before adding LLM calls.
        
        Args:
            days_back: Number of days of history to analyze
            
        Returns:
            Partial report with session stats
        """
        job_id = self.generate_job_id()
        report = EvolutionReport(
            job_id=job_id,
            started_at=datetime.now().isoformat(),
            status=AnalysisStatus.LOADING_SESSIONS
        )
        
        self.current_job_id = job_id
        self.current_report = report
        
        try:
            if self._sessions_enabled(sources):
                sessions = self.session_loader.load_all_sessions(
                    days_back=days_back,
                    lookback_hours=lookback_hours,
                    start_time=start_time,
                    end_time=end_time,
                    max_sessions=max_sessions,
                )
            else:
                sessions = []
                report.errors.append("Session source disabled by request.sources")
            report.sessions_analyzed = len(sessions)
            
            stats = self.session_loader.get_stats(sessions)
            
            # For now, return with stats in errors (temp storage)
            report.errors.append(f"Session stats: {json.dumps(stats)}")
            
            report.status = AnalysisStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()
            
        except Exception as e:
            report.status = AnalysisStatus.FAILED
            report.errors.append(str(e))
            report.completed_at = datetime.now().isoformat()
        
        return report
    
    async def analyze_tier2(
        self,
        days_back: int = 30,
        lookback_hours: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        max_sessions: Optional[int] = None,
        sources: Optional[List[str]] = None,
        **kwargs,
    ) -> EvolutionReport:
        """
        Run Tier 1 + Tier 2 analysis (session loading + classification).
        
        Args:
            days_back: Number of days of history to analyze
            
        Returns:
            Report with classifications and gaps
        """
        job_id = self.generate_job_id()
        report = EvolutionReport(
            job_id=job_id,
            started_at=datetime.now().isoformat(),
            status=AnalysisStatus.LOADING_SESSIONS
        )
        
        self.current_job_id = job_id
        self.current_report = report
        
        try:
            # Tier 1: Load sessions
            logger.info("📥 Tier 1: Loading sessions...")
            if self._sessions_enabled(sources):
                sessions = self.session_loader.load_all_sessions(
                    days_back=days_back,
                    lookback_hours=lookback_hours,
                    start_time=start_time,
                    end_time=end_time,
                    max_sessions=max_sessions,
                )
            else:
                sessions = []
                report.errors.append("Session source disabled by request.sources")
            report.sessions_analyzed = len(sessions)
            logger.info("   Found %d sessions", len(sessions))

            if not sessions:
                report.errors.append("No sessions found to analyze")
                report.status = AnalysisStatus.COMPLETED
                report.completed_at = datetime.now().isoformat()
                return report

            # Tier 2: Classify sessions
            logger.info("📊 Tier 2: Classifying sessions...")
            report.status = AnalysisStatus.CLASSIFYING

            classifier = SessionClassifier(llm=self.llm, light_llm=self.light_llm)
            classifications, high_value_ids = await classifier.classify_all(sessions)

            logger.info("   Classified %d sessions", len(classifications))
            logger.info("   Found %d high-value sessions", len(high_value_ids))

            # Deep analyze high-value sessions
            if high_value_ids:
                high_value_sessions = [s for s in sessions if s.session_id in high_value_ids]
                logger.info("🔬 Deep analyzing %d high-value sessions...", len(high_value_sessions))

                gaps = await classifier.deep_analyze(high_value_sessions)
                report.gaps = gaps
                logger.info("   Found %d gaps", len(gaps))
            
            report.status = AnalysisStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()
            
        except Exception as e:
            report.status = AnalysisStatus.FAILED
            report.errors.append(str(e))
            report.completed_at = datetime.now().isoformat()
        
        return report
    
    async def _load_and_classify_sessions(
        self, report, days_back, lookback_hours, start_time, end_time, max_sessions, sources
    ):
        """Shared Tier 1 + Tier 2 logic reused by 3a, 3b, 3, and 4."""
        logger.info("📥 Tier 1: Loading sessions...")
        if self._sessions_enabled(sources):
            sessions = self.session_loader.load_all_sessions(
                days_back=days_back,
                lookback_hours=lookback_hours,
                start_time=start_time,
                end_time=end_time,
                max_sessions=max_sessions,
            )
        else:
            sessions = []
            report.errors.append("Session source disabled by request.sources")
        report.sessions_analyzed = len(sessions)
        logger.info("   Found %d sessions", len(sessions))

        if sessions:
            logger.info("📊 Tier 2: Classifying sessions...")
            report.status = AnalysisStatus.CLASSIFYING
            classifier = SessionClassifier(llm=self.llm, light_llm=self.light_llm, cache=self.cache)
            classifications, high_value_ids = await classifier.classify_all(sessions)
            logger.info("   Classified %d sessions", len(classifications))
            logger.info("   Found %d high-value sessions", len(high_value_ids))
            if high_value_ids:
                high_value_sessions = [s for s in sessions if s.session_id in high_value_ids]
                gaps = await classifier.deep_analyze(high_value_sessions)
                report.gaps.extend(gaps)
                logger.info("   Found %d gaps from sessions", len(gaps))

    def _read_server_log_errors(self, days_back: int = 30) -> str:
        """
        Read ERROR and WARNING lines from logs/server.log (+ server.log.1 if it exists),
        filtered to the analysis time window, deduplicated, and sorted by frequency.

        Returns a compact text block to append to the code files sent to the LLM,
        or an empty string if the log file is not found or is empty.
        """
        import json
        from collections import Counter
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days_back)

        import os as _os
        import re as _re
        _LOG_PATH_RE = _re.compile(r'^[A-Za-z0-9 _/\\:.\-]+$')
        workspace = Path(self.workspace_root)
        candidates = []
        env_log = _os.getenv("SERVER_LOG_PATH")
        if env_log and _LOG_PATH_RE.fullmatch(env_log):
            env_log = env_log.encode("utf-8").decode("utf-8")
            candidates.append(Path(env_log))
        candidates.extend([
            workspace.parent / "IAF-Agent-Studio" / "logs" / "server.log",
            workspace.parent / "logs" / "server.log",
        ])
        log_files = []
        for candidate in candidates:
            if candidate.exists():
                log_files.append(candidate)
                rotated = candidate.parent / (candidate.name + ".1")
                if rotated.exists():
                    log_files.append(rotated)
                break

        if not log_files:
            logger.debug("Tier 3b: server.log not found, skipping runtime error enrichment")
            return ""

        counter: Counter = Counter()   # (level, logger, msg_key) → count
        examples: dict = {}            # same key → first full msg

        for log_file in log_files:
            try:
                with open(log_file, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        level = rec.get("level", "")
                        if level not in ("ERROR", "WARNING", "CRITICAL"):
                            continue
                        # Time filter
                        ts_str = rec.get("ts", "")
                        try:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            if ts < cutoff:
                                continue
                        except Exception:
                            pass  # include if we can't parse the timestamp
                        logger_name = rec.get("logger", "")
                        msg = rec.get("msg", "")
                        # Dedup key: first 80 chars of message (catches repeated same error)
                        msg_key = msg[:80]
                        key = (level, logger_name, msg_key)
                        counter[key] += 1
                        if key not in examples:
                            examples[key] = msg
            except Exception as e:
                logger.warning("Tier 3b: could not read %s: %s", log_file, e)

        if not counter:
            return ""

        lines = ["=== RUNTIME ERRORS (server.log) ===",
                 f"(last {days_back} days — {sum(counter.values())} total occurrences)",
                 ""]
        for (level, log_name, _), count in counter.most_common(50):
            full_msg = examples[(level, log_name, _)]
            lines.append(f"[{count:3d}x] {level} {log_name} — {full_msg[:120]}")

        result = "\n".join(lines)
        logger.info("   Tier 3b: loaded %d distinct runtime errors/warnings from server.log",
                    len(counter))
        return result

    def _code_issues_to_gaps(self, code_issues, is_skill_analysis=False):
        """Convert CodeIssue list to Gap list."""
        gaps = []
        for ci in code_issues:
            if is_skill_analysis:
                gap_type = GapType.PROMPT_GAP
            elif ci.severity == "critical":
                gap_type = GapType.TOOL_LIMITATION
            else:
                gap_type = GapType.SKILL_WEAK
            gaps.append(Gap(
                type=gap_type,
                description=f"{ci.file}: {ci.issue}",
                evidence=[ci.file],
                frequency=1,
                severity=ci.severity,
                skill_file=ci.file if is_skill_analysis else None,
                suggested_addition=ci.suggestion if is_skill_analysis else None,
            ))
        return gaps

    async def analyze_tier3a(
        self,
        days_back: int = 30,
        lookback_hours: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        max_sessions: Optional[int] = None,
        sources: Optional[List[str]] = None,
        **kwargs,
    ) -> EvolutionReport:
        """Tier 3a — Skill prompt review: analyzes SKILL.md files only."""
        job_id = self.generate_job_id()
        report = EvolutionReport(job_id=job_id, started_at=datetime.now().isoformat(),
                                 status=AnalysisStatus.LOADING_SESSIONS)
        self.current_job_id = job_id
        self.current_report = report
        try:
            await self._load_and_classify_sessions(
                report, days_back, lookback_hours, start_time, end_time, max_sessions, sources)

            logger.info("🔍 Tier 3a: Reviewing skill prompts (SKILL.md)...")
            report.status = AnalysisStatus.ANALYZING_SKILLS
            analyzer = CodeAnalyzer(self.skills_root, llm=self.llm, cache=self.cache,
                                    patterns=CodeAnalyzer.SKILL_FILE_PATTERNS)
            skill_files = analyzer.discover_files()
            report.code_files_analyzed = len(skill_files)
            logger.info("   Found %d skill files", len(skill_files))
            skill_issues, skill_coverage = await analyzer.analyze(skill_files, prompt=SKILL_ANALYSIS_PROMPT, force_fresh=kwargs.get("force_fresh", False))
            report.gaps.extend(self._code_issues_to_gaps(skill_issues, is_skill_analysis=True))
            logger.info("   Found %d skill prompt issues", len(skill_issues))

            report.status = AnalysisStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()
        except Exception as e:
            report.status = AnalysisStatus.FAILED
            report.errors.append(str(e))
            report.completed_at = datetime.now().isoformat()
        return report

    async def analyze_tier3b(
        self,
        days_back: int = 30,
        lookback_hours: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        max_sessions: Optional[int] = None,
        sources: Optional[List[str]] = None,
        **kwargs,
    ) -> EvolutionReport:
        """Tier 3b — Core code review: analyzes Python files only (developer-facing)."""
        job_id = self.generate_job_id()
        report = EvolutionReport(job_id=job_id, started_at=datetime.now().isoformat(),
                                 status=AnalysisStatus.LOADING_SESSIONS)
        self.current_job_id = job_id
        self.current_report = report
        try:
            await self._load_and_classify_sessions(
                report, days_back, lookback_hours, start_time, end_time, max_sessions, sources)

            logger.info("🔧 Tier 3b: Reviewing core code (Python)...")
            report.status = AnalysisStatus.ANALYZING_CODE
            analyzer = CodeAnalyzer(self.workspace_root, llm=self.llm, cache=self.cache,
                                    patterns=CodeAnalyzer.CODE_FILE_PATTERNS)
            code_files = analyzer.discover_files()
            report.code_files_analyzed = len(code_files)
            logger.info("   Found %d code files", len(code_files))

            runtime_errors = self._read_server_log_errors(days_back=days_back)
            prompt = CODE_ANALYSIS_PROMPT
            if runtime_errors:
                prompt = CODE_ANALYSIS_PROMPT + "\n\n" + runtime_errors

            code_issues, _ = await analyzer.analyze(code_files, prompt=prompt, force_fresh=kwargs.get("force_fresh", False))
            report.gaps.extend(self._code_issues_to_gaps(code_issues, is_skill_analysis=False))
            logger.info("   Found %d code issues", len(code_issues))

            report.status = AnalysisStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()
        except Exception as e:
            report.status = AnalysisStatus.FAILED
            report.errors.append(str(e))
            report.completed_at = datetime.now().isoformat()
        return report

    async def analyze_tier3(
        self,
        days_back: int = 30,
        lookback_hours: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        max_sessions: Optional[int] = None,
        sources: Optional[List[str]] = None,
        **kwargs,
    ) -> EvolutionReport:
        """Tier 3 — Both 3a + 3b: skill prompt review + code review combined."""
        job_id = self.generate_job_id()
        report = EvolutionReport(job_id=job_id, started_at=datetime.now().isoformat(),
                                 status=AnalysisStatus.LOADING_SESSIONS)
        self.current_job_id = job_id
        self.current_report = report
        try:
            await self._load_and_classify_sessions(
                report, days_back, lookback_hours, start_time, end_time, max_sessions, sources)

            # 3a — skill prompts
            logger.info("🔍 Tier 3a: Reviewing skill prompts (SKILL.md)...")
            report.status = AnalysisStatus.ANALYZING_SKILLS
            skill_analyzer = CodeAnalyzer(self.workspace_root, llm=self.llm, cache=self.cache,
                                          patterns=CodeAnalyzer.SKILL_FILE_PATTERNS)
            skill_files = skill_analyzer.discover_files()
            report.code_files_analyzed = len(skill_files)
            skill_issues, _ = await skill_analyzer.analyze(skill_files, prompt=SKILL_ANALYSIS_PROMPT, force_fresh=kwargs.get("force_fresh", False))
            report.gaps.extend(self._code_issues_to_gaps(skill_issues, is_skill_analysis=True))
            logger.info("   Found %d skill prompt issues", len(skill_issues))

            # 3b — core code
            logger.info("🔧 Tier 3b: Reviewing core code (Python)...")
            report.status = AnalysisStatus.ANALYZING_CODE
            code_analyzer = CodeAnalyzer(self.workspace_root, llm=self.llm, cache=self.cache,
                                         patterns=CodeAnalyzer.CODE_FILE_PATTERNS)
            code_files = code_analyzer.discover_files()
            report.code_files_analyzed += len(code_files)
            runtime_errors = self._read_server_log_errors(days_back=days_back)
            code_prompt = CODE_ANALYSIS_PROMPT + ("\n\n" + runtime_errors if runtime_errors else "")
            code_issues, _ = await code_analyzer.analyze(code_files, prompt=code_prompt, force_fresh=kwargs.get("force_fresh", False))
            report.gaps.extend(self._code_issues_to_gaps(code_issues, is_skill_analysis=False))
            logger.info("   Found %d code issues", len(code_issues))

            report.status = AnalysisStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()
        except Exception as e:
            report.status = AnalysisStatus.FAILED
            report.errors.append(str(e))
            report.completed_at = datetime.now().isoformat()
        return report
    
    async def analyze_tier4a(
        self,
        days_back: int = 30,
        lookback_hours: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        max_sessions: Optional[int] = None,
        sources: Optional[List[str]] = None,
        **kwargs,
    ) -> EvolutionReport:
        """Tier 4a — Skill prompt improvements: Tier 2 + Tier 3a + ImprovementGenerator."""
        job_id = self.generate_job_id()
        report = EvolutionReport(job_id=job_id, started_at=datetime.now().isoformat(),
                                 status=AnalysisStatus.LOADING_SESSIONS)
        self.current_job_id = job_id
        self.current_report = report
        try:
            await self._load_and_classify_sessions(
                report, days_back, lookback_hours, start_time, end_time, max_sessions, sources)

            logger.info("🔍 Tier 3a: Reviewing skill prompts (SKILL.md)...")
            await self._update_status(report, AnalysisStatus.ANALYZING_SKILLS, {"tier": "3a"})
            analyzer = CodeAnalyzer(self.workspace_root, llm=self.llm, cache=self.cache,
                                    patterns=CodeAnalyzer.SKILL_FILE_PATTERNS)
            skill_files = analyzer.discover_files()
            report.code_files_analyzed = len(skill_files)
            logger.info("   Found %d skill files", len(skill_files))
            skill_issues, skill_coverage = await analyzer.analyze(skill_files, prompt=SKILL_ANALYSIS_PROMPT, force_fresh=kwargs.get("force_fresh", False))
            report.gaps.extend(self._code_issues_to_gaps(skill_issues, is_skill_analysis=True))
            logger.info("   Found %d skill prompt issues", len(skill_issues))

            logger.info("💡 Tier 4a: Generating skill prompt improvements...")
            await self._update_status(report, AnalysisStatus.GENERATING_IMPROVEMENTS, {"tier": "4a"})
            generator = ImprovementGenerator(llm=self.llm, cache=self.cache)
            report.improvements = await generator.generate(
                gaps=report.gaps, code_issues=skill_issues, skill_coverage=skill_coverage)
            logger.info("   Generated %d improvements", len(report.improvements))

            report.status = AnalysisStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()
            await self._save_report(report)
        except Exception as e:
            report.status = AnalysisStatus.FAILED
            report.errors.append(str(e))
            report.completed_at = datetime.now().isoformat()
            await self._save_report(report)
        return report

    async def analyze_tier4b(
        self,
        days_back: int = 30,
        lookback_hours: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        max_sessions: Optional[int] = None,
        sources: Optional[List[str]] = None,
        **kwargs,
    ) -> EvolutionReport:
        """Tier 4b — Code improvements: Tier 2 + Tier 3b + ImprovementGenerator."""
        job_id = self.generate_job_id()
        report = EvolutionReport(job_id=job_id, started_at=datetime.now().isoformat(),
                                 status=AnalysisStatus.LOADING_SESSIONS)
        self.current_job_id = job_id
        self.current_report = report
        try:
            await self._load_and_classify_sessions(
                report, days_back, lookback_hours, start_time, end_time, max_sessions, sources)

            logger.info("🔧 Tier 3b: Reviewing core code (Python)...")
            await self._update_status(report, AnalysisStatus.ANALYZING_CODE, {"tier": "3b"})
            analyzer = CodeAnalyzer(self.workspace_root, llm=self.llm, cache=self.cache,
                                    patterns=CodeAnalyzer.CODE_FILE_PATTERNS)
            code_files = analyzer.discover_files()
            report.code_files_analyzed = len(code_files)
            logger.info("   Found %d code files", len(code_files))
            runtime_errors = self._read_server_log_errors(days_back=days_back)
            code_prompt = CODE_ANALYSIS_PROMPT + ("\n\n" + runtime_errors if runtime_errors else "")
            code_issues, skill_coverage = await analyzer.analyze(code_files, prompt=code_prompt, force_fresh=kwargs.get("force_fresh", False))
            report.gaps.extend(self._code_issues_to_gaps(code_issues, is_skill_analysis=False))
            logger.info("   Found %d code issues", len(code_issues))

            logger.info("💡 Tier 4b: Generating code improvements...")
            await self._update_status(report, AnalysisStatus.GENERATING_IMPROVEMENTS, {"tier": "4b"})
            generator = ImprovementGenerator(llm=self.llm, cache=self.cache)
            report.improvements = await generator.generate(
                gaps=report.gaps, code_issues=code_issues, skill_coverage=skill_coverage)
            logger.info("   Generated %d improvements", len(report.improvements))

            report.status = AnalysisStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()
            await self._save_report(report)
        except Exception as e:
            report.status = AnalysisStatus.FAILED
            report.errors.append(str(e))
            report.completed_at = datetime.now().isoformat()
            await self._save_report(report)
        return report

    async def analyze_full(
        self,
        days_back: int = 30,
        lookback_hours: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        max_sessions: Optional[int] = None,
        sources: Optional[List[str]] = None,
        context_pack_id: Optional[str] = None,
        context_docs: Optional[List[str]] = None,
        **kwargs,
    ) -> EvolutionReport:
        """
        Run full analysis: Tier 1-4 (sessions + classification + code + improvements).
        
        Args:
            days_back: Number of days of history to analyze
            
        Returns:
            Complete report with improvements
        """
        job_id = self.generate_job_id()
        report = EvolutionReport(
            job_id=job_id,
            started_at=datetime.now().isoformat(),
            status=AnalysisStatus.LOADING_SESSIONS
        )
        
        self.current_job_id = job_id
        self.current_report = report
        
        all_code_issues = []
        skill_coverage = {}

        try:
            # Initial status update
            await self._update_status(report, AnalysisStatus.LOADING_SESSIONS, {"tier": 1})

            if context_pack_id or context_docs:
                report.errors.append("Context packs are accepted but not yet consumed in Tier 1-4")

            # Tier 1 + 2: Load sessions and classify behaviour
            await self._load_and_classify_sessions(
                report, days_back, lookback_hours, start_time, end_time, max_sessions, sources)
            await self._update_status(report, AnalysisStatus.CLASSIFYING, {"tier": 2, "sessions": report.sessions_analyzed})

            # Tier 3a: Skill prompt review
            logger.info("🔍 Tier 3a: Reviewing skill prompts (SKILL.md)...")
            await self._update_status(report, AnalysisStatus.ANALYZING_SKILLS, {"tier": "3a", "gaps": len(report.gaps)})
            skill_analyzer = CodeAnalyzer(self.workspace_root, llm=self.llm, cache=self.cache,
                                          patterns=CodeAnalyzer.SKILL_FILE_PATTERNS)
            skill_files = skill_analyzer.discover_files()
            report.code_files_analyzed = len(skill_files)
            logger.info("   Found %d skill files", len(skill_files))
            skill_issues, skill_coverage = await skill_analyzer.analyze(skill_files, prompt=SKILL_ANALYSIS_PROMPT, force_fresh=kwargs.get("force_fresh", False))
            report.gaps.extend(self._code_issues_to_gaps(skill_issues, is_skill_analysis=True))
            all_code_issues.extend(skill_issues)
            logger.info("   Found %d skill prompt issues", len(skill_issues))

            # Tier 3b: Core code review
            logger.info("🔧 Tier 3b: Reviewing core code (Python)...")
            await self._update_status(report, AnalysisStatus.ANALYZING_CODE, {"tier": "3b", "gaps": len(report.gaps)})
            code_analyzer = CodeAnalyzer(self.workspace_root, llm=self.llm, cache=self.cache,
                                         patterns=CodeAnalyzer.CODE_FILE_PATTERNS)
            code_files = code_analyzer.discover_files()
            report.code_files_analyzed += len(code_files)
            logger.info("   Found %d code files", len(code_files))

            # Enrich with runtime errors from server.log
            runtime_errors = self._read_server_log_errors(days_back=days_back)
            code_prompt = CODE_ANALYSIS_PROMPT + ("\n\n" + runtime_errors if runtime_errors else "")

            code_issues, _ = await code_analyzer.analyze(code_files, prompt=code_prompt, force_fresh=kwargs.get("force_fresh", False))
            report.gaps.extend(self._code_issues_to_gaps(code_issues, is_skill_analysis=False))
            all_code_issues.extend(code_issues)
            logger.info("   Found %d code issues", len(code_issues))

            # Tier 4: Generate improvements
            logger.info("💡 Tier 4: Generating improvements...")
            await self._update_status(report, AnalysisStatus.GENERATING_IMPROVEMENTS, {"tier": 4, "code_issues": len(all_code_issues)})

            generator = ImprovementGenerator(llm=self.llm, cache=self.cache)
            improvements = await generator.generate(
                gaps=report.gaps,
                code_issues=all_code_issues,
                skill_coverage=skill_coverage
            )

            report.improvements = improvements
            logger.info("   Generated %d improvements", len(improvements))
            
            report.status = AnalysisStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()
            
            await self._save_report(report)
            
        except Exception as e:
            report.status = AnalysisStatus.FAILED
            report.errors.append(str(e))
            report.completed_at = datetime.now().isoformat()
            await self._save_report(report)
        
        return report



if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Self-Evolution Analysis")
    parser.add_argument("--days", type=int, default=30, help="Days of history to analyze")
    parser.add_argument("--tier", type=int, default=1, help="Which tier to run (1-4)")
    args = parser.parse_args()
    
    # Get workspace root (parent of iaf_agent_skills)
    workspace_root = Path(__file__).parent.parent
    
    logger.info("🔍 Self-Evolution Analysis")
    logger.info("   Workspace: %s", workspace_root)
    logger.info("   Days back: %d", args.days)
    logger.info("   Tier: %d", args.tier)
    logger.info("-" * 40)
    
    engine = SelfEvolutionEngine(workspace_root=workspace_root)
    
    if args.tier == 1:
        report = asyncio.run(engine.analyze_tier1_only(days_back=args.days))
    elif args.tier == 2:
        report = asyncio.run(engine.analyze_tier2(days_back=args.days))
    elif args.tier == 3:
        report = asyncio.run(engine.analyze_tier3(days_back=args.days))
    elif args.tier == 4:
        report = asyncio.run(engine.analyze_full(days_back=args.days))
    else:
        report = asyncio.run(engine.analyze_tier1_only(days_back=args.days))
    
    logger.info("\n📊 Report:")
    logger.info("   Job ID: %s", report.job_id)
    logger.info("   Status: %s", report.status)
    logger.info("   Sessions: %d", report.sessions_analyzed)
    logger.info("   Code files: %d", report.code_files_analyzed)
    logger.info("   Gaps: %d", len(report.gaps))
    logger.info("   Improvements: %d", len(report.improvements))

    if report.gaps:
        logger.info("\n🔍 Gaps Found:")
        for gap in report.gaps[:10]:  # Limit output
            logger.info("   - [%s] %s: %s", gap.severity, gap.type, gap.description[:80])

    if report.improvements:
        logger.info("\n💡 Improvements:")
        for imp in report.improvements[:10]:  # Limit output
            logger.info("   - [%s] %s", imp.priority, imp.title)

    if report.errors:
        logger.warning("\n⚠️  Errors:")
        for e in report.errors:
            logger.warning("   %s", e)
