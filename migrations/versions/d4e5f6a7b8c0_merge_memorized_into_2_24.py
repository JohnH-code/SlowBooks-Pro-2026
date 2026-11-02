"""merge: memorized transactions with 2.24.0's line

John's build added memorized_transactions (c3d4e5f6a7b9) on 2.23.3's head;
2.24.0 went on from the same point (b1c2d3e4f5a6, c2d3e4f5a6b7). A company
file upgraded by the earlier build is at c3d4e5f6a7b9 and picks up 2.24.0's
two revisions here; a 2.24.0 file picks up the memorized table.

Revision ID: d4e5f6a7b8c0
Revises: c2d3e4f5a6b7, c3d4e5f6a7b9
Create Date: 2026-10-20

"""

from typing import Sequence, Union

revision: str = "d4e5f6a7b8c0"
down_revision: Union[str, Sequence[str], None] = ("c2d3e4f5a6b7", "c3d4e5f6a7b9")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
