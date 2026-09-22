import asyncio
import hashlib
import secrets
from datetime import UTC, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import select, update

from app.config import get_config
from app.db.models import (
    Agreement,
    Control,
    GPUSlot,
    Location,
    LoginAttempt,
    Membership,
    ModelDeployment,
    Session,
    SettingsRevision,
    User,
    Workspace,
)
from app.domain.common import uid, utcnow
from app.domain.errors import DomainError, require
from app.settings.registry import defaults

PASSWORDS = PasswordHasher(time_cost=3, memory_cost=16384, parallelism=1)
DUMMY_HASH = PASSWORDS.hash("Проверка несуществующего пользователя")


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


async def bootstrap(db, login, password, timezone="Europe/Moscow"):
    require(len(password) >= 12, "WEAK_PASSWORD", "Пароль должен содержать минимум 12 символов.", 422)
    require(not await db.scalar(select(User.id).limit(1)), "ALREADY_INITIALIZED", "Владелец уже создан.")
    user = User(
        id=uid(),
        login=login.casefold(),
        password_hash=await asyncio.to_thread(PASSWORDS.hash, password),
        app_role="admin",
        timezone=timezone,
    )
    db.add(user)
    await db.flush()
    workspace = Workspace(id=uid(), name="Мой инвентарь", owner_user_id=user.id)
    db.add(workspace)
    await db.flush()
    db.add_all(
        [
            Membership(workspace_id=workspace.id, user_id=user.id, role="owner"),
            Location(workspace_id=workspace.id, name="Место не указано", kind="system_unspecified"),
            SettingsRevision(revision=1, values=defaults(), actor_id=user.id, reason="Первичная установка"),
            Agreement(
                user_id=user.id,
                agreement_type="trusted_server",
                agreement_version="1",
                acceptance_context={"source": "bootstrap"},
            ),
            Control(key="settings", value={"external_blocked": True}),
            Control(key="auth", value={}),
            GPUSlot(id=1),
        ]
    )
    config = get_config()
    for name, model, endpoint, trust in [
        ("local_vlm", config.local_model, "ollama", "local"),
        ("privacy_asr", config.local_model, "ollama", "local"),
        ("embeddings", config.embedding_model, "ollama", "local"),
        ("local_audio", config.local_audio_model or "unconfigured", "local_audio", "local"),
        ("cloud_primary", config.cloud_model or "unconfigured", "cloud", "external"),
    ]:
        db.add(
            ModelDeployment(
                logical_name=name,
                actual_model_id=model,
                endpoint_ref=endpoint,
                trust_domain=trust,
                enabled=trust == "local"
                and (name != "local_audio" or config.local_audio_trusted and config.local_audio_verified),
                credential_ref="cloud_key"
                if trust == "external"
                else "local_audio_key"
                if name == "local_audio"
                else None,
            )
        )
    return {"user_id": user.id, "workspace_id": workspace.id}


async def issue_session(db, user, family_id=None):
    config = get_config()
    token = secrets.token_urlsafe(48)
    session = Session(
        id=uid(),
        user_id=user.id,
        family_id=family_id or uid(),
        refresh_token_hash=token_hash(token),
        expires_at=utcnow() + timedelta(days=config.refresh_days),
    )
    db.add(session)
    await db.flush()
    access = jwt.encode(
        {
            "sub": user.id,
            "sid": session.id,
            "ver": user.auth_version,
            "iss": config.jwt_issuer,
            "aud": config.jwt_audience,
            "iat": utcnow(),
            "exp": utcnow() + timedelta(minutes=config.access_minutes),
        },
        config.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    return {
        "access_token": access,
        "refresh_token": token,
        "token_type": "bearer",
        "expires_in": config.access_minutes * 60,
    }


async def login(db, login_name, password, ip):
    await db.get(Control, "auth", with_for_update=True)
    key = token_hash(login_name.casefold() + ":" + ip)
    attempt = await db.get(LoginAttempt, key)
    if not attempt:
        attempt = LoginAttempt(key=key, failures=0, window_start=utcnow())
        db.add(attempt)
    if (utcnow() - aware(attempt.window_start)).total_seconds() > 300:
        attempt.failures, attempt.window_start = 0, utcnow()
    require(
        attempt.failures < 10,
        "USER_RATE_LIMIT",
        "Слишком много попыток входа. Повторите через несколько минут.",
        429,
    )
    user = await db.scalar(select(User).where(User.login == login_name.casefold()))
    try:
        valid = await asyncio.to_thread(
            PASSWORDS.verify, user.password_hash if user else DUMMY_HASH, password
        )
    except VerificationError:
        valid = False
    if not user or not valid or user.status != "active":
        attempt.failures += 1
        await db.commit()
        raise DomainError("AUTH_REQUIRED", "Неверный логин или пароль.", 401)
    attempt.failures = 0
    return await issue_session(db, user)


async def refresh(db, token):
    session = await db.scalar(
        select(Session).where(Session.refresh_token_hash == token_hash(token)).with_for_update()
    )
    require(session is not None, "SESSION_EXPIRED", "Сессия истекла.", 401)
    if session.revoked_at:
        await db.execute(
            update(Session).where(Session.family_id == session.family_id).values(revoked_at=utcnow())
        )
        await db.commit()
        raise DomainError("SESSION_EXPIRED", "Повтор токена: войдите заново.", 401)
    require(aware(session.expires_at) > utcnow(), "SESSION_EXPIRED", "Сессия истекла.", 401)
    user = await db.get(User, session.user_id)
    require(user.status == "active", "SESSION_EXPIRED", "Сессия недоступна.", 401)
    session.revoked_at = utcnow()
    return await issue_session(db, user, session.family_id)


async def authenticate(db, token):
    config = get_config()
    try:
        claims = jwt.decode(
            token,
            config.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=config.jwt_issuer,
            audience=config.jwt_audience,
            options={"require": ["sub", "sid", "ver", "iss", "aud", "exp", "iat"]},
        )
        user = await db.get(User, claims["sub"])
        session = await db.get(Session, claims["sid"])
        require(
            user
            and user.status == "active"
            and session
            and session.user_id == user.id
            and not session.revoked_at
            and aware(session.expires_at) > utcnow()
            and user.auth_version == claims["ver"],
            "SESSION_EXPIRED",
            "Сессия истекла.",
            401,
        )
    except jwt.PyJWTError as exc:
        raise DomainError("AUTH_REQUIRED", "Требуется вход.", 401) from exc
    return user, session
