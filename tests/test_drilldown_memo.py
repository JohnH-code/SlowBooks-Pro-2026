"""An account's drill-down shows each line's own memo, as QuickBooks does
("Fund quarterly tax" rather than "Expense: Harbor Supply")."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_line_memo_is_sent_and_shown(client, seed_accounts):
    v = client.post("/api/vendors", json={"name": "Harbor Supply"}).json()["id"]
    r = client.post(
        "/api/expenses",
        json={
            "date": "2026-10-30",
            "vendor_id": v,
            "paid_from_account_id": seed_accounts["1000"].id,
            "amount": 900.0,
            "lines": [
                {
                    "account_id": seed_accounts["6400"].id,
                    "amount": 900.0,
                    "description": "Fund quarterly tax",
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    got = client.get(
        "/api/reports/account-transactions",
        params={
            "account_id": seed_accounts["6400"].id,
            "start_date": "2026-10-01",
            "end_date": "2026-10-31",
        },
    ).json()
    (e,) = got["entries"]
    assert e["memo"] == "Fund quarterly tax"
    bank = client.get(
        "/api/reports/account-transactions",
        params={
            "account_id": seed_accounts["1000"].id,
            "start_date": "2026-10-01",
            "end_date": "2026-10-31",
        },
    ).json()
    assert bank["entries"][0]["memo"] in (
        "",
        "Fund quarterly tax",
    )  # the bank line has none of its own
    js = (ROOT / "app/static/js/reports.js").read_text()
    assert "escapeHtml(e.memo || e.description || '')" in js
