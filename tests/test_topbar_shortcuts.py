"""John's build: the top bar's shortcuts are chosen per company.

Settings → Top Bar ticks which shortcuts follow Home and in what order
(app/static/js/topbar_shortcuts.js); the choice is the company setting
topbar_shortcuts. Left blank, Slowbooks' own bar is not touched."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "app/static/js/topbar_shortcuts.js").read_text(encoding="utf-8")


def test_the_choice_is_a_company_setting(client):
    assert client.get("/api/settings").json()["topbar_shortcuts"] == ""
    r = client.put(
        "/api/settings",
        json={"topbar_shortcuts": "write_cheques,make_deposits,enter_bills,bookkeeper"},
    )
    assert r.status_code == 200, r.text
    got = client.get("/api/settings").json()["topbar_shortcuts"]
    assert got == "write_cheques,make_deposits,enter_bills,bookkeeper"


def test_every_shortcut_opens_a_page_or_form_that_exists():
    app_js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
    for nav in [
        "#/deposits",
        "#/bookkeeper",
        "#/cc-charges",
        "#/banking",
        "#/expenses",
        "#/customers",
        "#/vendors",
        "#/quick-entry",
        "#/bill-entry",
        "#/journal",
        "#/memorized",
        "#/accounts",
        "#/reports",
    ]:
        assert f"'{nav}'" in JS
        assert f"'{nav[1:]}'" in app_js, nav
    for form in [
        "ExpensesPage.showForm",
        "BillsPage.showForm",
        "BillsPage.showPayForm",
        "InvoicesPage.showForm",
        "PaymentsPage.showForm",
        "CustomersPage.showForm",
    ]:
        assert f"'{form}'" in JS


def test_the_page_loads_it_after_the_app():
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    assert index.index("topbar_shortcuts.js") > index.index('src="/static/js/app.js"')
