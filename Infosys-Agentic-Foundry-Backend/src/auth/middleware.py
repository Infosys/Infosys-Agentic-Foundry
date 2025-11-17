from fastapi import Request, Response, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from src.auth.dependencies import get_user_info_from_request, get_client_ip, get_user_agent
from telemetry_wrapper import logger as log, update_session_context
from typing import Set
from src.utils.secrets_handler import current_user_email

class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Middleware to handle authentication for all requests"""
    
    # Define public endpoints that don't require authentication
    PUBLIC_ENDPOINTS: Set[str] = {
        "/auth/login",
        "/auth/register", 
        "/auth/guest-login",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/favicon.ico",
        "/health",
        "/metrics",
        "/get-version",
        "/auth/me",
        "/utility/get/version",
        "/chat/sdlc-agent/inference",
        "/utility/files/user-uploads/download",
        "/download"
    }

    def __init__(self, app, exclude_paths: Set[str] = None):
        super().__init__(app)
        if exclude_paths:
            self.PUBLIC_ENDPOINTS.update(exclude_paths)
    
    async def dispatch(self, request: Request, call_next):
        """Process each request through authentication middleware"""
        
        # Skip authentication for public endpoints
        if self._is_public_endpoint(request.url.path):
            return await call_next(request)
        log.info("about to call options")
        # Skip authentication for OPTIONS requests (CORS preflight)
        if request.method == "OPTIONS":
            response = await call_next(request)
            log.info(f"OPTIONS response status: {response.status_code}")
            log.info(f"OPTIONS response headers: {dict(response.headers)}")
            body = b""
            async for chunk in response.body_iterator:
                body += chunk
            log.info(f"OPTIONS response body: {body.decode('utf-8', errors='replace')}")
            # Reconstruct the response since body_iterator is consumed
            # response = Response(content=body, status_code=response.status_code, headers=dict(response.headers))
            return response
        log.info("about to validate")
        try:
            # Get user information from request
            user_info = await get_user_info_from_request(request)
            log.info("user details ")
            if not user_info:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Authentication required"}
                )
            log.info(f"user details: {user_info}")
            # Set user context in request state
            request.state.user = user_info
            body = await request.body()
            body_data = {}
            # Parse JSON manually
            if body and request.headers.get("content-type") == "application/json":
                try:
                    import json
                    body_data = json.loads(body.decode())
                    # Now you have access to: body_data["message"], body_data["metadata"], etc.
                except:
                    body_data = {}
            log.info(f"Query Parameters {body_data}")
            # Update session context for telemetry (remove user_session, use JWT token if needed)
            update_session_context(
                user_id=user_info.email,
                user_session=None,  # No session, JWT only
                session_id=user_info.email  # Use email as unique identifier
            )
            current_user_email.set(user_info.email)
            # Process the request
            response = await call_next(request)
            
            return response
            
        except Exception as e:
            log.error(f"Authentication middleware error: {e}")
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": f"Error is {e}"}
            )
    
    def _is_public_endpoint(self, path: str) -> bool:
        """Check if the endpoint is public (doesn't require authentication)"""
        # Exact match
        if path in self.PUBLIC_ENDPOINTS:
            return True
        
        # Check for path patterns
        public_patterns = [
            "/auth/",
            "/docs",
            "/openapi.json",
            "/redoc",
            "/static",
        ]
        
        return any(path.startswith(pattern) for pattern in public_patterns)


class AuditMiddleware(BaseHTTPMiddleware):
    """Middleware to log API requests for audit purposes"""
    
    def __init__(self, app, log_requests: bool = True):
        super().__init__(app)
        self.log_requests = log_requests
    
    async def dispatch(self, request: Request, call_next):
        """Log request details for audit"""
        
        if not self.log_requests:
            return await call_next(request)
        
        # Get request details
        ip_address = get_client_ip(request)
        method = request.method
        path = request.url.path
        log.info(f"Received {method} request for {path} from {ip_address} ")
        # Get user info if available
        response = await call_next(request)

        user_info = getattr(request.state, 'user', None)
        user_id = user_info.email if user_info and hasattr(user_info, 'email') else 'anonymous'
        
        # Log request
        log.info(f"API Request: {method} {path} - User: {user_id} - IP: {ip_address} - Status: {response.status_code}")
        log.info(f"Request Body: {request.body}")
        log.info(f"Request Path: {request.scope.get('path_params', {})}")

        # Log response status
        log.info(f"API Response: {method} {path} - Status: {response.status_code} - User: {user_id}")
        
        return response
