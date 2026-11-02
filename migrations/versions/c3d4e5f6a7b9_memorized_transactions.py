"""memorized transactions (QuickBooks' Memorized Transaction List); now empty

Revision ID: c3d4e5f6a7b9
Revises: e8f9a0b1c2d3
Create Date: 2026-10-19

"""

from typing import Sequence, Union


revision: str = "c3d4e5f6a7b9"
down_revision: Union[str, None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # John's build kept its own memorized_transactions table here (a pattern
    # as JSON) until 2.31.1 brought memorized transactions of its own under
    # the same name. A company file this revision already ran on keeps the
    # old table until c9e5a7b3d1f2 moves it aside and f6a7b8c9d0e2 carries
    # its cheques, bills and journal entries into the new one; a new file
    # never makes it.
    pass


def downgrade() -> None:
    pass
