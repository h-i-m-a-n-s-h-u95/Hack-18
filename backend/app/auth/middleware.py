"""
app/auth/middleware.py
Middleware for API Key Authentication
"""
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable
import logging

from app.auth.api_key_manager import APIKeyManager
from app.messaging.redis_client import get_redis_client

logger = logging.getLogger(__name__)


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to validate API keys for protected routes
    """
    
    # Routes that don't require API key authentication
    EXEMPT_PATHS = [
        "/docs",
        "/redoc",
        "/openapi.json",
        "/",
        "/status",
        "/health",
    ]
    
    # Routes that require admin scope
    ADMIN_PATHS = [
        "/api/v1/keys",
    ]
    
    def __init__(self, app, enforce_auth: bool = True):
        super().__init__(app)
        self.enforce_auth = enforce_auth
        self.manager: APIKeyManager = None
    
    async def get_manager(self) -> APIKeyManager:
        """Lazy load API key manager"""
        if self.manager is None:
            redis_client = get_redis_client()
            if redis_client._client is None:
                await redis_client.connect()
            self.manager = APIKeyManager(redis_client)
        return self.manager
    
    def is_exempt_path(self, path: str) -> bool:
        """Check if path is exempt from authentication"""
        for exempt_path in self.EXEMPT_PATHS:
            if path.startswith(exempt_path):
                return True
        return False
    
    def is_admin_path(self, path: str) -> bool:
        """Check if path requires admin permissions"""
        for admin_path in self.ADMIN_PATHS:
            if path.startswith(admin_path):
                return True
        return False
    
    async def dispatch(self, request: Request, call_next: Callable):
        """Process request and validate API key"""
        
        # Skip authentication for exempt paths
        if self.is_exempt_path(request.url.path):
            return await call_next(request)
        
        # Skip if authentication not enforced (development mode)
        if not self.enforce_auth:
            logger.debug(f"API key auth disabled for: {request.url.path}")
            return await call_next(request)
        
        # Extract API key from header
        api_key = request.headers.get("X-API-Key")
        
        if not api_key:
            logger.warning(f"Missing API key for: {request.url.path}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key is required. Provide X-API-Key header."
            )
        
        # Validate API key
        try:
            manager = await self.get_manager()
            metadata = await manager.validate_api_key(api_key)
            
            if not metadata:
                logger.warning(f"Invalid API key attempt for: {request.url.path}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired API key"
                )
            
            # Check admin permissions for admin paths
            if self.is_admin_path(request.url.path):
                if "admin" not in metadata.scopes:
                    logger.warning(
                        f"Non-admin key attempted admin route: {request.url.path}, "
                        f"key_id: {metadata.key_id}"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Admin permissions required"
                    )
            
            # Attach metadata to request state for use in routes
            request.state.api_key_metadata = metadata
            
            logger.debug(
                f"Authenticated request: {request.url.path}, "
                f"key_id: {metadata.key_id}, key_name: {metadata.name}"
            )
            
            response = await call_next(request)
            return response
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error validating API key: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal authentication error"
            )