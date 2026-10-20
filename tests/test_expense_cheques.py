"""John's build on 2.24.0's check printing: the voucher layout setting, the
Canadian date and word, a QuickBooks cheque's number without its import
reference, and expense_id as another name for transaction_id."""

from app.routes.checks import _cheque_style, register_check_data


def _cheque(client, seed_accounts, **extra):
    body = {
        "date": "2026-10-15",
        "payee": "Alison St. Hill",
        "paid_from_account_id": seed_accounts["1000"].id,
        "reference": "426",
        "lines": [
            {
                "account_id": seed_accounts["6000"].id,
                "amount": "100.00",
                "memo": "Nespresso",
            },
            {"account_id": seed_accounts["6100"].id, "amount": "13.00", "memo": "HST"},
        ],
    }
    body.update(extra)
    r = client.post("/api/expenses", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_print_a_cheque(client, db_session, seed_accounts):
    x = _cheque(client, seed_accounts)
    data = register_check_data(db_session, x["id"])
    assert data["payee"] == "Alison St. Hill" and data["check_number"] == "426"
    assert float(data["amount"]) == 113.0 and len(data["details"]) == 2
    _cheque_style(data, {"cheque_layout": "top", "sales_tax_system": "canada"})
    assert (
        data["layout"] == "top"
        and data["word"] == "Cheque"
        and data["cpa_date"] == "20261015"
    )
    for key in ("transaction_id", "expense_id"):
        r = client.get("/api/checks/print", params={key: x["id"]})
        assert r.status_code == 200 and r.content[:4] == b"%PDF"


def test_a_card_charge_has_no_cheque(client, seed_accounts):
    card = next(a for a in seed_accounts.values() if a.bank_kind == "credit_card")
    x = _cheque(client, seed_accounts, paid_from_account_id=card.id)
    assert (
        client.get("/api/checks/print", params={"expense_id": x["id"]}).status_code
        == 400
    )


def test_quickbooks_reference_prints_the_cheque_number(
    client, db_session, seed_accounts
):
    x = _cheque(client, seed_accounts, reference="8812 · QB #4410")
    assert register_check_data(db_session, x["id"])["check_number"] == "8812"
    y = _cheque(client, seed_accounts, reference="QB #4411")
    assert register_check_data(db_session, y["id"])["check_number"] == ""
