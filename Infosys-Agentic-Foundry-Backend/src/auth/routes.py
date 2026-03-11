from fastapi import APIRouter, Depends, Request, HTTPException, status, Query
from src.auth.models import (
    User, LoginRequest, LoginResponse, RegisterRequest, RegisterResponse,
    UpdatePasswordRequest, GrantApprovalPermissionRequest, ApprovalPermissionResponse,
    RevokeApprovalPermissionRequest, UserRole, Permission, RefreshTokenRequest, RefreshTokenResponse,
    RoleListResponse, AssignRoleDepartmentRequest, AssignRoleDepartmentResponse, UpdateUserRoleRequest,
    SetUserActiveStatusRequest, UserActiveStatusResponse,
    AdminResetPasswordRequest, AdminResetPasswordResponse, ChangePasswordRequest, ChangePasswordResponse
)
from src.auth.auth_service import AuthService
from src.auth.authorization_service import AuthorizationService
from src.auth.dependencies import (
    get_auth_service, get_authorization_service, get_current_user,
    require_role, require_permission, get_client_ip, get_user_agent
)
from src.api.dependencies import ServiceProvider
from src.database.services import RoleAccessService
from telemetry_wrapper import logger as log
from typing import Optional, List, Dict
from collections import defaultdict




router = APIRouter(tags=["Authentication"], prefix="/auth")


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    login_data: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    """Login endpoint"""
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    log.info("Login attempt with data: %s")
    login_response = await auth_service.login(login_data, ip_address, user_agent)
    log.info("login attempted")
    log.info("completed login")
    # Return response directly; caller handles refresh token storage (no cookies set server-side)
    return login_response


@router.post("/logout")
async def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Logout endpoint"""
    auth_header = request.headers.get("Authorization")
    token = auth_header.split(" ", 1)[1]
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    refresh_token = request.cookies.get("refresh_token")
    await auth_service.logout(token, refresh_token, ip_address, user_agent)
    return {"message": "Logged out successfully"}

@router.post("/register", response_model=RegisterResponse)
async def register(
    request: Request,
    register_data: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    """Register endpoint"""
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    
    # Try to get current user if request is authenticated
    current_user = None
    if hasattr(request.state, 'user'):
        current_user = request.state.user
    
    return await auth_service.register(register_data, ip_address, user_agent, current_user)


@router.post("/register-superadmin", response_model=RegisterResponse)
async def register_superadmin(
    request: Request,
    register_data: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Register a SuperAdmin user.
    This endpoint is only available when no SuperAdmin exists in the system.
    Use this to bootstrap the system or recover from a state with no SuperAdmin.
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    
    return await auth_service.register_superadmin(register_data, ip_address, user_agent)


@router.post("/assign-role-department", response_model=AssignRoleDepartmentResponse)
async def assign_role_department(
    request: Request,
    assign_data: AssignRoleDepartmentRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Assign role and department to a registered user.
    Only SuperAdmin or department Admin can use this endpoint.
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    
    # Only SuperAdmin and Admin can assign roles
    if current_user.role not in ["SuperAdmin", "Admin"]:
        raise HTTPException(
            status_code=403,
            detail="Only SuperAdmin or Admin can assign roles and departments"
        )
    
    result = await auth_service.assign_role_department(
        email_id=assign_data.email_id,
        department_name=assign_data.department_name,
        role=assign_data.role,
        current_user=current_user,
        ip_address=ip_address,
        user_agent=user_agent
    )
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    
    return AssignRoleDepartmentResponse(
        success=result["success"],
        message=result["message"]
    )


@router.get("/guest-login", response_model=LoginResponse)
async def guest_login(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service)
):
    """Guest login endpoint that returns JWT."""
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    login_response = await auth_service.guest_login(ip_address, user_agent)
    log.info("Guest login attempted with response: %s", login_response)
    return login_response


@router.post("/refresh-token", response_model=RefreshTokenResponse)
async def refresh_access_token(
    request: Request,
    payload: RefreshTokenRequest | None = None,
    auth_service: AuthService = Depends(get_auth_service)
):
    """Use refresh token (from cookie or body) to obtain a new access token."""
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    provided = (payload.refresh_token if payload else None) or request.cookies.get("refresh_token")
    if not provided:
        raise HTTPException(status_code=401, detail="Refresh token missing")
    return await auth_service.refresh_access_token(provided, ip_address, user_agent)


# ─────────────────────────────────────────────────────────────────────────────
# PWD MANAGEMENT ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/reset-password", response_model=AdminResetPasswordResponse)
async def admin_reset_password(
    request: Request,
    reset_data: AdminResetPasswordRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Reset a user's PWD with a temporary PWD (SuperAdmin only).
    
    The user will be required to change their PWD on next login.
    
    **SuperAdmin Only** - Only SuperAdmin users can reset PWDs for other users.
    
    Flow:
    1. User forgets PWD and contacts SuperAdmin
    2. SuperAdmin uses this endpoint to set a temporary PWD
    3. SuperAdmin communicates temporary PWD to user
    4. User logs in with temporary PWD
    5. User is prompted to change PWD (must_change_password=True in login response)
    6. User changes PWD via /auth/change-pwd endpoint
    """
    # Only SuperAdmin can reset PWDs
    if current_user.role != UserRole.SUPER_ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only SuperAdmin can reset user passwords"
        )
    
    # Verify target user exists
    target_user = await auth_service.user_repo.get_user_basic_by_email(reset_data.email_id)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with email '{reset_data.email_id}' not found"
        )
    
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    
    success = await auth_service.set_temporary_password(
        email=reset_data.email_id,
        temporary_password=reset_data.temporary_password,
        current_user_id=current_user.email,
        ip_address=ip_address,
        user_agent=user_agent
    )
    
    if success:
        return AdminResetPasswordResponse(
            success=True,
            message=f"Temporary password set for user '{reset_data.email_id}'. User will be required to change password on next login.",
            email=reset_data.email_id,
            must_change_password=True
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set temporary password"
        )


@router.post("/change-password", response_model=ChangePasswordResponse)
async def change_password(
    request: Request,
    password_data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Change the current user's PWD after admin has reset it.
    
    This endpoint is ONLY available when must_change_password=True,
    which is set by SuperAdmin via /auth/reset-pwd endpoint.
    
    Requires:
    - Current PWD (temporary PWD set by admin) for verification
    - New PWD to set
    
    The must_change_password flag is cleared after successful PWD change.
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    
    result = await auth_service.change_password(
        email=current_user.email,
        current_password=password_data.current_password,
        new_password=password_data.new_password,
        ip_address=ip_address,
        user_agent=user_agent
    )
    
    if result["success"]:
        return ChangePasswordResponse(
            success=True,
            message=result["message"]
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"]
        )


@router.get("/users")
async def list_users(
    request: Request,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    Lists users scoped by the logged-in user's role and department:
      - SuperAdmin: all users (mapped + unassigned), department-wise counts, unassigned users list.
      - Admin: users in current_user.department_name only, role-wise counts.
      - Others: 403.
    """
    # Gate: only Admin and SuperAdmin
    if current_user.role not in ("Admin", "SuperAdmin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin or SuperAdmin can list users"
        )

    try:
        # ---- SuperAdmin: show everything ----
        if current_user.role == "SuperAdmin":
            # Base users from login_credential
            all_users = await auth_service.user_repo.get_all_users()
            all_emails = {u["mail_id"] for u in all_users}

            # Enrich with dept-role mappings
            mappings = await auth_service.user_dept_mapping_repo.get_all_mappings()
            # mappings rows: {mail_id, department_name, role, created_at, created_by, user_name}

            # Build {email -> user summary} for ALL users (mapped + unassigned)
            by_email = {
                u["mail_id"]: {
                    "email": u["mail_id"],
                    "username": u["user_name"],
                    "global_is_active": u.get("is_active", True) if u.get("is_active") is not None else True,
                    "departments": []  # will be filled for mapped users; stays [] for unassigned
                }
                for u in all_users
            }

            # Aggregate dept-wise unique users (ignore NULL department_name used in special cases)
            dept_user_set: dict[str, set[str]] = defaultdict(set)
            assigned_emails: set[str] = set()

            for m in mappings:
                email = m.get("mail_id")
                dept = m.get("department_name")
    
                # Fill department-role mapping into the user's summary
                if email in by_email:
                    by_email[email]["departments"].append({
                        "department_name": dept,
                        "role": m.get("role"),
                        "is_active": m.get("is_active", True) if m.get("is_active") is not None else True,
                        "added_at": m.get("created_at"),
                        "added_by": m.get("created_by"),
                    })
                # Count only real departments (non-NULL)
                if dept is not None:
                    dept_user_set[dept].add(email)
                    assigned_emails.add(email)

            # Compute counts
            superadmin_emails = {m["mail_id"] for m in mappings if m["role"] == "SuperAdmin"}
            
            department_counts = {dept: len(users) for dept, users in dept_user_set.items()}
            unassigned_emails = sorted(all_emails - assigned_emails - superadmin_emails)
            unassigned_count = len(unassigned_emails)

            # Build a simple list for unassigned users (email + username)
            unassigned_users = [
                {
                    "email": e,
                    "username": by_email[e]["username"],
                    "global_is_active": by_email[e]["global_is_active"],
                    "departments": []  # explicitly empty to indicate "no department / no role yet"
                }
                for e in unassigned_emails
            ]

            return {
                "success": True,
                "scope": "all",
                "total_users": len(all_emails),
                "department_counts": department_counts,   # {"AI": 12, "ML": 8, ...}
                "unassigned_count": unassigned_count,     # users with no dept mapping
                "unassigned_users": unassigned_users,     # simple array for UI convenience
                "count": len(by_email),
                "users": list(by_email.values()),         # includes both mapped and unassigned (departments=[])
            }

        # ---- Admin: restrict to current_user.department_name ----
        admin_dept = current_user.department_name
        if not admin_dept:
            # Defensive: if token/user context lacks department, return empty
            log.warning(f"Admin {current_user.email} has no department_name in context")
            return {
                "success": True,
                "scope": "none",
                "total_users": 0,
                "role_counts": {},
                "count": 0,
                "users": []
            }

        dept_users = await auth_service.user_dept_mapping_repo.get_department_users(admin_dept)
        # dept_users rows: {mail_id, role, is_active, created_at, created_by, user_name, global_is_active}

        # Shape output and aggregate role-wise counts
        users_out: dict[str, dict] = {}
        role_counts: dict[str, int] = defaultdict(int)

        for du in dept_users:
            email = du.get("mail_id")
            role = du.get("role")
            role_counts[role] += 1

            if email not in users_out:
                users_out[email] = {
                    "email": email,
                    "username": du.get("user_name"),
                    "global_is_active": du.get("global_is_active", True) if du.get("global_is_active") is not None else True,
                    "departments": []
                }
            users_out[email]["departments"].append({
                "department_name": admin_dept,
                "role": role,
                "is_active": du.get("is_active", True) if du.get("is_active") is not None else True,
                "added_at": du.get("created_at"),
                "added_by": du.get("created_by"),
            })

        total_unique = len(users_out)

        return {
            "success": True,
            "scope": "department",
            "department_name": admin_dept,
            "total_users": total_unique,
            "role_counts": dict(role_counts),  # {"User": 94, "Developer": 20, "Admin": 5}
            "count": len(users_out),
            "users": list(users_out.values()),
        }

    except Exception as e:
        log.error(f"Error listing users: {e}")
        raise HTTPException(status_code=500, detail="Failed to list users")



@router.patch("/users/update-role")
async def update_user_role_in_department(
    request: Request,
    payload: UpdateUserRoleRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    Update a user's role and/or PWD within a department.
    - SuperAdmin: Can update any user in any department (must provide department_name in payload).
    - Admin: Can update users only within their own department.
    - Validates role is allowed in the department (if role update requested).
    - Updates role in userdepartmentmapping and/or PWD, writes audit logs.
    """

    # 1) Role gate: Admin and SuperAdmin only
    if current_user.role not in ("Admin", "SuperAdmin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin or SuperAdmin can update user details"
        )

    # At least one update field must be provided
    if not payload.new_role and not payload.temporary_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one of 'new_role' or 'temporary_password' must be provided"
        )

    target_email = payload.email_id.strip()
    new_role = payload.new_role.strip() if payload.new_role else None
    temporary_password = payload.temporary_password if payload.temporary_password else None

    # Prevent Admin from updating their own role
    if current_user.role == "Admin" and target_email == current_user.email and new_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin cannot update their own role"
        )

    # 2) Determine target department based on role
    if current_user.role == "SuperAdmin":
        # SuperAdmin must provide department in payload
        if not payload.department_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SuperAdmin must specify department_name in payload"
            )
        target_dept = payload.department_name.strip()
    else:
        # Admin: use their own department context
        admin_dept = current_user.department_name
        if not admin_dept:
            log.warning(f"Admin {current_user.email} has no department_name in current_user context")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin has no department context; contact SuperAdmin to assign a department"
            )
        # If Admin provides department_name, it must match their own department
        if payload.department_name and payload.department_name.strip() != admin_dept:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Admin can only update users in their own department '{admin_dept}'"
            )
        target_dept = admin_dept

    try:
        # 3) Verify target user is mapped to the target department
        in_dept = await auth_service.user_dept_mapping_repo.check_user_in_department(
            mail_id=target_email,
            department_name=target_dept
        )
        if not in_dept:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Target user is not in department '{target_dept}'"
            )

        # 3b) Block updates on SuperAdmin users
        target_global_role = await auth_service.user_dept_mapping_repo.get_user_role_for_department(
            mail_id=target_email,
            department_name=None
        )
        if target_global_role == "SuperAdmin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot update role for a SuperAdmin. SuperAdmin has system-wide access and is not tied to any department."
            )

        # Track what was updated
        updates_made = []
        old_role = None
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("User-Agent")

        # 4) Update role if provided
        if new_role:
            # Validate the new role is allowed in this department
            role_allowed = await auth_service.department_repo.is_role_allowed_in_department(
                department_name=target_dept,
                role_name=new_role
            )
            if not role_allowed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Role '{new_role}' is not allowed in department '{target_dept}'. "
                           f"Ask SuperAdmin to add this role to the department."
                )

            # Read old role for audit
            old_role = await auth_service.user_dept_mapping_repo.get_user_role_in_department(
                mail_id=target_email,
                department_name=target_dept
            )

            # Update the role
            updated = await auth_service.user_dept_mapping_repo.update_user_role_in_department(
                mail_id=target_email,
                department_name=target_dept,
                new_role=new_role
            )
            if not updated:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to update role"
                )

            # Audit log for role update
            try:
                await auth_service.audit_repo.log_action(
                    user_id=current_user.email,
                    action="ROLE_UPDATED_IN_DEPARTMENT",
                    resource_type="user",
                    resource_id=target_email,
                    old_value=old_role,
                    new_value=new_role,
                    ip_address=ip_address,
                    user_agent=user_agent
                )
            except Exception as audit_err:
                log.warning(f"Audit log failed for role update: {audit_err}")

            updates_made.append("role")

        # 5) Set temporary PWD if provided (user must change on next login)
        if temporary_password:
            password_updated = await auth_service.set_temporary_password(
                email=target_email,
                temporary_password=temporary_password,
                current_user_id=current_user.email,
                ip_address=ip_address,
                user_agent=user_agent
            )
            if not password_updated:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to set temporary password"
                )
            updates_made.append("password")

        # Build response message
        message_parts = []
        if "role" in updates_made:
            message_parts.append(f"role from '{old_role}' to '{new_role}'")
        if "password" in updates_made:
            message_parts.append("temporary password (user must change on next login)")

        return {
            "success": True,
            "message": f"Updated {' and '.join(message_parts)} for {target_email} in department '{target_dept}'",
            "data": {
                "email": target_email,
                "department_name": target_dept,
                "old_role": old_role,
                "new_role": new_role,
                "password_updated": "password" in updates_made,
                "must_change_password": "password" in updates_made,
                "updates": updates_made
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error updating role (actor={current_user.email}, target={target_email}, dept={target_dept}): {e}")
        raise HTTPException(status_code=500, detail="Internal server error while updating role")


@router.get("/get/search-paginated/users")
async def search_paginated_users_endpoint(
    request: Request,
    search_value: Optional[str] = Query(None, description="Substring match on email/username"),
    page_number: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    role: Optional[str] = Query(None, description="Filter by role"),
    department: Optional[str] = Query(None, description="SuperAdmin only: filter by department"),
    auth_service: AuthService = Depends(get_auth_service),
    user_data: User = Depends(get_current_user),
):
    """
    Role-aware search + pagination (NO status):
      - SuperAdmin: global view; can filter by department, role, and search.
      - Admin: restricted to current_user.department_name; can filter by role and search.
      - Others: 403.
    """
    if user_data.role not in ("Admin", "SuperAdmin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Admin or SuperAdmin can list users")

    limit = page_size
    offset = (page_number - 1) * page_size

    try:
        if user_data.role == "SuperAdmin":
            result = await auth_service.user_dept_mapping_repo.search_users_all(
                search=search_value,
                department_name=department,
                role=role,
                limit=limit,
                offset=offset
            )
            return {
                "success": True,
                "scope": "all",
                "filters": {
                    "search_value": search_value,
                    "department": department,
                    "role": role,
                },
                "page_number": page_number,
                "page_size": page_size,
                "total": result["total"],
                "count": len(result["rows"]),
                "users": result["rows"],
            }

        # ----- Admin path -----
        admin_dept = user_data.department_name
        if not admin_dept:
            log.warning(f"Admin {user_data.email} has no department_name in auth context")
            return {
                "success": True,
                "scope": "none",
                "page_number": page_number,
                "page_size": page_size,
                "total": 0,
                "count": 0,
                "users": [],
                "message": "No department found for current admin",
            }

        if department and department != admin_dept:
            raise HTTPException(status_code=403, detail=f"Admins can only query their department ({admin_dept}).")

        result = await auth_service.user_dept_mapping_repo.search_department_users_for_admin(
            admin_department=admin_dept,
            search=search_value,
            role=role,
            limit=limit,
            offset=offset,
        )
        return {
            "success": True,
            "scope": "department",
            "department_name": admin_dept,
            "filters": {"search_value": search_value, "role": role},
            "page_number": page_number,
            "page_size": page_size,
            "total": result["total"],
            "count": len(result["rows"]),
            "users": result["rows"],
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"[GET /auth/get/search-paginated/users] error: {e}")
        raise HTTPException(status_code=500, detail="Failed to search/list users")



@router.get("/admin-contacts")
async def get_admin_contacts(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    Returns a contact list of SuperAdmins (global) and Admins per department.
    Intended for newly registered members to know whom to contact for assignment.
    """
    try:
        # Pull all mappings once, then shape in-memory
        mappings = await auth_service.user_dept_mapping_repo.get_all_mappings()

        superadmins = sorted([
            {"email": m.get("mail_id"), "username": m.get("user_name")}
            for m in mappings
            if m.get("role") == "SuperAdmin" and m.get("department_name") is None
        ], key=lambda x: (x["username"] or "").lower())

        # Collect admins per department
        by_dept: Dict[str, List[Dict[str, str]]] = {}
        for m in mappings:
            if m.get("role") == "Admin" and m.get("department_name") is not None:
                dept = m.get("department_name")
                by_dept.setdefault(dept, [])
                by_dept[dept].append({"email": m.get("mail_id"), "username": m.get("user_name")})

        # Sort admins within each department and shape output list
        departments = []
        for dept, admins in by_dept.items():
            admins_sorted = sorted(admins, key=lambda x: (x["username"] or "").lower())
            departments.append({"department_name": dept, "admins": admins_sorted})
        departments.sort(key=lambda x: x["department_name"].lower())

        # Friendly message for the UI
        return {
            "success": True,
            "superadmins": superadmins,
            "departments": departments,
            "message": (
                "Contact a SuperAdmin for system-wide help, or a Department Admin "
                "to be assigned your role in that department."
            ),
        }
    except Exception as e:
        log.error(f"[GET /auth/admin-contacts] error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch admin contacts")


@router.get("/me/departments-with-roles")
async def get_current_user_department_roles(request: Request, auth_service: AuthService = Depends(get_auth_service)):
    """Get current user's departments with their specific roles in each department"""
    current_user = await get_current_user(request)
    
    # Get user's detailed department mappings
    department_roles = []
    if auth_service.user_dept_mapping_repo:
        # Get all mappings for this user with creation details
        async with auth_service.user_dept_mapping_repo.pool.acquire() as conn:
            query = """
            SELECT udm.department_name, udm.created_at, udm.created_by,
                   lc.role as user_global_role
            FROM userdepartmentmapping udm
            JOIN login_credential lc ON udm.mail_id = lc.mail_id
            WHERE udm.mail_id = $1
            ORDER BY udm.department_name
            """
            rows = await conn.fetch(query, current_user.email)
            
            for row in rows:
                department_roles.append({
                    "department_name": row["department_name"],
                    "role": row["user_global_role"],  # Currently same role for all departments
                    "added_to_department_at": row["created_at"],
                    "added_by": row["created_by"]
                })
    
    return {
        "user_id": current_user.id,
        "email": current_user.email,
        "username": current_user.username,
        "global_role": current_user.role,  # The single role from login_credential table
        "department_roles": department_roles,  # Detailed department information
        "note": "Currently all departments show the same role. To have different roles per department, the UserDepartmentMapping table would need a role column."
    }


@router.get("/superadmin/exists")
async def check_superadmin_exists(
    auth_service: AuthService = Depends(get_auth_service)
):
    """Check if a SuperAdmin user exists in the system"""
    try:
        superadmin_exists = await auth_service.user_dept_mapping_repo.has_superadmin_assignment()
        return {
            "success": True,
            "superadmin_exists": superadmin_exists,
            "message": "SuperAdmin exists" if superadmin_exists else "No SuperAdmin found"
        }
    except Exception as e:
        log.error(f"Error checking SuperAdmin existence: {e}")
        raise HTTPException(
            status_code=500, 
            detail="Internal server error while checking SuperAdmin existence"
        )


# ─────────────────────────────────────────────────────────────────────────────
# USER ENABLE/DISABLE ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@router.patch("/users/set-active-status", response_model=UserActiveStatusResponse)
async def set_user_active_status(
    request: Request,
    payload: SetUserActiveStatusRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Enable or disable a user's login access.
    
    Supports two modes:
    1. **Global disable** (department_name=None): Disables user across ALL departments
       - Only SuperAdmin can perform global disable
    2. **Department-specific disable** (department_name provided): Disables user in specific department only
       - SuperAdmin: Can disable in any department
       - Admin: Can only disable users in their own department
    
    When a user is globally disabled:
    - They cannot log in to ANY department
    
    When a user is disabled in a specific department:
    - They cannot log in to THAT department
    - They can still log in to other departments they have access to
    """
    # Only Admin and SuperAdmin can manage user active status
    if current_user.role not in ["Admin", "SuperAdmin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin and SuperAdmin can enable/disable users"
        )
    
    target_email = payload.email_id.strip()
    new_status = payload.is_active
    target_department = payload.department_name
    
    # Prevent users from disabling themselves
    if target_email == current_user.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own active status"
        )
    
    try:
        # Check if target user exists
        target_user = await auth_service.user_repo.get_user_basic_by_email(target_email)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User '{target_email}' not found"
            )
        
        # Admin cannot disable SuperAdmin users
        target_primary_role = await auth_service.user_dept_mapping_repo.get_user_primary_role(target_email)
        if current_user.role == "Admin" and target_primary_role == "SuperAdmin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin cannot change active status of SuperAdmin users"
            )
        
        # Determine scope: global or department-specific
        if target_department is None:
            # GLOBAL DISABLE - Only SuperAdmin can do this
            if current_user.role != "SuperAdmin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only SuperAdmin can globally enable/disable users. Admins must specify a department."
                )
            
            # Get current status for audit
            current_status = await auth_service.user_repo.is_user_active(target_email)
            
            # Update global status
            success = await auth_service.user_repo.set_user_active_status(target_email, new_status)
            scope = "global"
            
        else:
            # DEPARTMENT-SPECIFIC DISABLE
            # Verify department exists
            if auth_service.department_repo:
                dept_exists = await auth_service.department_repo.department_exists(target_department)
                if not dept_exists:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Department '{target_department}' does not exist"
                    )
            
            # For Admin users, verify they can only manage their own department
            if current_user.role == "Admin":
                admin_dept = current_user.department_name
                if not admin_dept:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Admin has no department context"
                    )
                if admin_dept != target_department:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"You can only manage users in your department '{admin_dept}'"
                    )
            
            # Check if target user is in the specified department
            target_in_dept = await auth_service.user_dept_mapping_repo.check_user_in_department(
                mail_id=target_email,
                department_name=target_department
            )
            if not target_in_dept:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User '{target_email}' is not a member of department '{target_department}'"
                )
            
            # Get current department-specific status for audit
            current_status = await auth_service.user_dept_mapping_repo.is_user_active_in_department(
                target_email, target_department
            )
            
            # Update department-specific status
            success = await auth_service.user_dept_mapping_repo.set_user_active_in_department(
                target_email, target_department, new_status
            )
            scope = "department"
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update user status"
            )
        
        # Log the action
        status_text = "enabled" if new_status else "disabled"
        old_status_text = "enabled" if current_status else "disabled"
        action = "USER_STATUS_CHANGED_GLOBAL" if scope == "global" else "USER_STATUS_CHANGED_IN_DEPARTMENT"
        
        try:
            await auth_service.audit_repo.log_action(
                user_id=current_user.email,
                action=action,
                resource_type="user",
                resource_id=target_email,
                old_value=f"{old_status_text} (dept: {target_department or 'global'})",
                new_value=f"{status_text} (dept: {target_department or 'global'})",
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("User-Agent")
            )
        except Exception as audit_err:
            log.warning(f"Audit log failed for user status change: {audit_err}")
        
        if scope == "global":
            message = f"User '{target_email}' has been {status_text} globally (all departments)"
        else:
            message = f"User '{target_email}' has been {status_text} in department '{target_department}'"
        
        return UserActiveStatusResponse(
            success=True,
            message=message,
            email=target_email,
            is_active=new_status,
            department_name=target_department,
            scope=scope
        )
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error changing user active status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user active status"
        )


@router.get("/users/{email}/active-status")
async def get_user_active_status(
    email: str,
    department_name: Optional[str] = Query(None, description="Department to check status for. If None, returns global status."),
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Get a user's active status.
    
    - If department_name is provided: Returns department-specific status
    - If department_name is None: Returns global status and all department statuses
    
    Access Control:
    - SuperAdmin: Can check any user's status in any department
    - Admin: Can check users within their department only
    """
    # Only Admin and SuperAdmin can check user status
    if current_user.role not in ["Admin", "SuperAdmin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin and SuperAdmin can check user active status"
        )
    
    try:
        # Check if target user exists
        target_user = await auth_service.user_repo.get_user_basic_by_email(email)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User '{email}' not found"
            )
        
        # Get global status
        global_is_active = await auth_service.user_repo.is_user_active(email)
        global_is_active = global_is_active if global_is_active is not None else True
        
        if department_name:
            # Department-specific query
            # For Admin users, verify they can only check their own department
            if current_user.role == "Admin":
                admin_dept = current_user.department_name
                if admin_dept != department_name:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"You can only check users in your department '{admin_dept}'"
                    )
            
            # Check if user is in the department
            target_in_dept = await auth_service.user_dept_mapping_repo.check_user_in_department(
                mail_id=email,
                department_name=department_name
            )
            if not target_in_dept:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User '{email}' is not a member of department '{department_name}'"
                )
            
            dept_is_active = await auth_service.user_dept_mapping_repo.is_user_active_in_department(
                email, department_name
            )
            dept_is_active = dept_is_active if dept_is_active is not None else True
            
            # Effective status: user must be active globally AND in department
            effective_is_active = global_is_active and dept_is_active
            
            return {
                "success": True,
                "email": email,
                "username": target_user.get("user_name"),
                "global_is_active": global_is_active,
                "department_name": department_name,
                "department_is_active": dept_is_active,
                "effective_is_active": effective_is_active,
                "message": "User can login" if effective_is_active else (
                    "User is globally disabled" if not global_is_active 
                    else f"User is disabled in department '{department_name}'"
                )
            }
        else:
            # Return global status and all department statuses
            # For Admin, only return their department
            if current_user.role == "Admin":
                admin_dept = current_user.department_name
                if not admin_dept:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Admin has no department context"
                    )
                
                # Check if user is in admin's department
                target_in_dept = await auth_service.user_dept_mapping_repo.check_user_in_department(
                    mail_id=email,
                    department_name=admin_dept
                )
                if not target_in_dept:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"User is not in your department '{admin_dept}'"
                    )
                
                dept_status = await auth_service.user_dept_mapping_repo.get_user_department_status(
                    email, admin_dept
                )
                departments = [{
                    "department_name": admin_dept,
                    "is_active": dept_status.get("is_active", True) if dept_status else True,
                    "role": dept_status.get("role") if dept_status else None
                }]
            else:
                # SuperAdmin gets all departments
                user_depts = await auth_service.user_dept_mapping_repo.get_user_departments(email)
                departments = [
                    {
                        "department_name": d.get("department_name"),
                        "is_active": d.get("is_active", True),
                        "role": d.get("role")
                    }
                    for d in user_depts
                ]
            
            return {
                "success": True,
                "email": email,
                "username": target_user.get("user_name"),
                "global_is_active": global_is_active,
                "departments": departments
            }
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error getting user active status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get user active status"
        )


@router.get("/departments")
async def get_available_departments(
    auth_service: AuthService = Depends(get_auth_service)
):
    """Get available departments for registration (public endpoint)"""
    try:
        # Get departments from the user repository using proper async context manager
        async with auth_service.user_repo.pool.acquire() as conn:
            results = await conn.fetch("SELECT department_name FROM departments ORDER BY department_name")
            department_list = [row["department_name"] for row in results]
            
        return {
            "success": True,
            "departments": department_list,
            "message": "Departments retrieved successfully"
        }
    except Exception as e:
        log.error(f"Error fetching departments for registration: {e}")
        return {
            "success": False,
            "departments": [],
            "message": "Failed to fetch departments"
        }



def get_role_access_service() -> RoleAccessService:
    """Dependency to get RoleAccessService instance"""
    return ServiceProvider.get_role_access_service()

