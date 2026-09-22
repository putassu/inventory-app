from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import or_, select

from app.api.catalog import page, serialize
from app.api.deps import database, idempotency_key, scope, write_scope
from app.application.idempotency import previous_response, remember
from app.application.notifications import ReminderValues
from app.db.models import Location, Notification, Outbox, ReminderRule
from app.db.session import scoped_get
from app.domain.common import utcnow
from app.domain.errors import require
from app.domain.schemas import StrictModel

router = APIRouter()


@router.get("/notifications")
async def notifications(
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
    selected=Depends(scope),
    db=Depends(database),
):
    return await page(
        db,
        select(Notification).where(
            Notification.workspace_id == selected.workspace_id,
            Notification.user_id == selected.user.id,
            Notification.dismissed_at.is_(None),
            or_(Notification.snoozed_until.is_(None), Notification.snoozed_until <= utcnow()),
        ),
        Notification,
        limit,
        cursor,
    )


class NotificationPatch(StrictModel):
    expected_version: int = Field(ge=1)
    mark_read: bool = False
    dismiss: bool = False


@router.patch("/notifications/{notification_id}")
async def update_notification(
    notification_id: UUID, data: NotificationPatch, selected=Depends(write_scope), db=Depends(database)
):
    row = await scoped_get(db, Notification, notification_id, selected.workspace_id)
    require(row.user_id == selected.user.id, "NOT_FOUND", "Уведомление не найдено.", 404)
    require(row.version == data.expected_version, "VERSION_CONFLICT", "Уведомление изменилось.")
    if data.mark_read:
        row.read_at = utcnow()
    if data.dismiss:
        row.dismissed_at = utcnow()
    row.version += 1
    return serialize(row)


class Snooze(StrictModel):
    hours: int = Field(ge=1, le=168)
    expected_version: int = Field(ge=1)


@router.post("/notifications/{notification_id}/snooze")
async def snooze(
    notification_id: UUID,
    data: Snooze,
    key=Depends(idempotency_key),
    selected=Depends(write_scope),
    db=Depends(database),
):
    body = data.model_dump()
    operation_scope = f"snooze:{notification_id}"
    cached = await previous_response(db, selected.user.id, selected.workspace_id, operation_scope, key, body)
    if cached:
        return cached
    row = await scoped_get(db, Notification, notification_id, selected.workspace_id)
    require(row.user_id == selected.user.id, "NOT_FOUND", "Уведомление не найдено.", 404)
    require(row.version == data.expected_version, "VERSION_CONFLICT", "Уведомление изменилось.")
    row.snoozed_until = utcnow() + timedelta(hours=data.hours)
    row.version += 1
    return remember(db, selected.user.id, selected.workspace_id, operation_scope, key, body, serialize(row))


@router.get("/reminder-rules")
async def rules(
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
    selected=Depends(scope),
    db=Depends(database),
):
    return await page(
        db,
        select(ReminderRule).where(
            ReminderRule.workspace_id == selected.workspace_id, ReminderRule.owner_user_id == selected.user.id
        ),
        ReminderRule,
        limit,
        cursor,
    )


@router.post("/reminder-rules", status_code=201)
async def create_rule(
    data: ReminderValues, key=Depends(idempotency_key), selected=Depends(write_scope), db=Depends(database)
):
    body = data.model_dump(mode="json")
    cached = await previous_response(db, selected.user.id, selected.workspace_id, "reminder_rule", key, body)
    if cached:
        return cached
    for location_id in data.location_ids:
        await scoped_get(db, Location, location_id, selected.workspace_id)
    row = ReminderRule(workspace_id=selected.workspace_id, owner_user_id=selected.user.id, values=body)
    db.add(row)
    await db.flush()
    db.add(
        Outbox(
            workspace_id=selected.workspace_id, event_type="plan_reminders", entity_id=selected.workspace_id
        )
    )
    return remember(db, selected.user.id, selected.workspace_id, "reminder_rule", key, body, serialize(row))


class RulePatch(StrictModel):
    expected_version: int = Field(ge=1)
    values: ReminderValues
    enabled: bool = True


@router.patch("/reminder-rules/{rule_id}")
async def update_rule(rule_id: UUID, data: RulePatch, selected=Depends(write_scope), db=Depends(database)):
    row = await scoped_get(db, ReminderRule, rule_id, selected.workspace_id)
    require(row.owner_user_id == selected.user.id, "NOT_FOUND", "Правило не найдено.", 404)
    require(row.version == data.expected_version, "VERSION_CONFLICT", "Правило уже изменилось.")
    for location_id in data.values.location_ids:
        await scoped_get(db, Location, location_id, selected.workspace_id)
    row.values, row.enabled = data.values.model_dump(mode="json"), data.enabled
    row.version += 1
    db.add(
        Outbox(
            workspace_id=selected.workspace_id, event_type="plan_reminders", entity_id=selected.workspace_id
        )
    )
    return serialize(row)


@router.delete("/reminder-rules/{rule_id}")
async def delete_rule(
    rule_id: UUID, expected_version: int, selected=Depends(write_scope), db=Depends(database)
):
    row = await scoped_get(db, ReminderRule, rule_id, selected.workspace_id)
    require(row.owner_user_id == selected.user.id, "NOT_FOUND", "Правило не найдено.", 404)
    require(row.version == expected_version, "VERSION_CONFLICT", "Правило уже изменилось.")
    row.enabled = False
    row.version += 1
    db.add(
        Outbox(
            workspace_id=selected.workspace_id, event_type="plan_reminders", entity_id=selected.workspace_id
        )
    )
    return {"status": "disabled"}
