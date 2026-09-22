from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def decimal_input(value):
    if isinstance(value, (float, bool)):
        raise ValueError("Количество передаётся строкой, без float.")
    return value


Quantity = Annotated[Decimal, BeforeValidator(decimal_input), Field(ge=0, max_digits=20, decimal_places=6)]
Policy = Literal["local_only", "cloud_allowed"]
QuantityState = Literal["exact", "estimated", "unknown", "not_applicable"]
TrackingMode = Literal["individual", "counted", "measured", "untracked"]
Category = Literal[
    "medicine",
    "document",
    "food",
    "clothing",
    "equipment",
    "dishes",
    "cosmetics",
    "household",
    "hobby",
    "other",
]


class LotFields(StrictModel):
    label: str | None = Field(None, max_length=255)
    serial_number: str | None = Field(None, max_length=255)
    manufacturer_batch: str | None = Field(None, max_length=255)
    acquired_at: date | None = None
    manufactured_on: date | None = None
    opened_on: date | None = None
    expiry_on: date | None = None
    expiry_precision: Literal["day", "month", "unknown"] = "unknown"
    expiry_raw_text: str | None = Field(None, max_length=255)
    after_opening_amount: int | None = Field(None, ge=1, le=36500)
    after_opening_unit: Literal["day", "month"] | None = None
    lot_attributes: dict = Field(default_factory=dict)


class Receive(LotFields):
    item_mode: Literal["create", "existing"] = "create"
    item_id: UUID | None = None
    item_name: str | None = Field(None, max_length=255)
    category: Category = "other"
    tracking_mode: TrackingMode = "counted"
    unit_code: str | None = Field(None, max_length=30)
    quantity_step: Quantity = Decimal(1)
    quantity: Quantity | None = None
    quantity_state: QuantityState = "unknown"
    location_id: UUID | None = None
    lot_mode: Literal["create", "existing"] = "create"
    lot_id: UUID | None = None
    privacy_policy: Policy = "local_only"
    attributes: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=30)
    barcode: str | None = Field(None, max_length=100)
    brand: str | None = Field(None, max_length=255)
    model: str | None = Field(None, max_length=255)
    user_description: str | None = Field(None, max_length=10000)
    generated_description: str | None = Field(None, max_length=10000)
    separate_item: bool = False
    package_size: Quantity | None = None


class StockSource(StrictModel):
    lot_id: UUID | None = None
    location_id: UUID | None = None


class Move(StockSource):
    to_location_id: UUID | None = None
    quantity: Quantity | None = None
    unit_code: str | None = None
    whole_presence: bool = False


class Consume(StockSource):
    quantity: Quantity | None = None
    unit_code: str | None = None
    reason: str = Field("Расход", max_length=500)


class SetQuantity(StockSource):
    quantity: Quantity | None = None
    quantity_state: QuantityState = "exact"
    reason: str = Field("Корректировка", min_length=1, max_length=500)


class ItemRef(StrictModel):
    item_id: UUID | None = None


class UpdateItem(ItemRef):
    name: str | None = Field(None, min_length=1, max_length=255)
    primary_category: Category | None = None
    attributes: dict | None = None
    tags: list[str] | None = Field(None, max_length=30)
    barcode: str | None = Field(None, max_length=100)
    brand: str | None = Field(None, max_length=255)
    model: str | None = Field(None, max_length=255)
    user_description: str | None = Field(None, max_length=10000)
    privacy_policy: Policy | None = None


class UpdateLot(LotFields):
    lot_id: UUID | None = None
    privacy_policy: Policy | None = None


class SplitLot(LotFields, StockSource):
    quantity: Quantity | None = None


class MergeLots(StrictModel):
    lot_ids: list[UUID] = Field(default_factory=list, min_length=2, max_length=20)


class CreateLocation(StrictModel):
    name: str | None = Field(None, max_length=255)
    parent_id: UUID | None = None
    description: str | None = Field(None, max_length=5000)
    kind: Literal["place", "container"] = "place"
    default_privacy_policy: Policy | None = None


class MoveLocation(StrictModel):
    location_id: UUID | None = None
    parent_id: UUID | None = None


class UpdateLocation(StrictModel):
    location_id: UUID | None = None
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=5000)
    default_privacy_policy: Policy | None = None


class ArchiveLocation(StrictModel):
    location_id: UUID | None = None
    transfer_to_id: UUID | None = None


class AddAlias(ItemRef):
    alias: str | None = Field(None, min_length=1, max_length=255)
    scope: Literal["user", "workspace"] = "workspace"


class RemoveAlias(StrictModel):
    alias_id: UUID | None = None


class Reverse(StrictModel):
    operation_id: UUID


COMMANDS: dict[str, type[StrictModel]] = {
    "receive_stock": Receive,
    "move_stock": Move,
    "consume_stock": Consume,
    "set_quantity": SetQuantity,
    "update_item": UpdateItem,
    "update_lot": UpdateLot,
    "split_lot": SplitLot,
    "merge_lots": MergeLots,
    "create_location": CreateLocation,
    "move_location": MoveLocation,
    "update_location": UpdateLocation,
    "archive_item": ItemRef,
    "restore_item": ItemRef,
    "archive_location": ArchiveLocation,
    "add_alias": AddAlias,
    "remove_alias": RemoveAlias,
    "confirm_presence": StockSource,
    "reverse_operation": Reverse,
}
CommandType = Literal[
    "receive_stock",
    "move_stock",
    "consume_stock",
    "set_quantity",
    "update_item",
    "update_lot",
    "split_lot",
    "merge_lots",
    "create_location",
    "move_location",
    "update_location",
    "archive_item",
    "restore_item",
    "archive_location",
    "add_alias",
    "remove_alias",
    "confirm_presence",
    "reverse_operation",
]


class Action(StrictModel):
    action_id: str = Field("a1", pattern=r"^[a-zA-Z0-9_-]{1,60}$")
    type: CommandType
    values: dict

    @model_validator(mode="after")
    def validate_values(self):
        schema = COMMANDS[self.type]
        values = schema.model_validate(self.values)
        # PATCH не превращает незаданные поля в явное обнуление.
        self.values = values.model_dump(mode="json", exclude_unset=self.type.startswith("update_"))
        return self


class ManualProposal(StrictModel):
    actions: list[Action] = Field(min_length=1, max_length=50)
    expected_versions: dict[str, int] = Field(default_factory=dict)
    client_request_id: UUID


class ManualConfirm(ManualProposal):
    explicit_confirmation: Literal[True]


class Change(StrictModel):
    action_id: str
    key: str
    value: object


class EditProposal(StrictModel):
    expected_revision: int = Field(ge=1)
    changes: list[Change] = Field(default_factory=list, max_length=100)


class ConfirmProposal(EditProposal):
    observed_review_hash: str
    client_request_id: UUID


class Context(StrictModel):
    location_id: UUID | None = None
    item_id: UUID | None = None


class Privacy(StrictModel):
    force_local: bool = True


class TaskCreate(StrictModel):
    workspace_id: UUID | None = None
    client_request_id: UUID
    input_mode: Literal["text", "photo", "audio", "photo_audio", "manual"] = "text"
    text: str | None = Field(None, max_length=16000)
    media_ids: list[UUID] = Field(default_factory=list, max_length=20)
    audio_media_id: UUID | None = None
    context: Context = Field(default_factory=Context)
    privacy: Privacy = Field(default_factory=Privacy)
    batch_id: UUID | None = None


class EvidenceValue(StrictModel):
    field: str
    source: Literal["text", "audio", "image", "model", "user", "default"]
    media_id: UUID | None = None
    region: dict | None = None
    value: object = None


class Extraction(StrictModel):
    schema_version: Literal["extraction.v1"] = "extraction.v1"
    intent_candidates: list[str] = Field(default_factory=list)
    extracted_entities: list[dict] = Field(default_factory=list)
    fields: dict = Field(default_factory=dict)
    evidence: list[EvidenceValue] = Field(default_factory=list)
    ambiguity: list[str] = Field(default_factory=list)
    privacy_signals: list[str] = Field(default_factory=list)
    quality_issues: list[str] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    read_only_query: str | None = None


class GatekeeperItem(StrictModel):
    name: str
    category: str


class Gatekeeper(StrictModel):
    is_safe: bool | None = None
    sensitive_flags: list[str] = Field(default_factory=list)
    transcription: str | None = None
    items: list[GatekeeperItem] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    confidence_score: float | None = Field(None, ge=0, le=1)
