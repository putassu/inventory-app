"""Карточки загрузки живут в каталоге до подтверждения, без повторного поступления."""

from sqlalchemy import select

from app.application.inventory import load_state, persist_state
from app.application.photos import bind_photo_variants
from app.db.models import Binding, Entry, Evidence, Item, Operation, Proposal, Task
from app.domain.common import utcnow
from app.domain.errors import DomainError, require
from app.domain.schemas import Action

PLACEHOLDER = "Вещь без названия"


async def edited_during_recognition(db, task, state, item_id):
    lot_ids = {lot["id"] for lot in state.rows["lot"].values() if lot["item_id"] == item_id}
    ids = {item_id, *lot_ids, *(b["id"] for b in state.rows["balance"].values() if b["lot_id"] in lot_ids)}
    return (
        await db.scalar(
            select(Entry.id)
            .join(Operation, Entry.operation_id == Operation.id)
            .where(
                Operation.workspace_id == task.workspace_id,
                Entry.entity_id.in_(ids),
                Entry.created_at >= task.created_at,
            )
            .limit(1)
        )
        is not None
    )


async def bind_sources(db, task, item_id):
    existing = set(
        (
            await db.scalars(
                select(Binding.media_id).where(
                    Binding.workspace_id == task.workspace_id,
                    Binding.entity_type == "item",
                    Binding.entity_id == item_id,
                    Binding.role == "source",
                )
            )
        ).all()
    )
    for ordinal, media_id in enumerate(task.media_ids):
        if media_id not in existing:
            db.add(
                Binding(
                    workspace_id=task.workspace_id,
                    entity_type="item",
                    entity_id=item_id,
                    media_id=media_id,
                    ordinal=ordinal,
                )
            )
    await bind_photo_variants(db, task.workspace_id, item_id, task.media_ids)


async def initialize(db, task, parent=None):
    if (
        task.context.get("purpose") == "ocr"
        or task.context.get("diagnostics_only")
        or task.context.get("item_id")
    ):
        return
    item_ids = parent.context.get("catalog_item_ids", []) if parent else []
    require(
        not parent or not parent.context.get("superseded_by"),
        "TASK_SUPERSEDED",
        "У этой задачи уже есть продолжение. Откройте последнюю обработку.",
    )
    state = await load_state(db, task.workspace_id, task.created_by, task.config_snapshot)
    state.automatic = True
    if not item_ids:
        state.apply(
            [
                {
                    "type": "receive_stock",
                    "values": {
                        "item_name": PLACEHOLDER,
                        "tracking_mode": "untracked",
                        "quantity_state": "not_applicable",
                        "location_id": task.context.get("location_id"),
                        "privacy_policy": "local_only",
                        "user_description": task.input_text[:10000] if task.input_text else None,
                    },
                }
            ]
        )
        item_ids = [state.previews[0]["item_id"]]
        state.rows["item"][item_ids[0]]["review_status"] = "processing"
    for item_id in item_ids:
        item = state.item(item_id)
        require(item["review_status"] != "confirmed", "ALREADY_VERIFIED", "Карточка уже подтверждена.")
        if parent:
            require(
                item.get("source_task_id") == parent.id,
                "TASK_SUPERSEDED",
                "Откройте последнюю обработку карточки.",
            )
        item.update(review_status="processing", source_task_id=task.id)
        item["version"] += int(bool(parent))
    await persist_state(db, state)
    task.context = {**task.context, "catalog_item_ids": item_ids}
    for item_id in item_ids:
        await bind_sources(db, task, item_id)
    if parent and parent.proposal_id:
        proposal = await db.get(Proposal, parent.proposal_id)
        if proposal and proposal.status == "editable":
            proposal.status = "cancelled"
            proposal.document = {
                **proposal.document,
                "status": "cancelled",
                "can_confirm": False,
                "available_actions": [],
            }
    if parent:
        parent.context = {**parent.context, "superseded_by": task.id}
        from app.domain.rules import transition

        if parent.status == "waiting_for_review":
            transition(parent, "cancelled")
        else:
            parent.status_version += 1


async def publish(db, task, actions, proposal_id=None):
    """Сохраняет только создание новых вещей; команды существующего учёта остаются предложениями."""
    item_ids = list(task.context.get("catalog_item_ids", []))
    if not item_ids:
        return actions
    rewritten, used = [], []
    for action in actions:
        values = action["values"]
        if action["type"] != "receive_stock" or values.get("item_mode", "create") != "create":
            rewritten.append(action)
            continue
        values = {
            **values,
            "item_name": (values.get("item_name") or "").strip() or None,
            "user_description": values.get("user_description") or (task.input_text or "")[:10000] or None,
        }
        state = await load_state(db, task.workspace_id, task.created_by, task.config_snapshot)
        state.automatic = True
        if len(used) < len(item_ids):
            item_id = item_ids[len(used)]
        else:
            state.apply(
                [
                    {
                        "type": "receive_stock",
                        "values": {
                            "item_name": PLACEHOLDER,
                            "tracking_mode": "untracked",
                            "quantity_state": "not_applicable",
                            "location_id": task.context.get("location_id"),
                            "user_description": values["user_description"],
                        },
                    }
                ]
            )
            item_id = state.previews[-1]["item_id"]
            state.rows["item"][item_id]["review_status"] = "processing"
        review = Action(
            type="verify_item",
            action_id=action.get("action_id", "a1"),
            values={**values, "item_id": item_id, "lot_mode": "create", "lot_id": None},
        ).model_dump(mode="json")
        stored = {
            **review,
            "values": {**review["values"], "item_name": values.get("item_name") or PLACEHOLDER},
        }
        edited = await edited_during_recognition(db, task, state, item_id)
        if not edited:
            try:
                state.apply([stored])
            except DomainError:
                # Ошибочные второстепенные поля не прячут распознанную вещь из каталога.
                state = await load_state(db, task.workspace_id, task.created_by, task.config_snapshot)
                state.automatic = True
                if item_id not in state.rows["item"]:
                    state.apply(
                        [
                            {
                                "type": "receive_stock",
                                "values": {
                                    "item_name": PLACEHOLDER,
                                    "tracking_mode": "untracked",
                                    "quantity_state": "not_applicable",
                                },
                            }
                        ]
                    )
                    item_id = state.previews[-1]["item_id"]
                    state.rows["item"][item_id]["review_status"] = "processing"
                    review["values"]["item_id"] = item_id
                state.apply(
                    [
                        {
                            "type": "verify_item",
                            "values": {
                                "item_id": item_id,
                                "item_name": values.get("item_name") or PLACEHOLDER,
                                "tracking_mode": "untracked",
                                "quantity_state": "not_applicable",
                                "location_id": task.context.get("location_id"),
                            },
                        }
                    ]
                )
        item = state.rows["item"][item_id]
        if edited:
            # Ручные операции, выполненные во время inference, имеют приоритет над его поздним ответом.
            item["version"] += 1
            item["search_revision"] = item["version"]
            task.result = {
                **task.result,
                "catalog_warnings": [
                    "Карточка изменилась во время распознавания. Ваши данные сохранены; результат модели оставлен для сравнения и ручной проверки."
                ],
            }
        item.update(
            source_task_id=task.id,
            review_status="error" if task.error_code or item["name"] == PLACEHOLDER else "unconfirmed",
        )
        await persist_state(db, state)
        await bind_sources(db, task, item_id)
        db.add(
            Evidence(
                workspace_id=task.workspace_id,
                entity_type="item",
                entity_id=item_id,
                field_key="recognition",
                source_type="model",
                verification_state="unconfirmed",
                proposal_id=proposal_id,
                normalized_value={"task_id": task.id, "values": values},
            )
        )
        used.append(item_id)
        rewritten.append(review)
    # Поисковый запрос и действия над существующими вещами не создают лишний инвентарь.
    unused = set(item_ids) - set(used)
    if unused:
        state = await load_state(db, task.workspace_id, task.created_by, task.config_snapshot)
        for item_id in unused:
            item = state.rows["item"].get(item_id)
            if item and item["review_status"] != "confirmed" and item["lifecycle"] == "active":
                state.apply([{"type": "archive_item", "values": {"item_id": item_id}}])
        await persist_state(db, state)
    task.context = {**task.context, "catalog_item_ids": used}
    return rewritten


async def mark_error(db, task):
    for item_id in task.context.get("catalog_item_ids", []):
        item = await db.get(Item, item_id)
        if item and item.source_task_id == task.id and item.review_status == "processing":
            item.review_status = "error"
            item.version += 1
            item.updated_at = utcnow()


async def discard_placeholders(db, task):
    await publish(db, task, [])


async def materialize_pending(factory):
    """Однократный перенос старых ожидающих загрузок; повтор команды ничего не дублирует."""
    from app.application.proposals import rebuild
    from app.application.tasks import ACTIVE
    from app.db.session import workspace_access

    count = 0
    async with factory() as db:
        ids = (
            await db.scalars(select(Task.id).where(Task.status.in_(ACTIVE | {"waiting_for_review"})))
        ).all()
    for task_id in ids:
        async with factory() as db, db.begin():
            task = await db.get(Task, task_id)
            await workspace_access(db, task.workspace_id, task.created_by, write=True, lock=True)
            await db.refresh(task)
            if "catalog_item_ids" in task.context or task.context.get("deleted"):
                continue
            proposal = await db.get(Proposal, task.proposal_id) if task.proposal_id else None
            if task.status == "waiting_for_review" and (not proposal or proposal.status != "editable"):
                continue
            await initialize(db, task)
            if not task.context.get("catalog_item_ids"):
                continue
            if proposal:
                actions = proposal.actions
                if task.error_code:
                    actions = [
                        {**action, "values": {**action["values"], "item_name": None}}
                        if action["type"] == "receive_stock"
                        and action["values"].get("item_mode") == "create"
                        and (action["values"].get("item_name") or "").startswith("Неопознанный предмет")
                        else action
                        for action in actions
                    ]
                proposal.actions = await publish(db, task, actions, proposal.id)
                verified = {a["action_id"] for a in proposal.actions if a["type"] == "verify_item"}
                proposal.document = {
                    **proposal.document,
                    "required_decisions": [
                        d
                        for d in proposal.document.get("required_decisions", [])
                        if not (d["action_id"] in verified and d["key"] == "operation")
                    ],
                }
                await rebuild(db, proposal, increment=True)
            task.status_version += 1
            count += 1
    return count


async def review_info(db, item):
    task = await db.get(Task, item.source_task_id) if item.source_task_id else None
    if task and task.workspace_id != item.workspace_id:
        task = None
    return {
        "review_status": item.review_status,
        "review_task_id": task.id if task else None,
        "review_proposal_id": task.proposal_id if task and task.status != "cancelled" else None,
        "recognition_error": task.error_code if task and item.review_status == "error" else None,
    }
