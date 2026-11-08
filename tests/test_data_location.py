"""John's build: the company files can live in a folder of the person's
choosing (data-location.txt beside the default data folder), so they are
backed up with everything else, as QuickBooks' company files can be."""

from pathlib import Path

import desktop_launcher as dl


def _home(tmp_path, monkeypatch):
    default = tmp_path / "AppSupport" / "SlowBooksPro" / "data"
    default.mkdir(parents=True)
    monkeypatch.setattr(dl, "default_data_dir", lambda: default)
    monkeypatch.delenv("SLOWBOOKS_DATA_DIR", raising=False)
    return default


def test_without_the_file_the_data_stays_in_the_default_place(tmp_path, monkeypatch):
    default = _home(tmp_path, monkeypatch)
    assert dl.get_data_dir() == default


def test_the_file_names_the_folder(tmp_path, monkeypatch):
    default = _home(tmp_path, monkeypatch)
    chosen = tmp_path / "DATA" / "Slowbooks" / "data"
    (default.parent / "data-location.txt").write_text(
        f"# where the books are\n{chosen}\n", encoding="utf-8"
    )
    assert dl.get_data_dir() == chosen
    # the .env (the settings key) goes with the books
    assert dl.env_file() == chosen.parent / ".env" or not dl.FROZEN


def test_the_command_line_still_wins(tmp_path, monkeypatch):
    default = _home(tmp_path, monkeypatch)
    (default.parent / "data-location.txt").write_text(
        "/somewhere/else\n", encoding="utf-8"
    )
    monkeypatch.setenv("SLOWBOOKS_DATA_DIR", str(tmp_path / "cli"))
    assert dl.get_data_dir() == Path(tmp_path / "cli")


def test_a_blank_file_is_no_choice(tmp_path, monkeypatch):
    default = _home(tmp_path, monkeypatch)
    (default.parent / "data-location.txt").write_text("\n# nothing\n", encoding="utf-8")
    assert dl.get_data_dir() == default
