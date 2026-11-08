"""John's build: a bill payment's cheque or reference number is changed in
place ("EFT" on one paid online), with no void left behind; one reference
such as "EFT" may name several vendors' payments; and a payment brought
over from QuickBooks Desktop with no Num is not a cheque waiting to print."""

from decimal import Decimal
from pathlib import Path

from app.models.bills import BillPayment
from app.models.transactions import Transaction
from app.services.check_numbers import unprinted_payments

from tests import test_replace_transaction_689 as r689

_balances, _bill_payment = r689._balances, r689._bill_payment
books = r689.books  # the fixture: a vendor and an open bill

JS = Path(__file__).resolve().parents[1] / "app" / "static" / "js"


def _pay(client, books):
    r = client.post("/api/bill-payments", json=_bill_payment(books))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_the_reference_changes_in_place_and_the_books_do_not_move(
    client, books, TestSession
):
    pid = _pay(client, books)
    before = _balances(TestSession)
    r = client.put(
        f"/api/bill-payments/{pid}/reference",
        json={"check_number": " EFT ", "method": "ach"},
    )
    assert r.status_code == 200, r.text
    got = r.json()
    assert (got["check_number"], got["method"], got["is_voided"]) == (
        "EFT",
        "ach",
        False,
    )
    assert _balances(TestSession) == before
    with TestSession() as s:
        assert s.query(BillPayment).count() == 1
    # blank takes the number off; the method stays when none is sent
    r = client.put(f"/api/bill-payments/{pid}/reference", json={"check_number": ""})
    assert r.status_code == 200, r.text
    assert (r.json()["check_number"], r.json()["method"]) == (None, "ach")


def test_a_void_payment_has_nothing_to_change(client, books):
    pid = _pay(client, books)
    assert client.post(f"/api/bill-payments/{pid}/void").status_code == 200
    r = client.put(f"/api/bill-payments/{pid}/reference", json={"check_number": "9"})
    assert r.status_code == 400
    assert (
        client.put(
            "/api/bill-payments/999999/reference", json={"check_number": "9"}
        ).status_code
        == 404
    )


def test_a_cheque_number_already_used_is_refused_unless_kept(client, books):
    assert (
        client.put(
            "/api/settings", json={"warn_duplicate_check_number": "true"}
        ).status_code
        == 200
    )
    first = client.post(
        "/api/bill-payments",
        json={**_bill_payment(books, amount="50.00"), "check_number": "1043"},
    )
    assert first.status_code == 201, first.text
    pid = _pay(client, books)
    url = f"/api/bill-payments/{pid}/reference"
    r = client.put(url, json={"check_number": "1043"})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "duplicate_check_number"
    r = client.put(
        url + "?allow_duplicate_check_number=true", json={"check_number": "1043"}
    )
    assert r.status_code == 200, r.text
    # "EFT" is a reference, not a cheque number: never refused
    assert client.put(url, json={"check_number": "EFT"}).status_code == 200
    # its own number again is not a duplicate of itself
    assert (
        client.put(
            f"/api/bill-payments/{first.json()['id']}/reference",
            json={"check_number": "1043"},
        ).status_code
        == 200
    )


def test_a_payment_brought_over_from_quickbooks_is_not_waiting_to_print(
    client, books, TestSession
):
    typed = _pay(client, books)
    imported = _pay(client, books)
    with TestSession() as s:
        bp = s.get(BillPayment, imported)
        txn = s.get(Transaction, bp.transaction_id)
        txn.reference = "QB #8391"
        s.commit()
        bank = books["a"]["1000"].id
        assert [p.id for p in unprinted_payments(s, bank)] == [typed]
    listed = {p["id"]: p for p in client.get("/api/bill-payments").json()}
    assert listed[imported]["reference"] == "QB #8391"
    assert listed[typed]["reference"] is None
    assert Decimal(str(listed[imported]["amount"])) == Decimal("100.00")


def test_the_reference_change_is_refused_to_read_only_sign_ins():
    from app.main import _role_allows

    path = "/api/bill-payments/1/reference"
    assert not _role_allows("readonly", "PUT", path)
    assert not _role_allows("accountant", "PUT", path)


def test_the_screens_use_it():
    cheques = (JS / "write_cheques.js").read_text(encoding="utf-8")
    assert "WriteChequesNo(p)" in cheques
    assert "/QB #\\d/.test(p.reference" in cheques
    bills = (JS / "bills.js").read_text(encoding="utf-8")
    assert "/^\\d+$/.test(checkNumber.trim()) && byVendor.size > 1" in bills
    pay = (JS / "pay_bills.js").read_text(encoding="utf-8")
    assert "/bill-payments/${id}/reference" in pay
    assert "BillsPage.qbOnlyNumber" in pay
