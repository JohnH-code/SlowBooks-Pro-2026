"""John's build: Make General Journal Entries laid out as QuickBooks Desktop
has it, saving through Journal Entries' own save."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "app" / "static" / "js"


def test_the_screen_is_loaded_after_journal_entries():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert html.index("/static/js/journal.js") < html.index(
        "/static/js/make_journal.js"
    )


def test_it_saves_through_the_journals_own_save():
    js = (JS / "make_journal.js").read_text(encoding="utf-8")
    assert "await JournalPage.save({ preventDefault() {}, target: f });" in js
    # QuickBooks' order, the balancing line, the buttons, Reverse
    assert "tr.replaceChildren(acct, debit, credit, desc, ...extras, remove);" in js
    assert "function suggest(tr)" in js
    for words in ("Save &amp; Close", "Save &amp; New", "'Revert'", "Reverse"):
        assert words in js, words
    # the description QuickBooks doesn't have: the first memo when blank
    assert "f.description.value = memo || 'General journal entry';" in js
