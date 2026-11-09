"""John's build: the logo prints at the size chosen in Settings."""

from app.routes.settings import ENUM_SETTINGS
from app.services.pdf_service import LOGO_SIZES, _sized_logo

PAGE = "<html><head><style>.company-logo { max-height: 60px; }</style></head><body></body></html>"


def test_small_is_the_size_it_always_was():
    assert _sized_logo(PAGE, {}) == PAGE
    assert _sized_logo(PAGE, {"invoice_logo_size": "small"}) == PAGE
    assert _sized_logo(PAGE, {"invoice_logo_size": "huge"}) == PAGE


def test_a_bigger_size_follows_the_templates_own_rule():
    out = _sized_logo(PAGE, {"invoice_logo_size": "large"})
    assert "max-height: 1.25in !important" in out
    assert out.index("1.25in") > out.index("60px")
    assert set(LOGO_SIZES) == ENUM_SETTINGS["invoice_logo_size"]


def test_settings_offers_it():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "app/static/js/settings.js").read_text()
    assert 'name="invoice_logo_size"' in js
