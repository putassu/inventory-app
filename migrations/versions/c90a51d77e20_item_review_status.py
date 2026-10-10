"""Неподтверждённые вещи доступны в каталоге до ручной проверки."""

import sqlalchemy as sa
from alembic import op

revision = "c90a51d77e20"
down_revision = "af426b7d9102"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "items",
        sa.Column("review_status", sa.String(20), nullable=False, server_default="confirmed"),
        schema="inventory",
    )
    op.add_column("items", sa.Column("source_task_id", sa.String(36), nullable=True), schema="inventory")
    op.create_index("ix_inventory_items_review_status", "items", ["review_status"], schema="inventory")
    op.create_index("ix_inventory_items_source_task_id", "items", ["source_task_id"], schema="inventory")
    op.create_check_constraint(
        "item_review_status",
        "items",
        "review_status IN ('processing','unconfirmed','confirmed','error')",
        schema="inventory",
    )
    op.alter_column("items", "review_status", server_default=None, schema="inventory")


def downgrade():
    op.drop_constraint("item_review_status", "items", schema="inventory", type_="check")
    op.drop_index("ix_inventory_items_source_task_id", table_name="items", schema="inventory")
    op.drop_index("ix_inventory_items_review_status", table_name="items", schema="inventory")
    op.drop_column("items", "source_task_id", schema="inventory")
    op.drop_column("items", "review_status", schema="inventory")
