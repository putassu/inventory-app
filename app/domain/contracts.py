"""Версионированные документы для клиентов; команды имеют отдельные строгие схемы."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.domain.schemas import CommandType, StrictModel


class FieldOption(StrictModel):
    value: object
    label: str


class ReviewField(StrictModel):
    action_id: str
    key: str
    label: str
    control: str
    value_type: str
    value: object = None
    required: bool
    editable: bool
    allow_unknown: bool
    options: list[FieldOption] = Field(default_factory=list)
    validation: dict = Field(default_factory=dict)
    source: str
    verification_state: str
    importance: str


class ReviewForm(StrictModel):
    template: str
    fields: list[ReviewField]
    readonly_fields: list[dict] = Field(default_factory=list)


class ReviewAction(StrictModel):
    action_id: str
    type: CommandType
    values: dict
    preview: dict


class ReviewDocument(StrictModel):
    schema_version: Literal["review.v1"]
    proposal_id: UUID
    task_id: UUID | None
    revision: int = Field(ge=1)
    status: str
    title: str
    summary: str
    can_confirm: bool
    effective_privacy: Literal["local_only", "cloud_allowed"]
    actions: list[ReviewAction]
    form: ReviewForm
    blocking_issues: list[dict]
    required_decisions: list[dict] = Field(default_factory=list)
    warnings: list[str]
    media: list[dict]
    available_actions: list[str]
    source_proposals: list[dict]
    review_hash: str


class Rectangle(StrictModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class CollageTile(StrictModel):
    index: int = Field(ge=1)
    media_id: str
    rect: Rectangle
    content_rect: Rectangle
    normalized_source_width: int = Field(gt=0)
    normalized_source_height: int = Field(gt=0)
    scale: float = Field(gt=0)
    small_tile: bool


class CollageManifest(StrictModel):
    schema_version: Literal["collage.v1"]
    canvas_width: int = Field(gt=0)
    canvas_height: int = Field(gt=0)
    preprocessing_version: str
    config_revision: int
    tiles: list[CollageTile] = Field(min_length=1)
    cache_key: str


class ExportDocument(StrictModel):
    schema_version: Literal["export.v1"]
    exported_at: datetime
    timezone: str
    reference_versions: dict[str, str]
    export_revision: int
    items: list[dict]
    lots: list[dict]
    balances: list[dict]
    locations: list[dict]
    aliases: list[dict]
    operations: list[dict] = Field(default_factory=list)
    entries: list[dict] = Field(default_factory=list)
    media: list[dict] = Field(default_factory=list)
    media_bindings: list[dict] = Field(default_factory=list)
