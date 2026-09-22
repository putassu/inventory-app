"""Серверные команды: миграции выполняет Alembic, не create_all."""

import argparse
import asyncio
import getpass
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import select, text, update

from app.application.auth import PASSWORDS, bootstrap
from app.config import get_config
from app.db.models import ModelDeployment, Session, User
from app.db.session import session_factory
from app.domain.common import canonical, utcnow


async def initialize(args):
    password = os.environ.get("INV_BOOTSTRAP_PASSWORD") or getpass.getpass(
        "Пароль владельца (не менее 12 символов): "
    )
    async with session_factory()() as db, db.begin():
        result = await bootstrap(db, args.login, password, args.timezone)
    if args.storage:
        from app.infrastructure.storage import Storage

        await Storage().initialize()
    print(canonical(result))


async def reset_password(args):
    password = getpass.getpass("Новый пароль владельца: ")
    if len(password) < 12:
        raise ValueError("Минимальная длина — 12 символов")
    async with session_factory()() as db, db.begin():
        user = await db.scalar(select(User).where(User.login == args.login).with_for_update())
        if not user:
            raise ValueError("Пользователь не найден")
        user.password_hash = PASSWORDS.hash(password)
        user.auth_version += 1
        await db.execute(update(Session).where(Session.user_id == user.id).values(revoked_at=utcnow()))
    print("Пароль обновлён; прежние access-токены отозваны.")


def schemas(args):
    from app.domain.contracts import CollageManifest, ExportDocument, ReviewDocument
    from app.domain.schemas import COMMANDS, Extraction, ManualConfirm
    from app.main import create_app

    path = Path(args.output)
    path.mkdir(parents=True, exist_ok=True)
    documents = {
        "openapi.json": create_app().openapi(),
        "extraction.v1.json": Extraction.model_json_schema(),
        "command.v1.json": ManualConfirm.model_json_schema(),
        "review.v1.json": ReviewDocument.model_json_schema(),
        "collage.v1.json": CollageManifest.model_json_schema(),
        "export.v1.json": ExportDocument.model_json_schema(),
    }
    for name, schema in COMMANDS.items():
        documents[f"command.{name}.v1.json"] = schema.model_json_schema()
    for name, document in documents.items():
        (path / name).write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Схемы сохранены: {path}")


def verify_prompts(args):
    manifest = json.loads(Path("docs/prompt-baseline.json").read_text(encoding="utf-8"))
    mismatches = [
        name
        for name, checksum in manifest.items()
        if not Path(name).exists() or hashlib.sha256(Path(name).read_bytes()).hexdigest() != checksum
    ]
    if mismatches:
        raise ValueError("Изменены исходные промпты: " + ", ".join(mismatches))
    print(f"Все {len(manifest)} исходных промптов совпадают побайтно.")


async def model_health(args):
    from app.infrastructure.models import LocalAdapter

    config = get_config()
    result = {
        "local": await LocalAdapter().capabilities(),
        "embeddings": await LocalAdapter().capabilities(config.embedding_model),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


async def sync_models(args):
    config = get_config()
    definitions = [
        ("local_vlm", config.local_model, "ollama", "local", None),
        ("privacy_asr", config.local_model, "ollama", "local", None),
        ("embeddings", config.embedding_model, "ollama", "local", None),
        (
            "local_audio",
            config.local_audio_model or "unconfigured",
            "local_audio",
            "local",
            "local_audio_key",
        ),
        ("cloud_primary", config.cloud_model or "unconfigured", "cloud", "external", "cloud_key"),
    ]
    async with session_factory()() as db, db.begin():
        for name, model, endpoint, trust, credential in definitions:
            row = await db.scalar(
                select(ModelDeployment).where(ModelDeployment.logical_name == name).with_for_update()
            )
            enabled = trust == "local" and (
                name != "local_audio" or config.local_audio_trusted and config.local_audio_verified
            )
            if row is None:
                db.add(
                    ModelDeployment(
                        logical_name=name,
                        actual_model_id=model,
                        endpoint_ref=endpoint,
                        trust_domain=trust,
                        credential_ref=credential,
                        enabled=enabled,
                    )
                )
            elif (row.actual_model_id, row.endpoint_ref, row.trust_domain) != (model, endpoint, trust):
                row.actual_model_id, row.endpoint_ref, row.trust_domain = model, endpoint, trust
                row.credential_ref, row.enabled = credential, enabled
                row.version += 1
                row.capabilities, row.checked_at = {}, None
    print("Реестр обновлён из конфигурации. Перед включением deployment выполните health-check.")


async def legacy_preview(args):
    from app.application.extraction import CATEGORY_MAP, UNIT_MAP, expiry
    from app.application.proposals import create_proposal
    from app.db.models import Workspace

    async with session_factory()() as db, db.begin():
        workspace = await db.get(Workspace, args.workspace_id, with_for_update=True)
        if workspace is None:
            raise ValueError("Рабочая область не найдена")
        rows = (
            (
                await db.execute(
                    text(
                        "SELECT id, name, quantity, unit_of_measure, primary_category::text, attributes, archived_at FROM public.items ORDER BY id"
                    )
                )
            )
            .mappings()
            .all()
        )
        count = 0
        for row in rows:
            if row["archived_at"]:
                continue
            unit = UNIT_MAP.get(row["unit_of_measure"], row["unit_of_measure"])
            mode = "counted" if unit else "untracked"
            attrs = row["attributes"] or {}
            values = {
                "item_name": row["name"],
                "category": CATEGORY_MAP.get(row["primary_category"], "other"),
                "tracking_mode": mode,
                "unit_code": unit,
                "quantity": str(row["quantity"]) if row["quantity"] is not None and unit else None,
                "quantity_state": "not_applicable"
                if not unit
                else "exact"
                if row["quantity"] is not None
                else "unknown",
                **expiry(attrs.get("expiry_date")),
            }
            await create_proposal(
                db,
                workspace.id,
                workspace.owner_user_id,
                [{"type": "receive_stock", "values": values}],
                warnings=[
                    f"Импорт старой карточки {row['id']}. Проверьте место, срок, единицу и режим учёта; старый pipeline мог записать их без HITL."
                ],
            )
            count += 1
    print(f"Создано предложений для проверки: {count}. Таблицы public сохранены.")


async def worker_options():
    from app.db.models import SettingsRevision
    from app.settings.registry import defaults

    factory = session_factory()
    try:
        async with factory() as db:
            desired = await db.scalar(
                select(SettingsRevision).order_by(SettingsRevision.revision.desc()).limit(1)
            )
            return desired.values if desired else defaults()
    finally:
        await factory.kw["bind"].dispose()
        session_factory.cache_clear()


def worker(args):
    from arq.worker import run_worker

    from app.workers.queue import CloudWorker, CPUWorker, MLWorker, Scheduler

    # arq запускает цикл сам; Runner сохраняет его после чтения настроек.
    with asyncio.Runner() as runner:
        settings = runner.run(worker_options())
        cls = {"cpu": CPUWorker, "ml": MLWorker, "cloud": CloudWorker, "scheduler": Scheduler}[args.role]
        cls.job_timeout = settings["timeout.worker_hard_seconds"]
        cls.max_jobs = (
            settings["queue.cpu_concurrency"]
            if args.role == "cpu"
            else settings["queue.cloud_concurrency"]
            if args.role == "cloud"
            else 1
        )
        run_worker(cls)


def main():
    parser = argparse.ArgumentParser(description="Инвентаризатор: серверное обслуживание")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("bootstrap")
    init.add_argument("--login", required=True)
    init.add_argument("--timezone", default="Europe/Moscow")
    init.add_argument("--storage", action="store_true")
    reset = commands.add_parser("reset-password")
    reset.add_argument("--login", required=True)
    schema = commands.add_parser("schemas")
    schema.add_argument("--output", default="docs/schemas")
    commands.add_parser("verify-prompts")
    commands.add_parser("model-health")
    commands.add_parser("sync-models")
    worker_parser = commands.add_parser("worker")
    worker_parser.add_argument("role", choices=["cpu", "ml", "cloud", "scheduler"])
    legacy = commands.add_parser("legacy-preview")
    legacy.add_argument("--workspace-id", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--output", required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--input", required=True)
    restore.add_argument("--deletion-ledger", required=True)
    ledger = commands.add_parser("deletion-ledger")
    ledger.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command in {"schemas", "verify-prompts", "worker"}:
        {"schemas": schemas, "verify-prompts": verify_prompts, "worker": worker}[args.command](args)
    elif args.command == "deletion-ledger":
        from app.infrastructure.backup import export_deletion_ledger

        asyncio.run(export_deletion_ledger(Path(args.output)))
    elif args.command in {"backup", "restore"}:
        from app.infrastructure.backup import backup, restore

        asyncio.run(
            backup(Path(args.output))
            if args.command == "backup"
            else restore(Path(args.input), Path(args.deletion_ledger))
        )
    else:
        asyncio.run(
            {
                "bootstrap": initialize,
                "reset-password": reset_password,
                "model-health": model_health,
                "sync-models": sync_models,
                "legacy-preview": legacy_preview,
            }[args.command](args)
        )


if __name__ == "__main__":
    main()
