"""John's build: customer payments and bill payments take documents of
their own, and QuickBooks documents imported onto the journal entry behind
a payment move onto the payment."""

from pathlib import Path

import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[1]


def test_a_payment_and_a_bill_payment_take_files(client):
    for kind in ("payment", "bill_payment"):
        r = client.post(
            f"/api/attachments/{kind}/7",
            files={"file": ("cheque.pdf", b"%PDF-1.4 x", "application/pdf")},
        )
        assert r.status_code == 201, r.text
        assert [
            a["filename"] for a in client.get(f"/api/attachments/{kind}/7").json()
        ] == ["cheque.pdf"]


def test_the_import_puts_documents_on_the_payment():
    from app.services.qbd_import import _ATTACH_ENTITY

    assert _ATTACH_ENTITY["payment"] == ("payment", "doc")
    assert _ATTACH_ENTITY["bill_payment"] == ("bill_payment", "doc")


def test_the_migration_moves_imported_documents_onto_the_payment(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "m", ROOT / "migrations/versions/c9d0e1f2a3b6_payment_attachments.py"
    )
    m = importlib.util.module_from_spec(spec)
    eng = sa.create_engine(f"sqlite:///{tmp_path/'t.db'}")
    with eng.begin() as c:
        c.execute(
            sa.text(
                "create table transactions (id integer primary key, source_type text, source_id integer)"
            )
        )
        c.execute(
            sa.text(
                "create table attachments (id integer primary key, entity_type text, entity_id integer)"
            )
        )
        c.execute(
            sa.text(
                "create table payments (id integer primary key, transaction_id integer)"
            )
        )
        c.execute(
            sa.text(
                "create table bill_payments (id integer primary key, transaction_id integer)"
            )
        )
        c.execute(
            sa.text(
                "insert into transactions values (10,'payment',3),(11,'bill_payment',4),(12,'journal_entry',null)"
            )
        )
        c.execute(sa.text("insert into payments values (3,10)"))
        c.execute(sa.text("insert into bill_payments values (4,11)"))
        c.execute(
            sa.text(
                "insert into attachments values (1,'journal_entry',10),(2,'journal_entry',11),(3,'journal_entry',12),(4,'expense',10)"
            )
        )
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        import alembic.op as op_module

        ctx = MigrationContext.configure(c)
        with Operations.context(ctx):
            spec.loader.exec_module(m)
            m.upgrade()
            rows = c.execute(
                sa.text(
                    "select id, entity_type, entity_id from attachments order by id"
                )
            ).fetchall()
            assert rows == [
                (1, "payment", 3),
                (2, "bill_payment", 4),
                (3, "journal_entry", 12),
                (4, "expense", 10),
            ]
            m.downgrade()
            rows = c.execute(
                sa.text(
                    "select id, entity_type, entity_id from attachments order by id"
                )
            ).fetchall()
            assert rows[:2] == [(1, "journal_entry", 10), (2, "journal_entry", 11)]
        assert op_module


def test_the_screens_have_it():
    js = (ROOT / "app/static/js/payment_attachments.js").read_text()
    assert "RecordFiles.insert('payment', id)" in js
    assert "RecordFiles.insert('bill_payment', id)" in js
    assert "AttachFile.flush('payment', saved.id)" in js
    assert "/static/js/payment_attachments.js" in (ROOT / "index.html").read_text()
