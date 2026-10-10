"""Проверка живых воркеров по коротким heartbeat arq, без запуска моделей."""

from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_config
from app.db.models import Control, GPUSlot


async def processing_health(db=None):
    roles = ("scheduler", "cpu", "ml")
    redis = Redis.from_url(get_config().redis_url, socket_connect_timeout=1, socket_timeout=1)
    workers = dict.fromkeys(roles, False)
    connected = False
    try:
        values = await redis.mget([f"inventory:{role}:health-check" for role in roles])
        connected = True
        workers = dict(zip(roles, map(bool, values), strict=True))
    except Exception:
        pass
    finally:
        await redis.aclose()
    paused = []
    gpu_state = None
    if db is not None:
        paused = [
            row.key.removeprefix("queue:")
            for row in await db.scalars(select(Control))
            if row.key.startswith("queue:") and row.value.get("paused")
        ]
        slot = await db.get(GPUSlot, 1)
        gpu_state = slot.state if slot else "unavailable"
    saving = connected and workers["scheduler"] and workers["cpu"] and "cpu" not in paused
    return {
        "redis": connected,
        "workers": workers,
        "saving_available": saving,
        "recognition_available": saving
        and workers["ml"]
        and "default" not in paused
        and gpu_state not in {"quarantined", "unavailable"},
        "gpu_state": gpu_state,
        "queues_paused": paused,
    }
