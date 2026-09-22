"""Один исполнитель команд для ручного ввода, AI-форм и отмены операций."""

from copy import deepcopy
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db.models import Alias, Balance, Entry, Item, Location, Lot, Operation, Outbox, Workspace
from app.domain.common import jsonable, utcnow
from app.domain.errors import require
from app.domain.reference import convert_quantity
from app.domain.rules import effective_expiry, validate_item, validate_quantity
from app.domain.schemas import Action

ENTITIES = {"location": Location, "item": Item, "lot": Lot, "balance": Balance, "alias": Alias}
LOT_FIELDS = {
    "label",
    "serial_number",
    "manufacturer_batch",
    "acquired_at",
    "manufactured_on",
    "opened_on",
    "expiry_on",
    "expiry_precision",
    "expiry_raw_text",
    "after_opening_amount",
    "after_opening_unit",
}
DATE_FIELDS = {"acquired_at", "manufactured_on", "opened_on", "expiry_on", "effective_expiry_on"}


def row_state(row):
    return {c.key: deepcopy(getattr(row, c.key)) for c in row.__table__.columns}


def new_state(model, values):
    result = {}
    for column in model.__table__.columns:
        default = column.default
        result[column.key] = (
            default.arg(None) if default and default.is_callable else default.arg if default else None
        )
    result.update(values)
    return result


def as_date(value):
    return date.fromisoformat(value) if isinstance(value, str) else value


class InventoryState:
    def __init__(self, workspace_id, user_id, rows, settings, history=None):
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.original = deepcopy(rows)
        self.rows = deepcopy(rows)
        self.settings = settings
        self.history = history or {}
        self.dependencies = {}
        self.entries = []
        self.previews = []
        self.current_action = ""

    def get(self, kind, entity_id):
        require(entity_id, "FIELD_REQUIRED", "Выберите объект в форме.", 422, field=kind + "_id")
        entity_id = str(entity_id)
        value = self.rows[kind].get(entity_id)
        require(value is not None, "NOT_FOUND", "Объект не найден в рабочей области.", 404)
        original = self.original[kind].get(entity_id)
        if original:
            self.dependencies[f"{kind}:{entity_id}"] = original["version"]
        return value

    def create(self, entity_type, **values):
        row = new_state(ENTITIES[entity_type], {"workspace_id": self.workspace_id, **values})
        self.rows[entity_type][row["id"]] = row
        return row

    def location(self, entity_id=None):
        if entity_id is None:
            entity_id = next(
                r["id"] for r in self.rows["location"].values() if r["kind"] == "system_unspecified"
            )
        row = self.get("location", entity_id)
        require(row["archived_at"] is None, "LOCATION_ARCHIVED", "Место находится в архиве.")
        return row

    def item(self, entity_id):
        item = self.get("item", entity_id)
        require(item["lifecycle"] == "active", "ITEM_INACTIVE", "Карточка недоступна для этой операции.")
        return item

    def lot_item(self, lot_id):
        lot = self.get("lot", lot_id)
        require(lot["archived_at"] is None, "LOT_ARCHIVED", "Партия находится в архиве.")
        return lot, self.item(lot["item_id"])

    def balance(self, lot_id, location_id, create=False):
        for row in self.rows["balance"].values():
            if row["lot_id"] == lot_id and row["location_id"] == location_id:
                return self.get("balance", row["id"])
        require(create, "BALANCE_NOT_FOUND", "В выбранном месте нет этой партии.", 422)
        return self.create(
            "balance", lot_id=lot_id, location_id=location_id, quantity=Decimal(0), quantity_state="exact"
        )

    def confirm_balance(self, balance):
        balance["last_confirmed_at"] = utcnow()
        balance["last_confirmed_by"] = self.user_id

    def set_expiry(self, lot):
        lot["effective_expiry_on"], lot["expiry_derivation"] = effective_expiry(
            lot["expiry_on"],
            lot["expiry_precision"],
            lot["expiry_raw_text"],
            lot["opened_on"],
            lot["after_opening_amount"],
            lot["after_opening_unit"],
            self.settings.get("expiry.month_expiry_policy"),
        )

    def validate(self):
        from types import SimpleNamespace

        for item in self.rows["item"].values():
            validate_item(SimpleNamespace(**item))
        for lot in self.rows["lot"].values():
            item = self.rows["item"][lot["item_id"]]
            balances = [b for b in self.rows["balance"].values() if b["lot_id"] == lot["id"]]
            for balance in balances:
                validate_quantity(
                    item["tracking_mode"],
                    balance["quantity"],
                    balance["quantity_state"],
                    item["quantity_step"],
                )
            if item["tracking_mode"] == "individual":
                require(
                    sum(b["quantity"] or Decimal(0) for b in balances) <= 1,
                    "INDIVIDUAL_DUPLICATE",
                    "Уникальный экземпляр нельзя размножить.",
                )
                require(
                    sum(lot_row["item_id"] == item["id"] for lot_row in self.rows["lot"].values()) == 1,
                    "INDIVIDUAL_DUPLICATE",
                    "Для другого экземпляра создайте отдельную карточку.",
                )
            if item["tracking_mode"] == "untracked":
                require(len(balances) == 1, "PRESENCE_DUPLICATE", "Присутствие должно иметь одно место.")
        for location in self.rows["location"].values():
            if location["archived_at"]:
                continue
            seen = {location["id"]}
            current = location
            depth = 1
            while current["parent_id"]:
                parent = self.rows["location"].get(current["parent_id"])
                require(
                    parent and parent["kind"] != "system_unspecified" and parent["archived_at"] is None,
                    "INVALID_LOCATION_TREE",
                    "Нельзя вложить место в недоступного родителя.",
                    422,
                )
                require(
                    parent["id"] not in seen, "INVALID_LOCATION_TREE", "В дереве мест возник бы цикл.", 422
                )
                seen.add(parent["id"])
                depth += 1
                current = parent
            require(
                depth <= self.settings.get("locations.max_depth", 6),
                "INVALID_LOCATION_TREE",
                "Превышена глубина дерева.",
                422,
            )

    def apply(self, actions):
        for raw in actions:
            action = Action.model_validate(raw)
            before = deepcopy(self.rows)
            self.current_action = action.type
            handler = getattr(self, action.type)
            summary = handler(action.values) or {}
            self.validate()
            changes = []
            for kind, rows in self.rows.items():
                for entity_id, after in rows.items():
                    previous = before[kind].get(entity_id)
                    if previous == after:
                        continue
                    if previous:
                        self.get(kind, entity_id)
                        after["version"] = previous["version"] + 1
                        after["updated_at"] = utcnow()
                    if kind == "item":
                        after["search_revision"] = after["version"]
                    if kind == "lot":
                        after["expiry_generation"] = (previous or {}).get("expiry_generation", 0) + 1
                    entry = {
                        "entity_type": kind,
                        "entity_id": entity_id,
                        "event_type": action.type,
                        "before_version": previous["version"] if previous else None,
                        "after_version": after["version"],
                        "before_state": jsonable(previous),
                        "after_state": jsonable(after),
                        "ordinal": len(self.entries),
                    }
                    if kind == "balance":
                        prior = previous["quantity"] if previous else Decimal(0)
                        entry["quantity_delta"] = (
                            after["quantity"] - prior
                            if prior is not None and after["quantity"] is not None
                            else None
                        )
                        entry["from_location_id"] = previous["location_id"] if previous else None
                        entry["to_location_id"] = after["location_id"]
                        lot = self.rows["lot"][after["lot_id"]]
                        entry["unit_id"] = self.rows["item"][lot["item_id"]]["base_unit_id"]
                    self.entries.append(entry)
                    changes.append(
                        {
                            "entity_type": kind,
                            "entity_id": entity_id,
                            "before": jsonable(previous),
                            "after": jsonable(after),
                        }
                    )
            self.previews.append({"action_id": action.action_id, **summary, "changes": changes})
        return self

    def receive_stock(self, v):
        location = self.location(v["location_id"])
        if v["item_mode"] == "create":
            require(
                v["item_name"],
                "FIELD_REQUIRED",
                "Название или временное имя должно быть сохранено в форме.",
                422,
                field="item_name",
            )
            item = self.create(
                "item",
                name=v["item_name"],
                primary_category=v["category"],
                tracking_mode=v["tracking_mode"],
                base_unit_id="pcs" if v["unit_code"] == "pair" else v["unit_code"],
                quantity_step=Decimal(v["quantity_step"]),
                attributes=v["attributes"],
                privacy_policy=v["privacy_policy"],
                created_by=self.user_id,
                **{
                    k: v[k]
                    for k in (
                        "tags",
                        "barcode",
                        "brand",
                        "model",
                        "user_description",
                        "generated_description",
                    )
                },
            )
        else:
            item = self.item(v["item_id"])
        policy = (
            "local_only"
            if "local_only"
            in (item["privacy_policy"], v["privacy_policy"], location["default_privacy_policy"])
            else "cloud_allowed"
        )
        if v["lot_mode"] == "create":
            lot = self.create(
                "lot",
                item_id=item["id"],
                lot_kind={"individual": "instance", "untracked": "untracked"}.get(
                    item["tracking_mode"], "batch"
                ),
                privacy_policy=policy,
                attributes=v["lot_attributes"],
                **{key: as_date(v[key]) if key in DATE_FIELDS else v[key] for key in LOT_FIELDS},
            )
            self.set_expiry(lot)
        else:
            lot, _ = self.lot_item(v["lot_id"])
            require(lot["item_id"] == item["id"], "LOT_MISMATCH", "Партия относится к другой карточке.")
            for key in LOT_FIELDS:
                proposed = as_date(v[key]) if key in DATE_FIELDS else v[key]
                if proposed is not None and not (key == "expiry_precision" and proposed == "unknown"):
                    require(
                        lot[key] == proposed,
                        "LOT_INCOMPATIBLE",
                        "Отличающиеся упаковки требуют новой партии.",
                    )
            require(
                lot["privacy_policy"] == policy, "LOT_INCOMPATIBLE", "Режимы приватности партий различаются."
            )
        balance = self.balance(lot["id"], location["id"], create=True)
        qty = Decimal(v["quantity"]) if v["quantity"] is not None else None
        if qty is not None:
            qty = convert_quantity(
                qty, v["unit_code"] or item["base_unit_id"], item["base_unit_id"], v["package_size"]
            )
        if balance["id"] in self.original["balance"] or balance["quantity"] != 0:
            require(
                qty is not None and balance["quantity"] is not None,
                "UNKNOWN_QUANTITY_MERGE",
                "Неизвестный остаток нужно сохранить отдельной партией.",
            )
            qty += balance["quantity"]
        balance["quantity"] = qty
        balance["quantity_state"] = (
            "estimated"
            if "estimated" in (v["quantity_state"], balance["quantity_state"])
            else v["quantity_state"]
        )
        self.confirm_balance(balance)
        return {
            "creates_item": v["item_mode"] == "create",
            "creates_lot": v["lot_mode"] == "create",
            "item_id": item["id"],
            "lot_id": lot["id"],
            "location_label": location["name"],
            "quantity_after": str(qty) if qty is not None else None,
        }

    def source(self, v):
        lot, item = self.lot_item(v["lot_id"])
        location = self.location(v["location_id"]) if v["location_id"] else None
        require(location, "FIELD_REQUIRED", "Выберите исходное место.", 422, field="location_id")
        return lot, item, self.balance(lot["id"], location["id"])

    def amount(self, v, item, balance):
        require(
            balance["quantity"] is not None,
            "UNKNOWN_QUANTITY",
            "Сначала установите количество или переместите целиком.",
        )
        require(
            v["quantity"] is not None and Decimal(v["quantity"]) > 0,
            "FIELD_REQUIRED",
            "Укажите положительное количество.",
            422,
            field="quantity",
        )
        amount = convert_quantity(
            Decimal(v["quantity"]), v.get("unit_code") or item["base_unit_id"], item["base_unit_id"]
        )
        require(
            amount <= balance["quantity"],
            "INSUFFICIENT_STOCK",
            "В выбранном месте недостаточно остатка.",
            available=str(balance["quantity"]),
        )
        return amount

    def move_stock(self, v):
        lot, item, source = self.source(v)
        require(v["to_location_id"], "FIELD_REQUIRED", "Выберите целевое место.", 422, field="to_location_id")
        target_location = self.location(v["to_location_id"])
        if source["location_id"] == target_location["id"]:
            return {"message": "Источник и назначение совпадают, перемещение не требуется."}
        if v["whole_presence"] and source["quantity"] is None:
            target = next(
                (
                    b
                    for b in self.rows["balance"].values()
                    if b["lot_id"] == lot["id"] and b["location_id"] == target_location["id"]
                ),
                None,
            )
            require(
                target is None,
                "UNKNOWN_QUANTITY_MERGE",
                "В назначении уже есть эта партия. Установите общий остаток или выделите новую партию.",
            )
            source["location_id"] = target_location["id"]
            self.confirm_balance(source)
            return {"whole_presence": True}
        amount = source["quantity"] if v["whole_presence"] else self.amount(v, item, source)
        require(amount is not None, "UNKNOWN_QUANTITY", "Неизвестное количество переносится только целиком.")
        target = self.balance(lot["id"], target_location["id"], create=True)
        require(
            target["quantity"] is not None,
            "UNKNOWN_QUANTITY_MERGE",
            "Назначение содержит неизвестный остаток.",
        )
        source["quantity"] -= amount
        target["quantity"] += amount
        target["quantity_state"] = (
            "estimated" if "estimated" in (target["quantity_state"], source["quantity_state"]) else "exact"
        )
        self.confirm_balance(source)
        self.confirm_balance(target)
        return {
            "quantity": str(amount),
            "source_after": str(source["quantity"]),
            "target_after": str(target["quantity"]),
        }

    def consume_stock(self, v):
        _, item, balance = self.source(v)
        amount = self.amount(v, item, balance)
        balance["quantity"] -= amount
        self.confirm_balance(balance)
        return {"quantity_after": str(balance["quantity"])}

    def set_quantity(self, v):
        _, _, balance = self.source(v)
        balance["quantity"] = Decimal(v["quantity"]) if v["quantity"] is not None else None
        balance["quantity_state"] = v["quantity_state"]
        self.confirm_balance(balance)

    def confirm_presence(self, v):
        _, _, balance = self.source(v)
        self.confirm_balance(balance)

    def update_item(self, v):
        item = self.item(v["item_id"])
        for key, value in v.items():
            if key != "item_id":
                require(
                    value is not None or key in {"barcode", "brand", "model", "user_description"},
                    "FIELD_REQUIRED",
                    "Это поле нельзя очистить.",
                    422,
                    field=key,
                )
                item[key] = value

    def update_lot(self, v):
        lot, item = self.lot_item(v["lot_id"])
        if v.get("opened_on") and v["opened_on"] != lot["opened_on"]:
            quantity = sum(
                b["quantity"] or Decimal(0) for b in self.rows["balance"].values() if b["lot_id"] == lot["id"]
            )
            require(
                quantity <= 1 or item["base_unit_id"] not in {"package", "pcs"},
                "SPLIT_REQUIRED",
                "Перед открытием одной из нескольких упаковок выделите её в отдельную партию.",
            )
        for key, value in v.items():
            if key == "lot_id":
                continue
            require(
                key != "privacy_policy" or value is not None,
                "FIELD_REQUIRED",
                "Выберите режим обработки.",
                422,
                field=key,
            )
            lot["attributes" if key == "lot_attributes" else key] = (
                as_date(value) if key in DATE_FIELDS else value
            )
        require(
            item["privacy_policy"] != "local_only" or lot["privacy_policy"] == "local_only",
            "POLICY_RESTRICTED",
            "Партия наследует локальную обработку карточки.",
            403,
        )
        self.set_expiry(lot)

    def split_lot(self, v):
        source, item, balance = self.source(v)
        require(
            item["tracking_mode"] in {"counted", "measured"},
            "SPLIT_NOT_ALLOWED",
            "Этот режим учёта не допускает дробление.",
        )
        amount = self.amount(v, item, balance)
        values = {
            k: deepcopy(value)
            for k, value in source.items()
            if k not in {"id", "version", "created_at", "updated_at", "workspace_id"}
        }
        values["parent_lot_id"] = source["id"]
        for key in LOT_FIELDS:
            if v.get(key) is not None and not (key == "expiry_precision" and v[key] == "unknown"):
                values[key] = as_date(v[key]) if key in DATE_FIELDS else v[key]
        if v["lot_attributes"]:
            values["attributes"] = v["lot_attributes"]
        lot = self.create("lot", **values)
        self.set_expiry(lot)
        balance["quantity"] -= amount
        target = self.create(
            "balance",
            lot_id=lot["id"],
            location_id=balance["location_id"],
            quantity=amount,
            quantity_state=balance["quantity_state"],
        )
        self.confirm_balance(balance)
        self.confirm_balance(target)
        return {"lot_id": lot["id"], "quantity": str(amount)}

    def merge_lots(self, v):
        require(
            len(set(v["lot_ids"])) == len(v["lot_ids"]), "INVALID_LOTS", "Партии не должны повторяться.", 422
        )
        lots = [self.lot_item(i)[0] for i in v["lot_ids"]]
        target = lots[0]
        require(
            self.item(target["item_id"])["tracking_mode"] in {"counted", "measured"},
            "MERGE_NOT_ALLOWED",
            "Экземпляры и присутствие не объединяются.",
        )
        compatible = {"item_id", "privacy_policy", "attributes", *LOT_FIELDS}
        for source in lots[1:]:
            require(
                all(source[key] == target[key] for key in compatible),
                "LOT_INCOMPATIBLE",
                "Партии отличаются по сроку, варианту или приватности.",
            )
            for balance in list(self.rows["balance"].values()):
                if balance["lot_id"] != source["id"]:
                    continue
                dest = self.balance(target["id"], balance["location_id"], create=True)
                require(
                    balance["quantity"] is not None and dest["quantity"] is not None,
                    "UNKNOWN_QUANTITY_MERGE",
                    "Сначала установите количество.",
                )
                dest["quantity"] += balance["quantity"]
                if balance["quantity_state"] == "estimated":
                    dest["quantity_state"] = "estimated"
                balance["quantity"] = Decimal(0)
            source["archived_at"] = utcnow()
            # parent_lot_id хранит происхождение при разделении. Связь слияния
            # остаётся в журнале; подмена родителя создала бы цикл с потомком.

    def create_location(self, v):
        require(v["name"], "FIELD_REQUIRED", "Укажите название места.", 422, field="name")
        if v["parent_id"]:
            self.location(v["parent_id"])
        location = self.create("location", **v)
        return {"location_id": location["id"]}

    def move_location(self, v):
        location = self.location(v["location_id"])
        require(
            location["kind"] != "system_unspecified", "SYSTEM_LOCATION", "Системное место нельзя перемещать."
        )
        if v["parent_id"]:
            self.location(v["parent_id"])
        location["parent_id"] = v["parent_id"]

    def update_location(self, v):
        location = self.location(v["location_id"])
        require(
            location["kind"] != "system_unspecified", "SYSTEM_LOCATION", "Системное место нельзя изменять."
        )
        for key, value in v.items():
            if key != "location_id":
                require(
                    key != "name" or value is not None,
                    "FIELD_REQUIRED",
                    "Название нельзя очистить.",
                    422,
                    field=key,
                )
                location[key] = value

    def archive_location(self, v):
        location = self.location(v["location_id"])
        require(
            location["kind"] != "system_unspecified",
            "SYSTEM_LOCATION",
            "Системное место нельзя архивировать.",
        )
        balances = [
            b
            for b in self.rows["balance"].values()
            if b["location_id"] == location["id"] and (b["quantity"] is None or b["quantity"] > 0)
        ]
        children = [
            loc
            for loc in self.rows["location"].values()
            if loc["parent_id"] == location["id"] and not loc["archived_at"]
        ]
        require(
            not (balances or children) or v["transfer_to_id"],
            "LOCATION_NOT_EMPTY",
            "Выберите место для переноса содержимого.",
        )
        if v["transfer_to_id"]:
            target = self.location(v["transfer_to_id"])
            require(
                target["id"] != location["id"],
                "INVALID_LOCATION_TREE",
                "Нельзя перенести содержимое в архивируемое место.",
            )
            for balance in balances:
                self.move_stock(
                    {
                        "lot_id": balance["lot_id"],
                        "location_id": location["id"],
                        "to_location_id": target["id"],
                        "quantity": None,
                        "whole_presence": True,
                    }
                )
            for child in children:
                child["parent_id"] = target["id"]
        location["archived_at"] = utcnow()

    def archive_item(self, v):
        item = self.item(v["item_id"])
        item.update(lifecycle="archived", archived_at=utcnow())

    def restore_item(self, v):
        item = self.get("item", v["item_id"])
        require(
            item["lifecycle"] == "archived",
            "ITEM_NOT_ARCHIVED",
            "Можно восстановить только архивную карточку.",
        )
        item.update(lifecycle="active", archived_at=None)

    def add_alias(self, v):
        item = self.item(v["item_id"])
        require(v["alias"], "FIELD_REQUIRED", "Укажите название.", 422, field="alias")
        self.create(
            "alias",
            item_id=item["id"],
            alias=v["alias"],
            normalized_alias=v["alias"].casefold(),
            scope=v["scope"],
            created_by=self.user_id,
        )
        item["search_revision"] += 1

    def remove_alias(self, v):
        alias = self.get("alias", v["alias_id"])
        alias["active"] = False
        self.item(alias["item_id"])["search_revision"] += 1

    def reverse_operation(self, v):
        entries = self.history.get(v["operation_id"])
        require(entries, "NOT_FOUND", "Операция не найдена.", 404)
        # Несколько действий одной операции могут менять одну запись: восстанавливаем
        # первое состояние, проверяя последнюю версию, без отката номера версии.
        grouped = {}
        for entry in entries:
            key = (entry["entity_type"], entry["entity_id"])
            if key not in grouped:
                grouped[key] = {**entry}
            grouped[key]["after_version"] = entry["after_version"]
        for entry in reversed(list(grouped.values())):
            kind = entry["entity_type"]
            current = self.get(kind, entry["entity_id"])
            require(
                current["version"] == entry["after_version"],
                "REVERSE_CONFLICT",
                "После операции данные изменились. Требуется отдельная корректировка.",
            )
            previous = entry["before_state"]
            if previous is None:
                if kind == "balance":
                    # Неизвестное присутствие остаётся неизвестным у архивной партии.
                    if current["quantity"] is not None:
                        current["quantity"] = Decimal(0)
                elif kind == "item":
                    current.update(lifecycle="archived", archived_at=utcnow())
                elif kind in {"lot", "location"}:
                    current["archived_at"] = utcnow()
                elif kind == "alias":
                    current["active"] = False
            else:
                for key, value in previous.items():
                    if key in {
                        "version",
                        "created_at",
                        "updated_at",
                        "search_revision",
                        "indexed_revision",
                        "expiry_generation",
                    }:
                        continue
                    column = ENTITIES[kind].__table__.columns[key]
                    if value is not None and isinstance(column.type, type(Balance.__table__.c.quantity.type)):
                        value = Decimal(value)
                    elif value is not None and key in DATE_FIELDS:
                        value = as_date(value)
                    elif value is not None and key.endswith("_at"):
                        from datetime import datetime

                        value = datetime.fromisoformat(value)
                    current[key] = value


async def load_state(db, workspace_id, user_id, settings, actions=()):
    rows = {}
    for kind, model in ENTITIES.items():
        entities = (await db.scalars(select(model).where(model.workspace_id == workspace_id))).all()
        rows[kind] = {row.id: row_state(row) for row in entities}
    history = {}
    for action in actions:
        if action["type"] == "reverse_operation":
            operation_id = action["values"]["operation_id"]
            operation = await db.scalar(
                select(Operation).where(Operation.id == operation_id, Operation.workspace_id == workspace_id)
            )
            require(
                operation and operation.status not in {"deleted", "purged"},
                "NOT_FOUND",
                "Операция не найдена.",
                404,
            )
            history[operation_id] = [
                row_state(e)
                for e in (
                    await db.scalars(
                        select(Entry).where(Entry.operation_id == operation_id).order_by(Entry.ordinal)
                    )
                ).all()
            ]
    return InventoryState(workspace_id, user_id, rows, settings, history)


async def persist_state(db, state, operation_id):
    changed_items = set()
    for kind, model in ENTITIES.items():
        for entity_id, values in state.rows[kind].items():
            previous = state.original[kind].get(entity_id)
            if previous == values:
                continue
            if previous:
                row = await db.get(model, entity_id)
                for key, value in values.items():
                    setattr(row, key, value)
            else:
                db.add(model(**values))
            if kind == "item":
                changed_items.add(entity_id)
            elif kind in {"lot", "alias"}:
                changed_items.add(values["item_id"])
            elif kind == "balance":
                changed_items.add(state.rows["lot"][values["lot_id"]]["item_id"])
        await db.flush()
    for entry in state.entries:
        db.add(Entry(operation_id=operation_id, **entry))
    for item_id in changed_items:
        item = state.rows["item"][item_id]
        db.add(
            Outbox(
                workspace_id=state.workspace_id,
                event_type="index_item",
                entity_id=item_id,
                entity_version=item["version"],
            )
        )
    if state.entries:
        workspace = await db.get(Workspace, state.workspace_id)
        workspace.version += 1
        workspace.updated_at = utcnow()
        db.add(
            Outbox(workspace_id=state.workspace_id, event_type="plan_reminders", entity_id=state.workspace_id)
        )
