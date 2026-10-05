"""
API endpoints for LLM Request Tracking Dashboard.

Provides RBAC-scoped endpoints to query and visualize LLM tracking data:
- Get all users with request counts (scoped by role)
- Get sessions for a specific user (with access validation)
- Get requests for a specific session (with access validation)
- Get detailed LLM call information for a specific request (with access validation)

RBAC Rules:
- SuperAdmin: can view all users across all departments
- Admin: can view all users within their own department
- User/Developer: can only view their own LLM calls
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query

from src.database.repositories import LLMRequestTrackingRepository
from src.api.dependencies import ServiceProvider
from src.auth.dependencies import get_current_user
from src.auth.models import User, UserRole

log = logging.getLogger(__name__)
router = APIRouter(prefix="/llm-tracking", tags=["llm-tracking"])


# ========== RBAC HELPER ==========

def _apply_llm_tracking_scope(
    current_user: User,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Apply RBAC scoping rules for LLM tracking endpoints.

    Returns (effective_department, effective_user_id):
      - SuperAdmin: (None, None) — no restrictions
      - Admin: (own_department, None) — scoped to department, can view any user in it
      - User/Developer: (own_department, own_email) — scoped to department AND own data only

    Safety: if Admin/User/Developer has no department assigned, use a sentinel
    value that will never match any real data (prevents data leakage).
    """
    role = current_user.role

    if role in [UserRole.SUPER_ADMIN, "SuperAdmin"]:
        return None, None
    elif role in [UserRole.ADMIN, "Admin"]:
        dept = current_user.department_name or "__NO_DEPARTMENT_ASSIGNED__"
        return dept, None
    else:
        dept = current_user.department_name or "__NO_DEPARTMENT_ASSIGNED__"
        return dept, current_user.email


def _check_user_access(current_user: User, target_user_id: str) -> None:
    """
    Verify the current user has permission to access a specific target user's data.
    Raises 403 if access is denied.
    """
    role = current_user.role

    if role in [UserRole.SUPER_ADMIN, "SuperAdmin"]:
        return

    if role in [UserRole.ADMIN, "Admin"]:
        return

    if current_user.email.lower() != target_user_id.lower():
        raise HTTPException(
            status_code=403,
            detail="Access denied: you can only view your own LLM tracking data"
        )


# ========== ENDPOINTS ==========

@router.get("/users")
async def get_all_users(
    llm_tracking_repo: LLMRequestTrackingRepository = Depends(ServiceProvider.get_llm_request_tracking_repo),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """
    Get all unique users with their LLM request statistics (RBAC-scoped).

    - SuperAdmin: sees all users across all departments
    - Admin: sees all users within their department
    - User/Developer: sees only their own entry
    """
    effective_dept, effective_user = _apply_llm_tracking_scope(current_user)

    try:
        users = await llm_tracking_repo.get_all_users(
            department_name=effective_dept,
            user_id=effective_user,
        )
        log.info(f"Retrieved {len(users)} users from LLM tracking for {current_user.email} (role={current_user.role})")
        return users
    except Exception as e:
        log.error(f"Failed to get users: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve users: {str(e)}")


@router.get("/users/{user_id}/sessions")
async def get_sessions_by_user(
    user_id: str,
    llm_tracking_repo: LLMRequestTrackingRepository = Depends(ServiceProvider.get_llm_request_tracking_repo),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """
    Get all sessions for a specific user with request statistics (RBAC-scoped).

    - SuperAdmin: can query any user
    - Admin: can query any user in their department
    - User/Developer: can only query their own user_id
    """
    _check_user_access(current_user, user_id)
    effective_dept, _ = _apply_llm_tracking_scope(current_user)

    try:
        sessions = await llm_tracking_repo.get_sessions_by_user(
            user_id=user_id,
            department_name=effective_dept,
        )
        log.info(f"Retrieved {len(sessions)} sessions for user {user_id}")
        return sessions
    except Exception as e:
        log.error(f"Failed to get sessions for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve sessions: {str(e)}")


@router.get("/sessions/{session_id}/requests")
async def get_requests_by_session(
    session_id: str,
    user_id: Optional[str] = Query(None, description="Filter by user_id (pass from drill-down context)"),
    llm_tracking_repo: LLMRequestTrackingRepository = Depends(ServiceProvider.get_llm_request_tracking_repo),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """
    Get all unique request_ids for a specific session with LLM call statistics (RBAC-scoped).

    Pass user_id query param to scope results to a specific user's requests within
    the session (important for shared session IDs like 'unknown').
    """
    effective_dept, effective_user = _apply_llm_tracking_scope(current_user)

    # For User/Developer, effective_user is already forced to their own email.
    # For Admin/SuperAdmin, use the user_id from query param if provided (drill-down context).
    resolved_user = effective_user or user_id

    if user_id and effective_user and user_id.lower() != effective_user.lower():
        raise HTTPException(
            status_code=403,
            detail="Access denied: you can only view your own LLM tracking data"
        )

    try:
        requests = await llm_tracking_repo.get_requests_by_session(
            session_id=session_id,
            department_name=effective_dept,
            user_id=resolved_user,
        )
        log.info(f"Retrieved {len(requests)} requests for session {session_id}")
        return requests
    except Exception as e:
        log.error(f"Failed to get requests for session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve requests: {str(e)}")


@router.get("/requests/{request_id}/llm-calls")
async def get_llm_calls_by_request(
    request_id: str,
    user_id: Optional[str] = Query(None, description="Filter by user_id (pass from drill-down context)"),
    session_id: Optional[str] = Query(None, description="Filter by session_id (pass from drill-down context)"),
    llm_tracking_repo: LLMRequestTrackingRepository = Depends(ServiceProvider.get_llm_request_tracking_repo),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """
    Get all detailed LLM call information for a specific request_id (RBAC-scoped).

    Pass user_id and session_id query params from the drill-down context to ensure
    consistent counts with the parent list view.
    """
    effective_dept, effective_user = _apply_llm_tracking_scope(current_user)

    resolved_user = effective_user or user_id

    if user_id and effective_user and user_id.lower() != effective_user.lower():
        raise HTTPException(
            status_code=403,
            detail="Access denied: you can only view your own LLM tracking data"
        )

    try:
        llm_calls = await llm_tracking_repo.get_llm_calls_by_request(
            request_id=request_id,
            department_name=effective_dept,
            user_id=resolved_user,
            session_id=session_id,
        )
        log.info(f"Retrieved {len(llm_calls)} LLM calls for request {request_id}")
        return llm_calls
    except Exception as e:
        log.error(f"Failed to get LLM calls for request {request_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve LLM calls: {str(e)}")
