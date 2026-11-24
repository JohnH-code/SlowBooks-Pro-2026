"""John's build: Write Cheques' Clear and a Cancel button.

Clear looked dead while a receipt scan was still reading: the clicks
waited behind the scan, and the scan's late result could then be written
into the fresh form. Clear now dims the form at once, and a scan the form
was cleared or closed during is dropped. Cancel closes without saving,
asking first when something was entered."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WC = (ROOT / "app/static/js/write_cheques.js").read_text(encoding="utf-8")
OCR = (ROOT / "app/static/js/ocr.js").read_text(encoding="utf-8")


def test_there_is_a_cancel_button_beside_clear():
    clear = WC.index('onclick="ExpensesPage.qbClear()"')
    cancel = WC.index('onclick="ExpensesPage.qbCancel()"')
    assert clear < cancel < clear + 400
    assert ">Cancel</button>" in WC


def test_cancel_asks_only_when_something_was_entered():
    body = WC[WC.index("ExpensesPage.qbCancel = function") :]
    body = body[: body.index("};")]
    assert "qbBlank(form)" in body and "_qbSnap" in body
    assert "confirm(" in body
    assert "ScanHelper.discard()" in body and "closeModal()" in body


def test_clear_shows_at_once_and_once():
    body = WC[WC.index("ExpensesPage.qbClear = function") :]
    body = body[: body.index("};")]
    assert "form.dataset.clearing" in body
    assert "opacity" in body


def test_a_scan_cleared_or_closed_during_is_dropped():
    assert "_scanGen" in OCR
    scan = OCR[OCR.index("async scan(") :]
    assert "gen !== this._scanGen" in scan[: scan.index("summary(result)")]
    discard = OCR[OCR.index("async discard()") :]
    assert "this._scanGen++" in discard[: discard.index("API.del")]
