"""John's build on 2.31.14: join its own migrations (ending with the payment
attachments, c9d0e1f2a3b6) and Slowbooks 2.31.10-2.31.14's (ending with
token payroll and imports, f3b9d2e6a1c7). Nothing changes in the database.

Revision ID: d2e3f4a5b6c8
Revises: c9d0e1f2a3b6, f3b9d2e6a1c7
"""

revision = "d2e3f4a5b6c8"
down_revision = ("c9d0e1f2a3b6", "f3b9d2e6a1c7")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
