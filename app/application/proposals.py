from copy import deepcopy

from pydantic import ValidationError
from sqlalchemy import select

from app.application.inventory import ENTITIES, load_state, persist_state
from app.application.settings import effective_settings
from app.db.models import (
    Binding,
    Confirmation,
    Evidence,
    Item,
    Operation,
    Outbox,
    Proposal,
    ProposalRevision,
    Receipt,
    Task,
)
from app.db.session import scoped_get, workspace_access
from app.domain.common import digest, jsonable, uid, utcnow
from app.domain.errors import DomainError, require
from app.domain.reference import ATTRIBUTE_LABELS, ATTRIBUTES, LIST_ATTRIBUTES, validate_attributes
from app.domain.rules import transition
from app.domain.schemas import COMMANDS, Action

LABELS = {
    "receive_stock": "Добавить вещь",
    "move_stock": "Переместить",
    "consume_stock": "Израсходовать",
    "set_quantity": "Установить остаток",
    "update_item": "Изменить карточку",
    "update_lot": "Изменить партию",
    "split_lot": "Разделить партию",
    "merge_lots": "Объединить партии",
    "create_location": "Создать место",
    "move_location": "Переместить место",
    "update_location": "Изменить место",
    "archive_item": "В архив",
    "restore_item": "Восстановить",
    "archive_location": "Архивировать место",
    "add_alias": "Добавить название",
    "remove_alias": "Удалить название",
    "confirm_presence": "Подтвердить наличие",
    "reverse_operation": "Отменить операцию",
}
FIELD_LABELS = {
    "item_name": "Название",
    "name": "Название",
    "item_mode": "Новая или существующая вещь",
    "item_id": "Карточка",
    "lot_id": "Партия",
    "location_id": "Место",
    "to_location_id": "Куда переместить",
    "quantity": "Количество",
    "quantity_state": "Точность количества",
    "unit_code": "Единица",
    "category": "Категория",
    "primary_category": "Категория",
    "tracking_mode": "Режим учёта",
    "privacy_policy": "Обработка AI",
    "expiry_on": "Годен до",
    "expiry_precision": "Точность срока",
    "expiry_raw_text": "Срок на упаковке",
    "opened_on": "Дата открытия",
    "parent_id": "Родительское место",
    "whole_presence": "Переместить целиком",
    "reason": "Причина",
    "lot_mode": "Новая или существующая партия",
    "separate_item": "Создать отдельную карточку",
    "quantity_step": "Шаг количества",
    "attributes": "Свойства",
    "lot_attributes": "Свойства партии",
    "tags": "Метки",
    "barcode": "Штрихкод",
    "brand": "Марка",
    "model": "Модель",
    "user_description": "Описание",
    "generated_description": "Описание AI",
    "package_size": "Единиц в упаковке",
    "serial_number": "Серийный номер",
    "label": "Название партии",
    "manufacturer_batch": "Номер партии",
    "acquired_at": "Дата приобретения",
    "manufactured_on": "Дата производства",
    "after_opening_amount": "Срок после открытия",
    "after_opening_unit": "Единица срока после открытия",
    "default_privacy_policy": "Приватность содержимого",
    "description": "Описание",
    "kind": "Тип места",
    "transfer_to_id": "Перенести содержимое в",
    "alias": "Дополнительное название",
    "scope": "Видимость названия",
    "alias_id": "Название",
    "lot_ids": "Объединяемые партии",
    "operation_id": "Исходная операция",
}


class PersistedConflict(DomainError):
    """Сохранённая новая форма должна пережить HTTP 409."""


def form_fields(actions, source):
    fields = []
    for action in actions:
        properties = COMMANDS[action["type"]].model_json_schema()["properties"]
        for key, value in action["values"].items():
            if key == "attributes":
                value = value if isinstance(value, dict) else {}
                category = action["values"].get("category") or action["values"].get(
                    "primary_category", "other"
                )
                for attribute in sorted(ATTRIBUTES.get(category, set())):
                    paths = (
                        ["strength.raw", "strength.value", "strength.unit"]
                        if attribute == "strength"
                        else [attribute]
                    )
                    for path in paths:
                        parts = path.split(".")
                        current = value.get(parts[0])
                        current = (
                            current.get(parts[1])
                            if len(parts) == 2 and isinstance(current, dict)
                            else current
                            if len(parts) == 1
                            else None
                        )
                        control = (
                            "chips_select"
                            if attribute in LIST_ATTRIBUTES
                            else "decimal_input"
                            if path == "strength.value"
                            else "text_input"
                        )
                        fields.append(
                            {
                                "action_id": action["action_id"],
                                "key": "attributes." + path,
                                "label": ATTRIBUTE_LABELS[path],
                                "control": control,
                                "value_type": "array"
                                if attribute in LIST_ATTRIBUTES
                                else "decimal"
                                if path == "strength.value"
                                else "string",
                                "value": current,
                                "required": False,
                                "editable": action["values"].get("item_mode") != "existing",
                                "allow_unknown": True,
                                "options": [],
                                "validation": {"min": "0", "step": "0.000001"}
                                if control == "decimal_input"
                                else {},
                                "source": "user" if source == "manual" else "model",
                                "verification_state": "known" if source == "manual" else "extracted",
                                "importance": "primary"
                                if attribute in {"strength", "active_ingredients", "dosage_form"}
                                else "secondary",
                            }
                        )
                continue
            prop = properties.get(key, {})
            variants = prop.get("anyOf", [prop])
            prop = next((p for p in variants if p.get("type") != "null"), prop)
            control = "text_input"
            if key in {"location_id", "to_location_id", "parent_id", "transfer_to_id"}:
                control = "location_picker"
            elif key.endswith("_id") or key == "lot_ids":
                control = "entity_picker"
            elif key in {"unit_code", "after_opening_unit"}:
                control = "unit_select"
            elif "enum" in prop:
                control = "segmented_control"
            elif key in {"quantity", "quantity_step", "package_size"}:
                control = (
                    "decimal_input"
                    if action["values"].get("tracking_mode") == "measured"
                    else "number_stepper"
                )
            elif key.endswith("_on") or prop.get("format") == "date":
                control = "date_picker"
            elif type(value) is bool:
                control = "switch"
            elif isinstance(value, list):
                control = "chips_select"
            elif isinstance(value, dict):
                control = "readonly_summary"
            fields.append(
                {
                    "action_id": action["action_id"],
                    "key": key,
                    "label": FIELD_LABELS.get(key, key),
                    "control": control,
                    "value_type": prop.get("type", "decimal"),
                    "required": False,
                    "editable": control != "readonly_summary",
                    "allow_unknown": True,
                    "options": [{"value": option, "label": option} for option in prop.get("enum", [])],
                    "validation": {"min": "0", "step": str(action["values"].get("quantity_step", "1"))}
                    if control in {"number_stepper", "decimal_input"}
                    else {},
                    "source": "user" if source == "manual" else "model",
                    "verification_state": "known" if source == "manual" else "extracted",
                    "importance": "primary"
                    if key in {"item_name", "quantity", "location_id", "lot_id"}
                    else "secondary",
                }
            )
    return fields


async def normalize_actions(db, workspace_id, actions):
    result = []
    state = await load_state(db, workspace_id, "", {})
    for raw in actions:
        action = Action.model_validate(raw).model_dump(mode="json")
        values = action["values"]
        if action["type"] == "receive_stock":
            values["location_id"] = state.location(values["location_id"])["id"]
            if values["item_mode"] == "create" and not values["item_name"]:
                # Временное имя входит в сохранённую команду и больше не зависит от времени apply.
                values["item_name"] = (
                    "Неопознанный предмет — " + utcnow().strftime("%Y-%m-%d %H:%M") + " · " + uid()[:8]
                )
            if values["item_mode"] == "existing" and values["item_id"]:
                item = state.get("item", values["item_id"])
                values.update(
                    item_name=item["name"],
                    category=item["primary_category"],
                    tracking_mode=item["tracking_mode"],
                    quantity_step=str(item["quantity_step"]),
                    attributes=item["attributes"],
                )
                values["unit_code"] = values["unit_code"] or item["base_unit_id"]
                if item["privacy_policy"] == "local_only":
                    values["privacy_policy"] = "local_only"
            if values["category"] == "document":
                values["privacy_policy"] = "local_only"
            if values["tracking_mode"] == "untracked":
                values.update(quantity=None, quantity_state="not_applicable", unit_code=None)
        elif action["type"] == "update_item" and values.get("item_id"):
            item = state.get("item", values["item_id"])
            values.setdefault("primary_category", item["primary_category"])
            values.setdefault("attributes", item["attributes"])
        result.append(action)
    require(
        len({a["action_id"] for a in result}) == len(result),
        "INVALID_ACTIONS",
        "Идентификаторы действий повторяются.",
        422,
    )
    return result


async def rebuild(db, proposal, *, increment=False, issues=None):
    if increment:
        proposal.revision += 1
    _, settings = await effective_settings(db)
    proposal.actions = await normalize_actions(db, proposal.workspace_id, proposal.actions)
    state = await load_state(db, proposal.workspace_id, proposal.created_by, settings, proposal.actions)
    blockers = [issue for issue in issues or [] if issue["code"] != "INTENT_REQUIRED"]
    decisions = deepcopy((proposal.document or {}).get("required_decisions", []))
    if any(issue["code"] == "INTENT_REQUIRED" for issue in issues or []):
        for action in proposal.actions:
            if not any(d["key"] == "operation" and d["action_id"] == action["action_id"] for d in decisions):
                decisions.append(
                    {
                        "action_id": action["action_id"],
                        "key": "operation",
                        "code": "INTENT_REQUIRED",
                        "message": "Во вводе нет однозначно совершённого действия. Выберите, что записать в учёт.",
                        "label": "Какое действие записать?",
                        "options": [{"value": code, "label": label} for code, label in LABELS.items()],
                    }
                )
    if any(warning.startswith("Графики приёма и произвольные таймеры") for warning in proposal.warnings):
        if not any(d["key"] == "unsupported_request" for d in decisions):
            decisions.append(
                {
                    "action_id": proposal.actions[0]["action_id"],
                    "key": "unsupported_request",
                    "code": "UNSUPPORTED_REQUEST",
                    "message": "Таймер или график не будут созданы. Выберите учёт без этой части либо отмените предложение.",
                    "label": "Часть запроса не поддерживается",
                    "options": [
                        {
                            "value": "inventory_only",
                            "label": "Записать только изменение учёта, без таймера или графика",
                        }
                    ],
                }
            )
    chosen = {(change["action_id"], change["key"]): change["value"] for change in proposal.user_changes}
    for decision in decisions:
        decision["value"] = chosen.get((decision["action_id"], decision["key"]))
        allowed = {option["value"] for option in decision["options"]}
        if decision["value"] not in allowed:
            blockers.append(
                {"code": decision["code"], "message": decision["message"], "action_id": decision["action_id"]}
            )
    try:
        state.apply(proposal.actions)
    except DomainError as error:
        blockers.append({"code": error.code, "message": error.message, **error.details})
    proposal.dependencies = state.dependencies
    if any(action["type"] in {"receive_stock", "split_lot", "update_lot"} for action in proposal.actions):
        proposal.dependencies = {
            **proposal.dependencies,
            "setting:expiry.month_expiry_policy": settings["expiry.month_expiry_policy"],
        }
    # Новое совпадение каталога после review требует показать его пользователю.
    for action in proposal.actions:
        v = action["values"]
        if action["type"] == "receive_stock" and v["item_mode"] == "create" and not v["separate_item"]:
            matches = sorted(
                i["id"]
                for i in state.original["item"].values()
                if i["lifecycle"] == "active" and i["name"].casefold() == (v["item_name"] or "").casefold()
            )
            proposal.dependencies = {**proposal.dependencies, "duplicate:" + action["action_id"]: matches}
            if matches:
                blockers.append(
                    {
                        "code": "DUPLICATE_CANDIDATE",
                        "action_id": action["action_id"],
                        "message": "Выберите найденную карточку или подтвердите создание отдельной.",
                        "candidate_ids": matches,
                    }
                )
    media = []
    if proposal.task_id:
        task = await scoped_get(db, Task, proposal.task_id, proposal.workspace_id)
        media = [
            {"media_id": media_id, "download": f"/api/v1/media/{media_id}/download"}
            for media_id in task.media_ids
        ]
        if task.context.get("diagnostics_only"):
            blockers.append(
                {"code": "DIAGNOSTIC_ONLY", "message": "Диагностический повтор нельзя применять к учёту."}
            )
    previews = {p["action_id"]: p for p in state.previews}
    fields = form_fields(proposal.actions, proposal.source)
    fields = [
        {
            **{key: decision[key] for key in ("action_id", "key", "label", "value", "options")},
            "control": "segmented_control",
            "value_type": "string",
            "required": True,
            "editable": True,
            "allow_unknown": False,
            "validation": {},
            "source": "user",
            "verification_state": "known" if decision["value"] else "unknown",
            "importance": "primary",
        }
        for decision in decisions
    ] + fields
    for field in fields:
        if field["key"] == "item_id":
            matches = proposal.dependencies.get("duplicate:" + field["action_id"], [])
            if matches:
                field["control"] = "candidate_cards"
                field["options"] = [
                    {
                        "value": item_id,
                        "label": " · ".join(
                            str(value)
                            for value in [
                                state.rows["item"][item_id]["name"],
                                state.rows["item"][item_id].get("brand"),
                                state.rows["item"][item_id].get("model"),
                                *state.rows["item"][item_id].get("attributes", {}).values(),
                            ]
                            if value
                        ),
                    }
                    for item_id in matches
                ]
        if field["key"] == "privacy_policy" and any(
            a["values"].get("category") == "document" for a in proposal.actions
        ):
            field["options"] = [{"value": "local_only", "label": "Только мой сервер"}]
    document = {
        "schema_version": "review.v1",
        "proposal_id": proposal.id,
        "task_id": proposal.task_id,
        "revision": proposal.revision,
        "status": proposal.status,
        "title": LABELS[proposal.actions[0]["type"]],
        "summary": "; ".join(
            LABELS[a["type"]]
            + (
                ": " + str(a["values"].get("item_name") or a["values"].get("name"))
                if a["values"].get("item_name") or a["values"].get("name")
                else ""
            )
            for a in proposal.actions
        ),
        "can_confirm": not blockers and proposal.status == "editable",
        "effective_privacy": "local_only"
        if any(a["values"].get("privacy_policy", "local_only") == "local_only" for a in proposal.actions)
        else "cloud_allowed",
        "actions": [{**a, "preview": previews.get(a["action_id"], {})} for a in proposal.actions],
        "form": {"template": proposal.actions[0]["type"] + ".v1", "fields": fields, "readonly_fields": []},
        "blocking_issues": blockers,
        "warnings": proposal.warnings,
        "media": media,
        "required_decisions": decisions,
        "available_actions": (["edit", "cancel"] if blockers else ["confirm", "edit", "cancel"])
        if proposal.status == "editable"
        else [],
        "source_proposals": proposal.source_proposals,
    }
    proposal.review_hash = digest(document)
    document["review_hash"] = proposal.review_hash
    proposal.document = jsonable(document)
    await db.flush()
    db.add(
        ProposalRevision(
            workspace_id=proposal.workspace_id,
            proposal_id=proposal.id,
            revision=proposal.revision,
            document=proposal.document,
        )
    )
    return proposal.document


async def create_proposal(db, workspace_id, user_id, actions, *, task=None, source="manual", warnings=None):
    proposal = Proposal(
        id=uid(),
        workspace_id=workspace_id,
        created_by=user_id,
        actions=actions,
        task_id=task.id if task else None,
        source=source,
        status="editable",
        revision=1,
        review_hash="",
        source_proposals=[],
        warnings=warnings or [],
        user_changes=[],
    )
    db.add(proposal)
    await rebuild(db, proposal)
    if task:
        task.proposal_id = proposal.id
        transition(task, "waiting_for_review", "review_ready")
        task.lease_owner = task.lease_until = None
    return proposal


def apply_changes(proposal, changes):
    actions = deepcopy(proposal.actions)
    by_id = {a["action_id"]: a for a in actions}
    for change in changes:
        action = by_id.get(change["action_id"])
        if change["key"].startswith("attributes."):
            require(
                action
                and action["type"] in {"receive_stock", "update_item"}
                and action["values"].get("item_mode") != "existing",
                "UNKNOWN_FIELD",
                "Для этой операции свойства карточки недоступны.",
                422,
            )
            category = action["values"].get("category") or action["values"].get("primary_category", "other")
            parts = change["key"].split(".")[1:]
            require(
                parts[0] in ATTRIBUTES.get(category, set())
                and (
                    len(parts) == 2
                    and parts[0] == "strength"
                    and parts[1] in {"raw", "value", "unit"}
                    or len(parts) == 1
                    and parts[0] != "strength"
                ),
                "UNKNOWN_FIELD",
                "Свойство не входит в схему категории.",
                422,
            )
            attributes = action["values"].setdefault("attributes", {})
            if len(parts) == 2 and not isinstance(attributes.get("strength"), dict):
                attributes["strength"] = {}
            target = attributes.setdefault("strength", {}) if len(parts) == 2 else attributes
            if change["value"] is None:
                target.pop(parts[-1], None)
                if not attributes.get("strength"):
                    attributes.pop("strength", None)
            else:
                target[parts[-1]] = change["value"]
            validate_attributes(category, attributes)
            continue
        if change["key"] in {"operation", "unsupported_request"}:
            decision = next(
                (
                    d
                    for d in proposal.document.get("required_decisions", [])
                    if d["action_id"] == change["action_id"] and d["key"] == change["key"]
                ),
                None,
            )
            require(
                action
                and decision
                and change["value"] in [option["value"] for option in decision["options"]],
                "UNKNOWN_FIELD",
                "Выберите доступное решение формы.",
                422,
            )
            if change["key"] == "operation":
                action["type"] = change["value"]
                action["values"] = {
                    key: value
                    for key, value in action["values"].items()
                    if key in COMMANDS[action["type"]].model_fields
                }
            continue
        require(
            action and change["key"] in COMMANDS[action["type"]].model_fields,
            "UNKNOWN_FIELD",
            "Поле не входит в схему действия.",
            422,
        )
        action["values"][change["key"]] = change["value"]
    try:
        actions = [Action.model_validate(a).model_dump(mode="json") for a in actions]
    except ValidationError as exc:
        raise DomainError("FIELD_VALIDATION_FAILED", "Поправка имеет неверный тип.", 422) from exc
    proposal.actions = actions
    proposal.user_changes = [*proposal.user_changes, *changes]


async def edit_proposal(db, proposal, expected_revision, changes):
    require(proposal.status == "editable", "ALREADY_CONFIRMED", "Предложение уже недоступно для правок.")
    require(
        proposal.revision == expected_revision,
        "VERSION_CONFLICT",
        "Форма уже изменилась.",
        review=proposal.document,
    )
    apply_changes(proposal, changes)
    return await rebuild(db, proposal, increment=True)


async def dependencies_changed(db, proposal, expected=None, *, settings=None):
    for key, version in (expected or proposal.dependencies).items():
        require(":" in key, "INVALID_VERSION_KEY", "Неизвестная сущность версии.", 422)
        kind, entity_id = key.split(":", 1)
        if kind == "setting":
            require(
                entity_id == "expiry.month_expiry_policy",
                "INVALID_VERSION_KEY",
                "Неизвестная настройка версии.",
                422,
            )
            if settings is None:
                _, settings = await effective_settings(db)
            if settings[entity_id] != version:
                return True
        elif kind == "duplicate":
            action = next((a for a in proposal.actions if a["action_id"] == entity_id), None)
            require(
                action and action["type"] == "receive_stock" and isinstance(version, list),
                "INVALID_VERSION_KEY",
                "Неизвестная сущность версии.",
                422,
            )
            name = (action["values"]["item_name"] or "").casefold()
            items = (
                await db.scalars(
                    select(Item).where(Item.workspace_id == proposal.workspace_id, Item.lifecycle == "active")
                )
            ).all()
            if sorted(i.id for i in items if i.name.casefold() == name) != version:
                return True
        else:
            require(kind in ENTITIES, "INVALID_VERSION_KEY", "Неизвестная сущность версии.", 422)
            row = await db.scalar(
                select(ENTITIES[kind]).where(
                    ENTITIES[kind].id == entity_id, ENTITIES[kind].workspace_id == proposal.workspace_id
                )
            )
            if row is None or row.version != version:
                return True
    return False


async def accept_confirmation(db, proposal, user_id, payload):
    if proposal.task_id:
        task = await scoped_get(db, Task, proposal.task_id, proposal.workspace_id)
        require(
            not task.context.get("diagnostics_only"),
            "DIAGNOSTIC_ONLY",
            "Диагностический повтор нельзя применять к учёту.",
            409,
        )
    existing = await db.scalar(
        select(Confirmation).where(
            Confirmation.proposal_id == proposal.id,
            Confirmation.proposal_revision == payload["expected_revision"],
        )
    )
    if existing:
        receipt = await db.get(Receipt, existing.receipt_id)
        require(
            receipt.observed_review_hash == payload["observed_review_hash"]
            and receipt.explicit_changes == payload.get("changes", []),
            "ALREADY_CONFIRMED",
            "Эта ревизия подтверждена с другими значениями.",
        )
        return confirmation_view(existing, proposal.task_id)
    require(proposal.status == "editable", "ALREADY_CONFIRMED", "Предложение уже подтверждено или отменено.")
    require(
        proposal.revision == payload["expected_revision"]
        and proposal.review_hash == payload["observed_review_hash"],
        "VERSION_CONFLICT",
        "Форма уже изменилась.",
        review=proposal.document,
    )
    sources = []
    for source in sorted(proposal.source_proposals, key=lambda s: s["proposal_id"]):
        row = await scoped_get(db, Proposal, source["proposal_id"], proposal.workspace_id, lock=True)
        require(
            row.status == "editable" and row.revision == source["revision"],
            "REVIEW_UPDATE_REQUIRED",
            "Исходная форма общего подтверждения изменилась.",
        )
        sources.append(row)
    if await dependencies_changed(db, proposal):
        if payload.get("changes"):
            # Сохраняем введённые пользователем поля, но новый preview требует нового confirm.
            apply_changes(proposal, payload["changes"])
        await rebuild(db, proposal, increment=True)
        raise PersistedConflict(
            "REVIEW_UPDATE_REQUIRED", "Учёт изменился. Проверьте обновлённую форму.", review=proposal.document
        )
    observed_revision = proposal.revision
    observed_hash = proposal.review_hash
    changes = payload.get("changes", [])
    if changes:
        apply_changes(proposal, changes)
        await rebuild(db, proposal, increment=True)
    if not proposal.document["can_confirm"]:
        raise PersistedConflict(
            "REVIEW_UPDATE_REQUIRED", "Устраните отмеченные поля.", review=proposal.document
        )
    receipt = Receipt(
        id=uid(),
        workspace_id=proposal.workspace_id,
        user_id=user_id,
        proposal_id=proposal.id,
        proposal_revision=observed_revision,
        observed_review_hash=observed_hash,
        confirmed_values_hash=digest(proposal.actions),
        explicit_changes=changes,
        confirmation_source="batch" if sources else proposal.source,
        client_request_id=payload["client_request_id"],
    )
    db.add(receipt)
    await db.flush()
    confirmation = Confirmation(
        id=uid(),
        workspace_id=proposal.workspace_id,
        proposal_id=proposal.id,
        proposal_revision=observed_revision,
        receipt_id=receipt.id,
        operation_id=uid(),
        status="queued",
        actions=proposal.actions,
        dependencies=proposal.dependencies,
        fencing_token=1,
        result={},
    )
    db.add(confirmation)
    for row in [proposal, *sources]:
        row.status = "confirming"
        row.document = {**row.document, "status": "confirming", "can_confirm": False, "available_actions": []}
        if row.task_id:
            task = await scoped_get(db, Task, row.task_id, proposal.workspace_id, lock=True)
            transition(task, "applying", "confirmation_queued")
    db.add(
        Outbox(
            workspace_id=proposal.workspace_id,
            event_type="apply_confirmation",
            entity_id=confirmation.id,
            payload={"fencing_token": 1},
        )
    )
    await db.flush()
    return confirmation_view(confirmation, proposal.task_id)


def confirmation_view(confirmation, task_id=None):
    return {
        "confirmation_id": confirmation.id,
        "operation_id": confirmation.operation_id,
        "task_id": task_id,
        "status": confirmation.status,
        "result": confirmation.result,
        "error_code": confirmation.error_code,
        "poll_after_ms": 1000 if confirmation.status in {"queued", "applying"} else None,
    }


async def combine(db, workspace_id, user_id, sources):
    _, settings = await effective_settings(db)
    require(
        1 < len(sources) <= settings["queue.max_review_batch_size"],
        "INVALID_BATCH_SIZE",
        "Недопустимый размер общего предложения.",
        422,
    )
    require(
        len({s["proposal_id"] for s in sources}) == len(sources),
        "INVALID_BATCH",
        "Предложения повторяются.",
        422,
    )
    actions = []
    warnings = []
    decisions = []
    user_choices = []
    for n, source in enumerate(sources):
        proposal = await scoped_get(db, Proposal, source["proposal_id"], workspace_id)
        require(
            proposal.status == "editable"
            and proposal.revision == source["revision"]
            and not proposal.source_proposals,
            "VERSION_CONFLICT",
            "Исходное предложение недоступно.",
        )
        if proposal.task_id:
            task = await scoped_get(db, Task, proposal.task_id, workspace_id)
            require(
                not task.context.get("diagnostics_only"),
                "DIAGNOSTIC_ONLY",
                "Диагностический повтор нельзя включить в подтверждение.",
            )
        actions.extend({**a, "action_id": f"s{n}_{a['action_id']}"} for a in proposal.actions)
        warnings.extend(proposal.warnings)
        decisions.extend(
            {**decision, "action_id": f"s{n}_{decision['action_id']}"}
            for decision in proposal.document.get("required_decisions", [])
        )
        user_choices.extend(
            {**change, "action_id": f"s{n}_{change['action_id']}"}
            for change in proposal.user_changes
            if change["key"] in {"operation", "unsupported_request"}
        )
    proposal = Proposal(
        id=uid(),
        workspace_id=workspace_id,
        created_by=user_id,
        actions=actions,
        source="batch",
        status="editable",
        revision=1,
        review_hash="",
        source_proposals=sources,
        warnings=warnings,
        user_changes=user_choices,
        document={"required_decisions": decisions},
    )
    db.add(proposal)
    await rebuild(db, proposal)
    return proposal.document


async def apply_confirmation(factory, confirmation_id, fencing_token=1):
    try:
        async with factory() as db, db.begin():
            # Порядок блокировок одинаков с confirm/cancel: сначала workspace.
            current = await db.get(Confirmation, confirmation_id)
            if current is None:
                return
            receipt = await db.get(Receipt, current.receipt_id)
            await workspace_access(db, current.workspace_id, receipt.user_id, write=True, lock=True)
            confirmation = await db.get(
                Confirmation, confirmation_id, with_for_update=True, populate_existing=True
            )
            if confirmation.status == "applied":
                return confirmation.result
            if confirmation.status != "queued" or confirmation.fencing_token != fencing_token:
                return
            proposal = await scoped_get(db, Proposal, confirmation.proposal_id, confirmation.workspace_id)
            _, settings = await effective_settings(db)
            require(
                not await dependencies_changed(db, proposal, confirmation.dependencies, settings=settings),
                "VERSION_CONFLICT",
                "Учёт или правила расчёта изменились после подтверждения.",
            )
            state = await load_state(
                db, confirmation.workspace_id, receipt.user_id, settings, confirmation.actions
            )
            state.apply(confirmation.actions)
            operation = Operation(
                id=confirmation.operation_id,
                workspace_id=confirmation.workspace_id,
                actor_user_id=receipt.user_id,
                confirmation_id=confirmation.id,
                type=confirmation.actions[0]["type"] if len(confirmation.actions) == 1 else "batch",
                normalized_payload=confirmation.actions,
                request_hash=digest(confirmation.actions),
                reverses_operation_id=next(
                    (
                        a["values"]["operation_id"]
                        for a in confirmation.actions
                        if a["type"] == "reverse_operation"
                    ),
                    None,
                ),
            )
            db.add(operation)
            await db.flush()
            await persist_state(db, state, operation.id)
            confirmation.status = "applied"
            confirmation.result = {
                "operation_id": operation.id,
                "changes": len(state.entries),
                "previews": jsonable(state.previews),
            }
            linked_media = set()
            for source_index, row in enumerate(
                [
                    proposal,
                    *[
                        await scoped_get(db, Proposal, s["proposal_id"], proposal.workspace_id)
                        for s in proposal.source_proposals
                    ],
                ]
            ):
                row.status = "applied"
                row.document = {
                    **row.document,
                    "status": "applied",
                    "can_confirm": False,
                    "available_actions": [],
                }
                if row.task_id:
                    task = await scoped_get(db, Task, row.task_id, row.workspace_id)
                    transition(task, "succeeded", "saved")
                    task.completed_at = utcnow()
                    # Материалы распознавания привязываются к подтверждённой карточке.
                    prefix = f"s{source_index - 1}_" if source_index else None
                    item_ids = {
                        p["item_id"]
                        for p in state.previews
                        if "item_id" in p and (prefix is None or p["action_id"].startswith(prefix))
                    }
                    for item_id in item_ids:
                        from app.application.photos import bind_photo_variants

                        await bind_photo_variants(db, row.workspace_id, item_id, task.media_ids)
                        for ordinal, media_id in enumerate(task.media_ids):
                            pair = (item_id, media_id)
                            if pair in linked_media:
                                continue
                            linked_media.add(pair)
                            existing = await db.scalar(
                                select(Binding.id).where(
                                    Binding.workspace_id == row.workspace_id,
                                    Binding.media_id == media_id,
                                    Binding.entity_type == "item",
                                    Binding.entity_id == item_id,
                                    Binding.role == "source",
                                )
                            )
                            if existing is None:
                                db.add(
                                    Binding(
                                        workspace_id=row.workspace_id,
                                        media_id=media_id,
                                        entity_type="item",
                                        entity_id=item_id,
                                        ordinal=ordinal,
                                    )
                                )
            for action in confirmation.actions:
                for key, value in action["values"].items():
                    db.add(
                        Evidence(
                            workspace_id=proposal.workspace_id,
                            entity_type="operation",
                            entity_id=operation.id,
                            field_key=f"{action['action_id']}.{key}",
                            source_type="user",
                            normalized_value={"value": value},
                            proposal_id=proposal.id,
                        )
                    )
            return confirmation.result
    except DomainError as error:
        async with factory() as db, db.begin():
            confirmation = await db.get(Confirmation, confirmation_id)
            if confirmation is None:
                return
            receipt = await db.get(Receipt, confirmation.receipt_id)
            await workspace_access(db, confirmation.workspace_id, receipt.user_id, lock=True)
            await db.refresh(confirmation)
            if confirmation.status != "queued" or confirmation.fencing_token != fencing_token:
                return
            confirmation.status = "conflict"
            confirmation.error_code = error.code
            proposal = await db.get(Proposal, confirmation.proposal_id)
            proposal.status = "editable"
            sources = [await db.get(Proposal, source["proposal_id"]) for source in proposal.source_proposals]
            for row in sources:
                row.status = "editable"
                await rebuild(db, row, increment=True)
            proposal.source_proposals = [{"proposal_id": row.id, "revision": row.revision} for row in sources]
            await rebuild(db, proposal, increment=True)
            for row in [proposal, *sources]:
                if row.task_id:
                    task = await db.get(Task, row.task_id)
                    transition(task, "waiting_for_review", "conflict")
            return {"status": "conflict", "code": error.code, "review": proposal.document}


async def retry_confirmation(db, confirmation):
    if confirmation.status == "applied":
        return confirmation_view(confirmation)
    require(
        confirmation.status == "failed",
        "INVALID_CONFIRMATION_STATE",
        "Повтор разрешён только после технического сбоя.",
    )
    confirmation.status = "queued"
    confirmation.error_code = None
    confirmation.fencing_token += 1
    proposal = await db.get(Proposal, confirmation.proposal_id)
    if proposal.task_id:
        task = await db.get(Task, proposal.task_id)
        task.status = "applying"
        task.status_version += 1
    db.add(
        Outbox(
            workspace_id=confirmation.workspace_id,
            event_type="apply_confirmation",
            entity_id=confirmation.id,
            payload={"fencing_token": confirmation.fencing_token},
        )
    )
    return confirmation_view(confirmation, proposal.task_id)
