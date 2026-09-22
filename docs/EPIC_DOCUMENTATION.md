# Эпик документации и сверки требований

Дата: 21.09.2026. Задача владельца: подробный README с полным деревом/назначением файлов, полная DOCS.md и исчерпывающее ТЗ frontend; дополнительно перепроверить по AGENT.md, RUNBOOK, REFACTOR_REPORT, EPIC-отчётам, API_MEDIA_PROGRESS и ACCEPTANCE.

## Результат и область проверки

- [README.md](../README.md) — назначение, запуск, профили ресурсов, полный аннотированный список текущих поставляемых файлов и отдельное описание локальных игнорируемых материалов.
- [DOCS.md](../DOCS.md) — текущая архитектура, предметные правила, HTTP flows/DTO, эксплуатация; полный справочник маршрутов, схем запросов, команд, Config, runtime settings, таблиц/колонок и ошибок.
- [FRONTEND_SPEC.md](FRONTEND_SPEC.md) — новое задание на интерфейс: экраны, состояния, авторизация, все команды, thumbnail/media, WAV, polling, HITL, batches, настройки, обслуживание, доступность, архитектура, 50 F-сценариев и связь со всеми T-01…T-80.
- [frontend/README.md](../frontend/README.md) — инструкция существующего клиента вместо общего Vite template.

Старый корневой `docs.md` содержал прежний BRD; он сохранён в локальный `data/docs-before-documentation-20260921.md`. Новый файл называется **DOCS.md**, исключение `docs.md` удалено из `.gitignore`. На Windows это одна регистронезависимая файловая позиция: пара конкурирующих docs.md/DOCS.md не создавалась.

Проверка — чтение требований/отчётов и сверка с текущими handlers, Pydantic/JSON Schema, Config, реестром настроек, ORM, Compose и тестами. Для навигации по коду использовался CodeGraph. Содержимое файлов с секретами не переносилось. Это аудит документации и контрактов, **не новый полный эксплуатационный прогон и не доказательство выполнения всех разделов исходного ТЗ**.

## Сопоставление источников

| Источник | Что перепроверено и где отражено |
|---|---|
| AGENT.md §0–1 | Личный доверенный сервер, обязательный HITL, invariants; DOCS §1/5, frontend §1 |
| §2–3 | Компоненты/источники истины/границы ML; DOCS §2, README architecture |
| §4 | Item/lot/balance, единицы, unknown, дерево, сроки; DOCS §4/21, frontend §7–8; дополнительные поля отдельно B-09 |
| §5 | Все 18 команд и единый путь ручного/AI подтверждения; DOCS §7/18, frontend §7 |
| §6 | Durable tasks, retries, cancel/fencing и state; DOCS §8, frontend §10 |
| §7 | Revision/hash/dirty changes, one-click, batch, controls; DOCS §7, frontend §11–12; gaps B-04/B-08 |
| §8–9 | Upload, EXIF, privacy, один image, collage manifest; DOCS §9, frontend §9; актуальный предел 512 px |
| §10 | Проверенный WAV, последовательные audio/image, segmentation; DOCS §9, frontend §9.3 |
| §11–12 | Граница local/external, snapshots, quotas/budgets; DOCS §5/9/12; реальные внешние провайдеры не объявлены протестированными |
| §13 | Роли workers, default/bulk, lease/quarantine, scheduler; DOCS §8/12, frontend §10/15 |
| §14 | Exact/FTS/hybrid/hydration/outbox; DOCS §10, ADR-002; алгоритм sparse отличается от рекомендованного FastEmbed |
| §15 | Только expiry, timezone/quiet hours/generations, in_app; DOCS §11, frontend §14 |
| §16 | Config/runtime/preferences, defaults, pending/effective, impact; DOCS §3/12/19/20, frontend §15 |
| §17 | Retention, archive/deleted/purged, shared media/dataset; DOCS §13/15, frontend §16 |
| §18 | Все реализованные маршруты и точные тела; DOCS §16–18; отсутствующие optional push endpoints не объявлены работающими |
| §19 | ETag, batch polling, принятие отдельно от apply, фоновые вкладки; DOCS §8, frontend §10–12 |
| §20 | Транзакции, idempotency, durable recovery, backup/deletion ledger; DOCS §6/8/13/21, RUNBOOK |
| §21 | Web/native auth, workspace, роль, Origin, private media; DOCS §5/6, frontend §2/5/17 |
| §22 | Экспорт, logs/timing/health, эксплуатационные метрики; DOCS §12–15; полный dashboard metrics — B-13 |
| §23 | Фактическая компактная структура, схемы и сохранённые prompts; README tree, DOCS §2/9/14 |
| §24 | Результаты эпиков отделены от нового плана frontend; REFACTOR_REPORT, frontend §21 |
| §25 | Все T-01…T-80 сопоставлены с обязанностью клиента; точные доказательства остаются в ACCEPTANCE |
| §26–27 | DoD/поставка/запуск без ложной полной приёмки UI; README, DOCS §14/15, frontend §20/21 |
| §28–30 | Уточнения владельца, граница доверия, ADR при изменении контракта; frontend §1/19, действующие ADR |
| RUNBOOK.md | Порты/профили, bootstrap, модели, backup/restore, остановка тестовых контейнеров; исправлена формулировка сохранности данных |
| REFACTOR_REPORT.md | 186 backend тестов и реальные smoke относятся к предшествующему прогону; 31 UI тест — к прежней совместимости |
| EPIC_DOMAIN.md | Команды/количества/сроки, preview/apply и конкуренция; DOCS §4/7/18 |
| EPIC_FRONTEND.md | Ограниченный исторический React v1, без нового E2E; новый документ не объявляет его полным интерфейсом |
| EPIC_MAINTENANCE.md | Retention impact, purge grace/shared links, restore ledger, отключённые функции, бюджет 6 вызовов |
| EPIC_MEDIA_PROGRESS.md | 512 px/256 KiB, thumbnail 256, normalized 1600, CPU память, пары и времена стадий |
| API_MEDIA_PROGRESS.md | Точные private photos DTO, client_preprocessed, task.progress/current/history, has_unknown_quantity |
| ACCEPTANCE.md | Сохранены оговорки mock/real, T-31 unknown, T-40 unit, T-49 simulated crash, T-57 UI partial, T-64 backend-only |

## Выявленные расхождения и решения в документации

| Область | Факт сверки | Решение |
|---|---|---|
| Стартовый personal-профиль AGENT | Пример CPU concurrency 4 и total attempts 4 отличается от действующих 2 и 6; audio segments объясняют увеличение бюджета | Defaults берутся из registry; пример ТЗ не переопределяет текущую конфигурацию |
| Размер collage | 1600×1200 в AGENT — демонстрация manifest, а не безопасный вход слабой модели | Зафиксированы deployment 512 px/262144 bytes, normalized 1600 и thumbnail 256 как разные назначения |
| Прогресс | Пример completed_stages не соответствует текущим current/history; процент и ETA пока null | Документирован реальный DTO и честный elapsed без имитации |
| Review example | strength_mg/options_ref/условные поля и строки readonly_fields из примера не проходят текущую строгую schema | Пример не копируется в wire-код; указаны attributes.strength, объекты readonly и B-08 |
| Task readback | Нет исходного ввода/media/context в TaskView | B-03; невозможность восстановления composer только по GET Task названа явно |
| Inbox UI | Нет thumbnails/сортировок/категории/места в summary response | B-04; миниатюры Item/Search не смешиваются с inbox |
| Каталог/история | UUID cursor, нет общего total и произвольной сортировки; include_archived не archive-only | B-05, запрещено представлять локальную фильтрацию страницы как полный результат |
| Лимиты | Schema maxItems и runtime admission limits различаются; api.max_page_size/max_poll_ids и polling defaults не управляют всеми handlers | DOCS фиксирует actual limits; B-01 — синхронизация capabilities/validators |
| Права клиента | `/me` не содержит membership role | B-02; app_role не заменяет workspace permission |
| Модель данных | Некоторые поля исходной концепции не имеют командного контракта; режим нельзя сменить update_item | B-09; frontend не сохраняет невалидные произвольные attributes |
| Качество ML | Auto detail-pass/калибровка/дополнительный fallback не реализованы | Не обещаны; T-31 допускает unknown. Реальные smoke не названы оценкой всего набора |
| Поиск | Собственный sparse BM25 с фиксированной опорной длиной + Qdrant IDF | Ссылка на ADR-002; не объявлен эквивалент FastEmbed/corpus-average |
| Опциональные функции | Push/dataset/cache/raw-payload diagnostics отсутствуют | Readonly/disabled отображение; отсутствующие endpoints не попали в current API |
| GC | Preview orphan-only, run полного regular_cleanup | B-12; нельзя обещать удаление лишь объектов preview |
| Settings rollback | Нет impact_confirmed в Rollback body | B-11 и допустимый validate/PATCH текущих значений для сокращения retention |
| Отдельные UI функции | Нет списка exports, точного unread count, attach/detach фото | B-06/B-07/B-10; временное поведение явно ограничено |
| Метрики | Системные counts/lag есть, полного набора §22.3/VRAM/ETA нет | B-13; OTel не обязателен для текущего progress |
| Тестовые volumes | В test Compose нет постоянных named volumes; stop сохраняет контейнеры, down/recreate не гарантирует доступность прежних данных | Исправлены RUNBOOK и формулировка REFACTOR_REPORT, без изменения контейнеров |
| UI pending | RUNBOOK утверждал поведение UI шире подтверждённого T-57 | Уточнены гарантия API и требование будущего UI |

AGENT.md не переписан под более узкую реализацию: исходные требования сохраняются. Наличие backend tests для каждой строки матрицы не означает полного выполнения всех UI/эксплуатационных/качество-ML требований. Новые B-01…B-13 — список зависимостей полного интерфейса, не скрытая декларация их реализации.

## Воспроизводимые проверки документации

Справочники DOCS получены из текущих объектов FastAPI/Pydantic, SQLAlchemy metadata, Config defaults и registry, без переноса значений секретного окружения. Перед публикацией сгенерированные OpenAPI/JSON Schema были сравнены с `app.openapi()` и реестром COMMANDS; сами служебные JSON-артефакты согласно указанию владельца в коммит не включены. README tree проверяется по фактическим неигнорируемым файлам `rg --files --hidden`, а не списку удалённых исторических путей Git.

Контрольные числа: **85 путей, 93 HTTP-операции**, 39 OpenAPI component schemas (две стандартные схемы validation исключены из подробных таблиц запросов), **18 команд, 36 прикладных таблиц, 67 административных и 4 пользовательских настройки**. Справочник ошибок содержит 111 статически объявленных кодов; это не закрытый enum всех возможных будущих ошибок.

Дополнительно проверяются существование относительных Markdown-ссылок, явные anchors, синтаксис JSON-примеров и отсутствие незаполненных генераторных вставок; документационные изменения проверяются `git diff --check`. Полный pytest/живые модели/контейнеры в этом эпике заново не запускались: менялись документация и правило её включения в Git, прикладное поведение не менялось. Исторические **186 passed** остаются результатом предыдущего backend прогона, а не этой сверки.

Результат автоматической сверки исходного полного дерева: **229 файлов, 16 Markdown-документов, 155 внутренних ссылок, 21 JSON-пример**; после фильтрации поставки в README перечислено **104 файла**. Все 81 упомянутые в ACCEPTANCE имена тестовых функций найдены; присутствуют все строки T-01…T-80, F-01…F-50 и B-01…B-13. OpenAPI и все 18 схем команд совпали с кодом до исключения служебных JSON-артефактов. Проверка исходных шести промптов и `git diff --check` прошли. Предупреждения Git о возможном LF→CRLF не являются ошибками содержимого.

## Сопровождение

При изменении endpoint/DTO/команды сначала обновить схемы и DOCS, затем связанные F/B-сценарии и ACCEPTANCE при наличии нового теста. При добавлении/удалении файла обновить дерево README. Изменённые экспериментальные defaults сверять с registry, фактический deployment — с effective settings. Если B-gap закрыт, записать endpoint/schema revision и проверку в новый отчёт; не удалять исходное требование без решения владельца.
