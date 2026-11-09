"""John's build: a cheque keeps the payee's address it was written with

Write Cheques' Address box can be changed, as QuickBooks lets it, and what
it held is the cheque's own: a vendor who moves later does not change the
address on a cheque already written. A bill payment keeps the vendor's
address as it stood when it was paid. NULL on everything written before:
those print the vendor's address as it is now, as before.

Revision ID: b8c9d0e1f2a5
Revises: a7b8c9d0e1f4
Create Date: 2026-11-08

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b8c9d0e1f2a5"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add(table: str) -> None:
    insp = sa.inspect(op.get_bind())
    if "payee_address" not in {c["name"] for c in insp.get_columns(table)}:
        op.add_column(table, sa.Column("payee_address", sa.Text(), nullable=True))


def upgrade() -> None:
    _add("transactions")
    _add("bill_payments")


def downgrade() -> None:
    with op.batch_alter_table("bill_payments") as batch:
        batch.drop_column("payee_address")
    with op.batch_alter_table("transactions") as batch:
        batch.drop_column("payee_address")
