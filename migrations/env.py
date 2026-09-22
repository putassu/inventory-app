import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_config
from app.db.models import Base


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name == "inventory"
    return True


def migrate(connection):
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        include_schemas=True,
        include_name=include_name,
        version_table_schema="inventory",
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def online():
    engine = create_async_engine(get_config().database_url, poolclass=pool.NullPool)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS inventory")
    async with engine.begin() as connection:
        await connection.exec_driver_sql("SET search_path TO public")
        connection.dialect.default_schema_name = "public"
        await connection.run_sync(migrate)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=get_config().database_url,
        target_metadata=Base.metadata,
        literal_binds=True,
        include_schemas=True,
        version_table_schema="inventory",
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online())
