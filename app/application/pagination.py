"""Сортировка и курсоры привязаны к фильтрам; равные значения разделяет ID."""

import base64
import json
from datetime import date, datetime
from typing import Literal

from sqlalchemy import String, and_, case, cast, func, or_, select

from app.db.models import Item, Lot
from app.domain.common import digest, jsonable
from app.domain.errors import DomainError, require

ItemSort = Literal["newest", "oldest", "name_asc", "name_desc", "status", "expiry"]
ReviewStatus = Literal["processing", "unconfirmed", "confirmed", "error"]
STATUS_ORDER = {"error": 0, "unconfirmed": 1, "processing": 2, "confirmed": 3}


def item_order(sort):
    expiry = (
        select(func.min(Lot.effective_expiry_on))
        .where(
            Lot.item_id == Item.id,
            Lot.workspace_id == Item.workspace_id,
            Lot.archived_at.is_(None),
        )
        .correlate(Item)
        .scalar_subquery()
    )
    return {
        "newest": [(Item.created_at, True)],
        "oldest": [(Item.created_at, False)],
        "name_asc": [(cast(func.lower(Item.name), String), False)],
        "name_desc": [(cast(func.lower(Item.name), String), True)],
        "status": [(case(STATUS_ORDER, value=Item.review_status, else_=3), False), (Item.created_at, True)],
        "expiry": [(func.coalesce(expiry, date(9999, 12, 31)), False)],
    }[sort] + [(Item.id, False)]


async def ordered_page(db, query, model, order, scope, limit=50, cursor=None):
    identity = digest([model.__tablename__, scope])
    if cursor:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(cursor))
            require(
                decoded["scope"] == identity and len(decoded["values"]) == len(order),
                "INVALID_CURSOR",
                "Курсор относится к другой сортировке или фильтрам.",
                400,
            )
            previous = []
            alternatives = []
            for (expression, descending), value in zip(order, decoded["values"], strict=True):
                kind = expression.type.python_type
                if kind in {date, datetime}:
                    value = kind.fromisoformat(value)
                else:
                    require(type(value) is kind, "INVALID_CURSOR", "Некорректный курсор.", 400)
                alternatives.append(and_(*previous, expression < value if descending else expression > value))
                previous.append(expression == value)
            query = query.where(or_(*alternatives))
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise DomainError("INVALID_CURSOR", "Некорректный курсор.", 400) from error
    rows = (
        await db.execute(
            query.add_columns(*(column for column, _ in order))
            .order_by(*(column.desc() if descending else column.asc() for column, descending in order))
            .limit(limit + 1)
        )
    ).all()
    more = len(rows) > limit
    visible = rows[:limit]
    next_cursor = (
        base64.urlsafe_b64encode(
            json.dumps(
                {
                    "scope": identity,
                    "values": jsonable(list(visible[-1][1:])),
                }
            ).encode()
        ).decode()
        if more
        else None
    )
    return [row[0] for row in visible], {"has_more": more, "next_cursor": next_cursor}
