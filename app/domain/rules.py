import calendar
from datetime import UTC, date, datetime
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from app.domain.common import utcnow
from app.domain.errors import require
from app.domain.reference import ATTRIBUTES, UNITS, validate_attributes


def validate_quantity(mode, quantity, state, step=Decimal(1)):
    require(step > 0, "INVALID_QUANTITY", "Шаг должен быть положительным.", 422)
    require(
        (quantity is None) == (state in {"unknown", "not_applicable"}),
        "INVALID_QUANTITY",
        "Количество не соответствует состоянию.",
        422,
    )
    if mode == "untracked":
        require(
            quantity is None and state == "not_applicable",
            "INVALID_QUANTITY",
            "Для присутствия количество не применяется.",
            422,
        )
    else:
        require(
            state != "not_applicable", "INVALID_QUANTITY", "Выберите известный или неизвестный остаток.", 422
        )
    if quantity is not None:
        require(
            quantity.is_finite()
            and 0 <= quantity < Decimal("100000000000000")
            and quantity.normalize().as_tuple().exponent >= -6
            and quantity % step == 0,
            "INVALID_QUANTITY",
            "Количество должно быть неотрицательным и кратным шагу.",
            422,
        )
    if mode == "individual":
        require(
            state == "exact" and quantity in {Decimal(0), Decimal(1)},
            "INVALID_QUANTITY",
            "Уникальный экземпляр имеет остаток 0 или 1.",
            422,
        )


def validate_item(item):
    require(item.primary_category in ATTRIBUTES, "INVALID_CATEGORY", "Неизвестная категория.", 422)
    validate_attributes(item.primary_category, item.attributes)
    require(
        item.tracking_mode == "untracked" or item.base_unit_id in UNITS,
        "UNKNOWN_UNIT",
        "Выберите единицу измерения или учёт присутствия.",
        422,
    )
    if item.primary_category == "document":
        require(
            item.privacy_policy == "local_only",
            "POLICY_RESTRICTED",
            "Документ обрабатывается только локально.",
            403,
        )


def effective_expiry(expiry_on, precision, raw, opened, amount, unit, month_policy):
    declared = expiry_on
    derivation = "explicit" if declared else "unknown"
    if precision == "month":
        try:
            month = date.fromisoformat((raw or str(expiry_on)[:7])[:7] + "-01")
        except (ValueError, TypeError):
            month = None
        declared = None
        if month and month_policy:
            declared = (
                month
                if month_policy == "first_day"
                else month.replace(day=calendar.monthrange(month.year, month.month)[1])
            )
            derivation = "normalized_month"
    elif precision == "unknown":
        declared = None
    opened_expiry = None
    if opened and amount and unit:
        opened_expiry = opened + (
            relativedelta(months=amount) if unit == "month" else relativedelta(days=amount)
        )
    if opened_expiry and declared:
        return min(declared, opened_expiry), "minimum"
    if opened_expiry:
        return opened_expiry, "after_opening"
    return declared, derivation


def aggregate(balances, tracking_mode):
    known = sum((b.quantity for b in balances if b.quantity is not None), Decimal(0))
    unknown = any(b.quantity_state == "unknown" for b in balances)
    return {
        "known_quantity": str(known),
        "has_unknown_quantity": unknown,
        "is_estimated": any(b.quantity_state == "estimated" for b in balances),
        "depleted": tracking_mode != "untracked" and not unknown and known == 0,
    }


def effective_privacy(
    *policies, force_local=False, external_enabled=False, decision="uncertain", category=None
):
    restricted = force_local or not external_enabled or decision != "non_sensitive" or category == "document"
    return "local_only" if restricted or "local_only" in policies else "cloud_allowed"


TRANSITIONS = {
    "accepted": {"preparing", "cancelled", "failed"},
    "preparing": {"queued", "waiting_for_review", "failed", "cancelled"},
    "queued": {"running", "cancelled", "expired"},
    "running": {"queued", "retry_wait", "waiting_for_review", "succeeded", "failed", "cancelled"},
    "retry_wait": {"queued", "failed", "cancelled", "expired"},
    "waiting_for_review": {"applying", "cancelled", "expired"},
    "applying": {"succeeded", "waiting_for_review", "failed"},
    "failed": set(),
    "succeeded": set(),
    "cancelled": set(),
    "expired": set(),
}


def transition(task, status, stage=None):
    require(
        status in TRANSITIONS.get(task.status, set()), "INVALID_TASK_STATE", "Переход состояния запрещён."
    )
    now = utcnow()
    progress = dict(getattr(task, "progress", None) or {})
    history = list(progress.get("history", []))
    previous = progress.get("current")
    if previous:
        started = datetime.fromisoformat(previous["started_at"]).replace(tzinfo=UTC)
        duration = max(0, round((now - started).total_seconds() * 1000))
        history.append(
            {
                **previous,
                "finished_at": now.isoformat(),
                "duration_ms": duration,
                "error_code": getattr(task, "error_code", None),
            }
        )
    task.progress = {
        "current": {"stage": stage or task.stage, "status": status, "started_at": now.isoformat()},
        "history": history[-64:],
        "percent": None,
        "estimated_remaining_ms": None,
    }
    task.status = status
    task.stage = stage or task.stage
    task.status_version += 1
