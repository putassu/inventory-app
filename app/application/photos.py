"""Фотографии каталога: приватные URL и одна выборка миниатюр на страницу."""

import asyncio
import hashlib

from sqlalchemy import select

from app.db.models import Binding, Media
from app.db.session import scoped_get
from app.domain.common import uid
from app.domain.errors import require
from app.infrastructure.media import decode_image, jpeg
from app.infrastructure.storage import Storage


async def item_photos(db, workspace_id, item_ids, entity_type="item"):
    result = {item_id: [] for item_id in item_ids}
    if not item_ids:
        return result
    rows = (
        await db.execute(
            select(Binding.entity_id, Media)
            .join(Media, Media.id == Binding.media_id)
            .where(
                Binding.workspace_id == workspace_id,
                Media.workspace_id == workspace_id,
                Binding.entity_type == entity_type,
                Binding.entity_id.in_(item_ids),
                Binding.role == "source",
                Media.state == "uploaded",
                Media.mime.startswith("image/"),
            )
            .order_by(Binding.ordinal, Binding.id)
        )
    ).all()
    originals = {media.id for _, media in rows}
    thumbnails = (
        (
            await db.scalars(
                select(Media)
                .where(
                    Media.workspace_id == workspace_id,
                    Media.kind == "thumbnail",
                    Media.state == "uploaded",
                    Media.manifest["source_media_id"].as_string().in_(originals),
                )
                .order_by(Media.created_at, Media.id)
            )
        ).all()
        if originals
        else []
    )
    by_source = {media.manifest["source_media_id"]: media for media in thumbnails}
    for item_id, source in rows:
        thumbnail = by_source.get(source.id)
        result[item_id].append(
            {
                "media_id": source.id,
                "url": f"/api/v1/media/{source.id}/download",
                "thumbnail": {
                    "media_id": thumbnail.id,
                    "url": f"/api/v1/media/{thumbnail.id}/download",
                    "width": thumbnail.width,
                    "height": thumbnail.height,
                }
                if thumbnail
                else None,
            }
        )
    return result


async def bind_photo_variants(db, workspace_id, item_id, source_ids, entity_type="item"):
    # Иначе GC удалит миниатюру вместе с материалами задачи, хотя карточка ещё жива.
    variants = (
        await db.scalars(
            select(Media).where(
                Media.workspace_id == workspace_id,
                Media.state == "uploaded",
                Media.kind.in_(["thumbnail", "normalized"]),
                Media.manifest["source_media_id"].as_string().in_(source_ids),
            )
        )
    ).all()
    existing = set(
        (
            await db.scalars(
                select(Binding.media_id).where(
                    Binding.workspace_id == workspace_id,
                    Binding.entity_type == entity_type,
                    Binding.entity_id == item_id,
                )
            )
        ).all()
    )
    for media in variants:
        if media.id not in existing:
            db.add(
                Binding(
                    workspace_id=workspace_id,
                    media_id=media.id,
                    entity_type=entity_type,
                    entity_id=item_id,
                    role=media.kind,
                    ordinal=source_ids.index(media.manifest["source_media_id"]),
                )
            )


async def attach_photos(db, workspace_id, entity_type, entity_id, source_ids, settings):
    """Ручные фото обрабатывает CPU при сохранении, без задачи и обращения к LLM."""
    storage = Storage()
    for ordinal, media_id in enumerate(dict.fromkeys(source_ids)):
        source = await scoped_get(db, Media, media_id, workspace_id)
        require(
            source.state == "uploaded" and source.kind == "source" and source.mime.startswith("image/"),
            "INVALID_MEDIA",
            "Фотография недоступна.",
            422,
        )
        thumbnail = await db.scalar(
            select(Media)
            .where(
                Media.workspace_id == workspace_id,
                Media.kind == "thumbnail",
                Media.state == "uploaded",
                Media.manifest["source_media_id"].as_string() == source.id,
            )
            .limit(1)
        )
        if thumbnail is None:
            payload = await storage.read(source.object_key)
            image, _ = await asyncio.to_thread(
                decode_image,
                payload,
                settings["media.max_decoded_pixels"],
                settings["media.thumbnail_max_side"],
            )
            try:
                payload = await asyncio.to_thread(jpeg, image, settings["media.jpeg_quality"])
                mid = uid()
                key = f"{workspace_id}/{mid}/thumbnail.jpg"
                await storage.put(key, payload, "image/jpeg")
                db.add(
                    Media(
                        id=mid,
                        workspace_id=workspace_id,
                        object_key=key,
                        mime="image/jpeg",
                        sha256=hashlib.sha256(payload).hexdigest(),
                        size_bytes=len(payload),
                        width=image.width,
                        height=image.height,
                        kind="thumbnail",
                        privacy_policy=source.privacy_policy,
                        manifest={"source_media_id": source.id},
                    )
                )
            finally:
                image.close()
            await db.flush()
        existing = await db.scalar(
            select(Binding.id)
            .where(
                Binding.workspace_id == workspace_id,
                Binding.entity_type == entity_type,
                Binding.entity_id == entity_id,
                Binding.media_id == source.id,
                Binding.role == "source",
            )
            .limit(1)
        )
        if existing is None:
            db.add(
                Binding(
                    workspace_id=workspace_id,
                    media_id=source.id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    ordinal=ordinal,
                )
            )
    await bind_photo_variants(db, workspace_id, entity_id, source_ids, entity_type)
