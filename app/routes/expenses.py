# ============================================================================
# Expenses — record a receipt that's already been paid (card, cash, check)
# DR Expense Account, CR the bank / credit-card account it was paid from.
# One step, no bill to pay later; the Scan Receipt flow lands here.
# ============================================================================

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.accounts import Account
from app.models.contacts import Vendor
from app.models.transactions import Transaction, TransactionLine
from app.schemas.expenses import (
    ExpenseCreate,
    ExpenseLineIn,
    ExpenseLineOut,
    ExpenseResponse,
)
from app.services.accounting import create_journal_entry, reversing_lines
from app.services.bank_posting import assert_not_reconciled, release_statement_links
from app.services.closing_date import check_closing_date

router = APIRouter(prefix="/api/expenses", tags=["expenses"])

SOURCE_TYPE = "expense"
VOID_SOURCE_TYPE = "expense_void"

# Accounts an expense can be paid from: cash on hand or credit extended.
PAID_FROM_TYPES = ("asset", "liability")


def _void_ids(db: Session, txn_ids: list[int]) -> set[int]:
    """Ids of expenses that already have a reversing entry posted."""
    if not txn_ids:
        return set()
    rows = (
        db.query(Transaction.source_id)
        .filter(
            Transaction.source_type == VOID_SOURCE_TYPE,
            Transaction.source_id.in_(txn_ids),
        )
        .all()
    )
    return {r[0] for r in rows}


def paid_from_line(txn: Transaction):
    """The line money left by: the credit on a bank or card account (the
    first, if a split credits another one too), else the largest credit.
    A simple expense has exactly one credit, so this is that line."""
    credits = [ln for ln in txn.lines if (ln.credit or 0) > 0]
    if not credits:
        return None
    banked = [ln for ln in credits if ln.account is not None and ln.account.bank_kind]
    if banked:
        return min(banked, key=lambda ln: ln.id or 0)
    return max(credits, key=lambda ln: ln.credit)


def _serialize(
    txn: Transaction,
    db: Session,
    voided: bool | None = None,
    vendors: dict | None = None,
) -> ExpenseResponse:
    if voided is None:
        voided = txn.id in _void_ids(db, [txn.id])
    credit_line = paid_from_line(txn)
    split = sorted(
        (ln for ln in txn.lines if ln is not credit_line),
        key=lambda ln: ln.id or 0,
    )
    if vendors is not None:
        vendor = vendors.get(txn.source_id) if txn.source_id else None
    else:
        vendor = (
            db.query(Vendor).filter(Vendor.id == txn.source_id).first()
            if txn.source_id
            else None
        )
    desc = txn.description or ""
    payee = vendor.name if vendor else desc.removeprefix("Expense: ").strip()
    lines = [
        ExpenseLineOut(
            account_id=ln.account_id,
            account_name=ln.account.name if ln.account else "",
            account_number=(ln.account.account_number or "") if ln.account else "",
            amount=float(Decimal(str(ln.debit or 0)) - Decimal(str(ln.credit or 0))),
            memo=ln.description or "",
        )
        for ln in split
    ]
    if len(lines) == 1:
        expense_account_name = lines[0].account_name
    elif lines:
        expense_account_name = f"Split ({len(lines)} accounts)"
    else:
        expense_account_name = ""
    return ExpenseResponse(
        id=txn.id,
        date=txn.date,
        payee=payee,
        vendor_id=vendor.id if vendor else None,
        expense_account_name=expense_account_name,
        paid_from_account_name=(
            credit_line.account.name if credit_line and credit_line.account else ""
        ),
        paid_from_kind=(
            (credit_line.account.bank_kind or "")
            if credit_line and credit_line.account
            else ""
        ),
        amount=float(credit_line.credit) if credit_line else 0.0,
        reference=txn.reference or "",
        memo=lines[0].memo if len(lines) == 1 else "",
        status="void" if voided else "recorded",
        printable=(
            not voided
            and credit_line is not None
            and credit_line.account is not None
            and credit_line.account.bank_kind == "bank"
        ),
        lines=lines,
    )


@router.get("", response_model=list[ExpenseResponse])
def list_expenses(db: Session = Depends(get_db)):
    from sqlalchemy.orm import selectinload

    # One query each for the lines, their accounts and the vendors: a
    # QuickBooks history brings thousands of cheques and card charges, and a
    # query per expense took ten seconds for 6,000.
    txns = (
        db.query(Transaction)
        .options(selectinload(Transaction.lines).selectinload(TransactionLine.account))
        .filter(Transaction.source_type == SOURCE_TYPE)
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .all()
    )
    voided = _void_ids(db, [t.id for t in txns])
    vendors = {v.id: v for v in db.query(Vendor).all()}
    return [_serialize(t, db, t.id in voided, vendors) for t in txns]


@router.get("/payees")
def list_payees(db: Session = Depends(get_db)):
    """Everyone an expense was ever paid to: the vendors (by id) and the
    other names written on cheques — employees, the Receiver General,
    QuickBooks' Other Names — that have no vendor record. QuickBooks offers
    them all in the Pay to the Order of box."""
    vendor_names = {(v.name or "").lower() for v in db.query(Vendor.name).all()}
    seen: dict[str, str] = {}
    for (desc,) in (
        db.query(Transaction.description)
        .filter(Transaction.source_type == SOURCE_TYPE)
        .filter(Transaction.source_id.is_(None))
        .distinct()
    ):
        name = (desc or "").removeprefix("Expense: ").strip()
        if not name or name == "Expense" or name.lower() in vendor_names:
            continue
        seen.setdefault(name.lower(), name)
    return sorted(seen.values(), key=str.lower)


@router.get("/quickfill")
def quickfill(
    vendor_id: Optional[int] = None,
    payee: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """The last expense paid to this vendor or payee — its accounts,
    amounts and memos — for the form to start from, as QuickBooks' QuickFill
    does. null when there is none."""
    q = db.query(Transaction).filter(Transaction.source_type == SOURCE_TYPE)
    if vendor_id:
        vendor = db.get(Vendor, vendor_id)
        names = [f"Expense: {vendor.name}"] if vendor else []
        q = q.filter(
            (Transaction.source_id == vendor_id) | (Transaction.description.in_(names))
        )
    elif payee:
        q = q.filter(Transaction.description == f"Expense: {payee.strip()}")
    else:
        return None
    voided_ids = {
        sid
        for (sid,) in db.query(Transaction.source_id).filter(
            Transaction.source_type == VOID_SOURCE_TYPE
        )
    }
    for txn in q.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(20):
        if txn.id in voided_ids:
            continue
        out = _serialize(txn, db, False)
        credit = paid_from_line(txn)
        return {
            "id": out.id,
            "date": out.date.isoformat(),
            "amount": out.amount,
            "paid_from_account_id": credit.account_id if credit else None,
            # a blank memo was saved as the payee's name: not worth repeating
            "lines": [
                {**ln.model_dump(), "memo": "" if ln.memo == out.payee else ln.memo}
                for ln in out.lines
            ],
        }
    return None


@router.get("/next-number")
def next_cheque_number(account_id: int, db: Session = Depends(get_db)):
    """The next cheque number for a bank account: one more than the highest
    number among its recent cheques (expenses and bill payments alike). A
    credit card has none."""
    import re

    acct = db.get(Account, account_id)
    if acct is None or acct.bank_kind != "bank":
        return {"number": None}
    refs = (
        db.query(Transaction.reference)
        .join(TransactionLine, TransactionLine.transaction_id == Transaction.id)
        .filter(TransactionLine.account_id == account_id, TransactionLine.credit > 0)
        .filter(Transaction.reference.isnot(None), Transaction.reference != "")
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .limit(60)
        .all()
    )
    numbers = []
    for (ref,) in refs:
        m = re.match(r"\s*(\d{1,7})(?:\s|$|·)", ref)
        if m:
            numbers.append(int(m.group(1)))
    return {"number": str(max(numbers) + 1) if numbers else None}


@router.get("/{expense_id}", response_model=ExpenseResponse)
def get_expense(expense_id: int, db: Session = Depends(get_db)):
    txn = (
        db.query(Transaction)
        .filter(Transaction.id == expense_id, Transaction.source_type == SOURCE_TYPE)
        .first()
    )
    if txn is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    return _serialize(txn, db)


@router.post("/{expense_id}/void", response_model=ExpenseResponse)
def void_expense(expense_id: int, db: Session = Depends(get_db)):
    """Reverse a recorded expense — same convention as bills and manual
    entries: the original stays in the ledger, a mirror-image entry
    cancels it, and the expense shows as void. Booked it to the wrong
    account? Void it and enter it again."""
    txn = (
        db.query(Transaction)
        .filter(Transaction.id == expense_id, Transaction.source_type == SOURCE_TYPE)
        .first()
    )
    if txn is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    if txn.id in _void_ids(db, [txn.id]):
        raise HTTPException(status_code=400, detail="Expense is already void")

    assert_not_reconciled(txn)
    check_closing_date(db, txn.date)

    create_journal_entry(
        db,
        txn.date,
        f"VOID {txn.description or 'Expense'}",
        reversing_lines(txn.lines),
        source_type=VOID_SOURCE_TYPE,
        source_id=txn.id,
        reference=txn.reference or "",
        class_id=txn.class_id,
        job_id=txn.job_id,
    )
    release_statement_links(db, txn)
    db.commit()
    db.refresh(txn)
    return _serialize(txn, db, True)


@router.post("", response_model=ExpenseResponse, status_code=201)
def create_expense(data: ExpenseCreate, db: Session = Depends(get_db)):
    check_closing_date(db, data.date)

    paid_from = (
        db.query(Account).filter(Account.id == data.paid_from_account_id).first()
    )
    if paid_from is None:
        raise HTTPException(status_code=404, detail="Paid-from account not found")
    if paid_from.account_type not in PAID_FROM_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Paid-from must be a bank, cash, or credit card account",
        )

    vendor = None
    if data.vendor_id is not None:
        vendor = db.query(Vendor).filter(Vendor.id == data.vendor_id).first()
        if vendor is None:
            raise HTTPException(status_code=404, detail="Vendor not found")

    payee = (data.payee or "").strip() or (vendor.name if vendor else "")
    memo = (data.memo or "").strip()

    # One account and an amount, or a split across several: the same thing
    # underneath, a list of (account, amount) lines.
    if data.lines:
        if data.expense_account_id is not None or data.amount is not None:
            raise HTTPException(
                status_code=400,
                detail="Give either the split lines or one account and an amount, not both",
            )
        split = data.lines
    else:
        if data.expense_account_id is None or data.amount is None:
            raise HTTPException(
                status_code=400, detail="Choose an expense account and an amount"
            )
        split = [
            ExpenseLineIn(
                account_id=data.expense_account_id,
                amount=data.amount,
                memo=memo or None,
                class_id=data.class_id,
                job_id=data.job_id,
                tax_code=data.tax_code,
            )
        ]

    accounts = {
        a.id: a
        for a in db.query(Account)
        .filter(Account.id.in_({ln.account_id for ln in split}))
        .all()
    }
    for ln in split:
        if ln.account_id not in accounts:
            raise HTTPException(status_code=404, detail="Expense account not found")
        if ln.account_id == paid_from.id:
            raise HTTPException(
                status_code=400, detail="Expense and paid-from accounts must differ"
            )
        if Decimal(str(ln.amount)).quantize(Decimal("0.01")) == 0:
            raise HTTPException(status_code=400, detail="A split line has no amount")
    # GST/HST on the taxable lines: backed out of a tax-included amount, or
    # added to it, and claimed on one line to the GST/HST account.
    values = [Decimal(str(ln.amount)) for ln in split]
    tax_total = Decimal("0")
    if any(ln.tax_code == "H" for ln in split):
        from app.services import hst

        itc_account = hst.account_id(db)
        if itc_account is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "A line is marked for GST/HST, but this company does not "
                    "charge it. Turn on GST/HST in Settings, or leave the tax "
                    "code off."
                ),
            )
        tax_rate = hst.rate(db)
        for i, ln in enumerate(split):
            if ln.tax_code != "H" or ln.account_id == itc_account:
                continue
            if data.amounts_include_tax:
                values[i], tax = hst.split_inclusive(values[i], tax_rate)
            else:
                tax = (values[i] * tax_rate).quantize(Decimal("0.01"))
            tax_total += tax
    amount = sum(values, Decimal("0")) + tax_total
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    journal_lines = []
    for i, ln in enumerate(split):
        value = values[i]
        entry = {
            "account_id": ln.account_id,
            "debit": value if value > 0 else Decimal("0"),
            "credit": -value if value < 0 else Decimal("0"),
            "description": (ln.memo or "").strip() or memo or payee,
            "class_id": ln.class_id if ln.class_id is not None else data.class_id,
            "job_id": ln.job_id if ln.job_id is not None else data.job_id,
        }
        if i == 0 and not data.lines:
            # the one-account form's extras belong to its one line
            entry.update(cost_code_id=data.cost_code_id, is_billable=data.is_billable)
            if "function" in data.model_fields_set:
                entry["function"] = data.function
        journal_lines.append(entry)
    if tax_total:
        journal_lines.append(
            {
                "account_id": itc_account,
                "debit": tax_total if tax_total > 0 else Decimal("0"),
                "credit": -tax_total if tax_total < 0 else Decimal("0"),
                "description": "GST/HST",
            }
        )
    journal_lines.append(
        {
            "account_id": paid_from.id,
            "debit": Decimal("0"),
            "credit": amount,
            "description": memo or payee,
        }
    )

    txn = create_journal_entry(
        db,
        data.date,
        f"Expense: {payee}" if payee else "Expense",
        journal_lines,
        source_type=SOURCE_TYPE,
        # The vendor is the only linked record an expense has; keep the
        # id where every other posting keeps its origin.
        source_id=vendor.id if vendor else None,
        reference=data.reference or "",
        class_id=data.class_id,
        job_id=data.job_id,
    )
    db.commit()
    db.refresh(txn)
    return _serialize(txn, db)
