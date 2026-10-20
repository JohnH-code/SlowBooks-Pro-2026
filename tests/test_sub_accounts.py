"""Sub-accounts: chosen on the account form, and shown on the P&L and
Balance Sheet under their parents with "- Other" and "Total" lines, as
QuickBooks does."""


def _acct(client, name, number, kind="expense", parent=None):
    r = client.post("/api/accounts", json={"name": name, "account_number": number, "account_type": kind, "parent_id": parent})
    assert r.status_code == 201, r.text
    return r.json()


def _spend(client, seed_accounts, account_id, amount):
    r = client.post("/api/expenses", json={
        "date": "2026-03-01", "payee": "X", "paid_from_account_id": seed_accounts["1000"].id,
        "expense_account_id": account_id, "amount": str(amount)})
    assert r.status_code == 201, r.text


def test_profit_and_loss_nests_sub_accounts(client, seed_accounts):
    auto = _acct(client, "Auto", "6770")
    fuel = _acct(client, "Fuel", "6771", parent=auto["id"])
    ins = _acct(client, "Auto Insurance", "6772", parent=auto["id"])
    _spend(client, seed_accounts, fuel["id"], 100)
    _spend(client, seed_accounts, ins["id"], 250)
    _spend(client, seed_accounts, auto["id"], 30)
    pl = client.get("/api/reports/profit-loss", params={"start_date": "2026-01-01", "end_date": "2026-12-31"}).json()
    tree = pl["tree"]["expenses"]
    shape = [(e["kind"], e["label"], e["depth"], e["amount"]) for e in tree if "Auto" in e["label"] or e["label"] == "Fuel"]
    assert shape == [
        ("header", "Auto", 0, None),
        ("account", "Fuel", 1, 100.0),
        ("account", "Auto Insurance", 1, 250.0),
        ("other", "Auto - Other", 1, 30.0),
        ("total", "Total Auto", 0, 380.0),
    ]
    # the section total is unchanged
    assert pl["total_expenses"] == 380.0
    pdf = client.get("/api/reports/profit-loss/pdf", params={"start_date": "2026-01-01", "end_date": "2026-12-31"})
    assert pdf.status_code == 200


def test_parent_with_no_postings_still_heads_its_sub_accounts(client, seed_accounts):
    util = _acct(client, "Utilities group", "6880")
    hydro = _acct(client, "Hydro", "6881", parent=util["id"])
    _spend(client, seed_accounts, hydro["id"], 75)
    bs = client.get("/api/reports/balance-sheet", params={"as_of_date": "2026-12-31"}).json()
    assert "tree" in bs and bs["tree"]["assets"]
    pl = client.get("/api/reports/profit-loss", params={"start_date": "2026-01-01", "end_date": "2026-12-31", "compare": "prior_year"}).json()
    labels = [(e["kind"], e["label"]) for e in pl["tree"]["expenses"]]
    assert ("header", "Utilities group") in labels and ("total", "Total Utilities group") in labels
    assert not any(l == "Utilities group - Other" for _, l in labels)


def test_parent_rules(client):
    inc = _acct(client, "Fees", "4100", kind="income")
    exp = _acct(client, "Travel", "6900")
    r = client.post("/api/accounts", json={"name": "Air", "account_number": "6901", "account_type": "expense", "parent_id": inc["id"]})
    assert r.status_code == 400 and "same type" in r.json()["detail"]
    air = _acct(client, "Air", "6902", parent=exp["id"])
    # no loops
    r = client.put(f"/api/accounts/{exp['id']}", json={"parent_id": air["id"]})
    assert r.status_code == 400
    # move to top level
    assert client.put(f"/api/accounts/{air['id']}", json={"parent_id": None}).json()["parent_id"] is None
