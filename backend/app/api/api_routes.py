"""
app/api/api_key_routes.py
FastAPI routes for API Key Management
"""
from fastapi import APIRouter, Depends, HTTPException, status, Security, Header
from fastapi.security import APIKeyHeader
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime
import logging

from app.auth.api_key_manager import APIKeyManager, APIKeyMetadata, APIKeyStatus
from app.messaging.redis_client import get_redis_client, RedisClient

logger = logging.getLogger(__name__)

# Router
router = APIRouter(prefix="/api/v1/keys", tags=["API Key Management"])

# Security
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


# ==================== REQUEST/RESPONSE MODELS ====================

class CreateAPIKeyRequest(BaseModel):
    """Request model for creating an API key"""
    name: str = Field(..., min_length=1, max_length=100, description="Name for the API key")
    description: Optional[str] = Field(None, max_length=500, description="Optional description")
    expires_in_days: Optional[int] = Field(None, gt=0, le=3650, description="Expiration in days")
    rate_limit_qps: float = Field(10.0, gt=0, le=1000, description="Rate limit in queries per second")
    scopes: Optional[List[str]] = Field(default=["read", "write"], description="Permission scopes")
    metadata: Optional[dict] = Field(None, description="Additional metadata")


class CreateAPIKeyResponse(BaseModel):
    """Response model for created API key"""
    api_key: str = Field(..., description="The generated API key - SAVE THIS!")
    key_id: str
    name: str
    created_at: datetime
    expires_at: Optional[datetime]
    rate_limit_qps: float
    scopes: List[str]


class APIKeyInfo(BaseModel):
    """Public info about an API key"""
    key_id: str
    name: str
    description: Optional[str]
    created_at: datetime
    created_by: Optional[str]
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    status: str
    total_requests: int
    rate_limit_qps: float
    scopes: List[str]


class UpdateAPIKeyRequest(BaseModel):
    """Request model for updating API key metadata"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    rate_limit_qps: Optional[float] = Field(None, gt=0, le=1000)
    scopes: Optional[List[str]] = None


# ==================== DEPENDENCIES ====================

async def get_api_key_manager() -> APIKeyManager:
    """Get API Key Manager instance"""
    redis_client = get_redis_client()
    # Ensure connected
    if redis_client._client is None:
        await redis_client.connect()
    return APIKeyManager(redis_client)


async def validate_api_key_dependency(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    manager: APIKeyManager = Depends(get_api_key_manager)
) -> APIKeyMetadata:
    """
    Validate API key from header
    Use this as a dependency for protected routes
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is missing. Provide X-API-Key header."
        )
    
    metadata = await manager.validate_api_key(x_api_key)
    
    if not metadata:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key"
        )
    
    return metadata


async def validate_admin_key(
    current_key: APIKeyMetadata = Depends(validate_api_key_dependency)
) -> APIKeyMetadata:
    """Validate that the API key has admin permissions"""
    if "admin" not in current_key.scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permissions required"
        )
    return current_key


# ==================== ROUTES ====================

@router.post("/", response_model=CreateAPIKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    request: CreateAPIKeyRequest,
    manager: APIKeyManager = Depends(get_api_key_manager),
    admin: APIKeyMetadata = Depends(validate_admin_key)
):
    """
    Create a new API key
    
    **⚠️ Important:** The API key is only shown once in the response. Save it securely!
    
    **Requires:** Admin permissions (scope: admin)
    """
    try:
        api_key, metadata = await manager.create_api_key(
            name=request.name,
            description=request.description,
            created_by=admin.created_by or admin.key_id,
            expires_in_days=request.expires_in_days,
            rate_limit_qps=request.rate_limit_qps,
            scopes=request.scopes,
            metadata=request.metadata
        )
        
        return CreateAPIKeyResponse(
            api_key=api_key,
            key_id=metadata.key_id,
            name=metadata.name,
            created_at=metadata.created_at,
            expires_at=metadata.expires_at,
            rate_limit_qps=metadata.rate_limit_qps,
            scopes=metadata.scopes
        )
    except Exception as e:
        logger.error(f"Failed to create API key: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create API key: {str(e)}"
        )


@router.get("/", response_model=List[APIKeyInfo])
async def list_api_keys(
    manager: APIKeyManager = Depends(get_api_key_manager),
    admin: APIKeyMetadata = Depends(validate_admin_key)
):
    """
    List all active API keys
    
    **Requires:** Admin permissions
    """
    keys = await manager.list_all_active_keys()
    
    return [
        APIKeyInfo(
            key_id=k.key_id,
            name=k.name,
            description=k.description,
            created_at=k.created_at,
            created_by=k.created_by,
            last_used_at=k.last_used_at,
            expires_at=k.expires_at,
            status=k.status.value,
            total_requests=k.total_requests,
            rate_limit_qps=k.rate_limit_qps,
            scopes=k.scopes
        )
        for k in keys
    ]


@router.get("/me", response_model=APIKeyInfo)
async def get_my_key_info(
    current_key: APIKeyMetadata = Depends(validate_api_key_dependency)
):
    """
    Get information about the current API key being used
    
    Useful for checking key status, usage, and permissions.
    """
    return APIKeyInfo(
        key_id=current_key.key_id,
        name=current_key.name,
        description=current_key.description,
        created_at=current_key.created_at,
        created_by=current_key.created_by,
        last_used_at=current_key.last_used_at,
        expires_at=current_key.expires_at,
        status=current_key.status.value,
        total_requests=current_key.total_requests,
        rate_limit_qps=current_key.rate_limit_qps,
        scopes=current_key.scopes
    )


@router.get("/{key_id}", response_model=APIKeyInfo)
async def get_api_key(
    key_id: str,
    manager: APIKeyManager = Depends(get_api_key_manager),
    admin: APIKeyMetadata = Depends(validate_admin_key)
):
    """
    Get details about a specific API key
    
    **Requires:** Admin permissions
    """
    metadata = await manager.get_key_metadata(key_id)
    
    if not metadata:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key {key_id} not found"
        )
    
    return APIKeyInfo(
        key_id=metadata.key_id,
        name=metadata.name,
        description=metadata.description,
        created_at=metadata.created_at,
        created_by=metadata.created_by,
        last_used_at=metadata.last_used_at,
        expires_at=metadata.expires_at,
        status=metadata.status.value,
        total_requests=metadata.total_requests,
        rate_limit_qps=metadata.rate_limit_qps,
        scopes=metadata.scopes
    )


@router.patch("/{key_id}", response_model=APIKeyInfo)
async def update_api_key(
    key_id: str,
    request: UpdateAPIKeyRequest,
    manager: APIKeyManager = Depends(get_api_key_manager),
    admin: APIKeyMetadata = Depends(validate_admin_key)
):
    """
    Update API key metadata
    
    Can update: name, description, rate limit, and scopes.
    Cannot update: the actual key value or creation date.
    
    **Requires:** Admin permissions
    """
    updated = await manager.update_key_metadata(
        key_id=key_id,
        name=request.name,
        description=request.description,
        rate_limit_qps=request.rate_limit_qps,
        scopes=request.scopes
    )
    
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key {key_id} not found"
        )
    
    return APIKeyInfo(
        key_id=updated.key_id,
        name=updated.name,
        description=updated.description,
        created_at=updated.created_at,
        created_by=updated.created_by,
        last_used_at=updated.last_used_at,
        expires_at=updated.expires_at,
        status=updated.status.value,
        total_requests=updated.total_requests,
        rate_limit_qps=updated.rate_limit_qps,
        scopes=updated.scopes
    )


@router.post("/{key_id}/revoke")
async def revoke_api_key(
    key_id: str,
    manager: APIKeyManager = Depends(get_api_key_manager),
    admin: APIKeyMetadata = Depends(validate_admin_key)
):
    """
    Revoke an API key
    
    Revoked keys cannot be used but their metadata is retained for audit purposes.
    
    **Requires:** Admin permissions
    """
    success = await manager.revoke_api_key(key_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key {key_id} not found"
        )
    
    return {"message": f"API key {key_id} revoked successfully", "key_id": key_id}


@router.delete("/{key_id}")
async def delete_api_key(
    key_id: str,
    manager: APIKeyManager = Depends(get_api_key_manager),
    admin: APIKeyMetadata = Depends(validate_admin_key)
):
    """
    Permanently delete an API key
    
    This removes all metadata and cannot be undone.
    Consider revoking instead if you need to maintain audit history.
    
    **Requires:** Admin permissions
    """
    success = await manager.delete_api_key(key_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key {key_id} not found"
        )
    
    return {"message": f"API key {key_id} deleted successfully", "key_id": key_id}


@router.get("/user/{user_id}/keys", response_model=List[APIKeyInfo])
async def list_user_keys(
    user_id: str,
    manager: APIKeyManager = Depends(get_api_key_manager),
    admin: APIKeyMetadata = Depends(validate_admin_key)
):
    """
    List all API keys created by a specific user
    
    **Requires:** Admin permissions
    """
    keys = await manager.list_keys_by_user(user_id)
    
    return [
        APIKeyInfo(
            key_id=k.key_id,
            name=k.name,
            description=k.description,
            created_at=k.created_at,
            created_by=k.created_by,
            last_used_at=k.last_used_at,
            expires_at=k.expires_at,
            status=k.status.value,
            total_requests=k.total_requests,
            rate_limit_qps=k.rate_limit_qps,
            scopes=k.scopes
        )
        for k in keys
    ]



@router.get("/stats/usage")
async def get_usage_stats(
    manager: APIKeyManager = Depends(get_api_key_manager),
    admin: APIKeyMetadata = Depends(validate_admin_key)
):
    """
    Get overall API key usage statistics
    
    **Requires:** Admin permissions
    """
    stats = await manager.get_usage_stats()
    return stats