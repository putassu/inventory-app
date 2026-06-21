import os
import uuid
import json
import datetime
from decimal import Decimal
from typing import List, Optional, Dict, Any
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, text

from config import settings, logger
from utils import optimize_image, generate_thumbnail, encode_file_base64, create_vertical_collage
from providers import llm_provider
from prompts import get_prompt
from backend.app.db.models import Item, ItemMedia, Location, PrimaryCategory, ItemStatus, MediaType
from backend.app.services.s3 import upload_file_to_s3
from backend.app.services.qdrant import upsert_item_vector, semantic_search_items, upsert_term_vectors

async def get_or_create_location(db: AsyncSession, name: str, user_id: uuid.UUID) -> uuid.UUID:
    """Find a location by name for the user, or create it if not found."""
    stmt = select(Location).where(Location.user_id == user_id, Location.name.ilike(name))
    res = await db.execute(stmt)
    loc = res.scalar_one_or_none()
    if loc:
        return loc.id
        
    # Create new location
    new_loc = Location(
        user_id=user_id,
        name=name,
        description=f"Автоматически создано при добавлении предмета через VLM"
    )
    db.add(new_loc)
    await db.commit()
    await db.refresh(new_loc)
    
    # Index location in Qdrant using upsert_term_vectors
    from backend.app.services.qdrant import upsert_term_vectors
    await upsert_term_vectors(
        parent_id=str(new_loc.id),
        user_id=str(user_id),
        name=name,
        synonyms=[],
        tags=[],
        is_location=True,
        generated_desc=new_loc.description or name
    )
    
    return new_loc.id

async def run_ml_pipeline(
    db: AsyncSession,
    user_id: uuid.UUID,
    photos: List[Path],
    audio_path: Optional[Path],
    text_comment: Optional[str],
    local_only: bool = False
) -> Dict[str, Any]:
    """
    Executes the multi-stage ML pipeline:
    1. Preprocesses and optimizes images (Adaptive downscaling, Thumbnails, Vertical Collage).
    2. Uploads raw and processed media to S3 (MinIO).
    3. Stage 1 (Gatekeeper): Evaluates is_safe & transcribes audio using small local model (local-gemma-4-e4b).
    4. Routing: Routes to Cloud Gemma (gemma-4-31b) if safe, or Local Gemma (local-gemma-4) if unsafe/local_only.
    5. Database resolution: Updates Postgres & indexes descriptions in Qdrant.
    """
    logger.info(f"Starting ML pipeline for user {user_id} with {len(photos)} photos.")
    
    # Generate an upload task ID for file names grouping
    task_uuid = uuid.uuid4()
    
    # 1. Image & Audio Preprocessing
    opt_photos = []
    thumbnails = []
    
    for i, photo_path in enumerate(photos):
        opt = optimize_image(photo_path, len(photos))
        if opt:
            opt_photos.append(opt)
        thumb = generate_thumbnail(photo_path)
        if thumb:
            thumbnails.append(thumb)
            
    # Always build collage for MinIO storage and local model gatekeeper
    target_width = settings.ADAPTIVE_IMAGE_SIZES.get(min(len(photos), 3), 512)
    collage_path = create_vertical_collage(opt_photos, target_width)
    
    # 2. Upload to S3 (MinIO)
    photo_urls = []
    thumb_urls = []
    collage_url = None
    audio_url = None
    
    for i, opt in enumerate(opt_photos):
        s3_key = f"users/{user_id}/tasks/{task_uuid}/photos/photo_{i}.jpg"
        url = upload_file_to_s3(opt, s3_key)
        photo_urls.append(url)
        
    for i, thumb in enumerate(thumbnails):
        s3_key = f"users/{user_id}/tasks/{task_uuid}/thumbnails/thumb_{i}.jpg"
        url = upload_file_to_s3(thumb, s3_key)
        thumb_urls.append(url)
        
    if collage_path:
        s3_key = f"users/{user_id}/tasks/{task_uuid}/collages/collage.jpg"
        collage_url = upload_file_to_s3(collage_path, s3_key)
        
    if audio_path:
        s3_key = f"users/{user_id}/tasks/{task_uuid}/audio/audio.wav"
        audio_url = upload_file_to_s3(audio_path, s3_key)
        
    # 3. Stage 1 (Gatekeeper)
    gatekeeper_prompt = get_prompt("gemma_e4b_gatekeeper.txt")
    gatekeeper_user_content = []
    
    if text_comment:
        gatekeeper_user_content.append({"type": "text", "text": f"Комментарий: {text_comment}"})
        
    if collage_path:
        base64_img = encode_file_base64(collage_path)
        if base64_img:
            gatekeeper_user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}
            })
            
    if audio_path:
        base64_audio = encode_file_base64(audio_path)
        if base64_audio:
            gatekeeper_user_content.append({
                "type": "input_audio",
                "input_audio": {"data": base64_audio, "format": "wav"}
            })
            
    logger.info("Executing Stage 1: Gatekeeper Safety check")
    gate_res = llm_provider.generate_multimodal(
        model_name=settings.SMALL_LOCAL_MODEL_NAME,
        system_prompt=gatekeeper_prompt,
        user_content=gatekeeper_user_content
    )
    
    # Parse gatekeeper outputs
    is_safe = gate_res.get("is_safe", True)
    transcription = gate_res.get("transcription") or text_comment or ""
    
    logger.info(f"Gatekeeper safety result: is_safe={is_safe}, transcription='{transcription}'")
    
    # 4. Stage 2 (VLM Extraction and Action Execution)
    core_prompt = get_prompt("gemma_core_vlm.txt")
    core_user_content = [
        {"type": "text", "text": f"Текст/Расшифровка: {transcription}"}
    ]
    if text_comment:
        core_user_content.append({"type": "text", "text": f"Пользовательский комментарий: {text_comment}"})
        
    # Determine fallback and model routing
    if is_safe and not local_only:
        model_to_use = settings.CLOUD_GEMMA_MODEL_NAME
        logger.info(f"Routing to Cloud VLM model: {model_to_use}")
        # Cloud model receives individual optimized photos
        for opt in opt_photos:
            base64_img = encode_file_base64(opt)
            if base64_img:
                core_user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}
                })
    else:
        model_to_use = settings.LOCAL_MODEL_NAME
        logger.info(f"Routing to Local VLM model: {model_to_use} (is_safe={is_safe}, local_only={local_only})")
        # Local model receives vertical collage
        if collage_path:
            base64_img = encode_file_base64(collage_path)
            if base64_img:
                core_user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}
                })
                
    core_res = llm_provider.generate_multimodal(
        model_name=model_to_use,
        system_prompt=core_prompt,
        user_content=core_user_content
    )
    
    intent = core_res.get("intent") or "add_item"
    logger.info(f"Core VLM output: intent={intent}")
    
    result_metadata = {
        "is_safe": is_safe,
        "transcription": transcription,
        "intent": intent,
        "actions_taken": [],
        "details": {}
    }
    
    # 5. Database execution & Qdrant vector indexing
    if intent == "add_item":
        item_details = core_res.get("item_details") or {}
        item_name = item_details.get("name") or "Без названия"
        
        # Resolve target location ID
        location_id = None
        move_details = core_res.get("move_details") or {}
        to_loc_name = move_details.get("to_location")
        if to_loc_name:
            location_id = await get_or_create_location(db, to_loc_name, user_id)
            
        # Compile description for vector database embedding
        tags = item_details.get("tags") or []
        primary_cat = item_details.get("primary_category") or "OTHER"
        generated_desc = f"{item_name}. Категория: {primary_cat}. Теги: {', '.join(tags)}."
        
        # Calculate embeddings vector via LiteLLM
        embedding = await llm_provider.generate_embeddings(settings.EMBEDDING_MODEL_NAME, generated_desc)
        
        # Create database entity
        item = Item(
            user_id=user_id,
            name=item_name,
            location_id=location_id,
            quantity=Decimal(str(item_details.get("quantity") or 1.0)),
            unit_of_measure=item_details.get("unit_of_measure") or "pcs",
            generated_desc=generated_desc,
            tags=tags,
            synonyms=item_details.get("synonyms") or [],
            primary_category=PrimaryCategory(primary_cat) if primary_cat in PrimaryCategory.__members__ else PrimaryCategory.OTHER,
            secondary_categories=[PrimaryCategory(c) for c in (item_details.get("secondary_categories") or []) if c in PrimaryCategory.__members__],
            status=ItemStatus.COMPLETED,
            attributes=item_details.get("attributes") or {}
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)
        
        # Write embedding points to Qdrant index (main + synonyms)
        await upsert_term_vectors(
            parent_id=str(item.id),
            user_id=str(user_id),
            name=item_name,
            synonyms=item_details.get("synonyms") or [],
            tags=tags,
            is_location=False,
            generated_desc=generated_desc
        )
        
        # Link S3 media records to item in DB
        for photo_url in photo_urls:
            media = ItemMedia(
                item_id=item.id,
                type=MediaType.PHOTO,
                original_url=photo_url,
                is_primary=False
            )
            db.add(media)
            
        if audio_url:
            media = ItemMedia(
                item_id=item.id,
                type=MediaType.AUDIO,
                original_url=audio_url,
                is_primary=False
            )
            db.add(media)
            
        await db.commit()
        
        result_metadata["actions_taken"].append(f"Создан предмет '{item_name}' (ID: {item.id})")
        result_metadata["details"]["item_id"] = str(item.id)
        result_metadata["details"]["location_id"] = str(location_id) if location_id else None
        
    elif intent == "consume_item":
        consume_details = core_res.get("consume_details") or {}
        item_name = consume_details.get("item_name") or ""
        amount = Decimal(str(consume_details.get("amount") or 1.0))
        
        # Find item matching synonym or description
        stmt = select(Item).where(Item.user_id == user_id, Item.archived_at.is_(None)).where(
            or_(
                Item.generated_desc.ilike(f"%{item_name}%"),
                text("array_to_string(synonyms, ',') ILIKE :name_query")
            )
        ).params(name_query=f"%{item_name}%").limit(1)
        
        res = await db.execute(stmt)
        item = res.scalar_one_or_none()
        
        if item:
            current_qty = item.quantity if item.quantity is not None else Decimal("0.0")
            new_qty = current_qty - amount
            if new_qty <= Decimal("0.0"):
                item.quantity = Decimal("0.0")
                item.status = ItemStatus.DEPLETED
                result_metadata["actions_taken"].append(f"Предмет '{item_name}' полностью израсходован (статус: depleted)")
            else:
                item.quantity = new_qty
                result_metadata["actions_taken"].append(f"Количество предмета '{item_name}' уменьшено на {amount}")
            await db.commit()
        else:
            result_metadata["actions_taken"].append(f"Предмет для списания '{item_name}' не найден")
            
    elif intent == "move_item":
        move_details = core_res.get("move_details") or {}
        item_name = move_details.get("item_name") or ""
        to_loc_name = move_details.get("to_location")
        
        if to_loc_name:
            location_id = await get_or_create_location(db, to_loc_name, user_id)
            
            # Find matching item
            stmt = select(Item).where(Item.user_id == user_id, Item.archived_at.is_(None)).where(
                or_(
                    Item.generated_desc.ilike(f"%{item_name}%"),
                    text("array_to_string(synonyms, ',') ILIKE :name_query")
                )
            ).params(name_query=f"%{item_name}%").limit(1)
            
            res = await db.execute(stmt)
            item = res.scalar_one_or_none()
            
            if item:
                item.location_id = location_id
                await db.commit()
                result_metadata["actions_taken"].append(f"Предмет '{item.generated_desc[:20]}' перемещен в '{to_loc_name}'")
            else:
                result_metadata["actions_taken"].append(f"Предмет '{item_name}' для перемещения не найден")
                
    elif intent == "delete_item":
        # Archive item
        move_details = core_res.get("move_details") or {}
        item_name = move_details.get("item_name") or ""
        
        stmt = select(Item).where(Item.user_id == user_id, Item.archived_at.is_(None)).where(
            or_(
                Item.generated_desc.ilike(f"%{item_name}%"),
                text("array_to_string(synonyms, ',') ILIKE :name_query")
            )
        ).params(name_query=f"%{item_name}%").limit(1)
        
        res = await db.execute(stmt)
        item = res.scalar_one_or_none()
        
        if item:
            item.archived_at = datetime.datetime.now(datetime.timezone.utc)
            await db.commit()
            result_metadata["actions_taken"].append(f"Предмет '{item_name}' архивирован (soft-deleted)")
        else:
            result_metadata["actions_taken"].append(f"Предмет '{item_name}' для удаления не найден")
            
    return result_metadata


async def save_extracted_entities_to_db(session, task, redis) -> dict:
    """Commit extracted JSON details (add, move, consume, delete) to database & Qdrant."""
    suggested_json = task.suggested_json
    
    # Handle case where suggested_json is from Gatekeeper (has 'items' array) instead of Core VLM
    if "intent" not in suggested_json and "items" in suggested_json and isinstance(suggested_json["items"], list) and len(suggested_json["items"]) > 0:
        first_item = suggested_json["items"][0]
        suggested_json = {
            "intent": "add_item",
            "item_details": {
                "name": first_item.get("name"),
                "primary_category": first_item.get("category"),
                "location": suggested_json.get("locations", [None])[0] if suggested_json.get("locations") else None
            }
        }
        
    intent = suggested_json.get("intent") or "add_item"
    user_id = task.user_id
    
    result_metadata = {
        "intent": intent,
        "actions_taken": [],
        "details": {}
    }
    
    if intent == "add_item":
        item_details = suggested_json.get("item_details") or {}
        item_name = item_details.get("name") or "Без названия"
        
        # Resolve target location
        location_id = None
        move_details = suggested_json.get("move_details") or {}
        to_loc_name = move_details.get("to_location") or item_details.get("location")
        if to_loc_name:
            location_id = await get_or_create_location(session, to_loc_name, user_id)
            
        tags = item_details.get("tags") or []
        primary_cat = item_details.get("primary_category") or "OTHER"
        generated_desc = f"{item_name}. Категория: {primary_cat}. Теги: {', '.join(tags)}."
        
        # Check for Smart Grouping (merge_with_item_id)
        merge_item_id_str = item_details.get("merge_with_item_id")
        merge_item = None
        if merge_item_id_str:
            try:
                merge_uuid = uuid.UUID(merge_item_id_str)
                stmt = select(Item).where(Item.id == merge_uuid, Item.user_id == user_id)
                res = await session.execute(stmt)
                merge_item = res.scalar_one_or_none()
            except ValueError:
                pass
                
        # Fallback: if no merge_item_id was found (e.g. from UI resolve), try finding an exact match in the same location
        if not merge_item and location_id and item_name and item_name != "Без названия":
            stmt = select(Item).where(
                Item.user_id == user_id, 
                Item.location_id == location_id, 
                Item.name == item_name
            )
            res = await session.execute(stmt)
            merge_item = res.scalar_one_or_none()
                
        new_quantity = Decimal(str(item_details.get("quantity") or 1.0)) if item_details.get("quantity") is not None else None
        
        if merge_item and merge_item.location_id == location_id:
            # Add to existing item in the SAME location
            if merge_item.quantity is not None and new_quantity is not None:
                merge_item.quantity += new_quantity
            elif merge_item.quantity is None and new_quantity is not None:
                merge_item.quantity = new_quantity
                
            merge_item.updated_at = datetime.datetime.now(datetime.timezone.utc)
            item = merge_item
            result_metadata["actions_taken"].append(f"Увеличено количество предмета '{item_name}' (ID: {item.id}) в той же локации")
            
        else:
            # Create a NEW item record
            group_id = None
            if merge_item:
                # Different location, but linked item
                group_id = merge_item.group_id or merge_item.id
                if not merge_item.group_id:
                    merge_item.group_id = group_id  # Update original to be grouped
                    
            item = Item(
                user_id=user_id,
                name=item_name,
                location_id=location_id,
                group_id=group_id,
                quantity=new_quantity,
                unit_of_measure=item_details.get("unit_of_measure") or "pcs",
                generated_desc=generated_desc,
                tags=tags,
                synonyms=item_details.get("synonyms") or [],
                primary_category=PrimaryCategory(primary_cat) if primary_cat in PrimaryCategory.__members__ else PrimaryCategory.OTHER,
                secondary_categories=[PrimaryCategory(c) for c in (item_details.get("secondary_categories") or []) if c in PrimaryCategory.__members__],
                status=ItemStatus.COMPLETED,
                attributes=item_details.get("attributes") or {}
            )
            session.add(item)
            await session.flush()  # Obtain item.id
            result_metadata["actions_taken"].append(f"Создан предмет '{item_name}' (ID: {item.id})")
            
            # Upsert points to Qdrant index only for new item
            await upsert_term_vectors(
                parent_id=str(item.id),
                user_id=str(user_id),
                name=item_name,
                synonyms=item_details.get("synonyms") or [],
                tags=tags,
                is_location=False,
                generated_desc=generated_desc
            )
            
        # Link S3 media items in Postgres to whichever `item` we used
        
        # Link S3 media items in Postgres
        for photo_url in task.photo_urls:
            media = ItemMedia(
                item_id=item.id,
                type=MediaType.PHOTO,
                original_url=photo_url,
                is_primary=False
            )
            session.add(media)
            
        if task.audio_url:
            media = ItemMedia(
                item_id=item.id,
                type=MediaType.AUDIO,
                original_url=task.audio_url,
                is_primary=False
            )
            session.add(media)
            
        result_metadata["details"]["item_id"] = str(item.id)
        result_metadata["details"]["location_id"] = str(location_id) if location_id else None
        
    elif intent == "consume_item":
        consume_details = suggested_json.get("consume_details") or {}
        item_name = consume_details.get("item_name") or ""
        amount = Decimal(str(consume_details.get("amount") or 1.0))
        
        target_item_id_str = consume_details.get("target_item_id")
        
        stmt = select(Item).where(Item.user_id == user_id, Item.archived_at.is_(None))
        if target_item_id_str:
            try:
                target_uuid = uuid.UUID(target_item_id_str)
                stmt = stmt.where(Item.id == target_uuid)
            except ValueError:
                stmt = stmt.where(Item.generated_desc.ilike(f"%{item_name}%"))
        else:
            stmt = stmt.where(
                or_(
                    Item.generated_desc.ilike(f"%{item_name}%"),
                    text("array_to_string(synonyms, ',') ILIKE :name_query")
                )
            ).params(name_query=f"%{item_name}%")
        stmt = stmt.limit(1)
        
        res = await session.execute(stmt)
        item = res.scalar_one_or_none()
        
        if item:
            current_qty = item.quantity if item.quantity is not None else Decimal("0.0")
            new_qty = current_qty - amount
            if new_qty < Decimal("0.0"):
                raise ValueError(f"Недостаточное количество предмета '{item_name}'. В наличии: {current_qty}, попытка списать: {amount}.")
            elif new_qty == Decimal("0.0"):
                item.quantity = Decimal("0.0")
                item.status = ItemStatus.DEPLETED
                result_metadata["actions_taken"].append(f"Предмет '{item_name}' полностью израсходован (статус: depleted)")
            else:
                item.quantity = new_qty
                result_metadata["actions_taken"].append(f"Количество предмета '{item_name}' уменьшено на {amount}")
        else:
            result_metadata["actions_taken"].append(f"Предмет для списания '{item_name}' не найден")
            
    elif intent == "move_item":
        move_details = suggested_json.get("move_details") or {}
        item_name = move_details.get("item_name") or ""
        to_loc_name = move_details.get("to_location")
        
        if to_loc_name:
            location_id = await get_or_create_location(session, to_loc_name, user_id)
            
            target_item_id_str = move_details.get("target_item_id")
            
            stmt = select(Item).where(Item.user_id == user_id, Item.archived_at.is_(None))
            if target_item_id_str:
                try:
                    target_uuid = uuid.UUID(target_item_id_str)
                    stmt = stmt.where(Item.id == target_uuid)
                except ValueError:
                    stmt = stmt.where(Item.generated_desc.ilike(f"%{item_name}%"))
            else:
                stmt = stmt.where(
                    or_(
                        Item.generated_desc.ilike(f"%{item_name}%"),
                        text("array_to_string(synonyms, ',') ILIKE :name_query")
                    )
                ).params(name_query=f"%{item_name}%")
            stmt = stmt.limit(1)
            
            res = await session.execute(stmt)
            item = res.scalar_one_or_none()
            if item:
                if item.location_id == location_id:
                    # VLM thought it was a move, but item is already here. It's likely an 'add' of an identical item!
                    if not move_details.get("from_location"):
                        qty_to_add = Decimal(str(suggested_json.get("item_details", {}).get("quantity") or 1.0))
                        if item.quantity is not None:
                            item.quantity += qty_to_add
                        else:
                            item.quantity = qty_to_add
                        item.updated_at = datetime.datetime.now(datetime.timezone.utc)
                        result_metadata["actions_taken"].append(f"Предмет уже находился в '{to_loc_name}', но так как from_location не указан, мы предполагаем добавление дубликата: количество увеличено на {qty_to_add}")
                    else:
                        result_metadata["actions_taken"].append(f"Предмет уже находился в '{to_loc_name}', перемещение не потребовалось")
                else:
                    item.location_id = location_id
                    item.updated_at = datetime.datetime.now(datetime.timezone.utc)
                    result_metadata["actions_taken"].append(f"Предмет перемещен в '{to_loc_name}'")
            else:
                result_metadata["actions_taken"].append(f"Предмет '{item_name}' для перемещения не найден")
                
    elif intent == "delete_item":
        move_details = suggested_json.get("move_details") or {}
        item_name = move_details.get("item_name") or ""
        
        target_item_id_str = move_details.get("target_item_id")
        
        stmt = select(Item).where(Item.user_id == user_id, Item.archived_at.is_(None))
        if target_item_id_str:
            try:
                target_uuid = uuid.UUID(target_item_id_str)
                stmt = stmt.where(Item.id == target_uuid)
            except ValueError:
                stmt = stmt.where(Item.generated_desc.ilike(f"%{item_name}%"))
        else:
            stmt = stmt.where(
                or_(
                    Item.generated_desc.ilike(f"%{item_name}%"),
                    text("array_to_string(synonyms, ',') ILIKE :name_query")
                )
            ).params(name_query=f"%{item_name}%")
        stmt = stmt.limit(1)
        
        res = await session.execute(stmt)
        item = res.scalar_one_or_none()
        if item:
            item.archived_at = datetime.datetime.now(datetime.timezone.utc)
            result_metadata["actions_taken"].append(f"Предмет '{item_name}' архивирован (soft-deleted)")
        else:
            result_metadata["actions_taken"].append(f"Предмет '{item_name}' для удаления не найден")
            
    return result_metadata
