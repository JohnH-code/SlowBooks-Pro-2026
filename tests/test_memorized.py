"""Memorized transactions: memorize an entered cheque, bill, deposit or
journal entry, enter it again on its schedule, with reminders."""

from datetime import date

from app.models.transactions import Transaction
from app.services import memorized as svc


def _cheque(client, seed_accounts, **extra):
    body = {
        "date": "2026-09-01", "payee": "Rogers", "paid_from_account_id": seed_accounts["1000"].id,
        "reference": "500",
        "lines": [
            {"account_id": seed_accounts["6000"].id, "amount": "100.00", "memo": "internet"},
            {"account_id": seed_accounts["6100"].id, "amount": "13.00", "memo": "HST"},
        ],
    }
    body.update(extra)
    r = client.post("/api/expenses", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_advance():
    assert svc.advance(date(2026, 1, 31), "monthly", 31) == date(2026, 2, 28)
    assert svc.advance(date(2026, 2, 28), "monthly", 31) == date(2026, 3, 31)
    assert svc.advance(date(2026, 1, 15), "quarterly") == date(2026, 4, 15)
    assert svc.advance(date(2026, 1, 15), "weekly") == date(2026, 1, 22)
    assert svc.advance(date(2026, 1, 15), "never") is None


def test_memorize_a_cheque_and_enter_it(client, db_session, seed_accounts):
    exp = _cheque(client, seed_accounts)
    m = client.post("/api/memorized/from-transaction", json={
        "transaction_id": exp["id"], "name": "Rogers internet", "frequency": "monthly",
    })
    assert m.status_code == 201, m.text
    m = m.json()
    assert m["kind"] == "expense" and m["next_date"] == "2026-10-01" and m["amount"] == 113.0

    # due from its date (no days in advance)
    assert client.get("/api/memorized/due").json() != [] or date.today() < date(2026, 10, 1)

    r = client.post(f"/api/memorized/{m['id']}/enter", json={})
    assert r.status_code == 200, r.text
    new = client.get(f"/api/expenses/{r.json()['id']}").json()
    assert new["date"] == "2026-10-01"
    assert new["payee"] == "Rogers" and new["amount"] == 113.0
    assert new["reference"] == "501"  # the next cheque number
    assert [l["memo"] for l in new["lines"]] == ["internet", "HST"]
    after = r.json()["memorized"]
    assert after["next_date"] == "2026-11-01" and after["times_entered"] == 1

    skipped = client.post(f"/api/memorized/{m['id']}/skip").json()
    assert skipped["next_date"] == "2026-12-01"


def test_one_line_amount_can_change(client, seed_accounts):
    r = client.post("/api/expenses", json={
        "date": "2026-09-05", "payee": "Hydro", "paid_from_account_id": seed_accounts["1000"].id,
        "expense_account_id": seed_accounts["6000"].id, "amount": "80",
    })
    m = client.post("/api/memorized/from-transaction", json={"transaction_id": r.json()["id"], "frequency": "never"}).json()
    assert m["next_date"] is None and m["name"] == "Hydro"
    e = client.post(f"/api/memorized/{m['id']}/enter", json={"date": "2026-10-05", "amount": 91.25}).json()
    x = client.get(f"/api/expenses/{e['id']}").json()
    assert x["amount"] == 91.25 and x["date"] == "2026-10-05"
    assert x["expense_account_name"] == seed_accounts["6000"].name


def test_journal_and_deposit_patterns(client, db_session, seed_accounts):
    je = client.post("/api/journal", json={
        "date": "2026-09-30", "description": "Amortization",
        "lines": [
            {"account_id": seed_accounts["6000"].id, "debit": "250.00"},
            {"account_id": seed_accounts["1000"].id, "credit": "250.00"},
        ],
    })
    assert je.status_code == 201, je.text
    m = client.post("/api/memorized/from-transaction", json={"transaction_id": je.json()["id"], "frequency": "quarterly"}).json()
    assert m["kind"] == "journal" and m["next_date"] == "2026-12-30"
    e = client.post(f"/api/memorized/{m['id']}/enter", json={}).json()
    assert db_session.query(Transaction).filter_by(id=e["id"]).one().date == date(2026, 12, 30)

    dep = client.post("/api/deposits", json={
        "deposit_to_account_id": seed_accounts["1000"].id, "date": "2026-09-03",
        "other_lines": [{"account_id": seed_accounts["4900"].id, "amount": "1200", "received_from": "Tenant", "memo": "rent"}],
    })
    assert dep.status_code == 200, dep.text
    m = client.post("/api/memorized/from-transaction", json={"transaction_id": dep.json()["transaction_id"]}).json()
    assert m["kind"] == "deposit" and m["amount"] == 1200.0
    e = client.post(f"/api/memorized/{m['id']}/enter", json={}).json()
    d = client.get(f"/api/deposits/{e['id']}").json()
    assert float(d["amount"]) == 1200.0


def test_bill_pattern_and_auto_enter(client, db_session, seed_accounts):
    vendor = client.post("/api/vendors", json={"name": "Landlord"}).json()
    bill = client.post("/api/bills", json={
        "vendor_id": vendor["id"], "bill_number": "R-1", "date": "2026-01-01",
        "lines": [{"account_id": seed_accounts["6000"].id, "description": "rent", "quantity": 1, "rate": 2000}],
    }).json()
    txn = db_session.query(Transaction).filter_by(source_type="bill", source_id=bill["id"]).one()
    m = client.post("/api/memorized/from-transaction", json={
        "transaction_id": txn.id, "frequency": "monthly", "action": "auto", "next_date": "2026-02-01", "remaining": 2,
    }).json()
    entered = client.post("/api/memorized/auto-enter").json()["entered"]
    # both remaining months were entered, then the schedule ended
    assert [e["date"] for e in entered if e["memorized_id"] == m["id"]] == ["2026-02-01", "2026-03-01"]
    after = next(x for x in client.get("/api/memorized").json() if x["id"] == m["id"])
    assert after["remaining"] == 0 and after["next_date"] is None
    totals = sorted(float(b["total"]) for b in client.get("/api/bills").json())
    assert totals == [2000.0, 2000.0, 2000.0]


def test_reminders_respect_days_in_advance(client, seed_accounts):
    exp = _cheque(client, seed_accounts)
    far = date.today().replace(year=date.today().year + 1).isoformat()
    m = client.post("/api/memorized/from-transaction", json={"transaction_id": exp["id"], "next_date": far}).json()
    assert all(x["id"] != m["id"] for x in client.get("/api/memorized/due").json())
    client.put(f"/api/memorized/{m['id']}", json={"next_date": date.today().isoformat()})
    assert any(x["id"] == m["id"] for x in client.get("/api/memorized/due").json())
    client.put(f"/api/memorized/{m['id']}", json={"action": "none"})
    assert all(x["id"] != m["id"] for x in client.get("/api/memorized/due").json())
    assert client.delete(f"/api/memorized/{m['id']}").status_code == 200


def test_edit_the_pattern(client, seed_accounts):
    exp = _cheque(client, seed_accounts)
    m = client.post("/api/memorized/from-transaction", json={"transaction_id": exp["id"]}).json()
    payload = {**m["payload"], "payee": "Rogers Wireless",
               "lines": [{"account_id": seed_accounts["6000"].id, "amount": "150.00", "memo": "plan"}]}
    r = client.put(f"/api/memorized/{m['id']}", json={"payload": payload, "name": "Rogers"})
    assert r.status_code == 200, r.text
    assert r.json()["amount"] == 150.0 and r.json()["name"] == "Rogers"
    e = client.post(f"/api/memorized/{m['id']}/enter", json={}).json()
    x = client.get(f"/api/expenses/{e['id']}").json()
    assert x["payee"] == "Rogers Wireless" and x["amount"] == 150.0
    # a journal entry that doesn't balance is refused
    je = client.post("/api/journal", json={"date": "2026-09-30", "description": "x", "lines": [
        {"account_id": seed_accounts["6000"].id, "debit": "10.00"},
        {"account_id": seed_accounts["1000"].id, "credit": "10.00"}]}).json()
    mj = client.post("/api/memorized/from-transaction", json={"transaction_id": je["id"]}).json()
    bad = {**mj["payload"], "lines": [{"account_id": seed_accounts["6000"].id, "debit": "10.00", "credit": "0.00"}]}
    assert client.put(f"/api/memorized/{mj['id']}", json={"payload": bad}).status_code == 422
