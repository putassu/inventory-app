from datetime import timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from sqlalchemy import func, select

from app.api.catalog import page, serialize
from app.api.deps import admin_user, current_user, database, idempotency_key, scope, write_scope
from app.application.idempotency import previous_response, remember
from app.application.settings import apply_settings, effective_settings, settings_view, validate_change
from app.config import get_config
from app.db.models import (
    Attempt,
    Audit,
    Control,
    GPUSlot,
    Item,
    Job,
    Media,
    ModelDeployment,
    Outbox,
    SettingsRevision,
    Task,
    User,
)
from app.db.session import scoped_get
from app.domain.common import digest, uid, utcnow
from app.domain.errors import require
from app.domain.schemas import StrictModel
from app.infrastructure.models import LocalAdapter
from app.settings.registry import USER_REGISTRY, defaults, schema, validate_values

router = APIRouter()


class SettingChange(StrictModel):
    key: str
    value: object


class SettingsPatch(StrictModel):
    expected_revision: int = Field(ge=1)
    changes: list[SettingChange] = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=500)
    impact_confirmed: bool = False


@router.get("/admin/settings/schema")
async def admin_schema(user=Depends(admin_user)):
    return {"schema_version": "settings.v1", "fields": schema()}


@router.get("/admin/settings")
async def admin_settings(user=Depends(admin_user), db=Depends(database)):
    return await settings_view(db)


@router.post("/admin/settings/validate")
async def validate(data: SettingsPatch, user=Depends(admin_user), db=Depends(database)):
    result = await validate_change(db, data.expected_revision, [c.model_dump() for c in data.changes])
    if result["retention_reduced"]:
        from app.application.maintenance import retention_impact

        _, current = await effective_settings(db)
        result["impact"] = await retention_impact(db, current, result["values"])
    return result


@router.patch("/admin/settings")
async def change_settings(
    data: SettingsPatch, key=Depends(idempotency_key), user=Depends(admin_user), db=Depends(database)
):
    await db.get(Control, "settings", with_for_update=True)
    body = data.model_dump(mode="json")
    cached = await previous_response(db, user.id, "admin", "settings", key, body)
    if cached:
        return cached
    result = await apply_settings(
        db, user.id, data.expected_revision, body["changes"], data.reason, data.impact_confirmed
    )
    return remember(db, user.id, "admin", "settings", key, body, result)


@router.get("/admin/settings/history")
async def settings_history(user=Depends(admin_user), db=Depends(database)):
    rows = (
        await db.scalars(select(SettingsRevision).order_by(SettingsRevision.revision.desc()).limit(100))
    ).all()
    return {"items": [serialize(r) for r in rows]}


class Rollback(StrictModel):
    expected_revision: int = Field(ge=1)
    target_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


@router.post("/admin/settings/rollback")
async def rollback(
    data: Rollback, key=Depends(idempotency_key), user=Depends(admin_user), db=Depends(database)
):
    await db.get(Control, "settings", with_for_update=True)
    body = data.model_dump()
    cached = await previous_response(db, user.id, "admin", "rollback", key, body)
    if cached:
        return cached
    previous = await db.scalar(
        select(SettingsRevision).where(SettingsRevision.revision == data.target_revision)
    )
    require(previous, "NOT_FOUND", "Ревизия не найдена.", 404)
    result = await apply_settings(
        db,
        user.id,
        data.expected_revision,
        [{"key": key, "value": value} for key, value in previous.values.items()],
        data.reason,
    )
    return remember(db, user.id, "admin", "rollback", key, body, result)


@router.get("/settings/schema")
async def user_schema(user=Depends(current_user)):
    return {"schema_version": "preferences.v1", "fields": schema(USER_REGISTRY)}


@router.get("/settings")
async def user_settings(user=Depends(current_user)):
    return {"version": user.preferences_version, "values": {**defaults(USER_REGISTRY), **user.preferences}}


class Preferences(StrictModel):
    expected_version: int = Field(ge=1)
    changes: list[SettingChange] = Field(max_length=10)


@router.patch("/settings")
async def save_preferences(data: Preferences, user=Depends(current_user), db=Depends(database)):
    user = await db.get(User, user.id, with_for_update=True, populate_existing=True)
    require(
        user.preferences_version == data.expected_version, "VERSION_CONFLICT", "Настройки уже изменились."
    )
    values = {**defaults(USER_REGISTRY), **user.preferences, **{c.key: c.value for c in data.changes}}
    user.preferences = validate_values(values, USER_REGISTRY)
    user.preferences_version += 1
    return await user_settings(user)


@router.get("/admin/models")
async def models(user=Depends(admin_user), db=Depends(database)):
    return {
        "items": [
            serialize(m)
            for m in (await db.scalars(select(ModelDeployment).order_by(ModelDeployment.logical_name))).all()
        ]
    }


class ModelPatch(StrictModel):
    expected_version: int = Field(ge=1)
    enabled: bool | None = None
    maintenance: bool | None = None


@router.patch("/admin/models/{model_id}")
async def update_model(model_id: UUID, data: ModelPatch, user=Depends(admin_user), db=Depends(database)):
    row = await db.get(ModelDeployment, str(model_id), with_for_update=True)
    require(row, "NOT_FOUND", "Deployment не найден.", 404)
    require(row.version == data.expected_version, "VERSION_CONFLICT", "Deployment уже изменён.")
    if data.enabled:
        require(
            row.checked_at and row.capabilities.get("verified_connection"),
            "CAPABILITY_CHECK_REQUIRED",
            "Сначала проверьте deployment.",
        )
    for key, value in data.model_dump(exclude_unset=True).items():
        if key != "expected_version":
            setattr(row, key, value)
    row.version += 1
    db.add(Audit(actor_id=user.id, action="model.update", details={"model_id": row.id, **data.model_dump()}))
    return serialize(row)


@router.post("/admin/models/{model_id}/health-check")
async def model_health(
    model_id: UUID,
    request: Request,
    key=Depends(idempotency_key),
    user=Depends(admin_user),
    db=Depends(database),
):
    row = await db.get(ModelDeployment, str(model_id))
    require(row, "NOT_FOUND", "Deployment не найден.", 404)
    model, endpoint, trust, version = row.actual_model_id, row.endpoint_ref, row.trust_domain, row.version
    user_id = user.id
    await db.commit()
    if endpoint == "local_audio":
        import io
        import wave

        from app.infrastructure.audio import LocalAudioAdapter
        from app.infrastructure.gpu import gpu_session

        output = io.BytesIO()
        with wave.open(output, "wb") as silence:
            silence.setnchannels(1)
            silence.setsampwidth(2)
            silence.setframerate(16000)
            silence.writeframes(b"\x00\x00" * 16000)
        async with gpu_session(request.app.state.session_factory) as slot:
            require(slot is not None, "GPU_BUSY", "Дождитесь завершения текущей обработки.", 409)
            await LocalAudioAdapter().infer(output.getvalue(), 60, model=model)
        capabilities = {
            "verified_connection": True,
            "modalities": ["text", "audio"],
            "supports_audio": True,
            "supports_combined_audio_image": False,
        }
    elif trust == "local":
        capabilities = await LocalAdapter().capabilities(model)
    else:
        config = get_config()
        require(
            config.cloud_url and config.cloud_model and config.cloud_key.get_secret_value(),
            "MODEL_NOT_CONFIGURED",
            "Задайте параметры LiteLLM в окружении.",
            503,
        )
        # Только синтетическое несекретное содержимое, действие явно запрошено администратором.
        from app.infrastructure.models import CloudAdapter

        _, values = await effective_settings(db)
        await CloudAdapter().infer(
            'Return JSON {"ok":true}.',
            {"health_check": True},
            values,
            policy="cloud_allowed",
            external_enabled=True,
        )
        capabilities = {"verified_connection": True, "modalities": ["text"], "image_verified": False}
    row = await db.get(ModelDeployment, str(model_id), with_for_update=True, populate_existing=True)
    require(row.version == version, "VERSION_CONFLICT", "Модель изменилась во время проверки.")
    row.capabilities = capabilities
    row.checked_at = utcnow()
    db.add(Audit(actor_id=user_id, action="model.health", details={"model_id": row.id}))
    return serialize(row)


@router.get("/admin/queues")
async def queues(user=Depends(admin_user), db=Depends(database)):
    counts = (
        await db.execute(
            select(Task.queue_class, Task.status, func.count()).group_by(Task.queue_class, Task.status)
        )
    ).all()
    slot = await db.get(GPUSlot, 1)
    return {
        "queues": [{"name": name, "status": status, "count": count} for name, status, count in counts],
        "gpu": {
            "state": slot.state,
            "task_id": slot.task_id,
            "lease_until": slot.lease_until,
            "fencing_token": slot.fencing_token,
        }
        if slot
        else None,
        "controls": {
            c.key: c.value
            for c in (await db.scalars(select(Control).where(Control.key.like("queue:%")))).all()
        },
    }


@router.post("/admin/queues/{name}/{action}")
async def queue_action(
    name: Literal["default", "bulk", "cpu", "cloud", "maintenance"],
    action: Literal["pause", "resume"],
    key=Depends(idempotency_key),
    user=Depends(admin_user),
    db=Depends(database),
):
    await db.get(Control, "settings", with_for_update=True)
    control = await db.get(Control, "queue:" + name)
    if control is None:
        control = Control(key="queue:" + name, value={})
        db.add(control)
    control.value = {"paused": action == "pause"}
    db.add(Audit(actor_id=user.id, action=f"queue.{action}", details={"queue": name}))
    return control.value


class GPURecovery(StrictModel):
    expected_fencing_token: int
    physical_inference_stopped: Literal[True]
    reason: str = Field(min_length=1, max_length=500)


@router.post("/admin/gpu/recover")
async def recover_gpu(
    data: GPURecovery, key=Depends(idempotency_key), user=Depends(admin_user), db=Depends(database)
):
    slot = await db.get(GPUSlot, 1, with_for_update=True)
    require(
        slot.state == "quarantined" and slot.fencing_token == data.expected_fencing_token,
        "VERSION_CONFLICT",
        "Состояние GPU изменилось.",
    )
    slot.fencing_token += 1
    slot.state = "idle"
    slot.owner = slot.task_id = slot.lease_until = None
    db.add(
        Audit(
            actor_id=user.id,
            action="gpu.recovered",
            reason=data.reason,
            details={"fencing_token": slot.fencing_token},
        )
    )
    return {"status": "idle"}


@router.get("/admin/tasks/{task_id}/trace")
async def trace(task_id: UUID, user=Depends(admin_user), selected=Depends(scope), db=Depends(database)):
    task = await scoped_get(db, Task, task_id, selected.workspace_id)
    attempts = (
        await db.scalars(select(Attempt).where(Attempt.task_id == task.id).order_by(Attempt.created_at))
    ).all()
    return {
        "task_id": task.id,
        "status": task.status,
        "stage": task.stage,
        "config_revision": task.config_revision,
        "config_snapshot_hash": task.config_snapshot_hash,
        "prompt_revision": task.prompt_revision,
        "output_schema_version": task.output_schema_version,
        "attempts": [serialize(a) for a in attempts],
        "progress": task.progress,
    }


@router.post("/admin/tasks/{task_id}/replay", status_code=202)
async def replay(
    task_id: UUID,
    key=Depends(idempotency_key),
    user=Depends(admin_user),
    selected=Depends(write_scope),
    db=Depends(database),
):
    from app.application.tasks import create_task, task_view

    task = await scoped_get(db, Task, task_id, selected.workspace_id)
    cached = await previous_response(db, user.id, selected.workspace_id, f"replay:{task_id}", key, {})
    if cached:
        return cached
    child = await create_task(
        db,
        task.workspace_id,
        user.id,
        {
            "client_request_id": uid(),
            "input_mode": task.input_mode,
            "text": task.input_text,
            "media_ids": task.media_ids,
            "audio_media_id": task.audio_media_id,
            "context": {
                "item_id": task.context.get("item_id"),
                "location_id": task.context.get("location_id"),
            },
            "privacy": {"force_local": True},
        },
        parent_task_id=task.id,
    )
    child.context = {**child.context, "diagnostics_only": True}
    db.add(Audit(actor_id=user.id, action="task.replay", details={"source": task.id, "task_id": child.id}))
    return remember(db, user.id, selected.workspace_id, f"replay:{task_id}", key, {}, task_view(child))


@router.post("/admin/search/reindex", status_code=202)
async def reindex(
    key=Depends(idempotency_key),
    user=Depends(admin_user),
    selected=Depends(write_scope),
    db=Depends(database),
):
    cached = await previous_response(db, user.id, selected.workspace_id, "reindex", key, {})
    if cached:
        return cached
    job = Job(
        id=uid(),
        workspace_id=selected.workspace_id,
        created_by=user.id,
        kind="reindex",
        manifest={},
        manifest_hash=digest({}),
    )
    db.add(job)
    await db.flush()
    db.add(Outbox(workspace_id=selected.workspace_id, event_type="maintenance", entity_id=job.id))
    db.add(Audit(actor_id=user.id, action="search.reindex", details={"job_id": job.id}))
    return remember(
        db, user.id, selected.workspace_id, "reindex", key, {}, {"job_id": job.id, "status": "queued"}
    )


@router.get("/admin/jobs/{job_id}")
async def job_status(job_id: UUID, user=Depends(admin_user), selected=Depends(scope), db=Depends(database)):
    row = await scoped_get(db, Job, job_id, selected.workspace_id)
    return {
        "job_id": row.id,
        "kind": row.kind,
        "status": row.status,
        "result": {k: v for k, v in row.result.items() if k != "object_key"},
    }


@router.post("/admin/gc/preview")
async def gc_preview(user=Depends(admin_user), db=Depends(database)):
    _, settings = await effective_settings(db)
    from app.db.models import Binding

    rows = (
        await db.scalars(
            select(Media).where(
                Media.state == "uploaded",
                Media.created_at < utcnow() - timedelta(hours=settings["retention.orphan_upload_hours"]),
                ~Media.id.in_(select(Binding.media_id)),
            )
        )
    ).all()
    return {
        "count": len(rows),
        "bytes": sum(r.size_bytes for r in rows),
        "media_ids": [r.id for r in rows],
        "policy": "Только непривязанные файлы старше заданного срока; активный учёт сохраняется.",
    }


@router.post("/admin/gc/run")
async def gc_run(
    request: Request, key=Depends(idempotency_key), user=Depends(admin_user), db=Depends(database)
):
    from app.application.maintenance import regular_cleanup

    result = await regular_cleanup(request.app.state.session_factory, force=True)
    db.add(Audit(actor_id=user.id, action="gc.run", details={"policy": "effective", **result}))
    return result


@router.get("/admin/audit")
async def audit(
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
    user=Depends(admin_user),
    db=Depends(database),
):
    return await page(db, select(Audit), Audit, limit, cursor)


@router.get("/admin/metrics")
async def metrics(user=Depends(admin_user), db=Depends(database)):
    counts = dict((await db.execute(select(Task.status, func.count()).group_by(Task.status))).all())
    outbox = dict((await db.execute(select(Outbox.status, func.count()).group_by(Outbox.status))).all())
    return {
        "tasks": counts,
        "outbox": outbox,
        "oldest_pending": await db.scalar(select(func.min(Task.created_at)).where(Task.status == "queued")),
        "attempts": await db.scalar(select(func.count()).select_from(Attempt)),
        "index_lag": await db.scalar(
            select(func.count()).select_from(Item).where(Item.indexed_revision < Item.search_revision)
        ),
    }


@router.get("/admin/health")
async def health(user=Depends(admin_user), db=Depends(database)):
    import asyncio

    import httpx
    from redis.asyncio import Redis

    config = get_config()

    async def probe(url):
        try:
            async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
                return (await client.get(url)).is_success
        except Exception:
            return False

    qdrant, minio, ollama = await asyncio.gather(
        probe(config.qdrant_url + "/healthz"),
        probe(config.s3_endpoint + "/minio/health/ready"),
        probe(config.ollama_url + "/api/tags"),
    )
    redis = Redis.from_url(config.redis_url, socket_connect_timeout=3, socket_timeout=3)
    try:
        redis_ok = await redis.ping()
    except Exception:
        redis_ok = False
    finally:
        await redis.aclose()
    return {
        "postgres": True,
        "redis": redis_ok,
        "qdrant": qdrant,
        "storage": minio if config.storage_backend == "s3" else True,
        "ollama": ollama,
        "external_configured": bool(config.cloud_url and config.cloud_key.get_secret_value()),
    }
