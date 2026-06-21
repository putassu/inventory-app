import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.schemas import LocationCreate, LocationResponse, LocationTreeResponse, LocationUpdateGeneric
from backend.app.db.models import User
from backend.app.api.deps import get_db_session, get_current_user
from backend.app.services.location import (
    create_location,
    get_location_by_id,
    get_locations_tree,
    move_location,
    delete_location,
    update_location_generic
)

router = APIRouter()


@router.get(
    "/locations",
    response_model=List[LocationTreeResponse],
    summary="Get hierarchical tree of storage locations",
    description="Returns all storage locations for the authenticated user formatted as a hierarchical tree.",
    responses={
        401: {"description": "Could not validate credentials."}
    }
)
async def list_locations_tree(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """Retrieve the nested tree of locations (root and sublocations) for the current active user."""
    roots = await get_locations_tree(db, current_user.id)
    return roots


@router.post(
    "/locations",
    response_model=LocationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new storage location",
    description="Creates a new location. If parent_location_id is supplied, nests it under that location.",
    responses={
        400: {"description": "Parent location validation failed or cyclic dependency."},
        401: {"description": "Could not validate credentials."}
    }
)
async def add_location(
    data: LocationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Create a storage location.
    
    - **name**: Name of the storage box/shelf/room
    - **parent_location_id**: Optional parent storage box ID
    - **description**: Optional text detail
    """
    try:
        location = await create_location(db, current_user.id, data)
        return location
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.put(
    "/locations/{location_id}",
    response_model=LocationResponse,
    summary="Update storage location",
    description="Updates a location's name, description, and custom attributes.",
    responses={
        401: {"description": "Could not validate credentials."},
        404: {"description": "Location not found or access denied."}
    }
)
async def modify_location(
    location_id: uuid.UUID,
    data: LocationUpdateGeneric,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Update location metadata.
    
    - **name**: Updated name
    - **description**: Updated description
    - **attributes**: Updated JSON attributes (will be merged with existing)
    """
    location = await update_location_generic(db, location_id, current_user.id, data)
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location not found"
        )
    return location


@router.put(
    "/locations/{location_id}/move",
    response_model=LocationResponse,
    summary="Reparent a storage location (container moving)",
    description="Changes the parent of a location. Validates that the new parent exists and does not form a loop.",
    responses={
        400: {"description": "Invalid move operation or cyclic dependency detected."},
        401: {"description": "Could not validate credentials."},
        404: {"description": "Location to move not found."}
    }
)
async def relocate_container(
    location_id: uuid.UUID,
    parent_location_id: Optional[uuid.UUID] = Query(None, description="New parent location UUID (null for root)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Move a storage container under a different parent location.
    
    - **location_id**: UUID of the container being moved
    - **parent_location_id**: UUID of the target parent container (or None to move to root level)
    """
    try:
        location = await move_location(db, location_id, current_user.id, parent_location_id)
        if not location:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Location not found"
            )
        return location
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.delete(
    "/locations/{location_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a storage location",
    description="Deletes a location. Supports recursive cascade delete or safe promotion/migration of child sublocations and items.",
    responses={
        400: {"description": "Invalid deletion settings or circular target reference."},
        401: {"description": "Could not validate credentials."},
        404: {"description": "Location to delete not found."}
    }
)
async def remove_location(
    location_id: uuid.UUID,
    cascade: bool = Query(False, description="If true, cascade delete all child locations. Else, promotes them."),
    move_to: Optional[uuid.UUID] = Query(None, description="Optional target location to migrate items to"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Delete a storage location.
    
    - **location_id**: Location to delete
    - **cascade**: True to recursively delete sub-boxes. False to promote sub-boxes up.
    - **move_to**: Optional UUID of target box to automatically migrate items into.
    """
    try:
        success = await delete_location(db, location_id, current_user.id, cascade=cascade, move_to=move_to)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Location not found"
            )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

from fastapi import UploadFile, File
from backend.app.services.s3 import upload_file_to_s3
from backend.app.db.models import LocationPhoto, Location
import shutil
from pathlib import Path

TEMP_DIR = Path("data/tmp")
TEMP_DIR.mkdir(parents=True, exist_ok=True)

@router.post(
    "/locations/{location_id}/media",
    response_model=LocationResponse,
    summary="Upload media for a location",
    description="Directly uploads photos or audio for a location without triggering ML processing."
)
async def upload_location_media(
    location_id: uuid.UUID,
    photos: list[UploadFile] = File(None),
    audio: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    from sqlalchemy import select
    
    # Check if location exists
    stmt = select(Location).where(Location.id == location_id, Location.user_id == current_user.id)
    res = await db.execute(stmt)
    location = res.scalar_one_or_none()
    if not location:
        raise HTTPException(status_code=404, detail="Location not found")
        
    user_id_str = str(current_user.id)
    temp_session_path = TEMP_DIR / str(uuid.uuid4())
    temp_session_path.mkdir(parents=True, exist_ok=True)
    
    try:
        if photos:
            for i, photo in enumerate(photos):
                ext = photo.filename.split(".")[-1] if photo.filename and "." in photo.filename else "jpg"
                p_path = temp_session_path / f"loc_photo_{i}.{ext}"
                with open(p_path, "wb") as buffer:
                    shutil.copyfileobj(photo.file, buffer)
                
                s3_key = f"users/{user_id_str}/locations/{location_id}/photo_{uuid.uuid4().hex[:8]}.{ext}"
                url = upload_file_to_s3(p_path, s3_key)
                
                # Create LocationPhoto
                lp = LocationPhoto(location_id=location_id, original_url=url)
                db.add(lp)
                
        if audio:
            ext = audio.filename.split(".")[-1] if audio.filename and "." in audio.filename else "wav"
            a_path = temp_session_path / f"loc_audio.{ext}"
            with open(a_path, "wb") as buffer:
                shutil.copyfileobj(audio.file, buffer)
                
            s3_key = f"users/{user_id_str}/locations/{location_id}/audio_{uuid.uuid4().hex[:8]}.{ext}"
            url = upload_file_to_s3(a_path, s3_key)
            location.audio_url = url
            
        await db.commit()
        await db.refresh(location)
        # Fetch the location again to get the relationships loaded
        stmt = select(Location).where(Location.id == location_id)
        res = await db.execute(stmt)
        location = res.scalar_one()
        return location
        
    finally:
        try:
            shutil.rmtree(temp_session_path)
        except Exception:
            pass
