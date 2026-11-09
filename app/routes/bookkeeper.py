# ============================================================================
# Bookkeeper inbox (John's build).
#
# An agent bookkeeper reads the month's statements (the clubs', Amex) and
# writes what it prepared, as JSON, into the company's bookkeeper folder
# (Settings: bookkeeper_folder) under "To review". Nothing it prepares is
# posted: the Bookkeeper inbox screen lists it, John checks or fixes each
# item, and the screen enters it through the ordinary routes (/api/bills,
# /api/expenses, /api/bill-payments), so every check those make still
# applies. Then it tells this route, which attaches the statement to what
# was entered and, once a file's items are all done, files the JSON and
# its statements under Done/YYYY-MM.
#
# A file in "To review":
#   {"title": "Amex statement Oct 2026", "source": ["Amex 2026-10.pdf"],
#    "items": [{"id": "1", "kind": "bill" | "expense" | "bill_payment",
#               "vendor": "Oakville Club", "date": "2026-10-31",
#               "number": "S209-2026-10", "memo": "...",
#               "paid_from": "American Express",        (expense, payment)
#               "lines": [{"account": "Meals", "amount": "361.12",
#                          "memo": "..."}],               (bill, expense)
#               "bill_number": "S209-2026-10", "amount": "783.80",
#               "method": "ach", "reference": "EFT",     (bill_payment)
#               "attach": true,  (attach the statement; default true)
#               "questions": ["..."]}]}
# Names, not ids: the agent writes what the statement and the routine say,
# and this route finds the vendor and the accounts, saying which it can't.
# ============================================================================

import json
import mimetypes
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.accounts import Account
from app.models.bills import Bill
from app.models.contacts import Vendor
from app.models.settings import Settings
from app.schemas.common import StrictModel
from app.services import file_store

router = APIRouter(prefix="/api/bookkeeper", tags=["bookkeeper"])

TO_REVIEW, DONE, DISMISSED = "To review", "Done", "Dismissed"
KINDS = ("bill", "expense", "bill_payment", "reconciliation", "hst_return")
_NAME = re.compile(r"^[^/\\]+$")
_ATTACH_TYPE = {"bill": "bill", "expense": "expense", "bill_payment": "expense"}


def _folder(db: Session) -> Optional[Path]:
    row = db.query(Settings).filter(Settings.key == "bookkeeper_folder").first()
    text = (row.value if row else "") or ""
    text = text.strip()
    if not text:
        return None
    return find_folder(text)


def find_folder(text: str) -> Path:
    """The folder as typed, or, when that isn't there, the same path under
    the home folder: "/data/alderella/bookkeeper" or "data/alderella/..."
    typed for "~/DATA/Alderella/Bookkeeper". A Mac's disk ignores case, so
    that is all it takes. The path as typed comes back when neither is
    there, so the screen can say what it looked for."""
    path = Path(text.strip()).expanduser()
    if path.is_dir():
        return path
    under_home = Path.home() / str(path).lstrip("/\\")
    if under_home.is_dir():
        return under_home
    return path


def _need_folder(db: Session) -> Path:
    folder = _folder(db)
    if folder is None:
        raise HTTPException(
            status_code=400,
            detail="No bookkeeper folder is set for this company (Settings, Company).",
        )
    if not folder.is_dir():
        raise HTTPException(
            status_code=400, detail=f"The bookkeeper folder {folder} isn't there."
        )
    return folder


def _in(folder: Path, name: str) -> Path:
    """``name`` inside To review, or 404: a bare file name, never a path."""
    if not name or not _NAME.match(name) or name.startswith("."):
        raise HTTPException(status_code=404, detail="Not in the inbox")
    path = folder / TO_REVIEW / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not in the inbox")
    return path


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"{path.name}: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise HTTPException(status_code=400, detail=f"{path.name}: no items")
    return data


def _write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)


def _by_name(db: Session, model, name):
    name = (name or "").strip()
    if not name:
        return None
    return (
        db.query(model)
        .filter(func.lower(model.name) == name.lower(), model.is_active.isnot(False))
        .first()
    )


def _money(x) -> Optional[float]:
    try:
        return round(float(str(x).replace(",", "").replace("$", "")), 2)
    except (TypeError, ValueError):
        return None


def _resolve(db: Session, item: dict) -> dict:
    """The item as the screen shows it: the vendor's and accounts' ids where
    the names are found, and the problems (a name not found, a line with no
    amount) the screen must have fixed before it enters it."""
    problems = []
    kind = item.get("kind")
    if kind == "reconciliation":
        return _resolve_reconciliation(db, item)
    if kind == "hst_return":
        return _resolve_hst(db, item)
    if kind not in KINDS:
        problems.append(f"Unknown kind {kind!r}")
    vendor = _by_name(db, Vendor, item.get("vendor"))
    if not vendor:
        problems.append(f"Vendor not found: {item.get('vendor') or '(none)'}")
    paid_from = None
    if kind in ("expense", "bill_payment"):
        paid_from = _by_name(db, Account, item.get("paid_from"))
        if not paid_from:
            problems.append(f"Account not found: {item.get('paid_from') or '(none)'}")
    lines = []
    for ln in item.get("lines") or []:
        acct = _by_name(db, Account, ln.get("account"))
        amount = _money(ln.get("amount"))
        if not acct:
            problems.append(f"Account not found: {ln.get('account') or '(none)'}")
        if amount is None:
            problems.append(f"No amount on the {ln.get('account') or ''} line")
        lines.append(
            {
                "account": ln.get("account"),
                "account_id": acct.id if acct else None,
                "amount": amount,
                "memo": ln.get("memo") or "",
            }
        )
    bill = None
    if kind == "bill_payment":
        if vendor:
            bill = (
                db.query(Bill)
                .filter(
                    Bill.vendor_id == vendor.id,
                    Bill.bill_number == (item.get("bill_number") or ""),
                )
                .first()
            )
        if not bill:
            problems.append(
                f"Bill {item.get('bill_number') or '(none)'} isn't entered yet"
            )
        elif float(bill.balance_due or 0) <= 0:
            problems.append(f"Bill {bill.bill_number} is already paid")
        total = _money(item.get("amount"))
    else:
        total = round(sum(ln["amount"] or 0 for ln in lines), 2)
        if not lines:
            problems.append("No lines")
    return {
        "id": str(item.get("id")),
        "kind": kind,
        "vendor": item.get("vendor"),
        "vendor_id": vendor.id if vendor else None,
        "date": item.get("date"),
        "number": item.get("number") or "",
        "memo": item.get("memo") or "",
        "paid_from": item.get("paid_from"),
        "paid_from_id": paid_from.id if paid_from else None,
        "lines": lines,
        "total": total,
        "bill_number": item.get("bill_number"),
        "bill_id": bill.id if bill else None,
        "bill_balance": float(bill.balance_due) if bill else None,
        "method": item.get("method") or "ach",
        "reference": item.get("reference") or "",
        "questions": [str(q) for q in item.get("questions") or []],
        "problems": problems,
    }


@router.get("/inbox")
def inbox(db: Session = Depends(get_db)):
    """What waits for review, file by file (only items not yet entered or
    dismissed)."""
    folder = _folder(db)
    if folder is None:
        return {"folder": None, "files": []}
    review = folder / TO_REVIEW
    files = []
    if review.is_dir():
        for path in sorted(review.glob("*.json")):
            try:
                data = _read(path)
            except HTTPException as e:
                files.append({"file": path.name, "error": e.detail, "items": []})
                continue
            items = [
                _resolve(db, it)
                for it in data["items"]
                if isinstance(it, dict)
                and not it.get("entered")
                and not it.get("dismissed")
            ]
            sources = [{"name": p.name, "n": n} for n, p, _ in _sources(folder, data)]
            files.append(
                {
                    "file": path.name,
                    "title": data.get("title") or path.stem,
                    "prepared": data.get("prepared"),
                    "source": sources,
                    "items": items,
                }
            )
    return {"folder": str(folder), "exists": folder.is_dir(), "files": files}


def _sources(folder: Path, data: dict) -> list:
    """The statements a file names, as (index, path, in To review): a bare
    file name is in To review; a path with a folder in it ("RBC bank
    statements/ALD - CAN $ Statement-4696 2026-11-30.pdf") is under the
    company's own folder (the bookkeeper folder's parent), where John
    keeps his statements: shown and attached from there, never moved.
    Anything outside the company's folder is left out."""
    out = []
    review = (folder / TO_REVIEW).resolve()
    company = folder.parent.resolve()
    for n, raw in enumerate(data.get("source") or []):
        text = str(raw or "").strip()
        if not text or text.lower().endswith(".json"):
            continue
        if "/" in text or "\\" in text:
            path = (company / text).resolve()
            if company not in path.parents:
                continue
        else:
            if not _NAME.match(text) or text.startswith("."):
                continue
            path = review / text
        if path.is_file():
            out.append((n, path, path.parent == review))
    return out


@router.get("/statement/{name}/{n}")
def statement(name: str, n: int, db: Session = Depends(get_db)):
    """The n-th statement an inbox file names, to look at beside it."""
    folder = _need_folder(db)
    data = _read(_in(folder, name))
    for i, path, _ in _sources(folder, data):
        if i == n:
            kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            return FileResponse(path, media_type=kind, filename=path.name)
    raise HTTPException(status_code=404, detail="No such statement")


@router.get("/source/{name}")
def source(name: str, db: Session = Depends(get_db)):
    """A statement waiting in To review, to look at beside its items."""
    path = _in(_need_folder(db), name)
    if path.suffix.lower() == ".json":
        raise HTTPException(status_code=404, detail="Not a statement")
    kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=kind, filename=path.name)


class Entered(StrictModel):
    entity_type: str  # bill | expense | bill_payment
    entity_id: int


def _settle(folder: Path, path: Path, data: dict) -> bool:
    """A file whose items are all entered or dismissed goes, with its
    statements, to Done/YYYY-MM (Dismissed if none was entered). True if
    it was filed."""
    items = [it for it in data["items"] if isinstance(it, dict)]
    if any(not it.get("entered") and not it.get("dismissed") for it in items):
        return False
    month = date.today().strftime("%Y-%m")
    dest = folder / (DONE if any(it.get("entered") for it in items) else DISMISSED)
    dest = dest / month
    dest.mkdir(parents=True, exist_ok=True)
    moving = [p for _, p, inside in _sources(folder, data) if inside] + [path]
    for src in moving:
        if src.is_file():
            target = dest / src.name
            n = 1
            while target.exists():
                target = dest / f"{src.stem} ({n}){src.suffix}"
                n += 1
            shutil.move(str(src), str(target))
    return True


def _item(data: dict, item_id: str) -> dict:
    for it in data["items"]:
        if isinstance(it, dict) and str(it.get("id")) == str(item_id):
            return it
    raise HTTPException(status_code=404, detail="No such item")


@router.post("/inbox/{name}/{item_id}/entered")
def entered(name: str, item_id: str, body: Entered, db: Session = Depends(get_db)):
    """The screen entered this item: note it in the file, attach the
    statement to what was entered (unless the item says not to), and file
    the whole thing away once nothing in it is left to review."""
    folder = _need_folder(db)
    path = _in(folder, name)
    data = _read(path)
    item = _item(data, item_id)
    if item.get("entered"):
        raise HTTPException(status_code=409, detail="Already entered")
    attached = []
    if item.get("attach", True) and body.entity_type in ("bill", "expense"):
        for _, f, _inside in _sources(folder, data):
            file_store.add_attachment(
                db,
                entity_type=_ATTACH_TYPE[body.entity_type],
                entity_id=body.entity_id,
                filename=f.name,
                content_type=mimetypes.guess_type(f.name)[0] or "application/pdf",
                data=f.read_bytes(),
            )
            attached.append(f.name)
        db.commit()
    item["entered"] = {
        "type": body.entity_type,
        "id": body.entity_id,
        "on": date.today().isoformat(),
    }
    _write(path, data)
    return {"attached": attached, "filed": _settle(folder, path, data)}


@router.post("/inbox/{name}/{item_id}/dismiss")
def dismiss(name: str, item_id: str, db: Session = Depends(get_db)):
    """Not to be entered (already in the books, or wrong): kept in the
    file as dismissed, never posted."""
    folder = _need_folder(db)
    path = _in(folder, name)
    data = _read(path)
    _item(data, item_id)["dismissed"] = date.today().isoformat()
    _write(path, data)
    return {"filed": _settle(folder, path, data)}


# ----------------------------------------------------------------------------
# A bank statement to reconcile (John's build).
#
#   {"id": "1", "kind": "reconciliation", "account": "RBC - Can $",
#    "statement_date": "2026-11-30", "opening_balance": "38288.74",
#    "closing_balance": "41020.11",
#    "lines": [{"date": "2026-11-03", "description": "Cheque 1043",
#               "amount": "-250.00", "cheque": "1043"}, ...]}
#
# Amounts as the statement shows them: money in positive, money out
# negative. Each line is matched here, when the inbox is shown, against
# the account's lines not yet in a completed reconciliation: same amount,
# the cheque number when the statement gives one, the nearest date within
# ten days. So an item entered after the agent ran (a service charge, a
# deposit) matches as soon as it is in the books.
# ----------------------------------------------------------------------------

MATCH_DAYS = 10


def _recon_candidates(db: Session, account: Account, through: date):
    from app.models.transactions import Transaction, TransactionLine
    from app.services.bank_register import is_debit_normal

    from app.services.bank_register import references_for

    rows = (
        db.query(TransactionLine, Transaction)
        .join(Transaction, TransactionLine.transaction_id == Transaction.id)
        .filter(TransactionLine.account_id == account.id)
        .filter(TransactionLine.reconciliation_id.is_(None))
        .filter(Transaction.date <= through)
        .order_by(Transaction.date, Transaction.id, TransactionLine.id)
        .all()
    )
    refs = references_for(db, list({t.id: t for _, t in rows}.values()))
    debit_normal = is_debit_normal(account)
    out = []
    for tl, txn in rows:
        dr = float(tl.debit or 0)
        cr = float(tl.credit or 0)
        amount = round((dr - cr) if debit_normal else (cr - dr), 2)
        out.append(
            {
                "line_id": tl.id,
                "date": txn.date,
                "amount": amount,
                "reference": (refs.get(txn.id) or "").strip(),
                "description": (txn.description or "").strip(),
                "cleared": bool(tl.cleared),
            }
        )
    return out


def _as_date(text):
    try:
        return date.fromisoformat(str(text)[:10])
    except (TypeError, ValueError):
        return None


def _match(statement_lines: list, candidates: list) -> tuple:
    """Each statement line to one book line (amount, then cheque number,
    then the nearest date); the statement lines left over; the book lines
    left over (outstanding)."""
    free = list(candidates)
    matched, missing = [], []
    for sl in statement_lines:
        amount = _money(sl.get("amount"))
        when = _as_date(sl.get("date"))
        cheque = str(sl.get("cheque") or "").strip()
        best, best_key = None, None
        for c in free:
            if amount is None or abs(c["amount"] - amount) > 0.005:
                continue
            days = abs((c["date"] - when).days) if when else 0
            if days > MATCH_DAYS and not (cheque and c["reference"] == cheque):
                continue
            key = (0 if cheque and c["reference"] == cheque else 1, days)
            if best_key is None or key < best_key:
                best, best_key = c, key
        if best:
            free.remove(best)
            matched.append((sl, best))
        else:
            missing.append(sl)
    # A fee the bank took on the 1st, kept in the books on the last day of
    # the month: the same amount up to 35 days away, once nothing nearer
    # took it.
    for sl in list(missing):
        amount = _money(sl.get("amount"))
        when = _as_date(sl.get("date"))
        near = [
            c
            for c in free
            if amount is not None
            and abs(c["amount"] - amount) <= 0.005
            and (when is None or abs((c["date"] - when).days) <= 35)
        ]
        if near:
            c = min(near, key=lambda c: abs((c["date"] - when).days) if when else 0)
            free.remove(c)
            missing.remove(sl)
            matched.append((sl, c))
    # Several statement lines to one book entry: the month's bank fees
    # ($2 + $6 + $25) kept as one "Royal Bank" entry of $33.00 on the last
    # day of the month.
    for c in list(free):
        group = _group_for(c, missing)
        if group:
            free.remove(c)
            for sl in group:
                missing.remove(sl)
                matched.append((sl, c))
    return matched, missing, free


def _group_for(c: dict, missing: list):
    """Two to six of the statement lines left over, all within the window
    of the book entry ``c``, that add up to it exactly; None if none do."""
    from itertools import combinations

    near = [
        sl
        for sl in missing
        if _money(sl.get("amount")) is not None
        and (
            _as_date(sl.get("date")) is None
            or abs((c["date"] - _as_date(sl.get("date"))).days) <= MATCH_DAYS + 21
        )
        and (_money(sl.get("amount")) > 0) == (c["amount"] > 0)
    ][:14]
    for size in range(2, min(6, len(near)) + 1):
        for combo in combinations(near, size):
            if abs(sum(_money(sl["amount"]) for sl in combo) - c["amount"]) < 0.005:
                return list(combo)
    return None


def _resolve_reconciliation(db: Session, item: dict) -> dict:
    from app.models.banking import Reconciliation, ReconciliationStatus

    problems = []
    account = _by_name(db, Account, item.get("account"))
    when = _as_date(item.get("statement_date"))
    opening = _money(item.get("opening_balance"))
    closing = _money(item.get("closing_balance"))
    lines = [ln for ln in item.get("lines") or [] if isinstance(ln, dict)]
    out = {
        "id": str(item.get("id")),
        "kind": "reconciliation",
        "vendor": item.get("account"),
        "account": item.get("account"),
        "account_id": account.id if account else None,
        "date": item.get("statement_date"),
        "statement_date": item.get("statement_date"),
        "opening_balance": opening,
        "closing_balance": closing,
        "total": closing,
        "lines": [],
        "questions": [str(q) for q in item.get("questions") or []],
        "problems": problems,
        "matched": [],
        "missing": [],
        "outstanding": [],
        "difference": None,
    }
    if not account:
        problems.append(f"Account not found: {item.get('account') or '(none)'}")
        return out
    if not when or closing is None:
        problems.append("The statement date or closing balance is missing")
        return out
    last = (
        db.query(Reconciliation)
        .filter(
            Reconciliation.account_id == account.id,
            Reconciliation.status == ReconciliationStatus.COMPLETED,
        )
        .order_by(Reconciliation.statement_date.desc(), Reconciliation.id.desc())
        .first()
    )
    beginning = round(float(last.statement_balance), 2) if last else 0.0
    if last and when <= last.statement_date:
        problems.append(
            f"{account.name} is already reconciled through {last.statement_date.isoformat()}"
        )
    if opening is not None and abs(opening - beginning) > 0.005:
        problems.append(
            f"The statement opens at {opening:,.2f} but the last reconciliation "
            f"ended at {beginning:,.2f}"
        )
    open_one = (
        db.query(Reconciliation)
        .filter(
            Reconciliation.account_id == account.id,
            Reconciliation.status == ReconciliationStatus.IN_PROGRESS,
        )
        .first()
    )
    if open_one:
        problems.append(
            f"A reconciliation of {account.name} is already open (through "
            f"{open_one.statement_date.isoformat()}); finish or drop it first"
        )
    matched, missing, outstanding = _match(lines, _recon_candidates(db, account, when))
    cleared = round(
        sum(c["amount"] for c in {c["line_id"]: c for _, c in matched}.values()), 2
    )
    difference = round(closing - (beginning + cleared), 2)
    for sl in missing:
        problems.append(
            f"Not in the books: {sl.get('date')} {sl.get('description') or ''} "
            f"{_money(sl.get('amount')) or 0:,.2f}".replace("  ", " ")
        )
    if not missing and abs(difference) > 0.005:
        problems.append(f"Everything matched but it is out by {difference:,.2f}")
    out.update(
        matched=[
            {
                "date": c["date"].isoformat(),
                "amount": c["amount"],
                "line_id": c["line_id"],
                "description": sl.get("description") or c["description"],
            }
            for sl, c in matched
        ],
        missing=[
            {
                "date": sl.get("date"),
                "description": sl.get("description") or "",
                "amount": _money(sl.get("amount")),
            }
            for sl in missing
        ],
        outstanding=[
            {
                "date": c["date"].isoformat(),
                "amount": c["amount"],
                "description": c["description"],
                "reference": c["reference"],
            }
            for c in outstanding
        ],
        beginning=beginning,
        cleared_total=cleared,
        difference=difference,
    )
    return out


@router.post("/inbox/{name}/{item_id}/reconcile")
def reconcile(name: str, item_id: str, db: Session = Depends(get_db)):
    """Start the reconciliation the statement gives, every matched line
    ticked, for John to look over and finish on the reconcile screen.
    Refused while anything on the statement isn't in the books or it
    doesn't come to $0.00."""
    from decimal import Decimal

    from app.models.transactions import TransactionLine
    from app.services import reconciliation as rc

    folder = _need_folder(db)
    path = _in(folder, name)
    data = _read(path)
    item = _item(data, item_id)
    if item.get("entered"):
        raise HTTPException(status_code=409, detail="Already started")
    got = _resolve_reconciliation(db, item)
    if got["problems"]:
        raise HTTPException(status_code=400, detail="; ".join(got["problems"]))
    recon = rc.start(
        db,
        got["account_id"],
        _as_date(got["statement_date"]),
        Decimal(str(got["closing_balance"])),
    )
    db.flush()
    for m in got["matched"]:
        line = db.get(TransactionLine, m["line_id"])
        if line is not None and not line.cleared:
            line.cleared = True
    # a line ticked earlier but not on this statement stays for later
    on_statement = {m["line_id"] for m in got["matched"]}
    for c in _recon_candidates(
        db, db.get(Account, got["account_id"]), recon.statement_date
    ):
        if c["cleared"] and c["line_id"] not in on_statement:
            line = db.get(TransactionLine, c["line_id"])
            line.cleared = False
    db.commit()
    item["entered"] = {
        "type": "reconciliation",
        "id": recon.id,
        "on": date.today().isoformat(),
    }
    _write(path, data)
    return {"reconciliation_id": recon.id, "filed": _settle(folder, path, data)}


# ----------------------------------------------------------------------------
# The quarterly GST/HST return (John's build).
#
#   {"id": "1", "kind": "hst_return", "start": "2026-10-01",
#    "end": "2026-12-31",
#    "previous": {"start": "2026-07-01", "end": "2026-09-30",
#                 "itc_at_filing": "3049.04"},
#    "carry_forward_opening": [{"period_end": "2026-06-30", "held": "10000.00"},
#                              {"period_end": "2026-09-30", "claimed": "5000.00"}],
#    "questions": []}
#
# Slowbooks works the return out when it is shown, from the ledger (the
# GST/HST Return report's figures), and adds: the ITCs entered after the
# previous return was filed (that period's ITCs now, less what they were
# when it was filed), and ITCs carried forward. John never claims a
# refund: when the ITCs exceed the tax, the smallest multiple of $5,000
# that keeps the return payable is held back; when there's room, the
# largest multiple of $5,000 of the carried-forward ITCs that keeps it
# payable is claimed. Both are a suggestion he can change. Unclaimed ITCs
# can be claimed within four years. The carry-forward list is kept in
# the setting hst_itc_carryforward, seeded from the item the first time.
# ----------------------------------------------------------------------------

STEP = 5000.0
CARRY_KEY = "hst_itc_carryforward"


def _carry(db: Session, item: dict) -> list:
    from app.services.settings_service import get_setting_raw

    raw = get_setting_raw(db, CARRY_KEY)
    if raw:
        try:
            rows = json.loads(raw)
            if isinstance(rows, list):
                return rows
        except ValueError:
            pass
    rows = []
    for r in item.get("carry_forward_opening") or []:
        if isinstance(r, dict) and r.get("period_end"):
            rows.append(
                {
                    "period_end": str(r["period_end"]),
                    "held": _money(r.get("held")) or 0.0,
                    "claimed": _money(r.get("claimed")) or 0.0,
                }
            )
    return rows


def _balance(rows: list) -> float:
    return round(sum((r.get("held") or 0) - (r.get("claimed") or 0) for r in rows), 2)


def _resolve_hst(db: Session, item: dict, held=None, claimed=None) -> dict:
    from app.services.hst import gst_hst_return

    problems = []
    start, end = _as_date(item.get("start")), _as_date(item.get("end"))
    out = {
        "id": str(item.get("id")),
        "kind": "hst_return",
        "vendor": "Receiver General",
        "date": item.get("end"),
        "start": item.get("start"),
        "end": item.get("end"),
        "lines": [],
        "questions": [str(q) for q in item.get("questions") or []],
        "problems": problems,
    }
    if not start or not end or start > end:
        problems.append("The return's period is missing")
        return out
    ret = gst_hst_return(db, start, end)
    if not ret.get("enabled"):
        problems.append("No GST/HST account is set up (Settings, Sales Tax)")
        return out
    late = 0.0
    prev = item.get("previous") or {}
    if prev.get("start") and prev.get("end") and prev.get("itc_at_filing") is not None:
        then = _money(prev.get("itc_at_filing")) or 0.0
        now = gst_hst_return(db, _as_date(prev["start"]), _as_date(prev["end"]))
        late = round(float(now["line_106"]) - then, 2)
    rows = _carry(db, item)
    balance = _balance(rows)
    collected = round(float(ret["line_103"]), 2)
    itc = round(float(ret["line_106"]), 2)
    before = round(collected - itc - late, 2)  # net tax before carry-forward
    if held is None and claimed is None:
        held = claimed = 0.0
        if before < 0:
            held = STEP * -(-(-before) // STEP)  # the smallest step >= the excess
        elif balance > 0:
            room = min(before, balance)
            claimed = STEP * (room // STEP)
            if claimed == 0 and balance < STEP and balance <= before:
                claimed = balance  # the last of it
    held, claimed = round(held or 0.0, 2), round(claimed or 0.0, 2)
    if claimed > balance + 0.005:
        problems.append(
            f"Claiming {claimed:,.2f} carried forward, but only {balance:,.2f} is"
        )
    line106 = round(itc + late + claimed - held, 2)
    line109 = round(collected - line106, 2)
    if line109 < 0:
        out["questions"].append(
            f"This return would be a refund of {-line109:,.2f}; hold back more ITCs?"
        )
    out.update(
        total=max(line109, 0.0),
        line_101=round(float(ret["line_101"]), 2),
        line_103=collected,
        line_105=collected,
        itc_period=itc,
        late_itc=late,
        held=held,
        claimed=claimed,
        line_106=line106,
        line_108=line106,
        line_109=line109,
        line_114=max(-line109, 0.0),
        line_115=max(line109, 0.0),
        carry_before=balance,
        carry_after=round(balance + held - claimed, 2),
        carry_rows=rows,
        ties=bool(ret.get("ties")),
        registration_number=ret.get("registration_number") or "",
    )
    return out


class HstPaid(StrictModel):
    date: str
    amount: float
    paid_from: str  # account name
    reference: Optional[str] = None
    held: float = 0.0
    claimed: float = 0.0


@router.post("/inbox/{name}/{item_id}/hst-paid")
def hst_paid(name: str, item_id: str, body: HstPaid, db: Session = Depends(get_db)):
    """The return is filed and paid: enter the payment (Receiver General,
    from the bank to GST/HST Payable, as John's past payments are), keep
    the period's ITCs as they were when filed (for next quarter's late
    ITCs) and the carry-forward list, and file the item away."""
    from decimal import Decimal

    from app.routes.expenses import create_expense
    from app.schemas.expenses import ExpenseCreate
    from app.services.hst import account_id as hst_account
    from app.services.settings_service import set_setting

    folder = _need_folder(db)
    path = _in(folder, name)
    data = _read(path)
    item = _item(data, item_id)
    if item.get("entered"):
        raise HTTPException(status_code=409, detail="Already recorded")
    got = _resolve_hst(db, item, held=body.held, claimed=body.claimed)
    if got["problems"]:
        raise HTTPException(status_code=400, detail="; ".join(got["problems"]))
    vendor = _by_name(db, Vendor, "Receiver General")
    bank = _by_name(db, Account, body.paid_from)
    tax = hst_account(db)
    if not bank or tax is None:
        raise HTTPException(status_code=400, detail="Bank or GST/HST account not found")
    amount = Decimal(str(round(body.amount, 2)))
    expense_id = None
    if amount > 0:
        made = create_expense(
            ExpenseCreate(
                date=_as_date(body.date),
                vendor_id=vendor.id if vendor else None,
                payee=None if vendor else "Receiver General",
                paid_from_account_id=bank.id,
                amount=amount,
                lines=[
                    {
                        "account_id": tax,
                        "amount": amount,
                        "description": f"GST/HST {got['start']} to {got['end']}",
                    }
                ],
                reference=body.reference or None,
                memo=f"GST/HST return to {got['end']}",
            ),
            db=db,
            allow_duplicate_check_number=True,
        )
        expense_id = made.id if hasattr(made, "id") else made["id"]
    rows = got["carry_rows"]
    if body.held or body.claimed:
        rows = rows + [
            {
                "period_end": got["end"],
                "held": round(body.held, 2),
                "claimed": round(body.claimed, 2),
            }
        ]
    set_setting(db, CARRY_KEY, json.dumps(rows))
    db.commit()
    item["entered"] = {
        "type": "hst_return",
        "id": expense_id,
        "on": date.today().isoformat(),
        "itc_at_filing": got["itc_period"],
        "line_106": got["line_106"],
        "line_109": got["line_109"],
        "held": round(body.held, 2),
        "claimed": round(body.claimed, 2),
    }
    _write(path, data)
    return {
        "expense_id": expense_id,
        "carry_forward": _balance(rows),
        "filed": _settle(folder, path, data),
    }
