from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy import func, select

from app.api.catalog import page, serialize
from app.api.deps import database, idempotency_key, scope, write_scope
from app.application.idempotency import previous_response, remember
from app.application.tasks import ACTIVE, cancel_task, create_task, manual_review, task_view
from app.db.models import Batch, Confirmation, Task
from app.db.session import scoped_get
from app.domain.common import uid
from app.domain.errors import require
from app.domain.schemas import StrictModel, TaskCreate

router = APIRouter()


@router.post("/tasks", status_code=202)
async def create(
    data: TaskCreate, key=Depends(idempotency_key), selected=Depends(write_scope), db=Depends(database)
):
    body = data.model_dump(mode="json")
    cached = await previous_response(db, selected.user.id, selected.workspace_id, "create_task", key, body)
    if cached:
        return cached
    task = await create_task(db, selected.workspace_id, selected.user.id, body)
    return remember(db, selected.user.id, selected.workspace_id, "create_task", key, body, task_view(task))


@router.get("/tasks")
async def tasks(
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
    batch_id: UUID | None = None,
    status: str | None = None,
    selected=Depends(scope),
    db=Depends(database),
):
    query = select(Task).where(
        Task.workspace_id == selected.workspace_id,
        func.coalesce(Task.context["deleted"].as_boolean(), False).is_(False),
    )
    if batch_id:
        query = query.where(Task.batch_id == str(batch_id))
    if status:
        query = query.where(Task.status == status)
    return await page(db, query, Task, limit, cursor, task_view)


class PollItem(StrictModel):
    task_id: UUID
    status_version: int = 0


class Poll(StrictModel):
    tasks: list[PollItem] = Field(max_length=100)


@router.post("/tasks/status")
async def poll(data: Poll, selected=Depends(scope), db=Depends(database)):
    changed, unchanged = [], []
    for entry in data.tasks:
        task = await scoped_get(db, Task, entry.task_id, selected.workspace_id)
        require(not task.context.get("deleted"), "TASK_PURGED", "Материалы задачи удалены.", 410)
        if task.status_version == entry.status_version:
            unchanged.append(task.id)
        else:
            changed.append(task_view(task))
    return {"changed": changed, "unchanged": unchanged, "poll_after_ms": 3000}


@router.get("/tasks/{task_id}")
async def task_status(
    task_id: UUID,
    response: Response,
    if_none_match: str | None = Header(None),
    selected=Depends(scope),
    db=Depends(database),
):
    task = await scoped_get(db, Task, task_id, selected.workspace_id)
    require(not task.context.get("deleted"), "TASK_PURGED", "Материалы задачи удалены.", 410)
    etag = f'"{task.id}:{task.status_version}"'
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    return task_view(task)


@router.post("/tasks/{task_id}/cancel")
async def cancel(
    task_id: UUID, key=Depends(idempotency_key), selected=Depends(write_scope), db=Depends(database)
):
    return await cancel_task(db, await scoped_get(db, Task, task_id, selected.workspace_id, lock=True))


class Retry(StrictModel):
    client_request_id: UUID


@router.post("/tasks/{task_id}/retry", status_code=202)
async def retry(
    task_id: UUID,
    data: Retry,
    key=Depends(idempotency_key),
    selected=Depends(write_scope),
    db=Depends(database),
):
    body = data.model_dump(mode="json")
    operation_scope = f"task_retry:{task_id}"
    cached = await previous_response(db, selected.user.id, selected.workspace_id, operation_scope, key, body)
    if cached:
        return cached
    task = await scoped_get(db, Task, task_id, selected.workspace_id, lock=True)
    require(
        task.status in {"failed", "cancelled", "expired"},
        "INVALID_TASK_STATE",
        "Повтор доступен после остановки обработки.",
    )
    if task.proposal_id:
        require(
            not await db.scalar(select(Confirmation.id).where(Confirmation.proposal_id == task.proposal_id)),
            "CONFIRMATION_RETRY_REQUIRED",
            "Повторите принятое подтверждение.",
        )
    child = await create_task(
        db,
        selected.workspace_id,
        selected.user.id,
        {
            "client_request_id": body["client_request_id"],
            "input_mode": task.input_mode,
            "text": task.input_text,
            "media_ids": task.media_ids,
            "audio_media_id": task.audio_media_id,
            "context": {k: task.context.get(k) for k in ("item_id", "location_id")},
            "privacy": {"force_local": task.requested_privacy == "local_only"},
            "batch_id": task.batch_id,
        },
        parent_task_id=task.id,
    )
    return remember(db, selected.user.id, selected.workspace_id, operation_scope, key, body, task_view(child))


@router.post("/tasks/{task_id}/manual-review", status_code=201)
async def manual(
    task_id: UUID,
    data: Retry,
    key=Depends(idempotency_key),
    selected=Depends(write_scope),
    db=Depends(database),
):
    body = data.model_dump(mode="json")
    operation_scope = f"manual_review:{task_id}"
    cached = await previous_response(db, selected.user.id, selected.workspace_id, operation_scope, key, body)
    if cached:
        return cached
    result = await manual_review(
        db,
        await scoped_get(db, Task, task_id, selected.workspace_id, lock=True),
        selected.user.id,
        str(data.client_request_id),
    )
    return remember(db, selected.user.id, selected.workspace_id, operation_scope, key, body, result)


class Priority(StrictModel):
    expected_version: int = Field(ge=1)
    priority: int = Field(ge=0, le=10)


@router.patch("/tasks/{task_id}/priority")
async def priority(task_id: UUID, data: Priority, selected=Depends(write_scope), db=Depends(database)):
    task = await scoped_get(db, Task, task_id, selected.workspace_id)
    require(
        task.status in ACTIVE - {"running"},
        "INVALID_TASK_STATE",
        "Приоритет меняется только у ожидающей задачи.",
    )
    require(task.status_version == data.expected_version, "VERSION_CONFLICT", "Задача уже изменилась.")
    task.priority = data.priority
    task.status_version += 1
    return task_view(task)


class BatchInput(StrictModel):
    name: str = Field("Загрузка", min_length=1, max_length=255)


@router.post("/ingestion-batches", status_code=201)
async def batch(
    data: BatchInput, key=Depends(idempotency_key), selected=Depends(write_scope), db=Depends(database)
):
    body = data.model_dump()
    cached = await previous_response(
        db, selected.user.id, selected.workspace_id, "ingestion_batch", key, body
    )
    if cached:
        return cached
    row = Batch(id=uid(), workspace_id=selected.workspace_id, created_by=selected.user.id, name=data.name)
    db.add(row)
    await db.flush()
    return remember(db, selected.user.id, selected.workspace_id, "ingestion_batch", key, body, serialize(row))


@router.get("/ingestion-batches/{batch_id}")
async def batch_progress(batch_id: UUID, selected=Depends(scope), db=Depends(database)):
    batch = await scoped_get(db, Batch, batch_id, selected.workspace_id)
    counts = (
        await db.execute(
            select(Task.status, func.count())
            .where(Task.workspace_id == selected.workspace_id, Task.batch_id == batch.id)
            .group_by(Task.status)
        )
    ).all()
    return {**serialize(batch), "counts": dict(counts)}
