import base64
import json
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import and_, exists, not_, select

from app.api.deps import database, idempotency_key, scope, write_scope
from app.application import proposals
from app.application.idempotency import previous_response, remember
from app.application.inventory import row_state
from app.application.photos import item_photos
from app.db.models import Alias, Balance, Confirmation, Entry, Item, Location, Lot, Operation, Proposal, Task
from app.db.session import scoped_get
from app.domain.common import jsonable
from app.domain.errors import DomainError, require
from app.domain.reference import ATTRIBUTES, CATEGORIES, UNITS
from app.domain.rules import aggregate, transition
from app.domain.schemas import ConfirmProposal, EditProposal, ManualConfirm, ManualProposal, StrictModel

router = APIRouter()


def serialize(row):
    return jsonable(row_state(row))


async def page(db, query, model, limit=50, cursor=None, render=serialize):
    if cursor:
        try:
            last = json.loads(base64.urlsafe_b64decode(cursor))
            require(
                last["type"] == model.__tablename__,
                "INVALID_CURSOR",
                "Курсор относится к другому списку.",
                400,
            )
            query = query.where(model.id > str(UUID(last["id"])))
        except (ValueError, KeyError, TypeError) as exc:
            raise DomainError("INVALID_CURSOR", "Некорректный курсор.", 400) from exc
    rows = (await db.scalars(query.order_by(model.id).limit(limit + 1))).all()
    more = len(rows) > limit
    rows = rows[:limit]
    cursor = (
        base64.urlsafe_b64encode(
            json.dumps({"type": model.__tablename__, "id": rows[-1].id}).encode()
        ).decode()
        if more
        else None
    )
    return {"items": [render(row) for row in rows], "next_cursor": cursor, "has_more": more}


async def item_view(db, item, photos=None):
    lots = (
        await db.scalars(select(Lot).where(Lot.workspace_id == item.workspace_id, Lot.item_id == item.id))
    ).all()
    balances = (
        await db.scalars(
            select(Balance).where(
                Balance.workspace_id == item.workspace_id, Balance.lot_id.in_([lot.id for lot in lots])
            )
        )
    ).all()
    active_lots = {lot.id for lot in lots if lot.archived_at is None}
    result = {
        **serialize(item),
        **aggregate([balance for balance in balances if balance.lot_id in active_lots], item.tracking_mode),
        "lots": [serialize(lot) for lot in lots],
        "balances": [serialize(b) for b in balances],
        "photos": photos
        if photos is not None
        else (await item_photos(db, item.workspace_id, [item.id]))[item.id],
    }
    if item.base_unit_id == "pcs" and item.attributes.get("counting_unit") == "pair":
        from decimal import Decimal

        count = Decimal(result["known_quantity"])
        result["quantity_display"] = {
            "unit_code": "pair",
            "complete_pairs": int(count // 2),
            "single_pieces": str(count % 2),
            "has_unknown_quantity": result["has_unknown_quantity"],
        }
    return result


@router.get("/reference/categories")
async def categories(selected=Depends(scope)):
    return {
        "schema_version": "categories.v1",
        "items": [{"code": k, "name": v, "attributes": sorted(ATTRIBUTES[k])} for k, v in CATEGORIES.items()],
    }


@router.get("/reference/units")
async def units(selected=Depends(scope)):
    return {
        "schema_version": "units.v1",
        "items": [
            {"code": k, "display_name": v[0], "dimension": v[1], "factor": v[2], "default_step": v[3]}
            for k, v in UNITS.items()
        ],
    }


@router.get("/forms")
async def forms(operation: str = "receive_stock", category: str = "other", selected=Depends(scope)):
    from app.domain.schemas import COMMANDS, Action

    require(operation in COMMANDS, "UNSUPPORTED_OPERATION", "Операция не поддерживается.", 422)
    if operation in {"reverse_operation", "merge_lots"}:
        return {
            "schema_version": "command.v1",
            "type": operation,
            "values_schema": COMMANDS[operation].model_json_schema(),
        }
    values = {"category": category} if operation == "receive_stock" else {}
    action = Action(type=operation, values=values).model_dump(mode="json")
    return {
        "schema_version": "review.v1",
        "type": operation,
        "actions": [action],
        "fields": proposals.form_fields([action], "manual"),
    }


@router.post("/proposals/manual", status_code=201)
async def manual_proposal(
    data: ManualProposal, key=Depends(idempotency_key), selected=Depends(write_scope), db=Depends(database)
):
    body = data.model_dump(mode="json")
    cached = await previous_response(
        db, selected.user.id, selected.workspace_id, "manual_proposal", key, body
    )
    if cached:
        return cached
    proposal = await proposals.create_proposal(db, selected.workspace_id, selected.user.id, body["actions"])
    if data.expected_versions and await proposals.dependencies_changed(db, proposal, data.expected_versions):
        raise proposals.PersistedConflict(
            "REVIEW_UPDATE_REQUIRED", "Исходные версии изменились.", review=proposal.document
        )
    return remember(
        db, selected.user.id, selected.workspace_id, "manual_proposal", key, body, proposal.document
    )


@router.post("/commands/manual-confirm", status_code=202)
async def manual_confirm(
    data: ManualConfirm, key=Depends(idempotency_key), selected=Depends(write_scope), db=Depends(database)
):
    body = data.model_dump(mode="json")
    cached = await previous_response(db, selected.user.id, selected.workspace_id, "manual_confirm", key, body)
    if cached:
        return cached
    proposal = await proposals.create_proposal(db, selected.workspace_id, selected.user.id, body["actions"])
    if data.expected_versions and await proposals.dependencies_changed(db, proposal, data.expected_versions):
        raise proposals.PersistedConflict(
            "REVIEW_UPDATE_REQUIRED", "Учёт уже изменился.", review=proposal.document
        )
    result = await proposals.accept_confirmation(
        db,
        proposal,
        selected.user.id,
        {
            "expected_revision": proposal.revision,
            "observed_review_hash": proposal.review_hash,
            "changes": [],
            "client_request_id": str(data.client_request_id),
        },
    )
    return remember(db, selected.user.id, selected.workspace_id, "manual_confirm", key, body, result)


@router.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: UUID, selected=Depends(scope), db=Depends(database)):
    proposal = await scoped_get(db, Proposal, proposal_id, selected.workspace_id)
    require(proposal.status not in {"deleted", "purged"}, "NOT_FOUND", "Предложение удалено.", 404)
    return proposal.document


@router.patch("/proposals/{proposal_id}")
async def edit_proposal(
    proposal_id: UUID,
    data: EditProposal,
    key=Depends(idempotency_key),
    selected=Depends(write_scope),
    db=Depends(database),
):
    body = data.model_dump(mode="json")
    operation_scope = f"edit_proposal:{proposal_id}"
    cached = await previous_response(db, selected.user.id, selected.workspace_id, operation_scope, key, body)
    if cached:
        return cached
    proposal = await scoped_get(db, Proposal, proposal_id, selected.workspace_id, lock=True)
    result = await proposals.edit_proposal(db, proposal, data.expected_revision, body["changes"])
    return remember(db, selected.user.id, selected.workspace_id, operation_scope, key, body, result)


@router.post("/proposals/{proposal_id}/confirm", status_code=202)
async def confirm(
    proposal_id: UUID,
    data: ConfirmProposal,
    key=Depends(idempotency_key),
    selected=Depends(write_scope),
    db=Depends(database),
):
    body = data.model_dump(mode="json")
    operation_scope = f"confirm:{proposal_id}"
    cached = await previous_response(db, selected.user.id, selected.workspace_id, operation_scope, key, body)
    if cached:
        return cached
    proposal = await scoped_get(db, Proposal, proposal_id, selected.workspace_id, lock=True)
    result = await proposals.accept_confirmation(db, proposal, selected.user.id, body)
    return remember(db, selected.user.id, selected.workspace_id, operation_scope, key, body, result)


@router.post("/proposals/{proposal_id}/cancel")
async def cancel_proposal(
    proposal_id: UUID, key=Depends(idempotency_key), selected=Depends(write_scope), db=Depends(database)
):
    proposal = await scoped_get(db, Proposal, proposal_id, selected.workspace_id, lock=True)
    require(
        proposal.status in {"editable", "cancelled"},
        "ALREADY_CONFIRMED",
        "Подтверждённое предложение нельзя отменить.",
    )
    if proposal.status != "cancelled":
        proposal.status = "cancelled"
        proposal.document = {
            **proposal.document,
            "status": "cancelled",
            "can_confirm": False,
            "available_actions": [],
        }
        if proposal.task_id:
            transition(await db.get(Task, proposal.task_id), "cancelled")
    return proposal.document


@router.get("/confirmations/{confirmation_id}")
async def get_confirmation(confirmation_id: UUID, selected=Depends(scope), db=Depends(database)):
    return proposals.confirmation_view(
        await scoped_get(db, Confirmation, confirmation_id, selected.workspace_id)
    )


@router.post("/confirmations/{confirmation_id}/retry", status_code=202)
async def retry_confirmation(
    confirmation_id: UUID, key=Depends(idempotency_key), selected=Depends(write_scope), db=Depends(database)
):
    operation_scope = f"retry_confirmation:{confirmation_id}"
    cached = await previous_response(db, selected.user.id, selected.workspace_id, operation_scope, key, {})
    if cached:
        return cached
    confirmation = await scoped_get(db, Confirmation, confirmation_id, selected.workspace_id, lock=True)
    result = await proposals.retry_confirmation(db, confirmation)
    return remember(db, selected.user.id, selected.workspace_id, operation_scope, key, {}, result)


class ProposalSource(StrictModel):
    proposal_id: UUID
    revision: int = Field(ge=1)


class ReviewBatch(StrictModel):
    sources: list[ProposalSource] = Field(min_length=2, max_length=50)


@router.post("/review-batches", status_code=201)
async def combine(
    data: ReviewBatch, key=Depends(idempotency_key), selected=Depends(write_scope), db=Depends(database)
):
    body = data.model_dump(mode="json")
    cached = await previous_response(db, selected.user.id, selected.workspace_id, "review_batch", key, body)
    if cached:
        return cached
    result = await proposals.combine(db, selected.workspace_id, selected.user.id, body["sources"])
    return remember(db, selected.user.id, selected.workspace_id, "review_batch", key, body, result)


@router.get("/review-batches/{proposal_id}")
async def review_batch(proposal_id: UUID, selected=Depends(scope), db=Depends(database)):
    proposal = await scoped_get(db, Proposal, proposal_id, selected.workspace_id)
    require(proposal.status not in {"deleted", "purged"}, "NOT_FOUND", "Предложение удалено.", 404)
    require(proposal.source_proposals, "NOT_FOUND", "Общее предложение не найдено.", 404)
    return proposal.document


class BatchConfirmation(ConfirmProposal):
    proposal_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=200)


class BatchConfirm(StrictModel):
    items: list[BatchConfirmation] = Field(min_length=1, max_length=20)


@router.post("/review-inbox/batch-confirm", status_code=202)
async def batch_confirm(data: BatchConfirm, selected=Depends(write_scope), db=Depends(database)):
    results = []
    for entry in data.items:
        body = entry.model_dump(mode="json", exclude={"proposal_id", "idempotency_key"})
        operation_scope = f"confirm:{entry.proposal_id}"
        try:
            async with db.begin_nested():
                cached = await previous_response(
                    db, selected.user.id, selected.workspace_id, operation_scope, entry.idempotency_key, body
                )
                if cached:
                    results.append(cached)
                    continue
                proposal = await scoped_get(db, Proposal, entry.proposal_id, selected.workspace_id)
                try:
                    result = await proposals.accept_confirmation(db, proposal, selected.user.id, body)
                except proposals.PersistedConflict as error:
                    # Пересчитанная форма сохраняется вместе с частичным результатом,
                    # а обычные ошибки откатывают только свой элемент пакета.
                    results.append(
                        {
                            "proposal_id": str(entry.proposal_id),
                            "status": "error",
                            "error": {"code": error.code, "message": error.message, **error.details},
                        }
                    )
                    continue
                results.append(
                    remember(
                        db,
                        selected.user.id,
                        selected.workspace_id,
                        operation_scope,
                        entry.idempotency_key,
                        body,
                        result,
                    )
                )
        except DomainError as error:
            results.append(
                {
                    "proposal_id": str(entry.proposal_id),
                    "status": "error",
                    "error": {"code": error.code, "message": error.message},
                }
            )
    return {"items": results}


@router.get("/review-inbox")
async def review_inbox(
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
    batch_id: UUID | None = None,
    selected=Depends(scope),
    db=Depends(database),
):
    query = select(Proposal).where(
        Proposal.workspace_id == selected.workspace_id, Proposal.status == "editable"
    )
    if batch_id:
        query = query.join(Task, Proposal.task_id == Task.id).where(Task.batch_id == str(batch_id))
    return await page(
        db,
        query,
        Proposal,
        limit,
        cursor,
        lambda p: {
            "proposal_id": p.id,
            "task_id": p.task_id,
            "summary": p.document["summary"],
            "can_confirm": p.document["can_confirm"],
            "blocking_count": len(p.document["blocking_issues"]),
            "revision": p.revision,
            "effective_privacy": p.document["effective_privacy"],
            "created_at": p.created_at.isoformat(),
            "link": f"/api/v1/proposals/{p.id}",
        },
    )


@router.get("/items")
async def items(
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
    category: str | None = None,
    include_archived: bool = False,
    availability: str | None = None,
    selected=Depends(scope),
    db=Depends(database),
):
    query = select(Item).where(
        Item.workspace_id == selected.workspace_id,
        Item.lifecycle.in_(["active", "archived"] if include_archived else ["active"]),
    )
    if category:
        query = query.where(Item.primary_category == category)
    if availability:
        require(
            availability in {"available", "depleted"}, "INVALID_FILTER", "Неизвестный фильтр наличия.", 422
        )
        remains = exists(
            select(Balance.id)
            .join(Lot, Balance.lot_id == Lot.id)
            .where(
                Lot.item_id == Item.id,
                Lot.workspace_id == selected.workspace_id,
                Lot.archived_at.is_(None),
                (Balance.quantity > 0) | (Balance.quantity_state == "unknown"),
            )
        )
        depleted = and_(Item.tracking_mode != "untracked", not_(remains))
        query = query.where(depleted if availability == "depleted" else not_(depleted))
    result = await page(db, query, Item, limit, cursor)
    photos = await item_photos(db, selected.workspace_id, [item["id"] for item in result["items"]])
    result["items"] = [
        await item_view(db, await db.get(Item, item["id"]), photos[item["id"]]) for item in result["items"]
    ]
    return result


@router.get("/items/{item_id}")
async def get_item(item_id: UUID, selected=Depends(scope), db=Depends(database)):
    item = await scoped_get(db, Item, item_id, selected.workspace_id)
    require(item.lifecycle != "deleted", "NOT_FOUND", "Карточка удалена.", 404)
    return await item_view(db, item)


@router.get("/items/{item_id}/lots")
async def item_lots(item_id: UUID, selected=Depends(scope), db=Depends(database)):
    return {"items": (await get_item(item_id, selected, db))["lots"], "has_more": False, "next_cursor": None}


@router.get("/items/{item_id}/balances")
async def item_balances(item_id: UUID, selected=Depends(scope), db=Depends(database)):
    view = await get_item(item_id, selected, db)
    return {
        "items": view["balances"],
        **{k: view[k] for k in ("known_quantity", "has_unknown_quantity", "is_estimated", "depleted")},
    }


@router.get("/items/{item_id}/aliases")
async def aliases(
    item_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
    selected=Depends(scope),
    db=Depends(database),
):
    await get_item(item_id, selected, db)
    return await page(
        db,
        select(Alias).where(
            Alias.workspace_id == selected.workspace_id, Alias.item_id == str(item_id), Alias.active.is_(True)
        ),
        Alias,
        limit,
        cursor,
    )


@router.get("/lots/{lot_id}")
async def get_lot(lot_id: UUID, selected=Depends(scope), db=Depends(database)):
    lot = await scoped_get(db, Lot, lot_id, selected.workspace_id)
    await get_item(UUID(lot.item_id), selected, db)
    return serialize(lot)


async def location_tree(db, workspace_id):
    locations = (
        await db.scalars(
            select(Location)
            .where(Location.workspace_id == workspace_id, Location.archived_at.is_(None))
            .order_by(Location.name, Location.id)
        )
    ).all()
    by_id = {r.id: r for r in locations}
    result = []
    for row in locations:
        names = [row.name]
        current = row
        while current.parent_id in by_id:
            current = by_id[current.parent_id]
            names.insert(0, current.name)
        result.append({**serialize(row), "full_path": " / ".join(names)})
    return result


@router.get("/locations")
async def locations(selected=Depends(scope), db=Depends(database)):
    return {"items": await location_tree(db, selected.workspace_id), "has_more": False, "next_cursor": None}


@router.get("/locations/{location_id}")
async def get_location(location_id: UUID, selected=Depends(scope), db=Depends(database)):
    await scoped_get(db, Location, location_id, selected.workspace_id)
    return next(
        (r for r in await location_tree(db, selected.workspace_id) if r["id"] == str(location_id)), None
    )


@router.get("/locations/{location_id}/contents")
async def location_contents(
    location_id: UUID, recursive: bool = False, selected=Depends(scope), db=Depends(database)
):
    await scoped_get(db, Location, location_id, selected.workspace_id)
    ids = {str(location_id)}
    if recursive:
        rows = await location_tree(db, selected.workspace_id)
        while True:
            expanded = ids | {r["id"] for r in rows if r["parent_id"] in ids}
            if ids == expanded:
                break
            ids = expanded
    item_ids = (
        select(Lot.item_id)
        .join(Balance, Lot.id == Balance.lot_id)
        .where(
            Balance.workspace_id == selected.workspace_id,
            Balance.location_id.in_(ids),
            Lot.archived_at.is_(None),
            (Balance.quantity > 0) | Balance.quantity_state.in_(["unknown", "not_applicable"]),
        )
    )
    rows = (
        await db.scalars(
            select(Item).where(
                Item.workspace_id == selected.workspace_id, Item.lifecycle == "active", Item.id.in_(item_ids)
            )
        )
    ).all()
    return {"items": [await item_view(db, row) for row in rows], "has_more": False, "next_cursor": None}


@router.get("/operations")
async def operations(
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
    selected=Depends(scope),
    db=Depends(database),
):
    return await page(
        db,
        select(Operation).where(
            Operation.workspace_id == selected.workspace_id, Operation.status.not_in(["deleted", "purged"])
        ),
        Operation,
        limit,
        cursor,
    )


@router.get("/operations/{operation_id}")
async def operation(operation_id: UUID, selected=Depends(scope), db=Depends(database)):
    row = await scoped_get(db, Operation, operation_id, selected.workspace_id)
    require(row.status not in {"deleted", "purged"}, "NOT_FOUND", "Операция удалена.", 404)
    entries = (
        await db.scalars(select(Entry).where(Entry.operation_id == row.id).order_by(Entry.ordinal))
    ).all()
    return {**serialize(row), "entries": [serialize(e) for e in entries]}


@router.get("/items/{item_id}/history")
async def history(
    item_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
    selected=Depends(scope),
    db=Depends(database),
):
    view = await get_item(item_id, selected, db)
    ids = [
        str(item_id),
        *[lot["id"] for lot in view["lots"]],
        *[balance["id"] for balance in view["balances"]],
    ]
    operation_ids = select(Entry.operation_id).where(Entry.entity_id.in_(ids))
    return await page(
        db,
        select(Operation).where(
            Operation.workspace_id == selected.workspace_id,
            Operation.status.not_in(["deleted", "purged"]),
            Operation.id.in_(operation_ids),
        ),
        Operation,
        limit,
        cursor,
    )


@router.post("/operations/{operation_id}/reverse-preview", status_code=201)
async def reverse_preview(
    operation_id: UUID, key=Depends(idempotency_key), selected=Depends(write_scope), db=Depends(database)
):
    operation_scope = f"reverse:{operation_id}"
    cached = await previous_response(db, selected.user.id, selected.workspace_id, operation_scope, key, {})
    if cached:
        return cached
    original = await scoped_get(db, Operation, operation_id, selected.workspace_id)
    require(original.status not in {"deleted", "purged"}, "NOT_FOUND", "Операция удалена.", 404)
    proposal = await proposals.create_proposal(
        db,
        selected.workspace_id,
        selected.user.id,
        [{"action_id": "a1", "type": "reverse_operation", "values": {"operation_id": str(operation_id)}}],
    )
    return remember(db, selected.user.id, selected.workspace_id, operation_scope, key, {}, proposal.document)
