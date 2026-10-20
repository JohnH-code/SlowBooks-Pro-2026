# ============================================================================
# Memorized transactions — keep a cheque, bill, deposit, journal entry or
# invoice as a pattern and enter it again: by hand from the list, when its
# reminder comes due, or automatically on its date (QuickBooks' Memorized
# Transaction List: Remind Me / Automatically Enter / Don't Remind Me).
#
# A memorized transaction is the create request its own form sends (the
# pattern), less the date. Entering it posts through that same route, so a
# memorized cheque is checked and posted exactly as a typed one is.
# ============================================================================

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.accounts import Account
from app.models.memorized import MemorizedTransaction
from app.models.transactions import Transaction

KINDS = ("expense", "bill", "deposit", "journal", "invoice")
FREQUENCIES = ("never", "weekly", "biweekly", "monthly", "quarterly", "semiannually", "annually")
ACTIONS = ("remind", "auto", "none")
_MONTHS = {"monthly": 1, "quarterly": 3, "semiannually": 6, "annually": 12}


def advance(d: date, frequency: str, anchor_day: int | None = None) -> date | None:
    """The date after `d` on the schedule; None for "never"."""
    if frequency == "weekly":
        return d + timedelta(days=7)
    if frequency == "biweekly":
        return d + timedelta(days=14)
    months = _MONTHS.get(frequency)
    if not months:
        return None
    import calendar

    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    day = min(anchor_day or d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def _f(v) -> float:
    return float(Decimal(str(v or 0)))


# ---------------------------------------------------------------- patterns


def pattern_from_transaction(db: Session, txn: Transaction) -> tuple[str, dict, str]:
    """(kind, payload, a suggested name) for an entered transaction."""
    st = txn.source_type or ""
    if st == "expense":
        from app.routes.expenses import _serialize, paid_from_line

        out = _serialize(txn, db, False)
        credit = paid_from_line(txn)
        lines = []
        for ln in txn.lines:
            if ln is credit:
                continue
            amount = _f(ln.debit) - _f(ln.credit)
            memo = ln.description or ""
            lines.append({
                "account_id": ln.account_id,
                "amount": f"{amount:.2f}",
                "memo": None if memo == out.payee else (memo or None),
                "class_id": ln.class_id,
                "job_id": ln.job_id,
            })
        payload = {
            "vendor_id": out.vendor_id,
            "payee": out.payee or None,
            "paid_from_account_id": credit.account_id if credit else None,
            "lines": lines,
            "class_id": txn.class_id,
            "job_id": txn.job_id,
        }
        return "expense", payload, out.payee or "Cheque"
    if st == "bill":
        from app.models.bills import Bill

        bill = db.get(Bill, txn.source_id)
        if bill is None:
            raise HTTPException(status_code=404, detail="The bill behind this transaction is gone")
        payload = {
            "vendor_id": bill.vendor_id,
            "terms": bill.terms or "Net 30",
            "tax_rate": _f(bill.tax_rate),
            "notes": bill.notes,
            "class_id": bill.class_id,
            "job_id": bill.job_id,
            "lines": [
                {
                    "item_id": l.item_id,
                    "account_id": l.account_id,
                    "description": l.description,
                    "quantity": _f(l.quantity) or 1,
                    "rate": _f(l.rate),
                    "class_id": l.class_id,
                    "job_id": l.job_id,
                    "line_order": l.line_order or i,
                }
                for i, l in enumerate(bill.lines)
            ],
        }
        return "bill", payload, bill.vendor.name if bill.vendor else "Bill"
    if st == "invoice":
        from app.models.invoices import Invoice

        inv = db.get(Invoice, txn.source_id)
        if inv is None:
            raise HTTPException(status_code=404, detail="The invoice behind this transaction is gone")
        payload = {
            "customer_id": inv.customer_id,
            "terms": inv.terms or "Net 30",
            "tax_rate": str(inv.tax_rate or 0),
            "notes": inv.notes,
            "class_id": inv.class_id,
            "job_id": inv.job_id,
            "lines": [
                {
                    "item_id": l.item_id,
                    "description": l.description,
                    "quantity": _f(l.quantity) or 1,
                    "rate": _f(l.rate),
                    "is_taxable": bool(getattr(l, "is_taxable", True)),
                    "line_order": getattr(l, "line_order", i) or i,
                }
                for i, l in enumerate(inv.lines)
            ],
        }
        return "invoice", payload, inv.customer.name if inv.customer else "Invoice"
    if st == "deposit":
        bank = next(
            (l for l in txn.lines if _f(l.debit) > 0 and l.account and l.account.bank_kind),
            None,
        )
        if bank is None:
            raise HTTPException(status_code=400, detail="This deposit has no bank line to memorize")
        from app.services import control_accounts

        uf = control_accounts.find(db, "1200")
        others = [
            {
                "account_id": l.account_id,
                "amount": f"{_f(l.credit) - _f(l.debit):.2f}",
                "memo": l.description or None,
            }
            for l in txn.lines
            if l is not bank and l.account_id != uf
        ]
        if not others:
            raise HTTPException(
                status_code=400,
                detail="This deposit only banked customer payments; there is nothing in it to repeat",
            )
        payload = {"deposit_to_account_id": bank.account_id, "other_lines": others, "class_id": txn.class_id}
        return "deposit", payload, txn.description or "Deposit"
    # a journal entry (typed, or brought over from QuickBooks)
    lines = [
        {
            "account_id": l.account_id,
            "debit": f"{_f(l.debit):.2f}",
            "credit": f"{_f(l.credit):.2f}",
            "description": l.description or None,
            "class_id": l.class_id,
            "job_id": l.job_id,
        }
        for l in txn.lines
    ]
    payload = {"description": txn.description or "Journal entry", "lines": lines, "class_id": txn.class_id}
    return "journal", payload, txn.description or "Journal entry"


# ---------------------------------------------------------------- entering


def _clean(payload: dict, schema) -> dict:
    """Drop keys a schema doesn't take (a pattern saved by an older build)."""
    fields = set(schema.model_fields)
    out = {k: v for k, v in payload.items() if k in fields}
    if "lines" in out and hasattr(schema.model_fields["lines"].annotation, "__args__"):
        line_schema = schema.model_fields["lines"].annotation.__args__[0]
        keep = set(line_schema.model_fields)
        out["lines"] = [{k: v for k, v in ln.items() if k in keep} for ln in out["lines"]]
    return out


def enter(db: Session, m: MemorizedTransaction, on: date, overrides: dict | None = None) -> dict:
    """Post the memorized transaction dated `on`. Returns where it went:
    {kind, id}. Raises the route's own HTTPException when it is refused."""
    payload = {**json.loads(m.payload), **(overrides or {})}
    payload["date"] = on.isoformat()
    if m.kind == "expense":
        from app.routes.expenses import create_expense, next_cheque_number
        from app.schemas.expenses import ExpenseCreate

        if not payload.get("reference") and payload.get("paid_from_account_id"):
            payload["reference"] = next_cheque_number(payload["paid_from_account_id"], db)["number"]
        if payload.get("lines") and len(payload["lines"]) == 1 and not payload["lines"][0].get("tax_code"):
            # keep it a one-account expense, as it was typed
            ln = payload.pop("lines")[0]
            payload.update(expense_account_id=ln["account_id"], amount=ln["amount"],
                           memo=payload.get("memo") or ln.get("memo"))
        out = create_expense(ExpenseCreate(**_clean(payload, ExpenseCreate)), db)
        return {"kind": "expense", "id": out.id}
    if m.kind == "bill":
        from app.routes.bills import create_bill
        from app.schemas.bills import BillCreate

        out = create_bill(BillCreate(**_clean(payload, BillCreate)), db)
        return {"kind": "bill", "id": out.id}
    if m.kind == "invoice":
        from app.routes.invoices.crud import create_invoice
        from app.schemas.invoices import InvoiceCreate

        out = create_invoice(InvoiceCreate(**_clean(payload, InvoiceCreate)), db)
        return {"kind": "invoice", "id": out.id}
    if m.kind == "deposit":
        from app.routes.deposits import create_deposit
        from app.schemas.deposits import DepositCreate

        out = create_deposit(DepositCreate(**_clean(payload, DepositCreate)), db)
        tid = out.get("transaction_id") if isinstance(out, dict) else getattr(out, "transaction_id", None)
        return {"kind": "deposit", "id": tid}
    if m.kind == "journal":
        from app.routes.journal import create_manual_journal_entry
        from app.schemas.journal import JournalEntryCreate

        out = create_manual_journal_entry(JournalEntryCreate(**_clean(payload, JournalEntryCreate)), db)
        return {"kind": "journal", "id": out.id}
    raise HTTPException(status_code=400, detail=f"Unknown memorized kind {m.kind}")


def _schema(kind: str):
    if kind == "expense":
        from app.schemas.expenses import ExpenseCreate as S
    elif kind == "bill":
        from app.schemas.bills import BillCreate as S
    elif kind == "invoice":
        from app.schemas.invoices import InvoiceCreate as S
    elif kind == "deposit":
        from app.schemas.deposits import DepositCreate as S
    elif kind == "journal":
        from app.schemas.journal import JournalEntryCreate as S
    else:
        raise HTTPException(status_code=400, detail=f"Unknown memorized kind {kind}")
    return S


def check_payload(kind: str, payload: dict) -> None:
    """Refuse an edited pattern its form would refuse (422, the reason)."""
    from pydantic import ValidationError

    S = _schema(kind)
    try:
        S(**_clean({**payload, "date": date.today().isoformat()}, S))
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail="; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()),
        )
    lines = payload.get("other_lines" if kind == "deposit" else "lines") or []
    if not lines:
        raise HTTPException(status_code=422, detail="It needs at least one line")
    if kind == "journal":
        dr = sum(Decimal(str(l.get("debit") or 0)) for l in lines)
        cr = sum(Decimal(str(l.get("credit") or 0)) for l in lines)
        if dr != cr:
            raise HTTPException(status_code=422, detail=f"Debits ({dr}) and credits ({cr}) must be equal")


def mark_entered(m: MemorizedTransaction, on: date) -> None:
    """Move the schedule on after an entry dated `on` for the due date."""
    m.last_entered = on
    m.times_entered = (m.times_entered or 0) + 1
    if m.remaining is not None:
        m.remaining = max(m.remaining - 1, 0)
    if m.next_date is not None:
        nxt = advance(m.next_date, m.frequency, m.next_date.day)
        m.next_date = nxt if (m.remaining is None or m.remaining > 0) else None


def due(db: Session, today: date | None = None) -> list[MemorizedTransaction]:
    """Reminders showing today: active, scheduled, Remind Me, and within
    their days in advance of the next date."""
    today = today or date.today()
    out = []
    for m in db.query(MemorizedTransaction).filter(MemorizedTransaction.is_active.is_(True)):
        if m.next_date is None or m.action != "remind":
            continue
        if m.next_date - timedelta(days=m.days_in_advance or 0) <= today:
            out.append(m)
    return sorted(out, key=lambda m: (m.next_date, m.name.lower()))


def auto_enter(db: Session, today: date | None = None) -> list[dict]:
    """Enter every Automatically Enter transaction whose date has come
    (each missed date once, as QuickBooks does). One that is refused stays
    due and is reported."""
    today = today or date.today()
    done = []
    for m in db.query(MemorizedTransaction).filter(
        MemorizedTransaction.is_active.is_(True), MemorizedTransaction.action == "auto"
    ).all():
        guard = 0
        while m.next_date is not None and m.next_date - timedelta(days=m.days_in_advance or 0) <= today and guard < 60:
            guard += 1
            on = m.next_date
            try:
                where = enter(db, m, on)
            except HTTPException as exc:
                db.rollback()
                done.append({"memorized_id": m.id, "name": m.name, "date": on.isoformat(), "error": str(exc.detail)})
                break
            mark_entered(m, on)
            db.commit()
            done.append({"memorized_id": m.id, "name": m.name, "date": on.isoformat(), **where})
    return done


def describe(db: Session, m: MemorizedTransaction) -> dict:
    payload = json.loads(m.payload)
    amount = 0.0
    if m.kind == "expense":
        amount = sum(float(l.get("amount") or 0) for l in payload.get("lines") or []) or float(payload.get("amount") or 0)
    elif m.kind in ("bill", "invoice"):
        amount = sum(float(l.get("quantity") or 1) * float(l.get("rate") or 0) for l in payload.get("lines") or [])
    elif m.kind == "deposit":
        amount = sum(float(l.get("amount") or 0) for l in payload.get("other_lines") or [])
    elif m.kind == "journal":
        amount = sum(float(l.get("debit") or 0) for l in payload.get("lines") or [])
    account = ""
    acct_id = payload.get("paid_from_account_id") or payload.get("deposit_to_account_id")
    if acct_id:
        a = db.get(Account, acct_id)
        account = a.name if a else ""
    return {
        "id": m.id,
        "name": m.name,
        "kind": m.kind,
        "frequency": m.frequency,
        "next_date": m.next_date.isoformat() if m.next_date else None,
        "action": m.action,
        "days_in_advance": m.days_in_advance or 0,
        "remaining": m.remaining,
        "is_active": bool(m.is_active),
        "last_entered": m.last_entered.isoformat() if m.last_entered else None,
        "times_entered": m.times_entered or 0,
        "amount": round(amount, 2),
        "account": account,
        "payload": payload,
    }
