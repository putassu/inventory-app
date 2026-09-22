from sqlalchemy import select

from app.db.models import Idempotency
from app.domain.common import digest, jsonable
from app.domain.errors import require


async def previous_response(db, user_id, workspace_id, scope, key, body):
    require(key and 1 <= len(key) <= 200, "IDEMPOTENCY_KEY_REQUIRED", "Передайте Idempotency-Key.", 400)
    row = await db.scalar(
        select(Idempotency).where(
            Idempotency.user_id == user_id,
            Idempotency.workspace_id == workspace_id,
            Idempotency.operation_scope == scope,
            Idempotency.key == key,
        )
    )
    if row:
        require(
            row.request_hash == digest(body),
            "IDEMPOTENCY_KEY_REUSED",
            "Ключ уже использован для другого запроса.",
        )
        return row.response
    return None


def remember(db, user_id, workspace_id, scope, key, body, response):
    db.add(
        Idempotency(
            user_id=user_id,
            workspace_id=workspace_id,
            operation_scope=scope,
            key=key,
            request_hash=digest(body),
            response=jsonable(response),
        )
    )
    return response
