"""John's build: the bank register keeps its column headings in view as it
scrolls, and can be read newest first.

A register of sixteen years opened at its oldest entries in the desktop app,
and once scrolled its headings were gone. The headings now hold to the top
of the page; Newest first (kept like Hide voided) turns the list round,
each row with its running balance, and opens it at the top."""

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from tests.test_browser_register_date import (  # noqa: E402
    ELEMENT_IN_VIEW,
    SCROLLED,
    _Ledger,
    _ledger_page,
    _redrawn,
    _wait_redrawn,
)
from tests.test_theme_contrast import browser_fixture  # noqa: E402,F401  (the fixture)

HEAD_TOP = """() => document.querySelector('#page-content thead th').getBoundingClientRect().top
    - document.getElementById('content').getBoundingClientRect().top"""

DATES = "rows => rows.map(r => r.cells[0].textContent)"


def test_the_headings_stay_in_view_as_the_register_scrolls(browser):
    ledger = _Ledger()
    page = _ledger_page(browser, ledger, "#/banking/1")
    try:
        page.wait_for_function(ELEMENT_IN_VIEW, arg="#reg-quick-entry")
        assert page.evaluate(SCROLLED) > 200
        # scrolled to the foot, the table's head is far above, yet in view
        assert abs(page.evaluate(HEAD_TOP)) <= 1
        page.evaluate("() => { document.getElementById('content').scrollTop = 400; }")
        assert abs(page.evaluate(HEAD_TOP)) <= 1
    finally:
        page.close()


def test_newest_first_turns_the_list_round_and_is_kept(browser):
    ledger = _Ledger()
    page = _ledger_page(browser, ledger, "#/banking/1")
    try:
        page.wait_for_function(ELEMENT_IN_VIEW, arg="#reg-quick-entry")
        rows = "#page-content tr[data-txn]"
        oldest_first = page.eval_on_selector_all(rows, DATES)
        balances = page.eval_on_selector_all(
            rows, "rows => rows.map(r => r.cells[8].textContent)"
        )
        assert oldest_first[0] == "Sep 1, 2026"

        _redrawn(page)
        page.check("#reg-newest-first")
        _wait_redrawn(page)
        newest_first = page.eval_on_selector_all(rows, DATES)
        assert newest_first == list(reversed(oldest_first))
        # each row keeps its own running balance
        assert page.eval_on_selector_all(
            rows, "rows => rows.map(r => r.cells[8].textContent)"
        ) == list(reversed(balances))
        # opened at the top, where the newest are; the entry row still there
        page.wait_for_function(f"() => ({SCROLLED})() === 0")
        assert page.is_checked("#reg-newest-first")
        assert page.locator("#reg-quick-entry").count() == 1

        # kept: opened again from another page, still newest first, at the top
        page.goto(page.url.split("#")[0] + "#/banking/4")
        page.wait_for_selector("#reg-filters[data-account='4']")
        page.goto(page.url.split("#")[0] + "#/banking/1?start_date=2026-09-05")
        page.wait_for_selector("#reg-opening")
        assert page.is_checked("#reg-newest-first")
        assert page.evaluate(SCROLLED) == 0
        dates = page.eval_on_selector_all("#page-content tbody tr", DATES)
        # the balance brought forward closes the list
        assert dates[0] == "Oct 30, 2026" and dates[-1] == "Sep 5, 2026"
        assert page.locator("#page-content tbody tr").last.get_attribute("id") == (
            "reg-opening"
        )

        _redrawn(page)
        page.uncheck("#reg-newest-first")
        _wait_redrawn(page)
        assert page.eval_on_selector_all(rows, DATES)[0] == "Sep 5, 2026"
        page.wait_for_function(ELEMENT_IN_VIEW, arg="#reg-quick-entry")
    finally:
        page.close()
