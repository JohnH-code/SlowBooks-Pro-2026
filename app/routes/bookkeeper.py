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
KINDS = ("bill", "expense", "bill_payment")
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
