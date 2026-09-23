from datetime import timedelta

from sqlalchemy import func, select

from app.application.proposals import create_proposal
from app.application.settings import effective_settings
from app.config import get_config
from app.db.models import (
    Batch,
    Binding,
    Confirmation,
    Item,
    Location,
    Media,
    ModelDeployment,
    Proposal,
    Task,
    User,
)
from app.db.session import scoped_get
from app.domain.common import digest, uid, utcnow
from app.domain.errors import require
from app.domain.rules import transition
from app.infrastructure.models import prompt_revision

ACTIVE = {"accepted", "preparing", "queued", "running", "retry_wait"}


def task_view(task):
    require(not task.context.get("deleted"), "TASK_PURGED", "Материалы задачи удалены.", 410)
    return {
        "task_id": task.id,
        "input_mode": task.input_mode,
        "parent_task_id": task.parent_task_id,
        "title": " ".join((task.input_text or "").split())[:160]
        or {
            "photo": "Обработка фотографии",
            "audio": "Обработка голоса",
            "photo_audio": "Обработка фото и голоса",
        }.get(task.input_mode, "Обработка запроса"),
        "status": task.status,
        "stage": task.stage,
        "status_version": task.status_version,
        "progress": task.progress,
        "proposal_id": task.proposal_id,
        "result": task.result if task.status == "succeeded" else {},
        "effective_privacy": task.effective_privacy,
        "batch_id": task.batch_id,
        "config_revision": task.config_revision,
        "error_code": task.error_code,
        "can_cancel": task.status in ACTIVE | {"waiting_for_review"},
        "poll_after_ms": 2000 if task.status in ACTIVE | {"applying"} else None,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "timing": {
            "processing_seconds": str(task.processing_seconds),
            "stage_started_at": (task.progress.get("current") or {}).get("started_at"),
            "server_time": utcnow().isoformat(),
        },
        "links": {
            "self": f"/api/v1/tasks/{task.id}",
            "review": f"/api/v1/proposals/{task.proposal_id}" if task.proposal_id else None,
        },
    }


async def create_task(db, workspace_id, user_id, data, parent_task_id=None):
    require(
        not data.get("workspace_id") or data["workspace_id"] == workspace_id,
        "WORKSPACE_MISMATCH",
        "Рабочие области не совпадают.",
        400,
    )
    existing = await db.scalar(
        select(Task).where(
            Task.workspace_id == workspace_id,
            Task.created_by == user_id,
            Task.client_request_id == data["client_request_id"],
        )
    )
    if existing:
        require(
            existing.context.get("request_hash") == digest(data),
            "IDEMPOTENCY_KEY_REUSED",
            "client_request_id использован для другого запроса.",
        )
        return existing
    revision, settings = await effective_settings(db)
    count = await db.scalar(
        select(func.count()).select_from(Task).where(Task.created_by == user_id, Task.status.in_(ACTIVE))
    )
    require(
        count < settings["queue.max_pending_per_user"],
        "ADMISSION_LIMIT",
        "Слишком много ожидающих задач.",
        429,
    )
    require(
        len(data["media_ids"]) <= settings["media.max_images_per_task"],
        "TASK_MEDIA_LIMIT",
        "Слишком много фотографий.",
        413,
    )
    require(
        len(set(data["media_ids"])) == len(data["media_ids"]),
        "INVALID_REQUEST",
        "Фотографии повторяются.",
        422,
    )
    require(
        data.get("text") or data["media_ids"] or data.get("audio_media_id"),
        "EMPTY_TASK",
        "Добавьте текст, фото или аудио.",
        422,
    )
    policies = []
    media = []
    for media_id in [*data["media_ids"], *([data["audio_media_id"]] if data.get("audio_media_id") else [])]:
        row = await scoped_get(db, Media, media_id, workspace_id)
        require(row.state == "uploaded", "MEDIA_PURGED", "Материал недоступен.", 410)
        require(
            row.mime.startswith("audio/")
            if media_id == data.get("audio_media_id")
            else row.mime.startswith("image/"),
            "UNSUPPORTED_INPUT",
            "Тип материала не соответствует полю задачи.",
            400,
        )
        policies.append(row.privacy_policy)
        media.append(row)
    require(
        sum(row.size_bytes for row in media) <= settings["media.max_task_bytes"],
        "TASK_MEDIA_LIMIT",
        "Общий размер материалов превышен.",
        413,
    )
    context = data.get("context", {})
    if parent_task_id:
        parent = await scoped_get(db, Task, parent_task_id, workspace_id)
        require(not parent.context.get("deleted"), "TASK_PURGED", "Материалы исходной задачи удалены.", 410)
        if parent.context.get("diagnostics_only"):
            context = {**context, "diagnostics_only": True}
    for field, model in (("item_id", Item), ("location_id", Location)):
        if context.get(field):
            row = await scoped_get(db, model, context[field], workspace_id)
            policies.append(row.privacy_policy if field == "item_id" else row.default_privacy_policy)
    if data.get("batch_id"):
        await scoped_get(db, Batch, data["batch_id"], workspace_id)
    user = await db.get(User, user_id)
    force_local = data.get("privacy", {}).get(
        "force_local", user.preferences.get("default_privacy", "local_only") == "local_only"
    )
    if user.preferences.get("prefer_local", True):
        settings = {**settings, "routing.strategy": "local_first"}
    deployments = (await db.scalars(select(ModelDeployment))).all()
    route = {
        row.logical_name: {
            "model_id": row.actual_model_id,
            "endpoint_ref": row.endpoint_ref,
            "trust_domain": row.trust_domain,
            "version": row.version,
        }
        for row in deployments
    }
    config = get_config()
    settings = {
        **settings,
        "model_deployments": route,
        "collage.max_width": min(settings["collage.max_width"], config.local_image_max_side),
        "collage.max_height": min(settings["collage.max_height"], config.local_image_max_side),
        "model.image_max_bytes": config.local_image_max_bytes,
    }
    task = Task(
        id=uid(),
        workspace_id=workspace_id,
        created_by=user_id,
        client_request_id=data["client_request_id"],
        parent_task_id=parent_task_id,
        batch_id=data.get("batch_id"),
        input_mode=data["input_mode"],
        input_text=data.get("text"),
        media_ids=data["media_ids"],
        audio_media_id=data.get("audio_media_id"),
        context={**context, "request_hash": digest(data)},
        requested_privacy="local_only" if force_local or "local_only" in policies else "cloud_allowed",
        effective_privacy="local_only",
        config_revision=revision,
        config_snapshot=settings,
        config_snapshot_hash=digest(settings),
        prompt_revision=prompt_revision(),
        model_route_revision=digest(route),
        queue_class="bulk"
        if settings["queue.bulk_after_outstanding"] and count >= settings["queue.bulk_after_outstanding"]
        else "default",
        deadline_at=utcnow() + timedelta(days=settings["retention.review_draft_days"])
        if settings["retention.review_draft_days"]
        else None,
    )
    db.add(task)
    await db.flush()
    task.progress = {
        "current": {"stage": task.stage, "status": task.status, "started_at": task.created_at.isoformat()},
        "history": [],
        "percent": None,
        "estimated_remaining_ms": None,
    }
    for i, row in enumerate(media):
        db.add(
            Binding(
                workspace_id=workspace_id, media_id=row.id, entity_type="task", entity_id=task.id, ordinal=i
            )
        )
    # PostgreSQL — очередь фактов. Scheduler восстановит dispatch даже без Redis.
    return task


async def cancel_task(db, task):
    require(
        task.status in ACTIVE | {"waiting_for_review", "cancelled"},
        "ALREADY_CONFIRMED",
        "После принятия подтверждения отмена задачи невозможна.",
    )
    if task.status != "cancelled":
        transition(task, "cancelled")
        task.cancel_requested_at = utcnow()
        if task.proposal_id:
            proposal = await db.get(Proposal, task.proposal_id)
            proposal.status = "cancelled"
            proposal.document = {
                **proposal.document,
                "status": "cancelled",
                "can_confirm": False,
                "available_actions": [],
            }
    return task_view(task)


async def manual_review(db, task, user_id, client_request_id):
    require(
        task.status in {"failed", "cancelled", "waiting_for_review"},
        "INVALID_TASK_STATE",
        "Ручное продолжение сейчас недоступно.",
    )
    if task.proposal_id:
        require(
            not await db.scalar(select(Confirmation.id).where(Confirmation.proposal_id == task.proposal_id)),
            "CONFIRMATION_RETRY_REQUIRED",
            "Повторите прежнее подтверждение, не создавая новое намерение.",
        )
    child = await create_task(
        db,
        task.workspace_id,
        user_id,
        {
            "client_request_id": client_request_id,
            "input_mode": "manual",
            "text": task.input_text or "Ручное продолжение",
            "media_ids": task.media_ids,
            "audio_media_id": task.audio_media_id,
            "context": {k: task.context.get(k) for k in ("item_id", "location_id")},
            "privacy": {"force_local": True},
            "batch_id": task.batch_id,
        },
        parent_task_id=task.id,
    )
    transition(child, "preparing")
    await create_proposal(
        db,
        task.workspace_id,
        user_id,
        [
            {
                "type": "receive_stock",
                "values": {
                    "tracking_mode": "untracked",
                    "quantity_state": "not_applicable",
                    "location_id": task.context.get("location_id"),
                },
            }
        ],
        task=child,
        source="manual",
        warnings=["Распознавание не применено. Заполните доступные сведения или сохраните фотокарточку."],
    )
    return task_view(child)
