import datetime
import uuid
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.db.models import Item, ItemStatus
from backend.app.schemas import ItemCreate, ItemUpdate, ItemUpdateGeneric
from backend.app.services.location import get_location_by_id


async def get_item_by_id(
    db: AsyncSession,
    item_id: uuid.UUID,
    user_id: uuid.UUID
) -> Optional[Item]:
    """Retrieve an item by ID, eagerly loading its media."""
    stmt = (
        select(Item)
        .where(Item.id == item_id, Item.user_id == user_id)
        .options(selectinload(Item.media))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_items(
    db: AsyncSession,
    user_id: uuid.UUID,
    location_id: Optional[uuid.UUID] = None,
    include_archived: bool = False
) -> List[Item]:
    """
    List items for a user, eagerly loading media.
    Filters by location_id if provided.
    By default, hides archived items unless include_archived is True.
    """
    stmt = (
        select(Item)
        .where(Item.user_id == user_id)
        .options(selectinload(Item.media))
    )

    if location_id is not None:
        stmt = stmt.where(Item.location_id == location_id)

    if not include_archived:
        stmt = stmt.where(Item.archived_at.is_(None))

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_item(
    db: AsyncSession,
    user_id: uuid.UUID,
    data: ItemCreate
) -> Item:
    """Create a new item. Validates storage location if specified."""
    if data.location_id:
        loc = await get_location_by_id(db, data.location_id, user_id)
        if not loc:
            raise ValueError("Target location not found or access denied")

    item = Item(
        user_id=user_id,
        location_id=data.location_id,
        quantity=data.quantity,
        unit_of_measure=data.unit_of_measure,
        generated_desc=data.generated_desc,
        tags=data.tags or [],
        synonyms=data.synonyms or [],
        primary_category=data.primary_category,
        secondary_categories=data.secondary_categories or [],
        status=data.status,
        attributes=data.attributes or {}
    )
    db.add(item)
    await db.commit()
    return await get_item_by_id(db, item.id, user_id)


async def update_item(
    db: AsyncSession,
    item_id: uuid.UUID,
    user_id: uuid.UUID,
    data: ItemUpdate
) -> Optional[Item]:
    """Update general item attributes. Validates location if location_id is changed."""
    item = await get_item_by_id(db, item_id, user_id)
    if not item:
        return None

    if data.location_id is not None:
        loc = await get_location_by_id(db, data.location_id, user_id)
        if not loc:
            raise ValueError("Target location not found or access denied")
        item.location_id = data.location_id

    # Update simple fields if provided in update payload
    for field in [
        "quantity", "unit_of_measure", "generated_desc", 
        "tags", "synonyms", "primary_category", 
        "secondary_categories", "status", "attributes", "archived_at"
    ]:
        val = getattr(data, field)
        if val is not None:
            setattr(item, field, val)

    item.updated_at = datetime.datetime.now(datetime.timezone.utc)
    await db.commit()
    return await get_item_by_id(db, item.id, user_id)


async def adjust_item_quantity(
    db: AsyncSession,
    item_id: uuid.UUID,
    user_id: uuid.UUID,
    amount: Decimal
) -> Optional[Item]:
    """
    Adjust an item's quantity.
    
    If the new quantity drops to 0 or below:
      - Quantity is set to 0.
      - Status is automatically updated to 'depleted' (Soft Delete criteria for quantity).
    """
    item = await get_item_by_id(db, item_id, user_id)
    if not item:
        return None

    current_qty = item.quantity if item.quantity is not None else Decimal("0.0")
    new_qty = current_qty + amount

    if new_qty <= Decimal("0.0"):
        item.quantity = Decimal("0.0")
        item.status = ItemStatus.DEPLETED
    else:
        item.quantity = new_qty
        # If the item was depleted before, restore status to completed or queued
        if item.status == ItemStatus.DEPLETED:
            item.status = ItemStatus.COMPLETED

    item.updated_at = datetime.datetime.now(datetime.timezone.utc)
    await db.commit()
    return await get_item_by_id(db, item.id, user_id)


async def move_item(
    db: AsyncSession,
    item_id: uuid.UUID,
    user_id: uuid.UUID,
    location_id: Optional[uuid.UUID]
) -> Optional[Item]:
    """Explicitly move an item to another storage location."""
    item = await get_item_by_id(db, item_id, user_id)
    if not item:
        return None

    if location_id is not None:
        loc = await get_location_by_id(db, location_id, user_id)
        if not loc:
            raise ValueError("Target location not found or access denied")

    item.location_id = location_id
    item.updated_at = datetime.datetime.now(datetime.timezone.utc)
    await db.commit()
    return await get_item_by_id(db, item.id, user_id)


async def soft_delete_item(
    db: AsyncSession,
    item_id: uuid.UUID,
    user_id: uuid.UUID
) -> bool:
    """Soft delete an item by setting its archived_at timestamp."""
    item = await get_item_by_id(db, item_id, user_id)
    if not item:
        return False

    item.archived_at = datetime.datetime.now(datetime.timezone.utc)
    item.updated_at = datetime.datetime.now(datetime.timezone.utc)
    await db.commit()
    return True

async def update_item_generic(db: AsyncSession, item_id: uuid.UUID, user_id: uuid.UUID, update_data: ItemUpdateGeneric) -> Optional[Item]:
    item = await get_item_by_id(db, item_id, user_id)
    if not item:
        return None
        
    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        if key == "attributes":
            old_attrs = item.attributes or {}
            new_attrs = old_attrs.copy()
            new_attrs.update(value)
            item.attributes = new_attrs
        else:
            setattr(item, key, value)
            
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def bulk_move_items(
    db: AsyncSession,
    item_ids: List[uuid.UUID],
    user_id: uuid.UUID,
    location_id: Optional[uuid.UUID]
) -> int:
    """Move multiple items to a new location in a single update query."""
    if location_id is not None:
        loc = await get_location_by_id(db, location_id, user_id)
        if not loc:
            raise ValueError("Target location not found or access denied")

    stmt = (
        update(Item)
        .where(Item.id.in_(item_ids), Item.user_id == user_id)
        .values(
            location_id=location_id,
            updated_at=datetime.datetime.now(datetime.timezone.utc)
        )
    )
    res = await db.execute(stmt)
    await db.commit()
    return res.rowcount


async def bulk_soft_delete_items(
    db: AsyncSession,
    item_ids: List[uuid.UUID],
    user_id: uuid.UUID
) -> int:
    """Soft delete multiple items in a single update query."""
    stmt = (
        update(Item)
        .where(Item.id.in_(item_ids), Item.user_id == user_id)
        .values(
            archived_at=datetime.datetime.now(datetime.timezone.utc),
            updated_at=datetime.datetime.now(datetime.timezone.utc)
        )
    )
    res = await db.execute(stmt)
    await db.commit()
    return res.rowcount
