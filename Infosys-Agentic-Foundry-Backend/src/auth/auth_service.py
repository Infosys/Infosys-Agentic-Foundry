import bcrypt
import jwt
import secrets
from datetime import datetime, timedelta
from typing import Optional
from src.auth.models import User, UserRole, UserStatus, LoginRequest, LoginResponse, RegisterRequest, RegisterResponse
from src.auth.repositories import UserRepository, AuditLogRepository
from telemetry_wrapper import logger as log

JWT_SECRET = "your_jwt_secret"  # Use config/env in production
JWT_ALGORITHM = "HS256"
JWT_EXP_DELTA_SECONDS = 3 * 60 * 60  # 3 hours

# In-memory blacklist for demonstration (use persistent store in production)
JWT_BLACKLIST = set()

class AuthService:
    """Service for authentication operations"""

    def __init__(self, user_repo: UserRepository, audit_repo: AuditLogRepository):
        self.user_repo = user_repo
        self.audit_repo = audit_repo

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
            
            # Check password
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
            
            if user_role == UserRole.ADMIN.value:
                pass  # Admin can access any role
            elif user_role == UserRole.DEVELOPER.value and requested_role == UserRole.ADMIN.value:
                return LoginResponse(approval=False, message="You are not authorized as Admin")
            elif user_role == UserRole.USER.value and requested_role in (UserRole.DEVELOPER.value, UserRole.ADMIN.value):
                return LoginResponse(approval=False, message=f"You are not authorized as {requested_role}")
            
            # Generate JWT token
            payload = {
                "mail_id": user_data['mail_id'],
                "user_name": user_data['user_name'],
                "role": user_data['role'],
                "exp": datetime.utcnow() + timedelta(seconds=JWT_EXP_DELTA_SECONDS)
            }
            token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

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
                role=requested_role,
                username=user_data['user_name'],
                email=user_data['mail_id'],
                message="Login successful"
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
                "exp": datetime.utcnow() + timedelta(seconds=JWT_EXP_DELTA_SECONDS)
            }
            token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

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
                role=user_data['role'],
                username=user_data['user_name'],
                email=user_data['mail_id'],
                message="Guest login successful"
            )

        except Exception as e:
            log.error(f"Guest login error: {e}")
            return LoginResponse(approval=False, message="Guest login failed due to an error.")

    async def logout(self, token: str, ip_address: str = None, user_agent: str = None) -> bool:
        """Logout user by blacklisting JWT token"""
        try:
            JWT_BLACKLIST.add(token)
            log.info(f"Token blacklisted for logout: {token}")
            await self.audit_repo.log_action(
                user_id=None,
                action="LOGOUT",
                resource_type="user",
                resource_id=None,
                new_value="JWT token blacklisted",
                ip_address=ip_address,
                user_agent=user_agent
            )
            return True
        except Exception as e:
            log.error(f"Logout error: {e}")
            return False
    
    async def register(self, register_request: RegisterRequest, ip_address: str = None, user_agent: str = None) -> RegisterResponse:
        """Register new user"""
        try:
            # Check if user already exists
            existing_user = await self.user_repo.get_user_by_email(register_request.email_id)
            if existing_user:
                return RegisterResponse(approval=False, message="User already exists")
            
            # Hash password
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
                role=UserRole(user_data['role']),
                status=UserStatus.ACTIVE,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
        except Exception as e:
            log.error(f"JWT validation error: {e}")
            return None
    
    async def update_password(self, email: str, new_password: str, current_user_id: str, 
                            ip_address: str = None, user_agent: str = None) -> bool:
        """Update user password"""
        try:
            # Hash new password
            password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            # Update password
            success = await self.user_repo.update_user_password(email, password_hash)
            
            if success:
                # Get user for audit log
                user_data = await self.user_repo.get_user_by_email(email)
                
                # Log password change
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
