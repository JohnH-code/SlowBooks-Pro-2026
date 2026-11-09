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
KINDS = ("bill", "expense", "bill_payment", "reconciliation")
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
            sources = [
                s for s in data.get("source") or [] if (review / str(s)).is_file()
            ]
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
    for name in [*(data.get("source") or []), path.name]:
        src = folder / TO_REVIEW / str(name)
        if src.is_file() and _NAME.match(str(name)):
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
        for src in data.get("source") or []:
            f = folder / TO_REVIEW / str(src)
            if not (f.is_file() and _NAME.match(str(src))):
                continue
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
