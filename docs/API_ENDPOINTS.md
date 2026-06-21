# Спецификация REST API

Все эндпоинты (кроме публичных из `/auth`) требуют передачи JWT-токена в заголовке запроса:
`Authorization: Bearer <token>`

Приложение построено на базе FastAPI (Python) и работает локально по адресу `http://localhost:9005`. Базовые префиксы роутов: `/auth`, `/inventory` и `/admin`.

---

## 🔐 Аутентификация (`/auth`)

### `POST /auth/register`
**Описание**: Регистрация нового пользователя.
- **Вход (JSON)**:
  - `email` (string, обязательное)
  - `password` (string, обязательное)
- **Действие**: Создает запись в таблице `users`, присваивает тариф `FREE`.
- **Выход (201 Created)**: JSON с данными созданного пользователя: `{"id": "UUID", "email": "...", "tier": "FREE", "is_active": true}`

### `POST /auth/login`
**Описание**: Аутентификация пользователя и получение JWT-токена доступа.
- **Вход (application/x-www-form-urlencoded)**: 
  - `username` (string, ваш email)
  - `password` (string)
- **Выход (200 OK)**: `{"access_token": "...", "token_type": "bearer", "user": { "id": "...", "tier": "FREE" }}`
- **Действие**: Обновляет `last_login_ip` и `last_login_dt` в базе данных.

### `GET /auth/me/settings`
**Описание**: Получение пользовательских настроек (System Settings / LLM / Notifications).
- **Выход (200 OK)**: JSON-объект `settings` (тип `JSONB` из БД), например: 
  `{"audit_reminder_days": 30, "local_llm_only": false, "timezone": "UTC"}`

### `PUT /auth/me/settings`
**Описание**: Обновление настроек пользователя.
- **Вход (JSON)**: Произвольный объект настроек. Ключи смерживаются с текущими.
- **Выход (200 OK)**: Обновленный объект настроек.

---

## 📦 Инвентарь: Предметы (`/inventory/items`)

### `GET /inventory/items`
**Описание**: Получение списка вещей пользователя.
- **Query параметры**:
  - `location_id` (UUID, опц): Фильтрация по конкретной локации.
  - `include_archived` (bool, по умолчанию `false`): Включить удаленные (soft-deleted) или израсходованные предметы.
- **Выход (200 OK)**: Массив объектов `ItemResponse` (включая связанные медиа, теги, синонимы, атрибуты).

### `GET /inventory/items/{id}`
**Описание**: Получить детальную информацию об одном предмете.
- **Path параметры**: `item_id` (UUID)
- **Выход (200 OK)**: Объект `ItemResponse` с детальными метаданными и `media` массивом.
- **Ошибки**: `404 Not Found`.

### `POST /inventory/items`
**Описание**: Добавление предмета "вручную" (без участия ML-модели).
- **Вход (JSON `ItemCreate`)**: 
  - `location_id` (UUID, опц)
  - `name` (string)
  - `quantity` (decimal, опц)
  - `unit_of_measure` (string, опц)
  - `primary_category` (string Enum `PrimaryCategory`)
  - `tags` (List[string])
  - `attributes` (Dict)
- **Выход (201 Created)**: Созданный объект `ItemResponse`.

### `PUT /inventory/items/{id}`
**Описание**: Обновление метаданных предмета (Имя, Категории, Теги, Атрибуты).
- **Вход (JSON `ItemUpdateGeneric`)**: 
  - `name`, `tags`, `attributes` и др.
- **Выход (200 OK)**: Обновленный `ItemResponse`.

### `PUT /inventory/items/{id}/adjust`
**Описание**: Быстрое изменение количества (quantity) предмета.
- **Query параметр**: `amount` (decimal). Может быть положительным (приход) или отрицательным (списание/расход).
- **Выход (200 OK)**: Обновленный `ItemResponse`.
- **Действие**: Если quantity падает до `<= 0`, предмету автоматически проставляется статус `depleted`.

### `PUT /inventory/items/{id}/move`
**Описание**: Явное перемещение предмета в другую локацию.
- **Query параметр**: `new_location_id` (UUID). Если null, переносится в "корень" (без места).
- **Выход (200 OK)**: Успешный `ItemResponse`.

### `DELETE /inventory/items/{id}`
**Описание**: Удаление предмета.
- **Выход (204 No Content)**.
- **Действие**: Это Soft-Delete. В базе проставляется метка `archived_at = NOW()`. Реальное удаление происходит через сборщик мусора.

---

## 📍 Инвентарь: Локации (`/inventory/locations`)

### `GET /inventory/locations`
**Описание**: Получение всех локаций пользователя. Возвращает плоский список или дерево (зависит от логики на клиенте), вложенность восстанавливается через `parent_location_id`.
- **Выход (200 OK)**: Массив `LocationResponse` (или `LocationTreeResponse`).

### `POST /inventory/locations`
**Описание**: Создание новой локации.
- **Вход (JSON `LocationCreate`)**: 
  - `name` (string, обязательно)
  - `parent_location_id` (UUID, опц)
  - `description` (string, опц)
- **Выход (201 Created)**: Созданный объект `LocationResponse`.

### `PUT /inventory/locations/{id}/move`
**Описание**: Перемещение всей локации (контейнера) внутрь другой локации.
- **Вход (JSON)**: `{"new_parent_id": "UUID"}`
- **Действие**: Изменяет `parent_location_id`. Защита от циклических ссылок не даст положить родителя внутрь его собственного ребенка.
- **Выход (200 OK)**: Обновленный `LocationResponse`.

### `DELETE /inventory/locations/{id}`
**Описание**: Удаление локации.
- **Query параметры**:
  - `cascade` (bool, по умолчанию `false`): Если `false` — подлокации и вещи "всплывают" на уровень выше (к родителю удаленной). Если `true` — полное каскадное удаление.
  - `move_to` (UUID, опц): Работает если `cascade=true`. Все вложенные вещи можно принудительно эвакуировать в эту новую локацию перед удалением старой.
- **Выход (204 No Content)**.

---

## ⚡ ML-Пайплайн и Фоновые задачи (`/inventory/items/process` & `/inventory/tasks`)

### `POST /inventory/items/process`
**Описание**: Главный эндпоинт загрузки фотографий или аудио для распознавания через ML-модели.
- **Вход (multipart/form-data)**: 
  - `photos` (List[UploadFile]): от 1 до 3 фотографий.
  - `audio` (UploadFile, опц): WAV 16KHz моно.
  - `text_comment` (str, опц)
  - `local_only` (bool, опц): Принудительно использовать только Local Gemma.
- **Выход (200 OK)**: `{"task_id": "UUID"}`
- **Действие**: Файлы сохраняются в S3, в Redis/ARQ ставится асинхронная задача `process_media_task` (в очередь `default` или `bulk`).

### `GET /inventory/tasks/{task_id}`
**Описание**: Polling статуса асинхронной задачи.
- **Выход (200 OK)**: Объект `TaskStatusResponse`, содержащий `status` (например, `processing`, `user_action_required`, `completed`), `suggested_json` (что распознали нейросети) и массивы ссылок на извлеченные медиа.

### `POST /inventory/tasks/{task_id}/resolve`
**Описание**: Разрешение конфликта Human-in-the-Loop (если статус `user_action_required`).
- **Вход (JSON)**: `corrected_json` (полный объект вещи с исправлениями пользователя).
- **Выход (200 OK)**: Задача возобновляется.
- **Действие**: Ставит задачу `resume_task` в очередь `high_priority`.

---

## 🔍 Поиск (`/inventory/search`)

### `GET /inventory/search`
**Описание**: Текстовый поиск и автокомплит по БД.
- **Query параметр**: `query` (string) и опциональный `location_id`.
- **Выход (200 OK)**: `SearchGlobalResponse` со списками найденных Items и Locations. Ищет по `name`, `tags`, `synonyms` и `generated_desc`.

### `POST /inventory/search/multimodal`
**Описание**: Мультимодальный семантический RAG-поиск в векторной базе данных (Qdrant).
- **Вход (multipart/form-data)**: 
  - `text_query` (str, опц)
  - `image` (UploadFile, опц)
  - `audio` (UploadFile, опц)
- **Выход (200 OK)**: Массив `{"item": ItemResponse, "score": float}`.
- **Механика**: Векторизует медиа через эмбеддер (BGE-M3/VLM) и выполняет поиск по косинусному расстоянию (Cosine Similarity) с весами IDF. Возвращает Top-K совпадений.

---

## ⚙️ Административные / Системные (`/admin`)

### `GET /admin/users`
**Описание**: Получение списка всех пользователей.
- **Выход (200 OK)**: Массив `UserResponse` (email, tier, активность).

### `PUT /admin/users/{user_id}`
**Описание**: Изменение параметров пользователя (для админов).
- **Вход (JSON `UserUpdateAdmin`)**: `tier`, `is_active`, `is_superuser`.
- **Выход (200 OK)**: Обновленный юзер.

### `POST /admin/gc-run`
**Описание**: Ручной триггер сборщика мусора (Garbage Collector).
- **Действие**: Физически (Hard Delete) удаляет из Postgres и Qdrant все предметы со статусом `depleted` или `archived_at`, которые старше заданного в настройках времени (TTL).
- **Выход (200 OK)**: Очередь `cron_only` принимает задачу на немедленное выполнение.
