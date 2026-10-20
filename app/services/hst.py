# ============================================================================
# Canadian GST/HST — a company that charges GST/HST, claims input tax credits
# on what it buys, and files a return monthly, quarterly or yearly.
#
# A US company's sales tax is a debt to the state and the tax it pays a
# supplier is part of the cost (services/purchase_posting.py). A Canadian
# registrant's is one account both ways, as QuickBooks Canada keeps it:
# GST/HST Payable is credited with the tax on every sale and debited with the
# tax on every purchase (the input tax credit), and the return is the
# difference for the period. Turned on per company in Settings
# (sales_tax_system = "canada"), with the account and the filing frequency;
# a company not registered keeps "not registered" and charges none.
#
# The return is read from the ledger, so it covers everything that ever
# posted to the account — invoices, bills, cheques, card charges and the
# full QuickBooks history alike. Each transaction that touches the account
# is one of three things:
#   - a sale (it has an income line): its tax is collected tax, line 103;
#   - a purchase (an expense, cost-of-goods or asset line): an input tax
#     credit, line 106;
#   - a payment, refund or filing (nothing but bank, receivable or payable
#     lines beside the tax): not on the return; listed as paid.
# ============================================================================

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.accounts import Account, AccountType
from app.models.transactions import Transaction, TransactionLine

FREQUENCIES = ("none", "monthly", "quarterly", "annual")
_MONTHS = {"monthly": 1, "quarterly": 3, "annual": 12}

ZERO = Decimal("0.00")


def _setting(db: Session, key: str, default: str = "") -> str:
    from app.services.settings_service import get_setting_raw

    value = get_setting_raw(db, key)
    return default if value in (None, "") else str(value)


def is_canadian(db: Session) -> bool:
    return _setting(db, "sales_tax_system", "us") == "canada"


def account_id(db: Session) -> int | None:
    """The GST/HST account when the company is a Canadian registrant."""
    if not is_canadian(db):
        return None
    raw = _setting(db, "hst_account_id")
    if raw.isdigit() and db.get(Account, int(raw)) is not None:
        return int(raw)
    return None


def rate(db: Session) -> Decimal:
    """The GST/HST rate as a fraction (13% → 0.13)."""
    try:
        return Decimal(_setting(db, "hst_rate", "13")) / 100
    except Exception:
        return Decimal("0.13")


def frequency(db: Session) -> str:
    value = _setting(db, "hst_filing_frequency", "quarterly")
    return value if value in FREQUENCIES else "quarterly"


def year_end_month(db: Session) -> int:
    raw = _setting(db, "hst_year_end_month", "12")
    return int(raw) if raw.isdigit() and 1 <= int(raw) <= 12 else 12


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, 1)


def periods(freq: str, year_end: int, first: date, last: date) -> list[tuple[date, date]]:
    """The filing periods from the one holding `first` to the one holding
    `last`, oldest first. Periods line up with the fiscal year: a quarterly
    filer with a March year end files April–June, July–September, …"""
    step = _MONTHS.get(freq)
    if not step:
        return []
    # the first month of a fiscal year
    anchor = date(first.year - 1, year_end % 12 + 1, 1)
    start = anchor
    while _add_months(start, step) <= date(first.year, first.month, 1):
        start = _add_months(start, step)
    out = []
    while start <= last:
        nxt = _add_months(start, step)
        out.append((start, nxt - timedelta(days=1)))
        start = nxt
    return out


def current_periods(db: Session, today: date | None = None, count: int = 8):
    """The latest `count` filing periods up to the one holding today, newest
    first, and the one to file now (the last that has ended)."""
    today = today or date.today()
    freq = frequency(db)
    if freq == "none":
        return [], None
    step = _MONTHS[freq]
    back = date(today.year - (step * count) // 12 - 1, 1, 1)
    ps = periods(freq, year_end_month(db), back, today)
    ps = list(reversed(ps))[:count]
    due = next((p for p in ps if p[1] < today), None)
    return ps, due


def _side(lines, tax_account: int, kinds: dict[int, tuple]) -> str:
    """sale / purchase / payment for a transaction's lines."""
    sale = purchase = False
    for ln in lines:
        if ln.account_id == tax_account:
            continue
        acct_type, bank_kind, number = kinds[ln.account_id]
        if acct_type == AccountType.INCOME:
            sale = True
        elif acct_type in (AccountType.EXPENSE, AccountType.COGS):
            purchase = True
        elif acct_type == AccountType.ASSET and not bank_kind and number not in ("1100", "1200"):
            purchase = True
    if sale:
        return "sale"
    if purchase:
        return "purchase"
    return "payment"


def gst_hst_return(db: Session, start: date, end: date) -> dict:
    """The GST/HST return for a period, from the ledger."""
    from app.services.settings_service import get_setting_raw

    tax_account = account_id(db)
    if tax_account is None:
        return {"enabled": False, "start_date": start.isoformat(), "end_date": end.isoformat()}
    acct = db.get(Account, tax_account)
    kinds = {
        a.id: (a.account_type, a.bank_kind, a.account_number)
        for a in db.query(Account).all()
    }
    txn_ids = [
        tid
        for (tid,) in db.query(TransactionLine.transaction_id)
        .join(Transaction, Transaction.id == TransactionLine.transaction_id)
        .filter(TransactionLine.account_id == tax_account)
        .filter(Transaction.date >= start, Transaction.date <= end)
        .distinct()
    ]
    collected = itc = paid = ZERO
    sales = ZERO
    detail = []
    for i in range(0, len(txn_ids), 500):
        chunk = txn_ids[i : i + 500]
        txns = db.query(Transaction).filter(Transaction.id.in_(chunk)).all()
        for t in txns:
            side = _side(t.lines, tax_account, kinds)
            tax = sum(
                (Decimal(l.credit or 0) - Decimal(l.debit or 0) for l in t.lines if l.account_id == tax_account),
                ZERO,
            )
            if side == "sale":
                collected += tax
                sales += sum(
                    (
                        Decimal(l.credit or 0) - Decimal(l.debit or 0)
                        for l in t.lines
                        if kinds[l.account_id][0] == AccountType.INCOME
                    ),
                    ZERO,
                )
            elif side == "purchase":
                itc += -tax
            else:
                paid += -tax
            detail.append(
                {
                    "transaction_id": t.id,
                    "date": t.date.isoformat(),
                    "reference": t.reference or "",
                    "description": t.description or "",
                    "source_type": t.source_type,
                    "side": side,
                    "tax": float(tax if side == "sale" else -tax),
                }
            )
    detail.sort(key=lambda d: (d["date"], d["transaction_id"]))
    # Line 101 is all sales and other revenue, taxable or not: the income
    # accounts for the period.
    revenue = ZERO
    for (credit, debit) in (
        db.query(TransactionLine.credit, TransactionLine.debit)
        .join(Transaction, Transaction.id == TransactionLine.transaction_id)
        .join(Account, Account.id == TransactionLine.account_id)
        .filter(Account.account_type == AccountType.INCOME)
        .filter(Transaction.date >= start, Transaction.date <= end)
    ):
        revenue += Decimal(credit or 0) - Decimal(debit or 0)
    net = collected - itc
    return {
        "enabled": True,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "account_id": tax_account,
        "account_name": acct.name if acct else "",
        "registration_number": get_setting_raw(db, "hst_registration_number") or "",
        "line_101": float(revenue),
        "taxable_sales": float(sales),
        "line_103": float(collected),
        "line_105": float(collected),
        "line_106": float(itc),
        "line_108": float(itc),
        "line_109": float(net),
        "payments_in_period": float(paid),
        "transactions": detail,
        "counts": {
            "sale": sum(1 for d in detail if d["side"] == "sale"),
            "purchase": sum(1 for d in detail if d["side"] == "purchase"),
            "payment": sum(1 for d in detail if d["side"] == "payment"),
        },
    }


def split_inclusive(amount: Decimal, tax_rate: Decimal) -> tuple[Decimal, Decimal]:
    """(net, tax) of an amount that includes tax at `tax_rate`."""
    amount = Decimal(str(amount))
    tax = (amount * tax_rate / (1 + tax_rate)).quantize(Decimal("0.01"))
    return amount - tax, tax
