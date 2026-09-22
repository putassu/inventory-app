import asyncio
import hashlib
import logging
import time
from contextlib import asynccontextmanager
from datetime import timedelta

from pydantic import ValidationError
from sqlalchemy import func, select

from app.application.extraction import normalize_extraction
from app.application.proposals import create_proposal, rebuild
from app.application.search import candidate_card, candidates
from app.application.settings import effective_settings
from app.config import get_config
from app.db.models import (
    Attempt,
    Balance,
    Binding,
    Control,
    Cooldown,
    Item,
    Location,
    Lot,
    Media,
    ModelDeployment,
    Task,
)
from app.db.session import workspace_access
from app.domain.common import uid, utcnow
from app.domain.errors import DomainError, require
from app.domain.rules import effective_privacy, transition
from app.domain.schemas import Gatekeeper
from app.infrastructure.audio import LocalAudioAdapter, join_transcripts, segments
from app.infrastructure.gpu import gpu_session
from app.infrastructure.logging import logged_job
from app.infrastructure.media import build_collage, decode_image, jpeg
from app.infrastructure.models import CloudAdapter, LocalAdapter, prompt, prompt_revision
from app.infrastructure.storage import Storage


@logged_job()
async def prepare_task(ctx, task_id):
    factory = ctx["factory"]
    async with factory() as db, db.begin():
        task = await db.get(Task, task_id)
        if not task or task.status != "accepted":
            return
        await workspace_access(db, task.workspace_id, task.created_by, write=True, lock=True)
        await db.refresh(task)
        if task.status != "accepted":
            return
        transition(task, "preparing", "media")
        task.fencing_token += 1
        token = task.fencing_token
        task.lease_until = utcnow() + timedelta(seconds=task.config_snapshot["timeout.lease_seconds"])
        media = [await db.get(Media, media_id) for media_id in task.media_ids]
        workspace_id, settings = task.workspace_id, task.config_snapshot
        revision = task.config_revision
    storage = ctx.get("storage") or Storage()
    assets = []
    try:
        sources = []
        for original in media:
            data = await storage.read(original.object_key)
            image, _ = await asyncio.to_thread(
                decode_image,
                data,
                settings["media.max_decoded_pixels"],
                settings.get("media.normalized_max_side", 1600),
            )
            for kind, bound in (
                ("normalized", settings.get("media.normalized_max_side", 1600)),
                ("thumbnail", settings.get("media.thumbnail_max_side", 256)),
            ):
                copy = image.copy()
                copy.thumbnail((bound, bound))
                payload = await asyncio.to_thread(jpeg, copy, settings.get("media.jpeg_quality", 80))
                if kind == "normalized":
                    sources.append((original.id, payload))
                mid = uid()
                key = f"{workspace_id}/{mid}/{kind}.jpg"
                await storage.put(key, payload, "image/jpeg")
                assets.append(
                    Media(
                        id=mid,
                        workspace_id=workspace_id,
                        object_key=key,
                        sha256=hashlib.sha256(payload).hexdigest(),
                        mime="image/jpeg",
                        size_bytes=len(payload),
                        width=copy.width,
                        height=copy.height,
                        kind=kind,
                        privacy_policy=original.privacy_policy,
                        manifest={"source_media_id": original.id},
                    )
                )
        collage_id = None
        if sources:
            payload, manifest = await asyncio.to_thread(build_collage, sources, settings, revision)
            collage_id = uid()
            key = f"{workspace_id}/{collage_id}/collage.jpg"
            await storage.put(key, payload, "image/jpeg")
            assets.append(
                Media(
                    id=collage_id,
                    workspace_id=workspace_id,
                    object_key=key,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    mime="image/jpeg",
                    size_bytes=len(payload),
                    width=manifest["canvas_width"],
                    height=manifest["canvas_height"],
                    kind="collage",
                    privacy_policy="local_only"
                    if any(m.privacy_policy == "local_only" for m in media)
                    else "cloud_allowed",
                    manifest=manifest,
                )
            )
        async with factory() as db, db.begin():
            task = await db.get(Task, task_id)
            await workspace_access(db, task.workspace_id, task.created_by, write=True, lock=True)
            await db.refresh(task)
            if task.status != "preparing" or task.fencing_token != token:
                return
            for asset in assets:
                db.add(asset)
            await db.flush()
            for asset in assets:
                db.add(
                    Binding(
                        workspace_id=workspace_id,
                        media_id=asset.id,
                        entity_type="task",
                        entity_id=task_id,
                        role=asset.kind,
                    )
                )
            task.result = {"collage_media_id": collage_id, "warnings": []}
            config = get_config()
            audio_ready = bool(
                config.local_audio_url
                and config.local_audio_model
                and config.local_audio_trusted
                and config.local_audio_verified
            )
            if task.audio_media_id and not audio_ready:
                task.result = {
                    **task.result,
                    "audio_unprocessed": True,
                    "warnings": [
                        "UNSUPPORTED_AUDIO: запись сохранена. Текущая локальная модель не поддерживает голос; проверьте действие вручную."
                    ],
                }
            transition(task, "queued", "audio" if task.audio_media_id and audio_ready else "privacy_asr")
            task.lease_until = None
    except Exception as error:
        await fail_to_review(
            factory,
            task_id,
            token,
            error.code if isinstance(error, DomainError) else "MEDIA_PREPARATION_FAILED",
        )


async def current_privacy(db, task, decision="uncertain", candidate_ids=()):
    _, settings = await effective_settings(db)
    control = await db.get(Control, "settings")
    policies = [task.requested_privacy]
    for media_id in [*task.media_ids, *([task.audio_media_id] if task.audio_media_id else [])]:
        media = await db.get(Media, media_id)
        policies.append(media.privacy_policy if media and media.state == "uploaded" else "local_only")
    location_ids = {task.context["location_id"]} if task.context.get("location_id") else set()
    for item_id in {*candidate_ids, *([task.context["item_id"]] if task.context.get("item_id") else [])}:
        item = await db.get(Item, item_id)
        policies.append(
            item.privacy_policy
            if item and item.workspace_id == task.workspace_id and item.lifecycle == "active"
            else "local_only"
        )
        if item:
            lots = (
                await db.scalars(
                    select(Lot).where(Lot.workspace_id == task.workspace_id, Lot.item_id == item_id)
                )
            ).all()
            policies.extend(lot.privacy_policy for lot in lots)
            location_ids.update(
                (
                    await db.scalars(
                        select(Balance.location_id).where(
                            Balance.workspace_id == task.workspace_id,
                            Balance.lot_id.in_([lot.id for lot in lots]),
                        )
                    )
                ).all()
            )
    for location_id in location_ids:
        while location_id:
            location = await db.get(Location, location_id)
            if not location or location.workspace_id != task.workspace_id:
                policies.append("local_only")
                break
            policies.append(location.default_privacy_policy)
            location_id = location.parent_id
    return effective_privacy(
        *policies,
        external_enabled=settings["routing.external_enabled"] and not control.value.get("external_blocked"),
        decision=decision,
    )


async def extraction_context(db, task, *, egress=False):
    gate = task.result.get("gatekeeper", {})
    transcript = task.result.get("transcript") or gate.get("transcription") or ""
    text = "\n".join(value for value in (task.input_text, transcript) if value)
    found = {}
    for term in [text, *[item["name"] for item in gate.get("items", [])]]:
        if not term:
            continue
        for item in await candidates(
            db, task.workspace_id, term, task.config_snapshot["search.final_candidates"]
        ):
            found[item.id] = item
    if task.context.get("item_id"):
        item = await db.get(Item, task.context["item_id"])
        if item and item.workspace_id == task.workspace_id and item.lifecycle == "active":
            found[item.id] = item
    cards = [
        await candidate_card(db, item)
        for item in list(found.values())[: task.config_snapshot["search.final_candidates"]]
    ]
    locations = (
        await db.scalars(
            select(Location).where(Location.workspace_id == task.workspace_id, Location.archived_at.is_(None))
        )
    ).all()
    if egress:
        by_id = {row.id: row for row in locations}

        def allowed_location(row):
            while row:
                if row.default_privacy_policy != "cloud_allowed":
                    return False
                row = by_id.get(row.parent_id)
            return True

        locations = [row for row in locations if allowed_location(row)]
    return {
        "text": text,
        "candidates": cards,
        "locations": [{"id": row.id, "name": row.name} for row in locations],
        "context": {k: task.context.get(k) for k in ("item_id", "location_id")},
    }


@asynccontextmanager
async def cloud_slot():
    yield (uid(), 0)


@logged_job()
async def run_ml_stage(ctx, task_id):
    factory = ctx["factory"]
    async with factory() as db:
        task = await db.get(Task, task_id)
        if not task or task.status != "queued":
            return
        settings, stage = task.config_snapshot, task.stage
    manager = cloud_slot() if stage == "cloud_extraction" else gpu_session(factory, task_id, settings)
    token = None
    started = None
    try:
        async with manager as reserved:
            if reserved is None:
                return
            async with factory() as db, db.begin():
                task = await db.get(Task, task_id)
                await workspace_access(db, task.workspace_id, task.created_by, write=True, lock=True)
                await db.refresh(task)
                if task.status != "queued":
                    return
                require(
                    task.prompt_revision == prompt_revision(),
                    "PROMPT_REVISION_UNAVAILABLE",
                    "Шаблон изменён: создайте явный повтор с новой конфигурацией.",
                )
                require(
                    task.attempt_count < settings["routing.max_total_attempts"],
                    "ATTEMPT_BUDGET",
                    "Бюджет распознавания исчерпан.",
                )
                total_seconds = settings["timeout.task_total_seconds"]
                require(
                    total_seconds is None or task.processing_seconds < total_seconds,
                    "PROCESSING_BUDGET",
                    "Бюджет времени исчерпан.",
                )
                attempt_query = (
                    select(func.count())
                    .select_from(Attempt)
                    .where(Attempt.task_id == task.id, Attempt.stage == stage)
                )
                segment_index = len(task.result.get("audio_parts", [])) if stage == "audio" else None
                if segment_index is not None:
                    attempt_query = attempt_query.where(
                        Attempt.diagnostics["segment_index"].as_integer() == segment_index
                    )
                stage_count = await db.scalar(attempt_query)
                require(
                    stage_count < settings["retry.max_attempts_per_stage"],
                    "STAGE_BUDGET",
                    "Бюджет стадии исчерпан.",
                )
                context = await extraction_context(db, task, egress=stage == "cloud_extraction")
                deployment_name = (
                    "cloud_primary"
                    if stage == "cloud_extraction"
                    else "local_audio"
                    if stage == "audio"
                    else "privacy_asr"
                    if stage == "privacy_asr"
                    else "local_vlm"
                )
                deployment = await db.scalar(
                    select(ModelDeployment).where(ModelDeployment.logical_name == deployment_name)
                )
                require(
                    deployment and deployment.enabled and not deployment.maintenance,
                    "MODEL_DISABLED",
                    "Модель отключена.",
                )
                saved_model = settings.get("model_deployments", {}).get(deployment_name)
                require(
                    saved_model
                    and saved_model["model_id"] == deployment.actual_model_id
                    and saved_model["endpoint_ref"] == deployment.endpoint_ref
                    and saved_model["trust_domain"] == deployment.trust_domain,
                    "MODEL_REVISION_UNAVAILABLE",
                    "Маршрут модели изменён: создайте явный повтор с новой конфигурацией.",
                )
                if stage == "cloud_extraction":
                    require(
                        await current_privacy(
                            db, task, "non_sensitive", [c["item_id"] for c in context["candidates"]]
                        )
                        == "cloud_allowed",
                        "POLICY_RESTRICTED",
                        "Внешняя передача запрещена.",
                        403,
                    )
                    require(
                        task.external_calls < settings["routing.max_external_calls"],
                        "EXTERNAL_CALL_BUDGET",
                        "Бюджет внешних вызовов исчерпан.",
                    )
                    # Если задан денежный лимит, неизвестную цену нельзя считать нулевой.
                    require(
                        settings["routing.max_external_cost_per_task"] is None,
                        "UNKNOWN_MODEL_PRICE",
                        "Для денежного лимита нужна проверенная стоимость deployment.",
                    )
                    cooldown = await db.scalar(
                        select(Cooldown).where(Cooldown.quota_key == deployment.actual_model_id)
                    )
                    from app.application.auth import aware

                    require(
                        not cooldown or cooldown.reset_at and aware(cooldown.reset_at) <= utcnow(),
                        "MODEL_COOLDOWN",
                        "Внешняя квота временно недоступна.",
                    )
                    task.external_calls += 1
                transition(task, "running", stage)
                task.attempt_count += 1
                task.fencing_token += 1
                token = task.fencing_token
                task.lease_owner = reserved[0]
                task.lease_until = utcnow() + timedelta(
                    seconds=settings["timeout.local_inference_seconds"] + 30
                )
                attempt = Attempt(
                    id=uid(),
                    workspace_id=task.workspace_id,
                    task_id=task.id,
                    fencing_token=token,
                    stage=stage,
                    model_id=deployment.actual_model_id,
                    trust_domain=deployment.trust_domain,
                    diagnostics={"segment_index": segment_index} if segment_index is not None else {},
                )
                db.add(attempt)
                attempt_id, model_id = attempt.id, deployment.actual_model_id
                collage = (
                    await db.get(Media, task.result["collage_media_id"])
                    if task.result.get("collage_media_id")
                    else None
                )
                audio = await db.get(Media, task.audio_media_id) if task.audio_media_id else None
                saved_result = dict(task.result)
                snapshot_context = dict(task.context)
            storage = ctx.get("storage") or Storage()
            image = await storage.read(collage.object_key) if collage else None
            if collage:
                context["collage_manifest"] = collage.manifest
            started = time.monotonic()
            if stage == "audio":
                audio_data = await storage.read(audio.object_key)
                # Каждая часть — отдельная попытка и отдельный checkpoint.
                pieces = list(await asyncio.to_thread(lambda: list(segments(audio_data))))
                offset = len(saved_result.get("audio_parts", []))
                require(offset < len(pieces), "EMPTY_AUDIO", "В записи нет звука.", 422)
                result = await (ctx.get("audio_adapter") or LocalAudioAdapter()).infer(
                    pieces[offset], settings["timeout.local_inference_seconds"], model=model_id
                )
                audio_complete = offset + 1 >= len(pieces)
            elif stage == "privacy_asr":
                result = await (ctx.get("local_adapter") or LocalAdapter()).infer(
                    prompt("gemma_e4b_gatekeeper.txt"), context, settings, image=image, model=model_id
                )
                result = Gatekeeper.model_validate(result).model_dump(mode="json")
            else:
                system = prompt("gemma_core_vlm.j2", saved_result.get("gatekeeper"))
                if stage == "cloud_extraction":
                    # Последняя проверка прямо перед внешним HTTP, после подготовки payload.
                    async with factory() as db:
                        task = await db.get(Task, task_id)
                        require(
                            task.status == "running"
                            and task.fencing_token == token
                            and await current_privacy(
                                db, task, "non_sensitive", [c["item_id"] for c in context["candidates"]]
                            )
                            == "cloud_allowed",
                            "POLICY_RESTRICTED",
                            "Передача отменена действующей политикой.",
                            403,
                        )
                    result = await (ctx.get("cloud_adapter") or CloudAdapter()).infer(
                        system,
                        context,
                        settings,
                        image=image,
                        policy="cloud_allowed",
                        external_enabled=True,
                        model=model_id,
                    )
                else:
                    result = await (ctx.get("local_adapter") or LocalAdapter()).infer(
                        system, context, settings, image=image, model=model_id
                    )
                result = normalize_extraction(
                    result,
                    context["candidates"],
                    context["locations"],
                    snapshot_context,
                    context["text"],
                    collage_manifest=context.get("collage_manifest"),
                )
            elapsed = time.monotonic() - started
            logging.getLogger("inventory").info(
                "model.response",
                extra={
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "stage": stage,
                    "duration_ms": round(elapsed * 1000),
                },
            )
            async with factory() as db, db.begin():
                task = await db.get(Task, task_id)
                await workspace_access(db, task.workspace_id, task.created_by, write=True, lock=True)
                await db.refresh(task)
                attempt = await db.get(Attempt, attempt_id)
                attempt.completed_at = utcnow()
                attempt.diagnostics = {
                    **attempt.diagnostics,
                    "wall_seconds": round(elapsed, 3),
                    "image_count": int(image is not None and stage != "audio"),
                }
                if task.status != "running" or task.fencing_token != token:
                    attempt.error_code = "STALE_RESULT"
                    return
                from decimal import Decimal

                task.processing_seconds += Decimal(str(round(elapsed, 3)))
                task.lease_owner = task.lease_until = None
                if stage == "audio":
                    parts = [*task.result.get("audio_parts", []), result]
                    task.result = {**task.result, "audio_parts": parts, "transcript": join_transcripts(parts)}
                    transition(task, "queued", "privacy_asr" if audio_complete else "audio")
                elif stage == "privacy_asr":
                    task.result = {**task.result, "gatekeeper": result}
                    decision = (
                        "non_sensitive"
                        if result["is_safe"] is True
                        and not result["sensitive_flags"]
                        and not any(i["category"] == "DOCUMENTS" for i in result["items"])
                        else "sensitive"
                        if result["is_safe"] is False
                        else "uncertain"
                    )
                    task.effective_privacy = await current_privacy(db, task, decision)
                    cloud = (
                        task.effective_privacy == "cloud_allowed"
                        and settings["routing.strategy"] == "cloud_preferred"
                    )
                    transition(task, "queued", "cloud_extraction" if cloud else "extraction")
                elif result.read_only_query:
                    rows = await candidates(db, task.workspace_id, result.read_only_query)
                    task.result = {"items": [await candidate_card(db, item) for item in rows]}
                    transition(task, "succeeded", "search_ready")
                    task.completed_at = utcnow()
                else:
                    warnings = [*task.result.get("warnings", []), *result.quality_issues]
                    proposal = await create_proposal(
                        db,
                        task.workspace_id,
                        task.created_by,
                        [a.model_dump(mode="json") for a in result.actions],
                        task=task,
                        source="ai",
                        warnings=warnings,
                    )
                    if result.ambiguity:
                        # Неоднозначное действие должно быть явно выбрано ручной формой.
                        await rebuild(
                            db,
                            proposal,
                            increment=True,
                            issues=[
                                {
                                    "code": "INTENT_REQUIRED",
                                    "message": "Выберите действие вручную: ввод содержит отрицание или намерение.",
                                }
                            ],
                        )
    except (DomainError, ValidationError) as error:
        code = error.code if isinstance(error, DomainError) else "INVALID_MODEL_JSON"
        await handle_failure(
            factory, task_id, token, code, error, stage, elapsed=time.monotonic() - started if started else 0
        )
    except Exception:
        await fail_to_review(factory, task_id, token, "MODEL_PROCESSING_FAILED")


async def handle_failure(factory, task_id, token, code, error, stage, elapsed=0):
    logging.getLogger("inventory").warning(
        "stage.failed",
        extra={"task_id": task_id, "stage": stage, "error_code": code, "duration_ms": round(elapsed * 1000)},
    )
    async with factory() as db, db.begin():
        task = await db.get(Task, task_id)
        if not task:
            return
        await workspace_access(db, task.workspace_id, task.created_by, write=True, lock=True)
        await db.refresh(task)
        if task.status not in {"running", "queued"} or token is not None and task.fencing_token != token:
            return
        attempts = (
            await db.scalars(
                select(Attempt).where(Attempt.task_id == task_id, Attempt.fencing_token == token)
            )
        ).all()
        for attempt in attempts:
            attempt.error_code, attempt.completed_at = code, utcnow()
            attempt.diagnostics = {**attempt.diagnostics, "wall_seconds": round(elapsed, 3)}
        from decimal import Decimal

        task.processing_seconds += Decimal(str(round(elapsed, 3)))
        task.error_code = code
        settings = task.config_snapshot
        if stage == "cloud_extraction" and code in {"RATE_LIMIT", "DAILY_QUOTA", "MODEL_CREDENTIALS"}:
            # Ограничение относится к фактическому вызову, даже если deployment уже изменён.
            for model in {attempt.model_id for attempt in attempts if attempt.stage == stage}:
                cooldown = await db.scalar(select(Cooldown).where(Cooldown.quota_key == model))
                if cooldown is None:
                    cooldown = Cooldown(quota_key=model, reason=code)
                    db.add(cooldown)
                cooldown.reason, cooldown.reset_at = code, getattr(error, "reset_at", None)
        can_retry = task.status == "running" and task.attempt_count < settings["routing.max_total_attempts"]
        if (
            can_retry
            and not getattr(error, "physical_unknown", False)
            and code in {"INVALID_MODEL_JSON", "MODEL_UNAVAILABLE", "CLOUD_CONNECTION", "RATE_LIMIT"}
        ):
            transition(task, "retry_wait")
            task.next_attempt_at = getattr(error, "reset_at", None) or utcnow() + timedelta(
                seconds=settings["retry.base_delay_seconds"] * 2 ** (task.attempt_count - 1)
            )
            return
        if (
            can_retry
            and stage == "extraction"
            and task.effective_privacy == "cloud_allowed"
            and code not in {"MODEL_REFUSAL", "POLICY_RESTRICTED"}
        ):
            if await current_privacy(db, task, "non_sensitive") == "cloud_allowed":
                transition(task, "queued", "cloud_extraction")
                return
    await fail_to_review(factory, task_id, token, code)


async def fail_to_review(factory, task_id, token, code):
    async with factory() as db, db.begin():
        task = await db.get(Task, task_id)
        if not task:
            return
        await workspace_access(db, task.workspace_id, task.created_by, write=True, lock=True)
        await db.refresh(task)
        if (
            task.status not in {"preparing", "running", "queued", "retry_wait"}
            or token is not None
            and task.fencing_token != token
        ):
            return
        if task.status in {"queued", "retry_wait"}:
            # Технический отказ до инференса переводится в подготовку ручного предложения.
            task.status = "preparing"
            task.status_version += 1
        task.error_code = code
        task.effective_privacy = "local_only"
        await create_proposal(
            db,
            task.workspace_id,
            task.created_by,
            [
                {
                    "type": "receive_stock",
                    "values": {
                        "tracking_mode": "untracked",
                        "quantity_state": "not_applicable",
                        "location_id": task.context.get("location_id"),
                    },
                }
            ],
            task=task,
            source="manual",
            warnings=[
                code
                + ": распознавание не завершено. Фото и запись сохранены; заполните форму вручную. Задача ничего не изменила в учёте."
            ],
        )
