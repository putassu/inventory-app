from fastapi import APIRouter, Depends
from pydantic import Field

from app.api.deps import db_session, idempotency_key, scope, write_scope
from app.application.idempotency import previous_response, remember
from app.db.models import Audit, Workspace
from app.domain.errors import require
from app.domain.item_fields import OPTIONAL_FIELDS, ItemFields, validate_profile

router = APIRouter()


def view(workspace):
    return {
        "version": workspace.item_fields_version,
        **ItemFields.model_validate(workspace.item_fields).model_dump(),
        "builtin_fields": [{"key": key, "label": label} for key, label in OPTIONAL_FIELDS.items()],
    }


@router.get("/item-fields")
async def get_fields(selected=Depends(scope), db=db_session):
    return view(await db.get(Workspace, selected.workspace_id))


class FieldsUpdate(ItemFields):
    expected_version: int = Field(ge=1)


@router.patch("/item-fields")
async def save_fields(
    data: FieldsUpdate, selected=Depends(write_scope), key=Depends(idempotency_key), db=db_session
):
    body = data.model_dump(mode="json")
    cached = await previous_response(db, selected.user.id, selected.workspace_id, "item_fields", key, body)
    if cached:
        return cached
    workspace = await db.get(Workspace, selected.workspace_id, with_for_update=True)
    require(
        workspace.item_fields_version == data.expected_version,
        "VERSION_CONFLICT",
        "Настройки полей изменились. Обновите их перед сохранением.",
    )
    profile = data.model_dump(exclude={"expected_version"}, mode="json")
    validate_profile(profile, workspace.item_fields)
    workspace.item_fields = profile
    workspace.item_fields_version += 1
    db.add(
        Audit(
            actor_id=selected.user.id,
            action="item_fields.updated",
            details={"workspace_id": workspace.id, "version": workspace.item_fields_version},
        )
    )
    return remember(db, selected.user.id, selected.workspace_id, "item_fields", key, body, view(workspace))
