"""John's build: the Canadian laser voucher cheque, cheque on top (Deluxe
SS9209 and the like) — each value printed at its own place on the sheet,
nothing the stock carries printed again, nothing in the MICR clear band."""

import re
from datetime import date
from decimal import Decimal

from app.services.pdf_service import render_check_html


def _html(**over):
    check = {
        "payee": "Oakville Club",
        "payee_address": ["56 Water Street", "Oakville, ON  L6J 2Y3"],
        "date": date(2026, 11, 8),
        "amount": Decimal("783.80"),
        "check_number": "0244",
        "memo": "October statement",
        "account_name": "RBC - Can $",
        "details": [{"description": "Bill #S209-2026-10", "amount": Decimal("783.80")}],
        **over,
    }
    return render_check_html(
        check, {"check_stock": "cpa_top", "company_name": "Alderella Holdings Inc."}
    )


def test_the_values_print_and_the_stocks_own_marks_do_not():
    html = _html()
    assert "Seven Hundred Eighty-Three and 80/100" in html
    assert "**783.80" in html
    assert "Oakville Club" in html and "56 Water Street" in html
    assert "".join(re.findall(r"<span>(\d)</span>", html))[:8] == "20261108"
    assert "Memo: October statement" in html
    # the company name, the cheque number, "PAY", "$" are on the stock
    assert "Alderella Holdings Inc." not in html
    assert "0244" not in html
    assert "@page { size: letter; margin: 0; }" in html


def test_both_stubs_carry_the_payment():
    html = _html()
    assert html.count("Bill #S209-2026-10") == 2
    assert html.count("RBC - Can $") == 2


def test_nothing_is_placed_in_the_micr_clear_band():
    html = _html()
    css = html.split("</style>")[-2]
    for top in re.findall(r"\.c-[a-z-]+ \{[^}]*top: ([0-9.]+)in", css):
        assert float(top) < 2.875 - 0.25, top


def test_the_setting_accepts_the_stock():
    from app.routes.settings import ENUM_SETTINGS

    assert "cpa_top" in ENUM_SETTINGS["check_stock"]
