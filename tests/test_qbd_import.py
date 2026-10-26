"""QuickBooks Desktop full-history import (/api/migration/qbd): the IIF
chart and lists, every transaction from the Journal report, checked year by
year against the Balance Sheet and Profit & Loss before anything is written,
and the Attach folder's documents onto their transactions."""

import io
import zipfile

from app.models.accounts import Account
from app.models.attachments import Attachment
from app.models.contacts import Vendor
from app.models.transactions import Transaction, TransactionLine

LISTS = "\r\n".join(
    [
        "!ACCNT\tNAME\tREFNUM\tTIMESTAMP\tACCNTTYPE\tOBAMOUNT\tDESC\tACCNUM\tSCD\tBANKNUM\tEXTRA\tHIDDEN\tDELCOUNT\tUSEID",
        "ACCNT\tChequing\t1\t1\tBANK\t4500.00\t\t\t0\t\t\tN\t0\tN",
        "ACCNT\tShareholder loan\t2\t1\tLTLIAB\t-9000.00\t\t\t0\t\t\tN\t0\tN",
        "ACCNT\tRetained Earnings\t3\t1\tEQUITY\t0.00\t\t\t0\t\t\tN\t0\tN",
        "ACCNT\tRental income\t4\t1\tINC\t0.00\t\t\t0\t\t\tN\t0\tN",
        "ACCNT\tUtilities\t5\t1\tEXP\t0.00\t\t\t0\t\t\tN\t0\tN",
        "ACCNT\tUtilities:Gas\t6\t1\tEXP\t0.00\t\t\t0\t\t\tN\t0\tN",
        "ACCNT\tOld account\t7\t1\tEXP\t0.00\t\t\t0\t\t\tY\t0\tN",
        "!VEND\tNAME\tREFNUM\tTIMESTAMP\tPRINTAS\tADDR1",
        'VEND\t"Locks, Keys and Re-keys"\t8\t1\t\t',
        "",
    ]
)

JOURNAL = "\n".join(
    [
        '"Trans #","Type","Date","Num","Name","Memo","Account","Debit","Credit"',
        '"1","General Journal","2023-01-01",,,"Loan in","Chequing",9000.00,""',
        ',,,,,"Loan in","Shareholder loan","",9000.00',
        ",,,,,,,9000.00,9000.00",
        '"2","Deposit","2023-06-30",,,"Deposit","Chequing",3000.00,""',
        ',,,,"Tenant A","Rent","Rental income","",3000.00',
        ",,,,,,,3000.00,3000.00",
        '"3","Cheque","2024-02-11","101","Gas Co",,"Chequing","",500.00',
        ',,,,"Gas Co",,"Utilities:Gas",500.00,""',
        ",,,,,,,500.00,500.00",
        '"4","Cheque","2024-03-01","102","Locks, Keys and Re-keys",,"Chequing","",7000.00',
        ',,,,"Locks, Keys and Re-keys",,"Shareholder loan",7000.00,""',
        ",,,,,,,7000.00,7000.00",
        '"TOTAL",,,,,,,19500.00,19500.00',
    ]
)

BALANCE_SHEET = "\n".join(
    [
        ',"31 Dec 23","31 Dec 24"',
        '"ASSETS","",""',
        '"Chequing",12000.00,4500.00',
        '"TOTAL ASSETS",12000.00,4500.00',
        '"Shareholder loan",9000.00,2000.00',
        '"Retained Earnings",0.00,3000.00',
        '"Net Income",3000.00,-500.00',
        '"Total Equity",3000.00,2500.00',
    ]
)

PROFIT_LOSS = "\n".join(
    [
        ',"31 Dec 23","31 Dec 24","TOTAL"',
        '"Rental income",3000.00,0.00,3000.00',
        '"Gas",0.00,500.00,500.00',
        '"Net Income",3000.00,-500.00,2500.00',
    ]
)

MAP = '"Trans #","Folder"\n"3","80000010-1707686400"\n'


def _attach_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Demo Co/Txn/80000010-1707686400/gas bill.pdf", b"%PDF-1.4 gas")
        z.writestr("Demo Co/Txn/80000099-1709251200/unmapped.pdf", b"%PDF-1.4 x")
        z.writestr("Demo Co/Inbox/loose.pdf", b"%PDF-1.4 y")
    return buf.getvalue()


def _files(journal=JOURNAL, bs=BALANCE_SHEET, attach=True):
    files = [
        ("files", ("lists.iif", io.BytesIO(LISTS.encode()), "text/plain")),
        ("files", ("journal.csv", io.BytesIO(journal.encode()), "text/csv")),
        ("files", ("balance sheet.csv", io.BytesIO(bs.encode()), "text/csv")),
        (
            "files",
            ("profit and loss.csv", io.BytesIO(PROFIT_LOSS.encode()), "text/csv"),
        ),
    ]
    if attach:
        files += [
            ("files", ("attach.zip", io.BytesIO(_attach_zip()), "application/zip")),
            ("files", ("attachment-map.csv", io.BytesIO(MAP.encode()), "text/csv")),
        ]
    return files


def test_dry_run_verifies_against_quickbooks(client, db_session):
    r = client.post("/api/migration/qbd/dry-run", files=_files())
    data = r.json()
    assert r.status_code == 200, data
    assert data["ok"], data["errors"]
    assert data["journals"] == 4
    assert data["attachments"] == 1
    assert any("Verified against QuickBooks to the cent" in w for w in data["warnings"])
    assert any("not in the map" in w for w in data["warnings"])
    # nothing written
    assert (
        db_session.query(Transaction).filter_by(source_type="qbd_import").count() == 0
    )


def test_dry_run_refuses_a_journal_that_disagrees(client):
    moved = JOURNAL.replace('"Utilities:Gas",500.00', '"Utilities",500.00')
    data = client.post("/api/migration/qbd/dry-run", files=_files(journal=moved)).json()
    assert not data["ok"]
    assert any("Utilities:Gas for the year to 2024-12-31" in e for e in data["errors"])
    r = client.post("/api/migration/qbd/import", files=_files(journal=moved))
    assert r.json()["imported_journals"] == 0


def test_dry_run_refuses_a_cut_off_journal(client):
    cut = JOURNAL.replace(
        '"TOTAL",,,,,,,19500.00,19500.00', '"TOTAL",,,,,,,20000.00,20000.00'
    )
    data = client.post("/api/migration/qbd/dry-run", files=_files(journal=cut)).json()
    assert not data["ok"]
    assert any("rows are missing" in e for e in data["errors"])


def test_import_posts_history_once_without_opening_balances(client, db_session):
    data = client.post("/api/migration/qbd/import", files=_files()).json()
    assert data["ok"], data["errors"]
    assert data["imported_journals"] == 4
    assert data["imported_attachments"] == 1

    txns = (
        db_session.query(Transaction)
        .filter(Transaction.source_type.in_(["qbd_import", "expense", "deposit"]))
        .all()
    )
    kinds = {t.reference: t.source_type for t in txns}
    # the general journal stays a journal entry; cheques become Expenses
    # (their number first in the reference), the deposit a Deposit
    assert kinds == {
        "QB #1": "qbd_import",
        "QB #2": "deposit",
        "101 · QB #3": "expense",
        "102 · QB #4": "expense",
    }
    # the IIF's OBAMOUNT is not posted: the Journal already carries it
    assert (
        db_session.query(Transaction).filter_by(source_type="opening_balance").count()
        == 0
    )

    cheq = db_session.query(Account).filter_by(name="Chequing").one()
    lines = db_session.query(TransactionLine).filter_by(account_id=cheq.id).all()
    assert sum(l.debit - l.credit for l in lines) == 4500

    # sub-account under its parent, hidden account inactive, seeded RE reused
    gas = db_session.query(Account).filter_by(name="Gas").one()
    assert (
        gas.parent_id == db_session.query(Account).filter_by(name="Utilities").one().id
    )
    assert (
        db_session.query(Account).filter_by(name="Old account").one().is_active is False
    )
    assert db_session.query(Account).filter_by(name="Retained Earnings").count() == 1

    # a name with a comma loses QuickBooks' quotes
    assert (
        db_session.query(Vendor).filter_by(name="Locks, Keys and Re-keys").count() == 1
    )

    gas_cheque = next(t for t in txns if t.reference == "101 · QB #3")
    att = (
        db_session.query(Attachment)
        .filter_by(entity_type="expense", entity_id=gas_cheque.id)
        .one()
    )
    assert att.filename == "gas bill.pdf"

    # the cheque opens as an Expense, paid from Chequing, to Gas
    exp = client.get(f"/api/expenses/{gas_cheque.id}").json()
    assert exp["payee"] == "Gas Co" and exp["amount"] == 500.0
    assert exp["paid_from_account_name"] == "Chequing"
    assert [l["account_name"] for l in exp["lines"]] == ["Gas"]
    # a payee that is a vendor is linked to it
    locks = client.get(
        f"/api/expenses/{next(t.id for t in txns if t.reference == '102 · QB #4')}"
    ).json()
    assert locks["vendor_id"] is not None
    dep = client.get(
        f"/api/deposits/{next(t.id for t in txns if t.reference == 'QB #2')}"
    ).json()
    assert float(dep["amount"]) == 3000
    assert [
        (o["account_name"], float(o["amount"]), o["description"])
        for o in dep["other_lines"]
    ] == [("Rental income", 3000.0, "Tenant A — Rent")]

    again = client.post("/api/migration/qbd/import", files=_files()).json()
    assert again["imported_journals"] == 0
    assert again["imported_attachments"] == 0
    assert (
        db_session.query(Transaction)
        .filter(Transaction.source_type.in_(["qbd_import", "expense", "deposit"]))
        .count()
        == 4
    )


def test_balance_sheet_report_matches_quickbooks(client):
    client.post("/api/migration/qbd/import", files=_files(attach=False))
    bs = client.get(
        "/api/reports/balance-sheet", params={"as_of_date": "2024-12-31"}
    ).json()
    assert bs["total_assets"] == 4500
    assert bs["total_liabilities"] == 2000
    assert bs["total_equity"] == 2500
