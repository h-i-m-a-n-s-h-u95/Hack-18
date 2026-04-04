"""
app/auth/api_key_manager.py
API Key Management System for Ringmaster Orchestrator
Integrated with existing RedisClient
"""
import secrets
import hashlib
import json
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from enum import Enum
from pydantic import BaseModel, Field
import logging

from app.messaging.redis_client import RedisClient

logger = logging.getLogger(__name__)


class APIKeyStatus(str, Enum):
    """API Key status enumeration"""
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class APIKeyMetadata(BaseModel):
    """Metadata for an API key"""
    key_id: str
    name: str
    description: Optional[str] = None
    created_at: datetime
    created_by: Optional[str] = None
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    status: APIKeyStatus = APIKeyStatus.ACTIVE
    
    # Usage tracking
    total_requests: int = 0
    rate_limit_qps: float = 10.0
    
    # Permissions/scopes
    scopes: List[str] = Field(default_factory=lambda: ["read", "write"])
    
    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)


class APIKeyManager:
    """
    Manages API key creation, validation, and storage in Redis
    
    Redis Key Structure:
    - apikey:hash:{hash} -> key_id (for lookup)
    - apikey:metadata:{key_id} -> APIKeyMetadata (JSON)
    - apikey:index:user:{user_id} -> Set of key_ids
    - apikey:active_keys -> Set of active key_ids
    """
    
    KEY_PREFIX = "rm_"
    REDIS_HASH_KEY = "apikey:hash:{hash}"
    REDIS_METADATA_KEY = "apikey:metadata:{key_id}"
    REDIS_USER_INDEX_KEY = "apikey:index:user:{user_id}"
    REDIS_ACTIVE_KEYS_SET = "apikey:active_keys"
    
    def __init__(self, redis_client: RedisClient):
        """
        Initialize API Key Manager
        
        Args:
            redis_client: RedisClient instance
        """
        self.redis = redis_client
    
    @staticmethod
    def generate_api_key() -> str:
        """Generate a secure random API key (rm_<64 hex chars>)"""
        random_bytes = secrets.token_bytes(32)
        key_hex = random_bytes.hex()
        return f"{APIKeyManager.KEY_PREFIX}{key_hex}"
    
    @staticmethod
    def hash_api_key(api_key: str) -> str:
        """Hash an API key for secure storage"""
        return hashlib.sha256(api_key.encode()).hexdigest()
    
    @staticmethod
    def generate_key_id() -> str:
        """Generate a unique key ID"""
        return f"key_{secrets.token_hex(16)}"
    
    async def create_api_key(
        self,
        name: str,
        description: Optional[str] = None,
        created_by: Optional[str] = None,
        expires_in_days: Optional[int] = None,
        rate_limit_qps: float = 10.0,
        scopes: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> tuple[str, APIKeyMetadata]:
        """
        Create a new API key with metadata
        
        Returns:
            Tuple of (api_key, metadata)
        """
        # Generate API key and key ID
        api_key = self.generate_api_key()
        key_id = self.generate_key_id()
        key_hash = self.hash_api_key(api_key)
        
        # Calculate expiration
        created_at = datetime.utcnow()
        expires_at = None
        if expires_in_days:
            expires_at = created_at + timedelta(days=expires_in_days)
        
        # Create metadata
        key_metadata = APIKeyMetadata(
            key_id=key_id,
            name=name,
            description=description,
            created_at=created_at,
            created_by=created_by,
            expires_at=expires_at,
            rate_limit_qps=rate_limit_qps,
            scopes=scopes or ["read", "write"],
            metadata=metadata or {}
        )
        
        # Store in Redis
        try:
            # Store hash -> key_id mapping
            hash_key = self.REDIS_HASH_KEY.format(hash=key_hash)
            await self.redis.client.set(hash_key, key_id)
            
            # Store metadata (with TTL if expires_at is set)
            metadata_key = self.REDIS_METADATA_KEY.format(key_id=key_id)
            metadata_json = key_metadata.model_dump_json()
            
            if expires_at:
                ttl_seconds = int((expires_at - created_at).total_seconds())
                await self.redis.client.setex(metadata_key, ttl_seconds, metadata_json)
            else:
                await self.redis.client.set(metadata_key, metadata_json)
            
            # Add to active keys set
            await self.redis.client.sadd(self.REDIS_ACTIVE_KEYS_SET, key_id)
            
            # Index by user if provided
            if created_by:
                user_index_key = self.REDIS_USER_INDEX_KEY.format(user_id=created_by)
                await self.redis.client.sadd(user_index_key, key_id)
            
            logger.info(f"✅ Created API key: {key_id} (name: {name})")
            return api_key, key_metadata
            
        except Exception as e:
            logger.error(f"❌ Failed to create API key: {str(e)}")
            raise
    
    async def validate_api_key(self, api_key: str) -> Optional[APIKeyMetadata]:
        """
        Validate an API key and return its metadata
        
        Also updates last_used_at timestamp and increments usage counter
        """
        try:
            # Hash the key
            key_hash = self.hash_api_key(api_key)
            hash_key = self.REDIS_HASH_KEY.format(hash=key_hash)
            
            # Look up key_id
            key_id = await self.redis.client.get(hash_key)
            if not key_id:
                return None
            
            # Get metadata
            metadata_key = self.REDIS_METADATA_KEY.format(key_id=key_id)
            metadata_json = await self.redis.client.get(metadata_key)
            
            if not metadata_json:
                return None
            
            metadata = APIKeyMetadata.model_validate_json(metadata_json)
            
            # Check if revoked
            if metadata.status == APIKeyStatus.REVOKED:
                return None
            
            # Check if expired
            if metadata.expires_at and datetime.utcnow() > metadata.expires_at:
                # Mark as expired
                metadata.status = APIKeyStatus.EXPIRED
                await self.redis.client.set(metadata_key, metadata.model_dump_json())
                return None
            
            # Update last used timestamp and increment counter
            metadata.last_used_at = datetime.utcnow()
            metadata.total_requests += 1
            
            # Save updated metadata (async, don't wait)
            await self.redis.client.set(metadata_key, metadata.model_dump_json())
            
            return metadata
            
        except Exception as e:
            logger.error(f"Error validating API key: {str(e)}")
            return None
    
    async def revoke_api_key(self, key_id: str) -> bool:
        """Revoke an API key"""
        try:
            metadata_key = self.REDIS_METADATA_KEY.format(key_id=key_id)
            metadata_json = await self.redis.client.get(metadata_key)
            
            if not metadata_json:
                return False
            
            metadata = APIKeyMetadata.model_validate_json(metadata_json)
            metadata.status = APIKeyStatus.REVOKED
            
            # Save updated metadata
            await self.redis.client.set(metadata_key, metadata.model_dump_json())
            
            # Remove from active keys set
            await self.redis.client.srem(self.REDIS_ACTIVE_KEYS_SET, key_id)
            
            logger.info(f"🔒 Revoked API key: {key_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to revoke API key: {str(e)}")
            return False
    
    async def delete_api_key(self, key_id: str) -> bool:
        """Permanently delete an API key"""
        try:
            metadata_key = self.REDIS_METADATA_KEY.format(key_id=key_id)
            metadata_json = await self.redis.client.get(metadata_key)
            
            if not metadata_json:
                return False
            
            metadata = APIKeyMetadata.model_validate_json(metadata_json)
            
            # Delete metadata
            await self.redis.client.delete(metadata_key)
            
            # Remove from active keys
            await self.redis.client.srem(self.REDIS_ACTIVE_KEYS_SET, key_id)
            
            # Remove from user index
            if metadata.created_by:
                user_index_key = self.REDIS_USER_INDEX_KEY.format(user_id=metadata.created_by)
                await self.redis.client.srem(user_index_key, key_id)
            
            logger.info(f"🗑️ Deleted API key: {key_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete API key: {str(e)}")
            return False
    
    async def get_key_metadata(self, key_id: str) -> Optional[APIKeyMetadata]:
        """Get metadata for a key by its ID"""
        try:
            metadata_key = self.REDIS_METADATA_KEY.format(key_id=key_id)
            metadata_json = await self.redis.client.get(metadata_key)
            
            if not metadata_json:
                return None
            
            return APIKeyMetadata.model_validate_json(metadata_json)
            
        except Exception as e:
            logger.error(f"Failed to get key metadata: {str(e)}")
            return None
    
    async def list_keys_by_user(self, user_id: str) -> List[APIKeyMetadata]:
        """List all API keys created by a user"""
        try:
            user_index_key = self.REDIS_USER_INDEX_KEY.format(user_id=user_id)
            key_ids = await self.redis.client.smembers(user_index_key)
            
            if not key_ids:
                return []
            
            # Fetch all metadata
            metadata_list = []
            for key_id in key_ids:
                metadata = await self.get_key_metadata(key_id)
                if metadata:
                    metadata_list.append(metadata)
            
            return metadata_list
            
        except Exception as e:
            logger.error(f"Failed to list keys by user: {str(e)}")
            return []
    
    async def list_all_active_keys(self) -> List[APIKeyMetadata]:
        """List all active API keys"""
        try:
            key_ids = await self.redis.client.smembers(self.REDIS_ACTIVE_KEYS_SET)
            
            if not key_ids:
                return []
            
            # Fetch all metadata
            metadata_list = []
            for key_id in key_ids:
                metadata = await self.get_key_metadata(key_id)
                if metadata and metadata.status == APIKeyStatus.ACTIVE:
                    metadata_list.append(metadata)
            
            return metadata_list
            
        except Exception as e:
            logger.error(f"Failed to list active keys: {str(e)}")
            return []
    
    async def update_key_metadata(
        self,
        key_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        rate_limit_qps: Optional[float] = None,
        scopes: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[APIKeyMetadata]:
        """Update API key metadata"""
        try:
            key_metadata = await self.get_key_metadata(key_id)
            
            if not key_metadata:
                return None
            
            # Update fields
            if name is not None:
                key_metadata.name = name
            if description is not None:
                key_metadata.description = description
            if rate_limit_qps is not None:
                key_metadata.rate_limit_qps = rate_limit_qps
            if scopes is not None:
                key_metadata.scopes = scopes
            if metadata is not None:
                key_metadata.metadata.update(metadata)
            
            # Save updated metadata
            metadata_key = self.REDIS_METADATA_KEY.format(key_id=key_id)
            await self.redis.client.set(metadata_key, key_metadata.model_dump_json())
            
            logger.info(f"📝 Updated API key metadata: {key_id}")
            return key_metadata
            
        except Exception as e:
            logger.error(f"Failed to update key metadata: {str(e)}")
            return None
    
    async def get_usage_stats(self) -> Dict[str, Any]:
        """Get overall API key usage statistics"""
        try:
            active_keys = await self.list_all_active_keys()
            
            total_keys = len(active_keys)
            total_requests = sum(k.total_requests for k in active_keys)
            
            # Calculate expiring soon (within 30 days)
            now = datetime.utcnow()
            expiring_soon = sum(
                1 for k in active_keys
                if k.expires_at and (k.expires_at - now).days <= 30
            )
            
            # Keys by user
            keys_by_user = {}
            for key in active_keys:
                if key.created_by:
                    keys_by_user[key.created_by] = keys_by_user.get(key.created_by, 0) + 1
            
            return {
                "total_active_keys": total_keys,
                "total_requests": total_requests,
                "expiring_soon": expiring_soon,
                "keys_by_user": keys_by_user,
                "average_requests_per_key": total_requests / total_keys if total_keys > 0 else 0
            }
            
        except Exception as e:
            logger.error(f"Failed to get usage stats: {str(e)}")
            return {}