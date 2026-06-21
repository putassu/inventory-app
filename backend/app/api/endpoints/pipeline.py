import os
import uuid
import shutil
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import User
from backend.app.api.deps import get_db_session, get_current_user
from backend.app.services.pipeline import run_ml_pipeline
from config import logger

router = APIRouter()

TEMP_DIR = Path("data/tmp")

@router.post(
    "/items/process",
    status_code=status.HTTP_200_OK,
    summary="Process VLM inventory action",
    description="Processes photos and optional audio with intent extraction, saving data in Postgres and Qdrant index.",
    responses={
        400: {"description": "Invalid input files or formatting issues."},
        401: {"description": "Could not validate credentials."}
    }
)
async def process_inventory_action(
    photos: List[UploadFile] = File(..., description="Photos of the inventory item(s) (1-3 files)"),
    audio: Optional[UploadFile] = File(None, description="Optional WAV mono 16 KHz audio file"),
    text_comment: Optional[str] = Form(None, description="Optional text context/comment"),
    local_only: bool = Form(False, description="Enforce local Gemma models only (disable Cloud Gemma)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Multimodal API endpoint processing uploads via Multipart Form.
    - Saves uploaded files temporarily.
    - Triggers the VLM processing pipeline.
    - Removes temporary uploads when finished.
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
        
    # Create temp directory
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    session_id = uuid.uuid4().hex
    temp_session_path = TEMP_DIR / session_id
    temp_session_path.mkdir()
    
    local_photos = []
    local_audio = None
    
    try:
        # Save photos locally
        for i, photo in enumerate(photos):
            ext = photo.filename.split(".")[-1] if photo.filename and "." in photo.filename else "jpg"
            p_path = temp_session_path / f"photo_{i}.{ext}"
            with open(p_path, "wb") as buffer:
                shutil.copyfileobj(photo.file, buffer)
            local_photos.append(p_path)
            
        # Save audio locally if provided
        if audio:
            ext = audio.filename.split(".")[-1] if audio.filename and "." in audio.filename else "wav"
            a_path = temp_session_path / f"audio.{ext}"
            with open(a_path, "wb") as buffer:
                shutil.copyfileobj(audio.file, buffer)
            local_audio = a_path
            
        # Run processing pipeline
        result = await run_ml_pipeline(
            db=db,
            user_id=current_user.id,
            photos=local_photos,
            audio_path=local_audio,
            text_comment=text_comment,
            local_only=local_only
        )
        return result
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.exception("ML Pipeline internal error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal pipeline error: {str(e)}"
        )
    finally:
        # Clean up temporary session files
        try:
            shutil.rmtree(temp_session_path)
        except Exception as e:
            logger.error(f"Failed to delete temp files at {temp_session_path}: {e}")
