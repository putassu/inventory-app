import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from app.config import get_config
from app.db.models import Item, Job, Media, Session, Tombstone, Workspace
from app.db.session import session_factory
from app.domain.common import canonical, digest, uid, utcnow
from app.infrastructure.storage import Storage


async def pg_command(program, extra):
    url = make_url(get_config().database_url)
    environment = {**os.environ, "PGPASSWORD": url.password or ""}
    command = [
        program,
        "--host",
        url.host or "localhost",
        "--port",
        str(url.port or 5432),
        "--username",
        url.username or "",
        "--dbname",
        url.database or "",
        *extra,
    ]
    result = await asyncio.to_thread(
        subprocess.run, command, env=environment, capture_output=True, check=False
    )
    if result.returncode:
        raise RuntimeError(f"{program}: ошибка {result.returncode}. Проверьте локальный доступ к PostgreSQL.")


async def backup(output: Path):
    if output.exists():
        raise ValueError("Каталог копии уже существует; выберите новый")
    output.mkdir(parents=True)
    storage = Storage()
    async with session_factory()() as db:
        if db.bind.dialect.name != "postgresql":
            raise ValueError("Для резервного копирования требуется PostgreSQL")
        await db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        # Purge/GC сначала меняют состояние media в БД. Блокировка сохраняет байты снимка до копирования.
        await db.execute(text("LOCK TABLE inventory.media_assets IN SHARE MODE"))
        snapshot = await db.scalar(text("SELECT pg_export_snapshot()"))
        version = await db.scalar(text("SELECT version_num FROM inventory.alembic_version"))
        media = (await db.scalars(select(Media).where(Media.state == "uploaded"))).all()
        tombstones = (await db.scalars(select(Tombstone))).all()
        await pg_command(
            "pg_dump",
            [
                "--format=custom",
                "--schema=inventory",
                "--snapshot",
                snapshot,
                "--file",
                str(output / "database.dump"),
            ],
        )
        ledger = [
            {"workspace_id": t.workspace_id, "entity_type": t.entity_type, "entity_id": t.entity_id}
            for t in tombstones
        ]
        (output / "deletion-ledger.json").write_text(canonical(ledger), encoding="utf-8")
        objects = []
        for asset in media:
            data = await storage.read(asset.object_key)
            relative = "objects/" + asset.id
            (output / "objects").mkdir(exist_ok=True)
            (output / relative).write_bytes(data)
            objects.append(
                {
                    "file": relative,
                    "object_key": asset.object_key,
                    "mime": asset.mime,
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
    manifest = {
        "schema_version": version,
        "application_version": "1.0.0",
        "created_at": utcnow().isoformat(),
        "objects": objects,
        "deletion_ledger_sha256": hashlib.sha256((output / "deletion-ledger.json").read_bytes()).hexdigest(),
        "database_sha256": hashlib.sha256((output / "database.dump").read_bytes()).hexdigest(),
    }
    (output / "backup.json").write_text(canonical(manifest), encoding="utf-8")
    print(canonical({"backup": str(output), "objects": len(objects), "schema_version": version}))


def read_ledger(path):
    records = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(records, dict):
        records = records["entries"]
    if not isinstance(records, list):
        raise ValueError("Некорректный журнал удалений")
    for record in records:
        UUID(record["workspace_id"])
        UUID(record["entity_id"])
        if record["entity_type"] != "item":
            raise ValueError("Неизвестный тип записи в журнале удалений")
    return records


async def export_deletion_ledger(output: Path):
    async with session_factory()() as db:
        tombstones = (await db.scalars(select(Tombstone).order_by(Tombstone.id))).all()
        records = [
            {"workspace_id": row.workspace_id, "entity_type": row.entity_type, "entity_id": row.entity_id}
            for row in tombstones
        ]
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".partial")
    temporary.write_text(
        canonical({"generated_at": utcnow().isoformat(), "entries": records}), encoding="utf-8"
    )
    temporary.replace(output)
    return len(records)


def validate_backup(source: Path, deletion_ledger: Path):
    """Проверяем весь архив до первого изменения БД или object storage."""
    manifest = json.loads((source / "backup.json").read_text(encoding="utf-8"))
    ledger = read_ledger(source / "deletion-ledger.json") + read_ledger(deletion_ledger)
    if hashlib.sha256((source / "database.dump").read_bytes()).hexdigest() != manifest["database_sha256"]:
        raise ValueError("Контрольная сумма PostgreSQL-копии не совпадает")
    if (
        hashlib.sha256((source / "deletion-ledger.json").read_bytes()).hexdigest()
        != manifest["deletion_ledger_sha256"]
    ):
        raise ValueError("Контрольная сумма журнала удалений не совпадает")
    keys = set()
    for obj in manifest["objects"]:
        path = (source / obj["file"]).resolve()
        if not path.is_relative_to(source.resolve()) or not path.is_file():
            raise ValueError("Некорректный путь в manifest")
        key = obj["object_key"]
        if (
            not key
            or key.startswith(("/", "\\"))
            or ".." in key.split("/")
            or "\\" in key
            or ":" in key
            or key in keys
        ):
            raise ValueError("Некорректный object key в manifest")
        keys.add(key)
        if hashlib.sha256(path.read_bytes()).hexdigest() != obj["sha256"]:
            raise ValueError("Контрольная сумма медиа не совпадает")
    ledger = list({(r["workspace_id"], r["entity_type"], r["entity_id"]): r for r in ledger}.values())
    return manifest, ledger


async def restore(source: Path, deletion_ledger: Path):
    manifest, ledger = validate_backup(source, deletion_ledger)
    async with session_factory()() as db:
        exists = await db.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'inventory')")
        )
        if exists:
            raise ValueError("Восстановление разрешено только в пустую отдельную БД")
    storage = Storage()
    await storage.initialize()
    for obj in manifest["objects"]:
        path = (source / obj["file"]).resolve()
        data = path.read_bytes()
        await storage.put(obj["object_key"], data, obj["mime"])
    await pg_command(
        "pg_restore",
        [
            "--single-transaction",
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            str(source / "database.dump"),
        ],
    )
    purge_ids = []
    async with session_factory()() as db, db.begin():
        for record in ledger:
            item = await db.get(Item, record["entity_id"])
            workspace = await db.get(Workspace, record["workspace_id"])
            if not workspace:
                continue
            if item and item.workspace_id != workspace.id:
                raise ValueError("Журнал удалений ссылается на другой workspace")
            if not await db.scalar(
                select(Tombstone.id).where(
                    Tombstone.entity_id == record["entity_id"], Tombstone.entity_type == "item"
                )
            ):
                db.add(
                    Tombstone(workspace_id=workspace.id, entity_id=record["entity_id"], entity_type="item")
                )
            if not item:
                continue
            item.lifecycle = "deleted"
            item.deleted_at = utcnow()
            payload = {"items": [{"id": item.id, "version": item.version, "name": item.name}]}
            job = Job(
                id=uid(),
                workspace_id=item.workspace_id,
                created_by=item.created_by,
                kind="purge",
                manifest=payload,
                manifest_hash=digest(payload),
                not_before=utcnow(),
            )
            db.add(job)
            purge_ids.append(job.id)
        # Снимок не возобновляет старые сессии и временные ссылки на экспорт.
        for session in (await db.scalars(select(Session))).all():
            session.revoked_at = utcnow()
        for job in (await db.scalars(select(Job).where(Job.kind == "export"))).all():
            job.status, job.expires_at = "revoked", utcnow()
    from app.application.maintenance import purge_job

    for job_id in purge_ids:
        await purge_job(session_factory(), job_id)
    print(
        canonical(
            {"status": "restored", "objects": len(manifest["objects"]), "deletions_reapplied": len(purge_ids)}
        )
    )
