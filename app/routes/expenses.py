# ============================================================================
# Expenses — record a receipt that's already been paid (card, cash, check)
# DR Expense Account, CR the bank / credit-card account it was paid from.
# One step, no bill to pay later; the Scan Receipt flow lands here.
# ============================================================================

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.accounts import Account
from app.models.contacts import Vendor
from app.models.transactions import Transaction, TransactionLine
from app.schemas.expenses import ExpenseCreate, ExpenseLineOut, ExpenseResponse
from app.services.accounting import create_journal_entry, reversing_lines
from app.services.job_costing import line_cost_type
from app.services.bank_posting import assert_not_reconciled, release_statement_links
from app.services.check_numbers import refuse_duplicate
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


def _memo_of(txn: Transaction, credit_line) -> str:
    """The memo typed on the expense: its own column (#648), "" when none
    was typed. An expense saved before the column existed has none stored:
    its bank line holds the memo or, with none typed, the payee the entry's
    description carries ("Expense: {payee}", the vendor's name only when no
    payee was typed), which is not a memo."""
    if txn.memo is not None:
        return txn.memo
    line_desc = (credit_line.description or "") if credit_line else ""
    on_entry = (txn.description or "").removeprefix("Expense: ").strip()
    return "" if line_desc == on_entry else line_desc


def paid_from_line(txn: Transaction):
    """The line money left by: the credit on a bank or card account (the
    first, if another line credits something too), else the largest credit.
    A simple expense has exactly one credit, so this is that line."""
    credits = [ln for ln in txn.lines if (ln.credit or 0) > 0]
    if not credits:
        return None
    banked = [ln for ln in credits if ln.account is not None and ln.account.bank_kind]
    if banked:
        return min(banked, key=lambda ln: ln.id or 0)
    # a card credit (a refund, John's build): the card's line is the debit
    refunds = [
        ln
        for ln in txn.lines
        if (ln.debit or 0) > 0 and ln.account is not None and ln.account.bank_kind
    ]
    if refunds:
        return min(refunds, key=lambda ln: ln.id or 0)
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
    # the expense's lines: every line but the one it was paid from, in the
    # order posted (a GST/HST input tax credit is one of them; a cheque
    # brought over from QuickBooks may carry a credit line too)
    split = sorted(
        (ln for ln in txn.lines if ln is not credit_line), key=lambda x: x.id or 0
    )
    # a card credit (refund) carries its lines the other way round; they
    # read as the charge's would, its amount positive
    is_credit = credit_line is not None and (credit_line.debit or 0) > 0
    sign = Decimal("-1") if is_credit else Decimal("1")
    debit_line = split[0] if split else None
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
    # the first line's account, as 2.31 gives it; the lists say "Split (N
    # accounts)" from `lines`
    account_name = debit_line.account.name if debit_line and debit_line.account else ""
    return ExpenseResponse(
        id=txn.id,
        date=txn.date,
        payee=payee,
        vendor_id=vendor.id if vendor else None,
        expense_account_id=debit_line.account_id if debit_line else None,
        lines=[
            ExpenseLineOut(
                account_id=ln.account_id,
                account_name=ln.account.name if ln.account else "",
                account_number=(
                    (ln.account.account_number or "") if ln.account else ""
                ),
                amount=float(
                    sign * (Decimal(str(ln.debit or 0)) - Decimal(str(ln.credit or 0)))
                ),
                description=ln.description or "",
                class_id=ln.class_id,
                job_id=ln.job_id,
                cost_code_id=ln.cost_code_id,
                cost_type=ln.cost_type,
                function=ln.function,
                is_billable=bool(ln.is_billable),
                line_order=i,
            )
            for i, ln in enumerate(split)
        ],
        expense_account_name=account_name,
        paid_from_account_name=(
            credit_line.account.name if credit_line and credit_line.account else ""
        ),
        paid_from_kind=(
            (credit_line.account.bank_kind or "")
            if credit_line and credit_line.account
            else ""
        ),
        amount=(
            float(credit_line.debit if is_credit else credit_line.credit)
            if credit_line
            else 0.0
        ),
        is_credit=is_credit,
        reference=txn.reference or "",
        # the memo typed on the expense, kept on its own (#648); a split's
        # debit lines carry their own (#599)
        memo=_memo_of(txn, credit_line),
        payee_address=txn.payee_address,
        status="void" if voided else "recorded",
        printable=(
            not voided
            and credit_line is not None
            and credit_line.account is not None
            and credit_line.account.bank_kind == "bank"
        ),
        replaces_id=txn.replaces_id,
        replaced_by_id=txn.replaced_by_id,
        paid_from_account_id=credit_line.account_id if credit_line else None,
        class_id=txn.class_id,
        job_id=txn.job_id,
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
    """Everyone an expense was ever paid to that has no vendor record: the
    other names written on cheques (employees, the Receiver General,
    QuickBooks' Other Names). QuickBooks offers them all in the Pay to the
    Order of box."""
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
    """The last expense paid to this vendor or payee (its accounts, amounts
    and memos) for the form to start from, as QuickBooks' QuickFill does.
    null when there is none."""
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
                {
                    **ln.model_dump(),
                    "description": (
                        "" if ln.description == out.payee else ln.description
                    ),
                }
                for ln in out.lines
            ],
        }
    return None


@router.get("/next-number")
def next_cheque_number(account_id: int, db: Session = Depends(get_db)):
    """The next cheque number for a bank account: one more than the highest
    number among its recent cheques (expenses and bill payments alike). A
    credit card has none."""
    acct = db.get(Account, account_id)
    if acct is None or acct.bank_kind != "bank":
        return {"number": None}
    refs = (
        db.query(Transaction.reference)
        .join(TransactionLine, TransactionLine.transaction_id == Transaction.id)
        .filter(TransactionLine.account_id == account_id, TransactionLine.credit > 0)
        .filter(Transaction.reference.isnot(None), Transaction.reference != "")
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        # far enough back to reach the last numbered cheque among the
        # e-transfers and card payments that carry none
        .limit(1000)
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


def _line_specs(data: ExpenseCreate) -> list[dict]:
    """The expense's lines as plain dicts, checked: the older single
    expense_account_id + amount is one line; `lines` must add up to the
    amount paid, and no line may be zero or negative."""
    if data.lines is not None and data.expense_account_id is not None:
        raise HTTPException(
            status_code=422,
            detail="Send either lines or expense_account_id, not both",
        )
    if data.lines is None:
        if data.expense_account_id is None:
            raise HTTPException(
                status_code=422, detail="An expense needs an account or lines"
            )
        if data.amount is None or Decimal(str(data.amount)) <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        # the header-level fields are the one line's own
        return [
            {
                "account_id": data.expense_account_id,
                "amount": Decimal(str(data.amount)),
                "description": None,
                "class_id": None,
                "job_id": None,
                "cost_code_id": data.cost_code_id,
                "cost_type": data.cost_type,
                "is_billable": data.is_billable,
                "function": data.function,
                "set_function": "function" in data.model_fields_set,
                "tax_code": data.tax_code,
                "tax_amount": None,
            }
        ]
    if not data.lines:
        raise HTTPException(
            status_code=422, detail="An expense needs at least one line"
        )
    specs = []
    for n, ln in enumerate(data.lines, 1):
        part = Decimal(str(ln.amount)).quantize(Decimal("0.01"), ROUND_HALF_UP)
        if part == 0:
            raise HTTPException(
                status_code=422,
                detail=f"Line {n} is 0.00 and posts nothing; enter its share or remove the line",
            )
        if part < 0:
            raise HTTPException(
                status_code=422, detail=f"Line {n}: the amount must be positive"
            )
        specs.append(
            {
                "account_id": ln.account_id,
                "amount": part,
                "description": (ln.description or "").strip() or None,
                "class_id": ln.class_id,
                "job_id": ln.job_id,
                "cost_code_id": ln.cost_code_id,
                "cost_type": ln.cost_type,
                "is_billable": ln.is_billable,
                "function": ln.function,
                "set_function": "function" in ln.model_fields_set,
                "tax_code": ln.tax_code,
                "tax_amount": ln.tax_amount,
            }
        )
    total = sum((sp["amount"] for sp in specs), Decimal("0"))
    # GST/HST added on top of the lines is checked against the amount paid
    # once it is figured (create_expense)
    taxed_on_top = not data.amounts_include_tax and any(
        sp["tax_code"] == "H" for sp in specs
    )
    if (
        not taxed_on_top
        and data.amount is not None
        and Decimal(str(data.amount)) != total
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"The lines add up to ${total:,.2f} but the amount paid is "
                f"${Decimal(str(data.amount)):,.2f}; they must match"
            ),
        )
    return specs


def _gst_hst(db: Session, data: ExpenseCreate, specs: list[dict]):
    """A Canadian registrant's GST/HST on the lines marked H: backed out of
    an amount that includes it (a receipt's total) or added to it, and
    claimed on one line to the GST/HST account as an input tax credit. The
    specs' amounts become the net. (account, tax) — (None, 0) with no tax."""
    if not any(sp["tax_code"] == "H" for sp in specs):
        return None, Decimal("0")
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
    tax_total = Decimal("0")
    for sp in specs:
        if sp["tax_code"] != "H" or sp["account_id"] == itc_account:
            continue
        if data.amounts_include_tax:
            sp["amount"], tax = hst.split_inclusive(sp["amount"], tax_rate)
        elif sp.get("tax_amount") is not None:
            # the tax the form showed beside the net, as QuickBooks lets it
            # be adjusted
            tax = Decimal(str(sp["tax_amount"])).quantize(Decimal("0.01"))
        else:
            tax = (sp["amount"] * tax_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
        tax_total += tax
    return itc_account, tax_total


@router.post("", response_model=ExpenseResponse, status_code=201)
def create_expense(
    data: ExpenseCreate,
    db: Session = Depends(get_db),
    allow_duplicate_check_number: bool = Query(False),
):
    txn = post_expense(db, data, allow_duplicate_check_number)
    db.commit()
    db.refresh(txn)
    return _serialize(txn, db)


@router.put("/{expense_id}", response_model=ExpenseResponse)
def update_expense(
    expense_id: int,
    data: ExpenseCreate,
    db: Session = Depends(get_db),
    allow_duplicate_check_number: bool = Query(False),
):
    """Edit a saved cheque or card charge in place, as QuickBooks opens one
    from the register (John's build): the same transaction keeps its id,
    attachments and audit trail, and its lines are rewritten the way a
    register entry's are (replace_journal_lines). A void one is not edited;
    one a completed reconciliation holds keeps its amount, date and
    account."""
    txn = (
        db.query(Transaction)
        .filter(Transaction.id == expense_id, Transaction.source_type == SOURCE_TYPE)
        .first()
    )
    if txn is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    if txn.id in _void_ids(db, [txn.id]):
        raise HTTPException(
            status_code=400,
            detail="This cheque is void; a void cheque is not edited. Enter it again.",
        )
    post_expense(db, data, allow_duplicate_check_number, existing=txn)
    db.commit()
    db.refresh(txn)
    return _serialize(txn, db)


def post_expense(
    db: Session,
    data: ExpenseCreate,
    allow_duplicate_check_number: bool = False,
    existing: Transaction | None = None,
) -> Transaction:
    """Check and post an expense, without committing: the route commits,
    and a memorized cheque entered by the schedule posts through here in
    the schedule's own transaction. With `existing`, the saved expense is
    rewritten in place instead (update_expense)."""
    check_closing_date(db, data.date)
    if existing is not None:
        check_closing_date(db, existing.date)

    specs = _line_specs(data)
    itc_account, tax_total = _gst_hst(db, data, specs)
    amount = sum((sp["amount"] for sp in specs), Decimal("0")) + tax_total
    if data.lines is not None and data.amount is not None and tax_total:
        if Decimal(str(data.amount)) != amount:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"The lines and their GST/HST add up to ${amount:,.2f} but "
                    f"the amount paid is ${Decimal(str(data.amount)):,.2f}; "
                    "they must match"
                ),
            )
    expense_accounts = {}
    for sp in specs:
        acct = db.query(Account).filter(Account.id == sp["account_id"]).first()
        if acct is None:
            raise HTTPException(status_code=404, detail="Expense account not found")
        expense_accounts[acct.id] = acct

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
    if paid_from.id in expense_accounts:
        raise HTTPException(
            status_code=400, detail="Expense and paid-from accounts must differ"
        )

    # a check whose number the bank account already has (#481): the 409
    # the person answers, keep the number or edit it
    old_paid = paid_from_line(existing) if existing is not None else None
    if (
        existing is None
        or (data.reference or "").strip() != (existing.reference or "").strip()
        or (old_paid is not None and old_paid.account_id != paid_from.id)
    ):
        refuse_duplicate(
            db,
            paid_from.id,
            data.reference,
            allow=allow_duplicate_check_number,
            exclude_txn_id=existing.id if existing is not None else None,
        )

    vendor = None
    if data.vendor_id is not None:
        vendor = db.query(Vendor).filter(Vendor.id == data.vendor_id).first()
        if vendor is None:
            raise HTTPException(status_code=404, detail="Vendor not found")

    payee = (data.payee or "").strip() or (vendor.name if vendor else "")
    memo = (data.memo or "").strip()
    # the bank line shows in the register: the memo, else the payee
    line_desc = memo or payee
    journal_lines = []
    for sp in specs:
        line = {
            "account_id": sp["account_id"],
            "debit": sp["amount"],
            "credit": Decimal("0"),
            "description": sp["description"] or line_desc,
            "cost_code_id": sp["cost_code_id"],
            "cost_type": line_cost_type(db, sp["cost_code_id"], sp["cost_type"]),
            "is_billable": sp["is_billable"],
        }
        # a line's own class and job; left out, the expense's (the ledger
        # fills them in)
        for key in ("class_id", "job_id"):
            if sp[key] is not None:
                line[key] = sp[key]
        if sp["set_function"]:
            line["function"] = sp["function"]
        journal_lines.append(line)
    if tax_total:
        journal_lines.append(
            {
                "account_id": itc_account,
                "debit": tax_total,
                "credit": Decimal("0"),
                "description": "GST/HST",
            }
        )
    journal_lines.append(
        {
            "account_id": paid_from.id,
            "debit": Decimal("0"),
            "credit": amount,
            "description": line_desc,
        }
    )
    if data.is_credit:
        # a credit to the card (a refund, as QuickBooks' Enter Credit Card
        # Charges takes one): every line the other way round, the GST/HST
        # claimed on it given back
        for line in journal_lines:
            line["debit"], line["credit"] = line["credit"], line["debit"]

    if existing is not None:
        from app.services.bank_posting import reconciled_on, replace_journal_lines

        recon = reconciled_on(db, existing)
        if recon is not None and (
            data.date != existing.date
            or old_paid is None
            or old_paid.account_id != paid_from.id
            or Decimal(str(old_paid.credit or old_paid.debit or 0)).quantize(
                Decimal("0.01")
            )
            != amount.quantize(Decimal("0.01"))
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"This cheque was reconciled on the {recon.statement_date} "
                    "statement, so its amount, date and account stay as they "
                    "are. Its payee, memo and accounts can still be corrected."
                ),
            )
        replace_journal_lines(
            db,
            existing,
            data.date,
            f"Expense: {payee}" if payee else "Expense",
            journal_lines,
            source_type=SOURCE_TYPE,
            reference=data.reference or "",
            class_id=data.class_id,
            job_id=data.job_id,
        )
        existing.source_id = vendor.id if vendor else None
        existing.memo = memo
        if data.payee_address is not None:
            existing.payee_address = _address_text(data.payee_address)
        db.flush()
        return existing

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
    # the memo on its own (#648): "" when none was typed, which tells it
    # from an expense saved before the column existed
    txn.memo = memo
    txn.payee_address = _address_text(data.payee_address)
    db.flush()
    return txn


def _address_text(text) -> str | None:
    """The Address box's lines, trimmed, blank ones dropped; None if empty."""
    lines = [ln.strip() for ln in str(text or "").splitlines()]
    return "\n".join(ln for ln in lines if ln) or None


@router.post("/{expense_id}/replace", response_model=ExpenseResponse)
def replace_expense(
    expense_id: int,
    data: ExpenseCreate,
    db: Session = Depends(get_db),
    allow_duplicate_check_number: bool = Query(False),
):
    """Change a recorded expense (#689): void it and post `data` in its
    place, the two linked. The void's refusals stand (a reconciled line, a
    closed period), in its words."""
    from app.services.replace_transaction import replace

    return replace(db, "expense", expense_id, data, allow_duplicate_check_number)
