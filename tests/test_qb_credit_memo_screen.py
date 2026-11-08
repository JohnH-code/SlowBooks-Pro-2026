"""John's build: Create Credit Memos/Refunds laid out as QuickBooks Desktop
has it, saving through Credit Memos' own save, then asking whether to keep
the credit or apply it to an invoice."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "app" / "static" / "js"


def test_the_screen_is_loaded_after_credit_memos():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert html.index("/static/js/credit_memos.js") < html.index(
        "/static/js/create_credit_memos.js"
    )


def test_it_keeps_the_names_the_save_and_edit_read():
    js = (JS / "create_credit_memos.js").read_text(encoding="utf-8")
    for name in (
        'id="cm-form"',
        'name="customer_id" id="cm-customer-select"',
        'name="date"',
        'name="original_invoice_id" id="cm-invoice-select"',
        'name="tax_rate"',
        'name="notes"',
        'id="cm-lines"',
        "cm-subtotal",
        "cm-tax",
        "cm-total",
    ):
        assert name in js, name
    # Save & Close, Save & New, Clear / Revert, and the question after
    for words in (
        "Save &amp; Close",
        "Save &amp; New",
        "'Revert'",
        "Retain as an available credit",
        "Apply to an",
    ):
        assert words in js, words


def test_the_base_save_hands_back_the_saved_memo():
    js = (JS / "credit_memos.js").read_text(encoding="utf-8")
    assert "CreditMemosPage._lastSaved = saved;" in js


def test_a_vendor_credit_is_entered_in_enter_bills_as_credit():
    js = (JS / "enter_bills.js").read_text(encoding="utf-8")
    assert "VendorCreditsPage.showForm = () => open(null, { credit: true });" in js
    assert "VendorCreditsPage.replace = id => open(null, { creditId: id });" in js
    assert "`/vendor-credits/${Number(c.id)}/replace` : '/vendor-credits'" in js
    assert "'Credit Amount' : 'Amount Due'" in js


def test_unchanged_checks_ignore_the_dropdowns_own_text_boxes():
    """A dropdown's text box is filled in a moment after the form opens;
    counted, Save & Close on an unchanged credit voided and replaced it."""
    for name in (
        "create_credit_memos.js",
        "create_invoices.js",
        "receive_payments.js",
        "enter_bills.js",
        "write_cheques.js",
        "make_deposits.js",
    ):
        assert "contains('cbx-input')" in (JS / name).read_text(encoding="utf-8"), name
