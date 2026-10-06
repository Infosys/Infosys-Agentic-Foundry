# (c) 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.

"""
Token Usage Dashboard Endpoints - RBAC-scoped JSON APIs for the UI dashboard.

Provides aggregated token usage data with department-based isolation:
- SuperAdmin: sees all departments (can filter by department)
- Admin: sees only their own department
- User/Developer: sees only their own data
"""

import json
from datetime import date, datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict

_SERVER_TZ = timezone(timedelta(hours=5, minutes=30))  # IST


def _to_local_date(ts) -> str:
    """Convert a timestamp to local date string YYYY-MM-DD."""
    if ts is None:
        return ""
    if hasattr(ts, 'astimezone'):
        return ts.astimezone(_SERVER_TZ).strftime("%Y-%m-%d")
    return str(ts)[:10]


from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.database.repositories import QueryTokenUsageRepository, TokenUsageLogsRepository
from src.api.dependencies import ServiceProvider
from src.auth.dependencies import get_current_user
from src.auth.models import User, UserRole
from telemetry_wrapper import logger as log

router = APIRouter(prefix="/dashboard", tags=["Dashboard - Token Usage"])


# ========== RESPONSE MODELS ==========

class DashboardSummary(BaseModel):
    total_queries: int = 0
    total_llm_calls: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    total_query_cost: float = 0.0
    unique_agents: int = 0
    unique_users: int = 0
    avg_llm_calls_per_query: float = 0.0
    avg_cost_per_query: float = 0.0


class CostOverTimeByAgentItem(BaseModel):
    date: str
    agent_name: str
    cost: float = 0.0


class DailyTrendItem(BaseModel):
    date: str
    queries: int = 0
    llm_calls: int = 0
    tokens: int = 0
    cost: float = 0.0


class ModelBreakdownItem(BaseModel):
    model: str
    calls: int = 0
    tokens: int = 0
    cost: float = 0.0


class AgentBreakdownItem(BaseModel):
    agent_name: str
    queries: int = 0
    llm_calls: int = 0
    tokens: int = 0
    cost: float = 0.0


class TopUserItem(BaseModel):
    user_id: str
    queries: int = 0
    tokens: int = 0
    cost: float = 0.0


class QueryDetailItem(BaseModel):
    created_at: Optional[str] = None
    user_id: Optional[str] = None
    agent_name: Optional[str] = None
    query: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    total_cost: float = 0.0


class DashboardResponse(BaseModel):
    summary: DashboardSummary
    daily_trend: List[DailyTrendItem] = []
    cost_over_time_by_agent: List[CostOverTimeByAgentItem] = []
    model_breakdown: List[ModelBreakdownItem] = []
    agent_breakdown: List[AgentBreakdownItem] = []
    top_users: List[TopUserItem] = []
    recent_queries: List[QueryDetailItem] = []


class FilterOptionsResponse(BaseModel):
    departments: List[str] = []
    agents: List[Dict[str, Optional[str]]] = []
    users: List[str] = []
    models: List[str] = []
    statuses: List[str] = []
    sessions: List[str] = []


class DownloadReportResponse(BaseModel):
    download_url: str
    message: str


# ========== RBAC HELPER ==========

def _apply_scope(current_user: User, department_name: Optional[str], user_id: Optional[str]):
    """
    Apply RBAC scoping rules. Returns (effective_department, effective_user_id).

    SuperAdmin: can view any department, any user
    Admin: forced to own department, can filter users within it
    User/Developer: forced to own department AND own user_id

    Safety: if Admin/User/Developer has no department assigned, use a sentinel
    value that will never match any real data (prevents data leakage).
    """
    role = current_user.role

    if role in [UserRole.SUPER_ADMIN, "SuperAdmin"]:
        return department_name, user_id
    elif role in [UserRole.ADMIN, "Admin"]:
        dept = current_user.department_name or "__NO_DEPARTMENT_ASSIGNED__"
        return dept, user_id
    else:
        dept = current_user.department_name or "__NO_DEPARTMENT_ASSIGNED__"
        return dept, current_user.email


# ========== MAIN DASHBOARD ENDPOINT ==========

@router.get(
    "/token-usage",
    response_model=DashboardResponse,
    summary="Get token usage dashboard data (RBAC-scoped)"
)
async def get_dashboard_data(
    user_id: Optional[str] = Query(None, description="Filter by user ID (Admin+)"),
    department_name: Optional[str] = Query(None, description="Filter by department (SuperAdmin only)"),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    agent_name: Optional[str] = Query(None, description="Filter by agent name"),
    model: Optional[str] = Query(None, description="Filter by model name"),
    status: Optional[str] = Query(None, description="Filter by status (success/failure)"),
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
    date_from: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    query_token_usage_repo: QueryTokenUsageRepository = Depends(ServiceProvider.get_query_token_usage_repo),
    token_logs_repo: TokenUsageLogsRepository = Depends(ServiceProvider.get_token_usage_logs_repo),
    current_user: User = Depends(get_current_user),
):
    """
    Returns aggregated dashboard data for the token usage UI.

    RBAC enforcement:
    - SuperAdmin: sees all departments (optionally filtered)
    - Admin: sees only own department data
    - User/Developer: sees only own data
    """
    effective_dept, effective_user = _apply_scope(current_user, department_name, user_id)

    try:
        query_rows = await query_token_usage_repo.get_report_data(
            user_id=effective_user, agent_id=agent_id, agent_name=agent_name,
            date_from=date_from, date_to=date_to, department_name=effective_dept,
            session_id=session_id
        )
        log_rows = await token_logs_repo.get_report_data(
            user_id=effective_user, agent_id=agent_id, agent_name=agent_name,
            date_from=date_from, date_to=date_to, department_name=effective_dept,
            model=model, status=status, session_id=session_id
        )

        # --- Summary ---
        total_queries = len(query_rows)
        total_llm_calls = sum(r.get("total_llm_calls", 0) for r in query_rows)
        if not total_llm_calls:
            for r in query_rows:
                calls = r.get("llm_calls") or []
                if isinstance(calls, str):
                    try: calls = json.loads(calls)
                    except: calls = []
                total_llm_calls += len(calls) if isinstance(calls, list) else 0
        if not total_llm_calls:
            total_llm_calls = len(log_rows)
        total_tokens = sum(r.get("total_tokens", 0) for r in query_rows) or sum(r.get("total_tokens", 0) for r in log_rows)
        total_cost = sum(float(r.get("total_cost", 0)) for r in query_rows) or sum(float(r.get("total_cost", 0)) for r in log_rows)
        total_query_cost = sum(float(r.get("total_cost", 0)) for r in query_rows)
        unique_agents = len(set(r.get("agent_name") for r in query_rows if r.get("agent_name"))) or len(set(r.get("agent_name") for r in log_rows if r.get("agent_name")))
        unique_users = len(set(r.get("user_id") for r in query_rows if r.get("user_id")))

        summary = DashboardSummary(
            total_queries=total_queries,
            total_llm_calls=total_llm_calls,
            total_tokens=total_tokens,
            total_cost=round(total_cost, 6),
            total_query_cost=round(total_query_cost, 6),
            unique_agents=unique_agents,
            unique_users=unique_users,
            avg_llm_calls_per_query=round(total_llm_calls / total_queries, 2) if total_queries else 0.0,
            avg_cost_per_query=round(total_query_cost / total_queries, 6) if total_queries else 0.0,
        )

        # --- Daily Trend (from query_rows + log_rows) ---
        daily_map: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"queries": 0, "llm_calls": 0, "tokens": 0, "cost": 0.0})
        for r in query_rows:
            dt = r.get("created_at")
            if dt:
                day_key = _to_local_date(dt)
                daily_map[day_key]["queries"] += 1
                daily_map[day_key]["tokens"] += r.get("total_tokens", 0)
                daily_map[day_key]["cost"] += float(r.get("total_cost", 0))

        if log_rows:
            for r in log_rows:
                dt = r.get("timestamp")
                if dt:
                    day_key = _to_local_date(dt)
                    daily_map[day_key]["llm_calls"] += 1
        else:
            for r in query_rows:
                dt = r.get("created_at")
                if dt:
                    day_key = _to_local_date(dt)
                    daily_map[day_key]["llm_calls"] += r.get("total_llm_calls", 0)

        daily_trend = [
            DailyTrendItem(date=k, queries=v["queries"], llm_calls=v["llm_calls"],
                           tokens=v["tokens"], cost=round(v["cost"], 6))
            for k, v in sorted(daily_map.items())
        ]

        # --- Cost Over Time by Agent (from log_rows, fallback to query_rows) ---
        agent_time_map: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        if log_rows:
            for r in log_rows:
                dt = r.get("timestamp")
                agent = r.get("agent_name") or "unknown"
                if dt:
                    day_key = _to_local_date(dt)
                    agent_time_map[day_key][agent] += float(r.get("total_cost", 0))
        else:
            for r in query_rows:
                dt = r.get("created_at")
                agent = r.get("agent_name") or "unknown"
                if dt:
                    day_key = _to_local_date(dt)
                    agent_time_map[day_key][agent] += float(r.get("total_cost", 0))

        cost_over_time_by_agent = sorted(
            [CostOverTimeByAgentItem(date=day, agent_name=agent, cost=round(cost, 6))
             for day, agents in agent_time_map.items()
             for agent, cost in agents.items()],
            key=lambda x: (x.date, x.agent_name)
        )

        # --- Model Breakdown (from log_rows, fallback to query_rows llm_calls JSONB) ---
        model_map: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"calls": 0, "tokens": 0, "cost": 0.0})
        if log_rows:
            for r in log_rows:
                m_name = r.get("model_name") or "unknown"
                model_map[m_name]["calls"] += 1
                model_map[m_name]["tokens"] += r.get("total_tokens", 0)
                model_map[m_name]["cost"] += float(r.get("total_cost", 0))
        else:
            for r in query_rows:
                calls = r.get("llm_calls") or []
                if isinstance(calls, str):
                    try: calls = json.loads(calls)
                    except: calls = []
                if isinstance(calls, list):
                    for c in calls:
                        if isinstance(c, dict):
                            m_name = c.get("model") or c.get("model_name") or "unknown"
                            model_map[m_name]["calls"] += 1
                            model_map[m_name]["tokens"] += c.get("total_tokens", 0)
                            model_map[m_name]["cost"] += float(c.get("total_cost", 0))

        model_breakdown = sorted(
            [ModelBreakdownItem(model=k, calls=v["calls"], tokens=v["tokens"], cost=round(v["cost"], 6))
             for k, v in model_map.items()],
            key=lambda x: x.cost, reverse=True
        )

        # --- Agent Breakdown (from query_rows) ---
        agent_query_map: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"queries": 0, "llm_calls": 0, "tokens": 0, "cost": 0.0})
        for r in query_rows:
            name = r.get("agent_name") or "unknown"
            agent_query_map[name]["queries"] += 1
            agent_query_map[name]["tokens"] += r.get("total_tokens", 0)
            agent_query_map[name]["cost"] += float(r.get("total_cost", 0))
            agent_query_map[name]["llm_calls"] += r.get("total_llm_calls", 0)

        agent_breakdown = sorted(
            [AgentBreakdownItem(agent_name=k, queries=v["queries"], llm_calls=v["llm_calls"],
                                tokens=v["tokens"], cost=round(v["cost"], 6))
             for k, v in agent_query_map.items()],
            key=lambda x: x.cost, reverse=True
        )

        # --- Top Users (from query_rows) ---
        user_map: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"queries": 0, "tokens": 0, "cost": 0.0})
        for r in query_rows:
            uid = r.get("user_id") or "unknown"
            user_map[uid]["queries"] += 1
            user_map[uid]["tokens"] += r.get("total_tokens", 0)
            user_map[uid]["cost"] += float(r.get("total_cost", 0))

        top_users = sorted(
            [TopUserItem(user_id=k, queries=v["queries"], tokens=v["tokens"], cost=round(v["cost"], 6))
             for k, v in user_map.items()],
            key=lambda x: x.cost, reverse=True
        )[:20]

        # --- Recent Queries (latest 100) ---
        recent_queries = []
        for r in query_rows[:100]:
            dt = r.get("created_at")
            recent_queries.append(QueryDetailItem(
                created_at=dt.isoformat() if hasattr(dt, "isoformat") else str(dt),
                user_id=r.get("user_id"),
                agent_name=r.get("agent_name"),
                query=(r.get("query") or "")[:200],
                prompt_tokens=r.get("prompt_tokens", 0),
                completion_tokens=r.get("completion_tokens", 0),
                cached_tokens=r.get("cached_tokens", 0),
                total_cost=round(float(r.get("total_cost", 0)), 6),
            ))

        return DashboardResponse(
            summary=summary,
            daily_trend=daily_trend,
            cost_over_time_by_agent=cost_over_time_by_agent,
            model_breakdown=model_breakdown,
            agent_breakdown=agent_breakdown,
            top_users=top_users,
            recent_queries=recent_queries,
        )

    except Exception as e:
        log.error(f"Dashboard data fetch failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch dashboard data: {str(e)}")


# ========== FILTER OPTIONS ENDPOINT ==========

@router.get(
    "/filter-options",
    response_model=FilterOptionsResponse,
    summary="Get available filter options (RBAC-scoped)"
)
async def get_filter_options(
    query_token_usage_repo: QueryTokenUsageRepository = Depends(ServiceProvider.get_query_token_usage_repo),
    token_logs_repo: TokenUsageLogsRepository = Depends(ServiceProvider.get_token_usage_logs_repo),
    current_user: User = Depends(get_current_user),
):
    """
    Returns available filter dropdown values scoped by the caller's role.

    Visibility rules:
    - User/Developer: agents, models, statuses (scoped to own data)
    - Admin: agents, models, statuses, users (scoped to own department)
    - SuperAdmin: agents, models, statuses, users, departments (all data)
    """
    effective_dept, effective_user = _apply_scope(current_user, None, None)

    try:
        query_rows = await query_token_usage_repo.get_report_data(
            department_name=effective_dept, user_id=effective_user
        )
        log_rows = await token_logs_repo.get_report_data(
            department_name=effective_dept, user_id=effective_user
        )

        # Departments - only visible to SuperAdmin
        depts: List[str] = []
        if current_user.role in [UserRole.SUPER_ADMIN, "SuperAdmin"]:
            depts = sorted(set(
                r.get("department_name") for r in query_rows if r.get("department_name")
            ))

        # Agents - visible to all roles
        agent_set: Dict[str, Optional[str]] = {}
        for r in query_rows:
            aid = r.get("agent_id")
            if aid and aid not in agent_set:
                agent_set[aid] = r.get("agent_name")
        for r in log_rows:
            aid = r.get("agent_id")
            if aid and str(aid) not in agent_set:
                agent_set[str(aid)] = r.get("agent_name")
        agents = [{"agent_id": k, "agent_name": v} for k, v in agent_set.items()]

        # Users - visible to Admin and SuperAdmin only
        users: List[str] = []
        if current_user.role in [UserRole.SUPER_ADMIN, "SuperAdmin", UserRole.ADMIN, "Admin"]:
            users = sorted(set(r.get("user_id") for r in query_rows if r.get("user_id")))

        # Models - visible to all roles (from log_rows, fallback to query_rows JSONB)
        models = sorted(set(r.get("model_name") for r in log_rows if r.get("model_name")))
        if not models:
            model_set = set()
            for r in query_rows:
                calls = r.get("llm_calls") or []
                if isinstance(calls, str):
                    try: calls = json.loads(calls)
                    except: calls = []
                if isinstance(calls, list):
                    for c in calls:
                        if isinstance(c, dict):
                            m = c.get("model") or c.get("model_name")
                            if m:
                                model_set.add(m)
            models = sorted(model_set)

        # Statuses - visible to all roles
        statuses = sorted(set(r.get("status") for r in log_rows if r.get("status")))

        # Sessions - scoped to the user's visible data
        sessions = sorted(set(r.get("session_id") for r in query_rows if r.get("session_id")), reverse=True)

        return FilterOptionsResponse(
            departments=depts,
            agents=agents,
            users=users,
            models=models,
            statuses=statuses,
            sessions=sessions,
        )

    except Exception as e:
        log.error(f"Filter options fetch failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch filter options: {str(e)}")


# ========== DOWNLOAD REPORT ENDPOINT ==========

@router.get(
    "/download-report",
    response_model=DownloadReportResponse,
    summary="Generate downloadable report URL with current dashboard filters"
)
async def download_report(
    user_id: Optional[str] = Query(None, description="Filter by user ID (Admin+)"),
    department_name: Optional[str] = Query(None, description="Filter by department (SuperAdmin only)"),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    agent_name: Optional[str] = Query(None, description="Filter by agent name"),
    model: Optional[str] = Query(None, description="Filter by model name"),
    status: Optional[str] = Query(None, description="Filter by status (success/failure)"),
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
    date_from: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    current_user: User = Depends(get_current_user),
):
    """
    Generates the download URL for the report export endpoint,
    pre-filled with the same filters the user has active on the dashboard.

    The UI should redirect or open this URL to trigger the Excel download.
    """
    effective_dept, effective_user = _apply_scope(current_user, department_name, user_id)

    params = []
    if effective_user:
        params.append(f"user_id={effective_user}")
    if effective_dept:
        params.append(f"department_name={effective_dept}")
    if agent_id:
        params.append(f"agent_id={agent_id}")
    if agent_name:
        params.append(f"agent_name={agent_name}")
    if model:
        params.append(f"model={model}")
    if status:
        params.append(f"status={status}")
    if session_id:
        params.append(f"session_id={session_id}")
    if date_from:
        params.append(f"date_from={date_from.isoformat()}")
    if date_to:
        params.append(f"date_to={date_to.isoformat()}")

    query_string = "&".join(params)
    download_url = f"/reports/token-usage-export{'?' + query_string if query_string else ''}"

    return DownloadReportResponse(
        download_url=download_url,
        message="Use this URL to download the Excel report with the applied filters."
    )
