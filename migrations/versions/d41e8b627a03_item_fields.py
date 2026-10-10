"""Схема пользовательских свойств и их значения без изменения существующих вещей."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "d41e8b627a03"
down_revision = "c90a51d77e20"
branch_labels = depends_on = None


def upgrade():
    for table, column in (("workspaces", "item_fields"), ("items", "custom_attributes")):
        op.add_column(
            table, sa.Column(column, JSONB(), nullable=False, server_default="{}"), schema="inventory"
        )
        op.alter_column(table, column, server_default=None, schema="inventory")
    op.add_column(
        "workspaces",
        sa.Column("item_fields_version", sa.Integer(), nullable=False, server_default="1"),
        schema="inventory",
    )
    op.alter_column("workspaces", "item_fields_version", server_default=None, schema="inventory")


def downgrade():
    op.drop_column("items", "custom_attributes", schema="inventory")
    op.drop_column("workspaces", "item_fields_version", schema="inventory")
    op.drop_column("workspaces", "item_fields", schema="inventory")
