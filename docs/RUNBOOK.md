# Эксплуатация

## Первая установка

1. Скопировать `.env.example` в `.env.local`, задать независимые случайные `POSTGRES_PASSWORD`, `MINIO_PASSWORD`, `INV_JWT_SECRET` (не меньше 32 символов), Origin и HTTPS cookie policy. Файл не публикуется.
2. `docker compose --env-file .env.local build api web`.
3. `docker compose --env-file .env.local up -d postgres redis qdrant minio`.
4. `docker compose --env-file .env.local run --rm api alembic upgrade head`.
5. `docker compose --env-file .env.local run --rm api python -m app.cli bootstrap --login owner --storage`.
6. `docker compose --env-file .env.local up -d --force-recreate api cpu ml scheduler web`.
7. Проверить `/health/ready`, войти через web, создать место и ручную карточку, подтвердить форму. Проверить наличие операции в журнале.

На Linux обеспечить доступ контейнеров к доверенному inference endpoint. Ollama по умолчанию указан через `host.docker.internal`; не открывать его в Интернет. Данные PostgreSQL/MinIO и резервные копии находятся в отдельных Docker volumes. `down` сохраняет volumes; `down -v` удаляет данные и не применяется при обновлении.

Compose не публикует PostgreSQL, Redis, Qdrant и MinIO. Бакет создаётся приватным через bootstrap. API проверяет workspace для каждой загрузки/выдачи медиа. Ссылки не раскрывают S3 object keys. Web nginx проксирует `/api/v1/` и `/health/`.

## Локальный профиль на этом компьютере

Отдельный `deploy/compose.test.yml`: PostgreSQL 55432, Redis 56379, Qdrant 56333, MinIO 59000, только `127.0.0.1`. В нём нет привязки к старым `data/postgres_data` или `data/minio_data` и не предусмотрены постоянные named volumes. `stop` сохраняет контейнеры и их данные; после `down`/пересоздания сохранность тестовых данных и повторное подключение анонимных volumes не гарантируются. Не используйте этот профиль для личного архива.

`.env.local` содержит локальные настройки и предоставленный владельцем ключ доверенного LiteLLM. Старый `.env` не перезаписан. Конфигурация читает `.env`, затем `.env.local`, затем переменные процесса. В контейнерном профиле адреса зависимостей переопределяются внутренними именами сервисов.

## Модели и граница доверия

`gemma3:4b` через Ollama — text/image, ровно один image input. `bge-m3:latest` — 1024 измерения. `local-gemma-4-e4b` на `https://as.rsmu.ru/litellm` признан владельцем доверенным сервером и проверен с `input_audio` WAV. Ключ находится только в `.env.local`. Обработка аудио и коллажа выполняется последовательно. Поддержка одновременного audio+image не заявляется.

```powershell
uv run python -m app.cli model-health
uv run python -m scripts.probe_audio --url https://as.rsmu.ru/litellm --model local-gemma-4-e4b --key-env-file .env.local
```

Пример с тишиной не отправляет личные данные. Для проверки разрешённой записи добавить `--wav tests/cases/case_1/audio.wav`. После успешной проверки доверенного endpoint устанавливаются `INV_LOCAL_AUDIO_TRUSTED=true`, `INV_LOCAL_AUDIO_VERIFIED=true`, URL/model/key. После изменения развёртывания повторить проверку. Если bootstrap выполнен до настройки аудио, зарегистрировать deployment через повторяемую команду `sync-models` и проверить его через административный API.

Настройки `INV_CLOUD_*` относятся к внешнему AI. Они независимы от доверенного аудио endpoint. Cloud выключен по умолчанию. Его включение не разрешает отправку local-only карточек, партий, мест или медиа. Неизвестная чувствительность запрещает cloud. Реальные внешние провайдеры в этой приёмке не использовались; HTTP-контракты и ошибки проверены локально. Инференс никогда не получает SQL или полномочий записывать учёт.

## Обновление и миграция

Сначала создать резервную копию. Остановить API/воркеры, обновить код/образ, выполнить Alembic, затем запустить процессы. `alembic check` подтверждает совпадение схемы с моделями. SQLAlchemy `create_all` используется только в SQLite тестах.

После замены API пересоздать также nginx: `docker compose --env-file .env.local up -d --force-recreate api cpu ml scheduler web`. Иначе работающий nginx может продолжать обращаться к прежнему внутреннему IP контейнера. Это проверено отдельным повторным контейнерным smoke.

Старая схема `public` сохранена. Для переноса карточек выполнить `python -m app.cli legacy-preview --workspace-id UUID`, затем проверить предложения. Старые распознанные данные не объявляются автоматически подтверждёнными.

Все шесть исходных промптов проверяет `python -m app.cli verify-prompts`. Изменение промптов не подменяет snapshot ожидающей задачи: старая задача получает безопасную ручную форму, повтор создаётся явно с новой ревизией.

## Очередь и зависимые сервисы

- После потери Redis scheduler перечитает PostgreSQL и заново отправит accepted/queued задачи, подтверждения и outbox. Удалять задачи PostgreSQL нельзя.
- Принятое подтверждение повторяется через `/confirmations/{id}/retry`: сохраняются confirmation/operation IDs, ML не повторяется.
- Ошибка Qdrant не откатывает учёт. Outbox повторяется с задержкой; dead letters и отставание видны в `/admin/metrics`. Поиск возвращает текстовые совпадения с предупреждением при недоступном GPU/индексе.
- После неизвестного таймаута GPU slot остаётся `quarantined`. Убедиться, что физическое выполнение на inference сервере остановлено. Затем `/admin/gpu/recover` с текущим fencing token, `physical_inference_stopped:true` и причиной. Истечение lease не доказывает остановку модели.
- Пауза очереди запрещает новый dispatch; уже начатые вызовы завершаются с fencing-проверкой.
- Диагностический replay и его потомки не могут применяться к учёту. Логи содержат request ID, код ошибки и длительность, без ключей, фотографий и сырого текста.

Переиндексация: `POST /api/v1/admin/search/reindex` с авторизацией, workspace и Idempotency-Key. Создаётся теневая коллекция, сравниваются текущие версии PostgreSQL, затем alias переключается атомарно. Все workspace пересобираются вместе, фильтрация по workspace сохраняется. Старую коллекцию можно удалить отдельно после проверки; она не источник истины.

## Настройки

API возвращает желаемую и эффективную ревизии; полный будущий UI обязан показывать их раздельно. Изменения concurrency/hard timeout применяются после перезапуска CPU/ML/scheduler. Подтверждение запуска от всех этих компонентов переводит ревизию в effective. Экстренный запрет внешней передачи действует сразу. Rollback создаёт новую ревизию, не стирая историю. Покрытие текущего UI ограничено [EPIC_FRONTEND.md](EPIC_FRONTEND.md) и T-57 в [ACCEPTANCE.md](ACCEPTANCE.md).

Снижение срока хранения сначала проходит dry-run и подтверждение последствий. Автоудаление архива по умолчанию выключено. Отсрочка физического удаления по умолчанию 30 дней. До начала hard purge можно отменить задание. Операционные исправления не создают отдельного обучающего набора при `datasets.enabled=false`.

## Backup и restore

```sh
python -m app.cli backup --output /app/data/backups/2026-09-17
python -m app.cli deletion-ledger --output /app/data/backups/current-deletions.json
```

Копия включает согласованный `pg_dump` снимок схемы `inventory`, manifest/контрольные суммы и приватные медиа. Экспорт пользователя JSON/CSV/ZIP не заменяет backup. Секреты развёртывания резервируются владельцем отдельно. Расписание запуска backup и выгрузку копий на другой диск настраивать на хосте; пример команды выше предназначен для ежедневного cron/Task Scheduler. Регулярно обновлять отдельный `current-deletions.json`, особенно после удаления, и хранить рядом с копиями вне основного диска.

Восстановление выполняется в отдельную пустую БД и выделенное хранилище, при остановленном приложении:

```sh
python -m app.cli restore --input /app/data/backups/2026-09-17 --deletion-ledger /app/data/backups/current-deletions.json
alembic upgrade head
```

Перед записью проверяются пути и контрольные суммы. Старый снимок дополняется актуальным журналом удалений: удалённые после копии объекты повторно очищаются до выдачи клиентам. Сессии и временные экспорты отзываются. Затем восстановить Qdrant из PostgreSQL. Пробный backup/restore на двух временных PostgreSQL БД проверен автоматическим тестом.

Сброс пароля владельца: `python -m app.cli reset-password --login owner`. Пароль вводится без эха; действовавшие сессии отзываются.

## Проверки перед обновлением

С 21.09 inference имеет отдельный безопасный предел: `INV_LOCAL_IMAGE_MAX_SIDE=512`, `INV_LOCAL_IMAGE_MAX_BYTES=262144`. Повысить сторону до 1024 можно только после проверки памяти конкретного runtime; это не заменяет visual-token budget llama.cpp. Настройка коллажа ограничивается deployment-пределом при создании snapshot. Фотографии карточек и миниатюры имеют отдельные размеры. Контракт загрузки/thumbnail/progress — [API_MEDIA_PROGRESS.md](API_MEDIA_PROGRESS.md).

`INV_LOG_LEVEL=INFO` задаёт уровень структурированных логов. Сырые ответы модели и ключи не выводятся даже при DEBUG. История стадий находится в task.progress и административном trace; OpenTelemetry collector не нужен для запуска.

`uv run pytest -q`, `uv run ruff check app tests/unit tests/integration scripts`, `uv run mypy`, `uv run alembic check`, `uv run python -m app.cli verify-prompts`; во frontend — `npm test`, `npm run lint`, `npm run build`.

Для PostgreSQL concurrency задать `INV_TEST_POSTGRES_URL` отдельной тестовой БД. Для backup/restore — `INV_RUN_BACKUP_TEST=1` с запущенным `deploy/compose.test.yml`. Для живых моделей — `python -m scripts.smoke_stack` (несколько минут; выделенная БД/бакет/коллекция удаляются после теста). Результаты находятся в `docs/*smoke.json`; сырое распознавание и ключи в них не записываются.

Физическая потеря Redis проверяется opt-in `INV_TEST_REDIS_LOSS=1`: тест очищает только выделенную DB13 этого тестового сервиса. Для контейнерной проверки overlay `deploy/compose.verify.yml` использует отдельную `inventory_verify`, Redis DB14, бакет/коллекцию inventory-verify и web-порт 18080. Создать эту тестовую БД, выполнить миграции overlay, затем `python -m scripts.smoke_containers`; повторный запуск с существующим тестовым владельцем — `--skip-bootstrap`. Скрипт содержит только фиксированный пароль изолированного тестового владельца и не предназначен для рабочей БД.

`python -m scripts.smoke_media_memory` проверяет две параллельные подготовки большого JPEG в собранном образе `inventarizator:local`, в отдельном контейнере без сети и swap с лимитом 256 MiB. Для освобождения памяти после тестов: `docker compose -f deploy/compose.test.yml -f deploy/compose.verify.yml stop`. Существующие контейнеры, их файловые слои и подключённые volumes сохраняются; это не резервное копирование.

Полный справочник конфигурации, API и БД — [DOCS.md](../DOCS.md); результат сверки документации и отличия от исходного ТЗ — [EPIC_DOCUMENTATION.md](EPIC_DOCUMENTATION.md).
