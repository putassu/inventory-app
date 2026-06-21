import enum
import uuid
import datetime
from decimal import Decimal
from typing import List, Optional, Dict, Any

from sqlalchemy import (
    String,
    Text,
    Numeric,
    Boolean,
    DateTime,
    Integer,
    ForeignKey,
    text,
    Index
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB, ENUM as PG_ENUM


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy 2.0 declarative models."""
    pass


class UserTier(str, enum.Enum):
    """Tiers/plans for users with specific model quotas."""
    FREE = 'FREE'
    STANDARD = 'STANDARD'
    PREMIUM = 'PREMIUM'


class User(Base):
    """User accounts table representing user credentials, tiers, and LiteLLM keys."""
    __tablename__ = 'users'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )
    tier: Mapped[UserTier] = mapped_column(
        PG_ENUM(UserTier, name='user_tier', create_type=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default=text("'FREE'::user_tier"),
        default=UserTier.FREE
    )
    litellm_user_key: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        default=True
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    tier_expired_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    litellm_key_expired_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    last_login_ip: Mapped[Optional[str]] = mapped_column(
        String(45),
        nullable=True
    )
    last_login_dt: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    settings: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}', tier={self.tier})>"


class SystemSetting(Base):
    """Dynamic configuration values configurable by administrators."""
    __tablename__ = 'system_settings'

    key: Mapped[str] = mapped_column(
        String(100),
        primary_key=True
    )
    value: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<SystemSetting(key='{self.key}')>"


class ItemStatus(str, enum.Enum):
    """Status tracking for item processing workflow."""
    QUEUED = 'queued'
    PROCESSING = 'processing'
    USER_ACTION_REQUIRED = 'user_action_required'
    COMPLETED = 'completed'
    DEPLETED = 'depleted'


class PrimaryCategory(str, enum.Enum):
    """Primary category classification for items."""
    MEDICINES = 'MEDICINES'
    DOCUMENTS = 'DOCUMENTS'
    CLOTHES = 'CLOTHES'
    TECH = 'TECH'
    FOOD = 'FOOD'
    DISHES = 'DISHES'
    COSMETICS = 'COSMETICS'
    HOUSEHOLD = 'HOUSEHOLD'
    HOBBY = 'HOBBY'
    OTHER = 'OTHER'


class MediaType(str, enum.Enum):
    """Types of media files associated with items."""
    PHOTO = 'photo'
    AUDIO = 'audio'


class LocationStatus(str, enum.Enum):
    """Status tracking for locations."""
    ACTIVE = 'active'
    USER_ACTION_REQUIRED = 'user_action_required'


class Location(Base):
    """Locations table representing hierarchical storage places (e.g., Room -> Cabinet -> Drawer)."""
    __tablename__ = 'locations'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True
    )
    parent_location_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('locations.id', ondelete='CASCADE'),
        nullable=True
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    status: Mapped[LocationStatus] = mapped_column(
        PG_ENUM(LocationStatus, name='location_status', create_type=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default=text("'active'::location_status"),
        default=LocationStatus.ACTIVE
    )
    audio_url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    attributes: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict
    )

    # Relationships
    parent_location: Mapped[Optional["Location"]] = relationship(
        "Location",
        remote_side=[id],
        back_populates="child_locations"
    )
    child_locations: Mapped[List["Location"]] = relationship(
        "Location",
        back_populates="parent_location",
        cascade="all, delete-orphan"
    )
    items: Mapped[List["Item"]] = relationship(
        "Item",
        back_populates="location"
    )
    photos: Mapped[List["LocationPhoto"]] = relationship(
        "LocationPhoto",
        back_populates="location",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Location(id={self.id}, name='{self.name}', user_id={self.user_id})>"


class Item(Base):
    """Items table representing inventoried goods, medications, docs, or supplies."""
    __tablename__ = 'items'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        server_default=text("'Без названия'"),
        default='Без названия'
    )
    location_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('locations.id', ondelete='SET NULL'),
        nullable=True,
        index=True
    )
    group_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True
    )
    quantity: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True
    )
    unit_of_measure: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True
    )
    generated_desc: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    tags: Mapped[List[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        server_default=text("'{}'::text[]"),
        default=list
    )
    synonyms: Mapped[List[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        server_default=text("'{}'::text[]"),
        default=list
    )
    primary_category: Mapped[PrimaryCategory] = mapped_column(
        PG_ENUM(PrimaryCategory, name='primary_category', create_type=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default=text("'OTHER'::primary_category"),
        default=PrimaryCategory.OTHER
    )
    secondary_categories: Mapped[List[PrimaryCategory]] = mapped_column(
        ARRAY(PG_ENUM(PrimaryCategory, name='primary_category', create_type=False, values_callable=lambda x: [e.value for e in x])),
        nullable=False,
        server_default=text("'{}'::primary_category[]"),
        default=list
    )
    status: Mapped[ItemStatus] = mapped_column(
        PG_ENUM(ItemStatus, name='item_status', create_type=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
        server_default=text("'queued'::item_status"),
        default=ItemStatus.QUEUED
    )
    attributes: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict
    )
    moves_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
        default=0
    )
    archived_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc)
    )

    # Indexes
    __table_args__ = (
        Index("idx_items_attributes_gin", "attributes", postgresql_using="gin"),
    )

    # Relationships
    location: Mapped[Optional["Location"]] = relationship(
        "Location",
        back_populates="items"
    )
    media: Mapped[List["ItemMedia"]] = relationship(
        "ItemMedia",
        back_populates="item",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Item(id={self.id}, user_id={self.user_id}, category={self.primary_category}, status={self.status})>"


class ItemMedia(Base):
    """Media attachments (photos, audio files) linked to inventoried items."""
    __tablename__ = 'item_media'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()")
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('items.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    type: Mapped[MediaType] = mapped_column(
        PG_ENUM(MediaType, name='media_type', create_type=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True
    )
    original_url: Mapped[str] = mapped_column(
        String(1024),
        nullable=False
    )
    preview_url: Mapped[Optional[str]] = mapped_column(
        String(1024),
        nullable=True
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )

    # Relationships
    item: Mapped["Item"] = relationship(
        "Item",
        back_populates="media"
    )

    def __repr__(self) -> str:
        return f"<ItemMedia(id={self.id}, item_id={self.item_id}, type={self.type}, is_primary={self.is_primary})>"


class LocationPhoto(Base):
    """Photo attachments associated with hierarchical storage locations."""
    __tablename__ = 'location_photos'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()")
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('locations.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    original_url: Mapped[str] = mapped_column(
        String(1024),
        nullable=False
    )
    preview_url: Mapped[Optional[str]] = mapped_column(
        String(1024),
        nullable=True
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )

    # Relationships
    location: Mapped["Location"] = relationship(
        "Location",
        back_populates="photos"
    )

    def __repr__(self) -> str:
        return f"<LocationPhoto(id={self.id}, location_id={self.location_id}, is_primary={self.is_primary})>"


class TaskStatus(str, enum.Enum):
    """Status tracking for background ML task pipeline."""
    QUEUED = 'queued'
    PROCESSING = 'processing'
    USER_ACTION_REQUIRED = 'user_action_required'
    COMPLETED = 'completed'
    FAILED = 'failed'


class Task(Base):
    """Background tasks for processing items, photos, and voice transcripiton."""
    __tablename__ = 'tasks'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    status: Mapped[TaskStatus] = mapped_column(
        PG_ENUM(TaskStatus, name='task_status', create_type=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
        server_default=text("'queued'::task_status"),
        default=TaskStatus.QUEUED
    )
    transcription: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    is_safe: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True
    )
    confidence_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(3, 2),
        nullable=True
    )
    suggested_json: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict
    )
    photo_urls: Mapped[List[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        server_default=text("'{}'::text[]"),
        default=list
    )
    audio_url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    execution_times: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict
    )
    debug_logs: Mapped[List[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        default=list
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<Task(id={self.id}, user_id={self.user_id}, status={self.status})>"

