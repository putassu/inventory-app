import uuid
import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status, UploadFile, File, Form, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, text, asc, desc
from sqlalchemy.orm import selectinload

from backend.app.schemas import ItemResponse, SearchGlobalResponse
from backend.app.db.models import User, Item, Location, PrimaryCategory
from backend.app.api.deps import get_db_session, get_current_user
from backend.app.services.qdrant import hybrid_search_items_locations
from backend.app.services.settings_manager import SettingsManager
from providers import llm_provider
from prompts import get_prompt
from utils import encode_file_base64
from config import settings
import json
import shutil
from pathlib import Path

router = APIRouter()


@router.get(
    "/search",
    response_model=SearchGlobalResponse,
    summary="Global text search with filters",
    description="Searches active inventory items and locations by query string with optional filters for category, tags, date range, and sort.",
    responses={
        401: {"description": "Could not validate credentials."}
    }
)
async def global_search(
    query: str = Query("", description="Search query string (empty returns all with filters)"),
    location_id: Optional[uuid.UUID] = Query(None, description="Filter items by location"),
    category: Optional[str] = Query(None, description="Filter by primary OR secondary category (e.g. TECH, FOOD)"),
    tags: Optional[str] = Query(None, description="Comma-separated tags to filter by"),
    date_from: Optional[datetime.date] = Query(None, description="Filter items created after this date"),
    date_to: Optional[datetime.date] = Query(None, description="Filter items created before this date"),
    sort_by: Optional[str] = Query("updated_at", description="Sort field: name, created_at, updated_at, primary_category"),
    sort_dir: Optional[str] = Query("desc", description="Sort direction: asc or desc"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Fast DB-level global search with filters. NO LLM involved.
    """
    # --- Items query ---
    stmt_items = (
        select(Item)
        .where(Item.user_id == current_user.id, Item.archived_at.is_(None))
        .options(selectinload(Item.media))
    )
    if location_id is not None:
        stmt_items = stmt_items.where(Item.location_id == location_id)

    # Text search filter (only if query is not empty)
    if query.strip():
        q = query.strip()
        search_filter_items = or_(
            Item.name.ilike(f"%{q}%"),
            Item.generated_desc.ilike(f"%{q}%"),
            text("array_to_string(tags, ',') ILIKE :search_query"),
            text("array_to_string(synonyms, ',') ILIKE :search_query")
        )
        stmt_items = stmt_items.where(search_filter_items).params(search_query=f"%{q}%")

    # Category filter — matches primary_category OR any secondary_categories
    if category:
        cat_upper = category.upper()
        stmt_items = stmt_items.where(
            or_(
                Item.primary_category == cat_upper,
                text(f"'{cat_upper}' = ANY(secondary_categories)")
            )
        )

    # Tags filter
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        for tag in tag_list:
            stmt_items = stmt_items.where(
                text("EXISTS (SELECT 1 FROM unnest(tags) t WHERE t ILIKE :tag_val)")
            ).params(tag_val=f"%{tag}%")

    # Date range
    if date_from:
        stmt_items = stmt_items.where(Item.created_at >= datetime.datetime.combine(date_from, datetime.time.min, tzinfo=datetime.timezone.utc))
    if date_to:
        stmt_items = stmt_items.where(Item.created_at <= datetime.datetime.combine(date_to, datetime.time.max, tzinfo=datetime.timezone.utc))

    # Sorting
    sort_column = getattr(Item, sort_by, Item.updated_at)
    stmt_items = stmt_items.order_by(desc(sort_column) if sort_dir == "desc" else asc(sort_column))
    stmt_items = stmt_items.limit(limit)

    res_items = await db.execute(stmt_items)
    items = res_items.scalars().all()

    # --- Locations query ---
    stmt_locs = (
        select(Location)
        .where(Location.user_id == current_user.id)
        .options(selectinload(Location.photos))
    )
    if query.strip():
        q = query.strip()
        search_filter_locs = or_(
            Location.name.ilike(f"%{q}%"),
            Location.description.ilike(f"%{q}%")
        )
        stmt_locs = stmt_locs.where(search_filter_locs)
    stmt_locs = stmt_locs.limit(limit)
    res_locs = await db.execute(stmt_locs)
    locations = res_locs.scalars().all()

    return {"items": list(items), "locations": list(locations)}


@router.post(
    "/search/multimodal",
    response_model=List[ItemResponse],
    summary="Multimodal semantic search",
    description="Searches inventory using text, audio, or images via local LLM -> Gemini fallback -> Qdrant hybrid search."
)
async def multimodal_search(
    text_query: Optional[str] = Form(None),
    audio: Optional[UploadFile] = File(None),
    photo: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    if not any([text_query, audio, photo]):
        raise HTTPException(status_code=400, detail="Must provide at least one of: text, audio, photo")

    temp_dir = Path(f"data/tmp/search_{uuid.uuid4()}")
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        user_content = []
        if text_query:
            user_content.append({"type": "text", "text": text_query})
            
        if photo:
            photo_path = temp_dir / photo.filename
            with open(photo_path, "wb") as f:
                shutil.copyfileobj(photo.file, f)
            b64 = encode_file_base64(photo_path)
            if b64:
                user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
                
        if audio:
            audio_path = temp_dir / audio.filename
            with open(audio_path, "wb") as f:
                shutil.copyfileobj(audio.file, f)
            b64 = encode_file_base64(audio_path)
            if b64:
                user_content.append({"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}})
                
        prompt = get_prompt("search_extractor.j2")
        
        local_model = await SettingsManager.get("local_model_name", settings.LOCAL_MODEL_NAME)
        res = await llm_provider.generate_multimodal(
            model_name=local_model,
            system_prompt=prompt,
            user_content=user_content
        )
        
        confidence = float(res.get("confidence_score", 1.0))
        
        # Fallback to Gemini if confidence is low
        min_conf = await SettingsManager.get("min_confidence_score", settings.MIN_CONFIDENCE_SCORE)
        if confidence < min_conf:
            gemini_model = await SettingsManager.get("gemini_model_name", settings.GEMINI_MODEL_NAME)
            res = await llm_provider.generate_multimodal(
                model_name=gemini_model,
                system_prompt=prompt,
                user_content=user_content
            )
            
        search_str = res.get("query", "")
        if not search_str:
            return []
            
        # Perform Qdrant hybrid search
        hits = await hybrid_search_items_locations(
            user_id=current_user.id,
            query=search_str,
            is_location=False,
            limit=10
        )
        
        # Fetch actual DB items
        if not hits:
            return []
            
        hit_ids = [uuid.UUID(h["parent_id"]) for h in hits]
        stmt = (
            select(Item)
            .where(Item.id.in_(hit_ids), Item.archived_at.is_(None))
            .options(selectinload(Item.media))
        )
        db_items = (await db.execute(stmt)).scalars().all()
        
        # Sort back to Qdrant order
        id_map = {item.id: item for item in db_items}
        sorted_items = [id_map[hid] for hid in hit_ids if hid in id_map]
        
        return sorted_items
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

