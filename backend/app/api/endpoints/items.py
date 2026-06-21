import uuid
from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.schemas import ItemCreate, ItemUpdate, ItemResponse, ItemUpdateGeneric
from backend.app.db.models import User
from backend.app.api.deps import get_db_session, get_current_user
from backend.app.services.item import (
    create_item,
    get_item_by_id,
    list_items,
    update_item_generic,
    adjust_item_quantity,
    move_item,
    soft_delete_item
)

router = APIRouter()


@router.get(
    "/items",
    response_model=List[ItemResponse],
    summary="List inventory items",
    description="Lists all active (unarchived) items for the user, with optional filtering by location_id.",
    responses={
        401: {"description": "Could not validate credentials."}
    }
)
async def list_user_items(
    location_id: Optional[uuid.UUID] = Query(None, description="Filter items by location UUID"),
    include_archived: bool = Query(False, description="Include soft deleted items in output"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """Retrieve items belonging to the current user with optional location filtering."""
    items = await list_items(db, current_user.id, location_id=location_id, include_archived=include_archived)
    return items


@router.get(
    "/items/{item_id}",
    response_model=ItemResponse,
    summary="Get item details",
    description="Returns detailed information of a single item, including its associated media attachments.",
    responses={
        401: {"description": "Could not validate credentials."},
        404: {"description": "Item not found or access denied."}
    }
)
async def get_item_details(
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """Retrieve detailed metadata of an item by ID."""
    item = await get_item_by_id(db, item_id, current_user.id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found"
        )
    return item


@router.post(
    "/items",
    response_model=ItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new item manually",
    description="Manually creates a new item in the database with custom categories, tags, attributes, and location.",
    responses={
        400: {"description": "Invalid storage location or validation error."},
        401: {"description": "Could not validate credentials."}
    }
)
async def add_item(
    data: ItemCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Manually create a new inventory item.
    
    - **location_id**: Optional storage box ID
    - **quantity**: Countable quantity
    - **unit_of_measure**: kg, pcs, pack, etc.
    - **tags**: General tag labels
    - **primary_category**: Taxonomy category
    - **attributes**: Category-specific JSON variables
    """
    try:
        item = await create_item(db, current_user.id, data)
        return item
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.put(
    "/items/{item_id}",
    response_model=ItemResponse,
    summary="Update item metadata",
    description="Updates item metadata such as name, categories, tags, and custom attributes.",
    responses={
        401: {"description": "Could not validate credentials."},
        404: {"description": "Item not found or access denied."}
    }
)
async def modify_item(
    item_id: uuid.UUID,
    data: ItemUpdateGeneric,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Update item general information.
    
    - **name**: Updated name
    - **tags**: Updated list of tags
    - **attributes**: Updated JSON attributes (will be merged with existing)
    """
    item = await update_item_generic(db, item_id, current_user.id, data)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found"
        )
    return item


@router.put(
    "/items/{item_id}/adjust",
    response_model=ItemResponse,
    summary="Adjust item quantity",
    description="Adjusts the quantity of an item by adding or subtracting the amount. If quantity drops to <=0, automatically sets status to depleted.",
    responses={
        401: {"description": "Could not validate credentials."},
        404: {"description": "Item not found or access denied."}
    }
)
async def adjust_quantity(
    item_id: uuid.UUID,
    amount: Decimal = Query(..., description="Quantity delta to add (positive) or subtract (negative)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Adjust item quantity.
    
    - **item_id**: Item to adjust
    - **amount**: Positive value to add, negative value to subtract
    """
    item = await adjust_item_quantity(db, item_id, current_user.id, amount)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found"
        )
    return item


@router.put(
    "/items/{item_id}/move",
    response_model=ItemResponse,
    summary="Move item to another location",
    description="Changes the storage location of an item. Validates that the target location exists and belongs to the user.",
    responses={
        400: {"description": "Target location not found or access denied."},
        401: {"description": "Could not validate credentials."},
        404: {"description": "Item not found."}
    }
)
async def relocate_item(
    item_id: uuid.UUID,
    location_id: Optional[uuid.UUID] = Query(None, description="Target location UUID (null for root)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Explicitly move an item to another storage box/shelf.
    
    - **item_id**: Item UUID
    - **location_id**: Target container UUID (or None to move to root)
    """
    try:
        item = await move_item(db, item_id, current_user.id, location_id)
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Item not found"
            )
        return item
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.delete(
    "/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft delete an item (archive)",
    description="Hides an item by setting its archived_at timestamp. Physical cleanup is deferred to the Garbage Collector.",
    responses={
        401: {"description": "Could not validate credentials."},
        404: {"description": "Item not found."}
    }
)
async def remove_item(
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Archive an item (Soft Delete).
    
    - **item_id**: Item UUID to archive
    """
    success = await soft_delete_item(db, item_id, current_user.id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found"
        )
