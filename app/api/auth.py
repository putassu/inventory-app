from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field
from sqlalchemy import select, update

from app.api.deps import current_auth, current_user, database, idempotency_key
from app.application import auth
from app.application.idempotency import previous_response, remember
from app.config import get_config
from app.db.models import Agreement, Membership, Session, User, Workspace
from app.domain.common import utcnow
from app.domain.errors import DomainError, require
from app.domain.schemas import StrictModel

router = APIRouter()


class Login(StrictModel):
    login: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=1024)
    client_type: Literal["web", "native"] = "native"


class Refresh(StrictModel):
    refresh_token: str | None = None
    client_type: Literal["web", "native"] = "native"


def csrf_check(request):
    require(
        request.headers.get("origin") in get_config().cors_origins,
        "FORBIDDEN",
        "Источник браузерного запроса не разрешён.",
        403,
    )


def token_response(request, response, result, client_type):
    if client_type == "web":
        csrf_check(request)
        config = get_config()
        response.set_cookie(
            "inventory_refresh",
            result.pop("refresh_token"),
            httponly=True,
            secure=config.cookie_secure,
            samesite="strict",
            path="/api/v1/auth",
            max_age=config.refresh_days * 86400,
        )
    return result


@router.post("/auth/login")
async def login(data: Login, request: Request, response: Response, db=Depends(database)):
    if data.client_type == "web":
        csrf_check(request)
    result = await auth.login(
        db, data.login, data.password, request.client.host if request.client else "unknown"
    )
    return token_response(request, response, result, data.client_type)


@router.post("/auth/refresh")
async def refresh(data: Refresh, request: Request, response: Response, db=Depends(database)):
    cookie = request.cookies.get("inventory_refresh")
    if cookie or data.client_type == "web":
        csrf_check(request)
    token = cookie if data.client_type == "web" else data.refresh_token
    require(token, "SESSION_EXPIRED", "Отсутствует токен сессии.", 401)
    return token_response(request, response, await auth.refresh(db, token), data.client_type)


@router.post("/auth/logout")
async def logout(
    request: Request, response: Response, authentication=Depends(current_auth), db=Depends(database)
):
    if request.cookies.get("inventory_refresh"):
        csrf_check(request)
    authentication[1].revoked_at = utcnow()
    response.delete_cookie("inventory_refresh", path="/api/v1/auth")
    return {"status": "ok"}


@router.post("/auth/logout-all")
async def logout_all(user=Depends(current_user), db=Depends(database)):
    locked = await db.get(User, user.id, with_for_update=True)
    locked.auth_version += 1
    await db.execute(update(Session).where(Session.user_id == user.id).values(revoked_at=utcnow()))
    return {"status": "ok"}


@router.get("/workspaces")
async def workspaces(user=Depends(current_user), db=Depends(database)):
    rows = (
        await db.scalars(
            select(Workspace)
            .join(Membership, Membership.workspace_id == Workspace.id)
            .where(Membership.user_id == user.id, Membership.status == "active")
            .order_by(Workspace.id)
        )
    ).all()
    return {
        "items": [{"id": r.id, "name": r.name, "version": r.version} for r in rows],
        "has_more": False,
        "next_cursor": None,
    }


@router.get("/me")
async def me(user=Depends(current_user), db=Depends(database)):
    agreements = (await db.scalars(select(Agreement).where(Agreement.user_id == user.id))).all()
    return {
        "id": user.id,
        "login": user.login,
        "app_role": user.app_role,
        "locale": user.locale,
        "timezone": user.timezone,
        "version": user.version,
        "workspaces": (await workspaces(user, db))["items"],
        "agreements": [{"type": a.agreement_type, "version": a.agreement_version} for a in agreements],
    }


class ProfileUpdate(StrictModel):
    expected_version: int = Field(ge=1)
    locale: Literal["ru", "en"] | None = None
    timezone: str | None = None


@router.patch("/me")
async def update_me(data: ProfileUpdate, user=Depends(current_user), db=Depends(database)):
    user = await db.get(User, user.id, with_for_update=True, populate_existing=True)
    require(user.version == data.expected_version, "VERSION_CONFLICT", "Профиль уже изменился.")
    if data.timezone:
        try:
            ZoneInfo(data.timezone)
        except ZoneInfoNotFoundError as exc:
            raise DomainError("INVALID_TIMEZONE", "Неизвестный часовой пояс.", 422) from exc
        user.timezone = data.timezone
    if data.locale:
        user.locale = data.locale
    user.version += 1
    return await me(user, db)


class AgreementInput(StrictModel):
    agreement_type: Literal["trusted_server"]
    version: Literal["1"]


@router.post("/me/agreements")
async def agreement(
    data: AgreementInput, key=Depends(idempotency_key), user=Depends(current_user), db=Depends(database)
):
    await db.get(User, user.id, with_for_update=True)
    body = data.model_dump()
    cached = await previous_response(db, user.id, "profile", "agreement", key, body)
    if cached:
        return cached
    existing = await db.scalar(
        select(Agreement).where(
            Agreement.user_id == user.id,
            Agreement.agreement_type == data.agreement_type,
            Agreement.agreement_version == data.version,
        )
    )
    if not existing:
        db.add(Agreement(user_id=user.id, agreement_type=data.agreement_type, agreement_version=data.version))
    return remember(db, user.id, "profile", "agreement", key, body, {"status": "accepted"})
