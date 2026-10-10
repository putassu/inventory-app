"""Полный подтверждённый текст OCR хранится отдельно от описания."""

import sqlalchemy as sa
from alembic import op

revision = "af426b7d9102"
down_revision = "721e69034285"
branch_labels = depends_on = None


def upgrade():
    op.add_column("items", sa.Column("ocr_text", sa.Text(), nullable=True), schema="inventory")


def downgrade():
    op.drop_column("items", "ocr_text", schema="inventory")
