"""John's build: a record's Attachments box attaches in one step.

The box had a file chooser and an Attach (or Upload) button beside it:
choose, then attach. app/static/js/one_step_attach.js hides the chooser
and makes the button "Attach File…": it opens the chooser, and the file
picked is attached at once by the page's own upload code."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "app/static/js/one_step_attach.js").read_text(encoding="utf-8")


def test_the_page_loads_it_after_the_attachment_boxes():
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    assert index.index("one_step_attach.js") > index.index("payment_attachments.js")


@pytest.mark.parametrize(
    "page, input_id",
    [
        ("deposits.js", "deposit-attach-file"),
        ("expenses.js", "expense-attach-file"),
        ("journal.js", "journal-attach-file"),
        ("bills.js", "bill-attach-file"),
        ("invoices.js", "inv-attach-file"),
    ],
)
def test_every_attachments_box_is_one_it_fits(page, input_id):
    """Each box is a file input with the Attach/Upload button right after
    it, the shape the script looks for."""
    src = (ROOT / "app/static/js" / page).read_text(encoding="utf-8")
    at = src.index(f'id="{input_id}"')
    after = src[at : at + 260]
    assert "<button" in after and (
        "Attach</button>" in after or "Upload</button>" in after
    )
    assert input_id.endswith("-attach-file")


def test_the_payment_box_fits_too():
    src = (ROOT / "app/static/js/payment_attachments.js").read_text(encoding="utf-8")
    assert 'class="record-files-input"' in src
    assert ".record-files-input" in JS


def test_the_button_opens_the_chooser_and_a_choice_attaches():
    assert "Attach File…" in JS
    assert "input.click()" in JS and "button.click()" in JS
    # the page's own upload still reads the file from the input
    assert "input.hidden = true" in JS
