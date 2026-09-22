from datetime import timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy import select

from app.api.catalog import page
from app.api.deps import database, idempotency_key, scope, write_scope
from app.application.auth import aware
from app.application.idempotency import previous_response, remember
from app.application.maintenance import cancel_purge, confirm_purge, deletion_manifest
from app.application.settings import effective_settings
from app.db.models import Job
from app.db.session import scoped_get
from app.domain.common import digest, uid, utcnow
from app.domain.errors import require
from app.domain.schemas import StrictModel
from app.infrastructure.storage import Storage

router = APIRouter()


class ExportInput(StrictModel):
    format: Literal["json", "csv", "zip"] = "json"
    include_media: bool = False
    include_history: bool = False


@router.post("/exports", status_code=202)
async def export(
    data: ExportInput, key=Depends(idempotency_key), selected=Depends(write_scope), db=Depends(database)
):
    body = data.model_dump()
    cached = await previous_response(db, selected.user.id, selected.workspace_id, "export", key, body)
    if cached:
        return cached
    _, settings = await effective_settings(db)
    manifest = {**body, "timezone": selected.user.timezone}
    job = Job(
        id=uid(),
        workspace_id=selected.workspace_id,
        created_by=selected.user.id,
        kind="export",
        manifest=manifest,
        manifest_hash=digest(manifest),
        expires_at=utcnow() + timedelta(hours=settings["exports.ttl_hours"]),
    )
    db.add(job)
    await db.flush()
    from app.db.models import Outbox

    db.add(Outbox(workspace_id=selected.workspace_id, event_type="maintenance", entity_id=job.id))
    return remember(
        db,
        selected.user.id,
        selected.workspace_id,
        "export",
        key,
        body,
        {"export_id": job.id, "status": "queued"},
    )


@router.get("/exports/{export_id}")
async def export_status(export_id: UUID, selected=Depends(scope), db=Depends(database)):
    job = await scoped_get(db, Job, export_id, selected.workspace_id)
    require(job.kind == "export", "NOT_FOUND", "Экспорт не найден.", 404)
    status = "expired" if job.status == "succeeded" and aware(job.expires_at) <= utcnow() else job.status
    return {
        "export_id": job.id,
        "status": status,
        "expires_at": job.expires_at,
        "download": f"/api/v1/exports/{job.id}/download" if status == "succeeded" else None,
        "sha256": job.result.get("sha256"),
    }


@router.get("/exports/{export_id}/download")
async def export_download(export_id: UUID, selected=Depends(scope), db=Depends(database)):
    job = await scoped_get(db, Job, export_id, selected.workspace_id)
    require(job.status not in {"expired", "revoked"}, "EXPORT_EXPIRED", "Экспорт больше недоступен.", 410)
    require(job.kind == "export" and job.status == "succeeded", "NOT_FOUND", "Экспорт ещё не готов.", 404)
    require(aware(job.expires_at) > utcnow(), "EXPORT_EXPIRED", "Срок доступа к экспорту истёк.", 410)
    return Response(
        await Storage().read(job.result["object_key"]),
        media_type=job.result["mime"],
        headers={"Cache-Control": "private, no-store"},
    )


class DeletionInput(StrictModel):
    item_ids: list[UUID] = Field(min_length=1, max_length=100)


@router.post("/deletion-previews", status_code=201)
async def deletion_preview(
    data: DeletionInput, key=Depends(idempotency_key), selected=Depends(write_scope), db=Depends(database)
):
    body = data.model_dump(mode="json")
    cached = await previous_response(
        db, selected.user.id, selected.workspace_id, "deletion_preview", key, body
    )
    if cached:
        return cached
    manifest = await deletion_manifest(db, selected.workspace_id, body["item_ids"])
    job = Job(
        id=uid(),
        workspace_id=selected.workspace_id,
        created_by=selected.user.id,
        kind="deletion_preview",
        status="preview",
        manifest=manifest,
        manifest_hash=digest(manifest),
    )
    db.add(job)
    await db.flush()
    return remember(
        db,
        selected.user.id,
        selected.workspace_id,
        "deletion_preview",
        key,
        body,
        {
            "preview_id": job.id,
            "preview_revision": job.version,
            "preview_hash": job.manifest_hash,
            "impact": manifest,
        },
    )


class PurgeInput(StrictModel):
    preview_id: UUID
    preview_revision: int = Field(ge=1)
    preview_hash: str
    explicit_confirmation: Literal[True]


@router.post("/purge-jobs", status_code=202)
async def purge(
    data: PurgeInput, key=Depends(idempotency_key), selected=Depends(write_scope), db=Depends(database)
):
    body = data.model_dump(mode="json")
    cached = await previous_response(db, selected.user.id, selected.workspace_id, "purge", key, body)
    if cached:
        return cached
    preview = await scoped_get(db, Job, data.preview_id, selected.workspace_id)
    require(preview.version == data.preview_revision, "VERSION_CONFLICT", "Предпросмотр изменился.")
    job = await confirm_purge(db, preview, selected.user.id, data.preview_hash)
    return remember(
        db,
        selected.user.id,
        selected.workspace_id,
        "purge",
        key,
        body,
        {
            "purge_job_id": job.id,
            "status": job.status,
            "version": job.version,
            "not_before": job.not_before.isoformat(),
        },
    )


def purge_view(job):
    return {
        "purge_job_id": job.id,
        "status": job.status,
        "version": job.version,
        "result": job.result,
        "not_before": job.not_before,
        "created_at": job.created_at,
    }


@router.get("/purge-jobs")
async def purge_jobs(
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
    selected=Depends(scope),
    db=Depends(database),
):
    return await page(
        db,
        select(Job).where(Job.workspace_id == selected.workspace_id, Job.kind == "purge"),
        Job,
        limit,
        cursor,
        render=purge_view,
    )


@router.get("/purge-jobs/{job_id}")
async def purge_status(job_id: UUID, selected=Depends(scope), db=Depends(database)):
    job = await scoped_get(db, Job, job_id, selected.workspace_id)
    require(job.kind == "purge", "NOT_FOUND", "Задание не найдено.", 404)
    return purge_view(job)


class CancelPurge(StrictModel):
    expected_version: int = Field(ge=1)
    explicit_confirmation: Literal[True]


@router.post("/purge-jobs/{job_id}/cancel")
async def cancel_deletion(
    job_id: UUID,
    data: CancelPurge,
    key=Depends(idempotency_key),
    selected=Depends(write_scope),
    db=Depends(database),
):
    body = data.model_dump()
    operation = f"cancel_purge:{job_id}"
    cached = await previous_response(db, selected.user.id, selected.workspace_id, operation, key, body)
    if cached:
        return cached
    job = await scoped_get(db, Job, job_id, selected.workspace_id)
    job = await cancel_purge(db, job, data.expected_version, selected.user.id)
    return remember(
        db,
        selected.user.id,
        selected.workspace_id,
        operation,
        key,
        body,
        {"purge_job_id": job.id, "status": job.status, "version": job.version, **job.result},
    )
