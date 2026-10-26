"""A cheque split across several accounts (QuickBooks' Write Cheques), and
Make Deposits' other half: money deposited straight from another account."""

from decimal import Decimal

from app.models.transactions import Transaction


def _split(client, seed_accounts, lines, **extra):
    body = {
        "date": "2026-09-02",
        "payee": "KPMG",
        "paid_from_account_id": seed_accounts["1000"].id,
        "reference": "426",
        "lines": lines,
    }
    body.update(extra)
    return client.post("/api/expenses", json=body)


def test_split_expense_posts_every_line(client, db_session, seed_accounts):
    r = _split(
        client,
        seed_accounts,
        [
            {
                "account_id": seed_accounts["6000"].id,
                "amount": "800.00",
                "memo": "audit fee",
            },
            {"account_id": seed_accounts["2200"].id, "amount": "104.00", "memo": "HST"},
        ],
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["amount"] == 904.0
    assert body["expense_account_name"] == "Split (2 accounts)"
    assert body["paid_from_account_name"] == seed_accounts["1000"].name
    assert [(l["account_id"], l["amount"], l["memo"]) for l in body["lines"]] == [
        (seed_accounts["6000"].id, 800.0, "audit fee"),
        (seed_accounts["2200"].id, 104.0, "HST"),
    ]
    txn = db_session.query(Transaction).filter_by(id=body["id"]).one()
    assert txn.source_type == "expense"
    assert (
        sum(l.debit for l in txn.lines)
        == sum(l.credit for l in txn.lines)
        == Decimal("904.00")
    )

    again = client.get(f"/api/expenses/{body['id']}").json()
    assert again["lines"] == body["lines"]


def test_split_line_can_be_a_credit(client, seed_accounts):
    r = _split(
        client,
        seed_accounts,
        [
            {"account_id": seed_accounts["6000"].id, "amount": "500.00"},
            {
                "account_id": seed_accounts["4900"].id,
                "amount": "-50.00",
                "memo": "refund netted",
            },
        ],
    )
    assert r.status_code == 201, r.text
    assert r.json()["amount"] == 450.0


def test_split_refusals(client, seed_accounts):
    bank = seed_accounts["1000"].id
    assert (
        _split(client, seed_accounts, [{"account_id": bank, "amount": "5"}]).status_code
        == 400
    )
    assert (
        _split(
            client,
            seed_accounts,
            [
                {"account_id": seed_accounts["6000"].id, "amount": "10"},
                {"account_id": seed_accounts["4900"].id, "amount": "-20"},
            ],
        ).status_code
        == 400
    )
    r = _split(
        client,
        seed_accounts,
        [{"account_id": seed_accounts["6000"].id, "amount": "5"}],
        expense_account_id=seed_accounts["6000"].id,
        amount="5",
    )
    assert r.status_code == 400


def test_split_expense_voids_whole(client, db_session, seed_accounts):
    body = _split(
        client,
        seed_accounts,
        [
            {"account_id": seed_accounts["6000"].id, "amount": "800.00"},
            {"account_id": seed_accounts["2200"].id, "amount": "104.00"},
        ],
    ).json()
    r = client.post(f"/api/expenses/{body['id']}/void")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "void"
    void = (
        db_session.query(Transaction)
        .filter_by(source_type="expense_void", source_id=body["id"])
        .one()
    )
    assert len(void.lines) == 3


def test_single_account_expense_unchanged(client, seed_accounts):
    r = client.post(
        "/api/expenses",
        json={
            "date": "2026-09-02",
            "expense_account_id": seed_accounts["6000"].id,
            "paid_from_account_id": seed_accounts["1000"].id,
            "amount": "30.30",
            "memo": "lunch",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["expense_account_name"] == seed_accounts["6000"].name
    assert body["memo"] == "lunch"
    assert len(body["lines"]) == 1


def test_deposit_straight_from_other_accounts(client, db_session, seed_accounts):
    r = client.post(
        "/api/deposits",
        json={
            "deposit_to_account_id": seed_accounts["1000"].id,
            "date": "2026-09-03",
            "other_lines": [
                {
                    "account_id": seed_accounts["4900"].id,
                    "amount": "5914.35",
                    "received_from": "T&C Holdings",
                    "memo": "distribution",
                },
                {
                    "account_id": seed_accounts["6200"].id,
                    "amount": "-14.35",
                    "memo": "bank fee",
                },
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["amount"] == 5900.0
    d = client.get(f"/api/deposits/{r.json()['transaction_id']}").json()
    assert float(d["amount"]) == 5900.0
    assert d["account_id"] == seed_accounts["1000"].id
    assert [
        (o["account_id"], float(o["amount"]), o["description"])
        for o in d["other_lines"]
    ] == [
        (seed_accounts["4900"].id, 5914.35, "T&C Holdings — distribution"),
        (seed_accounts["6200"].id, -14.35, "bank fee"),
    ]
    assert d["payments"] == []
    slip = client.get(f"/api/deposits/{d['id']}/print-preview")
    assert slip.status_code == 200 and "T&amp;C Holdings — distribution" in slip.text


def test_deposit_line_cannot_come_from_undeposited_funds(client, seed_accounts):
    r = client.post(
        "/api/deposits",
        json={
            "deposit_to_account_id": seed_accounts["1000"].id,
            "date": "2026-09-03",
            "other_lines": [{"account_id": seed_accounts["1200"].id, "amount": "10"}],
        },
    )
    assert r.status_code == 400
