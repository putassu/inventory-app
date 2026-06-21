import uuid
import datetime
from typing import Generator
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.db.database import AsyncSessionLocal
from backend.app.db.models import User, UserTier
from backend.app.core.security import decode_access_token

# Bearer token security schema
security_scheme = HTTPBearer(auto_error=False)


async def get_db_session() -> Generator[AsyncSession, None, None]:
    """FastAPI Dependency providing a clean transactional async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db_session)
) -> User:
    """
    FastAPI Dependency to authenticate requests.
    Decodes the Bearer token, validates claims, and injects the current active User entity.
    Raises 401 Unauthorized for invalid/expired tokens, and 403 Forbidden for inactive users.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if not credentials:
        raise credentials_exception
        
    token = credentials.credentials
    payload = decode_access_token(token)
    if not payload:
        raise credentials_exception
        
    user_id_str: str = payload.get("sub")
    if not user_id_str:
        raise credentials_exception
        
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise credentials_exception
        
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        raise credentials_exception
        
    # Lazy subscription and key expiration checks
    now = datetime.datetime.now(datetime.timezone.utc)
    downgraded = False
    
    if user.tier != UserTier.FREE and user.tier_expired_at is not None:
        if user.tier_expired_at < now:
            user.tier = UserTier.FREE
            user.litellm_api_key = f"sk-litellm-free-{uuid.uuid4().hex[:8]}"
            user.tier_expired_at = None
            user.litellm_key_expired_at = None
            downgraded = True
            
    if not downgraded and user.litellm_key_expired_at is not None:
        if user.litellm_key_expired_at < now:
            user.litellm_api_key = f"sk-litellm-free-{uuid.uuid4().hex[:8]}"
            user.litellm_key_expired_at = None
            downgraded = True
            
    if downgraded:
        user.updated_at = now
        await db.commit()
        await db.refresh(user)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account"
        )
        
    return user

async def get_current_admin_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Dependency for admin-only endpoints."""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires administrative privileges"
        )
    return current_user
