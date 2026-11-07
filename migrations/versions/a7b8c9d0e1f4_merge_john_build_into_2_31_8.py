"""merge: John's build (memorized cheques) with 2.31.8's line

Revision ID: a7b8c9d0e1f4
Revises: f6a7b8c9d0e2, d7f3a9c1b5e2
Create Date: 2026-11-07

"""

from typing import Sequence, Union

revision: str = "a7b8c9d0e1f4"
down_revision: Union[str, Sequence[str], None] = ("f6a7b8c9d0e2", "d7f3a9c1b5e2")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
