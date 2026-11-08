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


def test_the_settings_key_goes_with_the_books(tmp_path, monkeypatch):
    default = _home(tmp_path, monkeypatch)
    monkeypatch.setattr(dl, "FROZEN", True)
    chosen = tmp_path / "DATA" / "Slowbooks"
    chosen.mkdir(parents=True)
    (default.parent / "data-location.txt").write_text(f"{chosen}\n", encoding="utf-8")
    assert dl.env_file() == chosen / ".env"
    # still so once the launcher pins the folder for the app
    monkeypatch.setenv("SLOWBOOKS_DATA_DIR", str(chosen))
    assert dl.env_file() == chosen / ".env"
    # the computer's own font set-up stays in the platform's place
    assert dl._config_dir() == default.parent


def test_a_first_move_s_layout_still_finds_its_key(tmp_path, monkeypatch):
    """The first move put the books in Slowbooks/data and the key beside
    that folder; until the folder is tidied the key is read from there."""
    default = _home(tmp_path, monkeypatch)
    monkeypatch.setattr(dl, "FROZEN", True)
    chosen = tmp_path / "DATA" / "Slowbooks" / "data"
    chosen.mkdir(parents=True)
    (chosen.parent / ".env").write_text("K=1\n", encoding="utf-8")
    (default.parent / "data-location.txt").write_text(f"{chosen}\n", encoding="utf-8")
    assert dl.env_file() == chosen.parent / ".env"


def test_with_no_chosen_folder_the_key_stays_where_it_was(tmp_path, monkeypatch):
    default = _home(tmp_path, monkeypatch)
    monkeypatch.setattr(dl, "FROZEN", True)
    assert dl.env_file() == default.parent / ".env"


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
