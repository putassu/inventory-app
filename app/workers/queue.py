"""Redis сигнализирует о работе; восстановление всегда начинается с PostgreSQL."""

from datetime import timedelta

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import or_, select

from app.application.auth import aware
from app.application.proposals import apply_confirmation
from app.application.search import index_item
from app.application.settings import acknowledge_restart, effective_settings
from app.config import get_config
from app.db.models import Audit, Confirmation, Control, GPUSlot, Item, Job, Outbox, Proposal, Task
from app.db.session import session_factory
from app.domain.common import uid, utcnow
from app.domain.rules import transition
from app.infrastructure.logging import configure_logging, logged_job
from app.workers.pipeline import prepare_task, run_ml_stage


async def startup(ctx):
    configure_logging()
    ctx["factory"] = session_factory()
    async with ctx["factory"]() as db, db.begin():
        await acknowledge_restart(db, ctx.get("component", "cpu_worker"))


async def ml_startup(ctx):
    ctx["component"] = "ml_worker"
    await startup(ctx)


async def scheduler_startup(ctx):
    ctx["component"] = "scheduler"
    await startup(ctx)


@logged_job("confirmation_id")
async def apply_job(ctx, confirmation_id, fencing_token=1):
    try:
        return await apply_confirmation(ctx["factory"], confirmation_id, fencing_token)
    except Exception:
        async with ctx["factory"]() as db, db.begin():
            row = await db.get(Confirmation, confirmation_id, with_for_update=True)
            if row and row.status == "queued" and row.fencing_token == fencing_token:
                # Если commit успел пройти, статус applied уже сохранён и не изменится.
                row.status, row.error_code = "failed", "APPLY_FAILED"
                proposal = await db.get(Proposal, row.proposal_id)
                if proposal.task_id:
                    task = await db.get(Task, proposal.task_id)
                    transition(task, "failed", "apply_failed")


@logged_job("job_id")
async def outbox_job(ctx, event_id):
    factory = ctx["factory"]
    owner = uid()
    async with factory() as db, db.begin():
        event = await db.get(Outbox, event_id, with_for_update=True)
        if (
            not event
            or event.status in {"done", "dead_letter"}
            or event.lease_until
            and aware(event.lease_until) > utcnow()
        ):
            return
        event.lease_owner, event.lease_until = owner, utcnow() + timedelta(minutes=10)
        event.attempts += 1
        kind, entity_id, workspace_id, payload = (
            event.event_type,
            event.entity_id,
            event.workspace_id,
            event.payload,
        )
    try:
        done = True
        if kind == "apply_confirmation":
            await apply_job(ctx, entity_id, payload.get("fencing_token", 1))
        elif kind == "index_item":
            done = await index_item(factory, entity_id, workspace_id)
        elif kind == "plan_reminders":
            from app.application.notifications import plan_workspace

            await plan_workspace(factory, workspace_id)
        elif kind == "maintenance":
            from app.application.maintenance import run_job

            await run_job(factory, entity_id)
        else:
            raise ValueError("Неизвестный тип outbox")
        async with factory() as db, db.begin():
            event = await db.get(Outbox, event_id, with_for_update=True)
            if event.lease_owner == owner:
                event.lease_until = event.lease_owner = None
                if done:
                    event.status, event.processed_at = "done", utcnow()
                else:
                    event.attempts -= 1
                    event.next_attempt_at = utcnow() + timedelta(seconds=5)
    except Exception:
        async with factory() as db, db.begin():
            event = await db.get(Outbox, event_id, with_for_update=True)
            if event.lease_owner == owner:
                event.status = "dead_letter" if event.attempts >= 8 else "pending"
                event.error_code = "OUTBOX_DEPENDENCY_FAILED"
                if event.status == "dead_letter" and event.event_type == "maintenance":
                    job = await db.get(Job, event.entity_id)
                    if job and job.status in {"queued", "running"}:
                        job.status, job.result = "failed", {"error_code": "MAINTENANCE_FAILED"}
                event.lease_until = event.lease_owner = None
                event.next_attempt_at = utcnow() + timedelta(seconds=min(300, 2**event.attempts))


async def reconcile(ctx):
    factory = ctx["factory"]
    async with factory() as db, db.begin():
        _, settings = await effective_settings(db)
        controls = {row.key: row.value for row in (await db.scalars(select(Control))).all()}
        cpu_paused = controls.get("queue:cpu", {}).get("paused")
        maintenance_paused = controls.get("queue:maintenance", {}).get("paused")
        slot = await db.get(GPUSlot, 1, with_for_update=True)
        if slot and slot.state == "running" and slot.lease_until and aware(slot.lease_until) < utcnow():
            slot.state = "quarantined"
            db.add(
                Audit(
                    action="gpu.lease_expired",
                    details={"task_id": slot.task_id, "fencing_token": slot.fencing_token},
                )
            )
        tasks = (
            await db.scalars(
                select(Task)
                .where(Task.status.in_(["preparing", "running", "retry_wait"]))
                .with_for_update(skip_locked=True)
            )
        ).all()
        for task in tasks:
            if (
                task.status == "retry_wait"
                and task.next_attempt_at
                and aware(task.next_attempt_at) <= utcnow()
            ):
                transition(task, "queued")
            elif task.lease_until and aware(task.lease_until) < utcnow():
                task.fencing_token += 1
                task.lease_until = None
                if task.status == "preparing":
                    task.status, task.stage = "accepted", "upload_verified"
                    task.status_version += 1
                elif task.status == "running":
                    # После неизвестного физического состояния требуется recovery slot.
                    transition(task, "queued")
        # Восстанавливаем CPU-применение после потери Redis независимо от outbox ack.
        confirmations = (
            await db.scalars(select(Confirmation).where(Confirmation.status == "queued").limit(100))
        ).all()
        jobs = (
            []
            if cpu_paused
            else [
                ("apply_job", (c.id, c.fencing_token), f"confirm:{c.id}:{c.fencing_token}", "inventory:cpu")
                for c in confirmations
            ]
        )
        events = (
            await db.scalars(
                select(Outbox)
                .where(
                    Outbox.status == "pending",
                    Outbox.next_attempt_at <= utcnow(),
                    or_(Outbox.lease_until.is_(None), Outbox.lease_until < utcnow()),
                )
                .order_by(Outbox.created_at)
                .limit(30)
            )
        ).all()
        if not cpu_paused:
            jobs.extend(
                ("outbox_job", (e.id,), f"outbox:{e.id}:{e.attempts}", "inventory:cpu")
                for e in events
                if not maintenance_paused
                or e.event_type not in {"maintenance", "index_item", "plan_reminders"}
            )
        accepted = (
            await db.scalars(
                select(Task).where(Task.status == "accepted").order_by(Task.created_at).limit(10)
            )
        ).all()
        if not controls.get("queue:cpu", {}).get("paused"):
            jobs.extend(
                ("prepare_task", (t.id,), f"prepare:{t.id}:{t.status_version}", "inventory:cpu")
                for t in accepted
            )
        ready = (
            await db.scalars(
                select(Task)
                .where(Task.status == "queued")
                .order_by(Task.priority.desc(), Task.created_at)
                .limit(100)
            )
        ).all()
        # Взвешенный цикл хранится в PostgreSQL и не сбрасывается при потере Redis.
        cursor = await db.get(Control, "dispatch_cursor", with_for_update=True)
        if cursor is None:
            cursor = Control(key="dispatch_cursor", value={"position": 0})
            db.add(cursor)
        cycle = ["default"] * settings["queue.default_weight"] + ["bulk"] * settings["queue.bulk_weight"]
        preferred = cycle[cursor.value["position"] % len(cycle)]
        local = [
            t
            for t in ready
            if t.stage != "cloud_extraction" and not controls.get("queue:" + t.queue_class, {}).get("paused")
        ]
        if local and slot and slot.state == "idle":
            task = next((t for t in local if t.queue_class == preferred or t.priority > 0), local[0])
            jobs.append(("run_ml_stage", (task.id,), f"ml:{task.id}:{task.status_version}", "inventory:ml"))
            cursor.value = {"position": cursor.value["position"] + 1}
        if not controls.get("queue:cloud", {}).get("paused"):
            for task in [t for t in ready if t.stage == "cloud_extraction"][
                : settings["queue.cloud_concurrency"]
            ]:
                jobs.append(
                    ("run_ml_stage", (task.id,), f"cloud:{task.id}:{task.status_version}", "inventory:cloud")
                )
        # Индекс восстанавливается из ревизий даже при утрате отдельного события.
        behind = (
            await db.scalars(select(Item).where(Item.search_revision > Item.indexed_revision).limit(10))
        ).all()
        for item in behind:
            pending = await db.scalar(
                select(Outbox.id)
                .where(
                    Outbox.entity_id == item.id,
                    Outbox.event_type == "index_item",
                    Outbox.status.in_(["pending", "dead_letter"]),
                )
                .limit(1)
            )
            if not pending:
                db.add(
                    Outbox(
                        workspace_id=item.workspace_id,
                        event_type="index_item",
                        entity_id=item.id,
                        entity_version=item.search_revision,
                    )
                )
    for function, args, job_id, queue in jobs:
        await ctx["redis"].enqueue_job(function, *args, _job_id=job_id, _queue_name=queue)


async def periodic(ctx):
    from app.application.maintenance import regular_cleanup
    from app.application.notifications import plan_all

    async with ctx["factory"]() as db:
        control = await db.get(Control, "queue:maintenance")
        if control and control.value.get("paused"):
            return
    await plan_all(ctx["factory"])
    await regular_cleanup(ctx["factory"])


class CPUWorker:
    functions = [apply_job, prepare_task, outbox_job]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_config().redis_url)
    queue_name = "inventory:cpu"
    max_jobs = 2
    job_timeout = 1500
    keep_result = 0
    max_tries = 1


class MLWorker:
    functions = [run_ml_stage]
    on_startup = ml_startup
    redis_settings = RedisSettings.from_dsn(get_config().redis_url)
    queue_name = "inventory:ml"
    max_jobs = 1
    job_timeout = 1500
    keep_result = 0
    max_tries = 1


class CloudWorker(MLWorker):
    queue_name = "inventory:cloud"


class Scheduler:
    functions = []
    on_startup = scheduler_startup
    redis_settings = RedisSettings.from_dsn(get_config().redis_url)
    queue_name = "inventory:scheduler"
    cron_jobs = [
        cron(reconcile, second=set(range(0, 60, 3)), unique=True, run_at_startup=True),
        cron(periodic, minute=set(range(0, 60, 5)), second=1, unique=True, run_at_startup=True),
    ]
    max_jobs = 1
    job_timeout = 120
    keep_result = 0
