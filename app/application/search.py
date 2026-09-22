import base64
import json
from datetime import date

from sqlalchemy import func, or_, select

from app.application.inventory import row_state
from app.application.settings import effective_settings
from app.db.models import Alias, Balance, Item, Location, Lot, Workspace
from app.domain.common import digest, jsonable
from app.domain.errors import DomainError, require
from app.domain.rules import aggregate
from app.infrastructure import search as index
from app.infrastructure.gpu import gpu_session
from app.infrastructure.models import LocalAdapter


async def search_document(db, item):
    aliases = (
        await db.scalars(
            select(Alias.alias).where(
                Alias.workspace_id == item.workspace_id, Alias.item_id == item.id, Alias.active.is_(True)
            )
        )
    ).all()
    # Сгенерированное описание не становится подтверждённым признаком поиска.
    return " ".join(
        [
            item.name,
            item.brand or "",
            item.model or "",
            item.barcode or "",
            item.user_description or "",
            *item.tags,
            *aliases,
            json.dumps(item.attributes, ensure_ascii=False, sort_keys=True),
        ]
    )


async def candidates(db, workspace_id, query, limit=8):
    aliases = select(Alias.item_id).where(
        Alias.workspace_id == workspace_id,
        Alias.active.is_(True),
        Alias.normalized_alias.contains(query.casefold(), autoescape=True),
    )
    serials = select(Lot.item_id).where(
        Lot.workspace_id == workspace_id, func.lower(Lot.serial_number) == query.casefold()
    )
    predicates = [
        Item.name.icontains(query, autoescape=True),
        Item.id == query,
        Item.barcode == query,
        func.lower(Item.model) == query.casefold(),
        Item.id.in_(aliases),
        Item.id.in_(serials),
    ]
    if db.bind.dialect.name == "postgresql" and query:
        predicates.append(
            func.to_tsvector("russian", Item.name + " " + func.coalesce(Item.user_description, "")).op("@@")(
                func.plainto_tsquery("russian", query)
            )
        )
    return (
        await db.scalars(
            select(Item)
            .where(Item.workspace_id == workspace_id, Item.lifecycle == "active", or_(*predicates))
            .order_by(Item.name, Item.id)
            .limit(limit)
        )
    ).all()


async def candidate_card(db, item):
    lots = (
        await db.scalars(
            select(Lot).where(
                Lot.workspace_id == item.workspace_id, Lot.item_id == item.id, Lot.archived_at.is_(None)
            )
        )
    ).all()
    balances = (
        await db.scalars(
            select(Balance).where(
                Balance.workspace_id == item.workspace_id, Balance.lot_id.in_([lot.id for lot in lots])
            )
        )
    ).all()
    locations = (await db.scalars(select(Location).where(Location.workspace_id == item.workspace_id))).all()
    by_id = {r.id: r for r in locations}
    result = {
        "candidate_id": item.id,
        "item_id": item.id,
        "name": item.name,
        "category": item.primary_category,
        "tracking_mode": item.tracking_mode,
        "unit_code": item.base_unit_id,
        "privacy_policy": item.privacy_policy,
        "attributes": item.attributes,
        "version": item.version,
        "index_revision": item.indexed_revision,
        **aggregate(balances, item.tracking_mode),
        "lots": [],
    }
    for lot in lots:
        for balance in (b for b in balances if b.lot_id == lot.id):
            location = by_id[balance.location_id]
            names = [location.name]
            while location.parent_id in by_id:
                location = by_id[location.parent_id]
                names.insert(0, location.name)
            result["lots"].append(
                {
                    "lot_id": lot.id,
                    "location_id": balance.location_id,
                    "location_path": " / ".join(names),
                    "quantity": str(balance.quantity) if balance.quantity is not None else None,
                    "quantity_state": balance.quantity_state,
                    "expiry_on": str(lot.effective_expiry_on) if lot.effective_expiry_on else None,
                    "serial_number": lot.serial_number,
                }
            )
    return result


async def search(
    factory,
    workspace_id,
    query,
    *,
    category=None,
    location_id=None,
    availability=None,
    expired=False,
    limit=30,
    cursor=None,
):
    identity = digest([workspace_id, query, category, location_id, availability, expired])
    offset = 0
    if cursor:
        try:
            page = json.loads(base64.urlsafe_b64decode(cursor))
            require(
                page["query"] == identity and type(page["offset"]) is int and 0 <= page["offset"] <= 100000,
                "INVALID_CURSOR",
                "Курсор относится к другому поиску.",
                400,
            )
            offset = page["offset"]
        except (KeyError, ValueError, TypeError) as error:
            raise DomainError("INVALID_CURSOR", "Некорректный курсор поиска.", 400) from error
    async with factory() as db:
        _, settings = await effective_settings(db)
        exact = await candidates(db, workspace_id, query, limit)
        ids = [item.id for item in exact]
    matched = {item_id: "text_or_exact" for item_id in ids}
    warning = None
    if query:
        try:
            async with gpu_session(factory) as slot:
                if slot is None:
                    warning = "Семантический поиск ожидает GPU; показаны текстовые совпадения."
                else:
                    dense = (await LocalAdapter().embed([query]))[0]
                    qdrant = index.client()
                    try:
                        retrieved = await index.retrieve(
                            qdrant, workspace_id, query, dense, settings, category=category
                        )
                    finally:
                        await qdrant.close()
                    for item_id in retrieved:
                        if item_id not in matched:
                            ids.append(item_id)
                            matched[item_id] = "dense_sparse_rrf"
        except Exception:
            warning = "Семантический индекс недоступен; используется поиск по каталогу."
    async with factory() as db:
        query_db = select(Item).where(Item.workspace_id == workspace_id, Item.lifecycle == "active")
        if query:
            query_db = query_db.where(Item.id.in_(ids))
        if category:
            query_db = query_db.where(Item.primary_category == category)
        if location_id:
            all_locations = (
                await db.scalars(select(Location).where(Location.workspace_id == workspace_id))
            ).all()
            subtree = {location_id}
            while True:
                expanded = subtree | {loc.id for loc in all_locations if loc.parent_id in subtree}
                if expanded == subtree:
                    break
                subtree = expanded
            query_db = query_db.where(
                Item.id.in_(
                    select(Lot.item_id)
                    .join(Balance, Balance.lot_id == Lot.id)
                    .where(
                        Balance.workspace_id == workspace_id,
                        Balance.location_id.in_(subtree),
                        Lot.archived_at.is_(None),
                        (Balance.quantity > 0) | Balance.quantity_state.in_(["unknown", "not_applicable"]),
                    )
                )
            )
        if expired:
            query_db = query_db.where(
                Item.id.in_(
                    select(Lot.item_id).where(
                        Lot.workspace_id == workspace_id, Lot.effective_expiry_on < date.today()
                    )
                )
            )
        rows = (await db.scalars(query_db)).all()
        rows.sort(key=lambda item: ids.index(item.id) if item.id in ids else len(ids))
        result = []
        for item in rows:
            card = await candidate_card(db, item)
            if availability and card["depleted"] != (availability == "depleted"):
                continue
            result.append(
                {
                    **card,
                    "matched_by": matched.get(item.id, "filter"),
                    "explanation_short": "Совпадение по подтверждённым данным каталога.",
                }
            )
        from app.application.photos import item_photos

        visible = result[offset : offset + limit]
        photos = await item_photos(db, workspace_id, [item["item_id"] for item in visible])
        for item in visible:
            item["photos"] = photos[item["item_id"]]
    more = len(result) > offset + limit
    next_cursor = (
        base64.urlsafe_b64encode(json.dumps({"query": identity, "offset": offset + limit}).encode()).decode()
        if more
        else None
    )
    return {
        "items": result[offset : offset + limit],
        "warning": warning,
        "has_more": more,
        "next_cursor": next_cursor,
    }


async def index_item(factory, item_id, workspace_id, collection=None):
    # Один локальный slot сериализует также индексаторы, включая сетевую запись Qdrant.
    async with gpu_session(factory) as slot:
        if slot is None:
            return False
        async with factory() as db:
            item = await db.scalar(select(Item).where(Item.id == item_id, Item.workspace_id == workspace_id))
            if item is None:
                return True
            snapshot = jsonable(row_state(item))
            document = await search_document(db, item)
        qdrant = index.client()
        try:
            if item.lifecycle != "active":
                if await qdrant.collection_exists(collection or index.get_config().search_collection):
                    await qdrant.delete(
                        collection or index.get_config().search_collection,
                        points_selector=[item_id],
                        wait=True,
                    )
            else:
                vector = (await LocalAdapter().embed([document]))[0]
                await index.upsert(qdrant, snapshot, document, vector, collection)
        finally:
            await qdrant.close()
        if not collection:
            async with factory() as db, db.begin():
                current = await db.get(Item, item_id, with_for_update=True)
                if current and current.search_revision == snapshot["search_revision"]:
                    current.indexed_revision = current.search_revision
        return True


async def rebuild_index(factory, workspace_id, collection):
    """Теневая коллекция проверяется перед атомарным переключением общего alias."""
    from qdrant_client import models

    # Alias общий для workspace, поэтому пересобираем все доступные карточки.
    async with factory() as db:
        snapshots = [
            (item.id, item.workspace_id, item.search_revision)
            for item in (await db.scalars(select(Item))).all()
        ]
    qdrant = index.client()
    try:
        await index.initialize(qdrant, collection)
    finally:
        await qdrant.close()
    for item_id, owner, _ in snapshots:
        if not await index_item(factory, item_id, owner, collection):
            return False
    async with gpu_session(factory) as slot:
        if slot is None:
            return False
        qdrant = index.client()
        try:
            async with factory() as db, db.begin():
                # Короткая блокировка исключает изменения между проверкой и сменой alias.
                await db.scalars(select(Workspace).order_by(Workspace.id).with_for_update())
                current = (await db.scalars(select(Item))).all()
                active = {row.id: row for row in current if row.lifecycle == "active"}
                points = []
                cursor = None
                while True:
                    batch, cursor = await qdrant.scroll(
                        collection, limit=100, offset=cursor, with_payload=True, with_vectors=False
                    )
                    points.extend(batch)
                    if cursor is None:
                        break
                indexed = {str(point.id): point.payload for point in points}
                # Лишние/старые точки не проходят проверку. Повтор перечитает текущие данные.
                if set(indexed) != set(active) or any(
                    indexed[key].get("entity_version") != row.search_revision
                    or indexed[key].get("workspace_id") != row.workspace_id
                    for key, row in active.items()
                ):
                    return False
                alias = index.get_config().search_collection
                aliases = (await qdrant.get_aliases()).aliases
                actions = (
                    [models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=alias))]
                    if any(a.alias_name == alias for a in aliases)
                    else []
                )
                actions.append(
                    models.CreateAliasOperation(
                        create_alias=models.CreateAlias(collection_name=collection, alias_name=alias)
                    )
                )
                await qdrant.update_collection_aliases(actions)
                for row in current:
                    row.indexed_revision = row.search_revision
            return True
        finally:
            await qdrant.close()
