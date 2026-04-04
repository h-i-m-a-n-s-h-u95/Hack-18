from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import asyncio
import os

from app.auth.api_key_manager import APIKeyManager
from app.messaging.redis_client import get_redis_client
from app.config.settings import settings

router = APIRouter(prefix="/bootstrap", tags=["Bootstrap"])

class AdminKeyRequest(BaseModel):
    name: str = "Admin Key"
    description: str = "Initial admin API key"
    expires_in_days: int | None = None

class AdminKeyResponse(BaseModel):
    api_key: str
    key_id: str
    name: str
    created_at: str
    expires_at: str | None
    rate_limit_qps: float
    scopes: list[str]

@router.post("/admin-key", response_model=AdminKeyResponse)
async def create_admin_key(req: AdminKeyRequest):
    """
    Create a bootstrap Admin API key via HTTP.
    """
    redis_client = get_redis_client()

    try:
        await redis_client.connect()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to connect to Redis: {e}"
        )

    try:
        manager = APIKeyManager(redis_client)
        api_key, metadata = await manager.create_api_key(
            name=req.name,
            description=req.description,
            created_by="bootstrap-route",
            expires_in_days=req.expires_in_days,
            rate_limit_qps=100.0,
            scopes=["read", "write", "admin"]
        )

        return AdminKeyResponse(
            api_key=api_key,
            key_id=metadata.key_id,
            name=metadata.name,
            created_at=str(metadata.created_at),
            expires_at=str(metadata.expires_at) if metadata.expires_at else None,
            rate_limit_qps=metadata.rate_limit_qps,
            scopes=metadata.scopes
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create admin API key: {e}"
        )
    finally:
        await redis_client.disconnect()