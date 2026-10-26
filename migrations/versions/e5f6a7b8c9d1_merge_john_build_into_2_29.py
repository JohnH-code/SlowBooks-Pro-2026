"""merge: John's build (memorized transactions) with 2.29.2's line

A company file opened by the 2.24 build is at d4e5f6a7b8c0 and picks up
the revisions upstream added through 2.29.2 here; a 2.29.2 file picks up
the memorized table.

Revision ID: e5f6a7b8c9d1
Revises: d4e5f6a7b8c0, f2e3d4c5b6a7
Create Date: 2026-10-26

"""

from typing import Sequence, Union

revision: str = "e5f6a7b8c9d1"
down_revision: Union[str, Sequence[str], None] = ("d4e5f6a7b8c0", "f2e3d4c5b6a7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
