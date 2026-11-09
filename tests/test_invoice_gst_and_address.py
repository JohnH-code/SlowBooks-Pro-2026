"""John's build: a Canadian company's sales forms show its GST/HST number,
and an invoice brought over from QuickBooks Desktop keeps its customer's
address, as one typed in Slowbooks does."""

from pathlib import Path

from app.services.pdf_service import _jinja_env, gst_number

ROOT = Path(__file__).resolve().parents[1]


def test_the_number_under_sales_tax_or_a_canadian_companys_tax_id():
    assert gst_number({"hst_registration_number": " 123456789 RT0001 "}) == (
        "123456789 RT0001"
    )
    canada = {"sales_tax_system": "canada", "company_tax_id": "8154855263RT0001"}
    assert gst_number(canada) == "8154855263RT0001"
    # a US company's EIN is not a GST/HST number
    assert gst_number({"sales_tax_system": "us", "company_tax_id": "12-3456789"}) == ""
    assert gst_number(None) == ""


def test_the_sales_forms_print_it():
    for name in ("invoice_pdf", "credit_memo_pdf", "estimate_pdf", "statement_pdf"):
        text = (ROOT / "app" / "templates" / f"{name}.html").read_text(encoding="utf-8")
        assert "GST/HST No. {{ gst_number(company) }}" in text, name
    tpl = _jinja_env.from_string(
        "{% if gst_number(company) %}GST/HST No. {{ gst_number(company) }}{% endif %}"
    )
    assert tpl.render(
        company={"sales_tax_system": "canada", "company_tax_id": "X1"}
    ) == ("GST/HST No. X1")


def test_imported_invoices_take_the_customers_address():
    src = (ROOT / "app" / "services" / "qbd_documents.py").read_text(encoding="utf-8")
    assert src.count("**_addresses(self.db,") == 3


def test_a_canadian_company_prints_no_country_under_a_canadian_address():
    from app.services.pdf_service import _canadian_country_line, _home_is_canada

    assert _home_is_canada({"sales_tax_system": "canada"})
    assert _home_is_canada({"company_country": "CA"})
    assert not _home_is_canada({"sales_tax_system": "us"})
    assert _canadian_country_line("CA") == ""
    assert _canadian_country_line("US") == "United States"
    assert _canadian_country_line("BB") == "Barbados"
    assert _canadian_country_line(None) == ""
