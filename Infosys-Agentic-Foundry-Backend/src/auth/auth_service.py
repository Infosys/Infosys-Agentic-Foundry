import bcrypt
import jwt
import secrets
from datetime import datetime, timedelta
from typing import Optional, List
from src.auth.models import (
    User, UserRole, UserStatus, LoginRequest, LoginResponse, RegisterRequest, RegisterResponse, 
    RefreshTokenResponse, OAuthLoginInitResponse, OAuthCallbackResponse, OAuthLogoutResponse
)
from src.auth.repositories import UserRepository, AuditLogRepository, RefreshTokenRepository, DepartmentRepository, UserDepartmentMappingRepository, RegistrationRequestRepository, AuthorizationCodeRepository
from src.utils.send_email_helper import (
    send_email,
    notify_admins_new_registration,
    notify_admins_department_access_request,
    notify_user_request_approved,
    notify_user_request_rejected
)
from telemetry_wrapper import logger as log
from src.config.settings import (
    JWT_SECRET, JWT_ALGORITHM, ACCESS_TOKEN_EXPIRE_SECONDS,
    REFRESH_TOKEN_EXPIRE_DAYS, ENABLE_REFRESH_TOKENS, KEYCLOAK_ENABLED,
    AZURE_AD_ENABLED
)

import base64

# In-memory blacklist for demonstration (use persistent store in production)
JWT_BLACKLIST = set()

# Import Keycloak service conditionally
if KEYCLOAK_ENABLED:
    from src.auth.keycloak_service import KeycloakService

# Import Azure AD service conditionally
if AZURE_AD_ENABLED:
    from src.auth.azure_ad_service import AzureADService, INITIAL_SUPERADMIN_EMAILS
else:
    import os
    INITIAL_SUPERADMIN_EMAILS: list = [
        e.strip().lower()
        for e in os.getenv("INITIAL_SUPERADMIN_EMAILS", "").split(",")
        if e.strip()
    ]

class AuthService:
    """Service for authentication operations - supports both local and Keycloak auth"""

    def __init__(self, user_repo: UserRepository, audit_repo: AuditLogRepository, refresh_repo: RefreshTokenRepository = None, department_repo: DepartmentRepository = None, user_dept_mapping_repo: UserDepartmentMappingRepository = None, registration_request_repo: RegistrationRequestRepository = None, authorization_code_repo: AuthorizationCodeRepository = None):
        self.user_repo = user_repo
        self.audit_repo = audit_repo
        # refresh_repo is optional to keep backward compatibility if not wired yet
        self.refresh_repo = refresh_repo
        self.department_repo = department_repo
        self.user_dept_mapping_repo = user_dept_mapping_repo
        self.registration_request_repo = registration_request_repo
        self.authorization_code_repo = authorization_code_repo

        # Initialize Keycloak service if enabled
        self.keycloak_service = None
        if KEYCLOAK_ENABLED:
            self.keycloak_service = KeycloakService(audit_repo=audit_repo)

        # Initialize Azure AD service if enabled
        self.azure_ad_service = None
        if AZURE_AD_ENABLED:
            self.azure_ad_service = AzureADService()

    async def _log_login_failure(self, mail_id: str, email_id: str, reason: str, ip_address: str = None, user_agent: str = None):
        """Helper method to log login failures to audit trail"""
        await self.audit_repo.log_action(
            user_id=mail_id,
            action="LOGIN_FAILED",
            resource_type="user",
            resource_id=email_id,
            new_value=reason,
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def login(self, login_request: LoginRequest, ip_address: str = None, user_agent: str = None) -> LoginResponse:
        """Authenticate user and create session"""
        try:
            # Extract variables from login request
            user_email = login_request.email_id
            decoded_password = login_request.password
            requested_department = getattr(login_request, 'department_name', None)

            # Get user by email
            user_data = await self.user_repo.get_user_by_email(user_email, requested_department)

            if not user_data:
                await self.audit_repo.log_action(
                    user_id=None,
                    action="LOGIN_FAILED",
                    resource_type="user",
                    resource_id=user_email,
                    new_value="User not found",
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                return LoginResponse(approval=False, message="User not found")
            
            # Check PWD first before any additional processing
            if not bcrypt.checkpw(decoded_password.encode('utf-8'), user_data['password'].encode('utf-8')):
                await self._log_login_failure(user_data['mail_id'], user_email, "Incorrect password", ip_address, user_agent)
                return LoginResponse(approval=False, message="Incorrect password")
            
            # Role is already fetched via JOIN in get_user_by_email
            user_role = user_data.get('role')
            
            # Handle SuperAdmin case - can login without department or to any existing department
            if user_role == "SuperAdmin":
                if requested_department is not None and self.department_repo:
                    department_exists = await self.department_repo.department_exists(requested_department)
                    if not department_exists:
                        await self._log_login_failure(user_data['mail_id'], user_email, f"Department '{requested_department}' does not exist", ip_address, user_agent)
                        return LoginResponse(approval=False, message=f"Department '{requested_department}' does not exist")
                    # SuperAdmin always logs in as SuperAdmin role — they can switch to any
                    # department role after login via /switch-role endpoint
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
            
            # Update last_used_at for the department so it becomes the default on next login
            if requested_department and self.user_dept_mapping_repo:
                try:
                    await self.user_dept_mapping_repo.update_last_used_at(user_data['mail_id'], requested_department)
                except Exception as e:
                    log.warning(f"Failed to update last_used_at for {user_data['mail_id']} in {requested_department}: {e}")

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

            # Get all available roles in the requested department for multi-role support
            available_roles = []
            requires_role_selection = False
            if requested_department:
                try:
                    if user_role == "SuperAdmin" and self.department_repo:
                        # SuperAdmin has implicit access to ALL roles in the department
                        dept_roles_result = await self.department_repo.get_department_roles(requested_department)
                        if dept_roles_result and dept_roles_result.get("success"):
                            available_roles = dept_roles_result.get("roles", [])
                        if "SuperAdmin" not in available_roles:
                            available_roles = ["SuperAdmin"] + available_roles
                    elif self.user_dept_mapping_repo:
                        # Regular users: get explicit role assignments
                        available_roles = await self.user_dept_mapping_repo.get_user_roles_in_department(
                            user_data['mail_id'], requested_department
                        )
                        # Include SuperAdmin in available roles if user has a SuperAdmin assignment
                        is_also_superadmin = await self.user_dept_mapping_repo.has_superadmin_assignment_for_user(
                            user_data['mail_id']
                        )
                        if is_also_superadmin and "SuperAdmin" not in available_roles:
                            available_roles = ["SuperAdmin"] + available_roles
                    requires_role_selection = len(available_roles) > 1
                except Exception as e:
                    log.warning(f"Failed to get available roles: {e}")
                    available_roles = [user_role] if user_role else []

            return LoginResponse(
                approval=True,
                token=token,
                refresh_token=refresh_token,
                role=user_role,
                username=user_data['user_name'],
                email=user_data['mail_id'],
                department_name=requested_department,
                must_change_password=must_change_password,
                available_roles=available_roles if available_roles else None,
                requires_role_selection=requires_role_selection,
                message="Login successful. Please change your password." if must_change_password else "Login successful",
            )
            
        except Exception as e:
            log.error(f"Login error: {e}")
            return LoginResponse(approval=False, message="Login failed due to an error")
    
    def init_oauth_login(self, requested_role: str = None, custom_redirect_uri: str = None, frontend_origin: str = None) -> OAuthLoginInitResponse:
        """Initialize OAuth Authorization Code Flow - delegates to Keycloak"""
        if not self.keycloak_service:
            raise AttributeError("OAuth login requires Keycloak to be enabled (KEYCLOAK_ENABLED=true)")
        return self.keycloak_service.init_oauth_login(requested_role=requested_role, custom_redirect_uri=custom_redirect_uri, frontend_origin=frontend_origin)

    async def handle_oauth_callback(self, code: str, state: str, ip_address: str = None, user_agent: str = None) -> OAuthCallbackResponse:
        """Handle OAuth callback - delegates to Keycloak"""
        if not self.keycloak_service:
            raise AttributeError("OAuth callback requires Keycloak to be enabled (KEYCLOAK_ENABLED=true)")
        return await self.keycloak_service.handle_oauth_callback(code=code, state=state, ip_address=ip_address, user_agent=user_agent)

    async def guest_login(self, ip_address: str = None, user_agent: str = None) -> LoginResponse:
        """Creates or retrieves a guest user and establishes a valid session."""
        # Delegate to Keycloak if enabled (guest login may not be supported)
        if self.keycloak_service:
            return await self.keycloak_service.guest_login(ip_address, user_agent)
        
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

    def get_oauth_logout_url(self, id_token: str = None) -> OAuthLogoutResponse:
        """Get Keycloak logout URL - delegates to KeycloakService"""
        if not self.keycloak_service:
            raise AttributeError("OAuth logout requires Keycloak to be enabled (KEYCLOAK_ENABLED=true)")
        return self.keycloak_service.get_oauth_logout_url(id_token=id_token)

    async def logout(self, token: str, refresh_token: str = None, ip_address: str = None, user_agent: str = None) -> bool:
        """Logout user by blacklisting JWT token and revoking refresh token if provided"""
        # Delegate to Keycloak if enabled
        if self.keycloak_service:
            return await self.keycloak_service.logout(token, refresh_token, ip_address, user_agent)
        
        try:
            JWT_BLACKLIST.add(token)
            # Mask token for security - only log prefix for debugging
            token_prefix = token[:20] + "..." if len(token) > 20 else "***"
            log.info(f"Token blacklisted for logout: {token_prefix}")
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
        # Resolve the token against our local store first. SSO / authorization-code login
        # mints LOCAL refresh tokens (see exchange_authorization_code), so a locally-issued
        # token must be refreshed locally even when Keycloak is enabled. Only tokens that are
        # absent from our store (i.e. genuine Keycloak-issued refresh tokens) get delegated.
        token_row = None
        if self.refresh_repo and ENABLE_REFRESH_TOKENS:
            try:
                token_row = await self.refresh_repo.get_token(refresh_token)
            except Exception as e:
                log.error(f"Refresh token lookup error: {e}")
                return RefreshTokenResponse(approval=False, message="Failed to refresh token", token=None)

        if token_row is None and self.keycloak_service:
            return await self.keycloak_service.refresh_access_token(refresh_token, ip_address, user_agent)
        
        if not self.refresh_repo or not ENABLE_REFRESH_TOKENS:
            return RefreshTokenResponse(approval=False, message="Refresh token feature not enabled", token=None)
        try:
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
            if not user_data.get('is_active', True):
                # Revoke the refresh token so the deactivated user cannot retry
                try:
                    await self.refresh_repo.revoke_token(refresh_token)
                except Exception as e:
                    log.warning(f"Could not revoke refresh token for deactivated user (continuing): {e}")
                log.warning(f"Refresh token rejected: account '{user_mail_id}' is deactivated")
                return RefreshTokenResponse(approval=False, message="Account has been deactivated", token=None)
            
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
    
    async def register(self, register_request: RegisterRequest, ip_address: str = None, user_agent: str = None, current_user=None) -> RegisterResponse:
        """Register new user"""
        try:
            # Check if user already exists
            existing_user = await self.user_repo.get_user_basic_by_email(register_request.email_id)
            decoded_password = register_request.password
            if existing_user:
                # Check if user has at least one department assigned
                has_department = False
                if self.user_dept_mapping_repo:
                    user_depts = await self.user_dept_mapping_repo.get_user_departments_simple(register_request.email_id)
                    has_department = len(user_depts) > 0

                if has_department:
                    return RegisterResponse(
                        approval=False,
                        message="You are already registered. If you want to join another department, please log in and raise a department access request."
                    )
                else:
                    return RegisterResponse(
                        approval=False,
                        message="You are already registered. Your department access requests may still be pending. Please log in to check your request status."
                    )

            # Validate all requested departments exist
            invalid_departments = []
            if self.department_repo:
                for dept in register_request.department_names:
                    dept_exists = await self.department_repo.department_exists(dept)
                    if not dept_exists:
                        invalid_departments.append(dept)
            if invalid_departments:
                return RegisterResponse(
                    approval=False,
                    message=f"Department(s) not found: {', '.join(invalid_departments)}"
                )

            password_hash = bcrypt.hashpw(decoded_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            user_id = await self.user_repo.create_user(
                email=register_request.email_id,
                username=register_request.user_name,
                password=password_hash
            )
            if not user_id:
                return RegisterResponse(approval=False, message="Registration failed")

            log.info(f"User account created for {register_request.email_id}")

            # Create pending department access requests
            created_departments = []
            skipped_departments = []
            for dept in register_request.department_names:
                # Skip if a pending request already exists
                has_pending = await self.registration_request_repo.has_pending_request(
                    email_id=register_request.email_id,
                    department_name=dept
                )
                if has_pending:
                    skipped_departments.append(f"{dept} (request already pending)")
                    continue

                request_id = await self.registration_request_repo.create_request(
                    email_id=register_request.email_id,
                    user_name=register_request.user_name,
                    password_hash=password_hash,
                    department_name=dept
                )
                if request_id:
                    created_departments.append(dept)
                else:
                    skipped_departments.append(f"{dept} (failed to create request)")

            if not created_departments and skipped_departments:
                return RegisterResponse(
                    approval=True,
                    message=f"Account created but no department requests were new. Skipped: {', '.join(skipped_departments)}"
                )

            if not created_departments:
                return RegisterResponse(
                    approval=True,
                    message="Account created but failed to submit department requests. Please log in and raise requests."
                )

            message = f"Registration successful. Department access request submitted for: {', '.join(created_departments)}. Awaiting admin approval."
            if skipped_departments:
                message += f" Skipped: {', '.join(skipped_departments)}"

            # Notify admins about the new registration
            try:
                if self.user_dept_mapping_repo:
                    all_admin_emails = set()
                    for dept in created_departments:
                        dept_admins = await self.user_dept_mapping_repo.get_department_admin_emails(dept)
                        all_admin_emails.update(dept_admins)
                    if all_admin_emails:
                        notify_admins_new_registration(
                            admin_emails=list(all_admin_emails),
                            user_email=register_request.email_id,
                            user_name=register_request.user_name,
                            departments=created_departments
                        )
            except Exception as email_err:
                log.warning(f"Failed to send admin notification email for registration: {email_err}")

            return RegisterResponse(
                approval=True,
                message=message,
                pending_departments=created_departments
            )

        except Exception as e:
            log.error(f"Registration error: {e}")
            return RegisterResponse(approval=False, message="Registration failed due to an error")

    async def request_department_access(self, email_id: str, department_names: list,
                                         ip_address: str = None, user_agent: str = None) -> RegisterResponse:
        """Request access to additional departments. User must already be registered and logged in."""
        try:
            if not self.registration_request_repo:
                return RegisterResponse(approval=False, message="Registration service not available")

            existing_user = await self.user_repo.get_user_basic_by_email(email_id)
            if not existing_user:
                return RegisterResponse(approval=False, message="User account not found.")

            user_name = existing_user.get('user_name', email_id)

            # Validate all requested departments exist
            invalid_departments = []
            if self.department_repo:
                for dept in department_names:
                    dept_exists = await self.department_repo.department_exists(dept)
                    if not dept_exists:
                        invalid_departments.append(dept)
            if invalid_departments:
                return RegisterResponse(
                    approval=False,
                    message=f"Department(s) not found: {', '.join(invalid_departments)}"
                )

            created_departments = []
            skipped_departments = []
            for dept in department_names:
                # Skip if user is already in this department
                if self.user_dept_mapping_repo:
                    already_in_dept = await self.user_dept_mapping_repo.check_user_in_department(
                        mail_id=email_id, department_name=dept
                    )
                    if already_in_dept:
                        skipped_departments.append(f"{dept} (already a member)")
                        continue

                # Skip if a pending request already exists
                has_pending = await self.registration_request_repo.has_pending_request(
                    email_id=email_id, department_name=dept
                )
                if has_pending:
                    skipped_departments.append(f"{dept} (request already pending)")
                    continue

                request_id = await self.registration_request_repo.create_request(
                    email_id=email_id,
                    user_name=user_name,
                    password_hash='',
                    department_name=dept
                )
                if request_id:
                    created_departments.append(dept)
                else:
                    skipped_departments.append(f"{dept} (failed to create request)")

            if not created_departments and skipped_departments:
                return RegisterResponse(
                    approval=False,
                    message=f"No new requests created. Skipped: {', '.join(skipped_departments)}"
                )

            if not created_departments:
                return RegisterResponse(approval=False, message="Department access request failed")

            message = f"Department access request submitted for: {', '.join(created_departments)}. Awaiting admin approval."
            if skipped_departments:
                message += f" Skipped: {', '.join(skipped_departments)}"

            # Notify admins about the department access request
            try:
                if self.user_dept_mapping_repo:
                    all_admin_emails = set()
                    for dept in created_departments:
                        dept_admins = await self.user_dept_mapping_repo.get_department_admin_emails(dept)
                        all_admin_emails.update(dept_admins)
                    if all_admin_emails:
                        notify_admins_department_access_request(
                            admin_emails=list(all_admin_emails),
                            user_email=email_id,
                            user_name=user_name,
                            departments=created_departments
                        )
            except Exception as email_err:
                log.warning(f"Failed to send admin notification email for department access request: {email_err}")

            return RegisterResponse(
                approval=True,
                message=message,
                pending_departments=created_departments
            )

        except Exception as e:
            log.error(f"Department access request error: {e}")
            return RegisterResponse(approval=False, message="Department access request failed due to an error")

    async def get_my_requests(self, email_id: str) -> dict:
        """Get all department access requests for the current user (pending, approved, rejected)."""
        try:
            if not self.registration_request_repo:
                return {"success": False, "message": "Registration service not available"}

            requests = await self.registration_request_repo.get_requests_by_email(email_id)
            return {
                "success": True,
                "requests": requests
            }
        except Exception as e:
            log.error(f"Error fetching requests for {email_id}: {e}")
            return {"success": False, "message": f"Failed to fetch requests: {str(e)}"}

    async def get_my_requests_paginated(
        self,
        email_id: str,
        search_value: str = '',
        page: int = 1,
        limit: int = 20,
        status: str = None
    ) -> dict:
        """Get department access requests for the current user with pagination and search filtering."""
        try:
            if not self.registration_request_repo:
                return {
                    "success": False,
                    "message": "Registration service not available",
                    "details": [],
                    "total_count": 0,
                    "total_pages": 0,
                    "current_page": page,
                    "page_size": limit,
                    "has_next": False,
                    "has_previous": False
                }

            total_count = await self.registration_request_repo.get_total_requests_count_by_email(
                email_id, search_value=search_value, status=status
            )
            records = await self.registration_request_repo.get_requests_by_email_paginated(
                email_id, search_value=search_value, limit=limit, page=page, status=status
            )

            total_pages = (total_count + limit - 1) // limit if limit else 0  # Ceiling division

            return {
                "success": True,
                "message": f"Successfully retrieved {len(records)} requests (page {page} of {total_pages})",
                "details": records,
                "total_count": total_count,
                "total_pages": total_pages,
                "current_page": page,
                "page_size": limit,
                "has_next": page < total_pages,
                "has_previous": page > 1
            }
        except Exception as e:
            log.error(f"Error fetching paginated requests for {email_id}: {e}")
            return {
                "success": False,
                "message": f"Failed to fetch requests: {str(e)}",
                "details": [],
                "total_count": 0,
                "total_pages": 0,
                "current_page": page,
                "page_size": limit,
                "has_next": False,
                "has_previous": False
            }

    async def register_superadmin(self, register_request, ip_address: str = None, user_agent: str = None) -> RegisterResponse:
        """
        Register a SuperAdmin user.
        Only allowed when no SuperAdmin exists in the system.
        """
        decoded_password = register_request.password
        try:
            # Check if any SuperAdmin already exists
            # Emails in the seed list are exempt — they may register a local-auth account even
            # when a SuperAdmin already exists.
            if self.user_dept_mapping_repo:
                has_superadmin = await self.user_dept_mapping_repo.has_superadmin_assignment()
                is_seeded = register_request.email_id.lower() in INITIAL_SUPERADMIN_EMAILS
                if has_superadmin and not is_seeded:
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
            password_hash = bcrypt.hashpw(decoded_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
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
            
            # Block assigning roles to a SuperAdmin — they implicitly have all roles
            if self.user_dept_mapping_repo:
                target_is_superadmin = await self.user_dept_mapping_repo.has_superadmin_assignment_for_user(email_id)
                if target_is_superadmin:
                    return {
                        "success": False,
                        "message": "Cannot assign roles to a SuperAdmin. SuperAdmin implicitly has access to all roles in every department via role switching."
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
                # SuperAdmin cannot assign roles to themselves
                if email_id.lower() == current_user.email.lower():
                    return {
                        "success": False,
                        "message": "SuperAdmin cannot assign roles to themselves. SuperAdmin implicitly has all roles in every department."
                    }
                # SuperAdmin cannot assign roles to another SuperAdmin (they auto-have all roles)
                if self.user_dept_mapping_repo:
                    target_is_superadmin = await self.user_dept_mapping_repo.has_superadmin_assignment_for_user(email_id)
                    if target_is_superadmin:
                        return {
                            "success": False,
                            "message": "Cannot assign roles to a SuperAdmin. SuperAdmin implicitly has access to all roles in every department."
                        }
            elif current_user.role == "Admin":
                # Admin cannot assign roles to themselves
                if email_id.lower() == current_user.email.lower():
                    return {
                        "success": False,
                        "message": "Admin cannot assign roles to themselves. Please contact a SuperAdmin."
                    }
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
            
            # Check if user already has this specific role in this department
            if self.user_dept_mapping_repo:
                has_exact_role = await self.user_dept_mapping_repo.check_user_has_role_in_department(
                    mail_id=email_id,
                    department_name=department_name,
                    role=role
                )
                if has_exact_role:
                    return {
                        "success": False,
                        "message": f"User already has role '{role}' in department '{department_name}'."
                    }
                
                # Add user to department with role (allows multiple roles per department)
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

    async def remove_role_from_user_in_department(self, email_id: str, department_name: str, role: str,
                                                  current_user: User, ip_address: str = None,
                                                  user_agent: str = None) -> dict:
        """
        Remove a specific role from a user in a department.
        Only SuperAdmin or department Admin can remove roles.
        """
        try:
            # Check if user exists
            user_data = await self.user_repo.get_user_basic_by_email(email_id)
            if not user_data:
                return {
                    "success": False,
                    "message": f"User with email {email_id} not found."
                }

            # Cannot remove SuperAdmin role via this endpoint
            if role == "SuperAdmin":
                return {
                    "success": False,
                    "message": "Cannot remove SuperAdmin role via this endpoint."
                }

            # Authorization checks
            if current_user.role == "SuperAdmin":
                pass
            elif current_user.role == "Admin":
                # Admin cannot modify their own roles
                if email_id.lower() == current_user.email.lower():
                    return {
                        "success": False,
                        "message": "Admin cannot modify their own roles. Please contact a SuperAdmin."
                    }
                # Admin can only remove roles in their own departments
                if self.user_dept_mapping_repo:
                    admin_departments = await self.user_dept_mapping_repo.get_user_departments_simple(current_user.email)
                    if department_name not in admin_departments:
                        return {
                            "success": False,
                            "message": f"Admin can only manage users in their own departments. You are admin of: {', '.join(admin_departments)}"
                        }
            else:
                return {
                    "success": False,
                    "message": "Only SuperAdmin or Admin can remove roles"
                }

            # Verify the user actually has this role in this department
            if self.user_dept_mapping_repo:
                has_role = await self.user_dept_mapping_repo.check_user_has_role_in_department(
                    mail_id=email_id,
                    department_name=department_name,
                    role=role
                )
                if not has_role:
                    return {
                        "success": False,
                        "message": f"User does not have role '{role}' in department '{department_name}'."
                    }

                # Prevent removing the last role in a department
                user_depts = await self.user_dept_mapping_repo.get_user_departments(email_id)
                dept_data = next(
                    (d for d in user_depts if d.get("department_name") == department_name),
                    None
                )
                if dept_data and len(dept_data.get("roles", [])) <= 1:
                    return {
                        "success": False,
                        "message": f"Cannot remove the only role for user in department '{department_name}'. Assign another role first or remove the user from the department entirely."
                    }

                # Remove the role
                removed = await self.user_dept_mapping_repo.remove_user_from_department(
                    mail_id=email_id,
                    department_name=department_name,
                    role=role
                )

                if removed:
                    await self.audit_repo.log_action(
                        user_id=current_user.email,
                        action="USER_ROLE_REMOVED_FROM_DEPARTMENT",
                        resource_type="user",
                        resource_id=email_id,
                        new_value=f"Removed role '{role}' from department '{department_name}'",
                        ip_address=ip_address,
                        user_agent=user_agent
                    )
                    return {
                        "success": True,
                        "message": f"Successfully removed role '{role}' from user in department '{department_name}'"
                    }
                else:
                    return {
                        "success": False,
                        "message": "Failed to remove role from user in department."
                    }
            else:
                return {
                    "success": False,
                    "message": "User-department mapping service not available"
                }

        except Exception as e:
            log.error(f"Error removing role from user in department: {e}")
            return {
                "success": False,
                "message": f"Failed to remove role: {str(e)}"
            }

    async def approve_registration(self, request_id: int, role: str, current_user: User,
                                    department_name_override: str = None,
                                    ip_address: str = None, user_agent: str = None) -> dict:
        """Approve a pending registration request. Admin approves for their department, SuperAdmin for any.

        Args:
            department_name_override: Optional department name to override the one in the registration request.
                                     If provided, user will be added to this department instead.
        """
        try:
            if not self.registration_request_repo:
                return {"success": False, "message": "Registration service not available"}

            # Fetch the request
            request = await self.registration_request_repo.get_request_by_id(request_id)
            if not request:
                return {"success": False, "message": f"Registration request #{request_id} not found"}

            if request['status'] != 'pending':
                return {"success": False, "message": f"Request is already {request['status']}"}

            # Use override department if provided, otherwise use the original from request
            dept_name = department_name_override if department_name_override else request['department_name']

            # Authorization: Admin can only approve for their department
            if current_user.role == "Admin":
                if self.user_dept_mapping_repo:
                    admin_depts = await self.user_dept_mapping_repo.get_user_departments_simple(current_user.email)
                    if dept_name not in admin_depts:
                        return {
                            "success": False,
                            "message": f"You can only approve requests for your departments: {', '.join(admin_depts)}"
                        }
            elif current_user.role != "SuperAdmin":
                return {"success": False, "message": "Only Admin or SuperAdmin can approve registrations"}

            # Admin cannot assign Admin role — only SuperAdmin can
            if current_user.role == "Admin" and role == "Admin":
                return {
                    "success": False,
                    "message": "Only SuperAdmin can assign the Admin role. Please choose a different role."
                }

            # Validate role is allowed in the department
            if self.department_repo:
                role_allowed = await self.department_repo.is_role_allowed_in_department(dept_name, role)
                if not role_allowed:
                    return {
                        "success": False,
                        "message": f"Role '{role}' is not allowed in department '{dept_name}'"
                    }

            email_id = request['email_id']
            user_name = request['user_name']
            password_hash = request['password']

            # Create user in login_credential if they don't exist yet
            existing_user = await self.user_repo.get_user_basic_by_email(email_id)
            if not existing_user:
                user_id = await self.user_repo.create_user(
                    email=email_id,
                    username=user_name,
                    password=password_hash
                )
                if not user_id:
                    return {"success": False, "message": "Failed to create user account"}
                log.info(f"Created user account for {email_id} during registration approval")

            # Add user to the department with assigned role
            if self.user_dept_mapping_repo:
                # Check if already in this department
                already_in_dept = await self.user_dept_mapping_repo.check_user_in_department(
                    mail_id=email_id, department_name=dept_name
                )
                if already_in_dept:
                    # Still mark the request as approved
                    await self.registration_request_repo.approve_request(
                        request_id=request_id,
                        role=role,
                        reviewed_by=current_user.email
                    )
                    return {
                        "success": True,
                        "message": f"User is already in department '{dept_name}'. Request marked as approved."
                    }

                mapping_success = await self.user_dept_mapping_repo.add_user_to_department(
                    mail_id=email_id,
                    department_name=dept_name,
                    role=role,
                    created_by=current_user.email
                )
                if not mapping_success:
                    return {"success": False, "message": "Failed to add user to department"}

            # Update request status
            await self.registration_request_repo.approve_request(
                request_id=request_id,
                role=role,
                reviewed_by=current_user.email
            )

            # Audit log
            await self.audit_repo.log_action(
                user_id=current_user.email,
                action="REGISTRATION_APPROVED",
                resource_type="registration_request",
                resource_id=str(request_id),
                new_value=f"Approved {email_id} as '{role}' in '{dept_name}'",
                ip_address=ip_address,
                user_agent=user_agent
            )

            log.info(f"Registration request #{request_id} approved: {email_id} as {role} in {dept_name}")

            # Notify the user about the approval
            try:
                notify_user_request_approved(
                    user_email=email_id,
                    department_name=dept_name,
                    assigned_role=role,
                    approved_by=current_user.email
                )
            except Exception as email_err:
                log.warning(f"Failed to send approval notification email to {email_id}: {email_err}")

            return {
                "success": True,
                "message": f"Registration approved. User '{email_id}' assigned role '{role}' in department '{dept_name}'"
            }

        except Exception as e:
            log.error(f"Error approving registration: {e}")
            return {"success": False, "message": f"Failed to approve registration: {str(e)}"}

    async def reject_registration(self, request_id: int, current_user: User,
                                   rejection_reason: str = None,
                                   ip_address: str = None, user_agent: str = None) -> dict:
        """Reject a pending registration request."""
        try:
            if not self.registration_request_repo:
                return {"success": False, "message": "Registration service not available"}

            request = await self.registration_request_repo.get_request_by_id(request_id)
            if not request:
                return {"success": False, "message": f"Registration request #{request_id} not found"}

            if request['status'] != 'pending':
                return {"success": False, "message": f"Request is already {request['status']}"}

            dept_name = request['department_name']

            # Authorization check
            if current_user.role == "Admin":
                if self.user_dept_mapping_repo:
                    admin_depts = await self.user_dept_mapping_repo.get_user_departments_simple(current_user.email)
                    if dept_name not in admin_depts:
                        return {
                            "success": False,
                            "message": f"You can only reject requests for your departments: {', '.join(admin_depts)}"
                        }
            elif current_user.role != "SuperAdmin":
                return {"success": False, "message": "Only Admin or SuperAdmin can reject registrations"}

            await self.registration_request_repo.reject_request(
                request_id=request_id,
                reviewed_by=current_user.email,
                rejection_reason=rejection_reason
            )

            # Audit log
            await self.audit_repo.log_action(
                user_id=current_user.email,
                action="REGISTRATION_REJECTED",
                resource_type="registration_request",
                resource_id=str(request_id),
                new_value=f"Rejected {request['email_id']} for '{dept_name}'" + (f" - Reason: {rejection_reason}" if rejection_reason else ""),
                ip_address=ip_address,
                user_agent=user_agent
            )

            log.info(f"Registration request #{request_id} rejected for {request['email_id']} in {dept_name}")

            # Notify the user about the rejection
            try:
                notify_user_request_rejected(
                    user_email=request['email_id'],
                    department_name=dept_name,
                    rejected_by=current_user.email,
                    rejection_reason=rejection_reason
                )
            except Exception as email_err:
                log.warning(f"Failed to send rejection notification email to {request['email_id']}: {email_err}")

            return {
                "success": True,
                "message": f"Registration request rejected for user '{request['email_id']}' in department '{dept_name}'"
            }

        except Exception as e:
            log.error(f"Error rejecting registration: {e}")
            return {"success": False, "message": f"Failed to reject registration: {str(e)}"}

    async def bulk_approve_registration(self, request_ids: list, role: str, current_user: 'User',
                                         department_name_override: str = None,
                                         ip_address: str = None, user_agent: str = None) -> dict:
        """Approve multiple pending registration requests with the same role assignment and optional department override.

        Args:
            department_name_override: Optional department name to override for all users in the batch.
                                     If provided, all users will be added to this department instead of their requested one.
        """
        if not request_ids:
            return {"success": False, "message": "No request IDs provided"}

        approved = []
        failed = []

        for request_id in request_ids:
            result = await self.approve_registration(
                request_id=request_id,
                role=role,
                current_user=current_user,
                department_name_override=department_name_override,
                ip_address=ip_address,
                user_agent=user_agent
            )
            if result.get("success"):
                approved.append({"request_id": request_id, "message": result["message"]})
            else:
                failed.append({"request_id": request_id, "message": result["message"]})

        total = len(request_ids)
        all_failed = len(approved) == 0

        message = f"{len(approved)}/{total} registration(s) approved with role '{role}'"
        if department_name_override:
            message += f" in department '{department_name_override}'"
        if failed:
            message += f", {len(failed)} failed"

        return {
            "success": not all_failed,
            "message": message,
            "approved": approved,
            "failed": failed
        }

    async def bulk_reject_registration(self, request_ids: list, current_user: 'User',
                                        rejection_reason: str = None,
                                        ip_address: str = None, user_agent: str = None) -> dict:
        """Reject multiple pending registration requests with the same rejection reason."""
        if not request_ids:
            return {"success": False, "message": "No request IDs provided"}

        rejected = []
        failed = []

        for request_id in request_ids:
            result = await self.reject_registration(
                request_id=request_id,
                current_user=current_user,
                rejection_reason=rejection_reason,
                ip_address=ip_address,
                user_agent=user_agent
            )
            if result.get("success"):
                rejected.append({"request_id": request_id, "message": result["message"]})
            else:
                failed.append({"request_id": request_id, "message": result["message"]})

        total = len(request_ids)
        all_failed = len(rejected) == 0

        return {
            "success": not all_failed,
            "message": f"{len(rejected)}/{total} registration(s) rejected"
                       + (f", {len(failed)} failed" if failed else ""),
            "rejected": rejected,
            "failed": failed
        }

    async def get_pending_registrations(self, current_user: User) -> dict:
        """Get pending registration requests. Admin sees their departments, SuperAdmin sees all."""
        try:
            if not self.registration_request_repo:
                return {"success": False, "message": "Registration service not available", "requests": []}

            if current_user.role == "SuperAdmin":
                requests = await self.registration_request_repo.get_all_pending()
            elif current_user.role == "Admin":
                # Show only requests for the admin's currently logged-in department
                requests = await self.registration_request_repo.get_pending_by_department(current_user.department_name)
            else:
                return {"success": False, "message": "Only Admin or SuperAdmin can view registration requests", "requests": []}

            # Convert records to dicts (exclude PWD)
            result = []
            for req in requests:
                result.append({
                    "id": req['id'],
                    "email_id": req['email_id'],
                    "user_name": req['user_name'],
                    "department_name": req['department_name'],
                    "status": req['status'],
                    "created_at": str(req['created_at']) if req.get('created_at') else None,
                    "is_sso": req.get('is_sso', False)
                })

            return {"success": True, "requests": result}

        except Exception as e:
            log.error(f"Error fetching pending registrations: {e}")
            return {"success": False, "message": f"Failed to fetch registrations: {str(e)}", "requests": []}

    async def validate_jwt(self, token: str) -> Optional[User]:
        """Validate JWT and return user info"""
        try:
            if token in JWT_BLACKLIST:
                log.warning("JWT token is blacklisted (logged out)")
                return None

            # --- Primary path: internal HS256 JWT ---
            try:
                payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
                if not payload:
                    return None

                # Get user data with the specific department context from JWT
                department_name = payload.get("department_name")
                user_data = await self.user_repo.get_user_basic_by_email(payload["mail_id"])

                if not user_data:
                    return None
                if not user_data.get('is_active', True):
                    log.warning(f"JWT rejected: account '{payload['mail_id']}' is deactivated (global)")
                    return None
                # Check department-level disable — admin "disable user" writes here, not to login_credential
                if department_name and self.user_dept_mapping_repo:
                    dept_active = await self.user_dept_mapping_repo.is_user_active_in_department(
                        payload['mail_id'], department_name
                    )
                    if dept_active is False:
                        log.warning(
                            f"JWT rejected: account '{payload['mail_id']}' is disabled "
                            f"in department '{department_name}'"
                        )
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
            except jwt.exceptions.PyJWTError:
                pass  # Fall through to trusted Azure AD app-id check

            # --- Keycloak SSO path: RS256 token from another app on the same Keycloak realm ---
            if self.keycloak_service:
                claims = await self.keycloak_service.validate_keycloak_token(token)
                if claims:
                    email = (
                        claims.get("email")
                        or claims.get("preferred_username")
                        or claims.get("upn")
                    )
                    if email:
                        name = claims.get("name", email)
                        # Map Keycloak realm roles to internal role (default: User)
                        keycloak_roles = (
                            claims.get("realm_access", {}).get("roles", [])
                            + claims.get("resource_access", {}).get(
                                self.keycloak_service.client_id, {}
                            ).get("roles", [])
                        )
                        role = UserRole.ADMIN if "admin" in keycloak_roles else UserRole.USER
                        log.info(f"Keycloak SSO token accepted for {email} with role {role}")
                        return User(
                            id=email,
                            email=email,
                            username=name,
                            role=role,
                            status=UserStatus.ACTIVE,
                            created_at=datetime.utcnow(),
                            updated_at=datetime.utcnow(),
                            department_name=claims.get("department", "General"),
                        )

            # --- Azure AD path: RS256 signature verified via Microsoft JWKS ---
            if self.azure_ad_service:
                claims = await self.azure_ad_service.validate_token(token)
                if claims:
                    email = (
                        claims.get("upn")
                        or claims.get("unique_name")
                        or claims.get("email")
                        or claims.get("preferred_username")
                    )
                    if not email:
                        log.warning("Azure AD token is missing email/upn claim")
                        return None
                    name = claims.get("name", email)

                    # Look up user in IAF database by email
                    db_user = await self.user_repo.get_user_basic_by_email(email)
                    if db_user and self.user_dept_mapping_repo:
                        # SuperAdmin is stored with department_name = NULL, which
                        # get_user_departments() filters out — check via dedicated helper first.
                        is_superadmin = await self.user_dept_mapping_repo.has_superadmin_assignment_for_user(email)
                        if is_superadmin:
                            role = "SuperAdmin"
                            department_name = None
                            log.info(f"Azure AD token: user {email} is SuperAdmin")
                        else:
                            # User exists — fetch their department assignments
                            departments = await self.user_dept_mapping_repo.get_user_departments(email)
                            if departments:
                                # Take the first department (ordered by last_used_at DESC)
                                first_dept = departments[0]
                                role = first_dept.get("role", UserRole.USER)
                                department_name = first_dept.get("department_name", "General")
                                log.info(
                                    f"Azure AD token: user {email} found in DB with {len(departments)} dept(s) "
                                    f"— using first: dept={department_name}, role={role}"
                                )
                            else:
                                # User exists but has no department assignment —
                                # allow through with default role and department (no DB write).
                                # Marked PENDING_APPROVAL so middleware restricts to chat inference only.
                                # Role is "Developer" — the inference endpoint will resolve the
                                # agent's department and use it as the user's department.
                                log.info(
                                    f"Azure AD token: user {email} is in DB but has no dept assignment — "
                                    f"allowing with role 'Developer' (chat only, dept resolved from agent)"
                                )
                                role = "Developer"
                                department_name = None
                                return User(
                                    id=email,
                                    email=email,
                                    username=name,
                                    role=role,
                                    status=UserStatus.PENDING_APPROVAL,
                                    created_at=datetime.utcnow(),
                                    updated_at=datetime.utcnow(),
                                    department_name=department_name,
                                )
                    else:
                        # User not in IAF DB — allow through with Developer role
                        # and no department (no DB write).
                        # Marked PENDING_APPROVAL so middleware restricts to chat inference only.
                        # The inference endpoint will resolve the agent's department
                        # and use it as the user's department context.
                        log.info(
                            f"Azure AD token: user {email} not found in DB — "
                            f"allowing with role 'Developer' (chat only, dept resolved from agent)"
                        )
                        role = "Developer"
                        department_name = None
                        return User(
                            id=email,
                            email=email,
                            username=name,
                            role=role,
                            status=UserStatus.PENDING_APPROVAL,
                            created_at=datetime.utcnow(),
                            updated_at=datetime.utcnow(),
                            department_name=department_name,
                        )

                    return User(
                        id=email,
                        email=email,
                        username=name,
                        role=role,
                        status=UserStatus.ACTIVE,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                        department_name=department_name,
                    )

            return None
        except Exception as e:
            log.error(f"JWT validation error: {e}")
            return None
    
    async def update_password(self, email: str, new_password: str, current_user_id: str, 
                            ip_address: str = None, user_agent: str = None) -> bool:
        """Update user PWD"""
        # Delegate to Keycloak if enabled
        if self.keycloak_service:
            return await self.keycloak_service.update_password(email, new_password, current_user_id, ip_address, user_agent)
        
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
        # Delegate to Keycloak if enabled
        if self.keycloak_service:
            return await self.keycloak_service.update_role(email, new_role, current_user_id, ip_address, user_agent)
        
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
        decoded_password = temporary_password
        try:
            # Hash the temporary PWD
            password_hash = bcrypt.hashpw(decoded_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
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
        current_decoded_password = current_password
        new_decoded_password = new_password
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
            if not bcrypt.checkpw(current_decoded_password.encode('utf-8'), user_data['password'].encode('utf-8')):
                return {"success": False, "message": "Current password is incorrect"}
            
            # Hash new PWD
            password_hash = bcrypt.hashpw(new_decoded_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
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

    # ==================== Department Switching Methods ====================

    async def get_user_departments_with_default(self, email: str) -> dict:
        """
        Get all departments for a user, marking the most recently used one as default.
        Each department includes all available roles and the current active role.
        For SuperAdmin: shows all system departments with ALL roles defined in each department
        (SuperAdmin implicitly has access to every role without explicit assignment).
        """
        if not self.user_dept_mapping_repo:
            return {"approval": False, "departments": [], "message": "Department repository not initialized"}

        try:
            is_superadmin = await self.user_dept_mapping_repo.has_superadmin_assignment_for_user(email)

            if is_superadmin and self.department_repo:
                # SuperAdmin implicitly has ALL roles in ALL departments
                all_depts = await self.department_repo.get_all_departments()
                if not all_depts:
                    return {"approval": True, "departments": [], "message": "No departments available in the system"}

                departments = []
                for d in all_depts:
                    dept_name = d["department_name"]
                    # Get all roles defined in this department
                    dept_roles_result = await self.department_repo.get_department_roles(dept_name)
                    dept_roles = dept_roles_result.get("roles", []) if dept_roles_result and dept_roles_result.get("success") else []
                    # Always include SuperAdmin as an available role
                    if "SuperAdmin" not in dept_roles:
                        dept_roles = ["SuperAdmin"] + dept_roles

                    departments.append({
                        "department_name": dept_name,
                        "role": "SuperAdmin",  # Default active role
                        "roles": dept_roles,
                        "is_active": True,
                        "created_at": None,
                        "last_used_at": None,
                    })
            else:
                # Regular users: get their explicit department assignments
                departments = await self.user_dept_mapping_repo.get_user_departments(email)
                if not departments:
                    return {"approval": False, "departments": [], "message": "No departments found for user"}

            # The first one in the list is the most recently used (default)
            for i, dept in enumerate(departments):
                dept['is_default'] = (i == 0)

            return {
                "approval": True,
                "departments": departments,
                "message": "Departments retrieved successfully"
            }
        except Exception as e:
            log.error(f"Error getting departments for user {email}: {e}")
            return {"approval": False, "departments": [], "message": "Error retrieving departments"}

    async def switch_department(self, email: str, department_name: str,
                               ip_address: str = None, user_agent: str = None) -> dict:
        """
        Switch user to a different department.
        Updates last_used_at so the next request resolves the correct department.
        In AZURE_AD_ENABLED mode no backend JWT is minted — the UI keeps using
        the MSAL token and reads role/department_name from this response.
        """
        try:
            # Verify user has access to the department
            user_dept_data = await self.user_dept_mapping_repo.get_user_departments(email)
            user_departments = [d.get('department_name') for d in user_dept_data] if user_dept_data else []

            # SuperAdmin with no explicit department assignments can switch to any existing department
            is_superadmin = False
            if department_name not in user_departments:
                is_superadmin = await self.user_dept_mapping_repo.has_superadmin_assignment_for_user(email)
                if not is_superadmin:
                    return {
                        "approval": False,
                        "message": f"You do not have access to department '{department_name}'"
                    }
                # Validate department actually exists for SuperAdmin
                if self.department_repo:
                    dept_exists = await self.department_repo.department_exists(department_name)
                    if not dept_exists:
                        return {
                            "approval": False,
                            "message": f"Department '{department_name}' does not exist"
                        }

            # Get role for the department
            # For SuperAdmin: first check if they have explicit roles in this department
            dept_role = await self.user_dept_mapping_repo.get_user_role_for_department(email, department_name)
            if not dept_role and is_superadmin:
                # No explicit role in this department, fall back to SuperAdmin
                dept_role = "SuperAdmin"

            if not dept_role:
                return {
                    "approval": False,
                    "message": f"No role found for department '{department_name}'"
                }

            # Check if user is active in this department (skip for SuperAdmin without explicit assignment)
            if not is_superadmin:
                dept_status = await self.user_dept_mapping_repo.get_user_department_status(email, department_name)
                if not dept_status or dept_status.get('is_active') is False:
                    return {
                        "approval": False,
                        "message": f"Your access to department '{department_name}' is disabled"
                    }
            elif department_name in user_departments:
                # SuperAdmin with explicit assignment — check if active
                dept_status = await self.user_dept_mapping_repo.get_user_department_status(email, department_name)
                if dept_status and dept_status.get('is_active') is False:
                    # SuperAdmin can still switch but warn in logs
                    log.warning(f"SuperAdmin {email} switching to department {department_name} where their explicit assignment is disabled")

            # Update last_used_at to make this the default department
            await self.user_dept_mapping_repo.update_last_used_at(email, department_name)

            # Log the department switch
            await self.audit_repo.log_action(
                user_id=email,
                action="DEPARTMENT_SWITCHED",
                resource_type="user",
                resource_id=email,
                new_value=f"Switched to department: {department_name} with role: {dept_role}",
                ip_address=ip_address,
                user_agent=user_agent
            )

            log.info(f"User {email} switched to department {department_name} with role {dept_role}")

            # Always mint a new backend JWT so the caller has an updated token with the
            # new department context — regardless of AZURE_AD_ENABLED.  Local-auth users
            # need this to avoid using a stale JWT after reload; MSAL/Azure AD users can
            # also use the returned token as a session token for subsequent requests.
            user_data = await self.user_repo.get_user_basic_by_email(email)
            if not user_data:
                return {"approval": False, "message": "User not found"}

            username = user_data.get('user_name', email)
            payload = {
                "mail_id": email,
                "user_name": username,
                "role": dept_role,
                "department_name": department_name,
                "exp": datetime.utcnow() + timedelta(seconds=ACCESS_TOKEN_EXPIRE_SECONDS)
            }
            token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

            refresh_token = None
            if ENABLE_REFRESH_TOKENS and self.refresh_repo:
                refresh_token_str = secrets.token_urlsafe(32)
                expires_at = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
                await self.refresh_repo.store_token(
                    user_mail_id=email,
                    refresh_token=refresh_token_str,
                    expires_at=expires_at,
                    user_agent=user_agent,
                    ip_address=ip_address,
                    role=dept_role,
                    department_name=department_name
                )
                refresh_token = refresh_token_str

            # Get all available roles in the new department
            available_roles = []
            if is_superadmin:
                # SuperAdmin has access to all roles defined in the department
                if self.department_repo:
                    dept_roles_result = await self.department_repo.get_department_roles(department_name)
                    if dept_roles_result and dept_roles_result.get("success"):
                        available_roles = dept_roles_result.get("roles", [])
                if "SuperAdmin" not in available_roles:
                    available_roles = ["SuperAdmin"] + available_roles
            else:
                try:
                    available_roles = await self.user_dept_mapping_repo.get_user_roles_in_department(email, department_name)
                except Exception as e:
                    log.warning(f"Failed to get available roles for switch_department: {e}")
                    available_roles = [dept_role]

            return {
                "approval": True,
                "token": token,
                "refresh_token": refresh_token,
                "role": dept_role,
                "department_name": department_name,
                "available_roles": available_roles,
                "message": f"Switched to department '{department_name}'"
            }

        except Exception as e:
            log.error(f"Error switching department for {email}: {e}")
            return {"approval": False, "message": "Error switching department"}

    async def switch_role(self, email: str, role: str, department_name: str = None,
                          ip_address: str = None, user_agent: str = None) -> dict:
        """
        Switch user to a different role within a department.
        For SuperAdmin: can switch to any role defined in the department (no explicit assignment needed).
        For regular users: updates is_current flag and mints a new JWT with the new role.
        """
        try:
            # Use provided department or fall back (caller should provide from JWT context)
            if not department_name:
                return {"approval": False, "message": "Department name is required for role switching"}

            # Check if user is a SuperAdmin
            is_superadmin = await self.user_dept_mapping_repo.has_superadmin_assignment_for_user(email)

            if is_superadmin:
                # SuperAdmin can switch to ANY role defined in the department
                available_roles = []
                if self.department_repo:
                    dept_roles_result = await self.department_repo.get_department_roles(department_name)
                    if dept_roles_result and dept_roles_result.get("success"):
                        available_roles = dept_roles_result.get("roles", [])
                # Always include SuperAdmin as an available role
                if "SuperAdmin" not in available_roles:
                    available_roles = ["SuperAdmin"] + available_roles

                if role not in available_roles:
                    return {
                        "approval": False,
                        "message": f"Role '{role}' is not defined in department '{department_name}'. Available roles: {', '.join(available_roles)}"
                    }

                # Get current role before switching (for audit trail)
                previous_role_from_db = await self.user_dept_mapping_repo.get_user_role_in_department(email, department_name)
                previous_role = previous_role_from_db if previous_role_from_db else "SuperAdmin"

                # Update is_current flag if user has explicit assignments in this department
                await self.user_dept_mapping_repo.switch_role_in_department(email, department_name, role)
            else:
                # Regular user: verify they have the target role via explicit assignment
                available_roles = await self.user_dept_mapping_repo.get_user_roles_in_department(email, department_name)
                if not available_roles:
                    return {
                        "approval": False,
                        "message": f"You do not have any roles in department '{department_name}'"
                    }

                if role not in available_roles:
                    return {
                        "approval": False,
                        "message": f"You do not have role '{role}' in department '{department_name}'. Your available roles: {', '.join(available_roles)}"
                    }

                # Get current role before switching (for audit trail)
                previous_role = await self.user_dept_mapping_repo.get_user_role_in_department(email, department_name)

                # Switch the active role in the database
                success = await self.user_dept_mapping_repo.switch_role_in_department(email, department_name, role)
                if not success:
                    return {
                        "approval": False,
                        "message": f"Failed to switch to role '{role}' in department '{department_name}'"
                    }

            # Update last_used_at for the department
            await self.user_dept_mapping_repo.update_last_used_at(email, department_name)

            # Log the role switch with old and new role details
            await self.audit_repo.log_action(
                user_id=email,
                action="ROLE_SWITCHED",
                resource_type="user",
                resource_id=email,
                old_value=f"Previous role: {previous_role} in department: {department_name}",
                new_value=f"Switched to role: {role} in department: {department_name}",
                ip_address=ip_address,
                user_agent=user_agent
            )

            log.info(f"User {email} switched role from {previous_role} to {role} in department {department_name}")

            # Mint a new JWT with the updated role
            user_data = await self.user_repo.get_user_basic_by_email(email)
            if not user_data:
                return {"approval": False, "message": "User not found"}

            username = user_data.get('user_name', email)
            payload = {
                "mail_id": email,
                "user_name": username,
                "role": role,
                "department_name": department_name,
                "exp": datetime.utcnow() + timedelta(seconds=ACCESS_TOKEN_EXPIRE_SECONDS)
            }
            token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

            refresh_token = None
            if ENABLE_REFRESH_TOKENS and self.refresh_repo:
                refresh_token_str = secrets.token_urlsafe(32)
                expires_at = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
                await self.refresh_repo.store_token(
                    user_mail_id=email,
                    refresh_token=refresh_token_str,
                    expires_at=expires_at,
                    user_agent=user_agent,
                    ip_address=ip_address,
                    role=role,
                    department_name=department_name
                )
                refresh_token = refresh_token_str

            return {
                "approval": True,
                "token": token,
                "refresh_token": refresh_token,
                "role": role,
                "department_name": department_name,
                "available_roles": available_roles,
                "message": f"Switched to role '{role}' in department '{department_name}'"
            }

        except Exception as e:
            log.error(f"Error switching role for {email}: {e}")
            return {"approval": False, "message": "Error switching role"}

    # ==================== Authorization Code Exchange Methods ====================

    def _generate_authorization_code(self) -> str:
        """
        Generate a cryptographically secure one-time authorization code.
        Format: 64 characters, URL-safe, high entropy.
        """
        return secrets.token_urlsafe(48)  # 48 bytes = 64 URL-safe characters

    async def generate_and_store_authorization_code(
        self,
        access_token: str,
        refresh_token: str,
        id_token: str,
        email: str,
        username: str,
        role: str,
        department_name: str,
        expires_in: int,
        ip_address: str = None,
        user_agent: str = None
    ) -> Optional[str]:
        """
        Generate and store a one-time authorization code for OAuth callback.

        This code will be used to exchange for actual tokens via /auth/exchange-code endpoint.

        Returns:
            Authorization code if successful, None otherwise
        """
        if not self.authorization_code_repo:
            log.error("AuthorizationCodeRepository not initialized")
            return None

        try:
            # Generate secure code
            code = self._generate_authorization_code()

            # Store in database with 60-second expiry
            success = await self.authorization_code_repo.store_code(
                code=code,
                access_token=access_token,
                refresh_token=refresh_token,
                id_token=id_token,
                email=email,
                username=username,
                role=role,
                department_name=department_name,
                expires_in=expires_in,
                expiry_seconds=60,  # Code expires in 60 seconds
                ip_address=ip_address,
                user_agent=user_agent
            )

            if success:
                log.info(f"Generated authorization code for user {email}")
                return code
            else:
                log.error(f"Failed to store authorization code for user {email}")
                return None

        except Exception as e:
            log.error(f"Error generating authorization code: {e}")
            return None

    async def exchange_authorization_code(self, code: str, ip_address: str = None, user_agent: str = None) -> dict:
        """
        Exchange one-time authorization code for tokens.

        Security features:
        - Code can only be used once
        - Code expires after 60 seconds
        - Logs all exchange attempts (success and failure)

        Returns:
            dict with approval, tokens, and user info
        """
        if not self.authorization_code_repo:
            log.error("AuthorizationCodeRepository not initialized")
            return {"approval": False, "message": "Authorization code exchange not available"}

        try:
            # Exchange code for tokens
            token_data = await self.authorization_code_repo.exchange_code(code)

            if not token_data:
                # Log failed attempt
                await self.audit_repo.log_action(
                    user_id=None,
                    action="CODE_EXCHANGE_FAILED",
                    resource_type="authorization_code",
                    resource_id=code[:8] + "...",  # Log only first 8 chars
                    new_value="Code not found, already used, or expired",
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                return {
                    "approval": False,
                    "message": "Invalid, expired, or already used authorization code"
                }

            # Log successful exchange
            await self.audit_repo.log_action(
                user_id=token_data['email'],
                action="CODE_EXCHANGE_SUCCESS",
                resource_type="authorization_code",
                resource_id=code[:8] + "...",
                new_value=f"User: {token_data['email']}, Role: {token_data['role']}, Department: {token_data['department_name']}",
                ip_address=ip_address,
                user_agent=user_agent
            )

            log.info(f"Successfully exchanged authorization code for user {token_data['email']}")

            # Auto-provision OAuth user in local DB if not exists
            existing_user = await self.user_repo.get_user_basic_by_email(token_data['email'])
            if not existing_user:
                log.info(f"Auto-provisioning OAuth user in local DB: {token_data['email']}")
                # Create user with a random unusable PWD (they authenticate via Keycloak)
                random_password = bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt()).decode('utf-8')
                await self.user_repo.create_user(
                    email=token_data['email'],
                    username=token_data['username'],
                    password=random_password
                )
                # Assign department/role mapping if department is provided
                if token_data['department_name'] and self.user_dept_mapping_repo:
                    try:
                        await self.user_dept_mapping_repo.add_user_to_department(
                            mail_id=token_data['email'],
                            department_name=token_data['department_name'],
                            role=token_data['role']
                        )
                    except Exception as e:
                        log.warning(f"Could not assign department mapping for OAuth user: {e}")

            # Resolve department from local DB if not provided by Keycloak
            resolved_department = token_data['department_name']
            resolved_role = token_data['role']
            if not resolved_department and self.user_dept_mapping_repo:
                user_depts = await self.user_dept_mapping_repo.get_user_departments(token_data['email'])
                active_depts = [d for d in user_depts if d.get('is_active', True)]
                if active_depts:
                    resolved_department = active_depts[0]['department_name']
                    resolved_role = active_depts[0]['role']
                    log.info(f"Resolved department for OAuth user {token_data['email']}: {resolved_department}")

            # Mint a local HS256 JWT (same as PWD login) instead of returning raw Keycloak RS256 token
            local_payload = {
                "mail_id": token_data['email'],
                "user_name": token_data['username'],
                "role": resolved_role,
                "department_name": resolved_department,
                "exp": datetime.utcnow() + timedelta(seconds=ACCESS_TOKEN_EXPIRE_SECONDS)
            }
            local_token = jwt.encode(local_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

            # Generate a refresh token
            refresh_token = None
            if self.refresh_repo and ENABLE_REFRESH_TOKENS:
                refresh_token = secrets.token_urlsafe(64)
                refresh_expires = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
                try:
                    await self.refresh_repo.store_token(
                        user_mail_id=token_data['email'],
                        refresh_token=refresh_token,
                        expires_at=refresh_expires,
                        user_agent=user_agent,
                        ip_address=ip_address,
                        role=resolved_role,
                        department_name=resolved_department
                    )
                except Exception as e:
                    log.error(f"Failed storing refresh token during code exchange: {e}")
                    refresh_token = None

            return {
                "approval": True,
                "token": local_token,
                "refresh_token": refresh_token,
                "id_token": token_data['id_token'],
                "email": token_data['email'],
                "username": token_data['username'],
                "role": resolved_role,
                "department_name": resolved_department,
                "expires_in": ACCESS_TOKEN_EXPIRE_SECONDS,
                "message": "Authorization code exchanged successfully"
            }

        except Exception as e:
            log.error(f"Error exchanging authorization code: {e}")
            return {"approval": False, "message": "An error occurred during code exchange"}

    async def cleanup_expired_authorization_codes(self) -> int:
        """
        Cleanup expired and used authorization codes.
        This should be called periodically (e.g., via background task).

        Returns:
            Number of codes cleaned up
        """
        if not self.authorization_code_repo:
            return 0

        try:
            count = await self.authorization_code_repo.cleanup_expired_codes()
            return count
        except Exception as e:
            log.error(f"Error cleaning up authorization codes: {e}")
            return 0

    # ==================== JIT Provisioning for SSO Users ====================

    async def handle_sso_user_jit_provisioning(self, email: str, username: str, ip_address: str = None, user_agent: str = None) -> dict:
        """
        Handle Just-In-Time (JIT) provisioning for new SSO users.

        Checks if user exists in the system. If not, creates a pending registration request
        that requires admin approval before the user can access the system.

        Args:
            email: User's email from SSO provider
            username: User's username from SSO provider
            ip_address: Client IP for audit logging
            user_agent: User agent for audit logging

        Returns:
            dict with status and message:
            - {"status": "PENDING_APPROVAL", "message": "..."} - New user, awaiting admin approval
            - {"status": "USER_EXISTS", "email": "..."} - User exists, can proceed with login
        """
        if not self.registration_request_repo:
            log.error("RegistrationRequestRepository not initialized")
            return {"status": "ERROR", "message": "System configuration error"}

        try:
            # Check if user exists in login_credential table
            user_data = await self.user_repo.get_user_basic_by_email(email)

            if user_data:
                # Check if the user's main account is active (login_credential.is_active)
                if not user_data.get('is_active', True):
                    log.warning(f"SSO login attempt for deactivated account: {email}")
                    await self.audit_repo.log_action(
                        user_id=email,
                        action="SSO_LOGIN_FAILED",
                        resource_type="user",
                        resource_id=email,
                        new_value="SSO login blocked - account is deactivated",
                        ip_address=ip_address,
                        user_agent=user_agent
                    )
                    return {
                        "status": "ACCOUNT_DEACTIVATED",
                        "message": "Your account has been deactivated. Please contact your administrator."
                    }

                # Fetch department assignments — used for both the deactivation check
                # and to return the user's real role/department (no hardcoded defaults).
                role = None
                department_name = None
                if self.user_dept_mapping_repo:
                    # get_user_departments filters out NULL-department rows (SuperAdmin marker),
                    # so check SuperAdmin status via a dedicated helper first.
                    is_superadmin = await self.user_dept_mapping_repo.has_superadmin_assignment_for_user(email)
                    if is_superadmin:
                        role = "SuperAdmin"
                        department_name = None
                    else:
                        user_depts = await self.user_dept_mapping_repo.get_user_departments(email)
                        if user_depts:
                            active_depts = [d for d in user_depts if d.get('is_active', True)]
                            if not active_depts:
                                log.warning(f"SSO login attempt for user with all departments deactivated: {email}")
                                await self.audit_repo.log_action(
                                    user_id=email,
                                    action="SSO_LOGIN_FAILED",
                                    resource_type="user",
                                    resource_id=email,
                                    new_value="SSO login blocked - user has no active department access",
                                    ip_address=ip_address,
                                    user_agent=user_agent
                                )
                                return {
                                    "status": "ACCOUNT_DEACTIVATED",
                                    "message": "Your access has been disabled. Please contact your department administrator."
                                }
                            # get_user_departments returns rows ordered by last_used_at desc —
                            # first active entry is the user's default/most-recent department.
                            default_dept = active_depts[0]
                            role = default_dept.get("role")
                            department_name = default_dept.get("department_name")

                # User exists and is active — return DB role, never a hardcoded default
                log.info(f"SSO user {email} exists in system, proceeding with login (role={role}, dept={department_name})")
                return {
                    "status": "USER_EXISTS",
                    "email": email,
                    "role": role,
                    "department_name": department_name,
                }

            # User doesn't exist - check if they already have a pending request
            has_pending = await self.registration_request_repo.has_pending_sso_request(email)

            if has_pending:
                # Already submitted department selection, waiting for admin approval
                log.info(f"SSO user {email} already has pending approval request")
                await self.audit_repo.log_action(
                    user_id=None,
                    action="SSO_LOGIN_PENDING",
                    resource_type="user",
                    resource_id=email,
                    new_value=f"SSO login attempt - already has pending approval request",
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                return {
                    "status": "PENDING_APPROVAL",
                    "message": "Your account is awaiting administrator approval. Please contact your system administrator."
                }

            # Auto-provision as SuperAdmin if email is in the seed list
            if email.lower() in INITIAL_SUPERADMIN_EMAILS:
                # SSO users have no local pwd; generate an unusable random hash
                # to satisfy the NOT NULL constraint on login_credential.pwd.
                _placeholder_pw = bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt()).decode('utf-8')
                user_id = await self.user_repo.create_user(
                    email=email, username=username, password=_placeholder_pw
                )
                if user_id:
                    await self.user_dept_mapping_repo.add_superadmin(
                        mail_id=email, created_by="system:env-seed"
                    )
                    await self.audit_repo.log_action(
                        user_id=email,
                        action="SUPERADMIN_AUTO_PROVISIONED",
                        resource_type="user",
                        resource_id=email,
                        new_value="SuperAdmin auto-provisioned from INITIAL_SUPERADMIN_EMAILS",
                        ip_address=ip_address,
                        user_agent=user_agent,
                    )
                    log.info(f"[JIT] {email} auto-provisioned as SuperAdmin from env seed list")
                    return {
                        "status": "USER_EXISTS",
                        "email": email,
                        "role": "SuperAdmin",
                        "department_name": None,
                    }

            # Brand new SSO user - ask them to select their department(s) first
            log.info(f"Brand new SSO user {email} - redirecting to department selection")
            await self.audit_repo.log_action(
                user_id=None,
                action="SSO_NEW_USER_DEPARTMENT_SELECTION",
                resource_type="user",
                resource_id=email,
                new_value="New SSO user redirected to department selection",
                ip_address=ip_address,
                user_agent=user_agent
            )
            return {
                "status": "NEEDS_DEPARTMENT_SELECTION",
                "email": email,
                "username": username,
                "message": "Please select the department(s) you want to join."
            }

        except Exception as e:
            log.error(f"Error in JIT provisioning for {email}: {e}")
            return {"status": "ERROR", "message": "An error occurred during user provisioning"}

    async def register_sso_user_with_departments(
        self, email: str, username: str, department_names: list,
        ip_address: str = None, user_agent: str = None
    ) -> dict:
        """
        Called when a new SSO user submits the department-selection form.
        Creates one pending registration request per selected department.
        """
        if not self.registration_request_repo:
            return {"success": False, "message": "System configuration error"}

        try:
            # Safety: reject if user already exists in the system
            user_data = await self.user_repo.get_user_basic_by_email(email)
            if user_data:
                return {"success": False, "message": "Account already exists. Please login normally."}

            # Safety: reject if pending request already submitted
            has_pending = await self.registration_request_repo.has_pending_sso_request(email)
            if has_pending:
                return {"success": False, "message": "You already have a pending registration request awaiting approval."}

            request_ids = await self.registration_request_repo.create_sso_requests_with_departments(
                email, username, department_names
            )

            if not request_ids:
                return {"success": False, "message": "Failed to submit registration request. Please try again."}

            await self.audit_repo.log_action(
                user_id=None,
                action="SSO_USER_PENDING_APPROVAL",
                resource_type="user",
                resource_id=email,
                new_value=f"SSO user submitted department registration for: {', '.join(department_names)} (IDs: {request_ids})",
                ip_address=ip_address,
                user_agent=user_agent
            )
            log.info(f"SSO user {email} registered for departments: {department_names}")

            # Notify admins about the new SSO registration
            try:
                if self.user_dept_mapping_repo:
                    all_admin_emails = set()
                    for dept in department_names:
                        dept_admins = await self.user_dept_mapping_repo.get_department_admin_emails(dept)
                        all_admin_emails.update(dept_admins)
                    if all_admin_emails:
                        notify_admins_new_registration(
                            admin_emails=list(all_admin_emails),
                            user_email=email,
                            user_name=username,
                            departments=department_names
                        )
            except Exception as email_err:
                log.warning(f"Failed to send admin notification email for SSO registration: {email_err}")

            return {"success": True, "message": "Registration submitted. Awaiting administrator approval."}

        except Exception as e:
            log.error(f"Error in SSO department registration for {email}: {e}")
            return {"success": False, "message": "An error occurred during registration"}

    async def list_pending_sso_users(self) -> dict:
        """
        Get list of all pending SSO users awaiting admin approval.

        Returns:
            dict with approval status and list of pending users
        """
        if not self.registration_request_repo:
            return {"approval": False, "pending_users": [], "message": "Registration repository not initialized"}

        try:
            pending_users = await self.registration_request_repo.get_all_pending_sso_users()

            # Convert to response format
            pending_list = [
                {
                    "id": user["id"],
                    "email": user["email_id"],
                    "username": user["user_name"],
                    "created_at": user["created_at"],
                    "is_sso": user["is_sso"]
                }
                for user in pending_users
            ]

            return {
                "approval": True,
                "pending_users": pending_list,
                "message": f"Found {len(pending_list)} pending SSO user(s)"
            }
        except Exception as e:
            log.error(f"Error listing pending SSO users: {e}")
            return {"approval": False, "pending_users": [], "message": "Failed to retrieve pending users"}

    async def approve_sso_user(self, request_id: int, department_name: str, role: str, admin_email: str, ip_address: str = None, user_agent: str = None) -> dict:
        """
        Approve a pending SSO user and assign them to a department with a role.

        This creates the user in login_credential and userdepartmentmapping tables.

        Args:
            request_id: ID of the pending registration request
            department_name: Department to assign the user to
            role: Role to assign (User, Developer, Admin, SuperAdmin)
            admin_email: Email of the admin approving the request
            ip_address: Client IP for audit logging
            user_agent: User agent for audit logging

        Returns:
            dict with approval status, user info, and message
        """
        if not self.registration_request_repo or not self.user_dept_mapping_repo:
            return {"approval": False, "message": "Required repositories not initialized"}

        try:
            # Get the registration request
            request_data = await self.registration_request_repo.get_request_by_id(request_id)

            if not request_data:
                return {"approval": False, "message": "Registration request not found"}

            if request_data["status"] != "pending":
                return {"approval": False, "message": f"Request is already {request_data['status']}"}

            if not request_data.get("is_sso", False):
                return {"approval": False, "message": "This is not an SSO registration request"}

            email = request_data["email_id"]
            username = request_data["user_name"]

            # Validate department exists
            if self.department_repo:
                dept_exists = await self.department_repo.validate_department_exists(department_name)
                if not dept_exists:
                    return {"approval": False, "message": f"Department '{department_name}' does not exist"}

            # Check if user already exists (safety check)
            existing_user = await self.user_repo.get_user_basic_by_email(email)
            if existing_user:
                return {"approval": False, "message": "User already exists in the system"}

            # Create user in login_credential with placeholder PWD (SSO users don't use local PWD)
            # Use a secure random PWD that will never be used
            import secrets
            placeholder_password = secrets.token_urlsafe(32)
            hashed_password = bcrypt.hashpw(placeholder_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

            user_id = await self.user_repo.create_user(email, username, hashed_password)

            if not user_id:
                return {"approval": False, "message": "Failed to create user account"}

            # Assign user to department with role
            mapping_created = await self.user_dept_mapping_repo.add_user_to_department(
                email, department_name, role
            )

            if not mapping_created:
                # Rollback: This is tricky - we'd need transaction support
                # For now, log error
                log.error(f"Failed to create department mapping for {email}, but user was created")
                return {"approval": False, "message": "Failed to assign department to user"}

            # Approve the registration request
            approved = await self.registration_request_repo.approve_sso_request(
                request_id, department_name, role, admin_email
            )

            if not approved:
                log.warning(f"User and mapping created but failed to update request status for {email}")

            # Log the approval
            await self.audit_repo.log_action(
                user_id=admin_email,
                action="SSO_USER_APPROVED",
                resource_type="user",
                resource_id=email,
                new_value=f"Approved by {admin_email}, assigned to {department_name} as {role}",
                ip_address=ip_address,
                user_agent=user_agent
            )

            log.info(f"SSO user {email} approved and assigned to {department_name} as {role}")

            # Notify the SSO user about the approval
            try:
                notify_user_request_approved(
                    user_email=email,
                    department_name=department_name,
                    assigned_role=role,
                    approved_by=admin_email
                )
            except Exception as email_err:
                log.warning(f"Failed to send approval notification email to {email}: {email_err}")

            return {
                "approval": True,
                "email": email,
                "department_name": department_name,
                "role": role,
                "message": f"User {email} has been approved and assigned to {department_name} as {role}"
            }

        except Exception as e:
            log.error(f"Error approving SSO user (request {request_id}): {e}")
            return {"approval": False, "message": "An error occurred while approving the user"}

    async def promote_to_superadmin(
        self, target_email: str, current_user, ip_address: str = None, user_agent: str = None
    ) -> dict:
        if current_user.role != "SuperAdmin":
            return {"success": False, "message": "Only SuperAdmin can promote others to SuperAdmin"}

        user_data = await self.user_repo.get_user_basic_by_email(target_email)
        if not user_data:
            return {"success": False, "message": f"User {target_email} not found. They must log in at least once."}

        already_superadmin = await self.user_dept_mapping_repo.get_user_role_for_department(
            mail_id=target_email, department_name=None
        )
        if already_superadmin == "SuperAdmin":
            return {"success": False, "message": f"{target_email} is already a SuperAdmin"}

        success = await self.user_dept_mapping_repo.add_superadmin(
            mail_id=target_email, created_by=current_user.email
        )
        if not success:
            return {"success": False, "message": "Failed to promote user to SuperAdmin"}

        await self.audit_repo.log_action(
            user_id=current_user.email,
            action="SUPERADMIN_PROMOTED",
            resource_type="user",
            resource_id=target_email,
            new_value=f"Promoted to SuperAdmin by {current_user.email}",
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return {"success": True, "message": f"{target_email} promoted to SuperAdmin successfully"}

    async def depromote_from_superadmin(
        self, target_email: str, current_user, ip_address: str = None, user_agent: str = None
    ) -> dict:
        if current_user.role != "SuperAdmin":
            return {"success": False, "message": "Only SuperAdmin can depromote other SuperAdmins"}

        if target_email.lower() == current_user.email.lower():
            return {"success": False, "message": "You cannot depromote yourself from SuperAdmin"}

        if target_email.lower() in INITIAL_SUPERADMIN_EMAILS:
            return {
                "success": False,
                "message": f"{target_email} is listed in INITIAL_SUPERADMIN_EMAILS and cannot be depromoted",
            }

        user_data = await self.user_repo.get_user_basic_by_email(target_email)
        if not user_data:
            return {"success": False, "message": f"User {target_email} not found"}

        current_role = await self.user_dept_mapping_repo.get_user_role_for_department(
            mail_id=target_email, department_name=None
        )
        if current_role != "SuperAdmin":
            return {"success": False, "message": f"{target_email} is not a SuperAdmin"}

        success = await self.user_dept_mapping_repo.remove_superadmin(mail_id=target_email)
        if not success:
            return {"success": False, "message": "Failed to depromote user from SuperAdmin"}

        await self.audit_repo.log_action(
            user_id=current_user.email,
            action="SUPERADMIN_depromoteD",
            resource_type="user",
            resource_id=target_email,
            old_value="SuperAdmin",
            new_value=f"depromoted from SuperAdmin by {current_user.email}",
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return {"success": True, "message": f"{target_email} depromoted from SuperAdmin successfully"}
