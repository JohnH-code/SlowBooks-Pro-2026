"""Canadian GST/HST: one account collects the tax on sales and claims it back
on purchases, and the return for any filing period comes from the ledger."""

from datetime import date

from app.models.transactions import Transaction, TransactionLine
from app.services import hst


def _canada(client, seed_accounts, freq="quarterly"):
    r = client.put(
        "/api/settings",
        json={
            "sales_tax_system": "canada",
            "hst_account_id": str(seed_accounts["2200"].id),
            "hst_rate": "13",
            "hst_filing_frequency": freq,
            "hst_year_end_month": "12",
            "default_tax_rate": "13",
        },
    )
    assert r.status_code == 200, r.text


def _lines(db, txn_id):
    return {
        (l.account_id, float(l.debit), float(l.credit))
        for l in db.query(TransactionLine).filter_by(transaction_id=txn_id)
    }


def test_periods_follow_the_fiscal_year():
    q = hst.periods("quarterly", 12, date(2026, 2, 10), date(2026, 8, 1))
    assert q == [
        (date(2026, 1, 1), date(2026, 3, 31)),
        (date(2026, 4, 1), date(2026, 6, 30)),
        (date(2026, 7, 1), date(2026, 9, 30)),
    ]
    march = hst.periods("quarterly", 3, date(2026, 5, 1), date(2026, 5, 1))
    assert march == [(date(2026, 4, 1), date(2026, 6, 30))]
    assert hst.periods("annual", 6, date(2026, 1, 1), date(2026, 1, 1)) == [
        (date(2025, 7, 1), date(2026, 6, 30))
    ]
    assert hst.periods("monthly", 12, date(2026, 2, 3), date(2026, 2, 3)) == [
        (date(2026, 2, 1), date(2026, 2, 28))
    ]


def test_hst_on_sales_and_purchases_and_the_return(
    client, db_session, seed_accounts, seed_customer
):
    _canada(client, seed_accounts)
    tax = seed_accounts["2200"].id
    bank = seed_accounts["1000"].id

    inv = client.post(
        "/api/invoices",
        json={
            "customer_id": seed_customer.id,
            "date": "2026-07-10",
            "tax_rate": "0.13",
            "lines": [{"description": "advisory", "quantity": 1, "rate": 1000}],
        },
    )
    assert inv.status_code in (200, 201), inv.text
    assert float(inv.json()["tax_amount"]) == 130.0

    vendor = client.post("/api/vendors", json={"name": "Bell"}).json()
    bill = client.post(
        "/api/bills",
        json={
            "vendor_id": vendor["id"],
            "bill_number": "B1",
            "date": "2026-07-15",
            "tax_rate": "0.13",
            "lines": [
                {
                    "account_id": seed_accounts["6000"].id,
                    "description": "phone",
                    "quantity": 1,
                    "rate": 200,
                }
            ],
        },
    )
    assert bill.status_code in (200, 201), bill.text
    btx = (
        db_session.query(Transaction)
        .filter_by(source_type="bill", source_id=bill.json()["id"])
        .one()
    )
    # the expense is the net amount; the tax is an input tax credit
    assert (seed_accounts["6000"].id, 200.0, 0.0) in _lines(db_session, btx.id)
    assert (tax, 26.0, 0.0) in _lines(db_session, btx.id)

    # a receipt's total with the HST in it
    exp = client.post(
        "/api/expenses",
        json={
            "date": "2026-08-02",
            "payee": "Staples",
            "paid_from_account_id": bank,
            "expense_account_id": seed_accounts["6000"].id,
            "amount": "113.00",
            "tax_code": "H",
            "amounts_include_tax": True,
        },
    )
    assert exp.status_code == 201, exp.text
    assert exp.json()["amount"] == 113.0
    assert (tax, 13.0, 0.0) in _lines(db_session, exp.json()["id"])
    assert (seed_accounts["6000"].id, 100.0, 0.0) in _lines(
        db_session, exp.json()["id"]
    )

    # paying the Receiver General is not on the return
    paid = client.post(
        "/api/expenses",
        json={
            "date": "2026-07-28",
            "payee": "Receiver General",
            "paid_from_account_id": bank,
            "expense_account_id": tax,
            "amount": "500.00",
        },
    )
    assert paid.status_code == 201, paid.text

    r = client.get(
        "/api/reports/gst-hst-return",
        params={"start_date": "2026-07-01", "end_date": "2026-09-30"},
    ).json()
    assert r["enabled"]
    assert r["line_103"] == 130.0
    assert r["line_106"] == 39.0
    assert r["line_109"] == 91.0
    assert r["line_101"] == 1000.0
    assert r["payments_in_period"] == 500.0
    assert r["counts"] == {"sale": 1, "purchase": 2, "payment": 1}

    periods = client.get("/api/reports/gst-hst-return/periods").json()
    assert periods["enabled"] and periods["frequency"] == "quarterly"
    assert periods["due"] is not None


def test_a_us_company_is_unchanged(client, db_session, seed_accounts):
    vendor = client.post("/api/vendors", json={"name": "Acme"}).json()
    bill = client.post(
        "/api/bills",
        json={
            "vendor_id": vendor["id"],
            "bill_number": "B1",
            "date": "2026-07-15",
            "tax_rate": "0.10",
            "lines": [
                {"account_id": seed_accounts["6000"].id, "quantity": 1, "rate": 100}
            ],
        },
    )
    btx = (
        db_session.query(Transaction)
        .filter_by(source_type="bill", source_id=bill.json()["id"])
        .one()
    )
    assert (seed_accounts["6000"].id, 110.0, 0.0) in _lines(db_session, btx.id)
    r = client.post(
        "/api/expenses",
        json={
            "date": "2026-08-02",
            "paid_from_account_id": seed_accounts["1000"].id,
            "expense_account_id": seed_accounts["6000"].id,
            "amount": "10",
            "tax_code": "H",
        },
    )
    assert r.status_code == 400
    assert (
        client.get(
            "/api/reports/gst-hst-return",
            params={"start_date": "2026-01-01", "end_date": "2026-12-31"},
        ).json()["enabled"]
        is False
    )


def test_cheque_quickfill_payees_and_next_number(client, seed_accounts):
    bank = seed_accounts["1000"].id
    first = client.post(
        "/api/expenses",
        json={
            "date": "2026-08-01",
            "payee": "Alison St. Hill",
            "paid_from_account_id": bank,
            "reference": "426",
            "lines": [
                {
                    "account_id": seed_accounts["6000"].id,
                    "amount": "100",
                    "memo": "Nespresso",
                },
                {"account_id": seed_accounts["6100"].id, "amount": "15.90"},
            ],
        },
    )
    assert first.status_code == 201, first.text
    assert "Alison St. Hill" in client.get("/api/expenses/payees").json()
    last = client.get(
        "/api/expenses/quickfill", params={"payee": "Alison St. Hill"}
    ).json()
    assert [(l["account_id"], l["amount"], l["memo"]) for l in last["lines"]] == [
        (seed_accounts["6000"].id, 100.0, "Nespresso"),
        (seed_accounts["6100"].id, 15.9, ""),
    ]
    assert (
        client.get("/api/expenses/quickfill", params={"payee": "Nobody"}).json() is None
    )
    assert client.get(
        "/api/expenses/next-number", params={"account_id": bank}
    ).json() == {"number": "427"}
    card = next(a for a in seed_accounts.values() if a.bank_kind == "credit_card")
    assert client.get(
        "/api/expenses/next-number", params={"account_id": card.id}
    ).json() == {"number": None}


def test_clean_up_unused_accounts(client, db_session, seed_accounts):
    from app.models.accounts import Account

    parent = client.post(
        "/api/accounts",
        json={"name": "Old group", "account_number": "6990", "account_type": "expense"},
    ).json()
    child = client.post(
        "/api/accounts",
        json={
            "name": "Old leaf",
            "account_number": "6991",
            "account_type": "expense",
            "parent_id": parent["id"],
        },
    ).json()
    data = client.get("/api/accounts/unused").json()
    ids = {a["id"] for a in data["delete"]}
    assert {parent["id"], child["id"]} <= ids
    # used accounts and control accounts are not offered
    assert seed_accounts["1000"].id not in ids
    assert seed_accounts["2200"].id not in ids
    assert any(a["account_number"] == "2200" for a in data["kept"])
    r = client.post(
        "/api/accounts/remove-unused", json={"account_ids": [parent["id"], child["id"]]}
    ).json()
    assert r == {"deleted": 2}
    assert (
        db_session.query(Account)
        .filter(Account.id.in_([parent["id"], child["id"]]))
        .count()
        == 0
    )


def test_clean_up_hands_checking_to_the_real_bank(client, db_session, seed_accounts):
    from app.models.accounts import Account

    rbc = client.post(
        "/api/accounts",
        json={
            "name": "RBC - Can $",
            "account_number": "1050",
            "account_type": "asset",
            "bank_kind": "bank",
        },
    ).json()
    assert (
        client.post(
            "/api/expenses",
            json={
                "date": "2026-08-01",
                "payee": "X",
                "paid_from_account_id": rbc["id"],
                "expense_account_id": seed_accounts["6000"].id,
                "amount": "5",
            },
        ).status_code
        == 201
    )
    data = client.get("/api/accounts/unused").json()
    checking = next(a for a in data["kept"] if a["account_number"] == "1000")
    assert checking["replace_with"][0]["id"] == rbc["id"]
    r = client.post(
        "/api/accounts/remove-unused",
        json={"account_ids": [], "replace": {str(checking["id"]): rbc["id"]}},
    )
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert db_session.get(Account, checking["id"]) is None
    assert db_session.get(Account, rbc["id"]).account_number == "1000"
    # the default bank for a bill payment is now RBC
    from app.services.accounting import get_checking_account_id

    assert get_checking_account_id(db_session) == rbc["id"]


def test_card_expenses_show_on_credit_card_charges(client, seed_accounts):
    card = next(a for a in seed_accounts.values() if a.bank_kind == "credit_card")
    r = client.post(
        "/api/expenses",
        json={
            "date": "2026-08-01",
            "payee": "Esso",
            "paid_from_account_id": card.id,
            "lines": [
                {"account_id": seed_accounts["6000"].id, "amount": "40"},
                {"account_id": seed_accounts["6100"].id, "amount": "5.20"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    bank = client.post(
        "/api/expenses",
        json={
            "date": "2026-08-02",
            "payee": "Bell",
            "paid_from_account_id": seed_accounts["1000"].id,
            "expense_account_id": seed_accounts["6000"].id,
            "amount": "10",
        },
    ).json()
    rows = client.get("/api/cc-charges").json()
    assert [
        (x["kind"], x["description"], x["amount"], x["account_name"]) for x in rows
    ] == [("expense", "Esso", 45.2, "Split (2 accounts)")]
    assert all(x["id"] != bank["id"] for x in rows)
