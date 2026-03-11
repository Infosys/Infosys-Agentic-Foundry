import bcrypt
import jwt
import secrets
from datetime import datetime, timedelta
from typing import Optional, List
from src.auth.models import User, UserRole, UserStatus, LoginRequest, LoginResponse, RegisterRequest, RegisterResponse, RefreshTokenResponse
from src.auth.repositories import UserRepository, AuditLogRepository, RefreshTokenRepository, DepartmentRepository, UserDepartmentMappingRepository
from telemetry_wrapper import logger as log
from src.config.settings import (
    JWT_SECRET, JWT_ALGORITHM, ACCESS_TOKEN_EXPIRE_SECONDS,
    REFRESH_TOKEN_EXPIRE_DAYS, ENABLE_REFRESH_TOKENS
)

# In-memory blacklist for demonstration (use persistent store in production)
JWT_BLACKLIST = set()

class AuthService:
    """Service for authentication operations"""

    def __init__(self, user_repo: UserRepository, audit_repo: AuditLogRepository, refresh_repo: RefreshTokenRepository = None, department_repo: DepartmentRepository = None, user_dept_mapping_repo: UserDepartmentMappingRepository = None):
        self.user_repo = user_repo
        self.audit_repo = audit_repo
        # refresh_repo is optional to keep backward compatibility if not wired yet
        self.refresh_repo = refresh_repo
        # department_repo is optional for backward compatibility but needed for role validation
        self.department_repo = department_repo
        # user_dept_mapping_repo for managing user-department relationships
        self.user_dept_mapping_repo = user_dept_mapping_repo

    async def _log_login_failure(self, user_id: str, email: str, reason: str, ip_address: str, user_agent: str):
        """Helper to log failed login attempts"""
        await self.audit_repo.log_action(
            user_id=user_id,
            action="LOGIN_FAILED",
            resource_type="user",
            resource_id=email,
            new_value=reason,
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def login(self, login_request: LoginRequest, ip_address: str = None, user_agent: str = None) -> LoginResponse:
        """Authenticate user and create session"""
        try:
            # Early check for required dependencies
            if not self.user_dept_mapping_repo:
                await self._log_login_failure(None, login_request.email_id, "User-department mapping service not available", ip_address, user_agent)
                return LoginResponse(approval=False, message="Login service temporarily unavailable")
            
            requested_department = login_request.department_name if login_request.department_name else "General"
            user_email = login_request.email_id
            
            # Get user by email - this returns role from userdepartmentmapping JOIN
            # For no department: checks for SuperAdmin with NULL department
            # For specific department: checks user's role in that department
            user_data = await self.user_repo.get_user_by_email(user_email, requested_department)
            
            if not user_data:
                await self._log_login_failure(None, user_email, "User not found", ip_address, user_agent)
                return LoginResponse(approval=False, message="User not found")
            
            # Check PWD first before any additional processing
            if not bcrypt.checkpw(login_request.password.encode('utf-8'), user_data['password'].encode('utf-8')):
                await self._log_login_failure(user_data['mail_id'], user_email, "Incorrect password", ip_address, user_agent)
                return LoginResponse(approval=False, message="Incorrect password")
            
            # Check if user account is active (global disable)
            is_active = user_data.get('is_active', True)  # Default to True for backward compatibility
            if not is_active:
                await self._log_login_failure(user_data['mail_id'], user_email, "Account is disabled", ip_address, user_agent)
                return LoginResponse(approval=False, message="Your account has been disabled. Please contact an administrator.")
            
            # Role is already fetched via JOIN in get_user_by_email
            user_role = user_data.get('role')
            
            # Handle SuperAdmin case - can login without department or to any existing department
            if user_role == "SuperAdmin":
                if requested_department is not None and self.department_repo:
                    department_exists = await self.department_repo.department_exists(requested_department)
                    if not department_exists:
                        await self._log_login_failure(user_data['mail_id'], user_email, f"Department '{requested_department}' does not exist", ip_address, user_agent)
                        return LoginResponse(approval=False, message=f"Department '{requested_department}' does not exist")
            else:
                # Non-SuperAdmin users must provide department
                if requested_department is None:
                    await self._log_login_failure(user_data['mail_id'], user_email, "Department is required for login", ip_address, user_agent)
                    return LoginResponse(approval=False, message="Department is required for login. Please specify your department.")
                
                # Validate department exists
                if self.department_repo:
                    department_exists = await self.department_repo.department_exists(requested_department)
                    if not department_exists:
                        await self._log_login_failure(user_data['mail_id'], user_email, f"Department '{requested_department}' does not exist", ip_address, user_agent)
                        return LoginResponse(approval=False, message=f"Department '{requested_department}' does not exist")
                
                # If user doesn't have a role in the requested department
                if not user_role:
                    user_dept_data = await self.user_dept_mapping_repo.get_user_departments(user_email)
                    user_departments = [d.get('department_name') for d in user_dept_data] if user_dept_data else []
                    dept_list = ", ".join(filter(None, user_departments)) if user_departments else "none"
                    
                    await self._log_login_failure(
                        user_data['mail_id'], user_email,
                        f"User does not have access to department '{requested_department}'. User departments: {dept_list}",
                        ip_address, user_agent
                    )
                    
                    if user_departments:
                        return LoginResponse(
                            approval=False, 
                            message=f"You do not have access to department '{requested_department}'. Your departments: {dept_list}"
                        )
                    else:
                        return LoginResponse(
                            approval=False,
                            message="You have not been assigned to any department yet. Please contact an administrator."
                        )
                
                # Check if user is active in the specific department (department-level disable)
                dept_is_active = await self.user_dept_mapping_repo.is_user_active_in_department(user_email, requested_department)
                if dept_is_active is False:  # Explicitly check for False, not None
                    await self._log_login_failure(
                        user_data['mail_id'], user_email, 
                        f"User is disabled in department '{requested_department}'", 
                        ip_address, user_agent
                    )
                    return LoginResponse(
                        approval=False, 
                        message=f"Your access to department '{requested_department}' has been disabled. Please contact your department administrator."
                    )
            
            # Generate short-lived access JWT token
            payload = {
                "mail_id": user_data['mail_id'],
                "user_name": user_data['user_name'],
                "role": user_role,
                "department_name": requested_department,
                "exp": datetime.utcnow() + timedelta(seconds=ACCESS_TOKEN_EXPIRE_SECONDS)
            }
            token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

            # Generate refresh token if repository configured
            if self.refresh_repo and ENABLE_REFRESH_TOKENS:
                refresh_token = secrets.token_urlsafe(64)
                refresh_expires = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
                try:
                    await self.refresh_repo.store_token(
                        user_mail_id=user_data['mail_id'],
                        refresh_token=refresh_token,
                        expires_at=refresh_expires,
                        user_agent=user_agent,
                        ip_address=ip_address,
                        role=user_role,
                        department_name=requested_department
                    )
                except Exception as e:
                    log.error(f"Failed storing refresh token: {e}")
                    refresh_token = None
            else:
                refresh_token = None

            # Log successful login
            await self.audit_repo.log_action(
                user_id=user_data['mail_id'],
                action="LOGIN_SUCCESS",
                resource_type="user",
                resource_id=login_request.email_id,
                new_value=f"Role: {user_role}, Department: {requested_department if requested_department else 'N/A'}",
                ip_address=ip_address,
                user_agent=user_agent
            )

            # Check if user must change PWD (temporary PWD flow)
            must_change_password = await self.user_repo.get_must_change_password_status(user_data['mail_id'])
            must_change_password = must_change_password if must_change_password is not None else False

            return LoginResponse(
                approval=True,
                token=token,
                refresh_token=refresh_token,
                role=user_role,
                username=user_data['user_name'],
                email=user_data['mail_id'],
                department_name=requested_department,
                must_change_password=must_change_password,
                message="Login successful. Please change your password." if must_change_password else "Login successful",
            )
            
        except Exception as e:
            log.error(f"Login error: {e}")
            return LoginResponse(approval=False, message="Login failed due to an error")
    
    async def guest_login(self, ip_address: str = None, user_agent: str = None) -> LoginResponse:
        """Creates or retrieves a guest user and establishes a valid session."""
        try:
            GUEST_EMAIL = "guest@example.com"
            GUEST_USERNAME = "Guest"
            GUEST_ROLE = UserRole.USER.value

            # 1. Find or create the guest user
            user_data = await self.user_repo.get_user_by_email(GUEST_EMAIL)
            
            if not user_data:
                # Create a guest user if it doesn't exist
                log.info(f"Guest user not found. Creating a new one.")
                password_hash = bcrypt.hashpw(secrets.token_bytes(16), bcrypt.gensalt()).decode('utf-8')
                user_id = await self.user_repo.create_user(
                    email=GUEST_EMAIL,
                    username=GUEST_USERNAME,
                    password=password_hash,
                    role=GUEST_ROLE
                )
                if not user_id:
                    return LoginResponse(approval=False, message="Failed to create guest user account.")
                # Fetch the newly created user's data
                user_data = await self.user_repo.get_user_by_email(GUEST_EMAIL)

            # Generate JWT token
            payload = {
                "mail_id": user_data['mail_id'],
                "user_name": user_data['user_name'],
                "role": user_data['role'],
                "department_name": user_data.get('department_name'),  # Guests typically don't have departments
                "exp": datetime.utcnow() + timedelta(seconds=ACCESS_TOKEN_EXPIRE_SECONDS)
            }
            token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
            refresh_token = None
            if self.refresh_repo and ENABLE_REFRESH_TOKENS:
                refresh_token = secrets.token_urlsafe(64)
                refresh_expires = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
                try:
                    await self.refresh_repo.store_token(
                        user_mail_id=user_data['mail_id'],
                        refresh_token=refresh_token,
                        expires_at=refresh_expires,
                        user_agent=user_agent,
                        ip_address=ip_address,
                        role=user_data['role'],
                        department_name=user_data.get('department_name')
                    )
                except Exception as e:
                    log.error(f"Failed storing refresh token (guest): {e}")
                    refresh_token = None

            # 3. Log the guest login action
            await self.audit_repo.log_action(
                user_id=user_data['mail_id'],
                action="GUEST_LOGIN_SUCCESS",
                resource_type="user",
                resource_id=GUEST_EMAIL,
                ip_address=ip_address,
                user_agent=user_agent
            )

            return LoginResponse(
                approval=True,
                token=token,
                refresh_token=refresh_token,
                role=user_data['role'],
                username=user_data['user_name'],
                email=user_data['mail_id'],
                department_name=user_data.get('department_name'),  # Include department (usually None for guests)
                message="Guest login successful"
            )

        except Exception as e:
            log.error(f"Guest login error: {e}")
            return LoginResponse(approval=False, message="Guest login failed due to an error.")

    async def logout(self, token: str, refresh_token: str = None, ip_address: str = None, user_agent: str = None) -> bool:
        """Logout user by blacklisting JWT token and revoking refresh token if provided"""
        try:
            JWT_BLACKLIST.add(token)
            log.info(f"Token blacklisted for logout: {token}")
            if refresh_token and self.refresh_repo:
                await self.refresh_repo.revoke_token(refresh_token)
                log.info("Refresh token revoked during logout")
            await self.audit_repo.log_action(
                user_id=None,
                action="LOGOUT",
                resource_type="user",
                resource_id=None,
                new_value="JWT token blacklisted" + (" & refresh token revoked" if refresh_token else ""),
                ip_address=ip_address,
                user_agent=user_agent
            )
            return True
        except Exception as e:
            log.error(f"Logout error: {e}")
            return False

    async def refresh_access_token(self, refresh_token: str, ip_address: str = None, user_agent: str = None) -> RefreshTokenResponse:
        """Validate refresh token and issue a new access token. Rotates refresh token for improved security."""
        if not self.refresh_repo or not ENABLE_REFRESH_TOKENS:
            return RefreshTokenResponse(approval=False, message="Refresh token feature not enabled", token=None)
        try:
            token_row = await self.refresh_repo.get_token(refresh_token)
            if not token_row:
                return RefreshTokenResponse(approval=False, message="Invalid refresh token", token=None)
            if token_row.get('revoked_at') is not None:
                return RefreshTokenResponse(approval=False, message="Refresh token revoked", token=None)
            expires_at = token_row.get('expires_at')
            if expires_at and expires_at < datetime.utcnow():
                return RefreshTokenResponse(approval=False, message="Refresh token expired", token=None)
            user_mail_id = token_row['user_mail_id']
            user_data = await self.user_repo.get_user_basic_by_email(user_mail_id)
            if not user_data:
                return RefreshTokenResponse(approval=False, message="User no longer exists", token=None)
            
            # Use the role and department that were stored with the refresh token
            # This preserves the exact same claims from the original access token
            original_role = token_row.get('role', 'User')  # fallback to 'User' if not stored
            original_department = token_row.get('department_name')  # can be None for SuperAdmin
            
            # Rotate refresh token: revoke old, store new
            try:
                await self.refresh_repo.revoke_token(refresh_token)
            except Exception as e:
                log.warning(f"Could not revoke old refresh token (continuing): {e}")
            new_refresh_token = secrets.token_urlsafe(64)
            new_refresh_expires = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
            try:
                await self.refresh_repo.store_token(
                    user_mail_id=user_mail_id,
                    refresh_token=new_refresh_token,
                    expires_at=new_refresh_expires,
                    user_agent=user_agent,
                    ip_address=ip_address,
                    role=original_role,
                    department_name=original_department
                )
            except Exception as e:
                log.error(f"Failed to store rotated refresh token: {e}")
                new_refresh_token = None
            # Create new access token with the same claims as the original
            payload = {
                "mail_id": user_data['mail_id'],
                "user_name": user_data['user_name'],
                "role": original_role,
                "department_name": original_department,
                "exp": datetime.utcnow() + timedelta(seconds=ACCESS_TOKEN_EXPIRE_SECONDS)
            }
            new_access_token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
            await self.audit_repo.log_action(
                user_id=user_mail_id,
                action="ACCESS_TOKEN_REFRESHED",
                resource_type="user",
                resource_id=user_mail_id,
                new_value="Issued new access token via refresh",
                ip_address=ip_address,
                user_agent=user_agent
            )
            return RefreshTokenResponse(approval=True, token=new_access_token, refresh_token=new_refresh_token, message="Access token refreshed")
        except Exception as e:
            log.error(f"Refresh token error: {e}")
            return RefreshTokenResponse(approval=False, message="Failed to refresh token", token=None)
    
    async def register(self, register_request: RegisterRequest, ip_address: str = None, user_agent: str = None, current_user: User = None) -> RegisterResponse:
        """Register new user - simplified version that only creates user with email, PWD, and username"""
        try:
            # Check if user already exists in the login_credential table
            existing_user = await self.user_repo.get_user_basic_by_email(register_request.email_id)
            
            if existing_user:
                return RegisterResponse(
                    approval=False, 
                    message=f"User with email {register_request.email_id} already exists" 
                )
            
            # Check if this is the first user registration (no users exist yet)
            is_first_user = not await self.user_repo.has_any_users()
            
            # Hash PWD 
            password_hash = bcrypt.hashpw(register_request.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            # Create new user (without role and department - just basic credentials)
            user_id = await self.user_repo.create_user(
                email=register_request.email_id,
                username=register_request.user_name,
                password=password_hash
            )
            
            if not user_id:
                return RegisterResponse(approval=False, message="Registration failed")
            
            log.info(f"Created new user {register_request.email_id}")
            
            # If this is the first user, automatically assign SuperAdmin role
            if is_first_user and self.user_dept_mapping_repo:
                mapping_success = await self.user_dept_mapping_repo.add_superadmin(
                    mail_id=register_request.email_id,
                    created_by=register_request.email_id  # Self-assigned for first user
                )
                if mapping_success:
                    log.info(f"First user {register_request.email_id} automatically assigned SuperAdmin role")
                    
                    # Log registration
                    await self.audit_repo.log_action(
                        user_id=user_id,
                        action="USER_REGISTERED",
                        resource_type="user",
                        resource_id=register_request.email_id,
                        new_value="Role: SuperAdmin (First User - Auto-assigned)",
                        ip_address=ip_address,
                        user_agent=user_agent
                    )
                    
                    return RegisterResponse(
                        approval=True, 
                        message=f"{register_request.user_name} registered successfully as the first SuperAdmin"
                    )
                else:
                    log.error(f"Failed to assign SuperAdmin role to first user {register_request.email_id}")
                    return RegisterResponse(
                        approval=False, 
                        message="Failed to assign SuperAdmin role"
                    )
            
            # Log regular user registration (without role/department)
            await self.audit_repo.log_action(
                user_id=user_id,
                action="USER_REGISTERED",
                resource_type="user",
                resource_id=register_request.email_id,
                new_value="User registered - awaiting role and department assignment",
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            return RegisterResponse(
                approval=True, 
                message=f"{register_request.user_name} registered successfully. Please contact an administrator to assign role and department."
            )
            
        except Exception as e:
            log.error(f"Registration error: {e}")
            return RegisterResponse(approval=False, message="Registration failed due to an error")
    
    async def register_superadmin(self, register_request: RegisterRequest, ip_address: str = None, user_agent: str = None) -> RegisterResponse:
        """
        Register a SuperAdmin user.
        Only allowed when no SuperAdmin exists in the system.
        """
        try:
            # Check if any SuperAdmin already exists
            if self.user_dept_mapping_repo:
                has_superadmin = await self.user_dept_mapping_repo.has_superadmin_assignment()
                if has_superadmin:
                    return RegisterResponse(
                        approval=False,
                        message="A SuperAdmin already exists in the system. Please contact the existing SuperAdmin."
                    )
            
            # Check if user already exists in the login_credential table
            existing_user = await self.user_repo.get_user_basic_by_email(register_request.email_id)
            
            if existing_user:
                return RegisterResponse(
                    approval=False, 
                    message=f"User with email {register_request.email_id} already exists" 
                )
            
            # Hash PWD
            password_hash = bcrypt.hashpw(register_request.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            # Create new user
            user_id = await self.user_repo.create_user(
                email=register_request.email_id,
                username=register_request.user_name,
                password=password_hash
            )
            
            if not user_id:
                return RegisterResponse(approval=False, message="Registration failed")
            
            log.info(f"Created new SuperAdmin user {register_request.email_id}")
            
            # Assign SuperAdmin role
            if self.user_dept_mapping_repo:
                mapping_success = await self.user_dept_mapping_repo.add_superadmin(
                    mail_id=register_request.email_id,
                    created_by=register_request.email_id
                )
                if mapping_success:
                    log.info(f"User {register_request.email_id} assigned SuperAdmin role")
                    
                    # Log registration
                    await self.audit_repo.log_action(
                        user_id=user_id,
                        action="SUPERADMIN_REGISTERED",
                        resource_type="user",
                        resource_id=register_request.email_id,
                        new_value="Role: SuperAdmin (No SuperAdmin existed)",
                        ip_address=ip_address,
                        user_agent=user_agent
                    )
                    
                    return RegisterResponse(
                        approval=True,
                        message=f"{register_request.user_name} registered successfully as SuperAdmin"
                    )
                else:
                    log.error(f"Failed to assign SuperAdmin role to {register_request.email_id}")
                    return RegisterResponse(
                        approval=False,
                        message="Failed to assign SuperAdmin role"
                    )
            
            return RegisterResponse(
                approval=False,
                message="Configuration error: Unable to assign SuperAdmin role"
            )
            
        except Exception as e:
            log.error(f"SuperAdmin registration error: {e}")
            return RegisterResponse(approval=False, message="SuperAdmin registration failed due to an error")
    
    async def assign_role_department(self, email_id: str, department_name: str, role: str, 
                                    current_user: User, ip_address: str = None, 
                                    user_agent: str = None) -> dict:
        """
        Assign role and department to a registered user.
        Only SuperAdmin or department Admin can assign roles.
        """
        try:
            # Check if user exists
            user_data = await self.user_repo.get_user_basic_by_email(email_id)
            if not user_data:
                return {
                    "success": False,
                    "message": f"User with email {email_id} not found. User must register first."
                }
            
            # Block assigning SuperAdmin to a department
            if self.user_dept_mapping_repo:
                target_role = await self.user_dept_mapping_repo.get_user_role_for_department(
                    mail_id=email_id,
                    department_name=None
                )
                if target_role == "SuperAdmin":
                    return {
                        "success": False,
                        "message": "Cannot assign a SuperAdmin to a department. SuperAdmin has system-wide access and is not tied to any department."
                    }
            
            # Validate department exists
            if self.department_repo:
                department_exists = await self.department_repo.department_exists(department_name)
                if not department_exists:
                    return {
                        "success": False,
                        "message": f"Department '{department_name}' does not exist"
                    }
            
            # Validate role is allowed in the department
            if self.department_repo:
                role_allowed = await self.department_repo.is_role_allowed_in_department(
                    department_name, 
                    role
                )
                if not role_allowed:
                    return {
                        "success": False,
                        "message": f"Role '{role}' is not allowed in department '{department_name}'. Please contact SuperAdmin to add this role to the department."
                    }
            
            # Authorization checks
            if current_user.role == "SuperAdmin":
                # SuperAdmin can assign anyone to any department
                pass
            elif current_user.role == "Admin":
                # Admin can only assign users to their own department
                if self.user_dept_mapping_repo:
                    admin_departments = await self.user_dept_mapping_repo.get_user_departments_simple(current_user.email)
                    if department_name not in admin_departments:
                        return {
                            "success": False,
                            "message": f"Admin can only assign users to their own departments. You are admin of: {', '.join(admin_departments)}"
                        }
            else:
                return {
                    "success": False,
                    "message": "Only SuperAdmin or Admin can assign roles and departments"
                }
            
            # Check if user is already in this department
            if self.user_dept_mapping_repo:
                user_in_dept = await self.user_dept_mapping_repo.check_user_in_department(
                    mail_id=email_id,
                    department_name=department_name
                )
                if user_in_dept:
                    return {
                        "success": False,
                        "message": f"User is already assigned to this department. Please update role if needed."
                    }
                
                # Add user to department with role
                mapping_success = await self.user_dept_mapping_repo.add_user_to_department(
                    mail_id=email_id,
                    department_name=department_name,
                    role=role,
                    created_by=current_user.email
                )
                
                if mapping_success:
                    await self.audit_repo.log_action(
                        user_id=current_user.email,
                        action="USER_ASSIGNED_TO_DEPARTMENT",
                        resource_type="user",
                        resource_id=email_id,
                        new_value=f"Assigned role '{role}' in department '{department_name}'",
                        ip_address=ip_address,
                        user_agent=user_agent
                    )
                    return {
                        "success": True,
                        "message": f"Successfully assigned role '{role}' to user in department '{department_name}'"
                    }
                else:
                    return {
                        "success": False,
                        "message": "Failed to assign user to department. User may already be in this department."
                    }
            else:
                return {
                    "success": False,
                    "message": "User-department mapping service not available"
                }
                
        except Exception as e:
            log.error(f"Error assigning role and department: {e}")
            return {
                "success": False,
                "message": f"Failed to assign role and department: {str(e)}"
            }
    
    async def validate_jwt(self, token: str) -> Optional[User]:
        """Validate JWT and return user info with current role/department from database"""
        try:
            if token in JWT_BLACKLIST:
                log.warning("JWT token is blacklisted (logged out)")
                return None
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            
            # Get user data with the specific department context from JWT
            department_name = payload.get("department_name")
            user_data = await self.user_repo.get_user_basic_by_email(payload["mail_id"])
            
            if not user_data:
                return None
            return User(
                id=user_data['mail_id'],
                email=user_data['mail_id'],
                username=user_data['user_name'],
                role=payload["role"],  # Get from database (current role)
                status=UserStatus.ACTIVE,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                department_name=department_name  # Get from database (current department)
            )
        except Exception as e:
            log.error(f"JWT validation error: {e}")
            return None
    
    async def update_password(self, email: str, new_password: str, current_user_id: str, 
                            ip_address: str = None, user_agent: str = None) -> bool:
        """Update user PWD"""
        try:
            # Hash new PWD
            password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            # Update PWD
            success = await self.user_repo.update_user_password(email, password_hash)
            
            if success:
                # Get user for audit log
                user_data = await self.user_repo.get_user_basic_by_email(email)
                
                # Log PWD change
                await self.audit_repo.log_action(
                    user_id=current_user_id,
                    action="PASSWORD_UPDATED",
                    resource_type="user",
                    resource_id=email,
                    new_value="Password changed",
                    ip_address=ip_address,
                    user_agent=user_agent
                )
            
            return success
            
        except Exception as e:
            log.error(f"Password update error: {e}")
            return False
    
    async def update_role(self, email: str, new_role: str, current_user_id: str, 
                         ip_address: str = None, user_agent: str = None) -> bool:
        """Update user role"""
        try:
            # Get current user data for audit log
            user_data = await self.user_repo.get_user_by_email(email)
            old_role = user_data['role'] if user_data else None
            
            # Update role
            success = await self.user_repo.update_user_role(email, new_role)
            
            if success:
                # Log role change
                await self.audit_repo.log_action(
                    user_id=current_user_id,
                    action="ROLE_UPDATED",
                    resource_type="user",
                    resource_id=email,
                    old_value=old_role,
                    new_value=new_role,
                    ip_address=ip_address,
                    user_agent=user_agent
                )
            
            return success
            
        except Exception as e:
            log.error(f"Role update error: {e}")
            return False

    async def update_department(self, email: str, new_department: str, current_user_id: str, 
                              ip_address: str = None, user_agent: str = None) -> bool:
        """Update user department"""
        try:
            # Get current user data for audit log
            user_data = await self.user_repo.get_user_by_email(email)
            old_department = user_data['department_name'] if user_data else None
            
            # Update department
            success = await self.user_repo.update_user_department(email, new_department)
            
            if success:
                # Log department change
                await self.audit_repo.log_action(
                    user_id=current_user_id,
                    action="DEPARTMENT_UPDATED",
                    resource_type="user",
                    resource_id=email,
                    old_value=old_department,
                    new_value=new_department,
                    ip_address=ip_address,
                    user_agent=user_agent
                )
            
            return success
            
        except Exception as e:
            log.error(f"Department update error: {e}")
            return False
    
    async def get_user_with_department(self, email: str) -> Optional[dict]:
        """
        Get user by email with proper error handling and department information.
        
        Args:
            email: User email to lookup
            
        Returns:
            User dictionary with department info or None if not found
        """
        try:
            user_data = await self.user_repo.get_user_by_email(email)
            if user_data:
                # Ensure department_name is properly set
                if 'department_name' not in user_data or user_data['department_name'] is None:
                    user_data['department_name'] = "General"
            return user_data
        except Exception as e:
            log.error(f"Error getting user {email}: {e}")
            return None
    
    async def validate_users_in_department(self, user_emails: List[str], target_department: str) -> tuple[List[str], List[str], List[str]]:
        """
        Validate that all provided user emails exist and belong to the specified department.
        
        Args:
            user_emails: List of user emails to validate
            target_department: The target department to validate users against
            
        Returns:
            Tuple of (valid_users, invalid_users, wrong_department_users)
        """
        if not user_emails:
            return [], [], []
        
        valid_users = []
        invalid_users = []
        wrong_department_users = []
        
        for email in user_emails:
            try:
                user_data = await self.get_user_with_department(email)
                if not user_data:
                    invalid_users.append(email)
                else:
                    user_department = user_data.get('department_name', 'General')
                    if user_department != target_department:
                        wrong_department_users.append(f"{email} (belongs to '{user_department}')")
                    else:
                        valid_users.append(email)
            except Exception as e:
                log.error(f"Error validating user {email} for department {target_department}: {e}")
                invalid_users.append(email)
        
        return valid_users, invalid_users, wrong_department_users

    async def set_temporary_password(self, email: str, temporary_password: str, current_user_id: str,
                                     ip_address: str = None, user_agent: str = None) -> bool:
        """
        Set a temporary PWD for a user (SuperAdmin only).
        This sets must_change_password = True so user is prompted to change on next login.
        """
        try:
            # Hash the temporary PWD
            password_hash = bcrypt.hashpw(temporary_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            # Set temporary PWD with must_change_password flag
            success = await self.user_repo.set_temporary_password(email, password_hash)
            
            if success:
                # Log the action
                await self.audit_repo.log_action(
                    user_id=current_user_id,
                    action="TEMPORARY_PASSWORD_SET",
                    resource_type="user",
                    resource_id=email,
                    new_value="Temporary password set - user must change on next login",
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                log.info(f"Temporary password set for user {email} by {current_user_id}")
            
            return success
            
        except Exception as e:
            log.error(f"Error setting temporary password for {email}: {e}")
            return False

    async def change_password(self, email: str, current_password: str, new_password: str,
                             ip_address: str = None, user_agent: str = None) -> dict:
        """
        Allow user to change their PWD after admin has reset it.
        Only works when must_change_password flag is True.
        Verifies current PWD before allowing change.
        Clears must_change_password flag after successful change.
        """
        try:
            # Check if must_change_password flag is set
            must_change = await self.user_repo.get_must_change_password_status(email)
            if not must_change:
                return {"success": False, "message": "Password change not required. Contact admin to reset your password if needed."}
            
            # Get user data to verify current PWD
            user_data = await self.user_repo.get_user_basic_by_email(email)
            if not user_data:
                return {"success": False, "message": "User not found"}
            
            # Verify current PWD
            if not bcrypt.checkpw(current_password.encode('utf-8'), user_data['password'].encode('utf-8')):
                return {"success": False, "message": "Current password is incorrect"}
            
            # Hash new PWD
            password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            # Update PWD and clear must_change_password flag
            success = await self.user_repo.update_user_password_and_clear_flag(email, password_hash)
            
            if success:
                # Log the action
                await self.audit_repo.log_action(
                    user_id=email,
                    action="PASSWORD_CHANGED",
                    resource_type="user",
                    resource_id=email,
                    new_value="Password changed by user",
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                log.info(f"Password changed for user {email}")
                return {"success": True, "message": "Password changed successfully"}
            
            return {"success": False, "message": "Failed to update password"}
            
        except Exception as e:
            log.error(f"Error changing password for {email}: {e}")
            return {"success": False, "message": "An error occurred while changing password"}
