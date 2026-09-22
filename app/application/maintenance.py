"""Экспорт и удаление отделены от предметных команд и имеют устойчивые manifests."""

import csv
import hashlib
import io
import json
import zipfile
from datetime import datetime, timedelta

from sqlalchemy import delete, select

from app.application.auth import aware
from app.application.inventory import row_state
from app.application.settings import effective_settings
from app.db.models import (
    Alias,
    Attempt,
    Audit,
    Balance,
    Binding,
    Confirmation,
    Control,
    Entry,
    Evidence,
    Idempotency,
    Item,
    Job,
    Location,
    Lot,
    Media,
    Notification,
    Occurrence,
    Operation,
    Outbox,
    Proposal,
    ProposalRevision,
    Receipt,
    Task,
    Tombstone,
    Workspace,
)
from app.domain.common import canonical, digest, jsonable, uid, utcnow
from app.domain.errors import require
from app.infrastructure.storage import Storage

EXPORT_MODELS = {"items": Item, "lots": Lot, "balances": Balance, "locations": Location, "aliases": Alias}


def safe_csv(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    text = "" if value is None else str(value)
    return (
        "'" + text
        if text.startswith(("\t", "\r", "\n")) or text.lstrip().startswith(("=", "+", "-", "@"))
        else text
    )


def csv_bytes(rows):
    output = io.StringIO(newline="")
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: safe_csv(value) for key, value in row.items()})
    return output.getvalue().encode("utf-8-sig")


async def export_job(factory, job_id):
    async with factory() as db:
        if db.bind.dialect.name == "postgresql":
            await db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        job = await db.get(Job, job_id)
        if job.status not in {"queued", "running"}:
            return
        workspace = await db.get(Workspace, job.workspace_id)
        payload = {
            "schema_version": "export.v1",
            "exported_at": utcnow().isoformat(),
            "timezone": job.manifest["timezone"],
            "reference_versions": {"categories": "v1", "units": "v1"},
            "export_revision": workspace.version,
        }
        for name, model in EXPORT_MODELS.items():
            query = select(model).where(model.workspace_id == job.workspace_id)
            if model is Item:
                query = query.where(Item.lifecycle != "deleted")
            elif model in {Lot, Alias}:
                query = query.where(
                    model.item_id.in_(
                        select(Item.id).where(
                            Item.workspace_id == job.workspace_id, Item.lifecycle != "deleted"
                        )
                    )
                )
            elif model is Balance:
                query = query.where(
                    Balance.lot_id.in_(
                        select(Lot.id)
                        .join(Item, Lot.item_id == Item.id)
                        .where(Item.lifecycle != "deleted", Item.workspace_id == job.workspace_id)
                    )
                )
            payload[name] = [
                jsonable(row_state(r)) for r in (await db.scalars(query.order_by(model.id))).all()
            ]
        if job.manifest.get("include_history"):
            operations = (
                await db.scalars(
                    select(Operation).where(
                        Operation.workspace_id == job.workspace_id,
                        Operation.status.notin_(["deleted", "purged"]),
                    )
                )
            ).all()
            payload["operations"] = [jsonable(row_state(r)) for r in operations]
            payload["entries"] = [
                jsonable(row_state(r))
                for r in (
                    await db.scalars(select(Entry).where(Entry.operation_id.in_([o.id for o in operations])))
                ).all()
            ]
        bindings = (
            await db.scalars(
                select(Binding).where(
                    Binding.workspace_id == job.workspace_id,
                    Binding.entity_type == "item",
                    Binding.entity_id.in_([i["id"] for i in payload["items"]]),
                )
            )
        ).all()
        media = (
            await db.scalars(
                select(Media).where(Media.id.in_([b.media_id for b in bindings]), Media.state == "uploaded")
            )
        ).all()
        payload["media"] = [
            {
                "id": asset.id,
                "mime": asset.mime,
                "sha256": asset.sha256,
                "file": f"media/{asset.id}" if job.manifest.get("include_media") else None,
            }
            for asset in media
        ]
        payload["media_bindings"] = [jsonable(row_state(binding)) for binding in bindings]
        manifest = dict(job.manifest)
        workspace_id = job.workspace_id
    files = {}
    format_ = manifest["format"]
    if format_ in {"json", "zip"}:
        files["inventory.json"] = canonical(payload).encode()
    if format_ in {"csv", "zip"}:
        for name in EXPORT_MODELS:
            files[name + ".csv"] = csv_bytes(payload[name])
    storage = Storage()
    if manifest.get("include_media"):
        for asset in media:
            files[f"media/{asset.id}"] = await storage.read(asset.object_key)
    if format_ == "json" and not manifest.get("include_media"):
        data, mime = files["inventory.json"], "application/json"
    else:
        checksums = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
        files["manifest.json"] = canonical({"schema_version": "export.v1", "checksums": checksums}).encode()
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        data, mime = stream.getvalue(), "application/zip"
    object_key = f"{workspace_id}/exports/{job_id}"
    await storage.put(object_key, data, mime)
    async with factory() as db, db.begin():
        job = await db.get(Job, job_id, with_for_update=True)
        if job.status not in {"queued", "running"}:
            # Удаление данных отзывает также уже строящийся экспорт.
            return
        job.status = "succeeded"
        job.result = {
            "object_key": object_key,
            "mime": mime,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        }


async def deletion_manifest(db, workspace_id, item_ids):
    require(item_ids and len(item_ids) <= 100, "INVALID_PURGE_SCOPE", "Выберите от 1 до 100 карточек.", 422)
    items = (
        await db.scalars(select(Item).where(Item.workspace_id == workspace_id, Item.id.in_(item_ids)))
    ).all()
    require(len(items) == len(set(item_ids)), "NOT_FOUND", "Карточка не найдена.", 404)
    require(all(i.lifecycle != "deleted" for i in items), "ITEM_DELETED", "Карточка уже удалена.", 410)
    affected = await deletion_scope(db, workspace_id, item_ids)
    task_ids = {task.id for task in affected["tasks"]}
    bindings = (
        await db.scalars(
            select(Binding).where(
                Binding.workspace_id == workspace_id,
                ((Binding.entity_type == "item") & Binding.entity_id.in_(item_ids))
                | ((Binding.entity_type == "task") & Binding.entity_id.in_(task_ids)),
            )
        )
    ).all()
    media = (await db.scalars(select(Media).where(Media.id.in_([b.media_id for b in bindings])))).all()
    shared = set(
        (
            await db.scalars(
                select(Binding.media_id).where(
                    Binding.media_id.in_([m.id for m in media]), Binding.id.notin_([b.id for b in bindings])
                )
            )
        ).all()
    )
    return {
        "items": [
            {"id": r.id, "version": r.version, "name": r.name, "lifecycle": r.lifecycle}
            for r in sorted(items, key=lambda i: i.id)
        ],
        "bindings": [
            {"id": b.id, "version": b.version, "media_id": b.media_id}
            for b in sorted(bindings, key=lambda b: b.id)
        ],
        "lots": [{"id": r.id, "version": r.version} for r in sorted(affected["lots"], key=lambda r: r.id)],
        "balances": [
            {"id": r.id, "version": r.version} for r in sorted(affected["balances"], key=lambda r: r.id)
        ],
        "tasks": [
            {"id": r.id, "version": r.status_version} for r in sorted(affected["tasks"], key=lambda r: r.id)
        ],
        "proposals": [
            {"id": r.id, "revision": r.revision} for r in sorted(affected["proposals"], key=lambda r: r.id)
        ],
        "shared_media_ids": sorted(shared),
        "exclusive_media_bytes": sum(m.size_bytes for m in media if m.id not in shared),
        "media_bytes": sum(m.size_bytes for m in media),
        "count": len(items),
    }


def references(value, identifiers):
    """UUID может быть значением JSON или частью ключа зависимости item:UUID."""
    if isinstance(value, str):
        return any(identifier in value for identifier in identifiers)
    if isinstance(value, dict):
        return any(
            references(key, identifiers) or references(part, identifiers) for key, part in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(references(part, identifiers) for part in value)
    return False


async def deletion_scope(db, workspace_id, item_ids):
    """Связанные черновики и задачи включаются транзитивно, включая replay и batch."""
    lots = (
        await db.scalars(select(Lot).where(Lot.workspace_id == workspace_id, Lot.item_id.in_(item_ids)))
    ).all()
    lot_ids = [lot.id for lot in lots]
    balances = (
        await db.scalars(
            select(Balance).where(Balance.workspace_id == workspace_id, Balance.lot_id.in_(lot_ids))
        )
    ).all()
    aliases = (
        await db.scalars(select(Alias).where(Alias.workspace_id == workspace_id, Alias.item_id.in_(item_ids)))
    ).all()
    entity_ids = set(item_ids) | set(lot_ids) | {row.id for row in [*balances, *aliases]}
    entries = (
        await db.scalars(
            select(Entry)
            .join(Operation, Entry.operation_id == Operation.id)
            .where(Operation.workspace_id == workspace_id, Entry.entity_id.in_(entity_ids))
        )
    ).all()
    operations = (
        await db.scalars(
            select(Operation).where(
                Operation.workspace_id == workspace_id, Operation.id.in_({e.operation_id for e in entries})
            )
        )
    ).all()
    confirmations = (
        await db.scalars(select(Confirmation).where(Confirmation.workspace_id == workspace_id))
    ).all()
    proposals = (await db.scalars(select(Proposal).where(Proposal.workspace_id == workspace_id))).all()
    tasks = (await db.scalars(select(Task).where(Task.workspace_id == workspace_id))).all()
    affected = entity_ids | {o.id for o in operations} | {o.confirmation_id for o in operations}
    while True:
        previous = len(affected)
        for row in confirmations:
            if row.id in affected or references([row.proposal_id, row.actions, row.dependencies], affected):
                affected.update([row.id, row.proposal_id, row.receipt_id])
        for row in proposals:
            if row.id in affected or references(
                [row.task_id, row.actions, row.dependencies, row.document, row.source_proposals], affected
            ):
                affected.add(row.id)
                if row.task_id:
                    affected.add(row.task_id)
        for row in tasks:
            if row.id in affected or references(
                [row.parent_task_id, row.proposal_id, row.context, row.result], affected
            ):
                affected.add(row.id)
        if len(affected) == previous:
            break
    return {
        "lots": lots,
        "balances": balances,
        "entries": entries,
        "operations": operations,
        "confirmations": [c for c in confirmations if c.id in affected],
        "proposals": [p for p in proposals if p.id in affected],
        "tasks": [t for t in tasks if t.id in affected],
        "ids": affected,
    }


async def block_deleted_data(db, workspace_id, item_ids):
    affected = await deletion_scope(db, workspace_id, item_ids)
    for operation in affected["operations"]:
        operation.status = "deleted"
    for proposal in affected["proposals"]:
        proposal.status = "deleted"
        proposal.document = {
            "schema_version": "review.v1",
            "proposal_id": proposal.id,
            "status": "deleted",
            "can_confirm": False,
            "available_actions": [],
        }
    for confirmation in affected["confirmations"]:
        if confirmation.status != "applied":
            confirmation.status, confirmation.error_code = "conflict", "ITEM_DELETED"
            confirmation.fencing_token += 1
        confirmation.result = {"deleted": True}
    for task in affected["tasks"]:
        task.input_text, task.context, task.result, task.progress = (
            None,
            {"deleted": True, "deleted_item_ids": sorted(item_ids)},
            {"deleted": True},
            {},
        )
        task.media_ids, task.audio_media_id = [], None
        task.fencing_token += 1
        task.cancel_requested_at = utcnow()
        task.status_version += 1
        if task.status not in {"succeeded", "failed", "cancelled", "expired"}:
            task.status = "cancelled"
    task_ids = {task.id for task in affected["tasks"]}
    bindings = (await db.scalars(select(Binding).where(Binding.workspace_id == workspace_id))).all()
    targeted = [
        b
        for b in bindings
        if b.entity_type == "item"
        and b.entity_id in item_ids
        or b.entity_type == "task"
        and b.entity_id in task_ids
    ]
    live_items = set(
        (
            await db.scalars(
                select(Item.id).where(Item.workspace_id == workspace_id, Item.lifecycle != "deleted")
            )
        ).all()
    )
    live_tasks = {
        t.id
        for t in (
            await db.scalars(
                select(Task).where(
                    Task.workspace_id == workspace_id,
                    Task.status.notin_(["succeeded", "failed", "expired", "cancelled"]),
                )
            )
        ).all()
        if not t.context.get("deleted")
    }
    other_media = {
        b.media_id
        for b in bindings
        if b not in targeted
        and (
            b.entity_type == "item"
            and b.entity_id in live_items
            or b.entity_type == "task"
            and b.entity_id in live_tasks
        )
    }
    for media_id in {b.media_id for b in targeted} - other_media:
        media = await db.get(Media, media_id)
        if media.state == "uploaded":
            media.state = "blocked"
    # Кэшированные ответы и готовые экспорты тоже являются копиями удаляемых данных.
    for cached in (
        await db.scalars(select(Idempotency).where(Idempotency.workspace_id == workspace_id))
    ).all():
        if references(cached.response, affected["ids"]):
            cached.response = {"status": "deleted", "code": "DATA_DELETED"}
    for job in (
        await db.scalars(
            select(Job).where(
                Job.workspace_id == workspace_id,
                Job.kind == "export",
                Job.status.in_(["queued", "running", "succeeded"]),
            )
        )
    ).all():
        job.status, job.expires_at = "revoked", utcnow()
    for occurrence in (
        await db.scalars(
            select(Occurrence).where(
                Occurrence.workspace_id == workspace_id,
                Occurrence.subject_lot_id.in_([lot.id for lot in affected["lots"]]),
            )
        )
    ).all():
        if occurrence.status != "delivered":
            occurrence.status = "cancelled"
    for notification in (
        await db.scalars(select(Notification).where(Notification.workspace_id == workspace_id))
    ).all():
        if references(notification.subjects, affected["ids"]):
            notification.body, notification.subjects, notification.dismissed_at = "Удалено", [], utcnow()
    return affected


async def confirm_purge(db, preview, user_id, preview_hash):
    require(
        preview.kind == "deletion_preview" and preview.status == "preview",
        "INVALID_PREVIEW",
        "Предпросмотр недоступен.",
    )
    require(preview.manifest_hash == preview_hash, "VERSION_CONFLICT", "Предпросмотр уже изменился.")
    current = await deletion_manifest(db, preview.workspace_id, [r["id"] for r in preview.manifest["items"]])
    require(
        digest(current) == preview_hash,
        "REVIEW_UPDATE_REQUIRED",
        "Область удаления изменилась; создайте новый предпросмотр.",
    )
    revision, settings = await effective_settings(db)
    current["policy_revision"] = revision
    job = Job(
        id=uid(),
        workspace_id=preview.workspace_id,
        created_by=user_id,
        kind="purge",
        manifest=current,
        manifest_hash=digest(current),
        not_before=utcnow() + timedelta(days=settings["retention.purge_grace_days"]),
        status="queued",
    )
    db.add(job)
    for target in current["items"]:
        item = await db.get(Item, target["id"])
        item.lifecycle, item.deleted_at = "deleted", utcnow()
        item.version += 1
        item.search_revision = item.version
        if not await db.scalar(
            select(Tombstone.id).where(Tombstone.entity_type == "item", Tombstone.entity_id == item.id)
        ):
            db.add(Tombstone(workspace_id=item.workspace_id, entity_type="item", entity_id=item.id))
        db.add(
            Outbox(
                workspace_id=item.workspace_id,
                event_type="index_item",
                entity_id=item.id,
                entity_version=item.version,
            )
        )
    await block_deleted_data(db, preview.workspace_id, {r["id"] for r in current["items"]})
    workspace = await db.get(Workspace, preview.workspace_id)
    workspace.version += 1
    preview.status = "confirmed"
    db.add(
        Audit(actor_id=user_id, action="purge.confirm", details={"job_id": job.id, "count": current["count"]})
    )
    await db.flush()
    return job


async def cancel_purge(db, job, expected_version, user_id):
    require(job.kind == "purge", "NOT_FOUND", "Задание не найдено.", 404)
    require(job.version == expected_version, "VERSION_CONFLICT", "Задание удаления изменилось.")
    require(
        job.status == "queued",
        "PURGE_ALREADY_STARTED",
        "Физическая очистка уже началась; отменить её нельзя.",
    )
    targets = {entry["id"] for entry in job.manifest["items"]}
    restored_scope = await deletion_scope(db, job.workspace_id, targets)
    for item_id in targets:
        item = await db.get(Item, item_id)
        if item.lifecycle == "deleted":
            # Явное восстановление делает карточку активной, иначе автоочистка архива удалит её снова.
            item.lifecycle, item.deleted_at, item.archived_at = "active", None, None
            item.version += 1
            item.search_revision = item.version
            db.add(
                Outbox(
                    workspace_id=job.workspace_id,
                    event_type="index_item",
                    entity_id=item.id,
                    entity_version=item.version,
                )
            )
    await db.execute(
        delete(Tombstone).where(
            Tombstone.workspace_id == job.workspace_id,
            Tombstone.entity_type == "item",
            Tombstone.entity_id.in_(targets),
            Tombstone.purged_at.is_(None),
        )
    )
    media_ids = select(Binding.media_id).where(
        Binding.workspace_id == job.workspace_id,
        Binding.entity_type == "item",
        Binding.entity_id.in_(targets),
    )
    for media in (
        await db.scalars(select(Media).where(Media.id.in_(media_ids), Media.state == "blocked"))
    ).all():
        media.state = "uploaded"
    await db.flush()
    remaining = list(
        (
            await db.scalars(
                select(Item.id).where(Item.workspace_id == job.workspace_id, Item.lifecycle == "deleted")
            )
        ).all()
    )
    blocked = await deletion_scope(db, job.workspace_id, remaining) if remaining else {"operations": []}
    blocked_operations = {operation.id for operation in blocked["operations"]}
    for operation in restored_scope["operations"]:
        if operation.id not in blocked_operations and operation.status == "deleted":
            operation.status = "applied"
    workspace = await db.get(Workspace, job.workspace_id)
    workspace.version += 1
    job.status, job.result = "cancelled", {"restored_items": len(targets)}
    job.version += 1
    db.add(Outbox(workspace_id=job.workspace_id, event_type="plan_reminders", entity_id=job.workspace_id))
    db.add(Audit(actor_id=user_id, action="purge.cancel", details={"job_id": job.id, "count": len(targets)}))
    return job


async def purge_job(factory, job_id):
    async with factory() as db:
        current = await db.get(Job, job_id)
        if current.status == "purging":
            await finish_purge(factory, job_id, current.manifest["objects"], current.manifest["item_ids"])
            return
    async with factory() as db, db.begin():
        job = await db.get(Job, job_id)
        await db.get(Workspace, job.workspace_id, with_for_update=True)
        if job.status != "queued" or job.not_before and aware(job.not_before) > utcnow():
            return
        item_ids = list(
            (
                await db.scalars(
                    select(Item.id).where(
                        Item.workspace_id == job.workspace_id,
                        Item.id.in_([r["id"] for r in job.manifest["items"]]),
                        Item.lifecycle == "deleted",
                    )
                )
            ).all()
        )
        if not item_ids:
            job.status, job.result = "cancelled", {"reason": "restored"}
            return
        affected = await block_deleted_data(db, job.workspace_id, set(item_ids))
        lots = affected["lots"]
        lot_ids = [lot.id for lot in lots]
        balances = affected["balances"]
        entries = affected["entries"]
        operations, confirmations, proposals = (
            affected["operations"],
            affected["confirmations"],
            affected["proposals"],
        )
        task_ids = {t.id for t in affected["tasks"]}
        bindings = (
            await db.scalars(
                select(Binding).where(
                    Binding.workspace_id == job.workspace_id,
                    ((Binding.entity_type == "item") & Binding.entity_id.in_(item_ids))
                    | ((Binding.entity_type == "task") & Binding.entity_id.in_(task_ids)),
                )
            )
        ).all()
        media_ids = {b.media_id for b in bindings}
        for binding in bindings:
            await db.delete(binding)
        await db.flush()
        objects = []
        for media_id in media_ids:
            if not await db.scalar(select(Binding.id).where(Binding.media_id == media_id).limit(1)):
                media = await db.get(Media, media_id)
                media.state = "purging"
                objects.append({"media_id": media.id, "object_key": media.object_key})
        for item_id in item_ids:
            item = await db.get(Item, item_id)
            item.name, item.attributes, item.tags = "Удалённый объект", {}, []
            item.brand = item.model = item.barcode = item.user_description = item.generated_description = None
            item.secondary_categories = []
            item.description_model_revision = None
        for lot in lots:
            lot.label = lot.serial_number = lot.manufacturer_batch = lot.expiry_raw_text = None
            lot.attributes = {}
            lot.expiry_on = lot.effective_expiry_on = lot.manufactured_on = lot.opened_on = (
                lot.acquired_at
            ) = None
            lot.after_opening_amount = lot.after_opening_unit = None
            lot.expiry_precision = lot.expiry_derivation = "unknown"
        for balance in balances:
            balance.quantity, balance.quantity_state = None, "unknown"
            balance.last_confirmed_at = balance.last_confirmed_by = None
        for entry in entries:
            entry.before_state = None
            entry.after_state = {"purged": True}
            entry.quantity_delta = entry.unit_id = entry.from_location_id = entry.to_location_id = None
        for operation in operations:
            operation.normalized_payload = []
            operation.status = "purged"
        for confirmation in confirmations:
            confirmation.actions, confirmation.result = [], {"purged": True}
            confirmation.dependencies = {}
            receipt = await db.get(Receipt, confirmation.receipt_id)
            receipt.explicit_changes = []
        for proposal in proposals:
            proposal.actions, proposal.user_changes, proposal.warnings = [], [], []
            proposal.status, proposal.dependencies = "purged", {}
            proposal.document = {
                "schema_version": "review.v1",
                "proposal_id": proposal.id,
                "status": "purged",
                "can_confirm": False,
            }
            revisions = (
                await db.scalars(select(ProposalRevision).where(ProposalRevision.proposal_id == proposal.id))
            ).all()
            for revision in revisions:
                revision.document = proposal.document
        for task_id in task_ids:
            task = await db.get(Task, task_id)
            task.input_text, task.result, task.media_ids, task.audio_media_id = None, {}, [], None
            task.context, task.progress = {"deleted": True}, {}
            if task.status not in {"succeeded", "failed", "cancelled", "expired"}:
                task.status, task.fencing_token = "cancelled", task.fencing_token + 1
                task.status_version += 1
        for attempt in (
            await db.scalars(
                select(Attempt).where(Attempt.workspace_id == job.workspace_id, Attempt.task_id.in_(task_ids))
            )
        ).all():
            attempt.diagnostics = {}
        await db.execute(
            delete(Alias).where(Alias.workspace_id == job.workspace_id, Alias.item_id.in_(item_ids))
        )
        await db.execute(
            delete(Evidence).where(
                Evidence.workspace_id == job.workspace_id,
                Evidence.entity_id.in_(affected["ids"]) | Evidence.proposal_id.in_([p.id for p in proposals]),
            )
        )
        occurrences = (
            await db.scalars(select(Occurrence).where(Occurrence.subject_lot_id.in_(lot_ids)))
        ).all()
        for occurrence in occurrences:
            occurrence.status = "cancelled"
        notifications = (
            await db.scalars(select(Notification).where(Notification.workspace_id == job.workspace_id))
        ).all()
        for notification in notifications:
            if any(s.get("item_id") in item_ids for s in notification.subjects):
                notification.body, notification.subjects, notification.dismissed_at = "Удалено", [], utcnow()
        for old_job in (
            await db.scalars(
                select(Job).where(Job.workspace_id == job.workspace_id, Job.kind == "deletion_preview")
            )
        ).all():
            if references(old_job.manifest, affected["ids"]):
                old_job.manifest = {"purged": True}
        for event in (await db.scalars(select(Outbox).where(Outbox.workspace_id == job.workspace_id))).all():
            if references(event.payload, affected["ids"]):
                event.payload = {}
        job.manifest = {"item_ids": item_ids, "objects": objects}
        job.status = "purging"
    # Сначала блокируется чтение в БД, затем повторяемо удаляются байты.
    await finish_purge(factory, job_id, objects, item_ids)


async def finish_purge(factory, job_id, objects, item_ids):
    storage = Storage()
    for obj in objects:
        await storage.delete(obj["object_key"])
    async with factory() as db, db.begin():
        job = await db.get(Job, job_id, with_for_update=True)
        for obj in objects:
            media = await db.get(Media, obj["media_id"])
            media.state, media.manifest = "purged", {}
            media.sha256, media.size_bytes, media.width, media.height, media.duration_seconds = (
                "",
                0,
                None,
                None,
                None,
            )
        tombstones = (await db.scalars(select(Tombstone).where(Tombstone.entity_id.in_(item_ids)))).all()
        for tombstone in tombstones:
            tombstone.purged_at = utcnow()
        job.status, job.result = "succeeded", {"purged_items": len(item_ids), "purged_objects": len(objects)}
        job.manifest = {"item_ids": item_ids}


async def run_job(factory, job_id):
    async with factory() as db:
        job = await db.get(Job, job_id)
        kind = job.kind
    if kind == "export":
        await export_job(factory, job_id)
    elif kind == "purge":
        await purge_job(factory, job_id)
    elif kind == "reindex":
        from app.application.search import rebuild_index

        collection = "inventory_rebuild_" + job_id.replace("-", "")
        ready = await rebuild_index(factory, job.workspace_id, collection)
        async with factory() as db, db.begin():
            job = await db.get(Job, job_id)
            job.status = "succeeded" if ready else "queued"
            job.result = {"collection": collection, "alias_switched": ready}
        if not ready:
            raise RuntimeError("Индекс изменился или GPU занята; перестройка будет повторена")


TERMINAL_TASKS = {"succeeded", "cancelled", "failed", "expired"}


async def cleanup_scope(db, settings, now):
    """Один расчёт кандидатов используется очисткой и предварительным просмотром политики."""
    items = (await db.scalars(select(Item))).all()
    tasks = {row.id: row for row in (await db.scalars(select(Task))).all()}
    media = (await db.scalars(select(Media).where(Media.state.in_(["uploaded", "purging"])))).all()
    bindings = (await db.scalars(select(Binding))).all()
    proposals = (await db.scalars(select(Proposal).where(Proposal.status == "editable"))).all()
    archive_days = settings["retention.archived_auto_purge_days"]
    task_days = settings["retention.task_input_days"]
    photo_days = settings["retention.source_photo_days"]
    draft_days = settings["retention.review_draft_days"]
    archived = {
        row.id
        for row in items
        if archive_days is not None
        and row.lifecycle == "archived"
        and row.archived_at
        and aware(row.archived_at) <= now - timedelta(days=archive_days)
    }
    expired_inputs = {
        row.id
        for row in tasks.values()
        if task_days is not None
        and row.status in TERMINAL_TASKS
        and aware(row.created_at) <= now - timedelta(days=task_days)
    }
    input_ids = {
        task_id
        for task_id in expired_inputs
        if any(
            (
                tasks[task_id].input_text,
                tasks[task_id].result,
                tasks[task_id].audio_media_id,
                tasks[task_id].progress,
            )
        )
    }
    draft_ids = {
        row.id
        for row in proposals
        if draft_days is not None and aware(row.created_at) <= now - timedelta(days=draft_days)
    }
    by_media = {}
    for binding in bindings:
        by_media.setdefault(binding.media_id, []).append(binding)
    disposable, detach = [], []
    for asset in media:
        attached = by_media.get(asset.id, [])
        expired_audio = [
            b
            for b in attached
            if b.entity_type == "task"
            and b.entity_id in expired_inputs
            and (asset.mime.startswith("audio/") or asset.kind != "source")
        ]
        remaining = [b for b in attached if b not in expired_audio]
        unused_photo = (
            asset.kind == "source"
            and asset.mime.startswith("image/")
            and photo_days is not None
            and aware(asset.created_at) <= now - timedelta(days=photo_days)
            and all(
                b.entity_type == "task"
                and b.entity_id in tasks
                and tasks[b.entity_id].status in TERMINAL_TASKS
                for b in remaining
            )
        )
        if unused_photo:
            detach.extend(remaining)
            remaining = []
        detach.extend(expired_audio)
        if not remaining and (
            asset.state == "purging"
            or expired_audio
            or unused_photo
            or aware(asset.created_at) <= now - timedelta(hours=settings["retention.orphan_upload_hours"])
        ):
            disposable.append(asset)
    return {
        "archived_items": archived,
        "task_inputs": input_ids,
        "drafts": draft_ids,
        "media": disposable,
        "detach": detach,
        "tasks": tasks,
    }


async def retention_impact(db, current, proposed, now=None):
    now = now or utcnow()
    before = await cleanup_scope(db, current, now)
    after = await cleanup_scope(db, proposed, now)
    current_media = {asset.id for asset in before["media"]}
    additional_media = [asset for asset in after["media"] if asset.id not in current_media]
    queued = (await db.scalars(select(Job).where(Job.kind == "purge", Job.status == "queued"))).all()
    control = await db.get(Control, "maintenance:gc")
    previous = control.value.get("last_completed_at") if control else None
    next_at = (
        max(now, datetime.fromisoformat(previous) + timedelta(hours=proposed["retention.gc_interval_hours"]))
        if previous
        else now
    )
    return {
        "archived_items": len(after["archived_items"] - before["archived_items"]),
        "task_inputs": len(after["task_inputs"] - before["task_inputs"]),
        "review_drafts": len(after["drafts"] - before["drafts"]),
        "media_count": len(additional_media),
        "media_bytes": sum(asset.size_bytes for asset in additional_media),
        "queued_grace_jobs_affected": 0,
        "queued_grace_jobs_preserved": len(queued),
        "types": sorted({asset.mime.split("/")[0] for asset in additional_media}),
        "next_cleanup_at": next_at.isoformat(),
        "first_new_purge_at": (next_at + timedelta(days=proposed["retention.purge_grace_days"])).isoformat()
        if after["archived_items"]
        else None,
        "eligible_total": {
            "archived_items": len(after["archived_items"]),
            "task_inputs": len(after["task_inputs"]),
            "review_drafts": len(after["drafts"]),
            "media_count": len(after["media"]),
            "media_bytes": sum(a.size_bytes for a in after["media"]),
        },
        "policy": "Показаны дополнительные цели относительно действующей политики. Уже подтверждённые сроки удаления сохраняются.",
    }


async def regular_cleanup(factory, now=None, *, force=False):
    now = now or utcnow()
    run_id = uid()
    async with factory() as db, db.begin():
        await db.get(Control, "settings", with_for_update=True)
        control = await db.get(Control, "maintenance:gc", with_for_update=True)
        if control is None:
            control = Control(key="maintenance:gc", value={})
            db.add(control)
        _, settings = await effective_settings(db)
        state = dict(control.value)
        if state.get("lease_until") and datetime.fromisoformat(state["lease_until"]) > now:
            return {"status": "running"}
        if (
            not force
            and state.get("last_completed_at")
            and datetime.fromisoformat(state["last_completed_at"])
            + timedelta(hours=settings["retention.gc_interval_hours"])
            > now
        ):
            return {"status": "not_due"}
        control.value = {**state, "run_id": run_id, "lease_until": (now + timedelta(minutes=30)).isoformat()}
    succeeded = False
    try:
        await _cleanup(factory, now)
        succeeded = True
        return {"status": "completed"}
    finally:
        async with factory() as db, db.begin():
            control = await db.get(Control, "maintenance:gc", with_for_update=True)
            if control.value.get("run_id") == run_id:
                control.value = {
                    **control.value,
                    "run_id": None,
                    "lease_until": None,
                    **({"last_completed_at": now.isoformat()} if succeeded else {}),
                }


async def _cleanup(factory, now):
    now = now or utcnow()
    storage = Storage()
    async with factory() as db, db.begin():
        _, settings = await effective_settings(db)
        archive_days = settings["retention.archived_auto_purge_days"]
        if archive_days is not None:
            archived = (
                await db.scalars(
                    select(Item).where(
                        Item.lifecycle == "archived", Item.archived_at <= now - timedelta(days=archive_days)
                    )
                )
            ).all()
            by_workspace = {}
            for item in archived:
                by_workspace.setdefault(item.workspace_id, []).append(item.id)
            for workspace_id, targets in by_workspace.items():
                workspace = await db.get(Workspace, workspace_id, with_for_update=True)
                for offset in range(0, len(targets), 100):
                    manifest = await deletion_manifest(db, workspace_id, targets[offset : offset + 100])
                    preview = Job(
                        workspace_id=workspace_id,
                        created_by=workspace.owner_user_id,
                        kind="deletion_preview",
                        status="preview",
                        manifest=manifest,
                        manifest_hash=digest(manifest),
                    )
                    db.add(preview)
                    await db.flush()
                    await confirm_purge(db, preview, workspace.owner_user_id, preview.manifest_hash)
        jobs = (
            await db.scalars(
                select(Job).where(
                    Job.kind == "purge", Job.status.in_(["queued", "purging"]), Job.not_before <= now
                )
            )
        ).all()
        purge_ids = [j.id for j in jobs]
        expired_exports = (
            await db.scalars(
                select(Job).where(
                    Job.kind == "export",
                    Job.status.in_(["succeeded", "expired", "revoked"]),
                    Job.expires_at <= now,
                )
            )
        ).all()
        expired_keys = [
            (job.id, job.result.get("object_key", f"{job.workspace_id}/exports/{job.id}"))
            for job in expired_exports
        ]
        for job in expired_exports:
            job.status = "expired"
        cleanup = await cleanup_scope(db, settings, now)
        for proposal_id in cleanup["drafts"]:
            proposal = await db.get(Proposal, proposal_id)
            proposal.status = "expired"
            proposal.document = {
                **proposal.document,
                "status": "expired",
                "can_confirm": False,
                "available_actions": [],
            }
        for task in cleanup["tasks"].values():
            if task.id in cleanup["task_inputs"]:
                task.input_text, task.result = None, {}
                task.audio_media_id, task.progress = None, {}
                task.context = task.context if task.context.get("deleted") else {}
            if (
                task.proposal_id in cleanup["drafts"] or task.deadline_at and aware(task.deadline_at) < now
            ) and task.status in {"accepted", "queued", "retry_wait", "waiting_for_review"}:
                task.status, task.status_version = "expired", task.status_version + 1
                task.fencing_token += 1
                if task.proposal_id:
                    proposal = await db.get(Proposal, task.proposal_id)
                    proposal.status = "expired"
                    proposal.document = {
                        **proposal.document,
                        "status": "expired",
                        "can_confirm": False,
                        "available_actions": [],
                    }
        for binding in cleanup["detach"]:
            task = cleanup["tasks"].get(binding.entity_id)
            if task:
                task.media_ids = [media_id for media_id in task.media_ids if media_id != binding.media_id]
            await db.delete(binding)
        orphan_media = cleanup["media"]
        for media in orphan_media:
            media.state = "purging"
        orphan_keys = [(m.id, m.object_key) for m in orphan_media]
        referenced = set((await db.scalars(select(Media.object_key).where(Media.state != "purged"))).all())
        for export in (
            await db.scalars(
                select(Job).where(Job.kind == "export", Job.status.in_(["queued", "running", "succeeded"]))
            )
        ).all():
            referenced.add(f"{export.workspace_id}/exports/{export.id}")
    for job_id, key in expired_keys:
        await storage.delete(key)
        async with factory() as db, db.begin():
            job = await db.get(Job, job_id)
            job.result = {"expired": True}
    for media_id, key in orphan_keys:
        await storage.delete(key)
        async with factory() as db, db.begin():
            media = await db.get(Media, media_id)
            media.state = "purged"
    for object_ in await storage.objects():
        if object_["key"] not in referenced and aware(object_["modified_at"]) < now - timedelta(
            hours=settings["retention.orphan_upload_hours"]
        ):
            await storage.delete(object_["key"])
    for job_id in purge_ids:
        await purge_job(factory, job_id)
