"""John's build: reminders for memorized transactions, as QuickBooks'
Reminders window does them.

A "Remind me" schedule only sat on Memorized Transactions' Due now list.
GET /api/memorized/upcoming lists what is due today or within the reminder
window (setting memorized_remind_days, 5 by default), overdue first, with
the memo; the app shows it when it opens and on Home
(app/static/js/memorized_reminders.js)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _cheque(client, seed_accounts, name, start, notes=None, **extra):
    body = {
        "kind": "expense",
        "name": name,
        "frequency": "monthly",
        "start_date": start,
        "payee": name,
        "notes": notes,
        "paid_from_account_id": seed_accounts["1000"].id,
        "lines": [{"account_id": seed_accounts["6000"].id, "amount": 250}],
    }
    body.update(extra)
    r = client.post("/api/memorized", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_upcoming_lists_what_is_due_within_the_window(client, seed_accounts):
    late = _cheque(client, seed_accounts, "Wawanesa", "2026-11-15", "Car insurance")
    soon = _cheque(client, seed_accounts, "Alison St. Hill", "2026-11-21", "Draw")
    _cheque(client, seed_accounts, "Far off", "2026-11-22")  # day 6: not yet
    r = client.get("/api/memorized/upcoming", params={"as_of": "2026-11-16"})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["days"] == 5  # the default window
    items = got["items"]
    assert [(i["id"], i["when"], i["days_away"]) for i in items] == [
        (late, "overdue", -1),
        (soon, "soon", 5),
    ]
    assert items[0]["memo"] == "Car insurance" and items[1]["memo"] == "Draw"
    assert items[0]["amount"] == "250.00" and items[0]["party"] == "Wawanesa"

    # on the day itself
    on_day = client.get(
        "/api/memorized/upcoming", params={"as_of": "2026-11-21", "days": 0}
    ).json()["items"]
    assert [(i["id"], i["when"]) for i in on_day] == [
        (late, "overdue"),
        (soon, "today"),
    ]


def test_the_window_is_a_setting_and_a_paused_schedule_is_left_out(
    client, seed_accounts
):
    first = _cheque(client, seed_accounts, "Rent", "2026-11-20")
    paused = _cheque(client, seed_accounts, "Old", "2026-11-17")
    assert client.post(f"/api/memorized/{paused}/pause").status_code == 200
    r = client.put("/api/settings", json={"memorized_remind_days": "2"})
    assert r.status_code == 200, r.text
    got = client.get("/api/memorized/upcoming", params={"as_of": "2026-11-16"}).json()
    assert got["days"] == 2 and got["items"] == []
    got = client.get("/api/memorized/upcoming", params={"as_of": "2026-11-18"}).json()
    assert [i["id"] for i in got["items"]] == [first]


def test_the_page_loads_the_reminders_after_the_app():
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    app_at = index.index('src="/static/js/app.js"')
    assert index.index('src="/static/js/memorized_reminders.js"') > app_at
    js = (ROOT / "app/static/js/memorized_reminders.js").read_text(encoding="utf-8")
    assert "/memorized/upcoming" in js and "window=page" in js
