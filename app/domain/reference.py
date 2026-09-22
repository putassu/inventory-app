from decimal import Decimal, InvalidOperation

from app.domain.errors import require

CATEGORIES = {
    "medicine": "Лекарства",
    "document": "Документы",
    "food": "Продукты",
    "clothing": "Одежда",
    "equipment": "Техника",
    "dishes": "Посуда",
    "cosmetics": "Косметика",
    "household": "Быт",
    "hobby": "Хобби",
    "other": "Другое",
}
# Коэффициент задан к общей единице измерения, но не к таблеткам или упаковкам.
UNITS = {
    "pcs": ("шт.", "count", "1", "1"),
    "pair": ("пара", "count", "2", "1"),
    "tablet": ("таблетка", "tablet", "1", "1"),
    "capsule": ("капсула", "capsule", "1", "1"),
    "package": ("упаковка", "package", "1", "1"),
    "g": ("г", "mass", "1", "0.001"),
    "kg": ("кг", "mass", "1000", "0.001"),
    "mg": ("мг", "mass", "0.001", "0.001"),
    "ml": ("мл", "volume", "1", "0.001"),
    "l": ("л", "volume", "1000", "0.001"),
    "m": ("м", "length", "1", "0.001"),
    "cm": ("см", "length", "0.01", "0.001"),
}
ATTRIBUTES = {
    "medicine": {"active_ingredients", "strength", "dosage_form", "brand"},
    "document": {"document_type", "owner_name", "masked_number"},
    "food": {"brand", "storage_conditions"},
    "clothing": {"size", "season", "brand", "color", "material", "counting_unit"},
    "equipment": {"brand", "model"},
    "dishes": {"material", "purpose"},
    "cosmetics": {"brand", "purpose"},
    "household": {"purpose", "brand", "storage_conditions"},
    "hobby": {"tags"},
    "other": {"color", "material", "purpose"},
}
ATTRIBUTE_LABELS = {
    "active_ingredients": "Действующие вещества",
    "strength.raw": "Дозировка на упаковке",
    "strength.value": "Значение дозировки",
    "strength.unit": "Единица дозировки",
    "dosage_form": "Лекарственная форма",
    "brand": "Марка",
    "document_type": "Тип документа",
    "owner_name": "Владелец документа",
    "masked_number": "Скрытый номер",
    "storage_conditions": "Условия хранения",
    "size": "Размер",
    "season": "Сезон",
    "color": "Цвет",
    "material": "Материал",
    "model": "Модель",
    "purpose": "Назначение",
    "tags": "Признаки",
    "counting_unit": "Предпочтительная единица счёта",
}
LIST_ATTRIBUTES = {"active_ingredients", "tags"}


def validate_attributes(category, attributes):
    require(
        not (set(attributes) - ATTRIBUTES[category]),
        "INVALID_ATTRIBUTES",
        "Атрибуты не входят в схему категории.",
        422,
    )
    for key, value in attributes.items():
        if key in LIST_ATTRIBUTES:
            valid = (
                isinstance(value, list)
                and len(value) <= 30
                and all(isinstance(part, str) and 0 < len(part) <= 255 for part in value)
            )
        elif key == "strength":
            valid = isinstance(value, dict) and not (set(value) - {"raw", "value", "unit"})
            if valid:
                valid = all(
                    isinstance(part, str) and len(part) <= 255
                    for name, part in value.items()
                    if name != "value"
                )
            if valid and "value" in value:
                number = value["value"]
                try:
                    valid = isinstance(number, (str, int)) and not isinstance(number, bool)
                    decimal = Decimal(number) if valid else Decimal("NaN")
                    exponent = decimal.normalize().as_tuple().exponent
                    valid = (
                        valid
                        and decimal.is_finite()
                        and 0 <= decimal < Decimal("100000000000000")
                        and isinstance(exponent, int)
                        and exponent >= -6
                    )
                except (InvalidOperation, ValueError):
                    valid = False
        else:
            valid = isinstance(value, str) and len(value) <= 2000
        require(valid, "INVALID_ATTRIBUTES", "Неверный тип свойства.", 422, field="attributes." + key)


def convert_quantity(quantity: Decimal, source: str, target: str, package_size=None) -> Decimal:
    require(
        source in UNITS and target in UNITS, "INVALID_UNIT_CONVERSION", "Выберите известную единицу.", 422
    )
    if source == target:
        return quantity
    if source == "package" and package_size is not None:
        require(
            Decimal(package_size) > 0,
            "INVALID_UNIT_CONVERSION",
            "Размер упаковки должен быть положительным.",
            422,
        )
        return quantity * Decimal(package_size)
    require(UNITS[source][1] == UNITS[target][1], "INVALID_UNIT_CONVERSION", "Единицы несовместимы.", 422)
    return quantity * Decimal(UNITS[source][2]) / Decimal(UNITS[target][2])
