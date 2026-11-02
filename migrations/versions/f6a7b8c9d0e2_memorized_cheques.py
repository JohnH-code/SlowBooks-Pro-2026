"""John's build on 2.31: memorized cheques and card charges, and the old
build's memorized transactions carried over

2.31.1's memorized transactions keep bills and journal entries. John's
build adds a third kind, a cheque or card charge (an expense): the account
it is paid from and a payee who is not a vendor on the header, and a
GST/HST code on a line (a line's amount is its debit, as a journal line's).

A company file opened by the 2.24 / 2.29 builds had that build's own list,
moved aside by c9e5a7b3d1f2 as john_memorized_old. Its cheques, bills and
journal entries are carried into the new tables with their schedules;
deposits and invoices are not (2.31 keeps recurring invoices as Recurring
Invoices, and memorizes no deposits), so the table stays only while it
still holds one of those.

Revision ID: f6a7b8c9d0e2
Revises: e5f6a7b8c9d1, 95209e8d293c
Create Date: 2026-11-02

"""

import json
from datetime import date
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f6a7b8c9d0e2"
down_revision: Union[str, Sequence[str], None] = ("e5f6a7b8c9d1", "95209e8d293c")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = "john_memorized_old"

# the old build's How often → (frequency, interval) as 2.31 stores them
_FREQ = {
    "weekly": ("weekly", 1),
    "biweekly": ("weekly", 2),
    "monthly": ("monthly", 1),
    "quarterly": ("quarterly", 1),
    "semiannually": ("monthly", 6),
    "annually": ("yearly", 1),
}


def _add(insp, table, column):
    if column.name not in {c["name"] for c in insp.get_columns(table)}:
        op.add_column(table, column)


def _day(value):
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _num(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _carry(bind) -> None:
    rows = bind.execute(
        sa.text(
            f"SELECT id, name, kind, payload, frequency, next_date, action, "
            f"remaining, is_active, last_entered, times_entered FROM {OLD}"
        )
    ).fetchall()
    mt = sa.Table(
        "memorized_transactions",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), primary_key=True),
        *(
            sa.Column(c)
            for c in (
                "kind name mode frequency interval start_date next_date anchor_day "
                "occurrences_limit entered_count is_active last_entered_on vendor_id "
                "terms tax_rate notes description reference is_adjusting basis "
                "class_id job_id paid_from_account_id payee"
            ).split()
        ),
    )
    ml = sa.table(
        "memorized_transaction_lines",
        *(
            sa.column(c)
            for c in (
                "memorized_id line_order account_id description job_id class_id "
                "is_billable item_id quantity rate debit credit tax_code"
            ).split()
        ),
    )
    carried = []
    for row in rows:
        kind = row.kind
        if kind not in ("expense", "bill", "journal"):
            continue
        try:
            p = json.loads(row.payload or "{}")
        except ValueError:
            continue
        frequency, interval = _FREQ.get(row.frequency, ("monthly", 1))
        nxt = _day(row.next_date) or date.today()
        header = {
            "kind": kind,
            "name": (row.name or kind.title())[:120],
            "mode": "auto" if row.action == "auto" else "remind",
            "frequency": frequency,
            "interval": interval,
            "start_date": nxt,
            "next_date": nxt,
            "anchor_day": nxt.day,
            "occurrences_limit": row.remaining,
            "entered_count": 0,
            # "never" and "don't remind me" have no schedule: kept, paused
            "is_active": bool(row.is_active)
            and row.frequency in _FREQ
            and row.action != "none",
            "last_entered_on": _day(row.last_entered),
            "vendor_id": p.get("vendor_id"),
            "terms": p.get("terms"),
            "tax_rate": _num(p.get("tax_rate")),
            "notes": p.get("notes") or p.get("memo"),
            "description": p.get("description"),
            "reference": p.get("reference"),
            "is_adjusting": False,
            "basis": None,
            "class_id": p.get("class_id"),
            "job_id": p.get("job_id"),
            "paid_from_account_id": p.get("paid_from_account_id"),
            "payee": p.get("payee") if kind == "expense" else None,
        }
        lines = []
        for i, ln in enumerate(p.get("lines") or []):
            line = {
                "line_order": i,
                "account_id": ln.get("account_id"),
                "description": ln.get("description") or ln.get("memo"),
                "job_id": ln.get("job_id"),
                "class_id": ln.get("class_id"),
                "is_billable": False,
                "item_id": None,
                "quantity": None,
                "rate": None,
                "debit": None,
                "credit": None,
                "tax_code": None,
            }
            if kind == "expense":
                amount = _num(ln.get("amount"))
                if amount <= 0:
                    continue
                line["debit"] = amount
                line["tax_code"] = ln.get("tax_code") or None
            elif kind == "bill":
                line["item_id"] = ln.get("item_id")
                line["quantity"] = _num(ln.get("quantity")) or 1
                line["rate"] = _num(ln.get("rate"))
            else:
                line["debit"] = _num(ln.get("debit"))
                line["credit"] = _num(ln.get("credit"))
            lines.append(line)
        if not lines:
            continue
        new_id = bind.execute(mt.insert().values(**header)).inserted_primary_key[0]
        bind.execute(ml.insert(), [{**ln, "memorized_id": new_id} for ln in lines])
        carried.append(row.id)
    for old_id in carried:
        bind.execute(sa.text(f"DELETE FROM {OLD} WHERE id = :i"), {"i": old_id})


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    _add(
        insp,
        "memorized_transactions",
        sa.Column("paid_from_account_id", sa.Integer(), nullable=True),
    )
    _add(
        insp,
        "memorized_transactions",
        sa.Column("payee", sa.String(200), nullable=True),
    )
    _add(
        insp,
        "memorized_transaction_lines",
        sa.Column("tax_code", sa.String(2), nullable=True),
    )
    if OLD in insp.get_table_names():
        _carry(bind)
        left = bind.execute(sa.text(f"SELECT COUNT(*) FROM {OLD}")).scalar()
        if not left:
            op.drop_table(OLD)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM memorized_transactions WHERE kind = 'expense'"))
    with op.batch_alter_table("memorized_transaction_lines") as batch:
        batch.drop_column("tax_code")
    with op.batch_alter_table("memorized_transactions") as batch:
        batch.drop_column("payee")
        batch.drop_column("paid_from_account_id")
