"""John's build: a cheque or card charge memorized with a schedule, beside
2.31's memorized bills and journal entries, and the 2.24 / 2.29 builds' own
memorized list carried into it."""

import json
from pathlib import Path

from app.models.transactions import Transaction

ROOT = Path(__file__).resolve().parent.parent


def _canada(client, seed_accounts):
    r = client.put(
        "/api/settings",
        json={
            "sales_tax_system": "canada",
            "hst_account_id": str(seed_accounts["2200"].id),
            "hst_rate": "13",
        },
    )
    assert r.status_code == 200, r.text


def _cheque(client, seed_accounts, **extra):
    body = {
        "kind": "expense",
        "name": "Office rent",
        "frequency": "monthly",
        "start_date": "2026-09-01",
        "payee": "Alison St. Hill",
        "paid_from_account_id": seed_accounts["1000"].id,
        "lines": [
            {
                "account_id": seed_accounts["6000"].id,
                "amount": 113,
                "tax_code": "H",
                "description": "rent",
            },
            {"account_id": seed_accounts["6100"].id, "amount": 10},
        ],
    }
    body.update(extra)
    return client.post("/api/memorized", json=body)


def test_a_memorized_cheque_is_entered_as_an_expense(client, db_session, seed_accounts):
    _canada(client, seed_accounts)
    bank = seed_accounts["1000"].id
    # an earlier cheque sets the number the memorized one takes next
    first = client.post(
        "/api/expenses",
        json={
            "date": "2026-08-01",
            "payee": "Bell",
            "paid_from_account_id": bank,
            "expense_account_id": seed_accounts["6000"].id,
            "amount": "5",
            "reference": "426",
        },
    )
    assert first.status_code == 201, first.text

    r = _cheque(client, seed_accounts)
    assert r.status_code == 201, r.text
    mem = r.json()
    assert mem["kind"] == "expense" and mem["payee"] == "Alison St. Hill"
    assert mem["paid_from_account_name"] == seed_accounts["1000"].name
    assert float(mem["amount"]) == 123.0
    assert [ln["tax_code"] for ln in mem["lines"]] == ["H", None]

    rows = client.get("/api/memorized", params={"kind": "expense"}).json()
    assert [(x["name"], x["party"]) for x in rows] == [
        ("Office rent", "Alison St. Hill")
    ]

    entered = client.post(
        f"/api/memorized/{mem['id']}/enter", json={"occurrence": "2026-09-01"}
    )
    assert entered.status_code == 200, entered.text
    assert entered.json()["kind"] == "expense"
    assert entered.json()["message"].startswith("Entered the expense dated")
    x = client.get(f"/api/expenses/{entered.json()['document_id']}").json()
    assert x["payee"] == "Alison St. Hill"
    assert x["reference"] == "427"
    assert x["amount"] == 123.0
    assert sorted((ln["account_id"], ln["amount"]) for ln in x["lines"]) == sorted(
        [
            (seed_accounts["6000"].id, 100.0),
            (seed_accounts["6100"].id, 10.0),
            (seed_accounts["2200"].id, 13.0),
        ]
    )
    txn = db_session.get(Transaction, x["id"])
    assert txn.source_type == "expense"
    assert client.get(f"/api/memorized/{mem['id']}").json()["next_date"] == "2026-10-01"


def test_a_memorized_cheque_is_refused_what_a_cheque_is(client, seed_accounts):
    assert _cheque(client, seed_accounts, paid_from_account_id=None).status_code == 422
    assert _cheque(client, seed_accounts, payee=None).status_code == 422
    # H without GST/HST turned on
    assert _cheque(client, seed_accounts).status_code == 400
    # paid from an expense account
    r = _cheque(
        client,
        seed_accounts,
        paid_from_account_id=seed_accounts["6000"].id,
        lines=[{"account_id": seed_accounts["6100"].id, "amount": 5}],
    )
    assert r.status_code == 400


def test_a_memorized_cheque_edits(client, seed_accounts):
    _canada(client, seed_accounts)
    mem = _cheque(client, seed_accounts).json()
    r = client.put(
        f"/api/memorized/{mem['id']}",
        json={"lines": [{"account_id": seed_accounts["6100"].id, "amount": 50}]},
    )
    assert r.status_code == 200, r.text
    assert float(r.json()["amount"]) == 50.0
    r = client.put(f"/api/memorized/{mem['id']}", json={"name": "Rent"})
    assert r.status_code == 200, r.text
    assert float(r.json()["amount"]) == 50.0


def _cfg(db):
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.attributes["database_url"] = "sqlite:///" + Path(db).as_posix()
    return cfg


def test_the_older_builds_list_is_carried_over(tmp_path):
    from alembic import command
    from sqlalchemy import create_engine, text

    db = tmp_path / "old.db"
    cfg = _cfg(db)
    # a file the 2.29 build last opened, with that build's own list
    command.upgrade(cfg, "e5f6a7b8c9d1")
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE memorized_transactions (id INTEGER PRIMARY KEY, "
                "name VARCHAR(200) NOT NULL, kind VARCHAR(20) NOT NULL, "
                "payload TEXT NOT NULL, frequency VARCHAR(20) NOT NULL, "
                "next_date DATE, action VARCHAR(10) NOT NULL, "
                "days_in_advance INTEGER NOT NULL DEFAULT 0, remaining INTEGER, "
                "is_active BOOLEAN NOT NULL, last_entered DATE, "
                "times_entered INTEGER NOT NULL DEFAULT 0, created_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX ix_memorized_transactions_id ON memorized_transactions (id)"
            )
        )
        rows = [
            (
                "Rent",
                "expense",
                {
                    "payee": "Alison",
                    "paid_from_account_id": 1,
                    "lines": [{"account_id": 7, "amount": "500.00", "memo": "rent"}],
                },
                "monthly",
                "auto",
            ),
            (
                "Depreciation",
                "journal",
                {
                    "description": "Monthly depreciation",
                    "lines": [
                        {"account_id": 8, "debit": "100.00", "credit": "0.00"},
                        {"account_id": 9, "debit": "0.00", "credit": "100.00"},
                    ],
                },
                "quarterly",
                "remind",
            ),
            ("Cash in", "deposit", {"other_lines": []}, "weekly", "remind"),
        ]
        for name, kind, payload, freq, action in rows:
            conn.execute(
                text(
                    "INSERT INTO memorized_transactions (name, kind, payload, "
                    "frequency, next_date, action, is_active) VALUES "
                    "(:n, :k, :p, :f, '2026-11-15', :a, 1)"
                ),
                {
                    "n": name,
                    "k": kind,
                    "p": json.dumps(payload),
                    "f": freq,
                    "a": action,
                },
            )
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        got = conn.execute(
            text(
                "SELECT kind, name, mode, frequency, interval, next_date, payee, "
                "paid_from_account_id FROM memorized_transactions ORDER BY id"
            )
        ).fetchall()
        lines = conn.execute(
            text(
                "SELECT account_id, debit, credit, description "
                "FROM memorized_transaction_lines ORDER BY id"
            )
        ).fetchall()
        left = conn.execute(text("SELECT kind FROM john_memorized_old")).fetchall()
    assert [tuple(r) for r in got] == [
        ("expense", "Rent", "auto", "monthly", 1, "2026-11-15", "Alison", 1),
        ("journal", "Depreciation", "remind", "quarterly", 1, "2026-11-15", None, None),
    ]
    assert [(r[0], float(r[1] or 0), float(r[2] or 0), r[3]) for r in lines] == [
        (7, 500.0, 0.0, "rent"),
        (8, 100.0, 0.0, None),
        (9, 0.0, 100.0, None),
    ]
    # the deposit has nowhere to go in 2.31: it stays where it was
    assert [r[0] for r in left] == ["deposit"]
