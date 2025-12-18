import bcrypt
import jwt
import secrets
from datetime import datetime, timedelta
from typing import Optional
from src.auth.models import User, UserRole, UserStatus, LoginRequest, LoginResponse, RegisterRequest, RegisterResponse, RefreshTokenResponse
from src.auth.repositories import UserRepository, AuditLogRepository, RefreshTokenRepository
from telemetry_wrapper import logger as log
from src.config.settings import (
    JWT_SECRET, JWT_ALGORITHM, ACCESS_TOKEN_EXPIRE_SECONDS,
    REFRESH_TOKEN_EXPIRE_DAYS, ENABLE_REFRESH_TOKENS
)

# In-memory blacklist for demonstration (use persistent store in production)
JWT_BLACKLIST = set()

class AuthService:
    """Service for authentication operations"""

    def __init__(self, user_repo: UserRepository, audit_repo: AuditLogRepository, refresh_repo: RefreshTokenRepository = None):
        self.user_repo = user_repo
        self.audit_repo = audit_repo
        # refresh_repo is optional to keep backward compatibility if not wired yet
        self.refresh_repo = refresh_repo

    async def login(self, login_request: LoginRequest, ip_address: str = None, user_agent: str = None) -> LoginResponse:
        """Authenticate user and create session"""
        try:
            # Get user by email
            user_data = await self.user_repo.get_user_by_email(login_request.email_id)
            
            if not user_data:
                await self.audit_repo.log_action(
                    user_id=None,
                    action="LOGIN_FAILED",
                    resource_type="user",
                    resource_id=login_request.email_id,
                    new_value="User not found",
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                return LoginResponse(approval=False, message="User not found")
            
            # Check pwd
            if not bcrypt.checkpw(login_request.password.encode('utf-8'), user_data['password'].encode('utf-8')):
                await self.audit_repo.log_action(
                    user_id=str(user_data['mail_id']),
                    action="LOGIN_FAILED",
                    resource_type="user",
                    resource_id=login_request.email_id,
                    new_value="Incorrect password",
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                return LoginResponse(approval=False, message="Incorrect password")
            
            # Check role authorization
            user_role = user_data['role']
            requested_role = login_request.role
            if requested_role not in ["User", "Developer", "Admin", "SuperAdmin"]:
                return LoginResponse(approval=False, message="Invalid role requested")
            
            if user_role == UserRole.ADMIN.value:
                pass  # Admin can access any role
            elif user_role == UserRole.DEVELOPER.value and requested_role == UserRole.ADMIN.value:
                return LoginResponse(approval=False, message="You are not authorized as Admin")
            elif user_role == UserRole.USER.value and requested_role in (UserRole.DEVELOPER.value, UserRole.ADMIN.value):
                return LoginResponse(approval=False, message=f"You are not authorized as {requested_role}")
            
            
            # Generate short-lived access JWT token
            payload = {
                "mail_id": user_data['mail_id'],
                "user_name": user_data['user_name'],
                "role": requested_role,  
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
                        ip_address=ip_address
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
                new_value=f"Role: {requested_role}",
                ip_address=ip_address,
                user_agent=user_agent
            )

            return LoginResponse(
                approval=True,
                token=token,
                refresh_token=refresh_token,
                role=requested_role,
                username=user_data['user_name'],
                email=user_data['mail_id'],
                message="Login successful",
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
                        ip_address=ip_address
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
            user_data = await self.user_repo.get_user_by_email(user_mail_id)
            if not user_data:
                return RefreshTokenResponse(approval=False, message="User no longer exists", token=None)
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
                    ip_address=ip_address
                )
            except Exception as e:
                log.error(f"Failed to store rotated refresh token: {e}")
                new_refresh_token = None
            # Create new access token
            payload = {
                "mail_id": user_data['mail_id'],
                "user_name": user_data['user_name'],
                "role": user_data['role'],
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
    
    async def register(self, register_request: RegisterRequest, ip_address: str = None, user_agent: str = None) -> RegisterResponse:
        """Register new user"""
        try:
            # Check if user already exists
            existing_user = await self.user_repo.get_user_by_email(register_request.email_id)
            if existing_user:
                return RegisterResponse(approval=False, message="User already exists")
            
            # Hash PWD
            password_hash = bcrypt.hashpw(register_request.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            # Create user
            user_id = await self.user_repo.create_user(
                email=register_request.email_id,
                username=register_request.user_name,
                password=password_hash,
                role=register_request.role
            )
            
            if not user_id:
                return RegisterResponse(approval=False, message="Registration failed")
            
            # Log registration
            await self.audit_repo.log_action(
                user_id=user_id,
                action="USER_REGISTERED",
                resource_type="user",
                resource_id=register_request.email_id,
                new_value=f"Role: {register_request.role}",
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            return RegisterResponse(approval=True, message=f"{register_request.user_name} registered successfully")
            
        except Exception as e:
            log.error(f"Registration error: {e}")
            return RegisterResponse(approval=False, message="Registration failed due to an error")
    
    async def validate_jwt(self, token: str) -> Optional[User]:
        """Validate JWT and return user info"""
        try:
            if token in JWT_BLACKLIST:
                log.warning("JWT token is blacklisted (logged out)")
                return None
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            user_data = await self.user_repo.get_user_by_email(payload["mail_id"])
            if not user_data:
                return None
            return User(
                id=user_data['mail_id'],
                email=user_data['mail_id'],
                username=user_data['user_name'],
                role=UserRole(payload['role']),
                status=UserStatus.ACTIVE,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
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
                user_data = await self.user_repo.get_user_by_email(email)
                
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
