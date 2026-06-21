import os
import uuid
import shutil
import datetime
from pathlib import Path
from typing import List, Optional


from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.db.models import User, Task, TaskStatus
from backend.app.schemas import TaskResponse, TaskResolve
from backend.app.api.deps import get_db_session, get_current_user
from backend.app.services.qdrant import delete_item_vector
from backend.app.services.settings_manager import SettingsManager
from backend.app.services.s3 import upload_file_to_s3
from config import settings, logger

router = APIRouter()

TEMP_DIR = Path("data/tmp")
TEMP_DIR.mkdir(parents=True, exist_ok=True)


async def get_redis(request: Request):
    """Retrieve the arq Redis connection pool from FastAPI app state."""
    return request.app.state.arq_redis


@router.post(
    "/items/process",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue multimodal inventory processing task",
    description="Processes photos and audio asynchronously. Rejects request if more than 3 photos are provided. Routes task to default or bulk queue based on user's active tasks.",
    responses={
        400: {"description": "Invalid input files or formatting issues."},
        401: {"description": "Could not validate credentials."}
    }
)
async def process_inventory_action(
    photos: list[UploadFile],
    audio: Optional[UploadFile] = File(None, description="Optional WAV mono 16 KHz audio file"),
    text_comment: Optional[str] = Form(None, description="Optional text context/comment"),
    local_only: bool = Form(False, description="Enforce local Gemma models only (disable Cloud Gemma)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    redis = Depends(get_redis)
):
    """
    Asynchronous multipart/form endpoint accepting files, checking active user task counters,
    uploading raw files to S3, and queuing a background Stage 1 job in arq.
    """
    if not photos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one photo must be provided"
        )
        
    if len(photos) > 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum of 3 photos allowed"
        )
        
    user_id_str = str(current_user.id)
    max_tasks = await SettingsManager.get("max_tasks_per_user", settings.MAX_TASKS_PER_USER)
    
    # Create a temp local directory to save incoming files
    task_uuid = uuid.uuid4()
    temp_session_path = TEMP_DIR / str(task_uuid)
    temp_session_path.mkdir(parents=True, exist_ok=True)
    
    raw_s3_photos = []
    raw_s3_audio = None
    
    try:
        # Save and upload photos
        for i, photo in enumerate(photos):
            ext = photo.filename.split(".")[-1] if photo.filename and "." in photo.filename else "jpg"
            p_path = temp_session_path / f"raw_photo_{i}.{ext}"
            with open(p_path, "wb") as buffer:
                shutil.copyfileobj(photo.file, buffer)
            
            s3_key = f"users/{user_id_str}/tasks/{task_uuid}/raw/raw_photo_{i}.{ext}"
            url = upload_file_to_s3(p_path, s3_key)
            raw_s3_photos.append(url)
            
        # Save and upload audio
        if audio:
            ext = audio.filename.split(".")[-1] if audio.filename and "." in audio.filename else "wav"
            a_path = temp_session_path / f"raw_audio.{ext}"
            with open(a_path, "wb") as buffer:
                shutil.copyfileobj(audio.file, buffer)
                
            s3_key = f"users/{user_id_str}/tasks/{task_uuid}/raw/raw_audio.{ext}"
            url = upload_file_to_s3(a_path, s3_key)
            raw_s3_audio = url
            
        # Insert Task record with status queued
        task = Task(
            id=task_uuid,
            user_id=current_user.id,
            status=TaskStatus.QUEUED,
            photo_urls=raw_s3_photos,
            audio_url=raw_s3_audio,
            transcription=text_comment,  # Initially storing user comment here for gatekeeper/asr
            suggested_json={}
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        
        # Increment active tasks counter atomically and route based on new value
        active_count = await redis.incr(f"inventory:active_tasks:{user_id_str}")
        queue_name = "bulk" if active_count > max_tasks else "default"
        logger.info(f"User {user_id_str} has {active_count} active tasks. Routing to queue: {queue_name}")
        
        # Check user settings for local LLM override
        if current_user.settings and current_user.settings.get("local_llm_only"):
            local_only = True
            
        # Enqueue arq background job
        await redis.enqueue_job(
            "run_stage1_pipeline", 
            str(task_uuid), 
            local_only, 
            _queue_name=queue_name
        )
        
        return {"task_id": str(task_uuid), "status": "queued"}
        
    except Exception as e:
        logger.exception(f"Failed to queue inventory action for task {task_uuid}")
        # If the counter was already incremented, revert it
        try:
            active_count_bytes = await redis.get(f"inventory:active_tasks:{user_id_str}")
            if active_count_bytes and int(active_count_bytes) > 0:
                await redis.decr(f"inventory:active_tasks:{user_id_str}")
        except:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to queue task: {str(e)}"
        )
    finally:
        try:
            shutil.rmtree(temp_session_path)
        except Exception as e:
            logger.error(f"Failed to clean up temp session files at {temp_session_path}: {e}")


@router.get(
    "/tasks",
    response_model=List[TaskResponse],
    summary="List tasks",
    description="Lists all background pipeline tasks for the current user."
)
async def list_tasks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    stmt = select(Task).where(Task.user_id == current_user.id).order_by(Task.created_at.desc())
    res = await db.execute(stmt)
    tasks = res.scalars().all()
    return list(tasks)


@router.get(
    "/tasks/{task_id}",
    response_model=TaskResponse,
    summary="Get background task status",
    description="Retrieves the processing status and results/suggested JSON of a background pipeline task."
)
async def get_task_status(
    task_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """Fetch task by ID, verifying user ownership."""
    stmt = select(Task).where(Task.id == task_id, Task.user_id == current_user.id)
    res = await db.execute(stmt)
    task = res.scalar_one_or_none()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
    return task


@router.post(
    "/tasks/{task_id}/resolve",
    response_model=TaskResponse,
    summary="Submit user resolution for paused task",
    description="Accepts corrected or approved item extraction JSON payload, updates the task, and queues the final Stage 2 pipeline to the high priority queue."
)
async def resolve_task(
    task_id: uuid.UUID,
    payload: TaskResolve,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    redis = Depends(get_redis)
):
    """Allows user approval/correction of suggested items and triggers Stage 2 processing."""
    stmt = select(Task).where(Task.id == task_id, Task.user_id == current_user.id)
    res = await db.execute(stmt)
    task = res.scalar_one_or_none()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
        
    if task.status != TaskStatus.USER_ACTION_REQUIRED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task cannot be resolved in its current state: {task.status.value}"
        )
        
    # Merge or overwrite suggested_json with the user-provided corrected layout
    # Keep metadata properties like collage_url / thumb_urls intact if they exist
    collage_url = task.suggested_json.get("collage_url")
    thumb_urls = task.suggested_json.get("thumb_urls")
    
    task.suggested_json = {
        **payload.suggested_json,
        "collage_url": collage_url,
        "thumb_urls": thumb_urls
    }
    
    # Transition status to queued and increment active tasks counter
    task.status = TaskStatus.QUEUED
    task.updated_at = datetime.datetime.now(datetime.timezone.utc)
    await db.commit()
    await db.refresh(task)
    
    user_id_str = str(current_user.id)
    await redis.incr(f"inventory:active_tasks:{user_id_str}")
    
    # Enqueue Stage 2 job into high_priority queue for instant final execution
    await redis.enqueue_job(
        "run_stage2_pipeline", 
        str(task_id), 
        _queue_name="high_priority"
    )
    
    return task
