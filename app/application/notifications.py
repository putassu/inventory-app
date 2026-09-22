import re
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, model_validator
from sqlalchemy import select

from app.application.auth import aware
from app.db.models import Balance, Item, Lot, Notification, Occurrence, ReminderRule, Workspace
from app.domain.common import digest, utcnow
from app.domain.rules import aggregate
from app.domain.schemas import StrictModel


class ReminderValues(StrictModel):
    categories: list[str] = Field(
        default_factory=lambda: ["medicine", "food", "document"], min_length=1, max_length=3
    )
    location_ids: list[str] = Field(default_factory=list, max_length=100)
    offsets_before_expiry: list[int] = Field(default_factory=lambda: [30, 7, 1], max_length=12)
    local_delivery_time: str = "09:00"
    timezone: str = "Europe/Moscow"
    quiet_hours: list[str] = Field(default_factory=lambda: ["22:00", "08:00"], max_length=2)
    send_expired: bool = True
    repeat_expired_interval: int = Field(7, ge=1, le=365)
    repeat_expired_max_count: int = Field(0, ge=0, le=12)
    group_mode: str = "by_day"
    channels: list[str] = Field(default_factory=lambda: ["in_app"])
    include_archived: bool = False
    hide_sensitive_details_on_lock_screen: bool = True

    @model_validator(mode="after")
    def validate_rules(self):
        if set(self.categories) - {"medicine", "food", "document"} or self.channels != ["in_app"]:
            raise ValueError("Поддерживаются только сроки лекарств, еды и документов и канал in_app.")
        if any(type(value) is not int or not 0 <= value <= 3650 for value in self.offsets_before_expiry):
            raise ValueError("Некорректные интервалы.")
        if self.group_mode not in {"by_day", "by_category", "none"}:
            raise ValueError("Неизвестный режим группировки.")
        if len(self.quiet_hours) not in {0, 2}:
            raise ValueError("Укажите начало и конец тихих часов.")
        try:
            ZoneInfo(self.timezone)
            if any(
                not re.fullmatch(r"\d{2}:\d{2}", value)
                for value in [self.local_delivery_time, *self.quiet_hours]
            ):
                raise ValueError("Используйте формат ЧЧ:ММ")
            time.fromisoformat(self.local_delivery_time)
            for value in self.quiet_hours:
                time.fromisoformat(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("Некорректное время или часовой пояс.") from exc
        if self.quiet_hours and self.quiet_hours[0] == self.quiet_hours[1]:
            raise ValueError("Начало и конец тихих часов должны различаться.")
        return self


def delivery_time(day, values):
    zone = ZoneInfo(values.timezone)
    target = datetime.combine(day, time.fromisoformat(values.local_delivery_time), zone)
    if values.quiet_hours:
        start, end = map(time.fromisoformat, values.quiet_hours)
        current = target.time()
        quiet = start <= current < end if start < end else current >= start or current < end
        if quiet:
            if start >= end and current >= start:
                day += timedelta(days=1)
            target = datetime.combine(day, end, zone)
    # Несуществующее время перехода на летнее время переносится вперёд на размер разрыва.
    return target.astimezone(UTC).astimezone(zone)


async def plan_workspace(factory, workspace_id, now=None):
    now = now or utcnow()
    async with factory() as db, db.begin():
        await db.get(Workspace, workspace_id, with_for_update=True)
        rules = (
            await db.scalars(select(ReminderRule).where(ReminderRule.workspace_id == workspace_id))
        ).all()
        lots = (await db.scalars(select(Lot).where(Lot.workspace_id == workspace_id))).all()
        items = {
            item.id: item
            for item in (await db.scalars(select(Item).where(Item.workspace_id == workspace_id))).all()
        }
        balances = (await db.scalars(select(Balance).where(Balance.workspace_id == workspace_id))).all()
        occurrences = (
            await db.scalars(select(Occurrence).where(Occurrence.workspace_id == workspace_id))
        ).all()
        existing = {o.dedupe_key: o for o in occurrences}
        valid_generations = {}
        due_groups = defaultdict(list)
        for rule in rules:
            values = ReminderValues.model_validate(rule.values)
            zone = ZoneInfo(values.timezone)
            today = now.astimezone(zone).date()
            for lot in lots:
                item = items[lot.item_id]
                stock = [b for b in balances if b.lot_id == lot.id]
                available = not aggregate(stock, item.tracking_mode)["depleted"]
                active = (
                    item.lifecycle == "active" or values.include_archived and item.lifecycle == "archived"
                )
                location_match = not values.location_ids or any(
                    b.location_id in values.location_ids for b in stock
                )
                if not (
                    rule.enabled
                    and active
                    and available
                    and location_match
                    and not lot.archived_at
                    and lot.effective_expiry_on
                    and item.primary_category in values.categories
                ):
                    continue
                if not values.send_expired and lot.effective_expiry_on < today:
                    continue
                generation = digest(
                    {"rule": rule.version, "lot": lot.expiry_generation, "expiry": lot.effective_expiry_on}
                )
                valid_generations[(rule.id, lot.id)] = generation
                targets = [
                    ("before:" + str(days), lot.effective_expiry_on - timedelta(days=days))
                    for days in set(values.offsets_before_expiry)
                ]
                if values.send_expired:
                    targets += [
                        (
                            "expired:" + str(n),
                            lot.effective_expiry_on + timedelta(days=1 + n * values.repeat_expired_interval),
                        )
                        for n in range(values.repeat_expired_max_count + 1)
                    ]
                due = []
                for threshold, day in sorted(targets, key=lambda p: p[1]):
                    if day > today + timedelta(days=90):
                        continue
                    when = delivery_time(day, values)
                    key = digest([rule.id, lot.id, generation, threshold, when])
                    occurrence = existing.get(key)
                    if occurrence is None:
                        occurrence = Occurrence(
                            workspace_id=workspace_id,
                            rule_id=rule.id,
                            subject_lot_id=lot.id,
                            generation=generation,
                            threshold_key=threshold,
                            occurrence_time=when,
                            dedupe_key=key,
                        )
                        db.add(occurrence)
                        existing[key] = occurrence
                    if aware(occurrence.occurrence_time) <= now and occurrence.status not in {
                        "delivered",
                        "cancelled",
                        "suppressed",
                    }:
                        due.append(occurrence)
                # После простоя доставляем один актуальный порог на субъект, остальные подавляем.
                if due:
                    newest = due[-1]
                    for old in due[:-1]:
                        old.status = "suppressed"
                    equivalent_delivered = any(
                        o.rule_id == rule.id
                        and o.subject_lot_id == lot.id
                        and o.status == "delivered"
                        and o.threshold_key == newest.threshold_key
                        and aware(o.occurrence_time).astimezone(zone).date()
                        == aware(newest.occurrence_time).astimezone(zone).date()
                        for o in occurrences
                    )
                    if equivalent_delivered:
                        newest.status = "suppressed"
                        continue
                    group = (
                        item.primary_category
                        if values.group_mode == "by_category"
                        else lot.id
                        if values.group_mode == "none"
                        else "day"
                    )
                    due_groups[(rule.id, group, today)].append((newest, lot, item, available, values))
        for occurrence in occurrences:
            if (
                occurrence.status in {"planned", "queued"}
                and valid_generations.get((occurrence.rule_id, occurrence.subject_lot_id))
                != occurrence.generation
            ):
                occurrence.status = "cancelled"
        by_rule = {r.id: r for r in rules}
        for (rule_id, group, today), entries in due_groups.items():
            key = digest([rule_id, group, today, sorted(e[0].dedupe_key for e in entries)])
            present = await db.scalar(select(Notification).where(Notification.dedupe_key == key))
            if not present:
                subjects, lines = [], []
                for occurrence, lot, item, _, _values in entries:
                    expired = lot.effective_expiry_on < today
                    unknown = any(b.quantity_state == "unknown" for b in balances if b.lot_id == lot.id)
                    line = f"{item.name}: {'срок истёк' if expired else 'годен до'} {lot.effective_expiry_on.isoformat()}"
                    if unknown:
                        line += "; наличие не подтверждено"
                    lines.append(line)
                    subjects.append(
                        {
                            "lot_id": lot.id,
                            "item_id": item.id,
                            "expiry_on": lot.effective_expiry_on.isoformat(),
                            "generation": occurrence.generation,
                        }
                    )
                db.add(
                    Notification(
                        workspace_id=workspace_id,
                        user_id=by_rule[rule_id].owner_user_id,
                        dedupe_key=key,
                        title="Проверьте сроки",
                        body="\n".join(lines),
                        subjects=subjects,
                    )
                )
            for occurrence, *_ in entries:
                occurrence.status = "delivered"


async def plan_all(factory):
    async with factory() as db:
        workspace_ids = (await db.scalars(select(Workspace.id))).all()
    for workspace_id in workspace_ids:
        await plan_workspace(factory, workspace_id)
