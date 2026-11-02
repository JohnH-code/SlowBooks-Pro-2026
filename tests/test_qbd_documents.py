"""QuickBooks Desktop import: invoices, payments, bills and bill payments as
documents paid up to QuickBooks' open balances, deposits linked to the
payments they took, and the bank reconciliation carried over."""

import io

from app.models.banking import Reconciliation
from app.models.bills import Bill, BillPayment
from app.models.invoices import Invoice
from app.models.payments import Payment, PaymentAllocation
from app.models.transactions import TransactionLine

LISTS = "\r\n".join(
    [
        "!ACCNT\tNAME\tREFNUM\tTIMESTAMP\tACCNTTYPE\tOBAMOUNT\tDESC\tACCNUM\tSCD\tBANKNUM\tEXTRA\tHIDDEN\tDELCOUNT\tUSEID",
        "ACCNT\tRBC\t1\t1\tBANK\t0\t\t\t0\t\t\tN\t0\tN",
        "ACCNT\tAccounts Receivable\t2\t1\tAR\t0\t\t\t0\t\t\tN\t0\tN",
        "ACCNT\tUndeposited Funds\t3\t1\tOCASSET\t0\t\t\t0\t\t\tN\t0\tN",
        "ACCNT\tAccounts Payable\t4\t1\tAP\t0\t\t\t0\t\t\tN\t0\tN",
        "ACCNT\tGST/HST Payable\t5\t1\tOCLIAB\t0\t\t\t0\t\t\tN\t0\tN",
        "ACCNT\tConsulting fee\t6\t1\tINC\t0\t\t\t0\t\t\tN\t0\tN",
        "ACCNT\tAuto\t7\t1\tEXP\t0\t\t\t0\t\t\tN\t0\tN",
        "ACCNT\tAuto:Insurance\t8\t1\tEXP\t0\t\t\t0\t\t\tN\t0\tN",
        "!CUST\tNAME",
        "CUST\tRE/MAX Premier",
        "CUST\tLakeview",
        "!VEND\tNAME",
        "VEND\tAmex",
        "!INVITEM\tNAME\tINVITEMTYPE\tACCNT",
        "INVITEM\tConsulting fees\tSERV\tConsulting fee",
        "",
    ]
)

H = '"Trans #","Type","Date","Num","Name","Memo","Terms","Due Date","Item","Account","Clr","Open Balance","Qty","Sales Price","Debit","Credit"'


def row(*cells):
    return ",".join(f'"{c}"' if c != "" else "" for c in cells)


JOURNAL = "\n".join(
    [
        H,
        # invoice 101, paid by payment and deposited
        row(
            "1",
            "Invoice",
            "2026-01-15",
            "101",
            "RE/MAX Premier",
            "",
            "Net 15",
            "2026-01-30",
            "",
            "Accounts Receivable",
            "",
            "0.00",
            "",
            "",
            "1130.00",
            "",
        ),
        row(
            "",
            "",
            "",
            "",
            "RE/MAX Premier",
            "Advisory",
            "",
            "",
            "Consulting fees",
            "Consulting fee",
            "",
            "",
            "-1",
            "1000.00",
            "",
            "1000.00",
        ),
        row(
            "",
            "",
            "",
            "",
            "RE/MAX Premier",
            "HST",
            "",
            "",
            "HST",
            "GST/HST Payable",
            "",
            "",
            "",
            "13.00%",
            "",
            "130.00",
        ),
        row(
            "", "", "", "", "", "", "", "", "", "", "", "", "", "", "1130.00", "1130.00"
        ),
        row(
            "2",
            "Payment",
            "2026-01-20",
            "5551",
            "RE/MAX Premier",
            "",
            "",
            "",
            "",
            "Undeposited Funds",
            "X",
            "",
            "",
            "",
            "1130.00",
            "",
        ),
        row(
            "",
            "",
            "",
            "",
            "RE/MAX Premier",
            "",
            "",
            "",
            "",
            "Accounts Receivable",
            "",
            "0.00",
            "",
            "",
            "",
            "1130.00",
        ),
        row(
            "", "", "", "", "", "", "", "", "", "", "", "", "", "", "1130.00", "1130.00"
        ),
        row(
            "3",
            "Deposit",
            "2026-01-21",
            "",
            "",
            "Deposit",
            "",
            "",
            "",
            "RBC",
            "X",
            "",
            "",
            "",
            "1130.00",
            "",
        ),
        row(
            "",
            "",
            "",
            "",
            "RE/MAX Premier",
            "Deposit",
            "",
            "",
            "",
            "Undeposited Funds",
            "",
            "",
            "",
            "",
            "",
            "1130.00",
        ),
        row(
            "", "", "", "", "", "", "", "", "", "", "", "", "", "", "1130.00", "1130.00"
        ),
        # invoice 102, still open
        row(
            "4",
            "Invoice",
            "2026-02-15",
            "102",
            "Lakeview",
            "",
            "",
            "2026-03-15",
            "",
            "Accounts Receivable",
            "",
            "565.00",
            "",
            "",
            "565.00",
            "",
        ),
        row(
            "",
            "",
            "",
            "",
            "Lakeview",
            "",
            "",
            "",
            "Consulting fees",
            "Consulting fee",
            "",
            "",
            "-1",
            "500.00",
            "",
            "500.00",
        ),
        row(
            "",
            "",
            "",
            "",
            "Lakeview",
            "HST",
            "",
            "",
            "HST",
            "GST/HST Payable",
            "",
            "",
            "",
            "13.00%",
            "",
            "65.00",
        ),
        row("", "", "", "", "", "", "", "", "", "", "", "", "", "", "565.00", "565.00"),
        # bill, part paid
        row(
            "5",
            "Bill",
            "2026-02-01",
            "",
            "Amex",
            "",
            "",
            "2026-02-11",
            "",
            "Accounts Payable",
            "",
            "50.00",
            "",
            "",
            "",
            "226.00",
        ),
        row(
            "",
            "",
            "",
            "",
            "Amex",
            "",
            "",
            "",
            "",
            "Insurance",
            "",
            "",
            "",
            "",
            "200.00",
            "",
        ),
        row(
            "",
            "",
            "",
            "",
            "Amex",
            "HST Paid",
            "",
            "",
            "",
            "GST/HST Payable",
            "",
            "",
            "",
            "13.00%",
            "26.00",
            "",
        ),
        row("", "", "", "", "", "", "", "", "", "", "", "", "", "", "226.00", "226.00"),
        row(
            "6",
            "Bill Pmt -Cheque",
            "2026-02-10",
            "77",
            "Amex",
            "",
            "",
            "",
            "",
            "RBC",
            "",
            "",
            "",
            "",
            "",
            "176.00",
        ),
        row(
            "",
            "",
            "",
            "",
            "Amex",
            "",
            "",
            "",
            "",
            "Accounts Payable",
            "",
            "",
            "",
            "",
            "176.00",
            "",
        ),
        row("", "", "", "", "", "", "", "", "", "", "", "", "", "", "176.00", "176.00"),
        # a voided invoice
        row(
            "7",
            "Invoice",
            "2026-02-20",
            "103",
            "Lakeview",
            "",
            "",
            "",
            "",
            "Accounts Receivable",
            "",
            "",
            "",
            "",
            "0.00",
            "",
        ),
        row(
            "",
            "",
            "",
            "",
            "Lakeview",
            "",
            "",
            "",
            "Consulting fees",
            "Consulting fee",
            "",
            "",
            "",
            "",
            "0.00",
            "",
        ),
        row("", "", "", "", "", "", "", "", "", "", "", "", "", "", "0.00", "0.00"),
        row(
            "TOTAL",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "4357.00",
            "4357.00",
        ),
    ]
)


def _files(journal=JOURNAL):
    return [
        ("files", ("lists.iif", io.BytesIO(LISTS.encode()), "text/plain")),
        ("files", ("journal.csv", io.BytesIO(journal.encode()), "text/csv")),
    ]


def test_documents_paid_as_quickbooks_left_them(client, db_session, seed_accounts):
    dry = client.post("/api/migration/qbd/dry-run", files=_files()).json()
    assert dry["ok"], dry["errors"]
    assert any(
        "RBC: QuickBooks reconciled it through 21 Jan 2026" in w
        for w in dry["warnings"]
    )

    data = client.post("/api/migration/qbd/import", files=_files()).json()
    assert data["ok"], data["errors"]

    inv = {i.invoice_number: i for i in db_session.query(Invoice).all()}
    paid, open_, void = inv["101"], inv["102"], inv["103"]
    assert (paid.status.value, float(paid.balance_due), float(paid.tax_amount)) == (
        "paid",
        0.0,
        130.0,
    )
    assert float(paid.tax_rate) == 0.13 and paid.terms == "Net 15"
    assert [(l.quantity, float(l.amount)) for l in paid.lines] == [(1, 1000.0)]
    assert paid.lines[0].item_id is not None
    assert (open_.status.value, float(open_.balance_due)) == ("sent", 565.0)
    assert void.status.value == "void"

    pay = db_session.query(Payment).one()
    alloc = db_session.query(PaymentAllocation).one()
    assert (alloc.payment_id, alloc.invoice_id, float(alloc.amount)) == (
        pay.id,
        paid.id,
        1130.0,
    )

    bill = db_session.query(Bill).one()
    assert (bill.status.value, float(bill.balance_due), float(bill.total)) == (
        "partial",
        50.0,
        226.0,
    )
    # HST paid stays its own line, to its account
    assert sorted(float(l.amount) for l in bill.lines) == [26.0, 200.0]
    assert float(db_session.query(BillPayment).one().amount) == 176.0

    # the customer and vendor balances are QuickBooks' open amounts
    custs = {
        c["name"]: float(c["balance"]) for c in client.get("/api/customers").json()
    }
    assert custs["Lakeview"] == 565.0 and custs["RE/MAX Premier"] == 0.0
    vend = {v["name"]: float(v["balance"]) for v in client.get("/api/vendors").json()}
    assert vend["Amex"] == 50.0

    # the deposit took the payment: nothing waits on Make Deposits
    assert client.get("/api/deposits/pending").json() == []

    # the reconciliation QuickBooks had, through its last reconciled date
    recon = db_session.query(Reconciliation).one()
    assert (
        str(recon.statement_date) == "2026-01-21"
        and float(recon.statement_balance) == 1130.0
    )
    stamped = (
        db_session.query(TransactionLine).filter_by(reconciliation_id=recon.id).all()
    )
    assert len(stamped) == 1 and float(stamped[0].debit) == 1130.0

    # the sub-account named like a starting account stays its own
    names = [a["name"] for a in client.get("/api/accounts").json()]
    assert "Insurance (Auto)" in names

    # a QuickBooks Canada company: CAD books, GST/HST on the seeded 2200
    settings = client.get("/api/settings").json()
    assert (
        settings["home_currency"] == "CAD" and settings["sales_tax_system"] == "canada"
    )
    assert (
        settings["hst_account_id"] == str(seed_accounts["2200"].id)
        and settings["hst_rate"] == "13"
    )
    assert "GST/HST Payable" in names

    again = client.post("/api/migration/qbd/import", files=_files()).json()
    assert again["imported_journals"] == 0
    assert db_session.query(Invoice).count() == 3
    assert db_session.query(Reconciliation).count() == 1


def test_a_second_quickbooks_company_is_refused(client, db_session, seed_accounts):
    """Transaction numbers start at 1 in every QuickBooks file: a second
    company's import into the same books would be skipped as "already
    imported". The dry run says so instead."""
    assert client.post("/api/migration/qbd/import", files=_files()).json()["ok"]
    other = JOURNAL.replace("2026-01-15", "2025-03-03").replace(
        "2026-01-20", "2025-03-09"
    )
    data = client.post("/api/migration/qbd/dry-run", files=_files(other)).json()
    assert not data["ok"]
    assert "different QuickBooks company" in data["errors"][0]
    # the same company again is fine
    assert client.post("/api/migration/qbd/dry-run", files=_files()).json()["ok"]
