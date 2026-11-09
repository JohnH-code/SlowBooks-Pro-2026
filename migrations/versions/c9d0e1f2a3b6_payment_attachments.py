"""John's build: documents on customer payments and bill payments

A customer payment and a bill payment take attachments of their own (the
cheque received, the remittance), as QuickBooks keeps them. QuickBooks
documents brought over before this went onto the journal entry behind the
payment, where they could not be seen from it: they move onto the payment.

Revision ID: c9d0e1f2a3b6
Revises: b8c9d0e1f2a5
Create Date: 2026-11-09

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c9d0e1f2a3b6"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if not {"attachments", "transactions"} <= tables:
        return
    for kind in ("payment", "bill_payment"):
        bind.execute(
            sa.text(
                "UPDATE attachments SET entity_type = :kind, entity_id = ("
                " SELECT t.source_id FROM transactions t WHERE t.id = attachments.entity_id)"
                " WHERE entity_type = 'journal_entry' AND entity_id IN ("
                " SELECT t.id FROM transactions t"
                " WHERE t.source_type = :kind AND t.source_id IS NOT NULL)"
            ),
            {"kind": kind},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for kind, table in (("payment", "payments"), ("bill_payment", "bill_payments")):
        bind.execute(
            sa.text(
                f"UPDATE attachments SET entity_type = 'journal_entry', entity_id = ("
                f" SELECT p.transaction_id FROM {table} p WHERE p.id = attachments.entity_id)"
                f" WHERE entity_type = :kind"
            ),
            {"kind": kind},
        )
