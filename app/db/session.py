from functools import lru_cache

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_config
from app.db.models import Membership, Workspace
from app.domain.errors import require


def make_engine(url: str):
    if url.startswith("sqlite"):
        engine = create_async_engine(url, execution_options={"schema_translate_map": {"inventory": None}})

        @event.listens_for(engine.sync_engine, "connect")
        def configure_sqlite(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    else:
        engine = create_async_engine(url, pool_pre_ping=True, pool_size=4, max_overflow=2)
    return engine


@lru_cache
def session_factory():
    return async_sessionmaker(make_engine(get_config().database_url), expire_on_commit=False)


async def workspace_access(db, workspace_id, user_id, *, write=False, lock=False):
    query = select(Workspace).where(Workspace.id == workspace_id)
    if lock:
        query = query.with_for_update()
    workspace = await db.scalar(query)
    member = await db.get(Membership, (workspace_id, user_id))
    require(
        workspace and member and member.status == "active", "NOT_FOUND", "Рабочая область не найдена.", 404
    )
    require(
        not write or member.role in {"owner", "editor"}, "FORBIDDEN", "Недостаточно прав для изменения.", 403
    )
    return workspace


async def scoped_get(db, model, entity_id, workspace_id, *, lock=False):
    query = select(model).where(model.id == str(entity_id), model.workspace_id == str(workspace_id))
    if lock:
        query = query.with_for_update()
    result = await db.scalar(query)
    require(result is not None, "NOT_FOUND", "Объект не найден.", 404)
    return result
