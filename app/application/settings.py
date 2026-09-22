from copy import deepcopy

from sqlalchemy import select

from app.db.models import Audit, Control, SettingsRevision
from app.domain.errors import require
from app.settings.registry import REGISTRY, defaults, validate_values


async def effective_settings(db):
    row = await db.scalar(
        select(SettingsRevision)
        .where(SettingsRevision.status == "effective")
        .order_by(SettingsRevision.revision.desc())
        .limit(1)
    )
    return (row.revision, defaults() | deepcopy(row.values)) if row else (1, defaults())


async def settings_view(db):
    desired = await db.scalar(select(SettingsRevision).order_by(SettingsRevision.revision.desc()).limit(1))
    revision, values = await effective_settings(db)
    return {
        "desired_revision": desired.revision if desired else revision,
        "effective_revision": revision,
        "status": desired.status if desired else "effective",
        "desired": defaults() | desired.values if desired else values,
        "effective": values,
        "components_pending": desired.components_pending if desired else [],
    }


async def validate_change(db, expected_revision, changes):
    view = await settings_view(db)
    require(
        expected_revision == view["desired_revision"],
        "VERSION_CONFLICT",
        "Настройки уже изменены.",
        current=view,
    )
    require(
        len({c["key"] for c in changes}) == len(changes),
        "INVALID_SETTING",
        "Параметр указан несколько раз.",
        422,
    )
    values = dict(view["desired"])
    for change in changes:
        require(change["key"] in REGISTRY, "UNKNOWN_SETTING", "Неизвестный параметр.", 422)
        values[change["key"]] = change["value"]
    validate_values(values)
    pending = [
        c["key"]
        for c in changes
        if REGISTRY[c["key"]].apply_mode == "requires_restart"
        and values[c["key"]] != view["effective"][c["key"]]
    ]
    retention_reduced = [
        c["key"]
        for c in changes
        if c["key"].startswith("retention.")
        and c["key"] != "retention.gc_interval_hours"
        and c["value"] is not None
        and (view["effective"][c["key"]] is None or c["value"] < view["effective"][c["key"]])
    ]
    return {
        "values": values,
        "components_pending": ["cpu_worker", "ml_worker", "scheduler"] if pending else [],
        "retention_reduced": retention_reduced,
        "changes": changes,
    }


async def apply_settings(db, user_id, expected_revision, changes, reason, impact_confirmed=False):
    control = await db.get(Control, "settings", with_for_update=True)
    require(control is not None, "NOT_INITIALIZED", "Выполните bootstrap.", 503)
    result = await validate_change(db, expected_revision, changes)
    require(
        not result["retention_reduced"] or impact_confirmed,
        "POLICY_IMPACT_REQUIRED",
        "Подтвердите последствия сокращения хранения.",
        impact=result["retention_reduced"],
    )
    row = SettingsRevision(
        revision=expected_revision + 1,
        values=result["values"],
        actor_id=user_id,
        reason=reason,
        previous_revision=expected_revision,
        components_pending=result["components_pending"],
        status="pending_restart" if result["components_pending"] else "effective",
    )
    db.add(row)
    db.add(
        Audit(
            actor_id=user_id,
            action="settings.apply",
            reason=reason,
            details={"revision": row.revision, "changes": changes},
        )
    )
    # Запрет передачи вовне действует даже для набора, ожидающего перезапуска.
    if any(c["key"] == "routing.external_enabled" and c["value"] is False for c in changes):
        control.value = {**control.value, "external_blocked": True}
    elif not result["components_pending"] and result["values"]["routing.external_enabled"]:
        control.value = {**control.value, "external_blocked": False}
    await db.flush()
    return await settings_view(db)


async def acknowledge_restart(db, component):
    await db.get(Control, "settings", with_for_update=True)
    row = await db.scalar(select(SettingsRevision).order_by(SettingsRevision.revision.desc()).limit(1))
    if row and row.status == "pending_restart" and component in row.components_pending:
        row.components_pending = [name for name in row.components_pending if name != component]
        if not row.components_pending:
            row.status = "effective"
