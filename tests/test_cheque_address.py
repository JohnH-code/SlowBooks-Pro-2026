"""John's build: a cheque keeps the payee and address it was written with.
Write Cheques' Address box can be changed for that cheque; a vendor who
moves later doesn't change cheques already written; a bill payment keeps
the vendor's address as it stood when paid."""

from app.models.contacts import Vendor


def _vendor(client, **kw):
    r = client.post(
        "/api/vendors",
        json={
            "name": "Snow Valley Resorts",
            "address1": "2722 Line 4 North",
            "city": "Minesing",
            "state": "ON",
            "zip": "L9X 1A1",
            **kw,
        },
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _cheque(client, seed_accounts, vendor_id, **kw):
    r = client.post(
        "/api/expenses",
        json={
            "date": "2026-11-07",
            "vendor_id": vendor_id,
            "paid_from_account_id": seed_accounts["1000"].id,
            "lines": [{"account_id": seed_accounts["6000"].id, "amount": "100.00"}],
            "reference": "245",
            **kw,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_the_address_typed_on_the_cheque_is_the_one_it_keeps(
    client, seed_accounts, db_session
):
    from app.routes.checks import register_check_data

    vid = _vendor(client)
    x = _cheque(
        client,
        seed_accounts,
        vid,
        payee_address="Snow Valley Resorts\nAttn: Accounts\n2722 Line 4 North\nMinesing, ON  L9X 1A1",
    )
    assert x["payee_address"].startswith("Snow Valley Resorts\nAttn: Accounts")
    data = register_check_data(db_session, x["id"])
    assert data["payee_block"][1] == "Attn: Accounts"
    assert data["payee_address"][0] == "Attn: Accounts"


def test_a_vendor_who_moves_does_not_change_a_cheque_already_written(
    client, seed_accounts, db_session
):
    from app.routes.checks import register_check_data

    vid = _vendor(client)
    x = _cheque(
        client,
        seed_accounts,
        vid,
        payee_address="Snow Valley Resorts\n2722 Line 4 North\nMinesing, ON  L9X 1A1",
    )
    v = db_session.get(Vendor, vid)
    v.address1 = "1 New Road"
    db_session.commit()
    data = register_check_data(db_session, x["id"])
    assert "2722 Line 4 North" in data["payee_address"]
    assert "1 New Road" not in data["payee_address"]


def test_a_cheque_from_before_keeps_printing_the_vendors_address(
    client, seed_accounts, db_session
):
    from app.routes.checks import register_check_data

    vid = _vendor(client)
    x = _cheque(client, seed_accounts, vid)  # no Address box sent
    assert x["payee_address"] is None
    data = register_check_data(db_session, x["id"])
    assert "payee_block" not in data and data["payee_address"][0] == "2722 Line 4 North"


def test_an_edit_that_sends_no_address_keeps_the_one_it_had(client, seed_accounts):
    vid = _vendor(client)
    x = _cheque(
        client, seed_accounts, vid, payee_address="Snow Valley Resorts\nPO Box 9"
    )
    r = client.put(
        f"/api/expenses/{x['id']}",
        json={
            "date": "2026-11-07",
            "vendor_id": vid,
            "paid_from_account_id": seed_accounts["1000"].id,
            "lines": [{"account_id": seed_accounts["6000"].id, "amount": "120.00"}],
            "reference": "245",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["payee_address"] == "Snow Valley Resorts\nPO Box 9"


def test_a_bill_payment_keeps_the_address_it_was_paid_to(
    client, seed_accounts, db_session
):
    from app.models.bills import BillPayment
    from app.routes.checks import bill_payment_check_data

    vid = _vendor(client)
    bill = client.post(
        "/api/bills",
        json={
            "vendor_id": vid,
            "bill_number": "INV-55102",
            "date": "2026-11-01",
            "lines": [
                {
                    "description": "passes",
                    "quantity": 1,
                    "rate": "100.00",
                    "account_id": seed_accounts["6000"].id,
                    "line_order": 0,
                }
            ],
        },
    )
    assert bill.status_code == 201, bill.text
    pay = client.post(
        "/api/bill-payments",
        json={
            "vendor_id": vid,
            "date": "2026-11-07",
            "amount": 100.0,
            "method": "check",
            "allocations": [{"bill_id": bill.json()["id"], "amount": 100.0}],
        },
    )
    assert pay.status_code == 201, pay.text
    v = db_session.get(Vendor, vid)
    v.address1 = "1 New Road"
    db_session.commit()
    bp = db_session.get(BillPayment, pay.json()["id"])
    data = bill_payment_check_data(db_session, bp)
    assert data["payee_address"][0] == "2722 Line 4 North"
    # the voucher's line for the bill, as QuickBooks lists it
    line = data["details"][0]
    assert data["bill_columns"] is True
    assert (
        line["ref"],
        float(line["original"]),
        float(line["discount"]),
        float(line["amount"]),
    ) == ("INV-55102", 100.0, 0.0, 100.0)
    assert line["date"].isoformat() == "2026-11-01"


def test_write_cheques_lets_the_address_be_changed_and_sends_it():
    from pathlib import Path

    js = Path(__file__).resolve().parents[1] / "app" / "static" / "js"
    wc = (js / "write_cheques.js").read_text(encoding="utf-8")
    assert '<textarea id="qb-address" class="qb-address-box" rows="4" title=' in wc
    assert 'readonly tabindex="-1" title="From the vendor' not in wc
    assert "x.payee_address ||" in wc
    assert "body.payee_address = addrBox.value;" in (js / "expenses.js").read_text(
        encoding="utf-8"
    )


def test_a_changed_address_asks_to_update_the_vendor():
    from pathlib import Path

    js = Path(__file__).resolve().parents[1] / "app" / "static" / "js"
    wc = (js / "write_cheques.js").read_text(encoding="utf-8")
    assert "ExpensesPage.qbAskVendorAddress = async function (vendorId, text)" in wc
    assert "await API.put(`/vendors/${Number(v.id)}`, fields);" in wc
    ex = (js / "expenses.js").read_text(encoding="utf-8")
    assert "await ExpensesPage.qbAskVendorAddress(vendorId, addrBox.value);" in ex


def test_the_vendor_takes_the_address_fields(client):
    vid = _vendor(client)
    r = client.put(
        f"/api/vendors/{vid}",
        json={
            "address1": "Attn: Accounts",
            "address2": "1 New Road",
            "city": "Barrie",
            "state": "ON",
            "zip": "L4M 1A1",
        },
    )
    assert r.status_code == 200, r.text
    assert (r.json()["address2"], r.json()["city"]) == ("1 New Road", "Barrie")
