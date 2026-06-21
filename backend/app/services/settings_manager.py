import json
import redis.asyncio as aioredis
from typing import Any, Dict, Optional
from sqlalchemy import select
from config import settings
from backend.app.api.deps import get_db_session
from backend.app.db.models import SystemSetting

class SettingsManager:
    """Manages dynamic system settings with Redis caching and PostgreSQL persistence."""
    
    _redis_client: Optional[aioredis.Redis] = None
    _cache_prefix = "inventory:settings:"
    
    # Defaults in case DB is uninitialized
    _defaults = {
        "min_confidence_score": settings.MIN_CONFIDENCE_SCORE,
        "max_tasks_per_user": settings.MAX_TASKS_PER_USER,
        "langgraph_node_retries": settings.LANGGRAPH_NODE_RETRIES,
        "garbage_ttl_seconds": settings.GARBAGE_TTL_SECONDS,
        "cloud_gemma_model_name": settings.CLOUD_GEMMA_MODEL_NAME,
        "local_model_name": settings.LOCAL_MODEL_NAME,
        "small_local_model_name": settings.SMALL_LOCAL_MODEL_NAME,
        "gemini_model_name": settings.GEMINI_MODEL_NAME,
        "asr_model_name": "whisper-1",
        "ocr_model_name": "google/vit-base-patch16-224",
    }
    
    @classmethod
    def get_redis(cls) -> aioredis.Redis:
        if cls._redis_client is None:
            cls._redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return cls._redis_client

    @classmethod
    async def get(cls, key: str, default: Any = None) -> Any:
        """Get a setting by key, trying Redis -> DB -> Default fallback."""
        r = cls.get_redis()
        cache_key = f"{cls._cache_prefix}{key}"
        
        # 1. Try Redis cache
        cached_val = await r.get(cache_key)
        if cached_val is not None:
            return json.loads(cached_val)
            
        # 2. Try Database
        async for db in get_db_session():
            stmt = select(SystemSetting).where(SystemSetting.key == key)
            result = await db.execute(stmt)
            db_setting = result.scalar_one_or_none()
            
            if db_setting is not None:
                val = db_setting.value
                # Cache for 1 hour to prevent DB spam (admin overrides clear cache instantly)
                await r.set(cache_key, json.dumps(val), ex=3600)
                return val
            break
            
        # 3. Try hardcoded default
        if key in cls._defaults:
            val = cls._defaults[key]
            await r.set(cache_key, json.dumps(val), ex=3600)
            return val
            
        return default

    @classmethod
    async def set(cls, key: str, value: Any, description: Optional[str] = None) -> SystemSetting:
        """Set a setting in DB and invalidate Redis cache."""
        async for db in get_db_session():
            stmt = select(SystemSetting).where(SystemSetting.key == key)
            result = await db.execute(stmt)
            db_setting = result.scalar_one_or_none()
            
            if db_setting:
                db_setting.value = value
                if description is not None:
                    db_setting.description = description
            else:
                db_setting = SystemSetting(key=key, value=value, description=description)
                db.add(db_setting)
                
            await db.commit()
            await db.refresh(db_setting)
            
            # Invalidate/Update Cache immediately
            r = cls.get_redis()
            cache_key = f"{cls._cache_prefix}{key}"
            await r.set(cache_key, json.dumps(value), ex=3600)
            
            return db_setting
        
        raise RuntimeError("Could not connect to Database")

    @classmethod
    async def delete(cls, key: str):
        """Delete a setting from DB and cache."""
        async for db in get_db_session():
            stmt = select(SystemSetting).where(SystemSetting.key == key)
            result = await db.execute(stmt)
            db_setting = result.scalar_one_or_none()
            
            if db_setting:
                await db.delete(db_setting)
                await db.commit()
            
            r = cls.get_redis()
            cache_key = f"{cls._cache_prefix}{key}"
            await r.delete(cache_key)
            break

    @classmethod
    async def get_all(cls) -> Dict[str, Any]:
        """Get all settings from DB."""
        settings_dict = {}
        async for db in get_db_session():
            stmt = select(SystemSetting)
            result = await db.execute(stmt)
            for s in result.scalars().all():
                settings_dict[s.key] = s.value
            break
        return settings_dict
