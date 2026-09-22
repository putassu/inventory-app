"""Короткие структурированные события без содержимого запросов и ответов модели."""

import json
import logging
import time
from datetime import UTC, datetime
from functools import wraps

from app.config import get_config


class JsonFormatter(logging.Formatter):
    def format(self, record):
        event = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        for key in (
            "request_id",
            "task_id",
            "confirmation_id",
            "job_id",
            "attempt_id",
            "stage",
            "job",
            "status",
            "duration_ms",
            "error_code",
            "error_type",
        ):
            if hasattr(record, key):
                event[key] = getattr(record, key)
        return json.dumps(event, ensure_ascii=False)


def configure_logging():
    logger = logging.getLogger("inventory")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(get_config().log_level)
    logger.propagate = False


def logged_job(id_field="task_id"):
    def decorate(function):
        @wraps(function)
        async def wrapped(ctx, entity_id, *args, **kwargs):
            logger = logging.getLogger("inventory")
            fields = {id_field: entity_id, "job": function.__name__}
            started = time.monotonic()
            logger.info("job.started", extra=fields)
            try:
                result = await function(ctx, entity_id, *args, **kwargs)
            except Exception as error:
                logger.error(
                    "job.failed",
                    extra={
                        **fields,
                        "duration_ms": round((time.monotonic() - started) * 1000),
                        "error_type": type(error).__name__,
                    },
                )
                raise
            logger.info(
                "job.finished", extra={**fields, "duration_ms": round((time.monotonic() - started) * 1000)}
            )
            return result

        return wrapped

    return decorate
