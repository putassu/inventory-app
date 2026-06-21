import os
import uuid
import asyncio
import datetime
import json
import httpx
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select, or_, and_, text
from arq import cron
from arq.connections import RedisSettings
import zoneinfo
from croniter import croniter

from backend.app.db.database import AsyncSessionLocal
from backend.app.db.models import (
    Task,
    TaskStatus,
    User,
    Item,
    ItemStatus,
    UserTier,
    Location
)
from backend.app.services.qdrant import delete_item_vector
from backend.app.services.settings_manager import SettingsManager
from backend.app.services.pipeline_graph import pipeline_graph
from config import settings, logger

# Ensure temp directory exists
TEMP_DIR = Path("data/tmp")
TEMP_DIR.mkdir(parents=True, exist_ok=True)


def get_redis_settings(url: str) -> RedisSettings:
    """Parse a Redis URL string into an arq RedisSettings instance."""
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    db = 0
    if parsed.path:
        try:
            db = int(parsed.path.lstrip("/"))
        except ValueError:
            pass
    password = parsed.password
    return RedisSettings(host=host, port=port, database=db, password=password)


async def decrement_active_tasks(redis, user_id):
    """Safely decrement user active tasks counter in Redis."""
    count = await redis.decr(f"inventory:active_tasks:{user_id}")
    if count < 0:
        await redis.set(f"inventory:active_tasks:{user_id}", 0)





async def run_stage1_pipeline(ctx, task_id_str: str, local_only: bool = False):
    """Worker job executing the LangGraph pipeline from start to end (or to safety interrupt)."""
    task_id = uuid.UUID(task_id_str)
    logger.info(f"Worker processing Stage 1 (LangGraph) for Task: {task_id}")
    
    async with AsyncSessionLocal() as session:
        stmt = select(Task).where(Task.id == task_id)
        res = await session.execute(stmt)
        task = res.scalar_one_or_none()
        if not task:
            logger.error(f"Task {task_id} not found in DB")
            return
            
        task.status = TaskStatus.PROCESSING
        task.updated_at = datetime.datetime.now(datetime.timezone.utc)
        await session.commit()
        await session.refresh(task)
        
        user_id = task.user_id
        raw_photos = task.photo_urls
        raw_audio = task.audio_url
        text_comment = task.transcription
        
    initial_state = {
        "task_id": str(task_id),
        "user_id": str(user_id),
        "local_only": local_only,
        "photo_urls": raw_photos,
        "audio_url": raw_audio,
        "transcription": text_comment or "",
        "opt_photos": [],
        "thumbnails": [],
        "collage_url": None,
        "is_safe": True,
        "suggested_json": {},
        "confidence_score": 1.0,
        "corrected_json": None,
        "error": None
    }
    
    config = {"configurable": {"thread_id": str(task_id)}}
    active_tasks_decremented = False
    
    execution_times = {}
    debug_logs = [f"Starting pipeline for task {task_id}"]
    
    import time
    start_time = time.time()
    
    try:
        # Run graph execution
        async for event in pipeline_graph.astream(initial_state, config):
            for node_name, state_update in event.items():
                elapsed = time.time() - start_time
                execution_times[node_name] = elapsed
                start_time = time.time()
                debug_logs.append(f"Node {node_name} completed in {elapsed:.2f}s")
                
                # Update DB continuously with logs
                async with AsyncSessionLocal() as session:
                    stmt = select(Task).where(Task.id == task_id)
                    res = await session.execute(stmt)
                    db_task = res.scalar_one_or_none()
                    if db_task:
                        db_task.execution_times = execution_times
                        db_task.debug_logs = debug_logs
                        await session.commit()
            
        # Check if the graph got paused/interrupted at hitl_node
        state_snapshot = await pipeline_graph.aget_state(config)
        if state_snapshot.next and "hitl_node" in state_snapshot.next:
            # Human intervention needed, update postgres task record
            async with AsyncSessionLocal() as session:
                stmt = select(Task).where(Task.id == task_id)
                res = await session.execute(stmt)
                db_task = res.scalar_one()
                db_task.status = TaskStatus.USER_ACTION_REQUIRED
                db_task.execution_times = execution_times
                db_task.debug_logs = debug_logs
                await session.commit()
            
            logger.warning(f"Task {task_id} requires human resolution. Pausing.")
            await decrement_active_tasks(ctx['redis'], user_id)
            active_tasks_decremented = True
        else:
            # Graph finished without interruption
            logger.info(f"Task {task_id} completed Stage 1 automatically without HITL.")
            
    except (Exception, asyncio.CancelledError) as e:
        logger.exception(f"Error executing Stage 1 (LangGraph) for task {task_id_str}")
        debug_logs.append(f"ERROR: {str(e) or 'Task cancelled/timed out'}")
        async with AsyncSessionLocal() as session:
            stmt = select(Task).where(Task.id == task_id)
            res = await session.execute(stmt)
            db_task = res.scalar_one_or_none()
            if db_task:
                db_task.status = TaskStatus.FAILED
                db_task.error_message = str(e)
                db_task.execution_times = execution_times
                db_task.debug_logs = debug_logs
                db_task.updated_at = datetime.datetime.now(datetime.timezone.utc)
                await session.commit()
        await decrement_active_tasks(ctx['redis'], user_id)
        active_tasks_decremented = True
    finally:
        if not active_tasks_decremented:
            await decrement_active_tasks(ctx['redis'], user_id)


async def run_stage2_pipeline(ctx, task_id_str: str):
    """Worker job resuming the LangGraph pipeline from safety interrupt review_node."""
    task_id = uuid.UUID(task_id_str)
    logger.info(f"Worker processing Stage 2 Resolution (LangGraph) for Task: {task_id}")
    
    config = {"configurable": {"thread_id": str(task_id)}}
    
    async with AsyncSessionLocal() as session:
        stmt = select(Task).where(Task.id == task_id)
        res = await session.execute(stmt)
        db_task = res.scalar_one_or_none()
        if not db_task:
            logger.error(f"Task {task_id} not found in DB")
            return
            
        db_task.status = TaskStatus.PROCESSING
        db_task.updated_at = datetime.datetime.now(datetime.timezone.utc)
        await session.commit()
        await session.refresh(db_task)
        
        user_id = db_task.user_id
        corrected_json = db_task.suggested_json
        
    active_tasks_decremented = False
    
    execution_times = db_task.execution_times or {}
    debug_logs = db_task.debug_logs or []
    debug_logs.append(f"Resuming pipeline for task {task_id}")
    
    import time
    start_time = time.time()
    
    try:
        # Retrieve snapshot state to make sure task is paused at hitl_node
        state_snapshot = await pipeline_graph.aget_state(config)
        if not state_snapshot or not state_snapshot.next or "hitl_node" not in state_snapshot.next:
            # Bootstrap state in checkpointer from DB Task record
            logger.info(f"LangGraph: Paused state not found for thread {task_id}. Bootstrapping state from DB.")
            await pipeline_graph.aupdate_state(
                config,
                {
                    "task_id": str(task_id),
                    "user_id": str(user_id),
                    "local_only": False,
                    "photo_urls": db_task.photo_urls,
                    "audio_url": db_task.audio_url,
                    "transcription": db_task.transcription or "",
                    "opt_photos": db_task.photo_urls,
                    "thumbnails": db_task.suggested_json.get("thumb_urls") or [],
                    "collage_url": db_task.suggested_json.get("collage_url"),
                    "is_safe": db_task.is_safe if db_task.is_safe is not None else True,
                    "suggested_json": corrected_json,
                    "confidence_score": float(db_task.confidence_score) if db_task.confidence_score else 1.0,
                    "corrected_json": corrected_json,
                    "error": None
                },
                as_node="hitl_node"
            )
        else:
            # Update the existing graph state with user corrections
            await pipeline_graph.aupdate_state(
                config,
                {"corrected_json": corrected_json},
                as_node="hitl_node"
            )
        
        # Resume the graph
        async for event in pipeline_graph.astream(None, config):
            for node_name, state_update in event.items():
                elapsed = time.time() - start_time
                execution_times[node_name] = elapsed
                start_time = time.time()
                debug_logs.append(f"Node {node_name} completed in {elapsed:.2f}s")
                
                async with AsyncSessionLocal() as session:
                    stmt = select(Task).where(Task.id == task_id)
                    res = await session.execute(stmt)
                    db_task_update = res.scalar_one_or_none()
                    if db_task_update:
                        db_task_update.execution_times = execution_times
                        db_task_update.debug_logs = debug_logs
                        await session.commit()
            
    except (Exception, asyncio.CancelledError) as e:
        logger.exception(f"Failed executing resolved Stage 2 (LangGraph) for task {task_id_str}")
        debug_logs.append(f"ERROR: {str(e) or 'Task cancelled/timed out'}")
        async with AsyncSessionLocal() as session:
            stmt = select(Task).where(Task.id == task_id)
            res = await session.execute(stmt)
            db_task = res.scalar_one_or_none()
            if db_task:
                db_task.status = TaskStatus.FAILED
                db_task.error_message = str(e)
                db_task.execution_times = execution_times
                db_task.debug_logs = debug_logs
                db_task.updated_at = datetime.datetime.now(datetime.timezone.utc)
                await session.commit()
        await decrement_active_tasks(ctx['redis'], user_id)
        active_tasks_decremented = True
    finally:
        if not active_tasks_decremented:
            await decrement_active_tasks(ctx['redis'], user_id)


# ==========================================
# CRON SCHEDULER JOBS
# ==========================================

async def flush_llm_quotas(ctx):
    """Daily scheduler: clear LiteLLM quarantine/cooldown keys from Redis at 07:05 UTC (10:05 MSK)."""
    logger.info("Scheduler: Flushing LLM quota cooldown keys in Redis")
    redis = ctx['redis']
    cursor = 0
    keys_deleted = 0
    while True:
        cursor, keys = await redis.scan(cursor=cursor, match="*cooldown*", count=100)
        if keys:
            # arq redis connections expect list/iterable of keys to delete
            await redis.delete(*keys)
            keys_deleted += len(keys)
        if cursor == 0:
            break
    logger.info(f"Scheduler: Successfully flushed {keys_deleted} cooldown keys from Redis.")


async def check_expired_subscriptions(ctx):
    """Daily scheduler: downgrade expired premium subscriptions and invalidate LiteLLM keys."""
    logger.info("Scheduler: Checking for expired subscriptions...")
    now = datetime.datetime.now(datetime.timezone.utc)
    
    async with AsyncSessionLocal() as session:
        # Select users whose tier has expired or LiteLLM key has expired
        stmt = select(User).where(
            User.tier != UserTier.FREE,
            User.tier_expired_at < now
        )
        res = await session.execute(stmt)
        expired_users = res.scalars().all()
        
        for user in expired_users:
            old_key = user.litellm_api_key
            user.tier = UserTier.FREE
            user.litellm_api_key = f"sk-litellm-free-{uuid.uuid4().hex[:8]}"
            user.tier_expired_at = None
            user.litellm_key_expired_at = None
            user.updated_at = now
            logger.info(f"Scheduler: Downgrading user {user.id} ({user.email}) to FREE tier due to expiration.")
            
            # Invalidate old LiteLLM key on the LiteLLM gateway Admin API
            if old_key:
                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(
                            f"{settings.LITELLM_API_BASE}/key/delete",
                            headers={"Authorization": f"Bearer {settings.LITELLM_API_KEY}"},
                            json={"key": old_key},
                            timeout=2.0
                        )
                        logger.info(f"Scheduler: Invalidation request for key {old_key} returned status {resp.status_code}")
                except Exception as e:
                    logger.warning(f"Scheduler: Could not block/delete key {old_key} from LiteLLM gateway: {e}")
                    
        await session.commit()


async def check_item_expirations(ctx):
    """Daily scheduler: check completed items shelf-life percentage and compile alert notifications (p80, p95, p99)."""
    logger.info("Scheduler: Scanning items for expiration warning alerts (p80/p95/p99)...")
    redis = ctx['redis']
    now = datetime.datetime.now(datetime.timezone.utc)
    
    async with AsyncSessionLocal() as session:
        stmt = select(User)
        res = await session.execute(stmt)
        users = {u.id: u.settings for u in res.scalars().all()}
        
        stmt = select(Location)
        res = await session.execute(stmt)
        locations = {l.id: l.attributes for l in res.scalars().all()}
        
        stmt = select(Item).where(Item.archived_at.is_(None))
        res = await session.execute(stmt)
        items = res.scalars().all()
        
        for item in items:
            expiry_str = item.attributes.get("expiry_date")
            if not expiry_str:
                continue
            try:
                # Expected format: YYYY-MM-DD
                expiry_date = datetime.datetime.strptime(expiry_str, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
            except ValueError:
                continue
                
            # Check if already expired
            if now > expiry_date:
                sent_key = f"inventory:alert_expired_sent:{item.id}:{now.strftime('%Y-%m-%d')}"
                already_sent = await redis.get(sent_key)
                if not already_sent:
                    msg = f"Alert EXPIRED: Item '{item.generated_desc.split('.')[0]}' is expired!"
                    logger.warning(msg)
                    alert_payload = {
                        "item_id": str(item.id),
                        "item_name": item.generated_desc.split(".")[0],
                        "alert_type": "expired",
                        "timestamp": now.isoformat()
                    }
                    await redis.lpush(f"inventory:alerts:{item.user_id}", json.dumps(alert_payload))
                    await redis.set(sent_key, "1", ex=86400 * 2)
                continue
                
            created_at = item.created_at
            total_duration = (expiry_date - created_at).total_seconds()
            if total_duration <= 0:
                continue
                
            elapsed_duration = (now - created_at).total_seconds()
            if elapsed_duration < 0:
                continue
                
            ratio = elapsed_duration / total_duration
            
            # Cascade settings resolution for percentiles
            percentiles = [0.8, 0.95, 0.99]
            if item.attributes.get("expiry_reminder_percentiles"):
                percentiles = item.attributes.get("expiry_reminder_percentiles")
            elif item.location_id and locations.get(item.location_id, {}).get("expiry_reminder_percentiles"):
                percentiles = locations[item.location_id].get("expiry_reminder_percentiles")
            elif users.get(item.user_id, {}).get("expiry_reminder_percentiles"):
                percentiles = users[item.user_id].get("expiry_reminder_percentiles")
            
            alert_type = None
            if ratio >= percentiles[2]:
                alert_type = "p99"
            elif ratio >= percentiles[1]:
                alert_type = "p95"
            elif ratio >= percentiles[0]:
                alert_type = "p80"
                
            if alert_type:
                sent_key = f"inventory:alert_sent:{item.id}:{alert_type}"
                already_sent = await redis.get(sent_key)
                if not already_sent:
                    msg = f"Alert {alert_type}: Item '{item.generated_desc.split('.')[0]}' shelf-life is at {ratio*100:.1f}% elapsed."
                    logger.warning(msg)
                    
                    alert_payload = {
                        "item_id": str(item.id),
                        "item_name": item.generated_desc.split(".")[0],
                        "alert_type": alert_type,
                        "ratio": ratio,
                        "timestamp": now.isoformat()
                    }
                    # Save notification alert to Redis list
                    await redis.lpush(f"inventory:alerts:{item.user_id}", json.dumps(alert_payload))
                    # Prevent duplicate triggers
                    await redis.set(sent_key, "1", ex=86400 * 30)

async def check_audits(ctx):
    """Daily scheduler: remind users to audit items that haven't been moved/checked recently."""
    logger.info("Scheduler: Scanning items for audit reminders...")
    redis = ctx['redis']
    now = datetime.datetime.now(datetime.timezone.utc)
    
    async with AsyncSessionLocal() as session:
        stmt = select(User)
        res = await session.execute(stmt)
        users = {u.id: u.settings for u in res.scalars().all()}
        
        stmt = select(Item).where(Item.archived_at.is_(None))
        res = await session.execute(stmt)
        items = res.scalars().all()
        
        for item in items:
            user_settings = users.get(item.user_id) or {}
            audit_days = user_settings.get("audit_reminder_days", 30)
            min_moves = user_settings.get("audit_min_moves", 0)
            audit_locs = user_settings.get("audit_locations", [])
            
            if item.moves_count < min_moves:
                continue
                
            if audit_locs and str(item.location_id) not in audit_locs:
                continue
                
            idle_days = (now - item.updated_at).total_seconds() / 86400.0
            if idle_days >= audit_days:
                # Need to remind
                sent_key = f"inventory:alert_audit_sent:{item.id}:{now.strftime('%Y-%m')}" # Monthly reminder
                already_sent = await redis.get(sent_key)
                if not already_sent:
                    msg = f"Alert AUDIT: Please check if '{item.generated_desc.split('.')[0]}' is still there."
                    logger.warning(msg)
                    alert_payload = {
                        "item_id": str(item.id),
                        "item_name": item.generated_desc.split(".")[0],
                        "alert_type": "audit",
                        "timestamp": now.isoformat()
                    }
                    await redis.lpush(f"inventory:alerts:{item.user_id}", json.dumps(alert_payload))
                    await redis.set(sent_key, "1", ex=86400 * 28)


async def cleanup_garbage_items(ctx):
    """Weekly scheduler: cleanup items in status 'depleted' or with non-null archived_at older than settings.GARBAGE_TTL_SECONDS."""
    logger.info("Scheduler: Running weekly Garbage Collector...")
    now = datetime.datetime.now(datetime.timezone.utc)
    garbage_ttl = await SettingsManager.get("garbage_ttl_seconds", settings.GARBAGE_TTL_SECONDS)
    cutoff = now - datetime.timedelta(seconds=garbage_ttl)
    logger.info(f"Scheduler: Deleting garbaged items older than {cutoff}")
    
    async with AsyncSessionLocal() as session:
        # Select items that are either:
        # 1. status = ItemStatus.DEPLETED and updated_at < cutoff
        # 2. archived_at is not null and archived_at < cutoff
        stmt = select(Item).where(
            or_(
                and_(Item.status == ItemStatus.DEPLETED, Item.updated_at < cutoff),
                and_(Item.archived_at.is_not(None), Item.archived_at < cutoff)
            )
        )
        res = await session.execute(stmt)
        items_to_delete = res.scalars().all()
        
        deleted_count = 0
        for item in items_to_delete:
            item_id_str = str(item.id)
            try:
                await delete_item_vector(item_id_str)
            except Exception as ex:
                logger.error(f"GC: Failed to delete Qdrant vector for item {item_id_str}: {ex}")
            
            await session.delete(item)
            deleted_count += 1
            
        await session.commit()
        logger.info(f"Scheduler: Garbage Collector deleted {deleted_count} items.")


async def check_reminders(ctx):
    """Hourly scheduler: evaluate remind_at and cron_schedule attributes for items."""
    logger.info("Scheduler: Scanning items for hourly reminders and cron jobs...")
    redis = ctx['redis']
    now = datetime.datetime.now(datetime.timezone.utc)
    
    async with AsyncSessionLocal() as session:
        stmt = select(User)
        res = await session.execute(stmt)
        users = {u.id: u.settings for u in res.scalars().all()}
        
        stmt = select(Item).where(Item.archived_at.is_(None))
        res = await session.execute(stmt)
        items = res.scalars().all()
        
        for item in items:
            attrs = item.attributes or {}
            remind_at_str = attrs.get("remind_at")
            cron_expr = attrs.get("cron_schedule")
            
            if not remind_at_str and not cron_expr:
                continue
                
            user_settings = users.get(item.user_id) or {}
            tz_name = user_settings.get("timezone", "UTC")
            try:
                user_tz = zoneinfo.ZoneInfo(tz_name)
            except Exception:
                user_tz = zoneinfo.ZoneInfo("UTC")
                
            now_local = now.astimezone(user_tz)
            trigger_alert = False
            
            if remind_at_str:
                try:
                    remind_time = datetime.datetime.fromisoformat(remind_at_str)
                    if now >= remind_time:
                        trigger_alert = True
                        attrs.pop("remind_at", None)
                        item.attributes = attrs.copy()
                except ValueError:
                    pass
                    
            elif cron_expr:
                try:
                    end_of_hour = now_local.replace(minute=59, second=59)
                    cron_it = croniter(cron_expr, end_of_hour)
                    prev_trigger = cron_it.get_prev(datetime.datetime)
                    
                    if prev_trigger.hour == now_local.hour and prev_trigger.date() == now_local.date():
                        sent_key = f"inventory:alert_cron_sent:{item.id}:{now_local.strftime('%Y-%m-%d-%H')}"
                        already_sent = await redis.get(sent_key)
                        if not already_sent:
                            trigger_alert = True
                            await redis.set(sent_key, "1", ex=7200)
                except Exception as e:
                    logger.error(f"Failed to parse cron_expr '{cron_expr}' for item {item.id}: {e}")
                    
            if trigger_alert:
                msg = f"Alert SCHEDULED REMINDER: Item '{item.generated_desc.split('.')[0]}'."
                logger.info(msg)
                alert_payload = {
                    "item_id": str(item.id),
                    "item_name": item.generated_desc.split(".")[0],
                    "alert_type": "reminder",
                    "timestamp": now.isoformat()
                }
                await redis.lpush(f"inventory:alerts:{item.user_id}", json.dumps(alert_payload))
                
        await session.commit()


async def cleanup_orphan_tasks(ctx):
    """Hourly scheduler: marks tasks that have been PROCESSING for > 2 hours as FAILED."""
    logger.info("Scheduler: Cleaning up orphan tasks...")
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(hours=2)
    
    async with AsyncSessionLocal() as session:
        stmt = select(Task).where(
            Task.status == TaskStatus.PROCESSING,
            Task.updated_at < cutoff
        )
        res = await session.execute(stmt)
        orphans = res.scalars().all()
        
        for task in orphans:
            task.status = TaskStatus.FAILED
            task.error_message = "Task timed out or worker crashed (Orphan cleanup)"
            task.updated_at = now
            logger.warning(f"Marked orphan task {task.id} as FAILED")
            
        await session.commit()

# ==========================================
# ARQ WORKER CONFIGURATION
# ==========================================

class WorkerSettings:
    """arq Worker settings for job routing and cron jobs mapping."""
    queue_name = os.getenv("ARQ_QUEUE_NAME", "default")
    job_timeout = 900
    functions = [run_stage1_pipeline, run_stage2_pipeline, cleanup_garbage_items, check_item_expirations, check_audits, check_reminders, cleanup_orphan_tasks]
    _cron_jobs_list = [
        # Reset quotas daily at 10:05 MSK / 07:05 UTC
        cron(flush_llm_quotas, hour=7, minute=5, unique=True),
        # Check expired subscriptions daily at 00:00 UTC
        cron(check_expired_subscriptions, hour=0, minute=0, unique=True),
        # Scan item shelf-life expirations daily at 01:00 UTC
        cron(check_item_expirations, hour=1, minute=0, unique=True),
        # Scan audits daily at 01:30 UTC
        cron(check_audits, hour=1, minute=30, unique=True),
        # Weekly Garbage Collector on Sunday at 02:00 UTC
        cron(cleanup_garbage_items, weekday=6, hour=2, minute=0, unique=True),
        # Hourly schedule checks
        cron(check_reminders, minute=0, unique=True),
        # Hourly orphan tasks cleanup
        cron(cleanup_orphan_tasks, minute=5, unique=True),
    ]
    
    cron_jobs = _cron_jobs_list if os.getenv("ARQ_ENABLE_CRON", "false").lower() == "true" else []
    # Set Redis settings dynamically
    redis_settings = get_redis_settings(settings.REDIS_URL)
