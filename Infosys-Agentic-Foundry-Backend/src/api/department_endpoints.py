from fastapi import APIRouter, Depends, HTTPException, Request, Query
from typing import List, Union, Optional
from src.auth.models import (
    AddDepartmentRequest, DepartmentResponse, DepartmentListResponse, User,
    AddAdminsToDepartmentRequest, RemoveAdminFromDepartmentRequest,
    AddRoleToDepartmentRequest, RemoveRoleFromDepartmentRequest, DepartmentRoleResponse,
    DepartmentUserInfo, DepartmentUsersResponse, DepartmentUsersInfo, AllDepartmentsUsersResponse,
    PaginatedDepartmentUsersResponse, PaginatedAllDepartmentsUsersResponse,
    SetRolePermissionsRequest, AccessPermission
)
from src.database.services import DepartmentService, RoleAccessService
from src.auth.dependencies import get_current_user
from src.api.dependencies import ServiceProvider
from telemetry_wrapper import logger as log

router = APIRouter(prefix="/departments", tags=["Department Management"])


# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def get_department_service(request: Request) -> DepartmentService:
    """Dependency to get DepartmentService instance"""
    return ServiceProvider.get_department_service()

def check_superadmin_permissions(user: User) -> None:
    """Check if user has super admin permissions"""
    if user.role != 'SuperAdmin':
        raise HTTPException(
            status_code=403, 
            detail="Access denied. Only SuperAdmin can access department management endpoints."
        )

def check_admin_permissions(user: User) -> None:
    """Check if user has admin or super admin permissions"""
    if user.role not in ['Admin', 'SuperAdmin']:
        raise HTTPException(
            status_code=403, 
            detail="Access denied. Only Admin and SuperAdmin can access role management endpoints."
        )

def check_department_admin_permissions(user: User, target_department: str) -> None:
    """Check if user has permissions to manage the specified department"""
    # SuperAdmin can manage any department
    if user.role == 'SuperAdmin':
        return
    
    # Admin can only manage their own department
    if user.role == 'Admin':
        user_department = getattr(user, 'department_name', None) 
        if user_department != target_department:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Admin users can only manage their own department ('{user_department}'). Cannot manage department '{target_department}'."
            )
        return
    
    # Other roles cannot manage departments
    raise HTTPException(
        status_code=403,
        detail="Access denied. Only Admin and SuperAdmin can manage departments."
    )

@router.post("/add", response_model=DepartmentResponse)
async def add_department(
    request: Request,
    department_request: AddDepartmentRequest,
    user_data: User = Depends(get_current_user),
    department_service: DepartmentService = Depends(get_department_service)
):
    """Add a new department - only SuperAdmin can add departments"""
    try:
        # Check superadmin permissions first
        check_superadmin_permissions(user_data)
        
        # Get client info for audit
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent", "")
        
        result = await department_service.add_department(
            request=department_request,
            created_by=user_data.email,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Add department endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/list", response_model=DepartmentListResponse)
async def get_all_departments(
    request: Request,
    user_data: User = Depends(get_current_user),
    department_service: DepartmentService = Depends(get_department_service)
):
    """Get all departments - only SuperAdmin can view departments"""
    try:
        result = await department_service.get_all_departments(requested_by=user_data.email)
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Get all departments endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/{department_name}", response_model=DepartmentResponse)
async def get_department_by_name(
    request: Request,
    department_name: str,
    user_data: User = Depends(get_current_user),
    department_service: DepartmentService = Depends(get_department_service)
):
    """Get a specific department by name - only SuperAdmin can view departments"""
    try:
        
        result = await department_service.get_department_by_name(
            department_name=department_name,
            requested_by=user_data.email
        )
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Get department by name endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/{department_name}", response_model=DepartmentResponse)
async def delete_department(
    request: Request,
    department_name: str,
    user_data: User = Depends(get_current_user),
    department_service: DepartmentService = Depends(get_department_service)
):
    """Delete a department - only SuperAdmin can delete departments"""
    try:
        # Check superadmin permissions first
        check_superadmin_permissions(user_data)
        
        # Get client info for audit
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent", "")
        
        result = await department_service.delete_department(
            department_name=department_name,
            deleted_by=user_data.email,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Delete department endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{department_name}/roles/add", response_model=DepartmentRoleResponse)
async def add_role_to_department(
    request: Request,
    department_name: str,
    role_request: AddRoleToDepartmentRequest,
    user_data: User = Depends(get_current_user),
    department_service: DepartmentService = Depends(get_department_service)
):
    """Add a role to department's allowed roles list - Admins can manage their own department, SuperAdmin can manage any"""
    try:
        # Check department-specific admin permissions
        check_department_admin_permissions(user_data, department_name)
        
        # Get client info for audit
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent", "")
        
        result = await department_service.add_role_to_department(
            department_name=department_name,
            role_name=role_request.role_name,
            added_by=user_data.email,
            ip_address=ip_address,
            user_agent=user_agent,
            user_department_name=department_name
        )
        
        # Auto-set default permissions based on role name
        if result.success:
            try:
                role_service = ServiceProvider.get_role_access_service()
                role_name_lower = role_request.role_name.strip().lower()
                
                if role_name_lower in ("admin", "developer"):
                    # Admin and Developer get all permissions
                    all_true = AccessPermission(tools=True, agents=True)
                    permissions_request = SetRolePermissionsRequest(
                        department_name=department_name,
                        role_name=role_request.role_name,
                        read_access=all_true,
                        add_access=all_true,
                        update_access=all_true,
                        delete_access=all_true,
                        execute_access=all_true,
                        execution_steps_access=True,
                        tool_verifier_flag_access=True,
                        plan_verifier_flag_access=True,
                        online_evaluation_flag_access=True,
                        evaluation_access=True,
                        vault_access=True,
                        data_connector_access=True,
                        knowledgebase_access=True,
                        validator_access=True,
                        file_context_access=True,
                        canvas_view_access=True,
                        context_access=True
                    )
                elif role_name_lower == "user":
                    # User gets only agent read access and agent execute access
                    read_perm = AccessPermission(tools=False, agents=True)
                    execute_perm = AccessPermission(tools=False, agents=True)
                    no_perm = AccessPermission(tools=False, agents=False)
                    permissions_request = SetRolePermissionsRequest(
                        department_name=department_name,
                        role_name=role_request.role_name,
                        read_access=read_perm,
                        add_access=no_perm,
                        update_access=no_perm,
                        delete_access=no_perm,
                        execute_access=execute_perm,
                        execution_steps_access=False,
                        tool_verifier_flag_access=False,
                        plan_verifier_flag_access=False,
                        online_evaluation_flag_access=False,
                        evaluation_access=False,
                        vault_access=False,
                        data_connector_access=False,
                        knowledgebase_access=False,
                        validator_access=False,
                        file_context_access=False,
                        canvas_view_access=False,
                        context_access=False
                    )
                else:
                    permissions_request = None
                
                if permissions_request:
                    perm_result = await role_service.set_role_permissions(
                        request=permissions_request,
                        set_by=user_data.email,
                        ip_address=ip_address,
                        user_agent=user_agent,
                        department_name=department_name
                    )
                    if perm_result.success:
                        log.info(f"Auto-set default permissions for role '{role_request.role_name}' in department '{department_name}'")
                    else:
                        log.warning(f"Failed to auto-set permissions for role '{role_request.role_name}': {perm_result.message}")
            except Exception as perm_error:
                log.warning(f"Failed to auto-set default permissions for role '{role_request.role_name}': {perm_error}")
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Add role to department endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/{department_name}/roles/{role_name}", response_model=DepartmentRoleResponse)
async def remove_role_from_department(
    request: Request,
    department_name: str,
    role_name: str,
    user_data: User = Depends(get_current_user),
    department_service: DepartmentService = Depends(get_department_service)
):
    """Remove a role from department's allowed roles list - Admins can manage their own department, SuperAdmin can manage any"""
    try:
        # Check department-specific admin permissions
        check_department_admin_permissions(user_data, department_name)
        
        # Get client info for audit
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent", "")
        
        result = await department_service.remove_role_from_department(
            department_name=department_name,
            role_name=role_name,
            removed_by=user_data.email,
            ip_address=ip_address,
            user_agent=user_agent,
            user_department_name=user_data.department_name
        )
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Remove role from department endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/{department_name}/roles", response_model=DepartmentRoleResponse)
async def get_department_roles(
    request: Request,
    department_name: str,
    user_data: User = Depends(get_current_user),
    department_service: DepartmentService = Depends(get_department_service)
):
    """Get all allowed roles for a department - Admins can view their own department, SuperAdmin can view any"""
    try:
        
        result = await department_service.get_department_roles(
            department_name=department_name,
            requested_by=user_data.email,
            user_department_name=user_data.department_name
        )
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Get department roles endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{department_name}/users", response_model=Union[AllDepartmentsUsersResponse, DepartmentUsersResponse])
async def get_department_users(
    department_name: str,
    user_data: User = Depends(get_current_user)
):
    """
    Get users in department(s).
    
    **Access Control:**
    - **SuperAdmin**: Pass `"all"` to get users from ALL departments, or a specific department name
    - **Admin**: Can only view users in their own department
    
    Args:
        department_name: Department name to query, or "all" for SuperAdmin to get all departments
    
    Returns:
        - If "all": List of all departments with their users (SuperAdmin only)
        - If specific department: List of users in that department
    """
    user_dept_mapping_repo = ServiceProvider.get_user_department_mapping_repository()
    department_service = get_department_service(None)
    
    # Handle "all" departments request (SuperAdmin only)
    if department_name.lower() == "all":
        if user_data.role != "SuperAdmin":
            raise HTTPException(
                status_code=403,
                detail="Only SuperAdmin can view users across all departments. Please specify your department name."
            )
        
        # Get all departments
        all_departments = await department_service.list_departments()
        
        departments_data = []
        total_users = 0
        
        for dept in all_departments:
            dept_name = dept.get("department_name")
            if dept_name:  # Skip if department name is None
                dept_users = await user_dept_mapping_repo.get_department_users(dept_name)
                
                users_list = [
                    DepartmentUserInfo(
                        email=user["mail_id"],
                        user_name=user.get("user_name"),
                        role=user["role"],
                        is_active=user.get("is_active", True) if user.get("is_active") is not None else True,
                        global_is_active=user.get("global_is_active", True) if user.get("global_is_active") is not None else True
                    )
                    for user in dept_users
                ]
                
                departments_data.append(DepartmentUsersInfo(
                    department_name=dept_name,
                    user_count=len(users_list),
                    users=users_list
                ))
                total_users += len(users_list)
        
        return AllDepartmentsUsersResponse(
            total_departments=len(departments_data),
            total_users=total_users,
            departments=departments_data
        )
    
    # Handle specific department request
    # Admin can only view their own department
    if user_data.role == "Admin":
        admin_dept = getattr(user_data, 'department_name', None)
        if admin_dept != department_name:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. You can only view users in your department '{admin_dept}'."
            )
    elif user_data.role != "SuperAdmin":
        raise HTTPException(
            status_code=403,
            detail="Only Admin and SuperAdmin can view department users."
        )
    
    # Get users for specific department
    department_users = await user_dept_mapping_repo.get_department_users(department_name)
    
    return DepartmentUsersResponse(
        department_name=department_name,
        total_count=len(department_users),
        users=[
            DepartmentUserInfo(
                email=user["mail_id"],
                user_name=user.get("user_name"),
                role=user["role"],
                is_active=user.get("is_active", True) if user.get("is_active") is not None else True,
                global_is_active=user.get("global_is_active", True) if user.get("global_is_active") is not None else True
            )
            for user in department_users
        ]
    )


@router.get("/{department_name}/users/search", response_model=Union[PaginatedAllDepartmentsUsersResponse, PaginatedDepartmentUsersResponse])
async def search_department_users(
    department_name: str,
    search: Optional[str] = Query(None, description="Search term for email or username (partial match)"),
    role: Optional[str] = Query(None, description="Filter by role (Admin, Developer, etc.)"),
    is_active: Optional[bool] = Query(None, description="Filter by active status in department"),
    global_is_active: Optional[bool] = Query(None, description="Filter by global active status"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    user_data: User = Depends(get_current_user)
):
    """
    Search and paginate users in department(s).
    
    **Access Control:**
    - **SuperAdmin**: Pass `"all"` to search users across ALL departments, or a specific department name
    - **Admin**: Can only search users in their own department
    
    Args:
        department_name: Department name to query, or "all" for SuperAdmin to search all departments
        search: Optional search term for email or username (partial, case-insensitive match)
        role: Optional filter by role name
        is_active: Optional filter by department-level active status
        global_is_active: Optional filter by global account active status
        page: Page number (starts from 1)
        page_size: Number of items per page (max 100)
    
    Returns:
        Paginated list of users matching the search criteria
    """
    user_dept_mapping_repo = ServiceProvider.get_user_department_mapping_repository()
    department_service = get_department_service(None)
    
    def filter_user(user: dict) -> bool:
        """Apply filters to a user record"""
        # Search filter (email or username)
        if search:
            search_lower = search.lower()
            email_match = search_lower in user.get("mail_id", "").lower()
            username_match = search_lower in (user.get("user_name") or "").lower()
            if not (email_match or username_match):
                return False
        
        # Role filter
        if role and user.get("role", "").lower() != role.lower():
            return False
        
        # is_active filter
        user_is_active = user.get("is_active", True) if user.get("is_active") is not None else True
        if is_active is not None and user_is_active != is_active:
            return False
        
        # global_is_active filter
        user_global_is_active = user.get("global_is_active", True) if user.get("global_is_active") is not None else True
        if global_is_active is not None and user_global_is_active != global_is_active:
            return False
        
        return True
    
    def convert_to_user_info(user: dict, dept_name: str = None) -> DepartmentUserInfo:
        """Convert a user dict to DepartmentUserInfo"""
        return DepartmentUserInfo(
            email=user["mail_id"],
            user_name=user.get("user_name"),
            role=user["role"],
            is_active=user.get("is_active", True) if user.get("is_active") is not None else True,
            global_is_active=user.get("global_is_active", True) if user.get("global_is_active") is not None else True
        )
    
    # Handle "all" departments request (SuperAdmin only)
    if department_name.lower() == "all":
        if user_data.role != "SuperAdmin":
            raise HTTPException(
                status_code=403,
                detail="Only SuperAdmin can search users across all departments. Please specify your department name."
            )
        
        # Get all departments
        all_departments = await department_service.list_departments()
        
        all_users = []
        total_users = 0
        
        for dept in all_departments:
            dept_name = dept.get("department_name")
            if dept_name:
                dept_users = await user_dept_mapping_repo.get_department_users(dept_name)
                total_users += len(dept_users)
                
                # Filter and add department info to each user
                for user in dept_users:
                    if filter_user(user):
                        user_info = convert_to_user_info(user, dept_name)
                        # Add department reference for context
                        user_info_dict = user_info.dict()
                        user_info_dict["department"] = dept_name
                        all_users.append(user_info_dict)
        
        # Apply pagination
        filtered_count = len(all_users)
        total_pages = (filtered_count + page_size - 1) // page_size if filtered_count > 0 else 1
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_users = all_users[start_idx:end_idx]
        
        return PaginatedAllDepartmentsUsersResponse(
            total_departments=len(all_departments),
            total_users=total_users,
            filtered_count=filtered_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1,
            users=[DepartmentUserInfo(**{k: v for k, v in u.items() if k != "department"}) for u in paginated_users]
        )
    
    # Handle specific department request
    # Admin can only view their own department
    if user_data.role == "Admin":
        admin_dept = getattr(user_data, 'department_name', None)
        if admin_dept != department_name:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. You can only search users in your department '{admin_dept}'."
            )
    elif user_data.role != "SuperAdmin":
        raise HTTPException(
            status_code=403,
            detail="Only Admin and SuperAdmin can search department users."
        )
    
    # Get users for specific department
    department_users = await user_dept_mapping_repo.get_department_users(department_name)
    
    # Apply filters
    filtered_users = [user for user in department_users if filter_user(user)]
    
    # Apply pagination
    total_count = len(filtered_users)
    total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paginated_users = filtered_users[start_idx:end_idx]
    
    return PaginatedDepartmentUsersResponse(
        department_name=department_name,
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_previous=page > 1,
        users=[convert_to_user_info(user) for user in paginated_users]
    )