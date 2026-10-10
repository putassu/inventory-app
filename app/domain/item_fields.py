"""Настраиваемые поля инвентаря; скрытие не удаляет записанные значения."""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import Field

from app.domain.errors import require
from app.domain.reference import ATTRIBUTE_LABELS
from app.domain.schemas import Category, StrictModel

OPTIONAL_FIELDS = {
    "brand": "Марка",
    "model": "Модель",
    "barcode": "Штрихкод",
    "tags": "Метки",
    "user_description": "Описание",
    "ocr_text": "Полный текст OCR",
    "expiry_on": "Срок годности",
    "serial_number": "Серийный номер",
    "opened_on": "Дата открытия",
    "after_opening_amount": "Срок после открытия",
    "after_opening_unit": "Единица срока после открытия",
    "package_size": "Единиц в упаковке",
    **{"attributes." + key: label + " (по категории)" for key, label in ATTRIBUTE_LABELS.items()},
}


class CustomField(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=80)
    type: Literal["boolean", "string", "decimal", "date"]
    categories: list[Category] = Field(default_factory=list, max_length=10)
    enabled: bool = True


class ItemFields(StrictModel):
    hidden_fields: list[str] = Field(default_factory=list, max_length=100)
    custom_fields: list[CustomField] = Field(default_factory=list, max_length=50)


def validate_profile(profile, previous):
    fields = profile["custom_fields"]
    keys = [f["key"] for f in fields]
    require(
        not set(profile["hidden_fields"]) - OPTIONAL_FIELDS.keys(),
        "INVALID_FIELDS",
        "Неизвестное стандартное поле.",
        422,
    )
    require(
        len(keys) == len(set(keys)) and not {"constructor", "prototype"}.intersection(keys),
        "INVALID_FIELDS",
        "Ключи полей должны быть уникальными.",
        422,
    )
    require(
        len({f["label"].casefold() for f in fields}) == len(fields),
        "INVALID_FIELDS",
        "Названия полей должны различаться.",
        422,
    )
    by_key = {f["key"]: f for f in fields}
    for field in previous.get("custom_fields", []):
        require(
            field["key"] in by_key and by_key[field["key"]]["type"] == field["type"],
            "FIELD_TYPE_LOCKED",
            "Сохранённое поле можно переименовать или скрыть. Для другого типа создайте новое.",
            422,
        )


def validate_custom_values(values, profile):
    definitions = {f["key"]: f for f in profile.get("custom_fields", [])}
    require(
        isinstance(values, dict) and not values.keys() - definitions.keys(),
        "INVALID_CUSTOM_ATTRIBUTES",
        "Неизвестное пользовательское свойство.",
        422,
    )
    for key, value in values.items():
        kind = definitions[key]["type"]
        valid = value is None
        if kind == "boolean":
            valid |= type(value) is bool
        elif kind == "string":
            valid |= isinstance(value, str) and len(value) <= 2000
        elif kind == "date":
            try:
                valid |= isinstance(value, str) and date.fromisoformat(value).isoformat() == value
            except (ValueError, TypeError):
                pass
        elif kind == "decimal":
            try:
                number = Decimal(value) if isinstance(value, str) and len(value) <= 22 else Decimal("NaN")
                exponent = number.as_tuple().exponent
                valid |= (
                    number.is_finite()
                    and abs(number) < Decimal("1e14")
                    and isinstance(exponent, int)
                    and exponent >= -6
                )
            except (InvalidOperation, ValueError):
                pass
        require(
            valid,
            "INVALID_CUSTOM_ATTRIBUTES",
            "Неверный тип пользовательского свойства.",
            422,
            field="custom_attributes." + key,
        )


def custom_form_fields(action, profile):
    values = action["values"].get("custom_attributes") or {}
    category = action["values"].get("category") or action["values"].get("primary_category", "other")
    for field in profile.get("custom_fields", []):
        current = values.get(field["key"])
        applicable = not field["categories"] or category in field["categories"]
        yield {
            "action_id": action["action_id"],
            "key": "custom_attributes." + field["key"],
            "label": field["label"],
            "value_type": field["type"],
            "control": {
                "boolean": "checkbox",
                "string": "text_input",
                "decimal": "decimal_input",
                "date": "date_picker",
            }[field["type"]],
            "value": current,
            "required": False,
            "editable": action["values"].get("item_mode") != "existing",
            "allow_unknown": True,
            "options": [],
            "validation": {"min": "-99999999999999", "step": "0.000001"}
            if field["type"] == "decimal"
            else {},
            "hidden": not field["enabled"] or not applicable,
            "importance": "secondary",
            "source": "user",
            "verification_state": "unconfirmed",
        }
