"""Источник истины; связи между рабочими областями запрещены составными FK."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.domain.common import uid, utcnow

J = JSON().with_variant(JSONB(), "postgresql")
Q = Numeric(20, 6)


class Base(DeclarativeBase):
    metadata = MetaData(
        schema="inventory",
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        },
    )


class Entity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    version: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Scoped(Entity):
    workspace_id: Mapped[str] = mapped_column(ForeignKey("inventory.workspaces.id"), index=True)

    @declared_attr.directive
    def __table_args__(cls):
        return (UniqueConstraint("workspace_id", "id"),)


def scoped_fk(table, column):
    return ForeignKeyConstraint(
        ["workspace_id", column], [f"inventory.{table}.workspace_id", f"inventory.{table}.id"]
    )


class User(Entity, Base):
    __tablename__ = "users"
    login: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    app_role: Mapped[str] = mapped_column(String(10), default="user")
    status: Mapped[str] = mapped_column(String(20), default="active")
    locale: Mapped[str] = mapped_column(String(10), default="ru")
    timezone: Mapped[str] = mapped_column(String(100), default="Europe/Moscow")
    auth_version: Mapped[int] = mapped_column(Integer, default=1)
    preferences: Mapped[dict] = mapped_column(J, default=dict)
    preferences_version: Mapped[int] = mapped_column(Integer, default=1)


class Workspace(Entity, Base):
    __tablename__ = "workspaces"
    name: Mapped[str] = mapped_column(String(255))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("inventory.users.id"))


class Membership(Base):
    __tablename__ = "workspace_memberships"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("inventory.workspaces.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("inventory.users.id"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(20), default="owner")
    status: Mapped[str] = mapped_column(String(20), default="active")


class Session(Entity, Base):
    __tablename__ = "sessions"
    user_id: Mapped[str] = mapped_column(ForeignKey("inventory.users.id"), index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[str] = mapped_column(String(36), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Agreement(Entity, Base):
    __tablename__ = "agreements"
    user_id: Mapped[str] = mapped_column(ForeignKey("inventory.users.id"))
    agreement_type: Mapped[str] = mapped_column(String(50))
    agreement_version: Mapped[str] = mapped_column(String(50))
    acceptance_context: Mapped[dict] = mapped_column(J, default=dict)
    __table_args__ = (UniqueConstraint("user_id", "agreement_type", "agreement_version"),)


class Location(Scoped, Base):
    __tablename__ = "locations"
    parent_id: Mapped[str | None] = mapped_column(String(36))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30), default="place")
    default_privacy_policy: Mapped[str | None] = mapped_column(String(20))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        scoped_fk("locations", "parent_id"),
        CheckConstraint("kind != 'system_unspecified' OR parent_id IS NULL", name="system_root"),
        Index(
            "uq_location_unspecified",
            "workspace_id",
            unique=True,
            postgresql_where=(kind == "system_unspecified"),
            sqlite_where=(kind == "system_unspecified"),
        ),
    )


class Item(Scoped, Base):
    __tablename__ = "items"
    name: Mapped[str] = mapped_column(String(255))
    primary_category: Mapped[str] = mapped_column(String(30), default="other")
    secondary_categories: Mapped[list] = mapped_column(J, default=list)
    tracking_mode: Mapped[str] = mapped_column(String(20), default="counted")
    base_unit_id: Mapped[str | None] = mapped_column(String(30))
    quantity_step: Mapped[Decimal] = mapped_column(Q, default=Decimal(1))
    attributes: Mapped[dict] = mapped_column(J, default=dict)
    attributes_schema_version: Mapped[str] = mapped_column(String(30), default="attributes.v1")
    barcode: Mapped[str | None] = mapped_column(String(100), index=True)
    brand: Mapped[str | None] = mapped_column(String(255))
    model: Mapped[str | None] = mapped_column(String(255))
    tags: Mapped[list] = mapped_column(J, default=list)
    user_description: Mapped[str | None] = mapped_column(Text)
    generated_description: Mapped[str | None] = mapped_column(Text)
    description_model_revision: Mapped[str | None] = mapped_column(String(100))
    privacy_policy: Mapped[str] = mapped_column(String(20), default="local_only")
    lifecycle: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("inventory.users.id"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    search_revision: Mapped[int] = mapped_column(BigInteger, default=1)
    indexed_revision: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        CheckConstraint("quantity_step > 0", name="positive_step"),
        CheckConstraint(
            "primary_category != 'document' OR privacy_policy = 'local_only'", name="private_document"
        ),
    )


class Lot(Scoped, Base):
    __tablename__ = "lots"
    item_id: Mapped[str] = mapped_column(String(36), index=True)
    lot_kind: Mapped[str] = mapped_column(String(20), default="batch")
    label: Mapped[str | None] = mapped_column(String(255))
    serial_number: Mapped[str | None] = mapped_column(String(255), index=True)
    manufacturer_batch: Mapped[str | None] = mapped_column(String(255))
    parent_lot_id: Mapped[str | None] = mapped_column(String(36))
    acquired_at: Mapped[date | None] = mapped_column(Date)
    manufactured_on: Mapped[date | None] = mapped_column(Date)
    opened_on: Mapped[date | None] = mapped_column(Date)
    expiry_on: Mapped[date | None] = mapped_column(Date)
    expiry_precision: Mapped[str] = mapped_column(String(20), default="unknown")
    expiry_raw_text: Mapped[str | None] = mapped_column(String(255))
    after_opening_amount: Mapped[int | None] = mapped_column(Integer)
    after_opening_unit: Mapped[str | None] = mapped_column(String(10))
    effective_expiry_on: Mapped[date | None] = mapped_column(Date, index=True)
    expiry_derivation: Mapped[str] = mapped_column(String(30), default="unknown")
    expiry_generation: Mapped[int] = mapped_column(Integer, default=1)
    privacy_policy: Mapped[str] = mapped_column(String(20), default="local_only")
    attributes: Mapped[dict] = mapped_column(J, default=dict)
    attributes_schema_version: Mapped[str] = mapped_column(String(30), default="lot.v1")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        scoped_fk("items", "item_id"),
        scoped_fk("lots", "parent_lot_id"),
    )


class Balance(Scoped, Base):
    __tablename__ = "stock_balances"
    lot_id: Mapped[str] = mapped_column(String(36), index=True)
    location_id: Mapped[str] = mapped_column(String(36), index=True)
    quantity: Mapped[Decimal | None] = mapped_column(Q)
    quantity_state: Mapped[str] = mapped_column(String(20), default="unknown")
    last_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("inventory.users.id"))
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "lot_id", "location_id"),
        scoped_fk("lots", "lot_id"),
        scoped_fk("locations", "location_id"),
        CheckConstraint("quantity IS NULL OR quantity >= 0", name="nonnegative"),
        CheckConstraint(
            "(quantity_state IN ('exact','estimated') AND quantity IS NOT NULL) OR "
            "(quantity_state IN ('unknown','not_applicable') AND quantity IS NULL)",
            name="quantity_state",
        ),
    )


class Alias(Scoped, Base):
    __tablename__ = "item_aliases"
    item_id: Mapped[str] = mapped_column(String(36))
    alias: Mapped[str] = mapped_column(String(255))
    normalized_alias: Mapped[str] = mapped_column(String(255), index=True)
    scope: Mapped[str] = mapped_column(String(20), default="workspace")
    created_by: Mapped[str] = mapped_column(ForeignKey("inventory.users.id"))
    source: Mapped[str] = mapped_column(String(30), default="explicit_user")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("workspace_id", "id"), scoped_fk("items", "item_id"))


class Media(Scoped, Base):
    __tablename__ = "media_assets"
    object_key: Mapped[str] = mapped_column(String(500), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    mime: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[Decimal | None] = mapped_column(Q)
    state: Mapped[str] = mapped_column(String(20), default="uploaded")
    kind: Mapped[str] = mapped_column(String(30), default="source")
    privacy_policy: Mapped[str] = mapped_column(String(20), default="local_only")
    client_preprocessed: Mapped[bool] = mapped_column(Boolean, default=False)
    manifest: Mapped[dict] = mapped_column(J, default=dict)


class Binding(Scoped, Base):
    __tablename__ = "media_bindings"
    media_id: Mapped[str] = mapped_column(String(36), index=True)
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(30), default="source")
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        scoped_fk("media_assets", "media_id"),
        UniqueConstraint("workspace_id", "media_id", "entity_type", "entity_id", "role"),
    )


class Batch(Scoped, Base):
    __tablename__ = "ingestion_batches"
    created_by: Mapped[str] = mapped_column(ForeignKey("inventory.users.id"))
    name: Mapped[str] = mapped_column(String(255), default="Загрузка")


class Task(Scoped, Base):
    __tablename__ = "tasks"
    created_by: Mapped[str] = mapped_column(ForeignKey("inventory.users.id"))
    client_request_id: Mapped[str] = mapped_column(String(36))
    parent_task_id: Mapped[str | None] = mapped_column(String(36))
    batch_id: Mapped[str | None] = mapped_column(String(36))
    input_mode: Mapped[str] = mapped_column(String(30), default="text")
    input_text: Mapped[str | None] = mapped_column(Text)
    media_ids: Mapped[list] = mapped_column(J, default=list)
    audio_media_id: Mapped[str | None] = mapped_column(String(36))
    context: Mapped[dict] = mapped_column(J, default=dict)
    requested_privacy: Mapped[str] = mapped_column(String(20), default="local_only")
    effective_privacy: Mapped[str] = mapped_column(String(20), default="local_only")
    status: Mapped[str] = mapped_column(String(30), default="accepted", index=True)
    stage: Mapped[str] = mapped_column(String(50), default="upload_verified")
    status_version: Mapped[int] = mapped_column(BigInteger, default=1)
    queue_class: Mapped[str] = mapped_column(String(20), default="default")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    config_revision: Mapped[int] = mapped_column(Integer, default=1)
    config_snapshot: Mapped[dict] = mapped_column(J, default=dict)
    config_snapshot_hash: Mapped[str] = mapped_column(String(80))
    model_route_revision: Mapped[str] = mapped_column(String(100), default="local.v1")
    prompt_revision: Mapped[str] = mapped_column(String(80))
    output_schema_version: Mapped[str] = mapped_column(String(30), default="extraction.v1")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    external_calls: Mapped[int] = mapped_column(Integer, default=0)
    external_cost: Mapped[Decimal | None] = mapped_column(Q)
    processing_seconds: Mapped[Decimal] = mapped_column(Q, default=Decimal(0))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fencing_token: Mapped[int] = mapped_column(BigInteger, default=0)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress: Mapped[dict] = mapped_column(J, default=dict)
    proposal_id: Mapped[str | None] = mapped_column(String(36))
    result: Mapped[dict] = mapped_column(J, default=dict)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(60))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "created_by", "client_request_id"),
        scoped_fk("tasks", "parent_task_id"),
        scoped_fk("ingestion_batches", "batch_id"),
        scoped_fk("media_assets", "audio_media_id"),
        Index("ix_tasks_dispatch", "status", "next_attempt_at", "priority", "created_at"),
    )


class Attempt(Scoped, Base):
    __tablename__ = "task_attempts"
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    fencing_token: Mapped[int] = mapped_column(BigInteger)
    stage: Mapped[str] = mapped_column(String(50))
    model_id: Mapped[str] = mapped_column(String(255))
    trust_domain: Mapped[str] = mapped_column(String(20), default="local")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(60))
    diagnostics: Mapped[dict] = mapped_column(J, default=dict)
    __table_args__ = (UniqueConstraint("workspace_id", "id"), scoped_fk("tasks", "task_id"))


class Proposal(Scoped, Base):
    __tablename__ = "proposals"
    task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("inventory.users.id"))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="editable")
    source: Mapped[str] = mapped_column(String(20), default="manual")
    actions: Mapped[list] = mapped_column(J, default=list)
    dependencies: Mapped[dict] = mapped_column(J, default=dict)
    document: Mapped[dict] = mapped_column(J, default=dict)
    review_hash: Mapped[str] = mapped_column(String(80))
    source_proposals: Mapped[list] = mapped_column(J, default=list)
    user_changes: Mapped[list] = mapped_column(J, default=list)
    warnings: Mapped[list] = mapped_column(J, default=list)
    __table_args__ = (UniqueConstraint("workspace_id", "id"), scoped_fk("tasks", "task_id"))


class ProposalRevision(Scoped, Base):
    __tablename__ = "proposal_revisions"
    proposal_id: Mapped[str] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer)
    document: Mapped[dict] = mapped_column(J)
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        scoped_fk("proposals", "proposal_id"),
        UniqueConstraint("proposal_id", "revision"),
    )


class Receipt(Scoped, Base):
    __tablename__ = "review_receipts"
    user_id: Mapped[str] = mapped_column(ForeignKey("inventory.users.id"))
    proposal_id: Mapped[str] = mapped_column(String(36))
    proposal_revision: Mapped[int] = mapped_column(Integer)
    observed_review_hash: Mapped[str] = mapped_column(String(80))
    confirmed_values_hash: Mapped[str] = mapped_column(String(80))
    explicit_changes: Mapped[list] = mapped_column(J, default=list)
    confirmation_source: Mapped[str] = mapped_column(String(20))
    client_request_id: Mapped[str] = mapped_column(String(36))
    __table_args__ = (UniqueConstraint("workspace_id", "id"), scoped_fk("proposals", "proposal_id"))


class Confirmation(Scoped, Base):
    __tablename__ = "confirmations"
    proposal_id: Mapped[str] = mapped_column(String(36))
    proposal_revision: Mapped[int] = mapped_column(Integer)
    receipt_id: Mapped[str] = mapped_column(String(36))
    operation_id: Mapped[str] = mapped_column(String(36), unique=True, default=uid)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    actions: Mapped[list] = mapped_column(J)
    dependencies: Mapped[dict] = mapped_column(J)
    fencing_token: Mapped[int] = mapped_column(BigInteger, default=1)
    result: Mapped[dict] = mapped_column(J, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(60))
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "proposal_id", "proposal_revision"),
        scoped_fk("proposals", "proposal_id"),
        scoped_fk("review_receipts", "receipt_id"),
    )


class Operation(Scoped, Base):
    __tablename__ = "operations"
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("inventory.users.id"))
    confirmation_id: Mapped[str] = mapped_column(String(36), unique=True)
    type: Mapped[str] = mapped_column(String(40))
    payload_schema_version: Mapped[str] = mapped_column(String(30), default="command.v1")
    normalized_payload: Mapped[list] = mapped_column(J)
    request_hash: Mapped[str] = mapped_column(String(80))
    reverses_operation_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(20), default="applied")
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        scoped_fk("confirmations", "confirmation_id"),
        scoped_fk("operations", "reverses_operation_id"),
    )


class Entry(Entity, Base):
    __tablename__ = "operation_entries"
    operation_id: Mapped[str] = mapped_column(ForeignKey("inventory.operations.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    before_version: Mapped[int | None] = mapped_column(BigInteger)
    after_version: Mapped[int] = mapped_column(BigInteger)
    before_state: Mapped[dict | None] = mapped_column(J)
    after_state: Mapped[dict] = mapped_column(J)
    quantity_delta: Mapped[Decimal | None] = mapped_column(Q)
    unit_id: Mapped[str | None] = mapped_column(String(30))
    from_location_id: Mapped[str | None] = mapped_column(String(36))
    to_location_id: Mapped[str | None] = mapped_column(String(36))
    ordinal: Mapped[int] = mapped_column(Integer)


class Evidence(Scoped, Base):
    __tablename__ = "field_evidence"
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[str] = mapped_column(String(36))
    field_key: Mapped[str] = mapped_column(String(100))
    source_type: Mapped[str] = mapped_column(String(20))
    media_id: Mapped[str | None] = mapped_column(String(36))
    region: Mapped[dict | None] = mapped_column(J)
    raw_value: Mapped[str | None] = mapped_column(Text)
    normalized_value: Mapped[dict] = mapped_column(J)
    verification_state: Mapped[str] = mapped_column(String(20), default="confirmed")
    proposal_id: Mapped[str] = mapped_column(String(36))
    model_revision: Mapped[str | None] = mapped_column(String(100))


class Idempotency(Entity, Base):
    __tablename__ = "idempotency_keys"
    user_id: Mapped[str] = mapped_column(String(36))
    workspace_id: Mapped[str] = mapped_column(String(36))
    operation_scope: Mapped[str] = mapped_column(String(120))
    key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(80))
    response: Mapped[dict] = mapped_column(J)
    __table_args__ = (UniqueConstraint("user_id", "workspace_id", "operation_scope", "key"),)


class Outbox(Scoped, Base):
    __tablename__ = "outbox_events"
    event_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(36))
    entity_version: Mapped[int] = mapped_column(BigInteger, default=1)
    payload: Mapped[dict] = mapped_column(J, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(36))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        Index("ix_outbox_dispatch", "next_attempt_at", "processed_at"),
    )


class SettingsRevision(Entity, Base):
    __tablename__ = "settings_revisions"
    revision: Mapped[int] = mapped_column(Integer, unique=True)
    values: Mapped[dict] = mapped_column(J)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("inventory.users.id"))
    reason: Mapped[str] = mapped_column(String(500))
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="effective")
    components_pending: Mapped[list] = mapped_column(J, default=list)


class Control(Base):
    __tablename__ = "runtime_controls"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(J, default=dict)


class Audit(Entity, Base):
    __tablename__ = "admin_audit"
    actor_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str | None] = mapped_column(String(500))
    request_id: Mapped[str | None] = mapped_column(String(36))
    details: Mapped[dict] = mapped_column(J, default=dict)


class GPUSlot(Base):
    __tablename__ = "gpu_slots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    owner: Mapped[str | None] = mapped_column(String(36))
    task_id: Mapped[str | None] = mapped_column(String(36))
    fencing_token: Mapped[int] = mapped_column(BigInteger, default=0)
    state: Mapped[str] = mapped_column(String(20), default="idle")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelDeployment(Entity, Base):
    __tablename__ = "model_deployments"
    logical_name: Mapped[str] = mapped_column(String(50), unique=True)
    actual_model_id: Mapped[str] = mapped_column(String(255))
    endpoint_ref: Mapped[str] = mapped_column(String(50))
    credential_ref: Mapped[str | None] = mapped_column(String(50))
    trust_domain: Mapped[str] = mapped_column(String(20), default="local")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    maintenance: Mapped[bool] = mapped_column(Boolean, default=False)
    capabilities: Mapped[dict] = mapped_column(J, default=dict)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Cooldown(Entity, Base):
    __tablename__ = "model_cooldowns"
    quota_key: Mapped[str] = mapped_column(String(255), unique=True)
    reason: Mapped[str] = mapped_column(String(50))
    reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReminderRule(Scoped, Base):
    __tablename__ = "reminder_rules"
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("inventory.users.id"))
    values: Mapped[dict] = mapped_column(J)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Occurrence(Scoped, Base):
    __tablename__ = "reminder_occurrences"
    rule_id: Mapped[str] = mapped_column(String(36))
    subject_lot_id: Mapped[str] = mapped_column(String(36))
    generation: Mapped[str] = mapped_column(String(80))
    threshold_key: Mapped[str] = mapped_column(String(50))
    occurrence_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="planned")
    dedupe_key: Mapped[str] = mapped_column(String(80), unique=True)
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        scoped_fk("reminder_rules", "rule_id"),
        scoped_fk("lots", "subject_lot_id"),
    )


class Notification(Scoped, Base):
    __tablename__ = "inbox_notifications"
    user_id: Mapped[str] = mapped_column(ForeignKey("inventory.users.id"), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(80), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    subjects: Mapped[list] = mapped_column(J, default=list)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Job(Scoped, Base):
    __tablename__ = "maintenance_jobs"
    created_by: Mapped[str] = mapped_column(ForeignKey("inventory.users.id"))
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    manifest: Mapped[dict] = mapped_column(J, default=dict)
    manifest_hash: Mapped[str] = mapped_column(String(80))
    result: Mapped[dict] = mapped_column(J, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Tombstone(Scoped, Base):
    __tablename__ = "deletion_tombstones"
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[str] = mapped_column(String(36))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("workspace_id", "id"), UniqueConstraint("entity_type", "entity_id"))
