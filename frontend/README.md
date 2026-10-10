# Web-интерфейс «Инвентаризатор»

React 19, React Router, Vite 8. Текущий вход: `src/main.jsx` → `src/App.jsx`. `src/v1` остаётся историческим исходником и не подключается к приложению. [ТЗ](../docs/FRONTEND_SPEC.md), [отчёт рефакторинга](../docs/EPIC_FRONTEND_REFACTOR.md).

## Запуск

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Vite слушает `http://localhost:5173`; если порт занят, печатает выбранный следующий порт. По умолчанию proxy настроен на уже запущенный проверочный стек: API `127.0.0.1:58000`, Origin `http://localhost:18080`. Для основного `docker-compose.yml` перед запуском dev:

```powershell
$env:INVENTORY_API_URL = 'http://127.0.0.1:8000'
$env:INVENTORY_API_ORIGIN = 'http://localhost:8080'
npm.cmd run dev
```

Origin должен входить в `INV_CORS_ORIGINS` API. Proxy работает только в dev; nginx контейнера использует внутренний `api:8000`. Секреты не задаются через Vite-переменные. Вход, ручные операции и загрузка файлов работают при локальном HTTP по Wi-Fi: UUID генерируются через `crypto.getRandomValues`, если `crypto.randomUUID` недоступен. Запись микрофона требует localhost/HTTPS или отдельного тестового исключения Chrome; загрузка готового аудио остаётся доступна. [Настройка Android по Wi-Fi](../docs/RUNBOOK.md#локальная-проверка-с-android-по-wi-fi).

## Проверка и обновление

```powershell
npm.cmd run lint
npm.cmd test
npm.cmd run build
```

Vitest использует один worker для экономии памяти. Тесты хранятся локально и исключены из Git по требованию владельца; в чистой поставке без локальных тестов доступны lint/build. Сборка создаёт `dist/`; изменение исходников само по себе не обновляет запущенный nginx-контейнер.

Для основного compose из корня проекта: `docker compose up -d --build --no-deps web`. Проверочный стек использует готовый образ `inventarizator-web:latest`; сначала `docker build -t inventarizator-web:latest frontend`, затем `docker compose -p inventory-refactor-test -f deploy/compose.test.yml -f deploy/compose.verify.yml up -d --no-deps web`. Команды не требуют удаления volumes. Backend обновляется отдельно после проверки изменений API.

## Файлы текущего приложения

| Файл или группа | Назначение |
|---|---|
| `src/main.jsx`, `src/App.jsx`, `src/index.css` | Монтирование, защищённые маршруты и scoped providers, общие стили и мобильная навигация |
| `src/api/client.js` | Авторизация, refresh, idempotency headers, scope cancellation, ошибки и пагинация |
| `src/utils/id.js` | UUID v4 для запросов и UI, включая локальный HTTP без randomUUID |
| `src/api/commands.js` | Ручные команды, версии объектов и пакетные операции |
| `src/api/confirmations.js` | Повторы принятого подтверждения и ожидание применения |
| `src/api/images.js`, `media.js`, `tasks.js` | Ограниченная очередь миниатюр, загрузка файлов, batch polling |
| `src/api/admin.js`, `maintenance.js`, `notifications.js`, `review.js` | Совместимые специализированные HTTP-адаптеры; новые экраны преимущественно используют общий клиент |
| `src/contexts/AuthContext.jsx` | Профиль, вход/выход, выбор доступного инвентаря |
| `src/contexts/TaskContext.jsx`, `NotificationContext.jsx` | Scoped состояние задач и уведомлений, жизненный цикл polling |
| `src/contexts/ThemeContext.jsx`, `ToastContext.jsx` | Тема и временные сообщения интерфейса |
| `src/hooks/useResource.js`, `usePaged.js` | Чтение одного ресурса/страниц, ошибки, отмена и обновление |
| `src/hooks/useJob.js`, `useMutation.js` | Ожидание фоновой работы и повтор неизменной мутации |
| `src/hooks/usePhotoUpload.js` | Последовательная загрузка ручных фото и сохранение ключа при сетевом повторе |
| `src/hooks/useDragAutoScroll.js` | Прокрутка ближайшей области у края во время перетаскивания, остановка при завершении |
| `src/hooks/useItemDrag.js` | Общий drag-and-drop вещей в каталоге и раскрытом содержимом мест |
| `src/hooks/useTaskRefresh.js` | Обновление открытой карточки и содержимого места при смене версии задачи |
| `src/components/ItemReviewStatus.jsx` | Цветной текстовый статус проверки и переход к задаче или форме |
| `src/components/ItemFieldsSettings.jsx` | Необязательные поля и пользовательские определения текущего инвентаря |
| `src/components/operations/EditItemModal.jsx` | Единая форма существующей вещи с фото, свойствами, сроками, количеством и местами |
| `src/utils/editItem.js`, `src/utils/itemFields.js` | Команды атомарной правки, пересчёт пар, вложенные значения и видимость полей |
| `src/components/OcrInput.jsx` | Явный запуск OCR, наблюдение, отмена, редактируемый полный текст |
| `src/components/operations/MergeItemsModal.jsx` | Серверный preview, выбор места, смена направления и подтверждение объединения |
| `src/components/Layout.jsx`, `ConfirmationStatus.jsx` | Навигация, область страницы, состояние принятого сохранения |
| `src/components/SettingsPanel.jsx`, `Reminders.jsx` | Реестр настроек и правила напоминаний |
| `src/components/ui/Help.jsx`, `src/utils/settingsHelp.js` | Справка по наведению/фокусу/нажатию, подробные объяснения всех настроек и технические ограничения |
| `src/components/StageRing.jsx`, `src/utils/progress.js` | Равные цветные секции этапов, фактические состояния без имитации ETA |
| `src/components/review/ReviewField.jsx` | Контролы серверной схемы; неизвестные блокируются |
| `src/components/review/ChangePreview.jsx` | Подписанные изменения до/после и свёрнутые технические данные |
| `src/components/ui/Button.jsx`, `Input.jsx`, `Select.jsx` | Общие подписанные элементы форм; кнопки по умолчанию не submit |
| `src/components/ui/Card.jsx`, `Skeleton.jsx`, `Modal.jsx` | Карточка, загрузка, нативное диалоговое окно |
| `src/components/ui/NumberStepper.jsx` | Шаги десятичного количества без float |
| `src/components/ui/Thumbnail.jsx`, `MediaCapture.jsx`, `TreeView.jsx` | Private thumbnails, подготовка фото/голоса, дерево мест |
| `src/components/PendingItems.jsx`, `src/utils/tasks.js` | Совместимость со старыми задачами без catalog_item_ids; новые реальные карточки не дублируются |
| `src/components/ProcessingStatus.jsx`, `ConfirmationStatus.jsx` | Живые воркеры, паузы/карантин и наблюдение за сохранением без дубликатов |
| `src/components/operations/ReceiveStockModal.jsx` | Ручное добавление/пополнение вещи с фото и контекстом места |
| `src/components/operations/StockOperationsModal.jsx` | Расход, перенос, уточнение остатка, подтверждение наличия |
| `src/components/operations/ItemOperationsModal.jsx` | Архив/восстановление, синонимы; редактирование передаётся общей форме |
| `src/components/operations/LotOperationsModal.jsx` | Изменение, разделение и объединение партий |
| `src/components/operations/LocationOperationsModal.jsx` | Создание, изменение, перенос и архив места |
| `src/components/operations/ReverseOperationModal.jsx` | Переход из диалога к единому серверному review отмены |
| `src/pages/Login.jsx`, `Items.jsx`, `ItemDetail.jsx`, `Locations.jsx` | Вход, каталог, карточка, дерево и содержимое места |
| `src/pages/Capture.jsx`, `Tasks.jsx` | Создание задачи, списки/детали задач и группы загрузки |
| `src/pages/Items.jsx`, `Locations.jsx` | Накопительный выбор над поиском и раскрытие вещей у места с миниатюрами |
| `src/pages/ReviewInbox.jsx`, `ReviewForm.jsx` | Проверка, объединение предложений, сохранение и конфликты |
| `src/pages/History.jsx` | Журнал, детали операции и предпросмотр реверса |
| `src/pages/Notifications.jsx`, `Settings.jsx`, `DataPage.jsx` | Уведомления, профиль, настройки, экспорт и удаление |
| `src/pages/admin/AdminLayout.jsx`, `AdminSettings.jsx` | Ограничение раздела администратором, системные настройки |
| `src/pages/admin/AdminModels.jsx`, `AdminQueues.jsx` | Проверка моделей, обслуживание, очереди и восстановление GPU |
| `src/pages/admin/AdminMaintenance.jsx`, `TaskTrace.jsx` | Health, метрики, аудит, reindex/GC и диагностика задачи |
| `src/utils/quantity.js`, `locations.js`, `labels.js`, `media.js` | Decimal/пары, проверка дерева, подписи и преобразование медиа |
| `src/utils/review.js`, `display.js` | Значения и видимость полей review, строгие типы чисел, представление свойств |
| `src/utils/captureDraft.js` | Передача фото и текста из ручной формы в composer в памяти вкладки; очистка при смене scope |
| `index.html`, `public/favicon.svg`, `public/icons.svg` | HTML и статические ресурсы |
| `vite.config.js`, `eslint.config.js`, `.prettierrc.json` | Dev proxy, тесты, линтер и форматирование |
| `package.json`, `package-lock.json` | Зависимости и воспроизводимые npm-команды |
| `Dockerfile`, `nginx.conf`, `.dockerignore`, `.gitignore` | Контейнерная сборка, SPA/API proxy, исключения локальных файлов |

1600 px — ограничение клиентской загрузки. Коллаж для модели формируется сервером с меньшим лимитом. Подтверждённая операция отображается только после receipt `applied`, а не после HTTP 202. Проверки Chromium на работающем стеке, включая мобильную ширину, AI и обрывы HTTP-ответов, описаны в [EPIC_BROWSER_QA.md](../docs/EPIC_BROWSER_QA.md). Полная F-матрица и аппаратная Android-приёмка этим прогоном не заменяются.

Фото источников в review открываются в отдельном диалоге по нажатию на миниатюру, с авторизованной загрузкой. Проверка 13 личных кейсов и оставшаяся блокировка модельной очереди описаны в [EPIC_REAL_CASE_QA.md](../docs/EPIC_REAL_CASE_QA.md).

После уточнения владельца формы упрощены: ручное добавление с фото, создание вещи прямо внутри места, фотографии и эмодзи мест, раздел «Где и сколько» вместо управления партиями. Сохранение ручной формы и архивирование не вызывают LLM. Подробности — [EPIC_SIMPLE_UX.md](../docs/EPIC_SIMPLE_UX.md).

Новые вещи из фото/голоса сразу создаются в каталоге. После распознавания они жёлтые и участвуют в поиске и напоминаниях без обязательного открытия review; ошибки красные, активная обработка синяя. «Проверить позже» сохраняет запись. Подтверждение verify_item исправляет ту же вещь без повторного поступления. Изменения существующих вещей требуют подтверждения. В фильтрах доступны статус и сортировки по имени, дате создания, сроку и приоритету ошибки. Контракт и проверка — [EPIC_UNCONFIRMED_ITEMS.md](../docs/EPIC_UNCONFIRMED_ITEMS.md).
