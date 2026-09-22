"""Фотографии каталога: приватные URL и одна выборка миниатюр на страницу."""

from sqlalchemy import select

from app.db.models import Binding, Media


async def item_photos(db, workspace_id, item_ids):
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
                Binding.entity_type == "item",
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


async def bind_photo_variants(db, workspace_id, item_id, source_ids):
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
                    Binding.entity_type == "item",
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
                    entity_type="item",
                    entity_id=item_id,
                    role=media.kind,
                    ordinal=source_ids.index(media.manifest["source_media_id"]),
                )
            )
