import datetime
import uuid
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.db.models import Location, Item
from backend.app.schemas import LocationCreate, LocationUpdateGeneric, LocationUpdate


async def get_location_by_id(
    db: AsyncSession,
    location_id: uuid.UUID,
    user_id: uuid.UUID
) -> Optional[Location]:
    """Retrieve a single location by ID and user_id, eagerly loading its photos."""
    stmt = (
        select(Location)
        .where(Location.id == location_id, Location.user_id == user_id)
        .options(selectinload(Location.photos))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_locations_tree(
    db: AsyncSession,
    user_id: uuid.UUID
) -> List[Location]:
    """Retrieve all locations for a user, eagerly loading photos and child locations, and return the root nodes of the hierarchy."""
    stmt = (
        select(Location)
        .where(Location.user_id == user_id)
        .options(
            selectinload(Location.photos),
            selectinload(Location.child_locations).selectinload(Location.child_locations)
        )
    )
    result = await db.execute(stmt)
    all_locs = list(result.scalars().all())

    # Build relationship hierarchy in-memory using SQLAlchemy identity map
    roots = [loc for loc in all_locs if loc.parent_location_id is None]
    return roots


async def create_location(
    db: AsyncSession,
    user_id: uuid.UUID,
    data: LocationCreate
) -> Location:
    """Create a new location for the user. If parent_location_id is set, validates it first."""
    if data.parent_location_id:
        parent = await get_location_by_id(db, data.parent_location_id, user_id)
        if not parent:
            raise ValueError("Parent location not found or access denied")

    location = Location(
        user_id=user_id,
        parent_location_id=data.parent_location_id,
        name=data.name,
        description=data.description
    )
    db.add(location)
    await db.commit()
    return await get_location_by_id(db, location.id, user_id)


async def move_location(
    db: AsyncSession,
    location_id: uuid.UUID,
    user_id: uuid.UUID,
    parent_location_id: Optional[uuid.UUID]
) -> Optional[Location]:
    """Change parent_location_id of a location. Prevents cycles and invalid references."""
    location = await get_location_by_id(db, location_id, user_id)
    if not location:
        return None

    if parent_location_id:
        # Prevent self-nesting
        if parent_location_id == location_id:
            raise ValueError("Cannot move a location into itself")

        # Load all locations to check for cycles
        stmt = select(Location).where(Location.user_id == user_id)
        res = await db.execute(stmt)
        all_locs = {l.id: l for l in res.scalars().all()}

        # Verify parent exists
        if parent_location_id not in all_locs:
            raise ValueError("Parent location not found or access denied")

        # Traverse upwards from proposed parent to verify no cycle with location_id
        curr = parent_location_id
        while curr is not None:
            if curr == location_id:
                raise ValueError("Cannot move a location into its own sublocation (descendant)")
            parent_loc = all_locs.get(curr)
            curr = parent_loc.parent_location_id if parent_loc else None

    location.parent_location_id = parent_location_id
    location.updated_at = datetime.datetime.now(datetime.timezone.utc)
    await db.commit()
    return await get_location_by_id(db, location.id, user_id)


async def delete_location(
    db: AsyncSession,
    location_id: uuid.UUID,
    user_id: uuid.UUID,
    cascade: bool = False,
    move_to: Optional[uuid.UUID] = None
) -> bool:
    """
    Delete a storage location.
    
    If cascade is True:
        Deletes the location and its sublocations cascade-wise (DB Level).
        If move_to is specified, all items inside this location and its sublocations are moved first.
        Otherwise, items location_id falls back to NULL.
        
    If cascade is False:
        Child locations are promoted to the deleted location's parent.
        Items inside are moved to move_to (if specified) or to the deleted location's parent.
    """
    location = await get_location_by_id(db, location_id, user_id)
    if not location:
        return False

    if move_to:
        if move_to == location_id:
            raise ValueError("Cannot move items to the location being deleted")
        target = await get_location_by_id(db, move_to, user_id)
        if not target:
            raise ValueError("Target move_to location not found or access denied")

    if not cascade:
        # Promote child locations to this location's parent
        stmt_loc = (
            update(Location)
            .where(Location.parent_location_id == location_id)
            .values(
                parent_location_id=location.parent_location_id,
                updated_at=datetime.datetime.now(datetime.timezone.utc)
            )
        )
        await db.execute(stmt_loc)

        # Move items in the deleted location to move_to or to the deleted location's parent
        target_location_id = move_to if move_to else location.parent_location_id
        stmt_items = (
            update(Item)
            .where(Item.location_id == location_id)
            .values(
                location_id=target_location_id,
                updated_at=datetime.datetime.now(datetime.timezone.utc)
            )
        )
        await db.execute(stmt_items)
    else:
        # Cascade deletion: we need to handle moving items for this location AND all its descendants
        if move_to:
            # Retrieve all locations to build the descendant tree in-memory
            stmt = select(Location).where(Location.user_id == user_id)
            res = await db.execute(stmt)
            all_locs = {l.id: l for l in res.scalars().all()}

            descendants = {location_id}
            added = True
            while added:
                added = False
                for loc_id, loc in all_locs.items():
                    if loc.parent_location_id in descendants and loc_id not in descendants:
                        descendants.add(loc_id)
                        added = True

            stmt_items = (
                update(Item)
                .where(Item.location_id.in_(descendants))
                .values(
                    location_id=move_to,
                    updated_at=datetime.datetime.now(datetime.timezone.utc)
                )
            )
            await db.execute(stmt_items)

    await db.delete(location)
    await db.commit()
    return True

async def update_location_generic(db: AsyncSession, location_id: uuid.UUID, user_id: uuid.UUID, update_data: LocationUpdateGeneric) -> Optional[Location]:
    location = await get_location_by_id(db, location_id, user_id)
    if not location:
        return None
        
    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        if key == "attributes":
            # merge dictionaries to ensure sqlalchemy tracks jsonb
            old_attrs = location.attributes or {}
            new_attrs = old_attrs.copy()
            new_attrs.update(value)
            location.attributes = new_attrs
        else:
            setattr(location, key, value)
            
    db.add(location)
    await db.commit()
    await db.refresh(location)
    return location


async def bulk_move_locations(
    db: AsyncSession,
    location_ids: List[uuid.UUID],
    user_id: uuid.UUID,
    parent_location_id: Optional[uuid.UUID]
) -> int:
    """Move multiple locations to a new parent location in a single operation, preventing cyclic references."""
    if not location_ids:
        return 0

    # Verify target parent exists and belongs to the user
    if parent_location_id:
        parent = await get_location_by_id(db, parent_location_id, user_id)
        if not parent:
            raise ValueError("Parent location not found or access denied")

        # Prevent moving a location to be nested under itself
        if parent_location_id in location_ids:
            raise ValueError("Cannot move a location into itself")

        # Cycle checks: fetch all locations to verify parent is not a descendant of any moved location
        stmt = select(Location).where(Location.user_id == user_id)
        res = await db.execute(stmt)
        all_locs = {l.id: l for l in res.scalars().all()}

        curr = parent_location_id
        while curr is not None:
            if curr in location_ids:
                raise ValueError("Cannot move a location into its own sublocation (descendant)")
            parent_loc = all_locs.get(curr)
            curr = parent_loc.parent_location_id if parent_loc else None

    stmt = (
        update(Location)
        .where(Location.id.in_(location_ids), Location.user_id == user_id)
        .values(
            parent_location_id=parent_location_id,
            updated_at=datetime.datetime.now(datetime.timezone.utc)
        )
    )
    res = await db.execute(stmt)
    await db.commit()
    return res.rowcount
