# 📦 Инвентаризатор — Backend API

Backend API сервис для умного учета личных вещей, медикаментов и расходников с использованием AI-ассистента, JWT-авторизации, иерархических локаций, ARQ-очередей и интеграции с LLM через LiteLLM.

## 🚀 Архитектура и Документация

Текущая версия проекта значительно выросла и состоит из нескольких ключевых подсистем. Подробная документация разбита на логические модули в директории `docs/`:

1. **[API Эндпоинты (API_ENDPOINTS.md)](docs/API_ENDPOINTS.md)**
   Полная спецификация REST API: авторизация, управление вещами, иерархия локаций, RAG-поиск и взаимодействие с задачами.
   
2. **[Схема Базы Данных (DATABASE_SCHEMA.md)](docs/DATABASE_SCHEMA.md)**
   Описание таблиц PostgreSQL (Пользователи, Локации, Вещи, Задачи) и векторной базы Qdrant. Перечисления (Enums) и настройки.

3. **[ML Пайплайн и Очереди (ML_PIPELINE_AND_ARQ.md)](docs/ML_PIPELINE_AND_ARQ.md)**
   Глубокое описание работы LangGraph, использования VLM моделей (`local-gemma`, `cloud-gemma`, `gemini-3.5`), структуры ARQ-очередей (`high_priority`, `bulk`, `cron_only`) и обхода блокировок DPI через форсированные монолитные запросы поверх LiteLLM.

4. **[Пользовательские сценарии (USER_FLOWS_AND_HITL.md)](docs/USER_FLOWS_AND_HITL.md)**
   Описание бизнес-логики: Human-in-the-Loop (HITL), алгоритм дедупликации (правило 100% совпадения), Умная Группировка, и система автоматических напоминаний и сроков годности.

---

## 🛠 Установка и запуск (Local Development)

### 1. Требования
- Python 3.12+
- Node.js (для фронтенда Vite)
- Docker & Docker Compose (PostgreSQL, Qdrant, Redis, LiteLLM)

### 2. Запуск инфраструктуры
Для старта базы данных, кэша и шлюза LiteLLM:
```bash
cd litellm
docker compose up -d
```

### 3. Переменные окружения (`.env`)
Создайте файл `.env` в корневой директории:
```env
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=inventory_db
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

JWT_SECRET_KEY=your_super_secret
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

LITELLM_API_BASE=http://localhost:4000
LITELLM_MASTER_KEY=sk-inventory-internal-key

MAX_TASKS_PER_USER=5
```

### 4. Запуск FastAPI Бэкенда
```bash
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 9005 --reload
```

### 5. Запуск ARQ Очередей
Вам потребуется запустить несколько процессов воркеров для обеспечения Fair-Share балансировки (в отдельных терминалах PowerShell):

```powershell
# Приоритетная очередь (HITL ответы)
$env:PYTHONPATH="."; $env:ARQ_QUEUE_NAME="high_priority"; python -m arq backend.app.services.worker.WorkerSettings

# Стандартная очередь
$env:PYTHONPATH="."; $env:ARQ_QUEUE_NAME="default"; python -m arq backend.app.services.worker.WorkerSettings

# Bulk-очередь (для массовых загрузок)
$env:PYTHONPATH="."; $env:ARQ_QUEUE_NAME="bulk"; python -m arq backend.app.services.worker.WorkerSettings

# Cron-воркер (Сборщик мусора, напоминания)
$env:PYTHONPATH="."; $env:ARQ_QUEUE_NAME="cron_only"; $env:ARQ_ENABLE_CRON="true"; python -m arq backend.app.services.worker.WorkerSettings
```

### 6. Запуск Frontend
```bash
cd frontend
npm install
npm run dev
```

---

## 🎯 Статус проекта
- [x] Полностью реализована архитектура ARQ и LangGraph.
- [x] Интегрирован LiteLLM с форсированием монолитных REST запросов для стабильного обхода DPI.
- [x] Подключены локальные модели (Gemma-4-e4b для Gatekeeper).
- [x] Разработан пользовательский интерфейс (Dynamic ItemForm, Schedule Tab).
- [x] Работают умные расписания (Cron-based Reminders).
- [x] Гибридный поиск (Qdrant BM25 + BGE-M3).
