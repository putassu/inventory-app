import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import timedelta

from app.db.models import GPUSlot
from app.domain.common import uid, utcnow
from app.infrastructure.models import ModelError


async def reserve(factory, task_id=None, lease_seconds=60):
    async with factory() as db, db.begin():
        slot = await db.get(GPUSlot, 1, with_for_update=True)
        if slot is None or slot.state != "idle":
            return None
        slot.owner, slot.task_id = uid(), task_id
        slot.fencing_token += 1
        slot.state = "running"
        slot.heartbeat_at = utcnow()
        slot.lease_until = utcnow() + timedelta(seconds=lease_seconds)
        return slot.owner, slot.fencing_token


async def renew(factory, owner, token, lease_seconds=60):
    async with factory() as db, db.begin():
        slot = await db.get(GPUSlot, 1, with_for_update=True)
        if slot.owner == owner and slot.fencing_token == token and slot.state == "running":
            slot.heartbeat_at = utcnow()
            slot.lease_until = utcnow() + timedelta(seconds=lease_seconds)
            return True
        return False


async def release(factory, owner, token, uncertain=False):
    async with factory() as db, db.begin():
        slot = await db.get(GPUSlot, 1, with_for_update=True)
        if slot.owner == owner and slot.fencing_token == token:
            slot.state = "quarantined" if uncertain else "idle"
            if not uncertain:
                slot.owner = slot.task_id = slot.lease_until = None


@asynccontextmanager
async def gpu_session(factory, task_id=None, settings=None):
    settings = settings or {}
    lease = settings.get("timeout.lease_seconds", 60)
    reserved = await reserve(factory, task_id, lease)
    if reserved is None:
        yield None
        return
    owner, token = reserved

    async def heartbeat():
        while True:
            await asyncio.sleep(settings.get("timeout.heartbeat_seconds", 10))
            if not await renew(factory, owner, token, lease):
                return

    heartbeat_task = asyncio.create_task(heartbeat())
    uncertain = False
    try:
        yield reserved
    except BaseException as error:
        uncertain = (
            isinstance(error, asyncio.CancelledError)
            or isinstance(error, ModelError)
            and error.physical_unknown
        )
        raise
    finally:
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task
        await asyncio.shield(release(factory, owner, token, uncertain))
