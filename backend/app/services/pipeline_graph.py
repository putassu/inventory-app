import os
import uuid
import shutil
import datetime
from decimal import Decimal
from pathlib import Path
from typing import TypedDict, List, Dict, Any, Optional

from sqlalchemy import select
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import RetryPolicy

from backend.app.db.database import AsyncSessionLocal
from backend.app.db.models import (
    Task,
    TaskStatus,
    Item,
    ItemMedia,
    Location,
    PrimaryCategory,
    ItemStatus,
    MediaType,
    UserTier
)
from backend.app.services.s3 import download_file_from_s3, upload_file_to_s3
from backend.app.services.qdrant import upsert_item_vector, hybrid_search_items_locations, upsert_term_vectors
from backend.app.services.pipeline import get_or_create_location, save_extracted_entities_to_db
from backend.app.schemas import GatekeeperOutput, RAGContextItem, RAGSearchResult
from backend.app.services.settings_manager import SettingsManager
from config import settings, logger
from utils import optimize_image, generate_thumbnail, create_vertical_collage, encode_file_base64
from providers import llm_provider
from prompts import get_prompt
import re
from dateutil.relativedelta import relativedelta


# ==========================================
# PIPELINE STATE
# ==========================================

class PipelineState(TypedDict):
    task_id: str
    user_id: str
    local_only: bool

    # Media inputs/outputs
    photo_urls: List[str]
    audio_url: Optional[str]
    transcription: str

    # Processed files S3 URLs
    opt_photos: List[str]
    thumbnails: List[str]
    collage_url: Optional[str]

    # Gatekeeper
    is_safe: bool
    gatekeeper_items: List[Dict[str, Any]]
    gatekeeper_locations: List[str]

    # VLM Extraction
    suggested_json: Dict[str, Any]
    confidence_score: float
    
    # Schedule Extraction
    schedule_parsing_failed: bool

    # User corrected JSON (set on HITL resume)
    corrected_json: Optional[Dict[str, Any]]

    # Error message
    error: Optional[str]

    # RAG Context injected text
    rag_context: Optional[str]


# ==========================================
# RETRY POLICY
# ==========================================

retry_policy = RetryPolicy(max_attempts=settings.LANGGRAPH_NODE_RETRIES)


# ==========================================
# HELPER: Build VLM user content
# ==========================================

def _build_vlm_user_content(
    transcription: str,
    rag_context: Optional[str],
    image_paths: List[Path],
) -> List[Dict[str, Any]]:
    """Build the multimodal user_content list for a VLM extraction call."""
    content: List[Dict[str, Any]] = []
    if transcription and transcription.strip():
        content.append({"type": "text", "text": f"Текст/Расшифровка: {transcription}"})
    else:
        content.append({"type": "text", "text": "Текст/Расшифровка отсутствует."})
    if rag_context:
        content.append({
            "type": "text",
            "text": (
                "Контекст существующих предметов и мест из базы данных (RAG):\n"
                f"{rag_context}\n"
                "Используй эти существующие ID и названия для связывания, "
                "если пользователь имеет в виду именно их."
            )
        })
    for img_path in image_paths:
        base64_img = encode_file_base64(img_path)
        if base64_img:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}
            })
    return content


def _parse_confidence(raw: Any) -> float:
    """Safely parse confidence_score from model output."""
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 1.0


def evaluate_time_expr(expr: str, current_date: datetime.datetime, expiry_date: Optional[datetime.datetime]) -> datetime.datetime:
    """Parses exact_time_expr from LLM into a specific UTC datetime."""
    if not expr:
        raise ValueError("Empty expression")
        
    expr = expr.strip()
    time_part = "12:00"
    if "@" in expr:
        parts = expr.split("@")
        expr = parts[0].strip()
        time_part = parts[1].strip()
        
    hour, minute = map(int, time_part.split(":"))
    
    if expr.startswith("SPECIFIC("):
        m = re.search(r"SPECIFIC\(([^)]+)\)", expr)
        if not m:
            raise ValueError("Invalid SPECIFIC format")
        base = datetime.datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
        return base.replace(hour=hour, minute=minute)
        
    if expr.startswith("RELATIVE("):
        m = re.search(r"RELATIVE\(([^)]+)\)", expr)
        if not m:
            raise ValueError("Invalid RELATIVE format")
        args = [s.strip() for s in m.group(1).split(",")]
        base_name = args[0]
        
        if base_name == "current_date":
            base = current_date
        elif base_name == "expiry_date":
            if not expiry_date:
                raise ValueError("expiry_date is required but not provided")
            base = expiry_date
        else:
            raise ValueError(f"Unknown base date: {base_name}")
            
        kwargs = {}
        for arg in args[1:]:
            k, v = arg.split("=")
            kwargs[k.strip()] = int(v.strip())
            
        base = base + relativedelta(**kwargs)
        return base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
    raise ValueError(f"Invalid format: {expr}")


# ==========================================
# GRAPH NODES
# ==========================================

async def preprocess_and_upload_node(state: PipelineState) -> Dict[str, Any]:
    """Download raw media from S3, optimize images, generate thumbnails/collage, re-upload."""
    task_id = uuid.UUID(state["task_id"])
    user_id = uuid.UUID(state["user_id"])
    logger.info(f"LangGraph: Preprocessing assets for task {task_id}")

    temp_dir = Path(f"data/tmp/{task_id}")
    temp_dir.mkdir(parents=True, exist_ok=True)

    local_raw_photos = []
    local_raw_audio = None

    try:
        # Download files from S3 to temp directory
        for i, url in enumerate(state["photo_urls"]):
            local_path = download_file_from_s3(url, temp_dir)
            local_raw_photos.append(local_path)

        if state["audio_url"]:
            local_raw_audio = download_file_from_s3(state["audio_url"], temp_dir)

        # Optimize photos and thumbnails
        opt_photos = []
        thumbnails = []
        for photo_path in local_raw_photos:
            opt = optimize_image(photo_path, len(local_raw_photos))
            if opt:
                opt_photos.append(opt)
            thumb = generate_thumbnail(photo_path)
            if thumb:
                thumbnails.append(thumb)

        # Create collage
        collage_path = None
        if opt_photos:
            target_width = settings.ADAPTIVE_IMAGE_SIZES.get(min(len(opt_photos), 3), 512)
            collage_path = create_vertical_collage(opt_photos, target_width)

        # Upload processed outputs to S3
        final_photo_urls = []
        final_thumb_urls = []
        final_collage_url = None

        for i, opt in enumerate(opt_photos):
            s3_key = f"users/{user_id}/tasks/{task_id}/photos/photo_{i}.jpg"
            url = upload_file_to_s3(opt, s3_key)
            final_photo_urls.append(url)

        for i, thumb in enumerate(thumbnails):
            s3_key = f"users/{user_id}/tasks/{task_id}/thumbnails/thumb_{i}.jpg"
            url = upload_file_to_s3(thumb, s3_key)
            final_thumb_urls.append(url)

        if collage_path:
            s3_key = f"users/{user_id}/tasks/{task_id}/collages/collage.jpg"
            final_collage_url = upload_file_to_s3(collage_path, s3_key)

        return {
            "opt_photos": final_photo_urls,
            "thumbnails": final_thumb_urls,
            "collage_url": final_collage_url
        }
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.error(f"Failed to clear task temp directory {temp_dir}: {e}")


async def gatekeeper_check_node(state: PipelineState) -> Dict[str, Any]:
    """Run safety check via local-gemma-4-e4b, extract entities, perform RAG hybrid search."""
    task_id = uuid.UUID(state["task_id"])
    user_id = uuid.UUID(state["user_id"])
    logger.info(f"LangGraph: Running Gatekeeper check for task {task_id}")

    # Download files required for check from S3
    temp_dir = Path(f"data/tmp/{task_id}_gatekeeper")
    temp_dir.mkdir(parents=True, exist_ok=True)

    collage_path = None
    audio_path = None

    try:
        if state["collage_url"]:
            collage_path = download_file_from_s3(state["collage_url"], temp_dir)
        if state["audio_url"]:
            audio_path = download_file_from_s3(state["audio_url"], temp_dir)

        gatekeeper_prompt = get_prompt("gemma_e4b_gatekeeper.txt")
        gatekeeper_user_content = []

        if state["transcription"]:
            gatekeeper_user_content.append({"type": "text", "text": f"Комментарий: {state['transcription']}"})

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

        small_model = await SettingsManager.get("small_local_model_name", settings.SMALL_LOCAL_MODEL_NAME)
        gate_res = await llm_provider.generate_multimodal(
            model_name=small_model,
            system_prompt=gatekeeper_prompt,
            user_content=gatekeeper_user_content,
            timeout_seconds=600.0
        )

        # Parse gatekeeper response using Pydantic model
        if "confidence_score" not in gate_res:
            gate_res["confidence_score"] = 1.0

        try:
            gatekeeper_data = GatekeeperOutput(**gate_res)
        except Exception as e:
            logger.warning(f"Gatekeeper output validation failed: {e}. Fallback parsing.")
            fallback_items = []
            for it in gate_res.get("items", []):
                if isinstance(it, str):
                    fallback_items.append({"name": it, "category": "OTHER"})
                elif isinstance(it, dict):
                    if "class" in it and "category" not in it:
                        it["category"] = it.pop("class")
                    # ensure category is valid
                    if it.get("category") not in PrimaryCategory.__members__:
                        it["category"] = "OTHER"
                    fallback_items.append(it)
                else:
                    fallback_items.append(it)
            gatekeeper_data = GatekeeperOutput(
                is_safe=gate_res.get("is_safe", True),
                transcription=gate_res.get("transcription") or state["transcription"] or "",
                items=fallback_items,
                locations=gate_res.get("locations") or [],
                confidence_score=float(gate_res.get("confidence_score") or 1.0)
            )

        is_safe = gatekeeper_data.is_safe
        transcription = gatekeeper_data.transcription or ""

        # Perform Qdrant Hybrid RAG if confidence exceeds threshold
        rag_context = None
        min_confidence = await SettingsManager.get("min_confidence_score", settings.MIN_CONFIDENCE_SCORE)
        
        if gatekeeper_data.confidence_score > min_confidence:
            logger.info(f"Gatekeeper confidence {gatekeeper_data.confidence_score} > {min_confidence}. Running hybrid RAG.")
            rag_items = []
            rag_locations = []

            # Search for each items entity
            for item_obj in gatekeeper_data.items:
                # item_obj is an ExtractedItem if successfully parsed, or dict if fallback
                item_name = item_obj.name if hasattr(item_obj, "name") else str(item_obj)
                hits = await hybrid_search_items_locations(
                    user_id=user_id,
                    query=item_name,
                    is_location=False,
                    query_tags=[],
                    limit=5
                )
                for hit in hits:
                    rag_items.append(RAGContextItem(**hit))

            # Search for each locations entity
            for loc_query in gatekeeper_data.locations:
                hits = await hybrid_search_items_locations(
                    user_id=user_id,
                    query=loc_query,
                    is_location=True,
                    query_tags=[],
                    limit=5
                )
                for hit in hits:
                    rag_locations.append(RAGContextItem(**hit))

            # Deduplicate by parent_id
            seen_items = set()
            unique_items = []
            for ri in rag_items:
                if ri.parent_id not in seen_items:
                    seen_items.add(ri.parent_id)
                    unique_items.append(ri)

            seen_locs = set()
            unique_locs = []
            for rl in rag_locations:
                if rl.parent_id not in seen_locs:
                    seen_locs.add(rl.parent_id)
                    unique_locs.append(rl)

            # Limit results
            rag_result = RAGSearchResult(
                items=unique_items[:10],
                locations=unique_locs[:10]
            )

            # Format context string
            context_lines = []
            if rag_result.items:
                context_lines.append("Найденные похожие существующие предметы в системе:")
                for ri in rag_result.items:
                    context_lines.append(
                        f"- Предмет: ID={ri.parent_id}, Название='{ri.name}', Описание='{ri.description}', Теги={ri.tags}, Сходство={ri.score:.2f}"
                    )
            if rag_result.locations:
                context_lines.append("Найденные похожие существующие локации в системе:")
                for rl in rag_result.locations:
                    context_lines.append(
                        f"- Локация: ID={rl.parent_id}, Название='{rl.name}', Описание='{rl.description}', Сходство={rl.score:.2f}"
                    )
            if context_lines:
                rag_context = "\n".join(context_lines)
                logger.info(f"RAG: Context generated successfully:\n{rag_context}")

        gatekeeper_items_dicts = []
        for it in gatekeeper_data.items:
            if hasattr(it, "model_dump"):
                gatekeeper_items_dicts.append(it.model_dump())
            elif isinstance(it, dict):
                gatekeeper_items_dicts.append(it)
            else:
                gatekeeper_items_dicts.append({"name": str(it), "category": "OTHER"})

        # Save Gatekeeper output to DB Task record
        async with AsyncSessionLocal() as session:
            stmt = select(Task).where(Task.id == task_id)
            res = await session.execute(stmt)
            db_task = res.scalar_one()

            db_task.is_safe = is_safe
            db_task.transcription = transcription
            db_task.photo_urls = state["opt_photos"]
            db_task.suggested_json = {
                "items": gatekeeper_items_dicts,
                "locations": gatekeeper_data.locations,
                "collage_url": state["collage_url"],
                "thumb_urls": state["thumbnails"],
                "gatekeeper_confidence": gatekeeper_data.confidence_score
            }
            db_task.updated_at = datetime.datetime.now(datetime.timezone.utc)
            await session.commit()

        return {
            "is_safe": is_safe,
            "transcription": transcription,
            "gatekeeper_items": gatekeeper_items_dicts,
            "gatekeeper_locations": gatekeeper_data.locations,
            "suggested_json": db_task.suggested_json,
            "rag_context": rag_context
        }
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.error(f"Failed to clear gatekeeper temp directory: {e}")


async def cloud_gemma_extract_node(state: PipelineState) -> Dict[str, Any]:
    """Extract entities via Cloud Gemma (gemma-4-31b). Sends individual optimized photos."""
    task_id = uuid.UUID(state["task_id"])
    model_name = await SettingsManager.get("cloud_gemma_model_name", settings.CLOUD_GEMMA_MODEL_NAME)
    logger.info(f"LangGraph: Cloud Gemma extraction for task {task_id} using {model_name}")

    temp_dir = Path(f"data/tmp/{task_id}_cloud_gemma")
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Download individual optimized photos for cloud model
        image_paths = []
        for url in state["opt_photos"]:
            path = download_file_from_s3(url, temp_dir)
            image_paths.append(path)

        # Render dynamic prompt using gatekeeper items
        core_prompt = get_prompt("gemma_core_vlm.j2", extracted_items=state.get("gatekeeper_items", []))
        user_content = _build_vlm_user_content(
            transcription=state["transcription"],
            rag_context=state.get("rag_context"),
            image_paths=image_paths,
        )

        core_res = await llm_provider.generate_multimodal(
            model_name=model_name,
            system_prompt=core_prompt,
            user_content=user_content,
            timeout_seconds=60.0
        )

        if "error" in core_res:
            logger.error(f"LangGraph: LLM returned error: {core_res['error']}")
            confidence_val = 0.0
        else:
            confidence_val = _parse_confidence(core_res.get("confidence_score", 1.0))

        suggested = {
            **core_res,
            "collage_url": state["collage_url"],
            "thumb_urls": state["thumbnails"]
        }

        # Persist to DB
        async with AsyncSessionLocal() as session:
            stmt = select(Task).where(Task.id == task_id)
            res = await session.execute(stmt)
            db_task = res.scalar_one()
            db_task.confidence_score = Decimal(str(confidence_val))
            db_task.suggested_json = suggested
            db_task.updated_at = datetime.datetime.now(datetime.timezone.utc)
            await session.commit()

        return {
            "suggested_json": suggested,
            "confidence_score": confidence_val
        }
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.error(f"Failed to clear cloud_gemma temp directory: {e}")


async def local_gemma_extract_node(state: PipelineState) -> Dict[str, Any]:
    """Extract entities via Local Gemma (local-gemma-4). Sends collage for efficiency."""
    task_id = uuid.UUID(state["task_id"])
    model_name = await SettingsManager.get("local_model_name", settings.LOCAL_MODEL_NAME)
    logger.info(f"LangGraph: Local Gemma extraction for task {task_id} using {model_name}")

    temp_dir = Path(f"data/tmp/{task_id}_local_gemma")
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Download collage for local model (single image, lower bandwidth)
        image_paths = []
        if state["collage_url"]:
            collage_path = download_file_from_s3(state["collage_url"], temp_dir)
            image_paths.append(collage_path)

        # Render dynamic prompt using gatekeeper items
        core_prompt = get_prompt("gemma_core_vlm.j2", extracted_items=state.get("gatekeeper_items", []))
        user_content = _build_vlm_user_content(
            transcription=state["transcription"],
            rag_context=state.get("rag_context"),
            image_paths=image_paths,
        )

        core_res = await llm_provider.generate_multimodal(
            model_name=model_name,
            system_prompt=core_prompt,
            user_content=user_content,
            timeout_seconds=600.0
        )

        if "error" in core_res:
            logger.error(f"LangGraph: LLM returned error: {core_res['error']}")
            confidence_val = 0.0
        else:
            confidence_val = _parse_confidence(core_res.get("confidence_score", 1.0))

        suggested = {
            **core_res,
            "collage_url": state["collage_url"],
            "thumb_urls": state["thumbnails"]
        }

        # Persist to DB
        async with AsyncSessionLocal() as session:
            stmt = select(Task).where(Task.id == task_id)
            res = await session.execute(stmt)
            db_task = res.scalar_one()
            db_task.confidence_score = Decimal(str(confidence_val))
            db_task.suggested_json = suggested
            db_task.updated_at = datetime.datetime.now(datetime.timezone.utc)
            await session.commit()

        return {
            "suggested_json": suggested,
            "confidence_score": confidence_val
        }
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.error(f"Failed to clear local_gemma temp directory: {e}")


async def cloud_gemini_extract_node(state: PipelineState) -> Dict[str, Any]:
    """Fallback extraction via Cloud Gemini (gemini-3.5-flash). Triggered when confidence < threshold."""
    task_id = uuid.UUID(state["task_id"])
    model_name = await SettingsManager.get("gemini_model_name", settings.GEMINI_MODEL_NAME)
    logger.info(f"LangGraph: Gemini fallback extraction for task {task_id} using {model_name}")

    temp_dir = Path(f"data/tmp/{task_id}_gemini")
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Download individual photos for Gemini
        image_paths = []
        for url in state["opt_photos"]:
            path = download_file_from_s3(url, temp_dir)
            image_paths.append(path)

        # Render dynamic prompt using gatekeeper items
        core_prompt = get_prompt("gemma_core_vlm.j2", extracted_items=state.get("gatekeeper_items", []))
        user_content = _build_vlm_user_content(
            transcription=state["transcription"],
            rag_context=state.get("rag_context"),
            image_paths=image_paths,
        )

        core_res = await llm_provider.generate_multimodal(
            model_name=model_name,
            system_prompt=core_prompt,
            user_content=user_content,
            timeout_seconds=60.0
        )

        if "error" in core_res:
            logger.error(f"LangGraph: LLM returned error: {core_res['error']}")
            confidence_val = 0.0
        else:
            confidence_val = _parse_confidence(core_res.get("confidence_score", 1.0))

        suggested = {
            **core_res,
            "collage_url": state["collage_url"],
            "thumb_urls": state["thumbnails"]
        }

        # Persist to DB
        async with AsyncSessionLocal() as session:
            stmt = select(Task).where(Task.id == task_id)
            res = await session.execute(stmt)
            db_task = res.scalar_one()
            db_task.confidence_score = Decimal(str(confidence_val))
            db_task.suggested_json = suggested
            db_task.updated_at = datetime.datetime.now(datetime.timezone.utc)
            await session.commit()

        return {
            "suggested_json": suggested,
            "confidence_score": confidence_val
        }
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.error(f"Failed to clear gemini temp directory: {e}")


async def review_node(state: PipelineState) -> Dict[str, Any]:
    """Pass-through node. State contains output from cloud_gemma or local_gemma."""
    task_id = uuid.UUID(state["task_id"])
    logger.info(f"LangGraph: review_node executed for task {task_id}")
    return {}


async def extract_schedule_node(state: PipelineState) -> Dict[str, Any]:
    """Extracts schedule if has_schedule_mention is true, with Gemini fallback and python parsing."""
    task_id = uuid.UUID(state["task_id"])
    suggested = state.get("suggested_json") or {}
    
    if not suggested.get("has_schedule_mention"):
        return {"schedule_parsing_failed": False}
        
    logger.info(f"LangGraph: Extracting schedule for task {task_id}")
    transcription = state.get("transcription", "")
    
    # Try parsing via LLM
    prompt = get_prompt("schedule_parser.j2", 
        current_date=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
        current_day_of_week=datetime.datetime.now(datetime.timezone.utc).strftime("%A"),
        current_time=datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M"),
        user_timezone="UTC", # Could be fetched from user settings if added to state
        expiry_date=None # Could extract from suggested items if available
    )
    
    async def try_parse_schedule(model_name: str) -> Optional[Dict[str, Any]]:
        try:
            res = await llm_provider.generate_multimodal(
                model_name=model_name,
                system_prompt=prompt,
                user_content=[{"type": "text", "text": transcription}]
            )
            
            cron_schedule = res.get("cron_schedule")
            exact_time_expr = res.get("exact_time_expr")
            
            if exact_time_expr:
                # Test parsing
                parsed_time = evaluate_time_expr(exact_time_expr, datetime.datetime.now(datetime.timezone.utc), None)
                return {"remind_at": parsed_time.isoformat()}
            elif cron_schedule:
                return {"cron_schedule": cron_schedule}
            return None
        except Exception as e:
            logger.error(f"Schedule extraction failed using {model_name}: {e}")
            return None

    # Attempt 1: Local Model
    local_model = await SettingsManager.get("local_model_name", settings.LOCAL_MODEL_NAME)
    schedule_data = await try_parse_schedule(local_model)
    
    # Attempt 2: Gemini Fallback (if allowed and failed)
    if not schedule_data and not state.get("local_only"):
        logger.info(f"LangGraph: Schedule extraction fallback to Gemini for task {task_id}")
        gemini_model = await SettingsManager.get("gemini_model_name", settings.GEMINI_MODEL_NAME)
        schedule_data = await try_parse_schedule(gemini_model)
        
    if not schedule_data:
        logger.warning(f"LangGraph: Schedule parsing completely failed for task {task_id}. Routing to HITL.")
        return {"schedule_parsing_failed": True}
        
    # Merge schedule data into item attributes if available
    if schedule_data:
        if suggested.get("item_details"):
            if "attributes" not in suggested["item_details"] or not suggested["item_details"]["attributes"]:
                suggested["item_details"]["attributes"] = {}
            suggested["item_details"]["attributes"].update(schedule_data)
        elif suggested.get("items"):
            for item in suggested["items"]:
                if "attributes" not in item or not item["attributes"]:
                    item["attributes"] = {}
                item["attributes"].update(schedule_data)
            
    # Persist
    async with AsyncSessionLocal() as session:
        stmt = select(Task).where(Task.id == task_id)
        db_task = (await session.execute(stmt)).scalar_one()
        db_task.suggested_json = suggested
        await session.commit()
        
    return {"suggested_json": suggested, "schedule_parsing_failed": False}


async def hitl_node(state: PipelineState) -> Dict[str, Any]:
    """HITL interrupt node. On resume, merges user corrections into suggested_json."""
    task_id = uuid.UUID(state["task_id"])
    logger.info(f"LangGraph: hitl_node executed for task {task_id}")

    # If user provided corrected JSON on resume, use it; otherwise keep extraction output
    corrected = state.get("corrected_json")
    if corrected:
        return {"suggested_json": corrected}

    return {"suggested_json": state.get("suggested_json") or {}}


async def execute_db_writes_node(state: PipelineState) -> Dict[str, Any]:
    """Write final entities to PostgreSQL and Qdrant index. Set task as COMPLETED."""
    task_id = uuid.UUID(state["task_id"])
    logger.info(f"LangGraph: Writing entities to database for task {task_id}")

    async with AsyncSessionLocal() as session:
        stmt = select(Task).where(Task.id == task_id)
        res = await session.execute(stmt)
        db_task = res.scalar_one()

        # Override output JSON if user corrections are provided
        final_json = state.get("corrected_json") or state.get("suggested_json") or {}
        db_task.suggested_json = final_json

        await save_extracted_entities_to_db(session, db_task, None)

        db_task.status = TaskStatus.COMPLETED
        db_task.updated_at = datetime.datetime.now(datetime.timezone.utc)
        await session.commit()

    return {}


# ==========================================
# GRAPH ROUTING
# ==========================================

def safety_router(state: PipelineState) -> str:
    """Route based on safety check: unsafe/local_only → local model, safe → cloud model."""
    is_safe = state.get("is_safe", True)
    local_only = state.get("local_only", False)

    if not is_safe or local_only:
        logger.info(f"LangGraph: Routing task {state['task_id']} to local_gemma (is_safe={is_safe}, local_only={local_only})")
        return "local_gemma_extract_node"

    logger.info(f"LangGraph: Routing task {state['task_id']} to cloud_gemma")
    return "cloud_gemma_extract_node"


async def confidence_checker(state: PipelineState) -> str:
    """Route based on extraction confidence and safety flags."""
    confidence = state.get("confidence_score", 1.0)
    is_safe = state.get("is_safe", True)
    local_only = state.get("local_only", False)
    min_conf = await SettingsManager.get("min_confidence_score", settings.MIN_CONFIDENCE_SCORE)

    if confidence >= min_conf:
        logger.info(f"LangGraph: Task {state['task_id']} confidence {confidence} OK. Proceeding to db_writes.")
        return "extract_schedule_node"

    if not is_safe or local_only:
        logger.info(f"LangGraph: Task {state['task_id']} is unsafe/local_only and confidence {confidence} < {min_conf}. Routing to hitl_node.")
        return "hitl_node"

    logger.info(f"LangGraph: Task {state['task_id']} confidence {confidence} < {min_conf}. Routing to cloud_gemini_extract_node.")
    return "cloud_gemini_extract_node"


async def gemini_checker(state: PipelineState) -> str:
    """Check if Gemini fallback succeeded."""
    confidence = state.get("confidence_score", 1.0)
    
    min_conf = await SettingsManager.get("min_confidence_score", settings.MIN_CONFIDENCE_SCORE)
    if confidence < min_conf:
        logger.info(f"LangGraph: Gemini fallback failed. Routing to hitl_node.")
        return "hitl_node"
        
    return "extract_schedule_node"


def schedule_checker(state: PipelineState) -> str:
    """Check if schedule parsing failed, requiring HITL."""
    if state.get("schedule_parsing_failed", False):
        return "hitl_node"
    return "execute_db_writes_node"


# ==========================================
# WORKFLOW CONSTRUCTION
# ==========================================

workflow = StateGraph(PipelineState)

# Add Nodes with retry policies on LLM-calling nodes
workflow.add_node("preprocess_and_upload_node", preprocess_and_upload_node, retry_policy=retry_policy)
workflow.add_node("gatekeeper_check_node", gatekeeper_check_node, retry_policy=retry_policy)
workflow.add_node("cloud_gemma_extract_node", cloud_gemma_extract_node, retry_policy=retry_policy)
workflow.add_node("local_gemma_extract_node", local_gemma_extract_node, retry_policy=retry_policy)
workflow.add_node("cloud_gemini_extract_node", cloud_gemini_extract_node, retry_policy=retry_policy)
workflow.add_node("extract_schedule_node", extract_schedule_node, retry_policy=retry_policy)
workflow.add_node("review_node", review_node)
workflow.add_node("hitl_node", hitl_node)
workflow.add_node("execute_db_writes_node", execute_db_writes_node, retry_policy=retry_policy)

# Edges: START → preprocess → gatekeeper
workflow.add_edge(START, "preprocess_and_upload_node")
workflow.add_edge("preprocess_and_upload_node", "gatekeeper_check_node")

# Conditional: gatekeeper → (safety split) → cloud_gemma or local_gemma
workflow.add_conditional_edges(
    "gatekeeper_check_node",
    safety_router,
    {
        "cloud_gemma_extract_node": "cloud_gemma_extract_node",
        "local_gemma_extract_node": "local_gemma_extract_node",
    }
)

# Both extraction paths converge at review_node
workflow.add_edge("cloud_gemma_extract_node", "review_node")
workflow.add_edge("local_gemma_extract_node", "review_node")

# Conditional: review → confidence_checker
workflow.add_conditional_edges(
    "review_node",
    confidence_checker,
    {
        "hitl_node": "hitl_node",
        "cloud_gemini_extract_node": "cloud_gemini_extract_node",
        "extract_schedule_node": "extract_schedule_node",
    }
)

# Conditional: cloud_gemini → gemini_checker
workflow.add_conditional_edges(
    "cloud_gemini_extract_node",
    gemini_checker,
    {
        "hitl_node": "hitl_node",
        "extract_schedule_node": "extract_schedule_node",
    }
)

# Conditional: extract_schedule → schedule_checker
workflow.add_conditional_edges(
    "extract_schedule_node",
    schedule_checker,
    {
        "hitl_node": "hitl_node",
        "execute_db_writes_node": "execute_db_writes_node",
    }
)

# HITL always proceeds to DB writes
workflow.add_edge("hitl_node", "execute_db_writes_node")
workflow.add_edge("execute_db_writes_node", END)

# Checkpointer initialization (MemorySaver — in-memory, suitable for dev; migrate to PostgresSaver for prod)
checkpointer = MemorySaver()

# Compile graph with HITL interruption before hitl_node
pipeline_graph = workflow.compile(
    checkpointer=checkpointer,
    interrupt_before=["hitl_node"]
)
