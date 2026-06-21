import os
from pathlib import Path
from dotenv import load_dotenv

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Load environment variables
BASE_DIR = Path(__file__).parent.parent.parent.parent.resolve()
load_dotenv(BASE_DIR / ".env")


def get_db_url() -> str:
    """
    Resolve the database connection URL dynamically.
    For host executions (like running pytest locally), it uses port 5433.
    Inside Docker, it uses the service name 'postgres' and port 5432.
    """
    # Allow explicit override via POSTGRES_DSN
    dsn = os.getenv("POSTGRES_DSN")
    if dsn:
        if dsn.startswith("postgresql://"):
            dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
        return dsn

    # Build DSN based on loaded environment settings
    user = os.getenv("POSTGRES_USER", "inventory_user")
    password = os.getenv("POSTGRES_PASSWORD", "")
    db_name = os.getenv("POSTGRES_DB", "inventory_db")

    # Simple heuristic to check if running inside a Docker container
    is_docker = os.path.exists("/.dockerenv") or os.getenv("RUNNING_IN_DOCKER") == "true"
    host = "postgres" if is_docker else "127.0.0.1"
    port = "5432" if is_docker else "5433"

    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db_name}"


import sys
from sqlalchemy.pool import NullPool

# Create async SQLAlchemy engine and session maker
DATABASE_URL = get_db_url()

# If running pytest, use NullPool to avoid async event loop connection sharing conflicts on Windows
is_testing = "pytest" in sys.modules or os.getenv("TESTING") == "true"

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    poolclass=NullPool if is_testing else None
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def get_db():
    """Dependency generator to yield async database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
