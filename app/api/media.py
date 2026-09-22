import asyncio
import hashlib
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy import select

from app.api.catalog import serialize
from app.api.deps import database, idempotency_key, scope
from app.application.idempotency import previous_response, remember
from app.application.settings import effective_settings
from app.db.models import Binding, Media
from app.db.session import scoped_get, workspace_access
from app.domain.common import uid
from app.domain.errors import DomainError, require
from app.infrastructure.media import inspect_media
from app.infrastructure.storage import Storage

router = APIRouter()


@router.post("/media", status_code=201)
async def upload(
    file: UploadFile = File(...),
    privacy_policy: str = Form("local_only"),
    client_preprocessed: bool = Form(False),
    key=Depends(idempotency_key),
    selected=Depends(scope),
    db=Depends(database),
):
    require(
        privacy_policy in {"local_only", "cloud_allowed"},
        "INVALID_POLICY",
        "Неизвестный режим обработки.",
        422,
    )
    await workspace_access(db, selected.workspace_id, selected.user.id, write=True)
    _, settings = await effective_settings(db)
    await db.commit()
    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data.extend(chunk)
        require(len(data) <= settings["media.max_file_bytes"], "FILE_TOO_LARGE", "Файл превышает лимит.", 413)
    metadata = await asyncio.to_thread(inspect_media, bytes(data), file.content_type, settings)
    checksum = hashlib.sha256(data).hexdigest()
    body = {"sha256": checksum, "privacy_policy": privacy_policy, "client_preprocessed": client_preprocessed}
    cached = await previous_response(db, selected.user.id, selected.workspace_id, "upload", key, body)
    if cached:
        return cached
    await db.commit()
    media_id = uid()
    object_key = f"{selected.workspace_id}/{media_id}/source"
    try:
        await Storage().put(object_key, bytes(data), metadata["mime"])
    except Exception as exc:
        raise DomainError("DEPENDENCY_UNAVAILABLE", "Не удалось сохранить файл.", 503) from exc
    # Только запись ссылки и проверка idempotency выполняются под блокировкой workspace.
    await workspace_access(db, selected.workspace_id, selected.user.id, write=True, lock=True)
    cached = await previous_response(db, selected.user.id, selected.workspace_id, "upload", key, body)
    if cached:
        return cached
    row = Media(
        id=media_id,
        workspace_id=selected.workspace_id,
        object_key=object_key,
        sha256=checksum,
        size_bytes=len(data),
        privacy_policy=privacy_policy,
        client_preprocessed=client_preprocessed,
        **metadata,
    )
    db.add(row)
    await db.flush()
    result = {
        "media_id": row.id,
        "state": row.state,
        "type": "audio" if row.mime.startswith("audio/") else "image",
        **metadata,
    }
    return remember(db, selected.user.id, selected.workspace_id, "upload", key, body, result)


@router.get("/media/{media_id}")
async def metadata(media_id: UUID, selected=Depends(scope), db=Depends(database)):
    row = await scoped_get(db, Media, media_id, selected.workspace_id)
    require(row.state == "uploaded", "MEDIA_PURGED", "Файл недоступен.", 410)
    result = serialize(row)
    result.pop("object_key")
    result["download"] = f"/api/v1/media/{row.id}/download"
    return result


@router.get("/media/{media_id}/download")
async def download(media_id: UUID, selected=Depends(scope), db=Depends(database)):
    row = await scoped_get(db, Media, media_id, selected.workspace_id)
    require(row.state == "uploaded", "MEDIA_PURGED", "Файл недоступен.", 410)
    return Response(
        await Storage().read(row.object_key),
        media_type=row.mime,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/media/{media_id}/delete-preview")
async def delete_preview(
    media_id: UUID, key=Depends(idempotency_key), selected=Depends(scope), db=Depends(database)
):
    row = await scoped_get(db, Media, media_id, selected.workspace_id)
    require(row.state == "uploaded", "MEDIA_PURGED", "Файл недоступен.", 410)
    bindings = (
        await db.scalars(
            select(Binding).where(Binding.workspace_id == selected.workspace_id, Binding.media_id == row.id)
        )
    ).all()
    return {
        "media_id": row.id,
        "version": row.version,
        "bindings": [serialize(b) for b in bindings],
        "can_delete_bytes": not bindings,
        "size_bytes": row.size_bytes,
    }
