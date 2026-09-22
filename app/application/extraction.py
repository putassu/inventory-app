"""Совместимость настроенного JSON старых промптов с extraction.v1."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import Field

from app.domain.errors import require
from app.domain.reference import ATTRIBUTES
from app.domain.schemas import Action, Extraction, StrictModel

CATEGORY_MAP = {
    "MEDICINES": "medicine",
    "DOCUMENTS": "document",
    "CLOTHES": "clothing",
    "TECH": "equipment",
    "FOOD": "food",
    "DISHES": "dishes",
    "COSMETICS": "cosmetics",
    "HOUSEHOLD": "household",
    "HOBBY": "hobby",
    "OTHER": "other",
}
UNIT_MAP = {
    "шт": "pcs",
    "шт.": "pcs",
    "штука": "pcs",
    "пара": "pair",
    "пару": "pair",
    "пары": "pair",
    "пар": "pair",
    "уп": "package",
    "уп.": "package",
    "таблетка": "tablet",
    "таблетки": "tablet",
    "г": "g",
    "кг": "kg",
    "мл": "ml",
    "л": "l",
}


class LegacyItem(StrictModel):
    name: str | None = None
    location: str | None = None
    quantity: Decimal | None = None
    unit_of_measure: str | None = None
    primary_category: str | None = None
    secondary_categories: list[str] | None = None
    tags: list[str] | None = None
    synonyms: list[str] | None = None
    merge_with_item_id: str | None = None
    document_summary: str | None = None
    attributes: dict = Field(default_factory=dict)


class LegacyMove(StrictModel):
    item_name: str | None = None
    target_item_id: str | None = None
    from_location: str | None = None
    to_location: str | None = None


class LegacyConsume(StrictModel):
    item_name: str | None = None
    target_item_id: str | None = None
    amount: Decimal | None = None


class LegacyOutput(StrictModel):
    intent: str
    confidence_score: float | None = Field(None, ge=0, le=1)
    item_details: LegacyItem | None = None
    move_details: LegacyMove | None = None
    consume_details: LegacyConsume | None = None
    has_schedule_mention: bool = False


def quantity(value):
    if value is None:
        return None
    try:
        number = Decimal(str(value))
        return str(number) if number.is_finite() and number >= 0 else None
    except InvalidOperation:
        return None


def expiry(value):
    if not value:
        return {"expiry_precision": "unknown"}
    raw = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}", raw):
        try:
            date.fromisoformat(raw + "-01")
            return {"expiry_on": None, "expiry_precision": "month", "expiry_raw_text": raw}
        except ValueError:
            pass
    try:
        parsed = date.fromisoformat(raw)
        return {"expiry_on": parsed.isoformat(), "expiry_precision": "day", "expiry_raw_text": raw}
    except ValueError:
        return {"expiry_precision": "unknown", "expiry_raw_text": raw[:255]}


def normalize_extraction(raw, candidates, locations, context, text="", *, collage_manifest=None):
    legacy = LegacyOutput.model_validate(raw)
    item = legacy.item_details or LegacyItem()
    move = legacy.move_details or LegacyMove()
    consume = legacy.consume_details or LegacyConsume()
    allowed = {candidate["candidate_id"]: candidate for candidate in candidates}
    for candidate_id in (item.merge_with_item_id, move.target_item_id, consume.target_item_id):
        require(
            candidate_id is None or candidate_id in allowed,
            "UNKNOWN_MODEL_CANDIDATE",
            "Модель выбрала неизвестный объект.",
            422,
        )
    category = CATEGORY_MAP.get(item.primary_category or "OTHER", "other")
    location_name = move.to_location or item.location
    location_matches = [
        loc["id"] for loc in locations if loc["name"].casefold() == (location_name or "").casefold()
    ]
    if not location_name:
        named = [
            loc for loc in locations if re.search(r"(?<!\w)" + re.escape(loc["name"]) + r"(?!\w)", text, re.I)
        ]
        if named:
            longest = max(len(loc["name"]) for loc in named)
            location_matches = [loc["id"] for loc in named if len(loc["name"]) == longest]
    location_id = context.get("location_id") or (location_matches[0] if len(location_matches) == 1 else None)
    attributes = {k: v for k, v in item.attributes.items() if k in ATTRIBUTES[category]}
    if category == "medicine":
        if item.attributes.get("active_ingredient"):
            attributes["active_ingredients"] = [item.attributes["active_ingredient"]]
        if item.attributes.get("dosage"):
            attributes["strength"] = {"raw": str(item.attributes["dosage"])}
    warnings = []
    if location_name and not location_id:
        warnings.append("Место из ввода не выбрано: " + location_name)
    if legacy.has_schedule_mention:
        warnings.append(
            "Графики приёма и произвольные таймеры не поддерживаются. Подтверждение относится только к учёту вещей."
        )
    uncertain_intent = bool(
        re.search(
            r"\b(не\s+(пил|выпил|ел|съел|переложил|выкинул)|собираюсь|планирую|потом|хочу)\b", text, re.I
        )
    )
    if uncertain_intent:
        warnings.append("В вводе есть отрицание или будущее намерение. Выберите действие вручную.")
    placement = bool(re.search(r"\bположил[аи]?\b", text, re.I)) and not uncertain_intent
    if placement and legacy.intent == "move_item" and not allowed and not context.get("item_id"):
        # Новую вещь нельзя переместить из выдуманного остатка.
        legacy.intent = "add_item"
        item.name = item.name or move.item_name
    if placement and allowed:
        uncertain_intent = True
        warnings.append("Найдены похожие вещи: выберите новое поступление или перенос уже учтённого остатка.")
    if legacy.intent == "add_item":
        unit = UNIT_MAP.get(item.unit_of_measure, item.unit_of_measure)
        amount = quantity(item.quantity)
        socks = bool(
            re.search(r"\bнос(?:ок|к[аиоуе]|ков|кам|ками|ках)\b", " ".join([text, item.name or ""]), re.I)
        )
        if socks:
            category = "clothing"
            attributes = {k: v for k, v in item.attributes.items() if k in ATTRIBUTES[category]}
            attributes["counting_unit"] = "pair"
            pair = re.search(
                r"\b(?:(одну|две|три|четыре|пять|\d+)\s+)?(пару|пара|пары|пар)\s+носк", text, re.I
            )
            if pair:
                count = pair.group(1) or "1"
                amount = {"одну": "1", "две": "2", "три": "3", "четыре": "4", "пять": "5"}.get(count, count)
                unit = "pair"
            elif re.search(r"\b(один|1)\s+носок\b", text, re.I):
                amount, unit = "1", "pcs"
            elif re.search(r"\b(два|2)\s+носка\b", text, re.I):
                amount, unit = "2", "pcs"
            elif unit is None:
                unit = "pcs"
        mode = (
            "untracked"
            if category == "document" or unit is None
            else "measured"
            if unit in {"g", "kg", "mg", "ml", "l", "m", "cm"}
            else "counted"
        )
        expiry_fields = expiry(item.attributes.get("expiry_date"))
        if collage_manifest and any(tile.get("small_tile") for tile in collage_manifest.get("tiles", [])):
            supplied_date = expiry_fields.get("expiry_raw_text")
            if supplied_date and supplied_date not in text:
                expiry_fields = {"expiry_precision": "unknown", "expiry_on": None, "expiry_raw_text": None}
                warnings.append(
                    "Срок не перенесён из мелкого коллажа: проверьте исходное фото или оставьте поле неизвестным."
                )
        values = {
            "item_mode": "existing" if item.merge_with_item_id else "create",
            "item_id": item.merge_with_item_id,
            "item_name": item.name,
            "category": category,
            "tracking_mode": mode,
            "unit_code": unit,
            "quantity_step": "0.001" if mode == "measured" else "1",
            "quantity": amount if mode != "untracked" else None,
            "quantity_state": "not_applicable"
            if mode == "untracked"
            else "exact"
            if amount is not None
            else "unknown",
            "location_id": location_id,
            "privacy_policy": "local_only",
            "attributes": attributes,
            "tags": item.tags or [],
            "generated_description": item.document_summary,
            **expiry_fields,
        }
        if item.attributes.get("serial_number"):
            values.update(
                tracking_mode="individual",
                unit_code="pcs",
                quantity="1",
                quantity_state="exact",
                serial_number=str(item.attributes["serial_number"]),
                item_mode="create",
                item_id=None,
            )
        action = Action(type="receive_stock", values=values)
    elif legacy.intent in {"consume_item", "move_item", "delete_item"}:
        candidate_id = consume.target_item_id if legacy.intent == "consume_item" else move.target_item_id
        candidate_id = candidate_id or context.get("item_id")
        require(
            candidate_id is None or candidate_id in allowed,
            "UNKNOWN_MODEL_CANDIDATE",
            "Выберите существующую карточку.",
            422,
        )
        candidate = allowed.get(candidate_id, {})
        lots = [
            lot
            for lot in candidate.get("lots", [])
            if lot["quantity"] is None or Decimal(lot["quantity"]) > 0
        ]
        chosen = lots[0] if len(lots) == 1 else {}
        if legacy.intent == "delete_item":
            action = Action(type="archive_item", values={"item_id": candidate_id})
        else:
            values = {
                "lot_id": chosen.get("lot_id"),
                "location_id": chosen.get("location_id"),
                "quantity": quantity(consume.amount)
                if legacy.intent == "consume_item"
                else quantity(item.quantity),
                "unit_code": candidate.get("unit_code"),
            }
            if legacy.intent == "move_item":
                values["to_location_id"] = location_id
                values["whole_presence"] = False
            action = Action(
                type="consume_stock" if legacy.intent == "consume_item" else "move_stock", values=values
            )
    elif legacy.intent in {"search", "find_item", "where_is"}:
        return Extraction(intent_candidates=["search"], read_only_query=text, quality_issues=warnings)
    else:
        action = Action(
            type="receive_stock", values={"tracking_mode": "untracked", "quantity_state": "not_applicable"}
        )
        warnings.append("Действие не распознано. Выберите его вручную.")
        uncertain_intent = True
    return Extraction(
        intent_candidates=[legacy.intent],
        extracted_entities=[{"name": item.name, "category": category}],
        actions=[action],
        ambiguity=["intent"] if uncertain_intent else [],
        quality_issues=warnings,
        privacy_signals=["document"] if category == "document" else [],
    )
