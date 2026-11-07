"""John's build: Make Deposits and Enter Credit Card Charges as QuickBooks
lays them out — GST/HST on a deposit's other lines (H/E), a saved deposit's
other lines changed in place, cash back, and a card Refund/Credit."""

from app.models.transactions import Transaction, TransactionLine

from tests.test_gst_hst import _canada


def _ledger(db, txn_id):
    return sorted(
        (l.account_id, round(float(l.debit), 2), round(float(l.credit), 2))
        for l in db.query(TransactionLine).filter_by(transaction_id=txn_id)
    )


def _deposit_txn(db, deposit_id):
    return db.get(Transaction, deposit_id) or (
        db.query(Transaction)
        .filter_by(source_type="deposit", source_id=deposit_id)
        .one()
    )


def test_a_deposit_line_coded_h_collects_hst(client, db_session, seed_accounts):
    _canada(client, seed_accounts)
    bank, income, hst = (seed_accounts[n].id for n in ("1000", "4000", "2200"))
    r = client.post(
        "/api/deposits",
        json={
            "deposit_to_account_id": bank,
            "date": "2026-11-07",
            "reference": "Deposit",
            "line_ids": [],
            "other_lines": [
                {
                    "account_id": income,
                    "amount": 100,
                    "received_from": "Smith",
                    "memo": "consulting",
                    "check_number": "77",
                    "tax_code": "H",
                    "tax_amount": 13,
                },
                {"account_id": income, "amount": 50, "memo": "exempt sale"},
            ],
        },
    )
    assert r.status_code in (200, 201), r.text
    dep = r.json()
    assert float(dep["amount"]) == 163.0
    got = client.get(f"/api/deposits/{dep['transaction_id']}").json()
    others = sorted(
        (o["account_id"], float(o["amount"]), o["description"])
        for o in got["other_lines"]
    )
    assert others == sorted(
        [
            (income, 100.0, "Smith — consulting — Chq 77"),
            (hst, 13.0, "GST/HST — Smith — consulting — Chq 77"),
            (income, 50.0, "exempt sale"),
        ]
    )


def test_hst_on_a_deposit_needs_canadian_tax(client, seed_accounts):
    r = client.post(
        "/api/deposits",
        json={
            "deposit_to_account_id": seed_accounts["1000"].id,
            "date": "2026-11-07",
            "line_ids": [],
            "other_lines": [
                {
                    "account_id": seed_accounts["4000"].id,
                    "amount": 100,
                    "tax_code": "H",
                    "tax_amount": 13,
                }
            ],
        },
    )
    assert r.status_code in (400, 422), r.text


def test_a_deposit_is_changed_in_place_with_cash_back(
    client, db_session, seed_accounts
):
    _canada(client, seed_accounts)
    bank, income, hst = (seed_accounts[n].id for n in ("1000", "4000", "2200"))
    petty = seed_accounts["6000"].id
    dep = client.post(
        "/api/deposits",
        json={
            "deposit_to_account_id": bank,
            "date": "2026-11-07",
            "line_ids": [],
            "other_lines": [{"account_id": income, "amount": 200, "memo": "sale"}],
        },
    ).json()
    r = client.put(
        f"/api/deposits/{dep['transaction_id']}",
        json={
            "date": "2026-11-08",
            "reference": "corrected",
            "line_ids": [],
            "other_lines": [
                {
                    "account_id": income,
                    "amount": 200,
                    "memo": "sale",
                    "tax_code": "H",
                    "tax_amount": 26,
                },
                {"account_id": petty, "amount": -20, "memo": "Cash back"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    got = client.get(f"/api/deposits/{dep['transaction_id']}").json()
    assert got["id"] == dep["transaction_id"]
    assert float(got["amount"]) == 206.0
    assert got["date"] == "2026-11-08" and got["reference"] == "corrected"
    others = sorted((o["account_id"], float(o["amount"])) for o in got["other_lines"])
    assert others == sorted([(income, 200.0), (hst, 26.0), (petty, -20.0)])
    # one deposit still, not a second one beside it
    deposits = [
        d for d in client.get("/api/deposits?limit=50").json() if not d.get("voided")
    ]
    assert len(deposits) == 1


def test_a_card_refund_reverses_the_charge_and_its_itc(
    client, db_session, seed_accounts
):
    _canada(client, seed_accounts)
    card = next(a for a in seed_accounts.values() if a.bank_kind == "credit_card")
    supplies, hst = seed_accounts["6000"].id, seed_accounts["2200"].id
    r = client.post(
        "/api/expenses",
        json={
            "date": "2026-11-07",
            "payee": "Staples",
            "paid_from_account_id": card.id,
            "amount": "56.50",
            "is_credit": True,
            "lines": [
                {
                    "account_id": supplies,
                    "amount": "50",
                    "tax_code": "H",
                    "tax_amount": "6.50",
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    x = r.json()
    assert x["is_credit"] is True and x["amount"] == 56.5
    assert _ledger(db_session, x["id"]) == sorted(
        [(card.id, 56.5, 0.0), (supplies, 0.0, 50.0), (hst, 0.0, 6.5)]
    )
    rows = client.get("/api/cc-charges").json()
    assert [(row["id"], row["amount"], row["account_name"]) for row in rows] == [
        (x["id"], -56.5, seed_accounts["6000"].name)
    ]
    # it opens as a refund and saves back as one
    again = client.get(f"/api/expenses/{x['id']}").json()
    assert again["is_credit"] is True
    assert sorted((ln["account_id"], ln["amount"]) for ln in again["lines"]) == sorted(
        [(supplies, 50.0), (hst, 6.5)]
    )
