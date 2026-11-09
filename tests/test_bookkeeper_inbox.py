"""John's build: the Bookkeeper inbox. The agent bookkeeper leaves what it
prepared (names, not ids) in the company's bookkeeper folder; the inbox
lists it with the vendor and accounts found, the screen enters each item
through the ordinary routes, and the statement is attached to it and filed
under Done once the file's items are all done. Nothing is posted by the
inbox itself."""

import json
from datetime import date
from pathlib import Path

import pytest

from app.models.attachments import Attachment
from app.models.settings import Settings

JS = Path(__file__).resolve().parents[1] / "app" / "static" / "js"


@pytest.fixture
def folder(tmp_path, TestSession):
    f = tmp_path / "Bookkeeper"
    (f / "To review").mkdir(parents=True)
    with TestSession() as s:
        s.add(Settings(key="bookkeeper_folder", value=str(f)))
        s.commit()
    return f


def _drop(folder, name, items, source=("statement.pdf",)):
    for s in source:
        (folder / "To review" / s).write_bytes(b"%PDF-1.4 statement")
    (folder / "To review" / name).write_text(
        json.dumps({"title": name, "source": list(source), "items": items})
    )


def _vendor(client, name):
    r = client.post("/api/vendors", json={"name": name})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_no_folder_no_inbox(client):
    assert client.get("/api/bookkeeper/inbox").json() == {"folder": None, "files": []}


def test_a_prepared_bill_is_listed_with_its_vendor_and_accounts_found(
    client, seed_accounts, folder
):
    vid = _vendor(client, "Oakville Club")
    _drop(
        folder,
        "club.json",
        [
            {
                "id": "1",
                "kind": "bill",
                "vendor": "oakville club",
                "date": "2026-10-31",
                "number": "S209-2026-10",
                "lines": [
                    {"account": "Advertising & Marketing", "amount": "42.50"},
                    {"account": "Office Supplies", "amount": "361.12"},
                    {"account": "No Such Account", "amount": "1"},
                ],
                "questions": ["Is the guest fee Promotion?"],
            }
        ],
    )
    box = client.get("/api/bookkeeper/inbox").json()
    (f,) = box["files"]
    assert f["source"] == ["statement.pdf"]
    (it,) = f["items"]
    assert it["vendor_id"] == vid
    assert [ln["account_id"] for ln in it["lines"]] == [
        seed_accounts["6000"].id,
        seed_accounts["6400"].id,
        None,
    ]
    assert it["total"] == 404.62
    assert it["problems"] == ["Account not found: No Such Account"]
    assert it["questions"] == ["Is the guest fee Promotion?"]
    # the statement can be looked at; nothing outside To review can
    assert client.get("/api/bookkeeper/source/statement.pdf").status_code == 200
    assert client.get("/api/bookkeeper/source/club.json").status_code == 404
    assert client.get("/api/bookkeeper/source/..%2F..%2Fetc").status_code == 404


def test_entering_attaches_the_statement_and_files_it_under_done(
    client, seed_accounts, folder, TestSession
):
    vid = _vendor(client, "American Express")
    _drop(
        folder,
        "amex.json",
        [
            {
                "id": "1",
                "kind": "expense",
                "vendor": "American Express",
                "date": "2026-10-12",
                "paid_from": "Credit Card",
                "lines": [{"account": "Auto & Truck Expense", "amount": "20.00"}],
            },
            {
                "id": "2",
                "kind": "expense",
                "vendor": "American Express",
                "date": "2026-10-13",
                "paid_from": "Credit Card",
                "lines": [{"account": "Office Supplies", "amount": "5.00"}],
            },
        ],
        source=("Amex Oct.pdf",),
    )
    it, second = client.get("/api/bookkeeper/inbox").json()["files"][0]["items"]
    # the screen posts it through the ordinary route ...
    r = client.post(
        "/api/expenses",
        json={
            "date": it["date"],
            "vendor_id": vid,
            "paid_from_account_id": it["paid_from_id"],
            "amount": 20.0,
            "lines": [{"account_id": it["lines"][0]["account_id"], "amount": 20.0}],
        },
    )
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    # ... and tells the inbox
    r = client.post(
        "/api/bookkeeper/inbox/amex.json/1/entered",
        json={"entity_type": "expense", "entity_id": eid},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"attached": ["Amex Oct.pdf"], "filed": False}
    with TestSession() as s:
        (a,) = s.query(Attachment).filter_by(entity_type="expense", entity_id=eid).all()
        assert a.filename == "Amex Oct.pdf"
    # entered once only; the rest still waits
    again = client.post(
        "/api/bookkeeper/inbox/amex.json/1/entered",
        json={"entity_type": "expense", "entity_id": eid},
    )
    assert again.status_code == 409
    (left,) = client.get("/api/bookkeeper/inbox").json()["files"][0]["items"]
    assert left["id"] == "2"
    # the last one dismissed: the file and its statement go to Done
    r = client.post("/api/bookkeeper/inbox/amex.json/2/dismiss")
    assert r.json() == {"filed": True}
    month = folder / "Done" / date.today().strftime("%Y-%m")
    assert sorted(p.name for p in month.iterdir()) == ["Amex Oct.pdf", "amex.json"]
    assert not list((folder / "To review").iterdir())
    kept = json.loads((month / "amex.json").read_text())
    assert kept["items"][0]["entered"]["id"] == eid
    assert kept["items"][1]["dismissed"]


def test_a_payment_names_the_bill_it_pays(client, seed_accounts, folder):
    vid = _vendor(client, "Oakville Golf Club")
    _drop(
        folder,
        "pay.json",
        [
            {
                "id": "p",
                "kind": "bill_payment",
                "vendor": "Oakville Golf Club",
                "date": "2026-11-08",
                "bill_number": "H242-2026-10",
                "amount": "338.02",
                "paid_from": "Checking",
                "reference": "EFT",
            }
        ],
    )
    (it,) = client.get("/api/bookkeeper/inbox").json()["files"][0]["items"]
    assert it["problems"] == ["Bill H242-2026-10 isn't entered yet"]
    r = client.post(
        "/api/bills",
        json={
            "vendor_id": vid,
            "bill_number": "H242-2026-10",
            "date": "2026-10-31",
            "lines": [{"account_id": seed_accounts["6400"].id, "amount": 338.02}],
        },
    )
    assert r.status_code == 201, r.text
    (it,) = client.get("/api/bookkeeper/inbox").json()["files"][0]["items"]
    assert it["problems"] == [] and it["bill_id"] == r.json()["id"]
    assert it["paid_from_id"] == seed_accounts["1000"].id


def test_the_screen_is_there():
    js = (JS / "bookkeeper_inbox.js").read_text(encoding="utf-8")
    for url in (
        "'/bills'",
        "'/expenses'",
        "'/bill-payments'",
        "/entered`",
        "/dismiss`",
    ):
        assert url in js, url
    index = (Path(__file__).resolve().parents[1] / "index.html").read_text()
    assert "/static/js/bookkeeper_inbox.js" in index
    assert 'href="#/bookkeeper"' in index


def test_a_folder_typed_from_the_top_of_the_disk_is_found_in_home(
    tmp_path, monkeypatch
):
    from app.routes.bookkeeper import find_folder

    monkeypatch.setenv("HOME", str(tmp_path))
    real = tmp_path / "DATA" / "Alderella" / "Bookkeeper"
    real.mkdir(parents=True)
    assert find_folder("~/DATA/Alderella/Bookkeeper") == real
    assert find_folder("/DATA/Alderella/Bookkeeper") == real
    assert find_folder("DATA/Alderella/Bookkeeper") == real
    assert find_folder("/nowhere/at/all") == Path("/nowhere/at/all")


def test_each_row_shows_its_accounts_and_hst():
    js = (JS / "bookkeeper_inbox.js").read_text(encoding="utf-8")
    assert '<th scope="col">Account</th>' in js
    assert '<th scope="col" class="amount">HST</th>' in js
    assert "this._accountsOf(it)" in js and "this._hstOf(it)" in js
    assert "No HST" in js


def _spend(client, accts, vid, day, amount, ref=None):
    r = client.post(
        "/api/expenses",
        json={
            "date": day,
            "vendor_id": vid,
            "paid_from_account_id": accts["1000"].id,
            "amount": amount,
            "reference": ref,
            "lines": [{"account_id": accts["6400"].id, "amount": amount}],
        },
    )
    assert r.status_code == 201, r.text


def test_a_statement_is_matched_and_starts_a_reconciliation(
    client, seed_accounts, folder, TestSession
):
    from app.models.banking import Reconciliation
    from app.models.transactions import TransactionLine

    vid = _vendor(client, "Staples")
    _spend(client, seed_accounts, vid, "2026-11-03", 40.00, "1043")
    _spend(client, seed_accounts, vid, "2026-11-05", 12.50)
    _spend(client, seed_accounts, vid, "2026-11-28", 99.00)  # not cleared yet
    item = {
        "id": "1",
        "kind": "reconciliation",
        "account": "Checking",
        "statement_date": "2026-11-30",
        "opening_balance": "0.00",
        "closing_balance": "-64.50",
        "lines": [
            {
                "date": "2026-11-06",
                "description": "Cheque 1043",
                "amount": "-40.00",
                "cheque": "1043",
            },
            {"date": "2026-11-05", "description": "Staples", "amount": "-12.50"},
            {"date": "2026-11-30", "description": "Service charge", "amount": "-12.00"},
        ],
    }
    _drop(folder, "rbc.json", [item])
    (it,) = client.get("/api/bookkeeper/inbox").json()["files"][0]["items"]
    assert len(it["matched"]) == 2 and len(it["outstanding"]) == 1
    assert it["problems"] == ["Not in the books: 2026-11-30 Service charge -12.00"]
    # refused until the service charge is in the books
    r = client.post("/api/bookkeeper/inbox/rbc.json/1/reconcile")
    assert r.status_code == 400
    _spend(client, seed_accounts, vid, "2026-11-30", 12.00)
    (it,) = client.get("/api/bookkeeper/inbox").json()["files"][0]["items"]
    assert it["problems"] == [] and it["difference"] == 0
    r = client.post("/api/bookkeeper/inbox/rbc.json/1/reconcile")
    assert r.status_code == 200, r.text
    rid = r.json()["reconciliation_id"]
    s = client.get(f"/api/banking/reconciliations/{rid}/transactions").json()
    assert abs(s["difference"]) < 0.005
    assert sum(1 for t in s["transactions"] if t["reconciled"]) == 3
    with TestSession() as db:
        assert db.get(Reconciliation, rid).status.value == "in_progress"
        assert (
            db.query(TransactionLine)
            .filter(TransactionLine.reconciliation_id == rid)
            .count()
            == 0
        )
