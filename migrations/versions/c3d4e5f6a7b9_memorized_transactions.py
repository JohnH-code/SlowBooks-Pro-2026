"""memorized transactions (QuickBooks' Memorized Transaction List)

Revision ID: c3d4e5f6a7b9
Revises: e8f9a0b1c2d3
Create Date: 2026-10-19

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c3d4e5f6a7b9"
down_revision: Union[str, None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memorized_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("frequency", sa.String(20), nullable=False, server_default="monthly"),
        sa.Column("next_date", sa.Date(), nullable=True),
        sa.Column("action", sa.String(10), nullable=False, server_default="remind"),
        sa.Column("days_in_advance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("remaining", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_entered", sa.Date(), nullable=True),
        sa.Column("times_entered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_memorized_transactions_id", "memorized_transactions", ["id"])


def downgrade() -> None:
    op.drop_index("ix_memorized_transactions_id", "memorized_transactions")
    op.drop_table("memorized_transactions")
