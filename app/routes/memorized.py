# ============================================================================
# Memorized Transactions — the list, the schedule, Enter, and the reminders
# (services/memorized.py does the work).
# ============================================================================

import json
from datetime import date
from datetime import date as dt_date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from app.schemas.common import StrictModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.memorized import MemorizedTransaction
from app.models.transactions import Transaction
from app.services import memorized as svc

router = APIRouter(prefix="/api/memorized", tags=["memorized"])


class Schedule(StrictModel):
    name: Optional[str] = Field(None, max_length=200)
    frequency: Optional[str] = None
    next_date: Optional[date] = None
    action: Optional[str] = None
    days_in_advance: Optional[int] = Field(None, ge=0, le=365)
    remaining: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None


class FromTransaction(Schedule):
    # the transaction, or the bill or invoice it posted
    transaction_id: Optional[int] = None
    bill_id: Optional[int] = None
    invoice_id: Optional[int] = None


class EnterRequest(StrictModel):
    date: Optional[dt_date] = None
    # a one-off change for this entry: the amount of a one-line pattern
    amount: Optional[float] = None


def _apply(m: MemorizedTransaction, s: Schedule, fields: set) -> None:
    if s.frequency is not None:
        if s.frequency not in svc.FREQUENCIES:
            raise HTTPException(
                status_code=422,
                detail=f"frequency must be one of {', '.join(svc.FREQUENCIES)}",
            )
        m.frequency = s.frequency
    if s.action is not None:
        if s.action not in svc.ACTIONS:
            raise HTTPException(
                status_code=422, detail="action must be remind, auto or none"
            )
        m.action = s.action
    if s.name:
        m.name = s.name.strip()
    if "next_date" in fields:
        m.next_date = s.next_date
    if s.days_in_advance is not None:
        m.days_in_advance = s.days_in_advance
    if "remaining" in fields:
        m.remaining = s.remaining
    if s.is_active is not None:
        m.is_active = s.is_active
    if m.frequency == "never":
        m.next_date = None


def _get(db: Session, mid: int) -> MemorizedTransaction:
    m = db.get(MemorizedTransaction, mid)
    if m is None:
        raise HTTPException(status_code=404, detail="Memorized transaction not found")
    return m


@router.get("")
def list_memorized(db: Session = Depends(get_db)):
    rows = db.query(MemorizedTransaction).all()
    return sorted((svc.describe(db, m) for m in rows), key=lambda d: d["name"].lower())


@router.get("/due")
def due_reminders(db: Session = Depends(get_db)):
    """The reminders to show now."""
    return [svc.describe(db, m) for m in svc.due(db)]


@router.post("/auto-enter")
def auto_enter(db: Session = Depends(get_db)):
    """Enter what is set to enter itself and has come due (the dashboard
    calls this as it opens)."""
    return {"entered": svc.auto_enter(db)}


@router.post("/from-transaction", status_code=201)
def memorize(body: FromTransaction, db: Session = Depends(get_db)):
    """Memorize an entered transaction (QuickBooks: Edit → Memorize)."""
    if body.transaction_id:
        txn = db.get(Transaction, body.transaction_id)
    else:
        kind, sid = (
            ("bill", body.bill_id) if body.bill_id else ("invoice", body.invoice_id)
        )
        txn = (
            db.query(Transaction)
            .filter(Transaction.source_type == kind, Transaction.source_id == sid)
            .order_by(Transaction.id)
            .first()
        )
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    kind, payload, name = svc.pattern_from_transaction(db, txn)
    m = MemorizedTransaction(
        name=(body.name or name)[:200],
        kind=kind,
        payload=json.dumps(payload),
        frequency="monthly",
        action="remind",
        days_in_advance=0,
    )
    _apply(m, body, body.model_fields_set)
    if "next_date" not in body.model_fields_set and m.frequency != "never":
        m.next_date = svc.advance(txn.date, m.frequency) or txn.date
    db.add(m)
    db.commit()
    return svc.describe(db, m)


class Update(Schedule):
    # the pattern itself (payee, accounts, lines …), as its form sends it
    payload: Optional[dict] = None


@router.put("/{mid}")
def update(mid: int, body: Update, db: Session = Depends(get_db)):
    m = _get(db, mid)
    if body.payload is not None:
        svc.check_payload(m.kind, body.payload)
        m.payload = json.dumps(body.payload)
    _apply(m, body, body.model_fields_set)
    db.commit()
    return svc.describe(db, m)


@router.delete("/{mid}")
def delete(mid: int, db: Session = Depends(get_db)):
    m = _get(db, mid)
    db.delete(m)
    db.commit()
    return {"deleted": mid}


@router.post("/{mid}/enter")
def enter_now(mid: int, body: EnterRequest, db: Session = Depends(get_db)):
    """Enter it now (dated `date`, else its next date, else today); a
    scheduled one moves on to its following date."""
    m = _get(db, mid)
    on = body.date or m.next_date or date.today()
    overrides = {}
    if body.amount is not None:
        payload = json.loads(m.payload)
        key = "other_lines" if m.kind == "deposit" else "lines"
        lines = payload.get(key) or []
        if m.kind not in ("expense", "deposit") or len(lines) != 1:
            raise HTTPException(
                status_code=400,
                detail="A new amount can only be given for a one-line cheque or deposit",
            )
        overrides[key] = [{**lines[0], "amount": f"{body.amount:.2f}"}]
    where = svc.enter(db, m, on, overrides)
    if m.next_date is not None:
        svc.mark_entered(m, on)
    else:
        m.last_entered = on
        m.times_entered = (m.times_entered or 0) + 1
    db.commit()
    return {**where, "memorized": svc.describe(db, m)}


@router.post("/{mid}/skip")
def skip(mid: int, db: Session = Depends(get_db)):
    """Skip this occurrence: move to the next date without entering."""
    m = _get(db, mid)
    if m.next_date is None:
        raise HTTPException(status_code=400, detail="It isn't scheduled")
    m.next_date = svc.advance(m.next_date, m.frequency, m.next_date.day)
    db.commit()
    return svc.describe(db, m)
