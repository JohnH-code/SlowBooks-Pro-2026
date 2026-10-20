# ============================================================================
# QuickBooks Desktop — full history, from QuickBooks' own exports.
#
# QuickBooks Desktop cannot export its transactions to IIF, but its Journal
# report (Reports → Accountant & Taxes → Journal, dates All, saved as CSV)
# lists every transaction it holds — cheques, deposits, bills, bill
# payments, invoices, payments, transfers, credit card charges and general
# journal entries alike — as balanced debit and credit lines. This source
# rebuilds the books from that report:
#
#   lists.iif         File → Utilities → Export → Lists to IIF Files: the
#                     chart (types, numbers, sub-accounts, hidden flags),
#                     customers, vendors, items and classes. Account
#                     balances in it (OBAMOUNT) are NOT used: the Journal
#                     carries every posting from the first day, and the
#                     balances again would count everything twice.
#   journal.csv       the Journal report, dates All. Cheques and credit
#                     card charges become Expenses (with every split line),
#                     deposits Deposits (their lines "other deposits"), the
#                     invoices, payments, bills and bill payments those
#                     documents (services/qbd_documents.py), the rest
#                     journal entries; each referenced "QB #<Trans #>", so a
#                     second upload posts nothing twice. With the columns
#                     Terms, Due Date, Item, Class, Sales Tax Code, Clr, Open
#                     Balance, Qty and Sales Price the documents are whole,
#                     and Clr carries each bank account's reconciliation.
#   balance sheet     Balance Sheet Standard, dates All, columns by Year, CSV
#   profit and loss   Profit & Loss Standard, dates All, columns by Year, CSV
#
# The two reports are the check: before anything is written, every balance
# sheet account is rebuilt at every year end and every income and expense
# account for every year, and each figure must equal QuickBooks' to the
# cent. Retained Earnings is checked the way QuickBooks shows it: what was
# posted to it plus every earlier year's net income.
#
# Attachments: QuickBooks keeps the documents attached to transactions in
# Attach/<company>/Txn/<TxnID>-<created>/, a folder per transaction named by
# an ID no report shows. Upload that folder as a zip together with an
# attachment map (a CSV of Trans # and folder name, made once by matching
# the folders to the transactions) and each document is attached to its
# transaction's journal entry. A folder the map does not name is reported,
# not guessed.
# ============================================================================

import csv
import io
import mimetypes
import posixpath
import re
import zipfile
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.accounts import Account, AccountType
from app.models.attachments import Attachment
from app.models.transactions import Transaction, TransactionLine
from app.services.accounting import _q, create_journal_entry
from app.services.iif_common import IIF_TO_ACCOUNT_TYPE
from app.services.migration_common import parse_amount

LABEL = "QuickBooks Desktop"
SOURCE_TYPE = "qbd_import"
REF_PREFIX = "QB #"

# QuickBooks account types (the IIF's ACCNTTYPE) → what the books need.
_TYPES = dict(IIF_TO_ACCOUNT_TYPE)
_TYPES["CCARD"] = AccountType.LIABILITY
_TYPES["COGS"] = AccountType.COGS
_BANK_KIND = {"BANK": "bank", "CCARD": "credit_card"}
# Balance sheet types carry a debit (assets) or credit (the rest) balance.
_DEBIT_NATURE = {"BANK", "AR", "OCASSET", "FIXASSET", "OASSET", "NONPOSTING"}
_PL_TYPES = {"INC", "EXINC", "EXP", "EXEXP", "COGS"}
_INCOME_TYPES = {"INC", "EXINC"}

_ATTACH_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


# ── files ──────────────────────────────────────────────────────────────────


def classify_filename(name: str) -> str | None:
    low = (name or "").lower()
    if low.endswith(".iif"):
        return "lists"
    if "map" in low:
        return "attach_map"
    if "journal" in low:
        return "gl"
    if "balance" in low:
        return "bs"
    if "profit" in low or "loss" in low or "p&l" in low:
        return "pl"
    if "trial" in low:
        return "skip"  # the Balance Sheet and P&L by year check more than it can
    if low.endswith(".pdf") or "/txn/" in low:
        return "skip"
    return None


def keep_binary(name: str, data: bytes) -> str | None:
    """A zip of QuickBooks' Attach folder is kept whole (its folder names are
    the transaction IDs); the route hands it over as bytes."""
    if not (name or "").lower().endswith(".zip"):
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if any("/txn/" in ("/" + n).lower() for n in z.namelist()):
                return "attachments"
    except zipfile.BadZipFile:
        return None
    return None


def _rows(text: str) -> list[list[str]]:
    text = text.lstrip("﻿")
    return [list(r) for r in csv.reader(io.StringIO(text))]


# ── the chart ──────────────────────────────────────────────────────────────


def _unquote(s: str) -> str:
    s = (s or "").strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1].replace('""', '"')
    return s.strip()


def _iif_sections(text: str) -> dict[str, list[dict]]:
    headers: dict[str, list[str]] = {}
    out: dict[str, list[dict]] = defaultdict(list)
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not line.strip():
            continue
        cells = line.split("\t")
        kind = cells[0].strip()
        if kind.startswith("!"):
            headers[kind[1:]] = [c.strip() for c in cells]
            continue
        hdr = headers.get(kind)
        if not hdr:
            continue
        # QuickBooks quotes any field holding a comma ("Locks, Keys and
        # Re-keys"); the quotes are not part of the name.
        out[kind].append(
            {
                h: (_unquote(cells[i]) if i < len(cells) else "")
                for i, h in enumerate(hdr)
                if h
            }
        )
    return out


def parse_chart(lists_text: str) -> tuple[list[dict], list[str]]:
    """The chart from the IIF's ACCNT rows: one spec per QuickBooks account,
    {qb_name, name, parent_qb, number, qb_type, type, bank_kind, hidden,
    description}. ``name`` is the account's own name (the last part of
    QuickBooks' Parent:Child); a name two parents share gets its parent in
    brackets so each stays its own account."""
    errors: list[str] = []
    specs: list[dict] = []
    for row in _iif_sections(lists_text).get("ACCNT", []):
        qb_name = _unquote(row.get("NAME", ""))
        if not qb_name:
            continue
        qb_type = (row.get("ACCNTTYPE") or "").strip().upper()
        if qb_type not in _TYPES:
            errors.append(
                f"Account {qb_name!r} has a type this import does not know: {qb_type!r}"
            )
            continue
        parts = [p.strip() for p in qb_name.split(":")]
        specs.append(
            {
                "qb_name": qb_name,
                "leaf": parts[-1],
                "parent_qb": ":".join(parts[:-1]) or None,
                "number": (row.get("ACCNUM") or "").strip() or None,
                "qb_type": qb_type,
                "type": _TYPES[qb_type],
                "bank_kind": _BANK_KIND.get(qb_type),
                "hidden": (row.get("HIDDEN") or "").strip().upper() == "Y",
                "description": _unquote(row.get("DESC", "")) or None,
            }
        )
    leaf_count: dict[str, int] = defaultdict(int)
    for s in specs:
        leaf_count[s["leaf"].lower()] += 1
    for s in specs:
        if leaf_count[s["leaf"].lower()] > 1 and s["parent_qb"]:
            s["name"] = f"{s['leaf']} ({s['parent_qb'].split(':')[-1]})"
        else:
            s["name"] = s["leaf"]
    specs.sort(key=lambda s: s["qb_name"].count(":"))
    if not specs:
        errors.append(
            "The IIF file has no chart of accounts (export the Chart of Accounts list with it)"
        )
    return specs, errors


# ── the journal ────────────────────────────────────────────────────────────


def parse_journal(text: str) -> tuple[list[dict], list[str]]:
    """Every transaction in the Journal report:
    {trans, type, date, num, name, memo, lines:[{account, name, memo,
    debit, credit, cls, cleared}]}. A transaction starts at a row with a
    Trans #, and ends at its totals row (no account, the sums)."""
    rows = _rows(text)
    errors: list[str] = []
    header_at = None
    for i, row in enumerate(rows):
        cells = [c.strip().lower() for c in row]
        if "trans #" in cells and "account" in cells and "debit" in cells:
            header_at = i
            break
    if header_at is None:
        return [], [
            "Journal: no header row with Trans #, Account, Debit and Credit — export "
            "the Journal report (Reports → Accountant & Taxes → Journal) as CSV"
        ]
    hdr = [c.strip().lower() for c in rows[header_at]]

    def col(*names):
        for n in names:
            if n in hdr:
                return hdr.index(n)
        return None

    c = {
        "trans": col("trans #"),
        "type": col("type"),
        "date": col("date"),
        "num": col("num"),
        "name": col("name"),
        "memo": col("memo"),
        "account": col("account"),
        "class": col("class"),
        "clr": col("clr"),
        "debit": col("debit"),
        "credit": col("credit"),
        # optional columns that make documents of invoices and bills
        "terms": col("terms"),
        "due": col("due date"),
        "item": col("item"),
        "tax_code": col("sales tax code"),
        "open": col("open balance"),
        "qty": col("qty"),
        "price": col("sales price"),
    }
    if None in (c["trans"], c["date"], c["account"], c["debit"], c["credit"]):
        return [], [
            "Journal: the header row lacks Trans #, Date, Account, Debit or Credit"
        ]

    def cell(row, key):
        i = c[key]
        return row[i].strip() if i is not None and i < len(row) else ""

    txns: list[dict] = []
    current = None
    grand = None
    for n, row in enumerate(rows[header_at + 1 :], start=header_at + 2):
        trans = cell(row, "trans")
        if trans.upper() == "TOTAL":
            grand = (
                parse_amount(cell(row, "debit")),
                parse_amount(cell(row, "credit")),
            )
            break
        if trans:
            if current is not None:
                errors.append(
                    f"Journal row {n}: transaction {current['trans']} has no totals row"
                )
                txns.append(current)
            raw_date = cell(row, "date")
            parsed = None
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m/%d/%y"):
                try:
                    parsed = datetime.strptime(raw_date, fmt).date()
                    break
                except ValueError:
                    continue
            if parsed is None:
                errors.append(f"Journal row {n}: unreadable date {raw_date!r}")
                current = None
                continue
            current = {
                "trans": trans,
                "type": cell(row, "type"),
                "date": parsed,
                "num": cell(row, "num"),
                "name": cell(row, "name"),
                "memo": cell(row, "memo"),
                "lines": [],
            }
        if current is None:
            continue
        account = cell(row, "account")
        try:
            debit = parse_amount(cell(row, "debit"))
            credit = parse_amount(cell(row, "credit"))
        except Exception as exc:
            errors.append(f"Journal row {n}: {exc}")
            continue
        if not account:
            if not (cell(row, "debit") or cell(row, "credit")):
                continue  # a blank row
            sd = sum(ln["debit"] for ln in current["lines"])
            sc = sum(ln["credit"] for ln in current["lines"])
            if (debit, credit) != (sd, sc):
                errors.append(
                    f"Journal: transaction {current['trans']} totals {debit}/{credit} "
                    f"but its lines add to {sd}/{sc}"
                )
            txns.append(current)
            current = None
            continue
        current["lines"].append(
            {
                "account": account,
                "name": cell(row, "name"),
                "memo": cell(row, "memo"),
                "cls": cell(row, "class"),
                # QuickBooks' cleared mark: X (or ✔) reconciled, * cleared,
                # M matched to a downloaded bank transaction
                "clr": cell(row, "clr"),
                "cleared": cell(row, "clr") not in ("", "-"),
                "debit": debit,
                "credit": credit,
                "terms": cell(row, "terms"),
                "due": cell(row, "due"),
                "item": cell(row, "item"),
                "tax_code": cell(row, "tax_code"),
                "open": cell(row, "open"),
                "qty": cell(row, "qty"),
                "price": cell(row, "price"),
            }
        )
    if current is not None:
        txns.append(current)
    if grand is None:
        errors.append(
            "Journal: no TOTAL row at the end — was the whole report exported?"
        )
    else:
        td = sum(ln["debit"] for t in txns for ln in t["lines"])
        tc = sum(ln["credit"] for t in txns for ln in t["lines"])
        if (td, tc) != grand:
            errors.append(
                f"Journal: the report's TOTAL is {grand[0]}/{grand[1]} but its "
                f"transactions add to {td}/{tc} — rows are missing"
            )
    seen = set()
    for t in txns:
        if t["trans"] in seen:
            errors.append(f"Journal: Trans # {t['trans']} appears twice")
        seen.add(t["trans"])
        if _q(sum(ln["debit"] - ln["credit"] for ln in t["lines"])) != 0:
            errors.append(f"Journal: transaction {t['trans']} does not balance")
    return txns, errors


def resolve_accounts(txns: list[dict], specs: list[dict]) -> list[str]:
    """Name every journal line's account by its full QuickBooks name. With
    the preference "Show lowest subaccount only" on, the Journal says
    "407ETR" for Auto:407ETR; a short name two parents share can't be told
    apart, and is named for the person to turn the preference off."""
    errors = []
    full = {s["qb_name"] for s in specs}
    by_leaf: dict[str, list[str]] = defaultdict(list)
    for sp in specs:
        by_leaf[sp["leaf"]].append(sp["qb_name"])
    unknown, ambiguous = set(), set()
    for t in txns:
        for line in t["lines"]:
            name = line["account"]
            if name in full:
                continue
            leaf = name.split(":")[-1].strip()
            hits = by_leaf.get(leaf, [])
            if len(hits) == 1:
                line["account"] = hits[0]
            elif hits:
                ambiguous.add(name)
            else:
                unknown.add(name)
    for name in sorted(unknown):
        errors.append(
            f"The Journal posts to {name!r}, which the IIF chart does not list"
        )
    for name in sorted(ambiguous):
        errors.append(
            f"The Journal names the account {name!r}, which more than one parent "
            f"account has. In QuickBooks turn off Edit → Preferences → Accounting → "
            f'"Show lowest subaccount only" and export the Journal again'
        )
    return errors


def _reference(t: dict, kind: str = SOURCE_TYPE) -> str:
    """ "QB #2130" on a journal entry; a cheque or deposit leads with its own
    number, which is what its Reference box shows ("426 · QB #921")."""
    tag = f"{REF_PREFIX}{t['trans']}"
    if kind != SOURCE_TYPE and t.get("num"):
        return f"{t['num'][:60]} · {tag}"
    return tag


# Where each QuickBooks transaction lands. Cheques and credit card charges
# are paid expenses (split across as many accounts as QuickBooks had them);
# deposits are deposits, their lines "other deposits"; everything else —
# general journal entries, bill payments, transfers — a journal entry.
_EXPENSE_TYPES = {"cheque", "check", "credit card charge"}
_DEPOSIT_TYPES = {"deposit"}
_DOC_SOURCE = {
    "expense": "expense",
    "deposit": "deposit",
    "invoice": "invoice",
    "payment": "payment",
    "bill": "bill",
    "bill_payment": "bill_payment",
    SOURCE_TYPE: SOURCE_TYPE,
}
# What a document attaches to: an expense or deposit by its posting (their
# pages are keyed so), an invoice or bill by the document; a payment, a bill
# payment or a journal entry on its posting's journal view.
_ATTACH_ENTITY = {
    "expense": ("expense", "txn"),
    "deposit": ("deposit", "txn"),
    "invoice": ("invoice", "doc"),
    "bill": ("bill", "doc"),
}
_TAG = re.compile(re.escape(REF_PREFIX) + r"(\S+)$")


def _imported(db: Session) -> dict[str, tuple[int, str, int | None]]:
    """{Trans # → (transaction id, kind, document id)} already posted by this
    import."""
    out = {}
    for tid, ref, kind, doc in db.query(
        Transaction.id,
        Transaction.reference,
        Transaction.source_type,
        Transaction.source_id,
    ).filter(
        Transaction.source_type.in_(list(_DOC_SOURCE)),
        Transaction.reference.like(f"%{REF_PREFIX}%"),
    ):
        m = _TAG.search(ref or "")
        if m:
            out[m.group(1)] = (tid, kind, doc)
    return out


FINGERPRINT_KEY = "qbd_import_fingerprint"


def fingerprint(txns: list[dict]) -> str:
    """Which QuickBooks company a Journal comes from: its first transactions
    (number, date, type, first account, amount) — history a later export of
    the same company still starts with."""
    import hashlib

    first = sorted(
        txns, key=lambda t: (int(t["trans"]) if t["trans"].isdigit() else 0, t["trans"])
    )[:5]
    words = "|".join(
        f"{t['trans']},{t['date']},{t['type']},"
        + (
            f"{t['lines'][0]['account']},{t['lines'][0]['debit']},{t['lines'][0]['credit']}"
            if t["lines"]
            else ""
        )
        for t in first
    )
    return hashlib.sha1(words.encode("utf-8")).hexdigest()


def _other_company(db: Session, txns: list[dict], seen: dict) -> str | None:
    """A refusal when these books already hold a different QuickBooks
    company's import: transaction numbers start at 1 in every company file,
    so a second company's would read as "already imported" and be skipped."""
    from app.services.settings_service import get_setting_raw

    if not txns:
        return None
    message = (
        "These books already hold the import of a different QuickBooks company. "
        "Its transaction numbers would collide with this one's and most of this "
        "file would be skipped as already imported. Create a new company "
        "(Companies → New Company) and import into that."
    )
    stored = get_setting_raw(db, FINGERPRINT_KEY)
    if stored:
        return None if stored == fingerprint(txns) else message
    # Books imported before the fingerprint was kept: the same transaction
    # number on another date is another company's.
    by_trans = {t["trans"]: t for t in txns}
    clashes = 0
    checked = 0
    for trans, (tid, _kind, _doc) in list(seen.items())[:200]:
        t = by_trans.get(trans)
        if t is None:
            continue
        checked += 1
        when = db.query(Transaction.date).filter(Transaction.id == tid).scalar()
        if when != t["date"]:
            clashes += 1
    return message if checked and clashes > checked // 2 else None


def _set_up_hst(db: Session, specs, by_qb, txns) -> str | None:
    """A QuickBooks Canada company charges GST/HST: point Settings at its
    account and rate, unless GST/HST is already set up."""
    from app.services.settings_service import get_setting_raw, set_setting

    if (get_setting_raw(db, "sales_tax_system") or "us") == "canada":
        return None
    tax = next(
        (by_qb[s["qb_name"]] for s in specs if s.get("rename") is not None), None
    )
    if tax is None:
        return None
    rates = {}
    for t in txns:
        for ln in t["lines"]:
            m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*%\s*", ln.get("price") or "")
            if m and ln["account"] and tax.name.lower().endswith(ln["account"].lower()):
                rates[m.group(1)] = rates.get(m.group(1), 0) + 1
    rate = max(rates, key=rates.get) if rates else "13"
    rate = format(Decimal(rate).normalize(), "f")
    set_setting(db, "sales_tax_system", "canada")
    set_setting(db, "home_currency", "CAD")
    set_setting(db, "hst_account_id", str(tax.id))
    set_setting(db, "hst_rate", rate)
    set_setting(db, "default_tax_rate", rate)
    return (
        f"Home currency set to CAD. GST/HST is set up: {tax.name} at {rate}%. Choose how often this company "
        "files (monthly, quarterly, yearly or not registered) in Settings → Sales Tax."
    )


def _kind(t: dict, by_qb_type: dict[str, str]) -> str:
    """expense, deposit or a journal entry, by the transaction's type and
    whether its first line (the bank, in QuickBooks) fits that document."""
    ttype = (t["type"] or "").strip().lower()
    lines = [ln for ln in t["lines"] if ln["debit"] or ln["credit"]]
    if len(lines) < 2:
        return SOURCE_TYPE
    head = lines[0]
    head_type = by_qb_type.get(head["account"])
    rest = lines[1:]
    if ttype in _EXPENSE_TYPES and head_type in ("BANK", "CCARD"):
        paid = head["credit"] - head["debit"]
        if paid > 0 and all(ln["account"] != head["account"] for ln in rest):
            return "expense"
    if ttype in _DEPOSIT_TYPES and head_type == "BANK":
        if head["debit"] - head["credit"] > 0 and all(
            ln["account"] != head["account"] for ln in rest
        ):
            return "deposit"
    return SOURCE_TYPE


def _description(t: dict) -> str:
    words = t["type"] + (f" {t['num']}" if t["num"] else "")
    if t["name"]:
        words += f" — {t['name']}"
    if t["memo"]:
        words += f": {t['memo']}"
    return words[:500]


def _line_description(t: dict, line: dict) -> str | None:
    parts = []
    if line["name"] and line["name"] != t["name"]:
        parts.append(line["name"])
    if line["memo"] and line["memo"] != t["memo"]:
        parts.append(line["memo"])
    return " — ".join(parts)[:300] or None


# ── deposits and reconciliations ───────────────────────────────────────────

# QuickBooks' "X" (or ✔) in the Clr column: the line is on a reconciled
# statement. "*" is cleared, "M" matched to a downloaded bank transaction —
# ticked, but not reconciled.
_RECONCILED = {"X", "✔", "√"}


def reconcile_plan(txns: list[dict], qtype: dict) -> dict:
    """{bank account: (last reconciled date, reconciled balance, lines)} —
    what the import will carry as each bank account's reconciliation, from
    the lines QuickBooks marked reconciled. Bank accounts only: a card's
    marks stay ticks."""
    out = {}
    for t in txns:
        for line in t["lines"]:
            if qtype.get(line["account"]) != "BANK" or line["clr"] not in _RECONCILED:
                continue
            d, bal, n = out.get(line["account"], (t["date"], Decimal("0"), 0))
            out[line["account"]] = (
                max(d, t["date"]),
                bal + line["debit"] - line["credit"],
                n + 1,
            )
    return out


def _carry_reconciliations(db: Session, by_qb, qtype, marks) -> list[str]:
    """One completed reconciliation per bank account, through the last date
    QuickBooks reconciled, holding every line it had reconciled. The first
    reconciliation here then starts from QuickBooks' last statement balance
    with only what was still outstanding."""
    from app.models.banking import Reconciliation, ReconciliationStatus

    per = defaultdict(list)
    for acct_name, clr, row, when in marks:
        if qtype.get(acct_name) == "BANK" and clr in _RECONCILED:
            per[acct_name].append((row, when))
    notes = []
    for acct_name, rows in per.items():
        acct = by_qb[acct_name]
        already = (
            db.query(Reconciliation)
            .filter(
                Reconciliation.account_id == acct.id,
                Reconciliation.status == ReconciliationStatus.COMPLETED,
            )
            .first()
        )
        if already:
            notes.append(
                f"{acct.name} already has a reconciliation here; QuickBooks' was not carried again"
            )
            continue
        last = max(w for _, w in rows)
        balance = _q(
            sum(
                (
                    Decimal(str(r.debit or 0)) - Decimal(str(r.credit or 0))
                    for r, _ in rows
                ),
                Decimal("0"),
            )
        )
        recon = Reconciliation(
            account_id=acct.id,
            statement_date=last,
            statement_balance=balance,
            beginning_balance=Decimal("0"),
            cleared_total=balance,
            status=ReconciliationStatus.COMPLETED,
            completed_at=datetime.utcnow(),
        )
        db.add(recon)
        db.flush()
        for r, _ in rows:
            r.cleared = True
            r.reconciliation_id = recon.id
        notes.append(
            f"{acct.name}: reconciled through {last:%d %b %Y} as in QuickBooks, "
            f"statement balance {balance:,.2f} ({len(rows)} items); the next "
            f"reconciliation here starts from that balance"
        )
    return notes


def _link_deposits(db: Session, txns, txn_ids, qtype) -> str:
    """Point each customer payment's Undeposited Funds line at the deposit
    that banked it — by customer and amount, the oldest payment first — so
    Make Deposits lists only what QuickBooks still had undeposited."""
    from app.services.accounting import get_undeposited_funds_id

    try:
        uf_id = get_undeposited_funds_id(db)
    except Exception:
        return ""
    waiting = defaultdict(list)  # (who, amount) → [line], oldest first
    by_amount = defaultdict(list)
    rows = (
        db.query(TransactionLine, Transaction)
        .join(Transaction, TransactionLine.transaction_id == Transaction.id)
        .filter(
            TransactionLine.account_id == uf_id,
            TransactionLine.debit > 0,
            TransactionLine.deposit_transaction_id.is_(None),
            Transaction.source_type == "payment",
        )
        .order_by(Transaction.date, Transaction.id)
        .all()
    )
    from app.models.payments import Payment
    from app.models.contacts import Customer

    names = dict(
        db.query(Payment.id, Customer.name)
        .join(Customer, Payment.customer_id == Customer.id)
        .all()
    )
    for line, txn in rows:
        key = ((names.get(txn.source_id) or "").lower(), _q(line.debit))
        waiting[key].append((line, txn.date))
        by_amount[key[1]].append((line, txn.date))
    used = set()
    linked = missed = 0
    uf_names = {
        name
        for name, kind in qtype.items()
        if kind == "OCASSET" and name.lower() == "undeposited funds"
    }
    for t in txns:
        if t["trans"] not in txn_ids:
            continue
        dep_id = txn_ids[t["trans"]][0]
        for line in t["lines"]:
            if line["account"] not in uf_names or line["credit"] <= line["debit"]:
                continue
            amount = _q(line["credit"] - line["debit"])
            pool = (
                waiting.get(((line["name"] or "").lower(), amount))
                or by_amount.get(amount)
                or []
            )
            hit = next(
                (ln for ln, d in pool if ln.id not in used and d <= t["date"]), None
            )
            if hit is None:
                missed += 1
                continue
            used.add(hit.id)
            hit.deposit_transaction_id = dep_id
            linked += 1
    db.flush()
    if not (linked or missed):
        return ""
    text = f"Linked {linked} customer payments to the deposits that banked them"
    if missed:
        text += (
            f"; {missed} deposited amounts matched no payment here and stay as they are"
        )
    return text


# ── QuickBooks' own reports, by year ───────────────────────────────────────

_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ],
        1,
    )
}


def _column_date(label: str) -> date | None:
    """'31 Dec 94', 'Dec 31, 94', '2024-12-31' → the period's last day."""
    s = " ".join(label.strip().lower().replace(",", " ").split())
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2}) ([a-z]{3})[a-z]* (\d{2}|\d{4})", s)  # 31 Dec 94
    if m:
        day, mon, year = int(m[1]), m[2], int(m[3])
    else:
        m = re.fullmatch(r"([a-z]{3})[a-z]* (\d{1,2}) (\d{2}|\d{4})", s)  # Dec 31, 94
        if not m:
            return None
        mon, day, year = m[1], int(m[2]), int(m[3])
    if mon not in _MONTHS:
        return None
    mon = _MONTHS[mon]
    if year < 100:
        year += 2000 if year < 50 else 1900
    return date(year, mon, day)


def parse_report_by_year(
    text: str, label: str
) -> tuple[list[date], dict[str, list[Decimal]], list[str]]:
    """A Balance Sheet or Profit & Loss with a column per year: the period
    end dates, and {row label: [figure per year]}. Section headings, totals
    and blank rows are left out by the caller, which matches labels to
    accounts."""
    rows = _rows(text)
    errors: list[str] = []
    for i, row in enumerate(rows):
        dates = [_column_date(c) for c in row[1:]]
        found = [d for d in dates if d]
        if len(found) >= 1 and row and not row[0].strip():
            ends = []
            idx = []
            for j, d in enumerate(dates, start=1):
                if d:
                    ends.append(d)
                    idx.append(j)
            figures: dict[str, list[Decimal]] = {}
            for r in rows[i + 1 :]:
                if not r or not r[0].strip():
                    continue
                vals = []
                for j in idx:
                    raw = r[j].strip() if j < len(r) else ""
                    try:
                        vals.append(parse_amount(raw))
                    except Exception:
                        vals.append(Decimal(0))
                figures[r[0].strip()] = vals
            if ends != sorted(ends):
                errors.append(f"{label}: the year columns are not in order")
            return ends, figures, errors
    return (
        [],
        {},
        [
            f"{label}: no row of year columns found — run it with Dates: All and "
            f"Show Columns: Year, and export it as CSV"
        ],
    )


def verify(txns, specs, bs_text, pl_text) -> tuple[list[str], list[str], int]:
    """Rebuild every balance QuickBooks shows by year and compare to the
    cent. Returns (errors, notes, figures checked)."""
    errors: list[str] = []
    notes: list[str] = []
    # The reports name an account by its own name; a name two parents share
    # cannot be told apart there and is left to the totals.
    by_leaf: dict[str, list[dict]] = defaultdict(list)
    for s in specs:
        by_leaf[s["leaf"]].append(s)
    parents = {s["parent_qb"] for s in specs if s["parent_qb"]}

    def shown_row(rows: dict, s: dict):
        """The report row that carries the account's own figures. A parent
        with sub-accounts shows its own postings as "<name> - Other" (its
        own-name row is a heading over the children)."""
        if len(by_leaf[s["leaf"]]) != 1:
            return None
        if s["qb_name"] in parents:
            return rows.get(f"{s['leaf']} - Other")
        return rows.get(s["leaf"])

    postings = defaultdict(list)  # qb_name → [(date, debit - credit)]
    for t in txns:
        for line in t["lines"]:
            postings[line["account"]].append(
                (t["date"], line["debit"] - line["credit"])
            )

    def net(qb_name, start, end):
        return sum(
            (
                a
                for d, a in postings[qb_name]
                if (start is None or d > start) and d <= end
            ),
            Decimal(0),
        )

    checked = 0
    pl_ends: list[date] = []
    if pl_text:
        pl_ends, pl_rows, e = parse_report_by_year(pl_text, "Profit & Loss")
        errors.extend(e)
        for s in specs:
            if s["qb_type"] not in _PL_TYPES:
                continue
            sign = -1 if s["qb_type"] in _INCOME_TYPES else 1
            shown = shown_row(pl_rows, s)
            prev = None
            for k, end in enumerate(pl_ends):
                ours = sign * net(s["qb_name"], prev, end)
                theirs = shown[k] if shown else Decimal(0)
                if shown is not None or ours != 0:
                    checked += 1
                    if _q(ours - theirs) != 0:
                        errors.append(
                            f"{s['qb_name']} for the year to {end}: QuickBooks shows "
                            f"{theirs:,.2f}, the Journal gives {ours:,.2f}"
                        )
                prev = end
    if bs_text:
        bs_ends, bs_rows, e = parse_report_by_year(bs_text, "Balance Sheet")
        errors.extend(e)
        pl_accounts = [s["qb_name"] for s in specs if s["qb_type"] in _PL_TYPES]
        for s in specs:
            if s["qb_type"] in _PL_TYPES:
                continue
            sign = 1 if s["qb_type"] in _DEBIT_NATURE else -1
            shown = shown_row(bs_rows, s)
            is_re = s["leaf"].lower() == "retained earnings"
            for k, end in enumerate(bs_ends):
                ours = sign * net(s["qb_name"], None, end)
                if is_re:
                    # QuickBooks shows Retained Earnings with every earlier
                    # year's net income closed into it.
                    year_start = (
                        date(end.year - 1, end.month, end.day)
                        if k == 0
                        else bs_ends[k - 1]
                    )
                    ours += sum(-net(a, None, year_start) for a in pl_accounts)
                theirs = shown[k] if shown else Decimal(0)
                if shown is not None or ours != 0:
                    checked += 1
                    if _q(ours - theirs) != 0:
                        errors.append(
                            f"{s['qb_name']} at {end}: QuickBooks shows {theirs:,.2f}, "
                            f"the Journal gives {ours:,.2f}"
                        )
    if not bs_text:
        notes.append(
            "No Balance Sheet by year was uploaded: balance sheet accounts were not verified"
        )
    if not pl_text:
        notes.append(
            "No Profit & Loss by year was uploaded: income and expense were not verified"
        )
    if len(errors) > 40:
        errors = errors[:40] + [f"…and {len(errors) - 40} more differences"]
    return errors, notes, checked


# ── attachments ────────────────────────────────────────────────────────────


def parse_attach_map(text: str) -> tuple[dict[str, str], list[str]]:
    """{QuickBooks folder name → Trans #} from the map CSV."""
    errors = []
    out: dict[str, str] = {}
    rows = _rows(text)
    if not rows:
        return out, ["Attachment map: the file is empty"]
    hdr = [c.strip().lower() for c in rows[0]]
    if "trans #" not in hdr or "folder" not in hdr:
        return out, ["Attachment map: needs columns Trans # and Folder"]
    it, iff = hdr.index("trans #"), hdr.index("folder")
    for r in rows[1:]:
        if len(r) <= max(it, iff) or not r[iff].strip():
            continue
        out[r[iff].strip()] = r[it].strip()
    return out, errors


def attachment_plan(zip_bytes: bytes | None, amap: dict[str, str], txns: list[dict]):
    """[(trans, filename, path in zip)] the import will attach, and notes on
    what it will not."""
    plan, notes = [], []
    if not zip_bytes:
        return plan, notes
    known = {t["trans"] for t in txns}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        folders = defaultdict(list)
        for name in z.namelist():
            parts = name.replace("\\", "/").split("/")
            low = [p.lower() for p in parts]
            if "txn" not in low or name.endswith("/"):
                continue
            k = low.index("txn")
            if len(parts) < k + 3 or parts[-1].startswith("."):
                continue
            folders[parts[k + 1]].append(name)
    unmapped = []
    for folder, files in sorted(folders.items()):
        trans = amap.get(folder)
        if not trans:
            unmapped.append(folder)
            continue
        if trans not in known:
            notes.append(
                f"Attachment map sends folder {folder} to Trans # {trans}, which the Journal does not have"
            )
            continue
        for path in files:
            fname = posixpath.basename(path)
            ext = posixpath.splitext(fname)[1].lower()
            if ext not in _ATTACH_TYPES:
                notes.append(
                    f"{fname} (Trans # {trans}) is a {ext or 'typeless'} file Slowbooks does not store; it was left out"
                )
                continue
            plan.append((trans, fname, path))
    if unmapped:
        notes.append(
            f"{len(unmapped)} attachment folder(s) are not in the map and were not attached: "
            + ", ".join(unmapped[:10])
            + (" …" if len(unmapped) > 10 else "")
        )
    return plan, notes


# ── dry run and import ─────────────────────────────────────────────────────


def _resolve_accounts(db: Session, specs: list[dict]):
    """{qb_name → existing Account or None (to create)} and the problems."""
    errors, notes = [], []
    everything = db.query(Account).all()
    existing = {a.name.lower(): a for a in everything}
    seeded_tax = next((a for a in everything if a.account_number == "2200"), None)
    plan = {}
    for s in specs:
        acct = existing.get(s["name"].lower())
        if (
            acct is None
            and seeded_tax is not None
            and not s["parent_qb"]
            and s["qb_type"] == "OCLIAB"
            and re.search(r"\b(GST|HST)\b", s["name"], re.I)
            and seeded_tax not in plan.values()
        ):
            # QuickBooks Canada's GST/HST Payable is Slowbooks' sales tax
            # account under its Canadian name: one account, renamed on import
            # (services/hst.py points GST/HST at it).
            s["rename"] = seeded_tax.name != s["name"]
            notes.append(
                f"{s['qb_name']} becomes {seeded_tax.account_number} {seeded_tax.name}, renamed {s['name']}"
            )
            plan[s["qb_name"]] = seeded_tax
            continue
        if acct is not None and acct.is_system and s["parent_qb"]:
            # A sub-account named like one of Slowbooks' starting accounts
            # (Auto:Insurance and 6300 Insurance) is its own account, kept
            # under its parent, not folded into the top-level one.
            s["name"] = f"{s['leaf']} ({s['parent_qb'].split(':')[-1]})"
            acct = existing.get(s["name"].lower())
        if acct is not None and acct.account_type != s["type"]:
            errors.append(
                f"QuickBooks account {s['qb_name']!r} is {s['type'].value}, but these books "
                f"already have {acct.name!r} as {acct.account_type.value}; rename one first"
            )
        elif acct is not None and acct.is_system:
            # one of Slowbooks' own starting accounts (Retained Earnings,
            # Accounts Receivable …): worth saying the two become one
            notes.append(
                f"{s['qb_name']} joins the existing account {acct.account_number or ''} {acct.name}".replace(
                    "  ", " "
                )
            )
        plan[s["qb_name"]] = acct
    return plan, errors, notes


def _prepare(db: Session, bundle: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    if "lists" not in bundle:
        errors.append(
            "Missing the IIF list export (File → Utilities → Export → Lists to IIF Files)"
        )
    if "gl" not in bundle:
        errors.append(
            "Missing the Journal report saved as CSV (a file name with 'journal' in it)"
        )
    if errors:
        return {"errors": errors, "warnings": warnings}
    specs, e = parse_chart(bundle["lists"])
    errors.extend(e)
    txns, e = parse_journal(bundle["gl"])
    errors.extend(e)
    errors.extend(resolve_accounts(txns, specs))
    plan, e, joins = _resolve_accounts(db, specs)
    errors.extend(e)
    v_errors, v_notes, checked = verify(txns, specs, bundle.get("bs"), bundle.get("pl"))
    errors.extend(v_errors)
    warnings.extend(v_notes)
    from app.services import qbd_documents

    qtype = {sp["qb_name"]: sp["qb_type"] for sp in specs}
    docplan = qbd_documents.plan(txns, qtype)
    warnings.extend(docplan["notes"])
    amap, e = (
        parse_attach_map(bundle["attach_map"]) if "attach_map" in bundle else ({}, [])
    )
    errors.extend(e)
    attach, a_notes = attachment_plan(bundle.get("attachments"), amap, txns)
    if bundle.get("attachments") and "attach_map" not in bundle:
        a_notes.insert(
            0,
            "An Attach folder came without an attachment map, so nothing in it can be attached",
        )
    warnings.extend(a_notes)
    seen = _imported(db)
    other = _other_company(db, txns, seen)
    if other:
        errors.insert(0, other)
    dups = [t for t in txns if t["trans"] in seen]
    if dups:
        warnings.append(
            f"{len(dups)} of the {len(txns)} transactions are already in the books from an "
            f"earlier import and will be skipped"
        )
    lists = _iif_sections(bundle["lists"])
    from app.models.contacts import Customer, Vendor

    def new_names(rows, model):
        have = {n.lower() for (n,) in db.query(model.name).all()}
        return len({_unquote(r.get("NAME", "")).lower() for r in rows} - have - {""})

    return {
        "new_customers": new_names(lists.get("CUST", []), Customer),
        "new_vendors": new_names(lists.get("VEND", []), Vendor),
        "errors": errors,
        "warnings": warnings,
        "specs": specs,
        "txns": txns,
        "plan": plan,
        "joins": joins,
        "checked": checked,
        "attach": attach,
        "dups": {t["trans"] for t in dups},
        "lists": lists,
        "docs": docplan,
        "reconcile": reconcile_plan(txns, qtype),
    }


def _summary(p: dict) -> dict:
    specs = p.get("specs") or []
    txns = p.get("txns") or []
    plan = p.get("plan") or {}
    out = {
        "ok": not p["errors"],
        "errors": p["errors"],
        "warnings": list(p["warnings"]),
        "accounts": len(specs),
        "new_accounts": len([s for s in specs if plan.get(s["qb_name"]) is None]),
        "journals": len(txns),
        "duplicate_journals": len(p.get("dups") or ()),
        "customers": p.get("new_customers", 0),
        "vendors": p.get("new_vendors", 0),
        "attachments": len(p.get("attach") or []),
        "figures_verified": p.get("checked", 0),
    }
    if txns:
        types = defaultdict(int)
        for t in txns:
            types[t["type"]] += 1
        first, last = min(t["date"] for t in txns), max(t["date"] for t in txns)
        out["warnings"].insert(
            0,
            f"{len(txns)} transactions from {first} to {last}: "
            + ", ".join(
                f"{n} {k}" for k, n in sorted(types.items(), key=lambda kv: -kv[1])
            ),
        )
    if p.get("joins"):
        out["warnings"].append(
            "These QuickBooks accounts join the account of the same name already in "
            "the books: "
            + "; ".join(
                j.replace(" joins the existing account ", " → ") for j in p["joins"]
            )
        )
    if p.get("checked") and not p["errors"]:
        out["warnings"].insert(
            1,
            f"Verified against QuickBooks to the cent: {p['checked']} balances and yearly totals",
        )
    docs = (p.get("docs") or {}).get("counts") or {}
    if any(docs.values()):
        out["warnings"].append(
            f"Documents: {docs.get('invoice', 0)} invoices, {docs.get('payment', 0)} customer "
            f"payments, {docs.get('bill', 0)} bills and {docs.get('bill_payment', 0)} bill "
            f"payments, each paid up to the open balance QuickBooks shows"
        )
    for acct, (last, bal, n) in sorted((p.get("reconcile") or {}).items()):
        out["warnings"].append(
            f"{acct}: QuickBooks reconciled it through {last:%d %b %Y}; the reconciled "
            f"balance comes to {bal:,.2f} ({n} items) — compare it with that statement's "
            f"ending balance"
        )
    return out


def dry_run(db: Session, bundle: dict) -> dict:
    p = _prepare(db, bundle)
    return _summary(p)


def run_import(db: Session, bundle: dict) -> dict:
    from app.services import file_store
    from app.services.iif_import import (
        import_classes,
        import_customers,
        import_items,
        import_vendors,
    )

    p = _prepare(db, bundle)
    result = _summary(p)
    zeros = dict(
        imported_accounts=0,
        imported_journals=0,
        imported_customers=0,
        imported_vendors=0,
        imported_attachments=0,
    )
    if p["errors"]:
        return {**result, **zeros}

    # The chart: parents first (specs are sorted by depth).
    by_qb: dict[str, Account] = {}
    created = 0
    for s in p["specs"]:
        acct = p["plan"].get(s["qb_name"])
        if acct is None:
            number = s["number"]
            if (
                number
                and db.query(Account.id)
                .filter(Account.account_number == number)
                .first()
            ):
                number = None  # the seeded chart has it; the name is what matters
            acct = Account(
                name=s["name"],
                account_number=number,
                account_type=s["type"],
                description=s["description"],
                is_active=not s["hidden"],
            )
            if s["bank_kind"]:
                acct.bank_kind = s["bank_kind"]
            if s["parent_qb"] and s["parent_qb"] in by_qb:
                acct.parent_id = by_qb[s["parent_qb"]].id
            db.add(acct)
            db.flush()
            created += 1
        elif s.get("rename"):
            acct.name = s["name"]
        by_qb[s["qb_name"]] = acct

    # Lists that carry no money: classes, customers, vendors, items.
    lists = p["lists"]
    counts = {}
    for key, fn in (
        ("CLASS", import_classes),
        ("CUST", import_customers),
        ("VEND", import_vendors),
        ("INVITEM", import_items),
    ):
        rows = lists.get(key) or []
        if rows:
            r = fn(db, rows)
            counts[key] = r.get("imported", 0)
            result["warnings"].extend(
                f"{key}: {e}" for e in (r.get("errors") or [])[:5]
            )

    # Every transaction, as QuickBooks posted it.
    from app.models.classes import TxnClass

    # Classes keep QuickBooks' full Parent:Child name, as the Journal writes it.
    classes = {c.name.lower(): c for c in db.query(TxnClass).all()}
    from app.models.contacts import Vendor

    from app.services import qbd_documents

    vendors = {
        name.lower(): vid for vid, name in db.query(Vendor.id, Vendor.name).all()
    }
    by_qb_type = {s["qb_name"]: s["qb_type"] for s in p["specs"]}
    maker = qbd_documents.Maker(db, by_qb, by_qb_type, p["docs"])
    posted = 0
    made = defaultdict(int)
    txn_ids: dict[str, tuple[int, str, int | None]] = {}
    marks = []  # (account, clr, transaction line, date) for the reconciliations
    for t in p["txns"]:
        if t["trans"] in p["dups"]:
            continue
        kind = p["docs"]["kind"].get(t["trans"]) or _kind(t, by_qb_type)
        lines = []
        cleared = []
        for line in t["lines"]:
            if line["debit"] == 0 and line["credit"] == 0:
                continue
            d, c = _q(line["debit"]), _q(line["credit"])
            if d < 0:
                c, d = c - d, _q(0)
            if c < 0:
                d, c = d - c, _q(0)
            entry = {
                "account_id": by_qb[line["account"]].id,
                "debit": d,
                "credit": c,
                "description": (
                    _line_description(t, line)
                    if kind == SOURCE_TYPE
                    # on a cheque or deposit each line keeps its own words:
                    # the name and memo QuickBooks shows on it
                    else (
                        " — ".join(
                            w
                            for w in (
                                line["name"] if kind == "deposit" else "",
                                line["memo"],
                            )
                            if w
                        )[:300]
                        or None
                    )
                ),
            }
            if line["cls"]:
                cls = classes.get(line["cls"].strip().lower())
                if cls is None:
                    cls = TxnClass(name=line["cls"].strip()[:100])
                    db.add(cls)
                    db.flush()
                    classes[line["cls"].strip().lower()] = cls
                entry["class_id"] = cls.id
            lines.append(entry)
            cleared.append((line["account"], line["clr"]))
        if not lines:
            # QuickBooks keeps a voided invoice or bill, every amount 0.00:
            # it comes across void, its number kept, posting nothing
            if (t["type"] or "").lower() in ("invoice", "bill") and t["lines"]:
                maker.void(t)
            continue
        doc_id = None
        if kind in qbd_documents.DOC_KINDS:
            source_type, source_id = getattr(maker, kind)(t)
            doc_id = source_id
            description = _description(t)
        elif kind == "expense":
            # the bank line first, so the Expense form reads it as Paid From
            payee = t["name"] or ""
            description = f"Expense: {payee}" if payee else "Expense"
            source_id = vendors.get(payee.lower())
        elif kind == "deposit":
            description = "Deposit" + (
                f": {t['memo']}" if t["memo"] and t["memo"].lower() != "deposit" else ""
            )
            source_id = None
        else:
            description, source_id = _description(t), None
        txn = create_journal_entry(
            db,
            t["date"],
            description[:500],
            lines,
            source_type=_DOC_SOURCE[kind],
            source_id=source_id,
            reference=_reference(t, kind)[:100],
        )
        if kind in qbd_documents.DOC_KINDS:
            maker.link(t, txn.id)
        elif kind == SOURCE_TYPE and t["trans"] in p["docs"]["side"]:
            maker.sides(t, txn.id)
        if any(clr for _, clr in cleared):
            db.flush()  # the session does not autoflush: the lines must be written to be read
            tl = (
                db.query(TransactionLine)
                .filter(TransactionLine.transaction_id == txn.id)
                .order_by(TransactionLine.id)
                .all()
            )
            for row, (acct_name, clr) in zip(tl, cleared):
                if clr and clr != "-":
                    row.cleared = True
                    marks.append((acct_name, clr, row, t["date"]))
        txn_ids[t["trans"]] = (txn.id, kind, doc_id)
        made[kind] += 1
        posted += 1

    # Payments applied to invoices and bill payments to bills; deposits to
    # the payments they took; the reconciliations QuickBooks had.
    maker.settle()
    deposited = _link_deposits(db, p["txns"], txn_ids, by_qb_type)
    reconciled = _carry_reconciliations(db, by_qb, by_qb_type, marks)

    # Documents, onto the cheque, deposit or journal entry they came with.
    attached = 0
    if p["attach"]:
        known = _imported(db)
        known.update(txn_ids)
        with zipfile.ZipFile(io.BytesIO(bundle["attachments"])) as z:
            for trans, fname, path in p["attach"]:
                if trans not in known:
                    continue
                tid, kind, doc_id = known[trans]
                entity, by = _ATTACH_ENTITY.get(kind, ("journal_entry", "txn"))
                if by == "doc" and doc_id:
                    tid = doc_id
                if (
                    db.query(Attachment.id)
                    .filter(
                        Attachment.entity_type == entity,
                        Attachment.entity_id == tid,
                        Attachment.filename == fname,
                    )
                    .first()
                ):
                    continue  # attached by an earlier run
                ext = posixpath.splitext(fname)[1].lower()
                file_store.add_attachment(
                    db,
                    entity_type=entity,
                    entity_id=tid,
                    filename=fname,
                    content_type=_ATTACH_TYPES.get(ext)
                    or mimetypes.guess_type(fname)[0],
                    data=z.read(path),
                )
                attached += 1
    if posted:
        result["warnings"].append(
            f"Posted {made['expense']} cheques and card charges as Expenses, "
            f"{made['deposit']} deposits as Deposits, {made['invoice']} invoices, "
            f"{made['payment']} customer payments, {made['bill']} bills, "
            f"{made['bill_payment']} bill payments and {made[SOURCE_TYPE]} other "
            f"transactions as journal entries"
        )
        if deposited:
            result["warnings"].append(deposited)
        result["warnings"].extend(reconciled)

    from app.services.settings_service import set_setting

    set_setting(db, FINGERPRINT_KEY, fingerprint(p["txns"]))
    hst_note = _set_up_hst(db, p["specs"], by_qb, p["txns"])
    if hst_note:
        result.setdefault("warnings", []).append(hst_note)
    db.commit()
    result.update(
        imported_accounts=created,
        imported_journals=posted,
        imported_customers=counts.get("CUST", 0),
        imported_vendors=counts.get("VEND", 0),
        imported_attachments=attached,
    )
    return result
