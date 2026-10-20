"""Printing a cheque written from Enter Expense (or brought over from
QuickBooks): voucher layout, Canadian date, and the stub's lines."""

from app.routes.checks import _expense_cheque, _cheque_style


def _cheque(client, seed_accounts, **extra):
    body = {"date": "2026-10-15", "payee": "Alison St. Hill", "paid_from_account_id": seed_accounts["1000"].id,
            "reference": "426", "lines": [
                {"account_id": seed_accounts["6000"].id, "amount": "100.00", "memo": "Nespresso"},
                {"account_id": seed_accounts["6100"].id, "amount": "13.00", "memo": "HST"}]}
    body.update(extra)
    r = client.post("/api/expenses", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_print_a_cheque(client, db_session, seed_accounts):
    x = _cheque(client, seed_accounts)
    assert x["paid_from_kind"] == "bank"
    data = _expense_cheque(db_session, x["id"])
    assert data["payee"] == "Alison St. Hill" and data["check_number"] == "426"
    assert float(data["amount"]) == 113.0 and len(data["details"]) == 2
    _cheque_style(data, {"cheque_layout": "top", "sales_tax_system": "canada"})
    assert data["layout"] == "top" and data["word"] == "Cheque" and data["cpa_date"] == "20261015"
    r = client.get("/api/checks/print", params={"expense_id": x["id"]})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


def test_a_card_charge_has_no_cheque(client, seed_accounts):
    card = next(a for a in seed_accounts.values() if a.bank_kind == "credit_card")
    x = _cheque(client, seed_accounts, paid_from_account_id=card.id)
    assert x["paid_from_kind"] == "credit_card"
    assert client.get("/api/checks/print", params={"expense_id": x["id"]}).status_code == 400


def test_quickbooks_reference_prints_the_cheque_number(client, db_session, seed_accounts):
    x = _cheque(client, seed_accounts, reference="8812 · QB #4410")
    assert _expense_cheque(db_session, x["id"])["check_number"] == "8812"
