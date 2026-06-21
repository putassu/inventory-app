import uuid
import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.schemas import UserCreate, UserResponse, Token, UserSettingsUpdate, UserSettings
from backend.app.db.models import User, UserTier
from backend.app.api.deps import get_db_session, get_current_user
from backend.app.core.security import get_password_hash, verify_password, create_access_token

router = APIRouter()


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
    description="Registers a new user, hashes the password, and assigns the default FREE tier and LiteLLM api key.",
    responses={
        400: {
            "description": "Email already registered or validation error.",
            "content": {"application/json": {"example": {"detail": "Email already registered"}}}
        }
    }
)
async def register(
    data: UserCreate,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Register a new user account with default FREE tier and custom LiteLLM API key.
    
    - **email**: Unique email address
    - **password**: Clear-text password (min 8 characters)
    """
    hashed = get_password_hash(data.password)
    # Generate a dummy litellm key for this user representing their quota key
    litellm_key = f"sk-litellm-free-{uuid.uuid4().hex[:8]}"
    
    user = User(
        email=data.email,
        hashed_password=hashed,
        tier=UserTier.FREE,
        litellm_user_key=litellm_key,
        is_active=True
    )
    
    db.add(user)
    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
        
    return user


@router.post(
    "/login",
    response_model=Token,
    summary="Login and receive access token",
    description="Authenticates the user using email and password, and returns a JWT access token containing subscription tier and LiteLLM key.",
    responses={
        400: {
            "description": "Incorrect email or password.",
            "content": {"application/json": {"example": {"detail": "Incorrect email or password"}}}
        }
    }
)
async def login(
    data: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Authenticate user and generate access token.
    
    - **email**: Registered email address
    - **password**: User password
    """
    stmt = select(User).where(User.email == data.email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect email or password"
        )
        
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is deactivated"
        )
        
    # Update last login details
    user.last_login_ip = request.client.host if request.client else None
    user.last_login_dt = datetime.datetime.now(datetime.timezone.utc)
    user.updated_at = datetime.datetime.now(datetime.timezone.utc)
    
    await db.commit()
    await db.refresh(user)
        
    token = create_access_token(
        subject=user.id,
        tier=user.tier.value,
        litellm_user_key=user.litellm_user_key
    )
    
    return {"access_token": token, "token_type": "bearer"}


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user",
    description="Retrieves the current authenticated user's profile."
)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get(
    "/me/settings",
    response_model=UserSettings,
    summary="Get current user settings",
    description="Retrieves the current user's preferences, including audit and expiration settings."
)
async def get_settings(
    current_user: User = Depends(get_current_user)
):
    # Ensure all defaults are returned by parsing through the Pydantic schema
    return UserSettings(**current_user.settings)


@router.put(
    "/me/settings",
    response_model=UserSettings,
    summary="Update user settings",
    description="Update preferences including audit reminder days and LLM flags."
)
async def update_settings(
    data: UserSettingsUpdate,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    update_data = data.model_dump(exclude_unset=True)
    if update_data:
        # Create a new dictionary to trigger SQLAlchemy JSONB mutation tracking
        new_settings = dict(current_user.settings)
        new_settings.update(update_data)
        current_user.settings = new_settings
        
        current_user.updated_at = datetime.datetime.now(datetime.timezone.utc)
        await db.commit()
        await db.refresh(current_user)
        
    return UserSettings(**current_user.settings)

