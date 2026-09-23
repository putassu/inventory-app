# Инвентаризатор — техническая документация

Версия документа: **1.0**, 21.09.2026. Область: фактически реализованный backend API v1, существующий базовый web-клиент, инфраструктура и обслуживание. Документ описывает текущий код, а не обещает реализацию всех пожеланий исходного AGENT.md. Новая полная спецификация интерфейса находится в [docs/FRONTEND_SPEC.md](docs/FRONTEND_SPEC.md).

В документации нет действующих секретов. Примеры UUID и названий синтетические. Для запроса к своей установке подставляются её адрес, access token, workspace и полученные от сервера идентификаторы.

## Содержание

1. [Назначение и инварианты](#purpose)
2. [Компоненты и потоки](#architecture)
3. [Установка и конфигурация](#installation)
4. [Предметная модель](#domain)
5. [Авторизация и приватность](#security)
6. [Общие правила HTTP](#http)
7. [Сценарии интеграции и ответы API](#flows)
8. [Задачи, состояния, прогресс и очереди](#tasks)
9. [Медиа и модели](#media)
10. [Поиск](#search)
11. [Напоминания](#reminders)
12. [Настройки и администрирование](#administration)
13. [Экспорт, удаление, backup/restore](#maintenance)
14. [Проверки и разработка](#testing)
15. [Диагностика и известные ограничения](#limitations)
16. [Все HTTP-операции](#api-reference)
17. [Все схемы тел HTTP-запросов](#request-reference)
18. [Все поля 18 предметных команд](#command-reference)
19. [Все параметры окружения](#env-reference)
20. [Все административные и пользовательские настройки](#settings-reference)
21. [Полный справочник 36 таблиц](#database-reference)
22. [Справочник кодов ошибок](#error-reference)

<a id="purpose"></a>
## 1. Назначение и инварианты

Приложение отвечает на вопросы «что есть», «где», «сколько» и «до какого срока». Карточка описывает вид вещи, партия — конкретное приобретение/срок/экземпляр, остаток — количество партии в месте. Инвентаризатор не является бухгалтерией, системой назначения лечения или автоматического заказа товаров.

Обязательные свойства:

1. Модель создаёт только недоверенное предложение. До явного confirm не меняются карточки, партии, остатки и предметная история.
2. Ручные и AI-операции используют одни схемы и один интерпретатор preview/apply.
3. Повтор подтверждения не создаёт вторую операцию; учёт меняется атомарно.
4. Количества не отрицательны. Неизвестное количество не равно нулю.
5. Перемещение сохраняет суммарный остаток в базовой единице.
6. Разные сроки, серийные номера и несовместимые партии не объединяются по похожему названию.
7. Local-only данные не передаются внешнему AI даже при ошибке, retry или диагностике.
8. Ожидание пользователя не удерживает GPU или транзакцию БД.
9. Устаревшая форма требует повторного просмотра актуальных данных.
10. Redis и Qdrant восстанавливаются из PostgreSQL; потеря этих сервисов не разрешает терять подтверждённый учёт.
11. Нулевой остаток не удаляет историю. Архивирование и физическое удаление — разные операции.
12. Любое обращение к scoped-сущности проверяет workspace; app-role администратора не заменяет членство в workspace.

Исходные требования и 80 сценариев: [AGENT.md](AGENT.md), [матрица приёмки](docs/ACCEPTANCE.md). Результаты реальных запусков и границы покрытия: [REFACTOR_REPORT.md](docs/REFACTOR_REPORT.md).

<a id="architecture"></a>
## 2. Компоненты и потоки

| Компонент | Ответственность | Источник |
|---|---|---|
| FastAPI | HTTP, аутентификация, валидация, workspace, создание задач и подтверждений | `app/main.py`, `app/api/` |
| Domain | Строгие команды, категории/единицы, сроки, количества, состояния | `app/domain/` |
| Application | Preview/apply, HITL, поиск, доступ, настройки, обслуживание | `app/application/` |
| PostgreSQL | Учёт, пользователи, задачи, snapshots, review, receipts, outbox, история | `app/db/`, `migrations/` |
| Redis/arq | Доставка фоновых заданий; не единственное место хранения очереди | `app/workers/queue.py` |
| CPU worker | Подготовка медиа, применение подтверждений, outbox, индексирование, maintenance | `CPUWorker` |
| ML worker | Последовательные стадии доверенного inference | `MLWorker`, `pipeline.py` |
| Cloud worker | Разрешённые внешние модельные вызовы; необязательный профиль | `CloudWorker` |
| Scheduler | Reconcile сохранённых заданий, напоминания и уборка | `Scheduler` |
| MinIO / Storage | Приватные исходники, производные изображения, временные экспорты | `infrastructure/storage.py` |
| Qdrant | Производный dense/sparse индекс; источником фактов остаётся SQL | `infrastructure/search.py` |

```mermaid
sequenceDiagram
    participant C as Клиент
    participant A as API
    participant P as PostgreSQL
    participant W as Workers
    participant M as Модель
    C->>A: Upload файлов; POST /tasks
    A->>P: Task + snapshot + bindings
    A-->>C: 202 task_id
    W->>P: Забрать сохранённую стадию
    W->>M: Ограниченный inference без открытой SQL-транзакции
    M-->>W: Недоверенные извлечённые факты
    W->>P: Proposal, revision, preview
    C->>A: GET review / PATCH правок
    C->>A: Явный confirm с revision и review_hash
    A->>P: Receipt + Confirmation + Outbox
    A-->>C: 202 confirmation_id, operation_id
    W->>P: Атомарно проверить версии и применить команду
    C->>A: GET confirmation
    A-->>C: applied или conflict/failed
```

Общий интерпретатор находится в `application/inventory.py`: сначала загружается состояние workspace, затем вычисляются изменения и preview; запись через `persist_state` происходит только при применении подтверждения. Блокировка workspace сериализует конкурирующие изменения. Неизменяемые `operation_entries` описывают before/after; отмена создаёт новую операцию, а не редактирует предыдущую.

### 2.1. Организация БД

Схема приложения — `inventory`, 36 прикладных таблиц. Alembic дополнительно ведёт `inventory.alembic_version`. Старая схема `public` не используется как источник текущего учёта и не удаляется автоматически. Большинство сущностей имеют UUID-строку `id`, `version`, UTC `created_at`/`updated_at`; scoped-сущности — `workspace_id`. Составные внешние ключи запрещают часть межworkspace-ссылок на уровне БД; права дополнительно проверяются сервисами.

| Группа | Таблицы |
|---|---|
| Доступ | users, workspaces, workspace_memberships, sessions, login_attempts, agreements |
| Учёт | items, lots, stock_balances, locations, item_aliases |
| Файлы | media_assets, media_bindings |
| Загрузка / inference | ingestion_batches, tasks, task_attempts, field_evidence |
| HITL | proposals, proposal_revisions, review_receipts, confirmations |
| История / доставка | operations, operation_entries, idempotency_keys, outbox_events |
| Эксплуатация | settings_revisions, runtime_controls, admin_audit, gpu_slots, model_deployments, model_cooldowns |
| Уведомления | reminder_rules, reminder_occurrences, inbox_notifications |
| Обслуживание | maintenance_jobs, deletion_tombstones |

Полный состав колонок, CHECK и уникальностей — [ниже](#database-reference). SQL-тип JSON в справочнике соответствует JSONB в PostgreSQL; SQLite используется в тестах с адаптацией схемы.

<a id="installation"></a>
## 3. Установка и конфигурация

Подробные команды первого запуска находятся в [README](README.md#быстрый-запуск-для-разработки), рабочий порядок обслуживания — в [RUNBOOK](docs/RUNBOOK.md). Требуются Python 3.12+, uv, Docker для сервисов; Node.js 22 нужен при сборке web. Образы и зависимости закреплены в Compose/lock-файлах. CUDA, Ollama и llama.cpp не устанавливаются основным Dockerfile.

### 3.1. Два независимых уровня настроек

**Окружение процесса:** `Config` читает `.env`, затем `.env.local`, затем переменные процесса с префиксом `INV_`. Это адреса сервисов, секреты, пределы deployment, пути, CORS/cookies, параметры доверенного аудио. Изменение окружения требует перезапуска соответствующего процесса. Секреты не возвращаются через административные настройки.

**Настройки в PostgreSQL:** конечный реестр пользовательских и административных ключей. Для задачи сохраняется config snapshot. Некоторые параметры применяются новым задачам, другие после перезапуска worker, аварийный запрет внешних вызовов проверяется непосредственно перед сетью. Справочник всех ключей приведён [ниже](#settings-reference).

Compose дополнительно читает `POSTGRES_PASSWORD` и `MINIO_PASSWORD` без префикса `INV_`, подставляя их во внутренние соединения. CLI bootstrap может читать `INV_BOOTSTRAP_PASSWORD` для неинтерактивного тестового запуска; обычная установка запрашивает пароль без эха. Эти значения нельзя помещать в web bundle или публиковать в выводе `docker compose config`.

### 3.2. Профили

| Профиль | Данные | Сеть / лимиты |
|---|---|---|
| Корневой Compose | БД inventory; named volumes postgres/media/qdrant/backups | API 8000, web 8080 на loopback; зависимости без host-портов; без cloud сумма лимитов 1600 MiB |
| Тестовые Compose-профили | В публичный коммит не включены | Используются только локально для проверок |

Тестовые Compose-профили, пробы и тестовые примеры не входят в публичную поставку. Для личного архива используется основной профиль с named volumes и резервными копиями.

Для HTTPS требуется точный `INV_CORS_ORIGINS` и `INV_COOKIE_SECURE=true`. Для локального HTTP разрешённого Origin устанавливается `false`. Браузерное приложение и API удобнее обслуживать через один Origin. Nginx уже проксирует `/api/v1` и `/health`; `/docs`, `/redoc` и `/openapi.json` доступны напрямую на API, а не через текущий web proxy.

### 3.3. CLI

Все команды: `uv run python -m app.cli <команда>`. В контейнере префикс `uv run` не нужен.

| Команда | Аргументы | Назначение |
|---|---|---|
| `bootstrap` | `--login`, опционально `--timezone`, `--storage` | Один владелец/admin, workspace, «Место не указано», начальные настройки/модели, при флаге приватное хранилище |
| `reset-password` | `--login` | Новый пароль, отзыв действующих сессий |
| `schemas` | `--output`, по умолчанию docs/schemas | OpenAPI и JSON Schema из текущего кода |
| `verify-prompts` | нет | Побайтовая проверка шести исходных промптов по baseline |
| `model-health` | нет | Диагностика настроенного локального runtime |
| `sync-models` | нет | Обновить реестр deployment из окружения; перепроверить capabilities перед включением |
| `worker` | `cpu`, `ml`, `cloud`, `scheduler` | Отдельный процесс arq выбранной роли |
| `legacy-preview` | `--workspace-id UUID` | Предложения переноса старых public.items без автоматического подтверждения |
| `backup` | `--output PATH` | Согласованная копия PostgreSQL и медиа |
| `deletion-ledger` | `--output PATH` | Актуальные tombstones для последующего restore |
| `restore` | `--input PATH --deletion-ledger PATH` | Восстановление в выделенные БД/хранилище с повторным применением удалений |

`legacy-preview` — инструмент однократного контролируемого переноса, не синхронизация двух баз. Не запускайте повторно без проверки уже созданных предложений. Сохранённые архивы исходников не включаются в Docker build.

<a id="domain"></a>
## 4. Предметная модель

### 4.1. Вещь, партия и остаток

- **Item:** имя, категория, режим учёта, базовая единица/шаг, атрибуты, tags, barcode/brand/model, описание пользователя и отдельное описание AI, privacy, lifecycle, версии поиска.
- **Lot:** ссылка на Item; label, serial/manufacturer batch, приобретение/производство/открытие, заявленный и вычисленный срок, lot_attributes, архив. Две партии одного товара могут иметь разные сроки.
- **Balance:** одна партия в одном месте; quantity и quantity_state. Для источника перемещения/расхода нужны `lot_id` и `location_id`, одного `item_id` недостаточно.
- **Location:** дерево `parent_id`; place/container/system_unspecified; описание, унаследованная политика приватности. Контейнер перемещается как узел дерева вместе с вложенными местами.
- **Alias:** явно подтверждённое альтернативное название. Модель не добавляет свои догадки в словарь автоматически.

Режимы: `individual` — экземпляр 0/1; `counted` — счётные вещи; `measured` — масса/объём/длина с шагом; `untracked` — наличие без количества. Режим учёта и базовая единица существующей карточки не меняются обычной `update_item`.

### 4.2. Количества

| Состояние | quantity | Смысл |
|---|---|---|
| `exact` | Decimal ≥ 0 | Подтверждённое точное количество |
| `estimated` | Decimal ≥ 0 | Приблизительное количество, отмеченное пользователем |
| `unknown` | null | Вещь есть/упомянута, величина не установлена |
| `not_applicable` | null | Только для untracked; количество не применяется |

Wire-формат количества — **строка** с точкой и максимум шестью знаками после неё; float/bool запрещены. Схема допускает и целое число, но клиенты должны использовать строки единообразно. В БД `NUMERIC(20,6)`; бизнес-валидация требует конечное число меньше 100000000000000, кратное положительному quantity_step. Пустая строка не заменяет null. Для individual разрешено только exact 0/1.

`known_quantity` суммирует известные остатки активных партий. `has_unknown_quantity=true` означает, что сумма не является полным остатком. `is_estimated=true` помечает приближение. `depleted=true` допустимо для количественного режима, когда неизвестных остатков нет и известная сумма равна нулю. Untracked не становится depleted арифметически.

Единицы: pcs, pair, tablet, capsule, package, g, kg, mg, ml, l, m, cm. Общие размерности: count, mass, volume, length; tablet/capsule/package не взаимозаменяемы автоматически. Для преобразования упаковки требуется подтверждённый package_size. Пара имеет коэффициент 2 к pcs; новая карточка пары хранится в pcs. `attributes.counting_unit="pair"` задаёт представление «1 пара и 1 штука» для трёх носков; не доказывает, что любые два носка подходят друг другу.

Количественный расход unknown требует сначала установить количество. Полное перемещение присутствия использует `whole_presence=true`; количество не подменяется выдуманной единицей. Ноль, unknown, наличие и архив должны различаться в UI.

### 4.3. Категории и атрибуты

| Код / название | Разрешённые атрибуты |
|---|---|
| medicine / Лекарства | active_ingredients[], strength {raw,value,unit}, dosage_form, brand |
| document / Документы | document_type, owner_name, masked_number |
| food / Продукты | brand, storage_conditions |
| clothing / Одежда | size, season, brand, color, material, counting_unit |
| equipment / Техника | brand, model |
| dishes / Посуда | material, purpose |
| cosmetics / Косметика | brand, purpose |
| household / Быт | purpose, brand, storage_conditions |
| hobby / Хобби | tags[] |
| other / Другое | color, material, purpose |

Неизвестные атрибуты отклоняются. Списки содержат до 30 непустых строк длиной до 255; обычные строковые атрибуты — до 2000 символов. `strength.value` — неотрицательный Decimal до шести знаков, `strength.raw` сохраняет текст на упаковке. Это характеристика товара, не назначение дозы. Структура справочников доступна через `/reference/categories` и `/reference/units`.

### 4.4. Сроки

`expiry_precision`: day, month или unknown. Календарные даты передаются `YYYY-MM-DD` без timezone. Для месяца сохраняется исходный текст `YYYY-MM`; `expiry.month_expiry_policy` должен явно определить first_day/last_day. Пока политика отсутствует, нельзя выдавать точный вычисленный день как достоверный.

`effective_expiry_on` рассчитывает сервер: учитывается заявленный срок и срок после открытия `opened_on + after_opening_amount/unit`, выбирается более ранний. Месяцы прибавляются календарно. Расчёт сопровождается происхождением (explicit/normalized_month/after_opening/minimum/unknown). Клиент не перезаписывает его собственными вычислениями. Изменение политики месяца после preview делает подтверждение устаревшим.

### 4.5. Команды

| Команда | Результат / важные ограничения |
|---|---|
| receive_stock | Новая или существующая Item; новая или существующая Lot; место/количество; совпадение имени требует выбора карточки или separate_item |
| move_stock | Перенос партии из места в место, частично либо целиком; сумма сохраняется |
| consume_stock | Расход конкретной партии/места; недостаточный и неизвестный остаток блокируют |
| set_quantity | Установка остатка и его точности с причиной |
| confirm_presence | Подтверждение наличия без придумывания количества |
| update_item | Метаданные карточки и privacy; незаданные поля не обнуляются |
| update_lot | Метаданные партии, даты/сроки и privacy |
| split_lot | Отделение количества в новую партию с новыми метаданными |
| merge_lots | Объединение 2–20 совместимых партий; не способом скрыть разные сроки/экземпляры |
| create_location | Новое место или контейнер, родитель, default privacy |
| update_location | Имя/описание/privacy места |
| move_location | Перемещение узла; циклы и превышение глубины запрещены |
| archive_location | Архивирование с явным transfer_to_id при необходимости переноса содержимого |
| archive_item / restore_item | Архив и восстановление карточки; история сохраняется |
| add_alias / remove_alias | Подтверждённые альтернативные названия |
| reverse_operation | Новая компенсирующая операция при совместимом актуальном состоянии |

Все поля перечислены в [справочнике команд](#command-reference). Там «обязательное в JSON» описывает транспортную схему. Бизнес-обязательность проверяется preview: многие поля намеренно nullable, чтобы сохранять неполную форму с blocking_issues.

<a id="security"></a>
## 5. Авторизация и приватность

### 5.1. Сессии

Пароли хешируются Argon2. Access JWT короткоживущий: default 15 минут. Refresh default 30 дней; при обновлении он ротируется. Повтор старого refresh отзывает семейство сессий. Logout отзывает текущую сессию, logout-all увеличивает auth_version и отзывает все. Токены access привязаны к действующей серверной сессии.

Для web всегда передаётся `client_type:"web"`. Refresh находится в HttpOnly cookie `inventory_refresh`, `SameSite=Strict`, Path `/api/v1/auth`; в JSON его нет. Login/refresh и logout с cookie проверяют Origin. Клиент отправляет `credentials:"include"` и хранит access token в памяти. Native-клиент может явно использовать `client_type:"native"` и refresh из JSON в защищённом системном хранилище.

`/me` возвращает id, login, app_role, locale, timezone, version, workspaces и принятые agreements. Workspace-членство проверяется backend: чтение для активного member, запись для owner/editor. **Текущий `/me` не возвращает role внутри workspace.** Полное управление членством и регистрация отсутствуют; нельзя делать UI приглашений на основании существования таблицы Membership.

### 5.2. Граница доверия

`local_only` — обработка только в доверенном контуре. `cloud_allowed` — потенциальное разрешение внешней обработки, которое ещё ограничивается глобальными настройками, классификацией и связанными объектами. Побеждает наиболее строгая политика media/item/lot/location/предков, force_local и аварийного запрета. Категория document всегда local_only. Неизвестная чувствительность также запрещает внешнюю передачу.

Согласие `trusted_server`, version `1` относится к серверу владельца и не является blanket-согласием на внешние модели. Bootstrap фиксирует согласие владельца. Сам текст соглашения должен быть предоставлен владельцем установки; frontend не сочиняет юридический документ из enum API.

Сервер повторяет проверку privacy перед исходящим запросом. Diagnostic replay и его потомки принудительно local-only и не могут применяться к учёту. Внешние провайдеры в реальной приёмке не использовались; их ошибки и контракты проверены MockTransport.

<a id="http"></a>
## 6. Общие правила HTTP

Базовый путь `/api/v1`, JSON UTF-8. Все бизнес-ресурсы требуют `Authorization: Bearer <access_token>`. Для scoped-операций нужен `X-Workspace-ID`, допускается альтернативный query `workspace_id`; при наличии обоих они обязаны совпадать. Условно публичны только health и login/refresh (последним нужны credentials). Swagger/OpenAPI публикуются стандартными маршрутами FastAPI.

### 6.1. Идемпотентность и версии

- `Idempotency-Key` — непрозрачная строка длиной 1–200. Обязательность указана для каждого маршрута [в таблице](#api-reference). Она не универсальна для всех POST: например, polling её не требует.
- `client_request_id` — UUID тела запроса там, где предусмотрен схемой. Это отдельное поле, не замена заголовка.
- При сетевой неопределённости повторяют то же тело с тем же ключом и client_request_id. Для нового пользовательского действия создают новые.
- Одна область идемпотентности включает пользователя, workspace и операцию. Повтор ключа с другим телом отклоняется как IDEMPOTENCY_KEY_REUSED.
- `expected_version` относится к конкретной сущности; `expected_revision` — к форме/настройкам. Они не взаимозаменяемы.
- HTTP 202 означает «принято», а не «применено». Успех изменения учёта — `confirmation.status="applied"`.

У отдельных управляющих ручек повтор защищён самим состоянием, хотя заголовок требуется: cancel, pause/resume, health-check, GC. Фронтенд всё равно сохраняет один ключ на пользовательское действие и не трактует любой 409 как транспортный retry.

### 6.2. Пагинация

Типовой список: `{items:[], next_cursor:null|string, has_more:boolean}`. Cursor непрозрачен; клиент не вычисляет offset самостоятельно и сбрасывает cursor при смене фильтров/workspace. Каталог, задачи, журнал и большинство списков ограничены `limit≤100`, default 50; поиск default 30. `/locations`, `/locations/{id}/contents` и `/items/{id}/lots` сейчас возвращают весь соответствующий список.

Общий `page()` сортирует по UUID `id`, **не по created_at**. Временной сортировки всех страниц и общего `total` в этих ручках нет. Поиск имеет собственный cursor, связанный с запросом/фильтрами. `settings/history` ограничен последними 100 ревизиями без cursor. Не выдавайте размер одной страницы за число всех объектов.

### 6.3. Ошибки

```json
{"error":{"code":"VERSION_CONFLICT","message":"Форма уже изменилась.","request_id":"request-uuid","retryable":false,"details":{"review":{}}}}
```

Это фрагмент оболочки: `details.review` при конфликте содержит полную новую форму, а не пустой объект. Ошибки валидации тела возвращают `field_errors:[{key:"body.quantity",code:"..."}]`; traceback/исходный ввод не включаются. У каждого ответа есть `X-Request-ID`.

| HTTP | Реакция клиента |
|---|---|
| 400 | Исправить workspace/cursor/запрос |
| 401 | Одна попытка refresh; при неуспехе вход без бесконечного цикла |
| 403 | Объяснить ограничение прав/privacy/Origin; не повторять автоматически |
| 404 | Объект отсутствует либо недоступен в выбранном workspace |
| 409 | Проверить code; обновить форму/версии или показать занятость; не подтверждать автоматически |
| 410 | Материал/задача/экспорт очищены или истекли |
| 413 | Уменьшить размер/число/длительность медиа по подсказке |
| 415 | Формат содержимого не поддерживается или не совпал с MIME |
| 422 | Показать ошибки полей/правил, сохранить введённые значения |
| 429 | Ограничение входа/очереди/провайдера; задержка, без создания новых дублей |
| 500 / 503 | Сохранить контекст, показать повтор/ручное продолжение, request_id |

`retryable` в HTTP-оболочке — общая подсказка, не permission обойти HITL. Нормализованные ошибки провайдера и расписание повторов модели обрабатываются worker, клиент не повторяет inference в цикле.

<a id="flows"></a>
## 7. Сценарии интеграции и ответы API

### 7.1. Вход и запуск клиента

`POST /auth/login`:

```json
{"login":"owner","password":"пароль владельца","client_type":"web"}
```

Успешный JSON содержит access_token, token_type и expires_in; web-refresh устанавливается cookie. Затем `/me`, выбор workspace, `/capabilities`, `/settings`, справочники категорий/единиц. Неавторизованный пользователь не должен получать личные картинки или список вещей. Refresh: `POST /auth/refresh` с `{"client_type":"web"}`.

### 7.2. Ручная операция

`POST /proposals/manual` с заголовком идемпотентности:

```json
{
  "client_request_id":"10000000-0000-4000-8000-000000000001",
  "actions":[{
    "action_id":"a1",
    "type":"receive_stock",
    "values":{
      "item_name":"Носки",
      "category":"clothing",
      "tracking_mode":"counted",
      "unit_code":"pair",
      "quantity":"1",
      "quantity_state":"exact",
      "attributes":{"counting_unit":"pair"}
    }
  }]
}
```

Ответ — сохранённый review.v1. Отсутствующее место заменяется системным. Для другого существующего места передают его location_id. `expected_versions` можно передать как `{ "item:<UUID>": 7, "lot:<UUID>": 3, "balance:<UUID>": 4, "location:<UUID>": 2 }` для реально затронутых сущностей; строка после двоеточия — фактический UUID, не имя.

`POST /commands/manual-confirm` разрешён только после осмысленного пользовательского подтверждения и требует `explicit_confirmation:true`. Для интерфейса со сравнением before/after предпочтительна цепочка manual proposal → review → confirm. Этот endpoint не используется для обхода AI-review.

### 7.3. Контракт review.v1

| Поле | Смысл |
|---|---|
| proposal_id, task_id | Идентичность предложения; у ручного task_id может быть null |
| revision, review_hash | Версия и digest показанного серверного документа; сохраняются как есть |
| status, can_confirm, available_actions | Возможности именно этой сохранённой ревизии |
| title, summary | Читаемое описание предполагаемой операции |
| effective_privacy | Текущая политика предложения |
| actions[] | Стабильный action_id, type, нормализованные values, preview |
| form | template, fields[], readonly_fields[] |
| blocking_issues[] | Ошибки, которые не позволяют применить предложение |
| required_decisions[] | Явный выбор operation/unsupported_request и допустимые options |
| warnings[] | Предупреждения, которые надо показать, даже если can_confirm=true |
| media[] | Приватные media_id/download; не Base64 |
| source_proposals[] | Источники объединённого атомарного review |

Поля формы: `action_id`, `key`, `label`, `control`, `value_type`, `value`, `required`, `editable`, `allow_unknown`, `options`, `validation`, `source`, `verification_state`, `importance`. Контролы перечислены `/capabilities`; неизвестный обязательный control нельзя незаметно пропускать. `options` — значения протокола и подписи, а не произвольный текст для отправки.

`preview` вычислен общим интерпретатором; он содержит сведения об операции и `changes` с before/after. Эти структуры показываются пользователю, но клиент не исполняет их как команды. Источники/кандидаты различаются по UUID. Свойства имеющейся карточки при пополнении могут быть readonly.

### 7.4. Правки, подтверждение и конфликты

`PATCH /proposals/{id}`:

```json
{"expected_revision":1,"changes":[{"action_id":"a1","key":"quantity","value":"2"}]}
```

Сервер сохраняет новую ревизию с preview; UI заменяет review целиком, не смешивает новый hash со старыми actions. Для вложенных свойств используются разрешённые ключи вроде `attributes.size`, `attributes.strength.value`. Null удаляет соответствующий атрибут; произвольный JSON Patch не поддерживается. `operation` и `unsupported_request` — специальные ключи решений, допустимые только когда сервер их запросил.

`POST /proposals/{id}/confirm`:

```json
{
  "expected_revision":2,
  "observed_review_hash":"hash из последнего показанного review",
  "client_request_id":"10000000-0000-4000-8000-000000000002",
  "changes":[]
}
```

Можно включить окончательные явные правки в `changes` этого же confirm. Backend их проверит и применит без повторного ML; если они требуют новой проверки либо состояние БД изменилось, вернёт 409 с актуальным review. Сам по себе старый `can_confirm=false` не означает, что исправления нельзя отправить: сначала PATCH для нового preview либо предусмотренный confirm с явными changes. В интерфейсе нельзя блокировать все пути исправления формы.

При VERSION_CONFLICT/REVIEW_UPDATE_REQUIRED клиент сохраняет несохранённые значения, принимает новую форму, показывает изменившиеся последствия и ждёт нового нажатия подтверждения. **Никакого автоматического confirm после 409.** Valid inline-правки при изменившемся учёте могут уже сохраниться на сервере; не добавляйте их второй раз без сравнения.

Ответ 202: confirmation_id, стабильный operation_id, task_id, status, result, error_code, poll_after_ms. Проверка `/confirmations/{id}` продолжается до applied/conflict/failed. `applied` содержит operation_id, число изменений и previews. При conflict proposal вновь editable; result может содержать review. `failed` допускает `/confirmations/{id}/retry` с прежним operation_id, без ML. GET confirmation может вернуть `task_id:null` — связь не следует выводить из этого поля при повторном чтении.

### 7.5. Загрузка с AI

Для каждого файла `POST /media` multipart: file, privacy_policy (`local_only` default), client_preprocessed (bool). Content-Type multipart устанавливает HTTP-клиент с boundary. Ответ 201: media_id, state, type, mime, width/height или duration_seconds.

После успешной загрузки всех материалов `POST /tasks`:

```json
{
  "client_request_id":"10000000-0000-4000-8000-000000000003",
  "input_mode":"text",
  "text":"Положил в белый шкаф пару носков",
  "media_ids":[],
  "context":{},
  "privacy":{"force_local":true}
}
```

Для фото добавляют media_ids, для аудио audio_media_id, для совместного ввода `input_mode:"photo_audio"`. Требуется хотя бы текст, фото или аудио. Строгая схема допускает до 20 media_ids, но runtime default — **3 фото**, максимум настройки — 12; действуют оба ограничения. Есть file/task byte limits и max_pending_per_user. Отклонённое создание задачи не превращает upload в подтверждённую вещь.

Фраза «положил» без существующего источника трактуется как предложение поступления; при похожих учтённых вещах требуется выбор операции. Без числа значение не обязано становиться 1. Отрицание/будущее намерение требует решения. Неопознанная вещь может получить сохранённое временное имя; дальнейшее apply не генерирует другое имя.

### 7.6. Пакеты

`POST /ingestion-batches` создаёт организационную группу с name. Её UUID передаётся новым задачам. `/ingestion-batches/{id}` возвращает counts по статусам; `/tasks` и `/review-inbox` фильтруются по batch_id. Сам batch не означает атомарности предметных операций.

**Независимое массовое подтверждение:** `/review-inbox/batch-confirm`, items до 20; у каждого proposal_id, revision/hash, changes, client_request_id и собственный idempotency_key. Результат каждой строки отдельно: успешные элементы сохраняются, ошибочные не откатывают остальные.

**Общее атомарное предложение:** `/review-batches` с sources `{proposal_id,revision}`. Default runtime limit 20 источников (схема до 50); создаётся один review с перенумерованными action_id. После проверки подтверждается обычным `/proposals/{id}/confirm`. Изменение любого источника требует обновления общей формы. Диагностические replay не включаются. Нельзя одновременно подтверждать исходник и полагаться на старую общую форму.

### 7.7. Каталог, места, история

`GET /items` фильтрует category, include_archived, availability=available/depleted. Это endpoint каталога, не текстовый поиск. Карточка ответа включает SQL-поля Item, агрегаты количества, lots[], balances[], photos[] и при соответствующей одежде quantity_display. `GET /items/{id}` имеет ту же расширенную форму; lots/balances/aliases/history доступны отдельно. Item использует `id`, `primary_category`, `base_unit_id`.

Фотографии:

```json
{"photos":[{"media_id":"source-uuid","url":"/api/v1/media/source-uuid/download","thumbnail":{"media_id":"thumb-uuid","url":"/api/v1/media/thumb-uuid/download","width":192,"height":256}}]}
```

Это иллюстрация структуры, `source-uuid`/`thumb-uuid` заменяются фактическими UUID. Без фото photos=[], без готового thumbnail — null. Миниатюра не является публичной ссылкой. Прямой `<img src>` не добавит Bearer/X-Workspace-ID: web-клиент получает Blob через авторизованный запрос, создаёт Object URL и освобождает его после использования.

`GET /locations` возвращает плоский список с parent_id/full_path; frontend строит дерево. `/contents?recursive=true` включает потомков. Системное unspecified — допустимое место, не отсутствие карточки Location. Архивные места исключены из дерева; текущий `GET /locations/{id}` для существующего архивного места может вернуть JSON null, это требуется обработать.

История `/operations` и `/items/{id}/history` — страницы операций, детали `/operations/{id}` добавляют entries. `reverse-preview` создаёт review для отмены; из UI нет endpoint произвольного редактирования entries, PUT Item или прямого DELETE остатка.

<a id="tasks"></a>
## 8. Задачи, состояния, прогресс и очереди

### 8.1. Task

| status | Смысл / действия |
|---|---|
| accepted | Принято, ожидает CPU-подготовки |
| preparing | Нормализация медиа |
| queued | Ожидает модельной стадии / ресурса |
| running | Выполняется стадия inference |
| retry_wait | Сервер запланировал повтор с задержкой |
| waiting_for_review | Результат сохранён, пользователь проверяет; GPU свободен |
| applying | Подтверждение принято, идёт запись |
| succeeded | Сценарий завершён; для read-only поиска это не обязательно запись |
| failed | Автоматическая обработка остановлена |
| cancelled | Пользователь отменил до принятого confirm |
| expired | Истёк срок незавершённой задачи/проверки |

Стадии (`stage`) детальнее status: upload_verified, media, audio, privacy_asr, extraction, review_ready, confirmation_queued, saved и служебные варианты. Не следует задавать жёсткую прогресс-полоску, предполагающую наличие каждой стадии: текстовый запрос пропускает медиа/аудио, read-only не требует confirm.

Task view: task_id/status/stage/status_version, progress, proposal_id, result (показывается в succeeded), effective_privacy, batch_id, config_revision, error_code, can_cancel, poll_after_ms, created_at/updated_at, timing, links.self/review. **Исходный input_text, audio_media_id и media_ids в этом ответе не выдаются.** Их нельзя обещать для восстановления composer после перезагрузки, опираясь только на GET Task.

`/tasks/{id}/retry` доступен для failed/cancelled/expired и создаёт child с новым client_request_id, новым snapshot и parent_task_id. Принятое confirmation нужно повторять отдельной ручкой confirmation, а не создавать новый inference. `/manual-review` предназначен для failed/cancelled/waiting_for_review. Priority 0–10 меняется по status_version через поле expected_version только в допускающих это состояниях.

### 8.2. Polling

`GET /tasks/{id}` отдаёт ETag `"task_id:status_version"`; `If-None-Match` с совпавшим ETag → 304 без JSON body. Пакетный `POST /tasks/status`:

```json
{"tasks":[{"task_id":"10000000-0000-4000-8000-000000000004","status_version":2}]}
```

Ответ `{changed:[TaskView], unchanged:[UUID], poll_after_ms:3000}`. До 100 IDs. Task view для активного состояния обычно рекомендует 2000 ms; confirmation queued/applying — 1000 ms. Эти реальные значения ответа имеют приоритет для текущего клиента. Реестровые polling-настройки пока не формируют динамически все ответы ручек.

Если один ID пакетного запроса уже очищен/недоступен, возможна ошибка всего запроса: split/bounded индивидуальная проверка устраняет такой ID из наблюдения. Не создавайте отдельный бесконечный таймер на каждую строку. После resume вкладки перечитайте состояния.

### 8.3. Время и проценты

`progress.current` содержит stage/status/started_at, history — максимум 64 завершённых перехода с finished_at/duration_ms/error_code. Это сохранённая в PostgreSQL история, не эфемерные события websocket. `timing.processing_seconds` — время модельных попыток, не полная сумма CPU+очередь+ожидание пользователя. `server_time` помогает клиентскому elapsed-таймеру.

`percent` и `estimated_remaining_ms` сейчас null. Клиент показывает этап, elapsed и неопределённый индикатор. Процент загрузки файла можно измерять отдельно; он не равен проценту распознавания. История длительностей пригодна для будущей статистической ETA, но такая оценка пока не реализована.

### 8.4. Отказоустойчивость

Scheduler каждые 3 секунды выполняет reconciler; периодические напоминания/cleanup проверяются каждые 5 минут. Реальные сроки cleanup дополнительно ограничены настройками. Redis доставляет jobs; задачи, подтверждения и outbox остаются в БД. arq не добавляет скрытую цепочку retry сверх прикладного бюджета (`max_tries=1`).

Локальные inference, embeddings и индексирование координируются единственным GPU slot с heartbeat, lease и fencing token. При неизвестном физическом состоянии вызова slot quarantined: истечение таймера не доказывает остановку llama.cpp. Восстановление требует подтверждения администратора, что физическое выполнение остановлено, текущего fencing token и причины.

default/bulk выбираются с весами 4:1; default порог bulk — 5 незавершённых задач. CPU concurrency default 2, local ML — 1. Пауза очереди предотвращает новый dispatch; уже начатый вызов не является мгновенно отменённым. Outbox имеет контролируемые повторы/dead letters; Redis можно восстановить без повторной предметной записи.

<a id="media"></a>
## 9. Медиа и модели

### 9.1. Подготовка файлов

Default: JPEG/PNG/WebP, без анимации; max 15 MiB/file, 45 MiB/task, 30 млн decoded pixels, 3 фото; WAV PCM16 mono/stereo до 60 секунд. MIME проверяется по содержимому. API проверяет структуру/заявленные размеры без декодирования полноразмерных пикселей; CPU worker выполняет декодирование. Ошибка битого потока становится ошибкой подготовки и ручной формой, а не вызовом модели.

Source.width/height описывают закодированные размеры. После EXIF-поворота normalized/thumbnail имеют ориентированные размеры. JPEG уменьшается декодером до последующих преобразований; прозрачность компонуется на белом, метаданные очищаются. Default normalized 1600 px/JPEG quality 80, thumbnail 256 px. Коллаж строится из нормализованных изображений по одному, без хранения нескольких больших RGBA-копий.

Один снимок подаётся без сетки и сохраняет пропорции. Несколько — один JPEG collage с подписями/manifest, сохраняющим порядок и координаты источников. Профиль inference **максимум 512 px, 262144 bytes**. JPEG quality уменьшается до допустимого объёма; превышение лимита не отправляется в модель. Deployment допускает max_side 256–1024, но повышение требует проверки runtime. Адаптер проверяет размер/число изображений ещё раз перед HTTP. Версия текущего preprocessing — collage-3.

`collage.v1` содержит canvas dimensions, preprocessing/config revision, cache_key, tiles. У tile есть rect, content_rect, normalized_source_width/height, scale, small_tile, media_id. source_region переводит область коллажа в нормализованные координаты источника; поля/подписи вне content_rect не являются изображением вещи. При мелких tiles неподтверждённая текстом пользователя дата не переносится как достоверная. Автоматических detail-pass сейчас нет.

Миниатюры выдаются пакетно на страницу Item/Search. После confirm варианты связываются с Item, чтобы TTL временной задачи не удалил живое фото. `client_preprocessed=true` отмечает подготовку клиентом, но не отключает серверную проверку. Рекомендуется отправлять уже обрезанный пользователем JPEG до 1600 px; необязательно передавать оригинал камеры. Для аудио — WAV PCM16 mono 16 kHz. Не обрезать автоматически слова или отрицания.

### 9.2. Адаптеры и промпты

| Адаптер | Протокол / назначение |
|---|---|
| LocalAdapter | Ollama: text/image, ровно одно изображение; embeddings BGE-M3 1024 |
| LocalAudioAdapter | Доверенный OpenAI-совместимый chat/input_audio WAV endpoint; URL/model/key и trust/verified обязательны |
| CloudAdapter | Внешний endpoint через независимые INV_CLOUD_*; разрешение policy и глобальных настроек перед HTTP |

Поддержка audio+image одним вызовом не заявляется. Аудио нормализуется в PCM16 mono/16k и сегментируется по 20 секунд с перекрытием 1 секунда; затем удаляются совпадающие фрагменты транскрипции. Default бюджет 6 модельных вызовов учитывает части аудио, privacy и extraction; timeout/stage retry ограничены общим бюджетом.

Шесть исходных prompt-файлов сохранены. Активный renderer разрешает gemma_e4b_gatekeeper.txt, gemma_core_vlm.j2, search_extractor.j2; runtime revision включает их hashes и дополнительный GUARD. calendar_prompt.txt, schedule_parser.j2 и gemma_core_vlm.txt сохраняются как исходные материалы и не означают наличие графиков приёма. GUARD/нормализатор требуют unknown вместо выдуманных фактов и запрещают выполнять команды из текста фотографии.

Каждая Task сохраняет конфигурацию, model deployment/route revision, prompt revision и output schema. Если текущий deployment/prompt несовместим со snapshot, требуется явное продолжение/повтор, а не незаметная замена модели в ожидающей задаче. Модели не получают SQL, ключи Storage или право применять учёт.

Реальная приёмка: Ollama Gemma3:4b для text/image, BGE-M3 для embeddings, доверенный local-gemma-4-e4b для аудио. Проверка vision на удалённой Gemma4 не заявляется. Разрешение JPEG не заменяет ограничения visual tokens и памяти на inference-сервере.

<a id="search"></a>
## 10. Поиск

`GET /search?query=...` — чтение без confirm. Фильтры: category, location_id, availability=available/depleted, expired, cursor, limit. Query до 2000 символов. PostgreSQL даёт точные/текстовые совпадения по имени, aliases, barcode/model/serial и русскому FTS; Qdrant объединяет dense BGE-M3 с фиксированным sparse BM25/IDF и RRF. Это реализация с фиксированной нормализацией длины, не полноценный обучаемый корпусный BM25; см. [ADR-002](docs/ADR-002.md).

После retrieval сервер перечитывает актуальные SQL-объекты, проверяет workspace/lifecycle/фильтры. Векторный индекс не может вернуть клиенту удалённую или чужую карточку. Ошибка Qdrant либо занятый GPU оставляет текстовый поиск и строку warning. `generated_description` не добавляется в подтверждённый поисковый документ автоматически.

Ответ `{items, warning, has_more, next_cursor}`. Search item использует **item_id/candidate_id, category, unit_code**, а не имена полей каталога. Дополнительно: name, tracking_mode, privacy_policy, attributes, version, index_revision, агрегаты количества, lots[] с lot_id/location_id/location_path/quantity/quantity_state/expiry_on/serial_number, matched_by, explanation_short, photos[]. Для полного редактирования запросите `/items/{item_id}`.

Переиндексация создаёт shadow collection, строит её по всем workspace, сверяет актуальные SQL-версии и атомарно переключает общий alias. API `/admin/search/reindex` возвращает job_id; прогресс читается `/admin/jobs/{id}`. Старую коллекцию удаляют отдельно после проверки. Outbox индексирует текущее состояние Item, а не воспроизводит устаревший payload события.

<a id="reminders"></a>
## 11. Напоминания

Правила касаются только expiry medicine/food/document. Канал только `in_app`; push/email/графики дозирования отсутствуют. Правило принадлежит пользователю в workspace. RulePatch передаёт полностью values плюс enabled и expected_version; DELETE отключает правило, не удаляет историю безвозвратно.

Поля: категории, location_ids, offsets_before_expiry (до 12 целых 0–3650), local_delivery_time HH:MM, IANA timezone, quiet_hours=[] либо [начало,конец], send_expired, repeat_expired_interval 1–365 дней, repeat_expired_max_count 0–12, group_mode by_day/by_category/none, channels=[in_app], include_archived, hide_sensitive_details_on_lock_screen. Defaults и полный JSON-контракт — ReminderValues [в справочнике](#request-reference).

Planner пересчитывает поколения occurrences при изменении срока, не дублирует доставку, учитывает quiet hours и календарь зоны. Depleted отменяет соответствующие будущие уведомления. Untracked-документ может иметь срок и получать уведомление. Unknown expiry не превращается в выдуманную дату напоминания. Catch-up объединяет пропущенные пороги по текущей политике.

`GET /notifications` возвращает не скрытые пользователем уведомления, срок откладывания которых уже прошёл. PATCH с expected_version и mark_read/dismiss; POST snooze — hours 1–168 и expected_version. В UI используются поля Notification из ответа, без пересчёта статуса правил по одному локальному таймеру. Отдельного total/unread-count endpoint нет.

<a id="administration"></a>
## 12. Настройки и администрирование

Обычный пользователь читает `/settings/schema`, `/settings` и сохраняет changes с expected_version. Доступны prefer_local, default_privacy, hide_sensitive_details, compact_view. Профиль locale/timezone редактируется отдельно через PATCH /me с version профиля. `locale=en` хранится сервером, но наличие полностью английского UI этим не обещается.

Администратор получает schema полей с key/group/type/default/min/max/enum/nullable/apply_mode/scope/sensitivity/control/editable/description_ru. Runtime view содержит desired_revision, effective_revision, status, desired, effective, components_pending. Процесс изменения: validate → показать последствия → PATCH с reason и expected_revision; для сокращения retention обязательно impact_confirmed. Rollback создаёт новую ревизию и не удаляет историю.

Режимы применения: new_tasks — новые snapshots; requires_restart — после подтверждения старта cpu_worker/ml_worker/scheduler; immediate — согласно реализации управляющего параметра. Если новый набор содержит restart-параметры, весь набор может ожидать рестарта; аварийный запрет external всё равно действует сразу. Backend не перезапускается из браузера автоматически.

Редактирование models ограничено enabled/maintenance и expected_version. URL/model/key регистрируются из окружения CLI sync-models, не вводятся через этот API. Перед включением требуется успешная capability/health проверка. Health внешней модели использует синтетический запрос по явному действию администратора.

Административные экраны могут использовать: health, metrics, queues, pause/resume, GPU recovery, trace, replay, settings history, models, reindex jobs, GC preview/run, audit. Очереди default/bulk/cpu/cloud/maintenance. Admin metrics содержит counts задач/outbox, oldest_pending, attempts, index_lag; это не Prometheus endpoint и не готовая оценка скорости прогресса.

`GC preview` сейчас описывает непривязанные старые uploads, а `GC run` запускает регулярную политику cleanup целиком. Их нельзя показывать как одну точную пару «вот только эти файлы будут удалены». Для сокращения retention используется отдельный impact в settings/validate. GC run возвращает running/not_due/completed, а не maintenance job_id.

<a id="maintenance"></a>
## 13. Экспорт, удаление, backup/restore

### 13.1. Экспорт

POST /exports: format json/csv/zip, include_media, include_history. Ответ 202 export_id/status. Чтение статуса → expires_at, download, sha256; готовый файл скачивается с авторизацией. TTL default 24 часа. Истёкший/отозванный export недоступен (410). Экспорт включает подтверждённый согласованный снимок; CSV обезвреживает значения, способные стать формулой; ZIP содержит контрольные суммы.

JSON export.v1: schema_version, exported_at, timezone, reference_versions, export_revision, items/lots/balances/locations/aliases и при включении history/media соответствующие массивы. Экспорт не является серверным backup. Список всех экспортов и восстановление очереди скачиваний отдельной ручкой пока отсутствуют; клиент сохраняет полученный export_id.

### 13.2. Архив и удаление

Архив — предметная команда с HITL, reversible restore_item. Физическое удаление — отдельный поток: POST /deletion-previews с item_ids (1–100) → preview_id/revision/hash/impact → явное POST /purge-jobs с этими значениями и explicit_confirmation=true.

После принятия purge учёт и связанные материалы сразу становятся недоступны обычным чтениям; bytes удаляются после not_before (default отсрочка 30 дней). Работа учитывает shared media и все связанные формы/историю/экспорты; старые копии не должны показывать удалённое. При stale impact нужен новый preview и новый пользовательский выбор.

`GET /purge-jobs` и `/purge-jobs/{id}` показывают status/version/not_before/result. До начала hard purge можно отменить queued job с expected_version и explicit_confirmation=true; после purging отмена недопустима. UI не должен путать отмену ещё ожидающего удаления с восстановлением уже уничтоженных bytes.

`POST /media/{id}/delete-preview` выдаёт bindings, size_bytes, can_delete_bytes, но **прямого delete endpoint файла нет**. Отмена upload в composer удаляет локальную ссылку; непривязанные серверные uploads очищаются TTL. Нельзя обещать пользователю физическое удаление этим preview.

### 13.3. Backup и восстановление

```powershell
uv run python -m app.cli backup --output data/backups/2026-09-21
uv run python -m app.cli deletion-ledger --output data/backups/current-deletions.json
```

Копия содержит согласованный pg_dump inventory, manifest, медиа и hashes. Перед restore проверяются целостность и безопасные пути; приложение останавливают и используют отдельную подготовленную БД/хранилище:

```powershell
uv run python -m app.cli restore --input data/backups/2026-09-21 --deletion-ledger data/backups/current-deletions.json
uv run alembic upgrade head
```

Актуальный deletion ledger должен быть новее backup и храниться отдельно: restore повторно применяет удаления, чтобы старый снимок не воскресил данные. Пользовательские сессии и временные экспорты отзываются. Qdrant восстанавливается из PostgreSQL. Секреты deployment резервирует владелец отдельно. Расписание на хосте и копирование на другой носитель автоматически не создаются.

### 13.4. Обновление

Сделать и проверить backup → остановить изменяющие данные процессы → собрать новый образ → Alembic upgrade/check → запустить API/workers/scheduler → пересоздать nginx → проверить health, вход, ручную операцию и поиск. `docker compose down -v` не используется для обновления. Исходники, старые public-таблицы и пользовательские медиа не мигрируются путём удаления каталогов.

<a id="testing"></a>
## 14. Проверки и разработка

Обычные проверки из корня:

```powershell
uv run pytest -q
uv run ruff check app tests scripts migrations
uv run ruff format --check app tests scripts migrations
uv run mypy
uv run python -m app.cli verify-prompts
uv run alembic check
```

SQLite-тесты проверяют предметные сценарии и HTTP без тяжёлых сервисов. PostgreSQL-тесты проверяют блокировки/конкуренцию. Opt-in проверки потери Redis и backup используют выделенные тестовые сервисы. Пример полного прогона:

```powershell
docker compose -f deploy/compose.test.yml up -d
$env:INV_TEST_POSTGRES_URL='postgresql+asyncpg://inventory:inventory-test-only@127.0.0.1:55432/inventory_test'
$env:INV_TEST_REDIS_LOSS='1'
$env:INV_RUN_BACKUP_TEST='1'
uv run pytest -q
```

Redis-loss тест очищает выделенную DB13 тестового Redis. Не включать его с рабочим Redis. Backup-тест создаёт отдельные временные БД. CI запускает PostgreSQL и обычный набор, но не весь opt-in/media/model набор. Последний полный backend прогон — 186 passed; mypy проверяет 9 файлов domain/settings. Детали доказательств — в матрице приёмки.

| Скрипт (`python -m scripts.…`) | Что проверяет / ограничения |
|---|---|
| smoke_local | Нормализация кейсов и настроенные локальные модели |
| probe_audio | Реальная поддержка input_audio на явно заданном доверенном endpoint; по умолчанию синтетический WAV |
| smoke_stack | Временные PG/S3/Qdrant, реальные фото/WAV, модели, review, arq и поиск; не рабочая база |
| smoke_small_label | Маленькая этикетка в collage и unknown вместо выдуманной даты |
| smoke_containers | Собранные API/workers/nginx, вход/cookie/Origin, upload 12 MP, явное подтверждение в inventory_verify |
| smoke_media_memory | Две CPU-подготовки по три фото в контейнере 256 MiB без сети/swap |

Контрактные артефакты регенерируются `python -m app.cli schemas`. При изменении HTTP/схем обновляются документация и тесты клиента. Исходные prompts проверяются относительно baseline начала рефакторинга; их наличие в git diff не означает автоматическую порчу текущим эпиком.

<a id="limitations"></a>
## 15. Диагностика и известные ограничения

### 15.1. Логи и восстановление

Logger inventory пишет JSON: timestamp UTC, level, event, разрешённые request_id/task_id/confirmation_id/job_id/attempt_id, stage/job/status, duration_ms, error_code/error_type. INV_LOG_LEVEL управляет DEBUG/INFO/WARNING/ERROR. Декораторы фиксируют начало/завершение jobs; стадии модели имеют отдельные события. Сырые payload, аудио, фото, ключи и exception text в эти сообщения не включаются. Доступ к admin trace также требует workspace.

| Симптом | Проверка / действие |
|---|---|
| API не готов | `/health/live`, затем ready; миграции inventory, INV_DATABASE_URL, PostgreSQL |
| 401 после входа | Origin/cookie_secure, client_type=web, credentials, серверные часы, session family |
| Задача accepted не движется | Запущены CPU и scheduler, очередь не paused, Redis доступен |
| Задача queued не движется | ML worker, deployment enabled/maintenance, GPU slot, cooldown и budgets |
| Audio unprocessed | TRUSTED/VERIFIED, корректные URL/model/key, реальная health-проверка и sync-models |
| GPU quarantined | Проверить и остановить физическое выполнение inference; recover с текущим token и причиной |
| Подтверждение queued | CPU/scheduler/outbox; не запускать повторный AI вместо confirmation |
| confirmation failed | Повторить confirmation, сохранив operation_id |
| confirmation conflict | Получить актуальный review, проверить и подтвердить заново |
| Поиск с warning | Qdrant/Ollama/GPU; подтверждённый каталог продолжает читаться |
| Нет thumbnail | Проверить completed media preparation/bindings; source не подгружать вместо thumbnail без решения клиента |
| nginx 502 после обновления | Пересоздать web вместе с API, чтобы обновился внутренний адрес |
| Экспорт недоступен | status/expires_at; создать новый export при необходимости |

### 15.2. Что нельзя предполагать о текущем API

- Не все ответы имеют строгие response_model в OpenAPI; для Task/Item/Search/review/maintenance используются описания этого документа и integration tests.
- `/capabilities` сообщает рекомендуемую preprocessing-конфигурацию и inference caps, но не полный набор изменяемых admission limits для обычного пользователя.
- `/me` не сообщает membership role; нет приглашений/администрирования пользователей и API смены пароля.
- Task view не восстанавливает исходный текст/аудио и список медиа composer после refresh.
- Нет server-side полнотекстового фильтра `/items`, общего total, произвольной сортировки, календаря expiry или dashboard-агрегатов.
- `/locations` не возвращает архивные места; отдельной команды restore_location нет.
- Нет общего списка всех exports, прямого attachment/delete фото карточки, crop-inference endpoint или редактирования source photo.
- Некоторые settings зарезервированы/read-only. Кроме того, api.max_page_size/max_poll_ids и polling-настройки не отменяют фиксированные ограничения текущих handlers: limit/IDs 100, интервалы из ответа.
- GC preview непривязанных файлов не является полным точным preview всех видов regular_cleanup.
- Backend поддерживает хранение locale=en, но полная локализация клиента требует отдельной реализации.
- Detail-pass, calibrated confidence/fallback, dataset, raw payload mode, дополнительный кэш, push и OpenTelemetry collector не реализованы.
- Полное качество всех личных cases не измерялось. Управляемый тест commit/ack не равен физическому выключению ОС во всех возможных точках.

Для полного будущего UX необходимые расширения API перечислены как **проектируемые**, с приоритетом и контрактом в [ТЗ фронтенда](docs/FRONTEND_SPEC.md#backend-gaps). Документация не изменяет сервер и не добавляет эти возможности.

<a id="api-reference"></a>
## 16. Полный справочник HTTP

**93 HTTP-операции на 85 путях**, получено из текущего FastAPI OpenAPI. Служебные маршруты Swagger/Redoc в эту сумму не включены. `*` у параметра обозначает обязательность OpenAPI. Workspace указан отдельно в колонке доступа; допускается заголовок либо query согласно общим правилам. Body schemas раскрыты в следующем разделе. Указан штатный success code; 304 у условного GET Task и runtime ошибки описаны выше.

| Метод и путь | Доступ и заголовки | Тело / параметры | Успех |
|---|---|---|---|
| `GET /health/live` | публичный | — | 200 |
| `GET /health/ready` | публичный | — | 200 |
| `GET /api/v1/capabilities` | Bearer | — | 200 |
| `POST /api/v1/auth/login` | публичный | application/json: Login | 200 |
| `POST /api/v1/auth/refresh` | публичный | application/json: Refresh | 200 |
| `POST /api/v1/auth/logout` | Bearer | — | 200 |
| `POST /api/v1/auth/logout-all` | Bearer | — | 200 |
| `GET /api/v1/workspaces` | Bearer | — | 200 |
| `GET /api/v1/me` | Bearer | — | 200 |
| `PATCH /api/v1/me` | Bearer | application/json: ProfileUpdate | 200 |
| `POST /api/v1/me/agreements` | Bearer, Idempotency-Key | application/json: AgreementInput | 200 |
| `GET /api/v1/reference/categories` | Bearer, workspace | — | 200 |
| `GET /api/v1/reference/units` | Bearer, workspace | — | 200 |
| `GET /api/v1/forms` | Bearer, workspace | query `operation`: string<br>query `category`: string | 200 |
| `POST /api/v1/proposals/manual` | Bearer, workspace: запись, Idempotency-Key | application/json: ManualProposal | 201 |
| `POST /api/v1/commands/manual-confirm` | Bearer, workspace: запись, Idempotency-Key | application/json: ManualConfirm | 202 |
| `GET /api/v1/proposals/{proposal_id}` | Bearer, workspace | path `proposal_id`*: string:uuid | 200 |
| `PATCH /api/v1/proposals/{proposal_id}` | Bearer, workspace: запись, Idempotency-Key | application/json: EditProposal<br>path `proposal_id`*: string:uuid | 200 |
| `POST /api/v1/proposals/{proposal_id}/confirm` | Bearer, workspace: запись, Idempotency-Key | application/json: ConfirmProposal<br>path `proposal_id`*: string:uuid | 202 |
| `POST /api/v1/proposals/{proposal_id}/cancel` | Bearer, workspace: запись, Idempotency-Key | path `proposal_id`*: string:uuid | 200 |
| `GET /api/v1/confirmations/{confirmation_id}` | Bearer, workspace | path `confirmation_id`*: string:uuid | 200 |
| `POST /api/v1/confirmations/{confirmation_id}/retry` | Bearer, workspace: запись, Idempotency-Key | path `confirmation_id`*: string:uuid | 202 |
| `POST /api/v1/review-batches` | Bearer, workspace: запись, Idempotency-Key | application/json: ReviewBatch | 201 |
| `GET /api/v1/review-batches/{proposal_id}` | Bearer, workspace | path `proposal_id`*: string:uuid | 200 |
| `POST /api/v1/review-inbox/batch-confirm` | Bearer, workspace: запись | application/json: BatchConfirm | 202 |
| `GET /api/v1/review-inbox` | Bearer, workspace | query `limit`: integer<br>query `cursor`: string / null<br>query `batch_id`: string:uuid / null | 200 |
| `GET /api/v1/items` | Bearer, workspace | query `limit`: integer<br>query `cursor`: string / null<br>query `category`: string / null<br>query `include_archived`: boolean<br>query `availability`: string / null | 200 |
| `GET /api/v1/items/{item_id}` | Bearer, workspace | path `item_id`*: string:uuid | 200 |
| `GET /api/v1/items/{item_id}/lots` | Bearer, workspace | path `item_id`*: string:uuid | 200 |
| `GET /api/v1/items/{item_id}/balances` | Bearer, workspace | path `item_id`*: string:uuid | 200 |
| `GET /api/v1/items/{item_id}/aliases` | Bearer, workspace | path `item_id`*: string:uuid<br>query `limit`: integer<br>query `cursor`: string / null | 200 |
| `GET /api/v1/lots/{lot_id}` | Bearer, workspace | path `lot_id`*: string:uuid | 200 |
| `GET /api/v1/locations` | Bearer, workspace | — | 200 |
| `GET /api/v1/locations/{location_id}` | Bearer, workspace | path `location_id`*: string:uuid | 200 |
| `GET /api/v1/locations/{location_id}/contents` | Bearer, workspace | path `location_id`*: string:uuid<br>query `recursive`: boolean | 200 |
| `GET /api/v1/operations` | Bearer, workspace | query `limit`: integer<br>query `cursor`: string / null | 200 |
| `GET /api/v1/operations/{operation_id}` | Bearer, workspace | path `operation_id`*: string:uuid | 200 |
| `GET /api/v1/items/{item_id}/history` | Bearer, workspace | path `item_id`*: string:uuid<br>query `limit`: integer<br>query `cursor`: string / null | 200 |
| `POST /api/v1/operations/{operation_id}/reverse-preview` | Bearer, workspace: запись, Idempotency-Key | path `operation_id`*: string:uuid | 201 |
| `POST /api/v1/media` | Bearer, workspace, Idempotency-Key | multipart/form-data: Body_upload_api_v1_media_post | 201 |
| `GET /api/v1/media/{media_id}` | Bearer, workspace | path `media_id`*: string:uuid | 200 |
| `GET /api/v1/media/{media_id}/download` | Bearer, workspace | path `media_id`*: string:uuid | 200 |
| `POST /api/v1/media/{media_id}/delete-preview` | Bearer, workspace, Idempotency-Key | path `media_id`*: string:uuid | 200 |
| `POST /api/v1/tasks` | Bearer, workspace: запись, Idempotency-Key | application/json: TaskCreate | 202 |
| `GET /api/v1/tasks` | Bearer, workspace | query `limit`: integer<br>query `cursor`: string / null<br>query `batch_id`: string:uuid / null<br>query `status`: string / null | 200 |
| `POST /api/v1/tasks/status` | Bearer, workspace | application/json: Poll | 200 |
| `GET /api/v1/tasks/{task_id}` | Bearer, workspace | path `task_id`*: string:uuid<br>header `if-none-match`: string / null | 200 |
| `POST /api/v1/tasks/{task_id}/cancel` | Bearer, workspace: запись, Idempotency-Key | path `task_id`*: string:uuid | 200 |
| `POST /api/v1/tasks/{task_id}/retry` | Bearer, workspace: запись, Idempotency-Key | application/json: Retry<br>path `task_id`*: string:uuid | 202 |
| `POST /api/v1/tasks/{task_id}/manual-review` | Bearer, workspace: запись, Idempotency-Key | application/json: Retry<br>path `task_id`*: string:uuid | 201 |
| `PATCH /api/v1/tasks/{task_id}/priority` | Bearer, workspace: запись | application/json: Priority<br>path `task_id`*: string:uuid | 200 |
| `POST /api/v1/ingestion-batches` | Bearer, workspace: запись, Idempotency-Key | application/json: BatchInput | 201 |
| `GET /api/v1/ingestion-batches/{batch_id}` | Bearer, workspace | path `batch_id`*: string:uuid | 200 |
| `GET /api/v1/search` | Bearer, workspace | query `query`: string<br>query `category`: string / null<br>query `location_id`: string:uuid / null<br>query `availability`: string / null<br>query `expired`: boolean<br>query `limit`: integer<br>query `cursor`: string / null | 200 |
| `GET /api/v1/notifications` | Bearer, workspace | query `limit`: integer<br>query `cursor`: string / null | 200 |
| `PATCH /api/v1/notifications/{notification_id}` | Bearer, workspace: запись | application/json: NotificationPatch<br>path `notification_id`*: string:uuid | 200 |
| `POST /api/v1/notifications/{notification_id}/snooze` | Bearer, workspace: запись, Idempotency-Key | application/json: Snooze<br>path `notification_id`*: string:uuid | 200 |
| `GET /api/v1/reminder-rules` | Bearer, workspace | query `limit`: integer<br>query `cursor`: string / null | 200 |
| `POST /api/v1/reminder-rules` | Bearer, workspace: запись, Idempotency-Key | application/json: ReminderValues | 201 |
| `PATCH /api/v1/reminder-rules/{rule_id}` | Bearer, workspace: запись | application/json: RulePatch<br>path `rule_id`*: string:uuid | 200 |
| `DELETE /api/v1/reminder-rules/{rule_id}` | Bearer, workspace: запись | path `rule_id`*: string:uuid<br>query `expected_version`*: integer | 200 |
| `GET /api/v1/admin/settings/schema` | Bearer, admin | — | 200 |
| `GET /api/v1/admin/settings` | Bearer, admin | — | 200 |
| `PATCH /api/v1/admin/settings` | Bearer, admin, Idempotency-Key | application/json: SettingsPatch | 200 |
| `POST /api/v1/admin/settings/validate` | Bearer, admin | application/json: SettingsPatch | 200 |
| `GET /api/v1/admin/settings/history` | Bearer, admin | — | 200 |
| `POST /api/v1/admin/settings/rollback` | Bearer, admin, Idempotency-Key | application/json: Rollback | 200 |
| `GET /api/v1/settings/schema` | Bearer | — | 200 |
| `GET /api/v1/settings` | Bearer | — | 200 |
| `PATCH /api/v1/settings` | Bearer | application/json: Preferences | 200 |
| `GET /api/v1/admin/models` | Bearer, admin | — | 200 |
| `PATCH /api/v1/admin/models/{model_id}` | Bearer, admin | application/json: ModelPatch<br>path `model_id`*: string:uuid | 200 |
| `POST /api/v1/admin/models/{model_id}/health-check` | Bearer, admin, Idempotency-Key | path `model_id`*: string:uuid | 200 |
| `GET /api/v1/admin/queues` | Bearer, admin | — | 200 |
| `POST /api/v1/admin/queues/{name}/{action}` | Bearer, admin, Idempotency-Key | path `name`*: default, bulk, cpu, cloud, maintenance<br>path `action`*: pause, resume | 200 |
| `POST /api/v1/admin/gpu/recover` | Bearer, admin, Idempotency-Key | application/json: GPURecovery | 200 |
| `GET /api/v1/admin/tasks/{task_id}/trace` | Bearer, admin, workspace | path `task_id`*: string:uuid | 200 |
| `POST /api/v1/admin/tasks/{task_id}/replay` | Bearer, admin, workspace: запись, Idempotency-Key | path `task_id`*: string:uuid | 202 |
| `POST /api/v1/admin/search/reindex` | Bearer, admin, workspace: запись, Idempotency-Key | — | 202 |
| `GET /api/v1/admin/jobs/{job_id}` | Bearer, admin, workspace | path `job_id`*: string:uuid | 200 |
| `POST /api/v1/admin/gc/preview` | Bearer, admin | — | 200 |
| `POST /api/v1/admin/gc/run` | Bearer, admin, Idempotency-Key | — | 200 |
| `GET /api/v1/admin/audit` | Bearer, admin | query `limit`: integer<br>query `cursor`: string / null | 200 |
| `GET /api/v1/admin/metrics` | Bearer, admin | — | 200 |
| `GET /api/v1/admin/health` | Bearer, admin | — | 200 |
| `POST /api/v1/exports` | Bearer, workspace: запись, Idempotency-Key | application/json: ExportInput | 202 |
| `GET /api/v1/exports/{export_id}` | Bearer, workspace | path `export_id`*: string:uuid | 200 |
| `GET /api/v1/exports/{export_id}/download` | Bearer, workspace | path `export_id`*: string:uuid | 200 |
| `POST /api/v1/deletion-previews` | Bearer, workspace: запись, Idempotency-Key | application/json: DeletionInput | 201 |
| `POST /api/v1/purge-jobs` | Bearer, workspace: запись, Idempotency-Key | application/json: PurgeInput | 202 |
| `GET /api/v1/purge-jobs` | Bearer, workspace | query `limit`: integer<br>query `cursor`: string / null | 200 |
| `GET /api/v1/purge-jobs/{job_id}` | Bearer, workspace | path `job_id`*: string:uuid | 200 |
| `POST /api/v1/purge-jobs/{job_id}/cancel` | Bearer, workspace: запись, Idempotency-Key | application/json: CancelPurge<br>path `job_id`*: string:uuid | 200 |

<a id="request-reference"></a>
## 17. Поля всех тел HTTP-запросов

Снимок схем из OpenAPI (исключены лишь стандартные HTTPValidationError/ValidationError). `Action.values` выбирается по type из отдельного справочника команд. `additionalProperties` в некоторых object-полях не означает разрешение произвольных предметных свойств: действуют серверные бизнес-правила. Необязательное поле отличается от явного null. Заголовки, query/path — в предыдущем разделе и OpenAPI; envelope ошибок переопределён приложением.

### `Action`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `action_id` | string | нет | {"pattern":"^[a-zA-Z0-9_-]{1,60}$","default":"a1"} |
| `type` | receive_stock, move_stock, consume_stock, set_quantity, update_item, update_lot, split_lot, merge_lots, create_location, move_location, update_location, archive_item, restore_item, archive_location, add_alias, remove_alias, confirm_presence, reverse_operation | да | — |
| `values` | object | да | — |

### `AgreementInput`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `agreement_type` | "trusted_server" | да | {"const":"trusted_server"} |
| `version` | "1" | да | {"const":"1"} |

### `BatchConfirm`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `items` | `array<BatchConfirmation>` | да | {"maxItems":20,"minItems":1} |

### `BatchConfirmation`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `expected_revision` | integer | да | {"minimum":1.0} |
| `changes` | `array<Change>` | нет | {"maxItems":100} |
| `observed_review_hash` | string | да | — |
| `client_request_id` | string:uuid | да | — |
| `proposal_id` | string:uuid | да | — |
| `idempotency_key` | string | да | {"maxLength":200,"minLength":1} |

### `BatchInput`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `name` | string | нет | {"maxLength":255,"minLength":1,"default":"Загрузка"} |

### `Body_upload_api_v1_media_post`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `file` | string | да | {"contentMediaType":"application/octet-stream"} |
| `privacy_policy` | string | нет | {"default":"local_only"} |
| `client_preprocessed` | boolean | нет | {"default":false} |

### `CancelPurge`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `expected_version` | integer | да | {"minimum":1.0} |
| `explicit_confirmation` | true | да | {"const":true} |

### `Change`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `action_id` | string | да | — |
| `key` | string | да | — |
| `value` | JSON | да | — |

### `ConfirmProposal`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `expected_revision` | integer | да | {"minimum":1.0} |
| `changes` | `array<Change>` | нет | {"maxItems":100} |
| `observed_review_hash` | string | да | — |
| `client_request_id` | string:uuid | да | — |

### `Context`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `location_id` | string:uuid / null | нет | — |
| `item_id` | string:uuid / null | нет | — |

### `DeletionInput`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `item_ids` | `array<string:uuid>` | да | {"maxItems":100,"minItems":1} |

### `EditProposal`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `expected_revision` | integer | да | {"minimum":1.0} |
| `changes` | `array<Change>` | нет | {"maxItems":100} |

### `ExportInput`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `format` | json, csv, zip | нет | {"default":"json"} |
| `include_media` | boolean | нет | {"default":false} |
| `include_history` | boolean | нет | {"default":false} |

### `GPURecovery`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `expected_fencing_token` | integer | да | — |
| `physical_inference_stopped` | true | да | {"const":true} |
| `reason` | string | да | {"maxLength":500,"minLength":1} |

### `Login`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `login` | string | да | {"maxLength":255,"minLength":1} |
| `password` | string | да | {"maxLength":1024,"minLength":1} |
| `client_type` | web, native | нет | {"default":"native"} |

### `ManualConfirm`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `actions` | `array<Action>` | да | {"maxItems":50,"minItems":1} |
| `expected_versions` | object | нет | — |
| `client_request_id` | string:uuid | да | — |
| `explicit_confirmation` | true | да | {"const":true} |

### `ManualProposal`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `actions` | `array<Action>` | да | {"maxItems":50,"minItems":1} |
| `expected_versions` | object | нет | — |
| `client_request_id` | string:uuid | да | — |

### `ModelPatch`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `expected_version` | integer | да | {"minimum":1.0} |
| `enabled` | boolean / null | нет | — |
| `maintenance` | boolean / null | нет | — |

### `NotificationPatch`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `expected_version` | integer | да | {"minimum":1.0} |
| `mark_read` | boolean | нет | {"default":false} |
| `dismiss` | boolean | нет | {"default":false} |

### `Poll`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `tasks` | `array<PollItem>` | да | {"maxItems":100} |

### `PollItem`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `task_id` | string:uuid | да | — |
| `status_version` | integer | нет | {"default":0} |

### `Preferences`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `expected_version` | integer | да | {"minimum":1.0} |
| `changes` | `array<SettingChange>` | да | {"maxItems":10} |

### `Priority`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `expected_version` | integer | да | {"minimum":1.0} |
| `priority` | integer | да | {"maximum":10.0,"minimum":0.0} |

### `Privacy`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `force_local` | boolean | нет | {"default":true} |

### `ProfileUpdate`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `expected_version` | integer | да | {"minimum":1.0} |
| `locale` | ru, en / null | нет | — |
| `timezone` | string / null | нет | — |

### `ProposalSource`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `proposal_id` | string:uuid | да | — |
| `revision` | integer | да | {"minimum":1.0} |

### `PurgeInput`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `preview_id` | string:uuid | да | — |
| `preview_revision` | integer | да | {"minimum":1.0} |
| `preview_hash` | string | да | — |
| `explicit_confirmation` | true | да | {"const":true} |

### `Refresh`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `refresh_token` | string / null | нет | — |
| `client_type` | web, native | нет | {"default":"native"} |

### `ReminderValues`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `categories` | `array<string>` | нет | {"maxItems":3,"minItems":1} |
| `location_ids` | `array<string>` | нет | {"maxItems":100} |
| `offsets_before_expiry` | `array<integer>` | нет | {"maxItems":12} |
| `local_delivery_time` | string | нет | {"default":"09:00"} |
| `timezone` | string | нет | {"default":"Europe/Moscow"} |
| `quiet_hours` | `array<string>` | нет | {"maxItems":2} |
| `send_expired` | boolean | нет | {"default":true} |
| `repeat_expired_interval` | integer | нет | {"maximum":365.0,"minimum":1.0,"default":7} |
| `repeat_expired_max_count` | integer | нет | {"maximum":12.0,"minimum":0.0,"default":0} |
| `group_mode` | string | нет | {"default":"by_day"} |
| `channels` | `array<string>` | нет | — |
| `include_archived` | boolean | нет | {"default":false} |
| `hide_sensitive_details_on_lock_screen` | boolean | нет | {"default":true} |

### `Retry`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `client_request_id` | string:uuid | да | — |

### `ReviewBatch`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `sources` | `array<ProposalSource>` | да | {"maxItems":50,"minItems":2} |

### `Rollback`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `expected_revision` | integer | да | {"minimum":1.0} |
| `target_revision` | integer | да | {"minimum":1.0} |
| `reason` | string | да | {"maxLength":500,"minLength":1} |

### `RulePatch`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `expected_version` | integer | да | {"minimum":1.0} |
| `values` | ReminderValues | да | — |
| `enabled` | boolean | нет | {"default":true} |

### `SettingChange`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `key` | string | да | — |
| `value` | JSON | да | — |

### `SettingsPatch`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `expected_revision` | integer | да | {"minimum":1.0} |
| `changes` | `array<SettingChange>` | да | {"maxItems":100,"minItems":1} |
| `reason` | string | да | {"maxLength":500,"minLength":1} |
| `impact_confirmed` | boolean | нет | {"default":false} |

### `Snooze`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `hours` | integer | да | {"maximum":168.0,"minimum":1.0} |
| `expected_version` | integer | да | {"minimum":1.0} |

### `TaskCreate`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `workspace_id` | string:uuid / null | нет | — |
| `client_request_id` | string:uuid | да | — |
| `input_mode` | text, photo, audio, photo_audio, manual | нет | {"default":"text"} |
| `text` | string / null | нет | — |
| `media_ids` | `array<string:uuid>` | нет | {"maxItems":20} |
| `audio_media_id` | string:uuid / null | нет | — |
| `context` | Context | нет | — |
| `privacy` | Privacy | нет | — |
| `batch_id` | string:uuid / null | нет | — |

<a id="command-reference"></a>
## 18. Все поля команд

Снимок строгих Pydantic-схем 18 команд. Тип `number / string` в quantity-схемах не отменяет запрет float в BeforeValidator: клиенты отправляют десятичные строки. Для update_* отсутствующие поля не меняются. Обязательность бизнес-полей окончательно определяется preview; неизвестные ключи запрещены.

### `receive_stock`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `label` | string / null | нет | {"default":null} |
| `serial_number` | string / null | нет | {"default":null} |
| `manufacturer_batch` | string / null | нет | {"default":null} |
| `acquired_at` | string:date / null | нет | {"default":null} |
| `manufactured_on` | string:date / null | нет | {"default":null} |
| `opened_on` | string:date / null | нет | {"default":null} |
| `expiry_on` | string:date / null | нет | {"default":null} |
| `expiry_precision` | day, month, unknown | нет | {"default":"unknown"} |
| `expiry_raw_text` | string / null | нет | {"default":null} |
| `after_opening_amount` | integer / null | нет | {"default":null} |
| `after_opening_unit` | day, month / null | нет | {"default":null} |
| `lot_attributes` | object | нет | — |
| `item_mode` | create, existing | нет | {"default":"create"} |
| `item_id` | string:uuid / null | нет | {"default":null} |
| `item_name` | string / null | нет | {"default":null} |
| `category` | medicine, document, food, clothing, equipment, dishes, cosmetics, household, hobby, other | нет | {"default":"other"} |
| `tracking_mode` | individual, counted, measured, untracked | нет | {"default":"counted"} |
| `unit_code` | string / null | нет | {"default":null} |
| `quantity_step` | number / string | нет | {"decimal_places":6,"default":"1","ge":0,"max_digits":20} |
| `quantity` | number / string / null | нет | {"default":null} |
| `quantity_state` | exact, estimated, unknown, not_applicable | нет | {"default":"unknown"} |
| `location_id` | string:uuid / null | нет | {"default":null} |
| `lot_mode` | create, existing | нет | {"default":"create"} |
| `lot_id` | string:uuid / null | нет | {"default":null} |
| `privacy_policy` | local_only, cloud_allowed | нет | {"default":"local_only"} |
| `attributes` | object | нет | — |
| `tags` | `array<string>` | нет | {"maxItems":30} |
| `barcode` | string / null | нет | {"default":null} |
| `brand` | string / null | нет | {"default":null} |
| `model` | string / null | нет | {"default":null} |
| `user_description` | string / null | нет | {"default":null} |
| `generated_description` | string / null | нет | {"default":null} |
| `separate_item` | boolean | нет | {"default":false} |
| `package_size` | number / string / null | нет | {"default":null} |

### `move_stock`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `lot_id` | string:uuid / null | нет | {"default":null} |
| `location_id` | string:uuid / null | нет | {"default":null} |
| `to_location_id` | string:uuid / null | нет | {"default":null} |
| `quantity` | number / string / null | нет | {"default":null} |
| `unit_code` | string / null | нет | {"default":null} |
| `whole_presence` | boolean | нет | {"default":false} |

### `consume_stock`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `lot_id` | string:uuid / null | нет | {"default":null} |
| `location_id` | string:uuid / null | нет | {"default":null} |
| `quantity` | number / string / null | нет | {"default":null} |
| `unit_code` | string / null | нет | {"default":null} |
| `reason` | string | нет | {"default":"Расход","maxLength":500} |

### `set_quantity`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `lot_id` | string:uuid / null | нет | {"default":null} |
| `location_id` | string:uuid / null | нет | {"default":null} |
| `quantity` | number / string / null | нет | {"default":null} |
| `quantity_state` | exact, estimated, unknown, not_applicable | нет | {"default":"exact"} |
| `reason` | string | нет | {"default":"Корректировка","maxLength":500,"minLength":1} |

### `update_item`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `item_id` | string:uuid / null | нет | {"default":null} |
| `name` | string / null | нет | {"default":null} |
| `primary_category` | medicine, document, food, clothing, equipment, dishes, cosmetics, household, hobby, other / null | нет | {"default":null} |
| `attributes` | object / null | нет | {"default":null} |
| `tags` | `array<string>` / null | нет | {"default":null} |
| `barcode` | string / null | нет | {"default":null} |
| `brand` | string / null | нет | {"default":null} |
| `model` | string / null | нет | {"default":null} |
| `user_description` | string / null | нет | {"default":null} |
| `privacy_policy` | local_only, cloud_allowed / null | нет | {"default":null} |

### `update_lot`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `label` | string / null | нет | {"default":null} |
| `serial_number` | string / null | нет | {"default":null} |
| `manufacturer_batch` | string / null | нет | {"default":null} |
| `acquired_at` | string:date / null | нет | {"default":null} |
| `manufactured_on` | string:date / null | нет | {"default":null} |
| `opened_on` | string:date / null | нет | {"default":null} |
| `expiry_on` | string:date / null | нет | {"default":null} |
| `expiry_precision` | day, month, unknown | нет | {"default":"unknown"} |
| `expiry_raw_text` | string / null | нет | {"default":null} |
| `after_opening_amount` | integer / null | нет | {"default":null} |
| `after_opening_unit` | day, month / null | нет | {"default":null} |
| `lot_attributes` | object | нет | — |
| `lot_id` | string:uuid / null | нет | {"default":null} |
| `privacy_policy` | local_only, cloud_allowed / null | нет | {"default":null} |

### `split_lot`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `lot_id` | string:uuid / null | нет | {"default":null} |
| `location_id` | string:uuid / null | нет | {"default":null} |
| `label` | string / null | нет | {"default":null} |
| `serial_number` | string / null | нет | {"default":null} |
| `manufacturer_batch` | string / null | нет | {"default":null} |
| `acquired_at` | string:date / null | нет | {"default":null} |
| `manufactured_on` | string:date / null | нет | {"default":null} |
| `opened_on` | string:date / null | нет | {"default":null} |
| `expiry_on` | string:date / null | нет | {"default":null} |
| `expiry_precision` | day, month, unknown | нет | {"default":"unknown"} |
| `expiry_raw_text` | string / null | нет | {"default":null} |
| `after_opening_amount` | integer / null | нет | {"default":null} |
| `after_opening_unit` | day, month / null | нет | {"default":null} |
| `lot_attributes` | object | нет | — |
| `quantity` | number / string / null | нет | {"default":null} |

### `merge_lots`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `lot_ids` | `array<string:uuid>` | нет | {"maxItems":20,"minItems":2} |

### `create_location`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `name` | string / null | нет | {"default":null} |
| `parent_id` | string:uuid / null | нет | {"default":null} |
| `description` | string / null | нет | {"default":null} |
| `kind` | place, container | нет | {"default":"place"} |
| `default_privacy_policy` | local_only, cloud_allowed / null | нет | {"default":null} |

### `move_location`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `location_id` | string:uuid / null | нет | {"default":null} |
| `parent_id` | string:uuid / null | нет | {"default":null} |

### `update_location`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `location_id` | string:uuid / null | нет | {"default":null} |
| `name` | string / null | нет | {"default":null} |
| `description` | string / null | нет | {"default":null} |
| `default_privacy_policy` | local_only, cloud_allowed / null | нет | {"default":null} |

### `archive_item`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `item_id` | string:uuid / null | нет | {"default":null} |

### `restore_item`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `item_id` | string:uuid / null | нет | {"default":null} |

### `archive_location`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `location_id` | string:uuid / null | нет | {"default":null} |
| `transfer_to_id` | string:uuid / null | нет | {"default":null} |

### `add_alias`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `item_id` | string:uuid / null | нет | {"default":null} |
| `alias` | string / null | нет | {"default":null} |
| `scope` | user, workspace | нет | {"default":"workspace"} |

### `remove_alias`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `alias_id` | string:uuid / null | нет | {"default":null} |

### `confirm_presence`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `lot_id` | string:uuid / null | нет | {"default":null} |
| `location_id` | string:uuid / null | нет | {"default":null} |

### `reverse_operation`

| Поле | Тип / варианты | Обязательное в JSON | Default / ограничения |
|---|---|---|---|
| `operation_id` | string:uuid | да | — |

<a id="env-reference"></a>
## 19. Все переменные Config

Здесь только **значения по умолчанию из исходного класса**, не содержимое локальных env. Производственная установка обязана задать собственные credentials. `INV_STORAGE_BACKEND=s3` — основной профиль; локальный файловый Storage используется в тестах. Веб-клиент не читает эти переменные.

| Переменная | Default из класса Config | Тип |
|---|---|---|
| `INV_DATABASE_URL` | `postgresql+asyncpg://inventory:inventory@127.0.0.1:55432/inventory` | str |
| `INV_REDIS_URL` | `redis://127.0.0.1:56379/0` | str |
| `INV_JWT_SECRET` | `секрет не задан` | pydantic.types.SecretStr |
| `INV_JWT_ISSUER` | `inventarizator` | str |
| `INV_JWT_AUDIENCE` | `inventory-client` | str |
| `INV_ACCESS_MINUTES` | `15` | int |
| `INV_REFRESH_DAYS` | `30` | int |
| `INV_CORS_ORIGINS` | `["http://localhost:3000","http://127.0.0.1:3000"]` | list[str] |
| `INV_COOKIE_SECURE` | `true` | bool |
| `INV_OLLAMA_URL` | `http://127.0.0.1:11434` | str |
| `INV_LOCAL_MODEL` | `gemma3:4b` | str |
| `INV_LOCAL_IMAGE_MAX_SIDE` | `512` | int |
| `INV_LOCAL_IMAGE_MAX_BYTES` | `262144` | int |
| `INV_LOG_LEVEL` | `INFO` | typing.Literal['DEBUG', 'INFO', 'WARNING', 'ERROR'] |
| `INV_EMBEDDING_MODEL` | `bge-m3:latest` | str |
| `INV_LOCAL_AUDIO_URL` | `null` | str \| None |
| `INV_LOCAL_AUDIO_MODEL` | `null` | str \| None |
| `INV_LOCAL_AUDIO_KEY` | `секрет не задан` | pydantic.types.SecretStr |
| `INV_LOCAL_AUDIO_TRUSTED` | `false` | bool |
| `INV_LOCAL_AUDIO_VERIFIED` | `false` | bool |
| `INV_CLOUD_URL` | `null` | str \| None |
| `INV_CLOUD_KEY` | `секрет не задан` | pydantic.types.SecretStr |
| `INV_CLOUD_MODEL` | `null` | str \| None |
| `INV_CLOUD_PROXY` | `null` | str \| None |
| `INV_STORAGE_BACKEND` | `s3` | str |
| `INV_MEDIA_ROOT` | `data\media-v1` | pathlib.Path |
| `INV_S3_ENDPOINT` | `http://127.0.0.1:59000` | str |
| `INV_S3_ACCESS_KEY` | `inventory` | str |
| `INV_S3_SECRET_KEY` | `секрет не задан` | pydantic.types.SecretStr |
| `INV_S3_BUCKET` | `inventory-private` | str |
| `INV_QDRANT_URL` | `http://127.0.0.1:56333` | str |
| `INV_SEARCH_COLLECTION` | `inventory_bge_m3_bm25_v1` | str |
| `INV_PROMPT_DIR` | `<корень проекта>/prompts` | pathlib.Path |
| `INV_BACKUP_ROOT` | `data\backups` | pathlib.Path |

Дополнительные переменные инструментов: POSTGRES_PASSWORD/MINIO_PASSWORD — Compose; INV_BOOTSTRAP_PASSWORD — необязательный CLI bootstrap; INV_TEST_POSTGRES_URL/INV_TEST_REDIS_LOSS/INV_RUN_BACKUP_TEST — opt-in проверки. Прочие env внешних утилит не являются настройками домена.

<a id="settings-reference"></a>
## 20. Все настройки PostgreSQL

67 административных ключей и 4 пользовательских. `null` допустим только при nullable. «Только чтение» запрещает включать несуществующую функцию. Реальные defaults могут отличаться в установленной ревизии; UI читает schema и desired/effective, а не копирует эту таблицу в код.

### 20.1. Администратор

| Ключ | Default | Тип / пределы / варианты | Применение; изменение | Назначение |
|---|---|---|---|---|
| `routing.strategy` | `local_first` | str; local_first, cloud_preferred | `new_tasks`; да | Порядок вызова моделей |
| `routing.external_enabled` | `false` | bool | `immediate`; да | Разрешить внешние модели |
| `routing.local_model_ref` | `local_vlm` | str; local_vlm | `new_tasks`; да | Локальная модель |
| `routing.privacy_asr_model_ref` | `privacy_asr` | str; privacy_asr | `new_tasks`; да | Первичная проверка |
| `routing.cloud_primary_ref` | `null` | str; cloud_primary; null | `new_tasks`; да | Внешняя модель |
| `routing.fallback_chain` | `[]` | list | `new_tasks`; только чтение | Дополнительная цепочка моделей пока не реализована |
| `routing.max_total_attempts` | `6` | int; 1…12 | `new_tasks`; да | Всего вызовов на задачу: до четырёх аудиочастей, проверка и извлечение |
| `routing.max_external_calls` | `1` | int; 0…5 | `new_tasks`; да | Внешних вызовов на задачу |
| `routing.max_external_cost_per_task` | `null` | decimal; 0…100; null | `new_tasks`; да | Максимальная внешняя стоимость |
| `quality.review_attention_threshold` | `null` | float; 0…1; null | `new_tasks`; только чтение | Порог уверенности пока не откалиброван; числовая оценка не применяется |
| `quality.fallback_threshold` | `null` | float; 0…1; null | `new_tasks`; только чтение | Автоматический fallback по оценке уверенности пока не реализован |
| `queue.default_weight` | `4` | int; 1…20 | `immediate`; да | Вес обычной очереди |
| `queue.bulk_weight` | `1` | int; 1…20 | `immediate`; да | Вес массовой очереди |
| `queue.bulk_after_outstanding` | `5` | int; 1…1000; null | `new_tasks`; да | Порог массовой очереди |
| `queue.max_pending_per_user` | `500` | int; 1…10000 | `new_tasks`; да | Лимит ожидающих задач |
| `queue.local_gpu_slots` | `1` | int; 1…1 | `requires_restart`; да | Одновременных GPU-вызовов |
| `queue.cpu_concurrency` | `2` | int; 1…8 | `requires_restart`; да | Одновременных CPU-задач |
| `queue.cloud_concurrency` | `1` | int; 1…8 | `requires_restart`; да | Одновременных внешних вызовов |
| `queue.max_review_batch_size` | `20` | int; 2…50 | `new_tasks`; да | Размер общего подтверждения |
| `timeout.local_inference_seconds` | `300` | int; 10…3600 | `new_tasks`; да | Таймаут локального вызова |
| `timeout.cloud_inference_seconds` | `60` | int; 5…300 | `new_tasks`; да | Таймаут внешнего вызова |
| `timeout.task_total_seconds` | `1200` | int; 30…86400; null | `new_tasks`; да | Бюджет времени обработки |
| `timeout.lease_seconds` | `60` | int; 10…600 | `new_tasks`; да | Срок аренды обработчика |
| `timeout.heartbeat_seconds` | `10` | int; 1…120 | `new_tasks`; да | Интервал heartbeat |
| `timeout.worker_hard_seconds` | `1500` | int; 30…86400 | `requires_restart`; да | Предельное время arq job |
| `retry.base_delay_seconds` | `2` | int; 1…300 | `new_tasks`; да | Начальная задержка повтора |
| `retry.max_delay_seconds` | `300` | int; 1…3600 | `new_tasks`; да | Максимальная задержка |
| `retry.max_attempts_per_stage` | `2` | int; 1…5 | `new_tasks`; да | Попыток на стадию |
| `media.max_images_per_task` | `3` | int; 1…12 | `new_tasks`; да | Фотографий на задачу |
| `media.max_file_bytes` | `15728640` | int; 1024…104857600 | `new_tasks`; да | Размер одного файла |
| `media.max_task_bytes` | `47185920` | int; 1024…314572800 | `new_tasks`; да | Размер материалов задачи |
| `media.max_decoded_pixels` | `30000000` | int; 100000…100000000 | `new_tasks`; да | Пикселей после декодирования |
| `media.max_audio_seconds` | `60` | int; 1…600 | `new_tasks`; да | Длительность записи |
| `media.normalized_max_side` | `1600` | int; 512…2048 | `new_tasks`; да | Сторона сохраняемого изображения |
| `media.thumbnail_max_side` | `256` | int; 64…512 | `new_tasks`; да | Сторона миниатюры |
| `media.jpeg_quality` | `80` | int; 40…95 | `new_tasks`; да | Качество JPEG |
| `collage.max_width` | `512` | int; 256…4096 | `new_tasks`; да | Ширина изображения, дополнительно ограниченная runtime |
| `collage.max_height` | `512` | int; 256…4096 | `new_tasks`; да | Высота изображения, дополнительно ограниченная runtime |
| `collage.min_tile_side` | `320` | int; 64…1024 | `new_tasks`; да | Минимальная сторона области |
| `collage.detail_passes_max` | `2` | int; 0…4 | `new_tasks`; только чтение | Резерв для detail-pass; сейчас нечитаемые поля остаются unknown |
| `model.context_budget` | `8192` | int; 2048…32768 | `new_tasks`; да | Контекст модели |
| `model.output_budget` | `2048` | int; 256…8192 | `new_tasks`; да | Размер ответа |
| `search.dense_candidates` | `30` | int; 1…200 | `new_tasks`; да | Семантических кандидатов |
| `search.sparse_candidates` | `30` | int; 1…200 | `new_tasks`; да | Текстовых кандидатов |
| `search.final_candidates` | `8` | int; 1…30 | `new_tasks`; да | Кандидатов в форме |
| `search.embedding_batch_size` | `1` | int; 1…1 | `new_tasks`; только чтение | Эмбеддинги обрабатываются по одному для экономии памяти |
| `polling.min_interval_ms` | `1000` | int; 500…10000 | `new_tasks`; да | Минимальный интервал обновления |
| `polling.max_interval_ms` | `10000` | int; 1000…60000 | `new_tasks`; да | Максимальный интервал обновления |
| `retention.orphan_upload_hours` | `24` | int; 1…8760 | `new_tasks`; да | Хранение непривязанных файлов, часы |
| `retention.task_input_days` | `30` | int; 1…3650; null | `new_tasks`; да | Хранение входного текста и аудио, дни |
| `retention.review_draft_days` | `90` | int; 1…3650; null | `new_tasks`; да | Хранение незавершённых форм, дни |
| `retention.source_photo_days` | `null` | int; 1…3650; null | `new_tasks`; да | Хранение непривязанных фото, дни |
| `retention.archived_auto_purge_days` | `null` | int; 1…3650; null | `new_tasks`; да | Автоочистка архива, дни |
| `retention.purge_grace_days` | `30` | int; 1…365 | `new_tasks`; да | Отсрочка окончательного удаления, дни |
| `retention.gc_interval_hours` | `24` | int; 1…720 | `new_tasks`; да | Интервал очистки, часы |
| `retention.debug_payload_days` | `1` | int; 1…30 | `new_tasks`; только чтение | Хранение payload выключено: расширенная диагностика не поставляется |
| `diagnostics.level` | `normal` | str; normal | `new_tasks`; только чтение | Доступна обычная диагностика без исходных payload; расширенный режим не поставляется |
| `diagnostics.store_payloads` | `false` | bool | `new_tasks`; только чтение | Сохранение исходных payload недоступно в этой поставке |
| `diagnostics.payload_session_ttl_minutes` | `30` | int; 1…120 | `new_tasks`; только чтение | Сессии расширенной диагностики не поставляются |
| `datasets.enabled` | `false` | bool | `new_tasks`; только чтение | Отдельное сохранение датасетов не поставляется; примеры не копируются |
| `cache.enabled` | `false` | bool | `new_tasks`; только чтение | Дополнительный кэш списков не поставляется; чтение выполняется из БД |
| `cache.ttl_seconds` | `30` | int; 1…300 | `new_tasks`; только чтение | Кэш списков выключен, настройка TTL недоступна |
| `locations.max_depth` | `6` | int; 1…20 | `new_tasks`; да | Глубина дерева мест |
| `expiry.month_expiry_policy` | `null` | str; last_day, first_day; null | `new_tasks`; да | Интерпретация месяца срока |
| `exports.ttl_hours` | `24` | int; 1…168 | `new_tasks`; да | Доступность экспорта, часы |
| `api.max_page_size` | `100` | int; 10…500 | `new_tasks`; да | Максимальный размер страницы |
| `api.max_poll_ids` | `100` | int; 1…500 | `new_tasks`; да | Задач в одном обновлении |

Проверяются зависимости: lease > 2×heartbeat; worker_hard > local_inference + 30 секунд; output_budget + 1024 < context_budget; min polling ≤ max polling; max_file ≤ max_task; retry base ≤ retry max. Названия очередей, slots=1, разрешённые refs и обязательный HITL не расширяются произвольными ключами.

### 20.2. Пользователь

| Ключ | Default | Тип / пределы / варианты | Применение; изменение | Назначение |
|---|---|---|---|---|
| `prefer_local` | `true` | bool | `new_tasks`; да | Предпочитать локальное распознавание |
| `default_privacy` | `local_only` | str; local_only, cloud_allowed | `new_tasks`; да | Приватность новых материалов |
| `hide_sensitive_details` | `true` | bool | `new_tasks`; да | Скрывать детали уведомлений |
| `compact_view` | `false` | bool | `new_tasks`; да | Компактный каталог |

<a id="database-reference"></a>
## 21. Все таблицы и колонки

Снимок SQLAlchemy metadata, без паролей и содержимого строк. Типы указаны в общей нотации ORM: DATETIME компилируется в PostgreSQL timestamp, JSON-вариант — в JSONB. `NULL=нет` — требование хранения, но Python-default может заполнить поле при вставке. FK в таблице указывает целевой столбец; межworkspace-ссылки часто составные и включают workspace_id. Полный порядок миграции — [начальная миграция](migrations/versions/721e69034285_initial_inventory_schema.py), актуальные модели — [models.py](app/db/models.py). Индексы определены там же; справочник не является инструкцией вручную создавать таблицы.

### `inventory.admin_audit`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `actor_id` | `VARCHAR(36)` | да | — |
| `action` | `VARCHAR(100)` | нет | — |
| `reason` | `VARCHAR(500)` | да | — |
| `request_id` | `VARCHAR(36)` | да | — |
| `details` | `JSON` | нет | — |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

### `inventory.agreements`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `user_id` | `VARCHAR(36)` | нет | inventory.users.id |
| `agreement_type` | `VARCHAR(50)` | нет | — |
| `agreement_version` | `VARCHAR(50)` | нет | — |
| `acceptance_context` | `JSON` | нет | — |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `user_id, agreement_type, agreement_version`.

### `inventory.confirmations`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `proposal_id` | `VARCHAR(36)` | нет | inventory.proposals.id |
| `proposal_revision` | `INTEGER` | нет | — |
| `receipt_id` | `VARCHAR(36)` | нет | inventory.review_receipts.id |
| `operation_id` | `VARCHAR(36)` | нет | unique |
| `status` | `VARCHAR(20)` | нет | — |
| `actions` | `JSON` | нет | — |
| `dependencies` | `JSON` | нет | — |
| `fencing_token` | `BIGINT` | нет | — |
| `result` | `JSON` | нет | — |
| `error_code` | `VARCHAR(60)` | да | — |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.proposals.workspace_id, inventory.review_receipts.workspace_id, inventory.workspaces.id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `workspace_id, id`; `operation_id`; `workspace_id, proposal_id, proposal_revision`.

### `inventory.deletion_tombstones`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `entity_type` | `VARCHAR(30)` | нет | — |
| `entity_id` | `VARCHAR(36)` | нет | — |
| `purged_at` | `DATETIME` | да | — |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.workspaces.id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `workspace_id, id`; `entity_type, entity_id`.

### `inventory.field_evidence`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `entity_type` | `VARCHAR(30)` | нет | — |
| `entity_id` | `VARCHAR(36)` | нет | — |
| `field_key` | `VARCHAR(100)` | нет | — |
| `source_type` | `VARCHAR(20)` | нет | — |
| `media_id` | `VARCHAR(36)` | да | — |
| `region` | `JSON` | да | — |
| `raw_value` | `TEXT` | да | — |
| `normalized_value` | `JSON` | нет | — |
| `verification_state` | `VARCHAR(20)` | нет | — |
| `proposal_id` | `VARCHAR(36)` | нет | — |
| `model_revision` | `VARCHAR(100)` | да | — |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.workspaces.id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `workspace_id, id`.

### `inventory.gpu_slots`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `id` | `INTEGER` | нет | PK |
| `owner` | `VARCHAR(36)` | да | — |
| `task_id` | `VARCHAR(36)` | да | — |
| `fencing_token` | `BIGINT` | нет | — |
| `state` | `VARCHAR(20)` | нет | — |
| `lease_until` | `DATETIME` | да | — |
| `heartbeat_at` | `DATETIME` | да | — |

### `inventory.idempotency_keys`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `user_id` | `VARCHAR(36)` | нет | — |
| `workspace_id` | `VARCHAR(36)` | нет | — |
| `operation_scope` | `VARCHAR(120)` | нет | — |
| `key` | `VARCHAR(200)` | нет | — |
| `request_hash` | `VARCHAR(80)` | нет | — |
| `response` | `JSON` | нет | — |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `user_id, workspace_id, operation_scope, key`.

### `inventory.inbox_notifications`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `user_id` | `VARCHAR(36)` | нет | inventory.users.id |
| `dedupe_key` | `VARCHAR(80)` | нет | unique |
| `title` | `VARCHAR(255)` | нет | — |
| `body` | `TEXT` | нет | — |
| `subjects` | `JSON` | нет | — |
| `read_at` | `DATETIME` | да | — |
| `dismissed_at` | `DATETIME` | да | — |
| `snoozed_until` | `DATETIME` | да | — |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.workspaces.id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `workspace_id, id`; `dedupe_key`.

### `inventory.ingestion_batches`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `created_by` | `VARCHAR(36)` | нет | inventory.users.id |
| `name` | `VARCHAR(255)` | нет | — |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.workspaces.id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `workspace_id, id`.

### `inventory.item_aliases`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `item_id` | `VARCHAR(36)` | нет | inventory.items.id |
| `alias` | `VARCHAR(255)` | нет | — |
| `normalized_alias` | `VARCHAR(255)` | нет | — |
| `scope` | `VARCHAR(20)` | нет | — |
| `created_by` | `VARCHAR(36)` | нет | inventory.users.id |
| `source` | `VARCHAR(30)` | нет | — |
| `active` | `BOOLEAN` | нет | — |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.items.workspace_id, inventory.workspaces.id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `workspace_id, id`.

### `inventory.items`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `name` | `VARCHAR(255)` | нет | — |
| `primary_category` | `VARCHAR(30)` | нет | — |
| `secondary_categories` | `JSON` | нет | — |
| `tracking_mode` | `VARCHAR(20)` | нет | — |
| `base_unit_id` | `VARCHAR(30)` | да | — |
| `quantity_step` | `NUMERIC(20, 6)` | нет | — |
| `attributes` | `JSON` | нет | — |
| `attributes_schema_version` | `VARCHAR(30)` | нет | — |
| `barcode` | `VARCHAR(100)` | да | — |
| `brand` | `VARCHAR(255)` | да | — |
| `model` | `VARCHAR(255)` | да | — |
| `tags` | `JSON` | нет | — |
| `user_description` | `TEXT` | да | — |
| `generated_description` | `TEXT` | да | — |
| `description_model_revision` | `VARCHAR(100)` | да | — |
| `privacy_policy` | `VARCHAR(20)` | нет | — |
| `lifecycle` | `VARCHAR(20)` | нет | — |
| `created_by` | `VARCHAR(36)` | нет | inventory.users.id |
| `archived_at` | `DATETIME` | да | — |
| `deleted_at` | `DATETIME` | да | — |
| `search_revision` | `BIGINT` | нет | — |
| `indexed_revision` | `BIGINT` | нет | — |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.workspaces.id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

CHECK: `primary_category != 'document' OR privacy_policy = 'local_only'`; `quantity_step > 0`.

Составная уникальность: `workspace_id, id`.

### `inventory.locations`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `parent_id` | `VARCHAR(36)` | да | inventory.locations.id |
| `name` | `VARCHAR(255)` | нет | — |
| `description` | `TEXT` | да | — |
| `kind` | `VARCHAR(30)` | нет | — |
| `default_privacy_policy` | `VARCHAR(20)` | да | — |
| `archived_at` | `DATETIME` | да | — |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.locations.workspace_id, inventory.workspaces.id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

CHECK: `kind != 'system_unspecified' OR parent_id IS NULL`.

Составная уникальность: `workspace_id, id`.

### `inventory.login_attempts`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `key` | `VARCHAR(64)` | нет | PK |
| `failures` | `INTEGER` | нет | — |
| `window_start` | `DATETIME` | нет | — |

### `inventory.lots`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `item_id` | `VARCHAR(36)` | нет | inventory.items.id |
| `lot_kind` | `VARCHAR(20)` | нет | — |
| `label` | `VARCHAR(255)` | да | — |
| `serial_number` | `VARCHAR(255)` | да | — |
| `manufacturer_batch` | `VARCHAR(255)` | да | — |
| `parent_lot_id` | `VARCHAR(36)` | да | inventory.lots.id |
| `acquired_at` | `DATE` | да | — |
| `manufactured_on` | `DATE` | да | — |
| `opened_on` | `DATE` | да | — |
| `expiry_on` | `DATE` | да | — |
| `expiry_precision` | `VARCHAR(20)` | нет | — |
| `expiry_raw_text` | `VARCHAR(255)` | да | — |
| `after_opening_amount` | `INTEGER` | да | — |
| `after_opening_unit` | `VARCHAR(10)` | да | — |
| `effective_expiry_on` | `DATE` | да | — |
| `expiry_derivation` | `VARCHAR(30)` | нет | — |
| `expiry_generation` | `INTEGER` | нет | — |
| `privacy_policy` | `VARCHAR(20)` | нет | — |
| `attributes` | `JSON` | нет | — |
| `attributes_schema_version` | `VARCHAR(30)` | нет | — |
| `archived_at` | `DATETIME` | да | — |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.items.workspace_id, inventory.workspaces.id, inventory.lots.workspace_id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `workspace_id, id`.

### `inventory.maintenance_jobs`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `created_by` | `VARCHAR(36)` | нет | inventory.users.id |
| `kind` | `VARCHAR(30)` | нет | — |
| `status` | `VARCHAR(20)` | нет | — |
| `manifest` | `JSON` | нет | — |
| `manifest_hash` | `VARCHAR(80)` | нет | — |
| `result` | `JSON` | нет | — |
| `expires_at` | `DATETIME` | да | — |
| `not_before` | `DATETIME` | да | — |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.workspaces.id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `workspace_id, id`.

### `inventory.media_assets`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `object_key` | `VARCHAR(500)` | нет | unique |
| `sha256` | `VARCHAR(64)` | нет | — |
| `mime` | `VARCHAR(100)` | нет | — |
| `size_bytes` | `BIGINT` | нет | — |
| `width` | `INTEGER` | да | — |
| `height` | `INTEGER` | да | — |
| `duration_seconds` | `NUMERIC(20, 6)` | да | — |
| `state` | `VARCHAR(20)` | нет | — |
| `kind` | `VARCHAR(30)` | нет | — |
| `privacy_policy` | `VARCHAR(20)` | нет | — |
| `client_preprocessed` | `BOOLEAN` | нет | — |
| `manifest` | `JSON` | нет | — |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.workspaces.id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `object_key`; `workspace_id, id`.

### `inventory.media_bindings`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `media_id` | `VARCHAR(36)` | нет | inventory.media_assets.id |
| `entity_type` | `VARCHAR(30)` | нет | — |
| `entity_id` | `VARCHAR(36)` | нет | — |
| `role` | `VARCHAR(30)` | нет | — |
| `ordinal` | `INTEGER` | нет | — |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.media_assets.workspace_id, inventory.workspaces.id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `workspace_id, media_id, entity_type, entity_id, role`; `workspace_id, id`.

### `inventory.model_cooldowns`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `quota_key` | `VARCHAR(255)` | нет | unique |
| `reason` | `VARCHAR(50)` | нет | — |
| `reset_at` | `DATETIME` | да | — |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `quota_key`.

### `inventory.model_deployments`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `logical_name` | `VARCHAR(50)` | нет | unique |
| `actual_model_id` | `VARCHAR(255)` | нет | — |
| `endpoint_ref` | `VARCHAR(50)` | нет | — |
| `credential_ref` | `VARCHAR(50)` | да | — |
| `trust_domain` | `VARCHAR(20)` | нет | — |
| `enabled` | `BOOLEAN` | нет | — |
| `maintenance` | `BOOLEAN` | нет | — |
| `capabilities` | `JSON` | нет | — |
| `checked_at` | `DATETIME` | да | — |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `logical_name`.

### `inventory.operation_entries`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `operation_id` | `VARCHAR(36)` | нет | inventory.operations.id |
| `entity_type` | `VARCHAR(40)` | нет | — |
| `entity_id` | `VARCHAR(36)` | нет | — |
| `event_type` | `VARCHAR(40)` | нет | — |
| `before_version` | `BIGINT` | да | — |
| `after_version` | `BIGINT` | нет | — |
| `before_state` | `JSON` | да | — |
| `after_state` | `JSON` | нет | — |
| `quantity_delta` | `NUMERIC(20, 6)` | да | — |
| `unit_id` | `VARCHAR(30)` | да | — |
| `from_location_id` | `VARCHAR(36)` | да | — |
| `to_location_id` | `VARCHAR(36)` | да | — |
| `ordinal` | `INTEGER` | нет | — |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

### `inventory.operations`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `actor_user_id` | `VARCHAR(36)` | нет | inventory.users.id |
| `confirmation_id` | `VARCHAR(36)` | нет | unique, inventory.confirmations.id |
| `type` | `VARCHAR(40)` | нет | — |
| `payload_schema_version` | `VARCHAR(30)` | нет | — |
| `normalized_payload` | `JSON` | нет | — |
| `request_hash` | `VARCHAR(80)` | нет | — |
| `reverses_operation_id` | `VARCHAR(36)` | да | inventory.operations.id |
| `status` | `VARCHAR(20)` | нет | — |
| `applied_at` | `DATETIME` | нет | — |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.workspaces.id, inventory.operations.workspace_id, inventory.confirmations.workspace_id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `workspace_id, id`; `confirmation_id`.

### `inventory.outbox_events`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `event_type` | `VARCHAR(40)` | нет | — |
| `entity_id` | `VARCHAR(36)` | нет | — |
| `entity_version` | `BIGINT` | нет | — |
| `payload` | `JSON` | нет | — |
| `attempts` | `INTEGER` | нет | — |
| `next_attempt_at` | `DATETIME` | нет | — |
| `lease_until` | `DATETIME` | да | — |
| `lease_owner` | `VARCHAR(36)` | да | — |
| `processed_at` | `DATETIME` | да | — |
| `error_code` | `VARCHAR(60)` | да | — |
| `status` | `VARCHAR(20)` | нет | — |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.workspaces.id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `workspace_id, id`.

### `inventory.proposal_revisions`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `proposal_id` | `VARCHAR(36)` | нет | inventory.proposals.id |
| `revision` | `INTEGER` | нет | — |
| `document` | `JSON` | нет | — |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.workspaces.id, inventory.proposals.workspace_id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `proposal_id, revision`; `workspace_id, id`.

### `inventory.proposals`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `task_id` | `VARCHAR(36)` | да | inventory.tasks.id |
| `created_by` | `VARCHAR(36)` | нет | inventory.users.id |
| `revision` | `INTEGER` | нет | — |
| `status` | `VARCHAR(20)` | нет | — |
| `source` | `VARCHAR(20)` | нет | — |
| `actions` | `JSON` | нет | — |
| `dependencies` | `JSON` | нет | — |
| `document` | `JSON` | нет | — |
| `review_hash` | `VARCHAR(80)` | нет | — |
| `source_proposals` | `JSON` | нет | — |
| `user_changes` | `JSON` | нет | — |
| `warnings` | `JSON` | нет | — |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.workspaces.id, inventory.tasks.workspace_id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `workspace_id, id`.

### `inventory.reminder_occurrences`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `rule_id` | `VARCHAR(36)` | нет | inventory.reminder_rules.id |
| `subject_lot_id` | `VARCHAR(36)` | нет | inventory.lots.id |
| `generation` | `VARCHAR(80)` | нет | — |
| `threshold_key` | `VARCHAR(50)` | нет | — |
| `occurrence_time` | `DATETIME` | нет | — |
| `status` | `VARCHAR(20)` | нет | — |
| `dedupe_key` | `VARCHAR(80)` | нет | unique |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.reminder_rules.workspace_id, inventory.lots.workspace_id, inventory.workspaces.id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `workspace_id, id`; `dedupe_key`.

### `inventory.reminder_rules`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `owner_user_id` | `VARCHAR(36)` | нет | inventory.users.id |
| `values` | `JSON` | нет | — |
| `enabled` | `BOOLEAN` | нет | — |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.workspaces.id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `workspace_id, id`.

### `inventory.review_receipts`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `user_id` | `VARCHAR(36)` | нет | inventory.users.id |
| `proposal_id` | `VARCHAR(36)` | нет | inventory.proposals.id |
| `proposal_revision` | `INTEGER` | нет | — |
| `observed_review_hash` | `VARCHAR(80)` | нет | — |
| `confirmed_values_hash` | `VARCHAR(80)` | нет | — |
| `explicit_changes` | `JSON` | нет | — |
| `confirmation_source` | `VARCHAR(20)` | нет | — |
| `client_request_id` | `VARCHAR(36)` | нет | — |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.proposals.workspace_id, inventory.workspaces.id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `workspace_id, id`.

### `inventory.runtime_controls`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `key` | `VARCHAR(100)` | нет | PK |
| `value` | `JSON` | нет | — |

### `inventory.sessions`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `user_id` | `VARCHAR(36)` | нет | inventory.users.id |
| `refresh_token_hash` | `VARCHAR(64)` | нет | unique |
| `family_id` | `VARCHAR(36)` | нет | — |
| `expires_at` | `DATETIME` | нет | — |
| `revoked_at` | `DATETIME` | да | — |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `refresh_token_hash`.

### `inventory.settings_revisions`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `revision` | `INTEGER` | нет | unique |
| `values` | `JSON` | нет | — |
| `actor_id` | `VARCHAR(36)` | да | inventory.users.id |
| `reason` | `VARCHAR(500)` | нет | — |
| `previous_revision` | `INTEGER` | да | — |
| `status` | `VARCHAR(30)` | нет | — |
| `components_pending` | `JSON` | нет | — |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `revision`.

### `inventory.stock_balances`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `lot_id` | `VARCHAR(36)` | нет | inventory.lots.id |
| `location_id` | `VARCHAR(36)` | нет | inventory.locations.id |
| `quantity` | `NUMERIC(20, 6)` | да | — |
| `quantity_state` | `VARCHAR(20)` | нет | — |
| `last_confirmed_at` | `DATETIME` | да | — |
| `last_confirmed_by` | `VARCHAR(36)` | да | inventory.users.id |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.workspaces.id, inventory.locations.workspace_id, inventory.lots.workspace_id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

CHECK: `quantity IS NULL OR quantity >= 0`; `(quantity_state IN ('exact','estimated') AND quantity IS NOT NULL) OR (quantity_state IN ('unknown','not_applicable') AND quantity IS NULL)`.

Составная уникальность: `workspace_id, id`; `workspace_id, lot_id, location_id`.

### `inventory.task_attempts`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `task_id` | `VARCHAR(36)` | нет | inventory.tasks.id |
| `fencing_token` | `BIGINT` | нет | — |
| `stage` | `VARCHAR(50)` | нет | — |
| `model_id` | `VARCHAR(255)` | нет | — |
| `trust_domain` | `VARCHAR(20)` | нет | — |
| `completed_at` | `DATETIME` | да | — |
| `error_code` | `VARCHAR(60)` | да | — |
| `diagnostics` | `JSON` | нет | — |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.tasks.workspace_id, inventory.workspaces.id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `workspace_id, id`.

### `inventory.tasks`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `created_by` | `VARCHAR(36)` | нет | inventory.users.id |
| `client_request_id` | `VARCHAR(36)` | нет | — |
| `parent_task_id` | `VARCHAR(36)` | да | inventory.tasks.id |
| `batch_id` | `VARCHAR(36)` | да | inventory.ingestion_batches.id |
| `input_mode` | `VARCHAR(30)` | нет | — |
| `input_text` | `TEXT` | да | — |
| `media_ids` | `JSON` | нет | — |
| `audio_media_id` | `VARCHAR(36)` | да | inventory.media_assets.id |
| `context` | `JSON` | нет | — |
| `requested_privacy` | `VARCHAR(20)` | нет | — |
| `effective_privacy` | `VARCHAR(20)` | нет | — |
| `status` | `VARCHAR(30)` | нет | — |
| `stage` | `VARCHAR(50)` | нет | — |
| `status_version` | `BIGINT` | нет | — |
| `queue_class` | `VARCHAR(20)` | нет | — |
| `priority` | `INTEGER` | нет | — |
| `config_revision` | `INTEGER` | нет | — |
| `config_snapshot` | `JSON` | нет | — |
| `config_snapshot_hash` | `VARCHAR(80)` | нет | — |
| `model_route_revision` | `VARCHAR(100)` | нет | — |
| `prompt_revision` | `VARCHAR(80)` | нет | — |
| `output_schema_version` | `VARCHAR(30)` | нет | — |
| `attempt_count` | `INTEGER` | нет | — |
| `external_calls` | `INTEGER` | нет | — |
| `external_cost` | `NUMERIC(20, 6)` | да | — |
| `processing_seconds` | `NUMERIC(20, 6)` | нет | — |
| `next_attempt_at` | `DATETIME` | да | — |
| `deadline_at` | `DATETIME` | да | — |
| `lease_owner` | `VARCHAR(36)` | да | — |
| `lease_until` | `DATETIME` | да | — |
| `fencing_token` | `BIGINT` | нет | — |
| `heartbeat_at` | `DATETIME` | да | — |
| `progress` | `JSON` | нет | — |
| `proposal_id` | `VARCHAR(36)` | да | — |
| `result` | `JSON` | нет | — |
| `cancel_requested_at` | `DATETIME` | да | — |
| `error_code` | `VARCHAR(60)` | да | — |
| `completed_at` | `DATETIME` | да | — |
| `workspace_id` | `VARCHAR(36)` | нет | inventory.tasks.workspace_id, inventory.ingestion_batches.workspace_id, inventory.media_assets.workspace_id, inventory.workspaces.id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `workspace_id, id`; `workspace_id, created_by, client_request_id`.

### `inventory.users`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `login` | `VARCHAR(255)` | нет | unique |
| `password_hash` | `TEXT` | нет | — |
| `app_role` | `VARCHAR(10)` | нет | — |
| `status` | `VARCHAR(20)` | нет | — |
| `locale` | `VARCHAR(10)` | нет | — |
| `timezone` | `VARCHAR(100)` | нет | — |
| `auth_version` | `INTEGER` | нет | — |
| `preferences` | `JSON` | нет | — |
| `preferences_version` | `INTEGER` | нет | — |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

Составная уникальность: `login`.

### `inventory.workspace_memberships`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `workspace_id` | `VARCHAR(36)` | нет | PK, inventory.workspaces.id |
| `user_id` | `VARCHAR(36)` | нет | PK, inventory.users.id |
| `role` | `VARCHAR(20)` | нет | — |
| `status` | `VARCHAR(20)` | нет | — |

### `inventory.workspaces`

| Колонка | SQL-тип | NULL | Ключ / ссылка |
|---|---|---|---|
| `name` | `VARCHAR(255)` | нет | — |
| `owner_user_id` | `VARCHAR(36)` | нет | inventory.users.id |
| `id` | `VARCHAR(36)` | нет | PK |
| `version` | `BIGINT` | нет | — |
| `created_at` | `DATETIME` | нет | — |
| `updated_at` | `DATETIME` | нет | — |

<a id="error-reference"></a>
## 22. Коды ошибок

Ниже перечислены **111 статически объявленных кодов** из require/DomainError/ModelError/PersistedConflict в текущих исходниках. Это справочник диагностики, не закрытый enum протокола: возможны коды стадий, валидации и новые версии сервера. Клиент всегда имеет fallback для неизвестного кода и сохраняет request_id. HTTP status и retryability определяются контекстом, поэтому нельзя выводить их только из подписи.

| Код | Сообщения / смысл в коде |
|---|---|
| `ADMISSION_LIMIT` | Слишком много ожидающих задач. |
| `ALREADY_CONFIRMED` | Подтверждённое предложение нельзя отменить. / После принятия подтверждения отмена задачи невозможна. / Предложение уже недоступно для правок. / Предложение уже подтверждено или отменено. / Эта ревизия подтверждена с другими значениями. |
| `ALREADY_INITIALIZED` | Владелец уже создан. |
| `ATTEMPT_BUDGET` | Бюджет распознавания исчерпан. |
| `AUDIO_TOO_LONG` | Запись превышает допустимую длительность. |
| `AUTH_REQUIRED` | Неверный логин или пароль. / Требуется вход. |
| `BALANCE_NOT_FOUND` | В выбранном месте нет этой партии. |
| `CAPABILITY_CHECK_REQUIRED` | Сначала проверьте deployment. |
| `CLOUD_CONNECTION` | Сообщение зависит от контекста. |
| `CONFIRMATION_RETRY_REQUIRED` | Повторите прежнее подтверждение, не создавая новое намерение. / Повторите принятое подтверждение. |
| `DAILY_QUOTA` | Сообщение зависит от контекста. |
| `DECODED_IMAGE_TOO_LARGE` | Слишком много пикселей в изображении. |
| `DEPENDENCY_UNAVAILABLE` | Не удалось сохранить файл. |
| `DIAGNOSTIC_ONLY` | Диагностический повтор нельзя включить в подтверждение. / Диагностический повтор нельзя применять к учёту. |
| `EMBEDDING_DIMENSION` | Неверная размерность BGE-M3. |
| `EMPTY_AUDIO` | В записи нет звука. |
| `EMPTY_TASK` | Добавьте текст, фото или аудио. |
| `EXPORT_EXPIRED` | Срок доступа к экспорту истёк. / Экспорт больше недоступен. |
| `EXTERNAL_CALL_BUDGET` | Бюджет внешних вызовов исчерпан. |
| `FIELD_REQUIRED` | Выберите исходное место. / Выберите объект в форме. / Выберите режим обработки. / Выберите целевое место. / Название или временное имя должно быть сохранено в форме. / Название нельзя очистить. / Укажите название места. / Укажите название. / Укажите положительное количество. / Это поле нельзя очистить. |
| `FIELD_VALIDATION_FAILED` | Поправка имеет неверный тип. |
| `FILE_TOO_LARGE` | Файл превышает лимит. |
| `FORBIDDEN` | Источник браузерного запроса не разрешён. / Недостаточно прав для изменения. / Требуются права администратора. |
| `GPU_BUSY` | Дождитесь завершения текущей обработки. |
| `IDEMPOTENCY_KEY_REQUIRED` | Передайте Idempotency-Key. |
| `IDEMPOTENCY_KEY_REUSED` | client_request_id использован для другого запроса. / Ключ уже использован для другого запроса. |
| `INDIVIDUAL_DUPLICATE` | Для другого экземпляра создайте отдельную карточку. / Уникальный экземпляр нельзя размножить. |
| `INSUFFICIENT_STOCK` | В выбранном месте недостаточно остатка. |
| `INVALID_ACTIONS` | Идентификаторы действий повторяются. |
| `INVALID_ATTRIBUTES` | Атрибуты не входят в схему категории. / Неверный тип свойства. |
| `INVALID_BATCH` | Предложения повторяются. |
| `INVALID_BATCH_SIZE` | Недопустимый размер общего предложения. |
| `INVALID_CATEGORY` | Неизвестная категория. |
| `INVALID_CONFIRMATION_STATE` | Повтор разрешён только после технического сбоя. |
| `INVALID_CURSOR` | Курсор относится к другому поиску. / Курсор относится к другому списку. / Некорректный курсор поиска. / Некорректный курсор. |
| `INVALID_FILTER` | Неизвестный фильтр наличия. |
| `INVALID_IMAGE_REGION` | Неверные координаты фрагмента. / Область пересекает подпись, поля или разные фотографии. |
| `INVALID_LOCATION_TREE` | В дереве мест возник бы цикл. / Нельзя вложить место в недоступного родителя. / Нельзя перенести содержимое в архивируемое место. / Превышена глубина дерева. |
| `INVALID_LOTS` | Партии не должны повторяться. |
| `INVALID_MODEL_INPUT` | Сообщение зависит от контекста. |
| `INVALID_MODEL_JSON` | Сообщение зависит от контекста. |
| `INVALID_POLICY` | Неизвестный режим обработки. |
| `INVALID_PREVIEW` | Предпросмотр недоступен. |
| `INVALID_PURGE_SCOPE` | Выберите от 1 до 100 карточек. |
| `INVALID_QUANTITY` | Выберите известный или неизвестный остаток. / Для присутствия количество не применяется. / Количество должно быть неотрицательным и кратным шагу. / Количество не соответствует состоянию. / Уникальный экземпляр имеет остаток 0 или 1. / Шаг должен быть положительным. |
| `INVALID_REQUEST` | Фотографии повторяются. |
| `INVALID_SETTING` | Lease должен превышать два heartbeat. / Задержки повторов несовместимы. / Значение вне допустимого диапазона. / Значение отсутствует в списке. / Интервалы обновления несовместимы. / Модель не зарегистрирована. / Не хватает контекста для входа. / Неверный тип параметра. / Параметр не может быть пустым. / Параметр указан несколько раз. / Предельное время worker должно иметь запас к вызову модели. / Файл превышает лимит всей задачи. |
| `INVALID_TASK_STATE` | Переход состояния запрещён. / Повтор доступен после остановки обработки. / Приоритет меняется только у ожидающей задачи. / Ручное продолжение сейчас недоступно. |
| `INVALID_TIMEZONE` | Неизвестный часовой пояс. |
| `INVALID_UNIT_CONVERSION` | Выберите известную единицу. / Единицы несовместимы. / Размер упаковки должен быть положительным. |
| `INVALID_VERSION_KEY` | Неизвестная настройка версии. / Неизвестная сущность версии. |
| `ITEM_DELETED` | Карточка уже удалена. |
| `ITEM_INACTIVE` | Карточка недоступна для этой операции. |
| `ITEM_NOT_ARCHIVED` | Можно восстановить только архивную карточку. |
| `LOCAL_CONNECTION` | Сообщение зависит от контекста. |
| `LOCAL_TIMEOUT` | Сообщение зависит от контекста. |
| `LOCATION_ARCHIVED` | Место находится в архиве. |
| `LOCATION_NOT_EMPTY` | Выберите место для переноса содержимого. |
| `LOT_ARCHIVED` | Партия находится в архиве. |
| `LOT_INCOMPATIBLE` | Отличающиеся упаковки требуют новой партии. / Партии отличаются по сроку, варианту или приватности. / Режимы приватности партий различаются. |
| `LOT_MISMATCH` | Партия относится к другой карточке. |
| `MEDIA_PURGED` | Материал недоступен. / Файл недоступен. |
| `MERGE_NOT_ALLOWED` | Экземпляры и присутствие не объединяются. |
| `MODEL_CONTEXT_LIMIT` | Сообщение зависит от контекста. |
| `MODEL_COOLDOWN` | Внешняя квота временно недоступна. |
| `MODEL_CREDENTIALS` | Сообщение зависит от контекста. |
| `MODEL_DISABLED` | Модель отключена. |
| `MODEL_IMAGE_LIMIT` | Payload изображения превышает лимит runtime. / Изображение не помещается в безопасный лимит модели. / Изображение превышает безопасное разрешение runtime. |
| `MODEL_NOT_CONFIGURED` | Внешняя модель не настроена. / Задайте параметры LiteLLM в окружении. |
| `MODEL_REFUSAL` | Сообщение зависит от контекста. |
| `MODEL_REVISION_UNAVAILABLE` | Маршрут модели изменён: создайте явный повтор с новой конфигурацией. |
| `MODEL_UNAVAILABLE` | Сообщение зависит от контекста. |
| `NOT_FOUND` | Deployment не найден. / Задание не найдено. / Карточка не найдена. / Карточка удалена. / Общее предложение не найдено. / Объект не найден в рабочей области. / Объект не найден. / Операция не найдена. / Операция удалена. / Правило не найдено. / Предложение удалено. / Рабочая область не найдена. / Ревизия не найдена. / Уведомление не найдено. / Экспорт ещё не готов. / Экспорт не найден. |
| `NOT_INITIALIZED` | Выполните bootstrap. |
| `NO_IMAGES` | Для коллажа нужны изображения. |
| `ONE_IMAGE_REQUIRED` | Локальная модель принимает только одно изображение. |
| `POLICY_IMPACT_REQUIRED` | Подтвердите последствия сокращения хранения. |
| `POLICY_RESTRICTED` | Внешняя передача запрещена. / Документ обрабатывается только локально. / Партия наследует локальную обработку карточки. / Передача отменена действующей политикой. |
| `PRESENCE_DUPLICATE` | Присутствие должно иметь одно место. |
| `PROCESSING_BUDGET` | Бюджет времени исчерпан. |
| `PROMPT_REVISION_UNAVAILABLE` | Шаблон изменён: создайте явный повтор с новой конфигурацией. |
| `PURGE_ALREADY_STARTED` | Физическая очистка уже началась; отменить её нельзя. |
| `RATE_LIMIT` | Сообщение зависит от контекста. |
| `REVERSE_CONFLICT` | После операции данные изменились. Требуется отдельная корректировка. |
| `REVIEW_UPDATE_REQUIRED` | Исходная форма общего подтверждения изменилась. / Исходные версии изменились. / Область удаления изменилась; создайте новый предпросмотр. / Устраните отмеченные поля. / Учёт изменился. Проверьте обновлённую форму. / Учёт уже изменился. |
| `SESSION_EXPIRED` | Отсутствует токен сессии. / Повтор токена: войдите заново. / Сессия истекла. / Сессия недоступна. |
| `SPLIT_NOT_ALLOWED` | Этот режим учёта не допускает дробление. |
| `SPLIT_REQUIRED` | Перед открытием одной из нескольких упаковок выделите её в отдельную партию. |
| `STAGE_BUDGET` | Бюджет стадии исчерпан. |
| `SYSTEM_LOCATION` | Системное место нельзя архивировать. / Системное место нельзя изменять. / Системное место нельзя перемещать. |
| `TASK_MEDIA_LIMIT` | Общий размер материалов превышен. / Слишком много фотографий. |
| `TASK_PURGED` | Материалы задачи удалены. / Материалы исходной задачи удалены. |
| `UNKNOWN_FIELD` | Выберите доступное решение формы. / Для этой операции свойства карточки недоступны. / Поле не входит в схему действия. / Свойство не входит в схему категории. |
| `UNKNOWN_MODEL_CANDIDATE` | Выберите существующую карточку. / Модель выбрала неизвестный объект. |
| `UNKNOWN_MODEL_PRICE` | Для денежного лимита нужна проверенная стоимость deployment. |
| `UNKNOWN_PROMPT` | Промпт не зарегистрирован. |
| `UNKNOWN_QUANTITY` | Неизвестное количество переносится только целиком. / Сначала установите количество или переместите целиком. |
| `UNKNOWN_QUANTITY_MERGE` | В назначении уже есть эта партия. Установите общий остаток или выделите новую партию. / Назначение содержит неизвестный остаток. / Неизвестный остаток нужно сохранить отдельной партией. / Сначала установите количество. |
| `UNKNOWN_SETTING` | Неизвестный или защищённый параметр. / Неизвестный параметр. |
| `UNKNOWN_UNIT` | Выберите единицу измерения или учёт присутствия. |
| `UNSUPPORTED_AUDIO` | Сообщение зависит от контекста. / Текущая локальная Gemma не поддерживает аудио. Запись сохранена; используйте текст или ручную форму. |
| `UNSUPPORTED_INPUT` | Тип материала не соответствует полю задачи. |
| `UNSUPPORTED_MEDIA_TYPE` | MIME не соответствует WAV. / MIME не соответствует содержимому изображения. / Анимация не поддерживается. / Нужна запись WAV PCM 16 bit, один или два канала. / Повреждённая запись WAV. / Поддерживаются JPEG, PNG и WebP. / Файл не является безопасным изображением. |
| `UNSUPPORTED_MODALITY` | Сообщение зависит от контекста. |
| `UNSUPPORTED_OPERATION` | Операция не поддерживается. |
| `UNSUPPORTED_SETTING` | Сообщение зависит от контекста. |
| `USER_RATE_LIMIT` | Слишком много попыток входа. Повторите через несколько минут. |
| `VERSION_CONFLICT` | Deployment уже изменён. / Задание удаления изменилось. / Задача уже изменилась. / Исходное предложение недоступно. / Модель изменилась во время проверки. / Настройки уже изменены. / Настройки уже изменились. / Правило уже изменилось. / Предпросмотр изменился. / Предпросмотр уже изменился. / Профиль уже изменился. / Состояние GPU изменилось. / Уведомление изменилось. / Учёт или правила расчёта изменились после подтверждения. / Форма уже изменилась. |
| `WEAK_PASSWORD` | Пароль должен содержать минимум 12 символов. |
| `WORKSPACE_MISMATCH` | Рабочие области запроса не совпадают. / Рабочие области не совпадают. |
| `WORKSPACE_REQUIRED` | Передайте X-Workspace-ID или workspace_id. |

Дополнительные коды инфраструктурной оболочки/стадий включают INTERNAL_ERROR, FIELD_VALIDATION_FAILED, MEDIA_PREPARATION_FAILED, UNSUPPORTED_AUDIO и ITEM_DELETED; они обрабатываются по тому же общему envelope/status. Ошибки провайдера не показывают его сырой ответ пользователю.


## Дополнение 23–24 сентября: текущий web и task DTO

Рефакторинг текущего React-клиента описан в [отчёте frontend](docs/EPIC_FRONTEND_REFACTOR.md). Клиент подготавливает JPEG до 1600 px и WAV PCM16 mono 16 kHz. Это транспортные файлы: backend по-прежнему независимо проверяет медиа и формирует один ограниченный коллаж для модели. Миниатюры скачиваются с авторизацией; отсутствие thumbnail не запускает фоновую загрузку оригинала.

К ответу `task_view` добавлены `input_mode`, nullable `parent_task_id` и `title`. Title содержит первые 160 символов пользовательского текста после нормализации пробелов либо русское название типа ввода. Состояния и `progress/timing` не изменены. Доступ остаётся ограничен рабочей областью. GET архивированного места теперь отвечает 404 `NOT_FOUND` вместо JSON null.
