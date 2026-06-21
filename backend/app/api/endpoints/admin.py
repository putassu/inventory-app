import uuid
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.db.models import User, SystemSetting
from backend.app.api.deps import get_db_session, get_current_admin_user
from backend.app.api.deps import get_current_admin_user
from backend.app.services.settings_manager import SettingsManager
from backend.app.schemas import UserResponse, UserUpdateAdmin, SystemSettingResponse, SystemSettingUpdate

router = APIRouter()

# ================================
# Admin User Management
# ================================

@router.get("/users", response_model=List[UserResponse])
async def list_users(
    skip: int = 0,
    limit: int = 100,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db_session)
):
    """List all users in the system."""
    stmt = select(User).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()

@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user_details(
    user_id: uuid.UUID,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db_session)
):
    """Get details of a specific user."""
    stmt = select(User).where(User.id == user_id)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    update_data: UserUpdateAdmin,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db_session)
):
    """Admin update user (tier, active status, etc)."""
    stmt = select(User).where(User.id == user_id)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    if update_data.tier is not None:
        user.tier = update_data.tier
    if update_data.is_active is not None:
        user.is_active = update_data.is_active
    if update_data.is_superuser is not None:
        user.is_superuser = update_data.is_superuser
        
    await db.commit()
    await db.refresh(user)
    return user

# ================================
# Dynamic System Settings
# ================================

@router.get("/settings", response_model=List[SystemSettingResponse])
async def list_settings(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db_session)
):
    """Get all dynamic system settings from DB."""
    stmt = select(SystemSetting)
    settings_list = (await db.execute(stmt)).scalars().all()
    return settings_list

@router.get("/settings/{key}", response_model=SystemSettingResponse)
async def get_setting(
    key: str,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db_session)
):
    """Get a specific system setting."""
    stmt = select(SystemSetting).where(SystemSetting.key == key)
    setting = (await db.execute(stmt)).scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail="Setting not found")
    return setting

@router.put("/settings/{key}", response_model=SystemSettingResponse)
async def override_setting(
    key: str,
    update_data: SystemSettingUpdate,
    admin_user: User = Depends(get_current_admin_user)
):
    """Create or override a dynamic system setting and invalidate cache."""
    try:
        setting = await SettingsManager.set(key, update_data.value, update_data.description)
        return setting
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/settings/{key}")
async def delete_setting(
    key: str,
    admin_user: User = Depends(get_current_admin_user)
):
    """Delete a setting override (will fallback to default config)."""
    try:
        await SettingsManager.delete(key)
        return {"status": "ok", "message": f"Setting {key} deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
