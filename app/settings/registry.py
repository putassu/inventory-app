"""Конечный реестр: неизвестный ключ не становится настройкой приложения."""

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation

from app.domain.errors import require


@dataclass(frozen=True)
class Setting:
    default: object
    type: str
    description_ru: str
    min: float | None = None
    max: float | None = None
    enum: tuple = ()
    nullable: bool = False
    apply_mode: str = "new_tasks"
    scope: str = "admin"
    sensitivity: str = "public"
    control: str = "number_stepper"
    editable: bool = True


def number(default, description, low=1, high=1000000, **kwargs):
    return Setting(default, "int", description, low, high, **kwargs)


def flag(default, description, **kwargs):
    return Setting(default, "bool", description, control="switch", **kwargs)


def choice(default, description, options, **kwargs):
    return Setting(default, "str", description, enum=tuple(options), control="segmented_control", **kwargs)


REGISTRY = {
    "routing.strategy": choice("local_first", "Порядок вызова моделей", ("local_first", "cloud_preferred")),
    "routing.external_enabled": flag(False, "Разрешить внешние модели", apply_mode="immediate"),
    "routing.local_model_ref": choice("local_vlm", "Локальная модель", ("local_vlm",)),
    "routing.privacy_asr_model_ref": choice("privacy_asr", "Первичная проверка", ("privacy_asr",)),
    "routing.cloud_primary_ref": choice(None, "Внешняя модель", ("cloud_primary",), nullable=True),
    "routing.fallback_chain": Setting(
        [],
        "list",
        "Дополнительная цепочка моделей пока не реализована",
        control="chips_select",
        editable=False,
    ),
    "routing.max_total_attempts": number(
        6, "Всего вызовов на задачу: до четырёх аудиочастей, проверка и извлечение", 1, 12
    ),
    "routing.max_external_calls": number(1, "Внешних вызовов на задачу", 0, 5),
    "routing.max_external_cost_per_task": Setting(
        None, "decimal", "Максимальная внешняя стоимость", 0, 100, nullable=True
    ),
    "quality.review_attention_threshold": Setting(
        None,
        "float",
        "Порог уверенности пока не откалиброван; числовая оценка не применяется",
        0,
        1,
        nullable=True,
        editable=False,
    ),
    "quality.fallback_threshold": Setting(
        None,
        "float",
        "Автоматический fallback по оценке уверенности пока не реализован",
        0,
        1,
        nullable=True,
        editable=False,
    ),
    "queue.default_weight": number(4, "Вес обычной очереди", 1, 20, apply_mode="immediate"),
    "queue.bulk_weight": number(1, "Вес массовой очереди", 1, 20, apply_mode="immediate"),
    "queue.bulk_after_outstanding": number(5, "Порог массовой очереди", 1, 1000, nullable=True),
    "queue.max_pending_per_user": number(500, "Лимит ожидающих задач", 1, 10000),
    "queue.local_gpu_slots": number(1, "Одновременных GPU-вызовов", 1, 1, apply_mode="requires_restart"),
    "queue.cpu_concurrency": number(2, "Одновременных CPU-задач", 1, 8, apply_mode="requires_restart"),
    "queue.cloud_concurrency": number(
        1, "Одновременных внешних вызовов", 1, 8, apply_mode="requires_restart"
    ),
    "queue.max_review_batch_size": number(20, "Размер общего подтверждения", 2, 50),
    "timeout.local_inference_seconds": number(300, "Таймаут локального вызова", 10, 3600),
    "timeout.cloud_inference_seconds": number(60, "Таймаут внешнего вызова", 5, 300),
    "timeout.task_total_seconds": number(1200, "Бюджет времени обработки", 30, 86400, nullable=True),
    "timeout.lease_seconds": number(60, "Срок аренды обработчика", 10, 600),
    "timeout.heartbeat_seconds": number(10, "Интервал heartbeat", 1, 120),
    "timeout.worker_hard_seconds": number(
        1500, "Предельное время arq job", 30, 86400, apply_mode="requires_restart"
    ),
    "retry.base_delay_seconds": number(2, "Начальная задержка повтора", 1, 300),
    "retry.max_delay_seconds": number(300, "Максимальная задержка", 1, 3600),
    "retry.max_attempts_per_stage": number(2, "Попыток на стадию", 1, 5),
    "media.max_images_per_task": number(3, "Фотографий на задачу", 1, 12),
    "media.max_file_bytes": number(15 * 1024 * 1024, "Размер одного файла", 1024, 100 * 1024 * 1024),
    "media.max_task_bytes": number(45 * 1024 * 1024, "Размер материалов задачи", 1024, 300 * 1024 * 1024),
    "media.max_decoded_pixels": number(30_000_000, "Пикселей после декодирования", 100000, 100_000_000),
    "media.max_audio_seconds": number(60, "Длительность записи", 1, 600),
    "media.normalized_max_side": number(1600, "Сторона сохраняемого изображения", 512, 2048),
    "media.thumbnail_max_side": number(256, "Сторона миниатюры", 64, 512),
    "media.jpeg_quality": number(80, "Качество JPEG", 40, 95),
    "collage.max_width": number(512, "Ширина изображения, дополнительно ограниченная runtime", 256, 4096),
    "collage.max_height": number(512, "Высота изображения, дополнительно ограниченная runtime", 256, 4096),
    "collage.min_tile_side": number(320, "Минимальная сторона области", 64, 1024),
    "collage.detail_passes_max": number(
        2, "Резерв для detail-pass; сейчас нечитаемые поля остаются unknown", 0, 4, editable=False
    ),
    "model.context_budget": number(8192, "Контекст модели", 2048, 32768),
    "model.output_budget": number(2048, "Размер ответа", 256, 8192),
    "search.dense_candidates": number(30, "Семантических кандидатов", 1, 200),
    "search.sparse_candidates": number(30, "Текстовых кандидатов", 1, 200),
    "search.final_candidates": number(8, "Кандидатов в форме", 1, 30),
    "search.embedding_batch_size": number(
        1, "Эмбеддинги обрабатываются по одному для экономии памяти", 1, 1, editable=False
    ),
    "polling.min_interval_ms": number(1000, "Минимальный интервал обновления", 500, 10000),
    "polling.max_interval_ms": number(10000, "Максимальный интервал обновления", 1000, 60000),
    "retention.orphan_upload_hours": number(24, "Хранение непривязанных файлов, часы", 1, 8760),
    "retention.task_input_days": number(30, "Хранение входного текста и аудио, дни", 1, 3650, nullable=True),
    "retention.review_draft_days": number(90, "Хранение незавершённых форм, дни", 1, 3650, nullable=True),
    "retention.source_photo_days": number(None, "Хранение непривязанных фото, дни", 1, 3650, nullable=True),
    "retention.archived_auto_purge_days": number(None, "Автоочистка архива, дни", 1, 3650, nullable=True),
    "retention.purge_grace_days": number(30, "Отсрочка окончательного удаления, дни", 1, 365),
    "retention.gc_interval_hours": number(24, "Интервал очистки, часы", 1, 720),
    "retention.debug_payload_days": number(
        1, "Хранение payload выключено: расширенная диагностика не поставляется", 1, 30, editable=False
    ),
    "diagnostics.level": choice(
        "normal",
        "Доступна обычная диагностика без исходных payload; расширенный режим не поставляется",
        ("normal",),
        editable=False,
    ),
    "diagnostics.store_payloads": flag(
        False, "Сохранение исходных payload недоступно в этой поставке", editable=False
    ),
    "diagnostics.payload_session_ttl_minutes": number(
        30, "Сессии расширенной диагностики не поставляются", 1, 120, editable=False
    ),
    "datasets.enabled": flag(
        False, "Отдельное сохранение датасетов не поставляется; примеры не копируются", editable=False
    ),
    "cache.enabled": flag(
        False, "Дополнительный кэш списков не поставляется; чтение выполняется из БД", editable=False
    ),
    "cache.ttl_seconds": number(30, "Кэш списков выключен, настройка TTL недоступна", 1, 300, editable=False),
    "locations.max_depth": number(6, "Глубина дерева мест", 1, 20),
    "expiry.month_expiry_policy": choice(
        None, "Интерпретация месяца срока", ("last_day", "first_day"), nullable=True
    ),
    "exports.ttl_hours": number(24, "Доступность экспорта, часы", 1, 168),
    "api.max_page_size": number(100, "Максимальный размер страницы", 10, 500),
    "api.max_poll_ids": number(100, "Задач в одном обновлении", 1, 500),
}

USER_REGISTRY = {
    "prefer_local": flag(True, "Предпочитать локальное распознавание", scope="user"),
    "default_privacy": choice(
        "local_only", "Приватность новых материалов", ("local_only", "cloud_allowed"), scope="user"
    ),
    "hide_sensitive_details": flag(True, "Скрывать детали уведомлений", scope="user"),
    "compact_view": flag(False, "Компактный каталог", scope="user"),
}


def defaults(registry=REGISTRY):
    return {key: definition.default for key, definition in registry.items()}


def schema(registry=REGISTRY):
    return [{"key": key, "group": key.split(".")[0], **asdict(value)} for key, value in registry.items()]


def validate_values(values, registry=REGISTRY):
    require(not (set(values) - set(registry)), "UNKNOWN_SETTING", "Неизвестный или защищённый параметр.", 422)
    for key, value in values.items():
        definition = registry[key]
        require(
            definition.editable or value == definition.default,
            "UNSUPPORTED_SETTING",
            definition.description_ru,
            422,
            key=key,
        )
        if value is None:
            require(definition.nullable, "INVALID_SETTING", "Параметр не может быть пустым.", 422, key=key)
            continue
        valid = {
            "int": type(value) is int,
            "bool": type(value) is bool,
            "str": isinstance(value, str),
            "float": type(value) in {float, int},
            "list": isinstance(value, list),
            "decimal": isinstance(value, str),
        }[definition.type]
        require(valid, "INVALID_SETTING", "Неверный тип параметра.", 422, key=key)
        if definition.enum:
            require(
                value in definition.enum, "INVALID_SETTING", "Значение отсутствует в списке.", 422, key=key
            )
        if definition.type in {"int", "float", "decimal"}:
            try:
                number = Decimal(str(value))
            except InvalidOperation:
                number = Decimal("NaN")
            require(
                number.is_finite()
                and (definition.min is None or number >= Decimal(str(definition.min)))
                and (definition.max is None or number <= Decimal(str(definition.max))),
                "INVALID_SETTING",
                "Значение вне допустимого диапазона.",
                422,
                key=key,
            )
    if registry is REGISTRY:
        require(
            values["timeout.heartbeat_seconds"] * 2 < values["timeout.lease_seconds"],
            "INVALID_SETTING",
            "Lease должен превышать два heartbeat.",
            422,
        )
        require(
            values["timeout.worker_hard_seconds"] > values["timeout.local_inference_seconds"] + 30,
            "INVALID_SETTING",
            "Предельное время worker должно иметь запас к вызову модели.",
            422,
        )
        require(
            values["model.output_budget"] + 1024 < values["model.context_budget"],
            "INVALID_SETTING",
            "Не хватает контекста для входа.",
            422,
        )
        require(
            values["polling.min_interval_ms"] <= values["polling.max_interval_ms"],
            "INVALID_SETTING",
            "Интервалы обновления несовместимы.",
            422,
        )
        require(
            values["media.max_file_bytes"] <= values["media.max_task_bytes"],
            "INVALID_SETTING",
            "Файл превышает лимит всей задачи.",
            422,
        )
        require(
            values["retry.base_delay_seconds"] <= values["retry.max_delay_seconds"],
            "INVALID_SETTING",
            "Задержки повторов несовместимы.",
            422,
        )
        require(
            set(values["routing.fallback_chain"]) <= {"local_vlm", "cloud_primary"},
            "INVALID_SETTING",
            "Модель не зарегистрирована.",
            422,
        )
    return values
