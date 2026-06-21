# Структура базы данных

В проекте используется реляционная СУБД PostgreSQL 16 (с поддержкой расширений для JSONB и UUID). 
Модели описаны через SQLAlchemy 2.0.

## 🗂 Таблицы

### `users`
Хранит профили пользователей, их тарифные планы и учетные данные.
- `id` (UUID, Primary Key)
- `email` (String) — Уникальный email пользователя.
- `hashed_password` (String) — Хэш пароля.
- `tier` (Enum: `UserTier`) — Уровень подписки (`FREE`, `STANDARD`, `PREMIUM`). Влияет на лимиты.
- `litellm_api_key` (String, nullable) — Уникальный ключ для шлюза LiteLLM.
- `is_active` (Boolean)
- `created_at`, `updated_at` (Timestamp)
- `tier_expired_at` (Timestamp, nullable) — Дата истечения платной подписки. Если дата в прошлом, бэкенд делает `lazy-downgrade` до `FREE`.
- `litellm_key_expired_at` (Timestamp, nullable) — Срок жизни LiteLLM ключа.
- `last_login_ip`, `last_login_dt` — Логирование последнего входа.
- `settings` (JSONB) — Вложенные настройки уведомлений, выбор моделей и т.д.

### `locations`
Хранит иерархическое дерево мест хранения пользователя (паттерн Adjacency List).
- `id` (UUID, Primary Key)
- `user_id` (UUID, Foreign Key) — Привязка к пользователю.
- `parent_location_id` (UUID, Foreign Key, nullable) — Ссылка на эту же таблицу (рекурсия). Null = корневая локация.
- `name` (String) — Название ("Шкаф", "Полка 2").
- `description` (String, nullable)
- `created_at`, `updated_at` (Timestamp)
- *Связи*: `items` (One-to-Many).

### `items`
Основная таблица инвентаря.
- `id` (UUID, Primary Key)
- `user_id` (UUID, Foreign Key)
- `location_id` (UUID, Foreign Key, nullable) — Если Null, вещь "без места" (или в корзине).
- `group_id` (UUID, nullable) — Идентификатор "умной группы" для объединения одинаковых предметов в разных локациях.
- `name` (String) — Название вещи.
- `quantity` (Numeric, nullable) — Остаток (может быть дробным).
- `unit_of_measure` (String, nullable) — Штуки, литры, упаковки.
- `primary_category` (Enum: `PrimaryCategory`) — Классификация (Медикаменты, Одежда, Техника и т.д.).
- `tags`, `synonyms` (ARRAY of String) — Массивы для гибридного поиска Qdrant. Синонимы пополняются автоматически при обучении (HITL).
- `generated_desc` (Text) — LLM-сгенерированное описание для векторизации.
- `attributes` (JSONB) — Специфические поля (например, `{"expiry_date": "2027-01-01", "remind_at": "..."}`).
- `status` (Enum: `ItemStatus`) — Текущий статус вещи (`queued`, `processing`, `user_action_required`, `completed`, `depleted`).
- `created_at`, `updated_at` (Timestamp)
- `archived_at` (Timestamp, nullable) — Soft Delete метка.

### `item_media`
Медиафайлы (фото и аудио), привязанные к предметам инвентаря.
- `id` (UUID, Primary Key)
- `item_id` (UUID, Foreign Key) — Каскадное удаление.
- `media_type` (Enum: `MediaType`) — `photo` или `audio`.
- `original_url`, `optimized_url`, `thumbnail_url` (String) — Ссылки на S3 (MinIO).
- `is_primary` (Boolean) — Основное фото карточки.

### `tasks`
Хранение состояний асинхронных ML-пайплайнов (LangGraph).
- `id` (UUID, Primary Key)
- `user_id` (UUID, Foreign Key)
- `status` (Enum: `TaskStatus`) — Статус процесса.
- `photo_urls`, `audio_url` (ARRAY of String) — Исходные медиафайлы S3.
- `is_safe` (Boolean) — Результат проверки Gatekeeper-ом на наличие приватных данных.
- `transcription` (Text, nullable) — Результат ASR (голос в текст).
- `suggested_json` (JSONB) — Временный слепок того, что распознала LLM/VLM, используемый в HITL.
- `confidence_score` (Numeric) — Степень уверенности модели (0.0 - 1.0).
- `created_at`, `updated_at` (Timestamp)

### `system_settings`
Глобальные системные настройки.
- `key` (String, Primary Key)
- `value` (JSONB)
- `description` (String)

---

## 🧬 Перечисления (Enums)

- `UserTier`: `FREE`, `STANDARD`, `PREMIUM`.
- `ItemStatus`: `queued`, `processing`, `user_action_required`, `completed`, `depleted`.
- `PrimaryCategory`: `MEDICINES`, `DOCUMENTS`, `CLOTHES`, `TECH`, `FOOD`, `DISHES`, `COSMETICS`, `HOUSEHOLD`, `HOBBY`, `OTHER`.
- `LocationStatus`: `active`, `user_action_required`.
- `MediaType`: `photo`, `audio`.
- `TaskStatus`: Аналогично `ItemStatus`.
