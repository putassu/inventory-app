import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import admin, auth, catalog, item_fields, maintenance, media, notifications, search, tasks
from app.api.deps import current_user, db_session
from app.application.settings import effective_settings
from app.config import get_config
from app.db.models import Control, GPUSlot
from app.db.session import session_factory
from app.domain.common import uid
from app.domain.errors import DomainError
from app.infrastructure.logging import configure_logging
from app.infrastructure.workers import processing_health

logger = logging.getLogger("inventory")


def create_app(factory=None):
    config = get_config()

    @asynccontextmanager
    async def lifespan(app):
        configure_logging()
        if len(config.jwt_secret.get_secret_value()) < 32:
            raise RuntimeError("Задайте INV_JWT_SECRET длиной не менее 32 символов.")
        yield

    app = FastAPI(
        title="Инвентаризатор",
        version="1.0.0",
        lifespan=lifespan,
        description="Учёт вещей с обязательным подтверждением и журналом операций.",
    )
    app.state.session_factory = factory or session_factory()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Workspace-ID", "Idempotency-Key", "If-None-Match"],
        expose_headers=["ETag", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = uid()
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                "request.failed",
                extra={"request_id": request.state.request_id, "error_type": type(exc).__name__},
            )
            response = JSONResponse(
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "Внутренняя ошибка.",
                        "request_id": request.state.request_id,
                        "retryable": True,
                    }
                },
                status_code=500,
            )
        response.headers["X-Request-ID"] = request.state.request_id
        logger.info(
            "request.finished",
            extra={
                "request_id": request.state.request_id,
                "status": response.status_code,
                "duration_ms": round((time.monotonic() - start) * 1000),
            },
        )
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return JSONResponse(
            {
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "request_id": request.state.request_id,
                    "retryable": error.status in {429, 503},
                    "details": error.details,
                }
            },
            status_code=error.status,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse(
            {
                "error": {
                    "code": "FIELD_VALIDATION_FAILED",
                    "message": "Проверьте поля запроса.",
                    "request_id": request.state.request_id,
                    "retryable": False,
                    "field_errors": [
                        {"key": ".".join(map(str, e["loc"])), "code": e["type"]} for e in error.errors()
                    ],
                }
            },
            status_code=422,
        )

    @app.get("/health/live")
    async def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready():
        try:
            async with app.state.session_factory() as db:
                await db.execute(
                    text("SELECT 1 FROM inventory.alembic_version LIMIT 1")
                    if not db.bind.dialect.name == "sqlite"
                    else text("SELECT 1")
                )
                processing = await processing_health(db)
            ready = processing["recognition_available"]
            return JSONResponse(
                {"status": "ready" if ready else "degraded", **processing},
                status_code=200 if ready else 503,
            )
        except Exception:
            return JSONResponse({"status": "unavailable"}, status_code=503)

    @app.get("/api/v1/processing-status")
    async def processing_status(user=Depends(current_user), db=db_session):
        return await processing_health(db)

    @app.get("/api/v1/capabilities")
    async def capabilities(user=Depends(current_user), db=db_session):
        _, settings = await effective_settings(db)
        slot = await db.get(GPUSlot, 1)
        queue = await db.get(Control, "queue:default")
        return {
            "schemas": ["review.v1", "extraction.v1", "command.v1", "collage.v1", "export.v1"],
            "media_types": ["image/jpeg", "image/png", "image/webp", "audio/wav"],
            "max_pending_ai_tasks": settings["queue.max_pending_total"],
            "ai_processing_paused": bool(queue and queue.value.get("paused"))
            or bool(slot and slot.state == "quarantined"),
            "media_limits": {
                "max_images": settings["media.max_images_per_task"],
                "max_file_bytes": settings["media.max_file_bytes"],
                "max_task_bytes": settings["media.max_task_bytes"],
                "max_audio_seconds": settings["media.max_audio_seconds"],
            },
            "media_preprocessing": {
                "client_preprocessing_supported": True,
                "server_revalidates": True,
                "recommended_upload": {
                    "image_max_side": 1600,
                    "jpeg_quality": 80,
                    "audio_format": "wav_pcm16",
                    "audio_sample_rate": 16000,
                    "audio_channels": 1,
                },
                "inference": {
                    "max_images": 1,
                    "max_side": config.local_image_max_side,
                    "max_bytes": config.local_image_max_bytes,
                    "multiple_images": "collage",
                },
            },
            "audio_inference": config.audio_configured,
            "controls": [
                "entity_picker",
                "location_picker",
                "segmented_control",
                "number_stepper",
                "decimal_input",
                "unit_select",
                "date_picker",
                "month_picker",
                "checkbox",
                "switch",
                "chips_select",
                "candidate_cards",
                "photo_region",
                "text_input",
                "readonly_summary",
            ],
            "polling": True,
            "push": False,
            "external_enabled_by_default": False,
            "cloud_configured": config.cloud_configured,
            "external_enabled": settings["routing.external_enabled"],
        }

    for router in (
        auth.router,
        catalog.router,
        item_fields.router,
        media.router,
        tasks.router,
        search.router,
        notifications.router,
        admin.router,
        maintenance.router,
    ):
        app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
