from dataclasses import dataclass

from fastapi import Depends, Header, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.application.auth import authenticate
from app.application.proposals import PersistedConflict
from app.db.models import User
from app.db.session import workspace_access
from app.domain.errors import require

bearer = HTTPBearer(auto_error=False)


async def database(request: Request):
    async with request.app.state.session_factory() as db:
        try:
            yield db
            await db.commit()
        except PersistedConflict:
            await db.commit()
            raise
        except BaseException:
            await db.rollback()
            raise


async def current_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db=Depends(database)
):
    require(credentials, "AUTH_REQUIRED", "Требуется вход.", 401)
    return await authenticate(db, credentials.credentials)


async def current_user(auth=Depends(current_auth)):
    return auth[0]


async def admin_user(user=Depends(current_user)):
    require(user.app_role == "admin", "FORBIDDEN", "Требуются права администратора.", 403)
    return user


@dataclass
class Scope:
    user: User
    workspace_id: str


async def scope(
    workspace_id: str | None = Query(None),
    x_workspace_id: str | None = Header(None),
    user=Depends(current_user),
    db=Depends(database),
):
    selected = x_workspace_id or workspace_id
    require(selected, "WORKSPACE_REQUIRED", "Передайте X-Workspace-ID или workspace_id.", 400)
    require(
        not workspace_id or not x_workspace_id or workspace_id == x_workspace_id,
        "WORKSPACE_MISMATCH",
        "Рабочие области запроса не совпадают.",
        400,
    )
    await workspace_access(db, selected, user.id)
    return Scope(user, selected)


async def write_scope(selected=Depends(scope), db=Depends(database)):
    await workspace_access(db, selected.workspace_id, selected.user.id, write=True, lock=True)
    return selected


def idempotency_key(idempotency_key: str = Header(..., min_length=1, max_length=200)):
    return idempotency_key
