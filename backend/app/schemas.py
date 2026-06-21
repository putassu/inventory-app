import datetime
import uuid
from decimal import Decimal
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field, ConfigDict

from backend.app.db.models import ItemStatus, PrimaryCategory, MediaType, UserTier, TaskStatus, LocationStatus


# ==========================================
# Media Schemas
# ==========================================

class TaskStatusResponse(BaseModel):
    task_id: uuid.UUID
    item_id: Optional[uuid.UUID]
    status: TaskStatus
    error_message: Optional[str]
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# Admin Schemas
# ==========================================

class UserUpdateAdmin(BaseModel):
    tier: Optional[UserTier] = None
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None

class SystemSettingResponse(BaseModel):
    key: str
    value: Any
    description: Optional[str] = None
    updated_at: datetime.datetime
    
    model_config = ConfigDict(from_attributes=True)

class SystemSettingUpdate(BaseModel):
    value: Any
    description: Optional[str] = None


class LocationPhotoResponse(BaseModel):
    id: uuid.UUID
    location_id: uuid.UUID
    original_url: str
    preview_url: Optional[str] = None
    is_primary: bool
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class ItemMediaResponse(BaseModel):
    id: uuid.UUID
    item_id: uuid.UUID
    type: MediaType
    original_url: str
    preview_url: Optional[str] = None
    is_primary: bool
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# Location Schemas
# ==========================================

class LocationCreate(BaseModel):
    name: str = Field(..., max_length=255, description="Name of the storage location")
    parent_location_id: Optional[uuid.UUID] = Field(None, description="Optional parent location ID for nested hierarchy")
    description: Optional[str] = Field(None, description="Description of the location")


class LocationUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255, description="Name of the storage location")
    parent_location_id: Optional[uuid.UUID] = Field(None, description="Optional parent location ID for nested hierarchy")
    description: Optional[str] = Field(None, description="Description of the location")

class LocationUpdateGeneric(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    attributes: Optional[Dict[str, Any]] = None

class LocationResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    parent_location_id: Optional[uuid.UUID] = None
    name: str
    description: Optional[str] = None
    status: LocationStatus
    audio_url: Optional[str] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    photos: List[LocationPhotoResponse] = []

    model_config = ConfigDict(from_attributes=True)


class LocationTreeResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    parent_location_id: Optional[uuid.UUID] = None
    name: str
    description: Optional[str] = None
    status: LocationStatus
    audio_url: Optional[str] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    photos: List[LocationPhotoResponse] = []
    child_locations: List["LocationTreeResponse"] = []

    model_config = ConfigDict(from_attributes=True)

class SearchGlobalResponse(BaseModel):
    items: List["ItemResponse"]
    locations: List[LocationResponse]


# ==========================================
# Item Schemas
# ==========================================

class ItemCreate(BaseModel):
    location_id: Optional[uuid.UUID] = Field(None, description="Where the item is stored")
    group_id: Optional[uuid.UUID] = Field(None, description="ID connecting identical items across different locations")
    quantity: Optional[Decimal] = Field(None, description="Quantity or remaining amount")
    unit_of_measure: Optional[str] = Field(None, max_length=50, description="Unit (e.g. pcs, ml, mg)")
    generated_desc: Optional[str] = Field(None, description="AI-generated description for Qdrant RAG search")
    tags: Optional[List[str]] = Field(None, description="General descriptive tags")
    synonyms: Optional[List[str]] = Field(None, description="Search synonyms")
    primary_category: Optional[PrimaryCategory] = Field(PrimaryCategory.OTHER, description="Primary taxonomy category")
    secondary_categories: Optional[List[PrimaryCategory]] = Field(None, description="Secondary helper categories")
    status: Optional[ItemStatus] = Field(ItemStatus.QUEUED, description="Lifecycle and processing status")
    attributes: Optional[Dict[str, Any]] = Field(None, description="Category-specific JSON properties")

class ItemUpdateGeneric(BaseModel):
    name: Optional[str] = Field(None, max_length=150)
    tags: Optional[List[str]] = None
    synonyms: Optional[List[str]] = None
    primary_category: Optional[PrimaryCategory] = None
    secondary_categories: Optional[List[PrimaryCategory]] = None
    attributes: Optional[Dict[str, Any]] = None

class ItemUpdate(BaseModel):
    location_id: Optional[uuid.UUID] = Field(None, description="Where the item is stored")
    group_id: Optional[uuid.UUID] = Field(None, description="ID connecting identical items across different locations")
    quantity: Optional[Decimal] = Field(None, description="Quantity or remaining amount")
    unit_of_measure: Optional[str] = Field(None, max_length=50, description="Unit (e.g. pcs, ml, mg)")
    generated_desc: Optional[str] = Field(None, description="AI-generated description for Qdrant RAG search")
    tags: Optional[List[str]] = Field(None, description="General descriptive tags")
    synonyms: Optional[List[str]] = Field(None, description="Search synonyms")
    primary_category: Optional[PrimaryCategory] = Field(None, description="Primary taxonomy category")
    secondary_categories: Optional[List[PrimaryCategory]] = Field(None, description="Secondary helper categories")
    status: Optional[ItemStatus] = Field(None, description="Lifecycle and processing status")
    attributes: Optional[Dict[str, Any]] = Field(None, description="Category-specific JSON properties")
    archived_at: Optional[datetime.datetime] = Field(None, description="Timestamp for soft deletion")


class ItemResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    location_id: Optional[uuid.UUID] = None
    group_id: Optional[uuid.UUID] = None
    quantity: Optional[Decimal] = None
    unit_of_measure: Optional[str] = None
    generated_desc: Optional[str] = None
    tags: List[str] = []
    synonyms: List[str] = []
    primary_category: PrimaryCategory
    secondary_categories: List[PrimaryCategory] = []
    status: ItemStatus
    attributes: Dict[str, Any] = {}
    archived_at: Optional[datetime.datetime] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    media: List[ItemMediaResponse] = []

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# User and Authentication Schemas
# ==========================================

class UserSettings(BaseModel):
    audit_reminder_days: int = Field(30, description="Remind to audit items every N days")
    audit_min_moves: int = Field(0, description="Only audit items with > M moves")
    audit_locations: List[str] = Field(default_factory=list, description="Locations to include in audit")
    local_llm_only: bool = Field(False, description="Use only local models")
    developer_mode: bool = Field(False, description="Return raw error texts")
    expiry_reminder_percentiles: List[float] = Field(default_factory=lambda: [0.8, 0.95, 0.99])
    timezone: str = Field("UTC", description="User local timezone for reminders (e.g. Europe/Moscow)")
    auto_archive_depleted: bool = Field(True, description="Automatically archive items when quantity is 0")
    default_item_status: str = Field("queued", description="Default status for manually created items")
    compact_view: bool = Field(False, description="Use compact view in UI lists")

class UserSettingsUpdate(BaseModel):
    audit_reminder_days: Optional[int] = None
    audit_min_moves: Optional[int] = None
    audit_locations: Optional[List[str]] = None
    local_llm_only: Optional[bool] = None
    developer_mode: Optional[bool] = None
    expiry_reminder_percentiles: Optional[List[float]] = None
    timezone: Optional[str] = None
    auto_archive_depleted: Optional[bool] = None
    default_item_status: Optional[str] = None
    compact_view: Optional[bool] = None


class UserCreate(BaseModel):
    email: str = Field(
        ..., 
        description="Unique email address of the user", 
        examples=["user@example.com"]
    )
    password: str = Field(
        ..., 
        min_length=8, 
        description="Password for the user account (min 8 characters)", 
        examples=["supersecretpassword"]
    )


class UserResponse(BaseModel):
    id: uuid.UUID = Field(
        ..., 
        description="Unique user identifier", 
        examples=["f47ac10b-58cc-4372-a567-0e02b2c3d479"]
    )
    email: str = Field(
        ..., 
        description="Email address of the user", 
        examples=["user@example.com"]
    )
    tier: UserTier = Field(
        ..., 
        description="Subscription tier / tariff plan", 
        examples=["FREE"]
    )
    litellm_user_key: Optional[str] = Field(
        None, 
        description="API key for LiteLLM gateway with assigned quotas", 
        examples=["sk-litellm-free-key"]
    )
    is_active: bool = Field(
        ..., 
        description="Whether the user account is active", 
        examples=[True]
    )
    created_at: datetime.datetime = Field(
        ..., 
        description="User registration timestamp"
    )
    tier_expired_at: Optional[datetime.datetime] = Field(
        None, 
        description="Expiration date of subscription tier",
        examples=["2027-06-15T00:00:00Z"]
    )
    litellm_key_expired_at: Optional[datetime.datetime] = Field(
        None, 
        description="Expiration date of LiteLLM key",
        examples=["2027-06-15T00:00:00Z"]
    )
    last_login_ip: Optional[str] = Field(
        None, 
        description="Client IP address of last login", 
        examples=["192.168.1.1"]
    )
    last_login_dt: Optional[datetime.datetime] = Field(
        None, 
        description="Timestamp of last login",
        examples=["2026-06-15T00:00:00Z"]
    )
    settings: Dict[str, Any] = Field(
        {}, 
        description="User-specific settings and preferences"
    )

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str = Field(
        ..., 
        description="JWT access token string", 
        examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."]
    )
    token_type: str = Field(
        ..., 
        description="Token type", 
        examples=["bearer"]
    )


class TokenData(BaseModel):
    user_id: Optional[uuid.UUID] = Field(
        None, 
        description="Subject user ID decoded from token"
    )
    tier: Optional[UserTier] = Field(
        None, 
        description="User subscription tier decoded from token"
    )
    litellm_user_key: Optional[str] = Field(
        None, 
        description="User's LiteLLM key decoded from token"
    )


class TaskResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    status: TaskStatus
    transcription: Optional[str] = None
    is_safe: Optional[bool] = None
    confidence_score: Optional[Decimal] = None
    suggested_json: Dict[str, Any] = {}
    photo_urls: List[str] = []
    audio_url: Optional[str] = None
    error_message: Optional[str] = None
    execution_times: Optional[Dict[str, Any]] = None
    debug_logs: Optional[List[str]] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class TaskResolve(BaseModel):
    suggested_json: Dict[str, Any] = Field(..., description="Approved or corrected JSON payload containing items details to extract")


# ==========================================
# RAG and Pipeline Message Schemas
# ==========================================

class ExtractedItem(BaseModel):
    name: str
    category: PrimaryCategory

class MoveConsumeDetails(BaseModel):
    item_name: str
    target_item_id: Optional[str] = None
    amount: Optional[float] = None
    to_location: Optional[str] = None

class GatekeeperOutput(BaseModel):
    is_safe: bool
    sensitive_flags: List[str] = []
    transcription: Optional[str] = None
    items: List[ExtractedItem] = []
    locations: List[str] = []
    confidence_score: float = 1.0


class RAGContextItem(BaseModel):
    parent_id: str
    name: str
    is_location: bool
    tags: List[str] = []
    description: Optional[str] = None
    score: float


class RAGSearchResult(BaseModel):
    items: List[RAGContextItem] = []
    locations: List[RAGContextItem] = []


