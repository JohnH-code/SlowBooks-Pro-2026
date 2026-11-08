"""John's build: in the desktop app each sidebar page opens in a window of
its own, as QuickBooks' lists and forms do (desktop_launcher.open_app_window,
static/js/desktop_windows.js)."""

import sys
import types
from pathlib import Path

import pytest

JS = (
    Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "desktop_windows.js"
)


class _Events:
    def __init__(self):
        self.closed = _Hook()
        self.closing = _Hook()


class _Hook(list):
    def __iadd__(self, fn):
        self.append(fn)
        return self


class _Win:
    def __init__(self, title, url, **kw):
        self.title, self.url, self.kw = title, url, kw
        self.events = _Events()
        self.shown = self.destroyed = 0
        self.on_top = False
        self.width, self.height = 1400, 900

    def restore(self):
        pass

    def show(self):
        self.shown += 1

    def destroy(self):
        self.destroyed += 1
        for fn in self.events.closed:
            fn()


@pytest.fixture
def api(monkeypatch):
    import desktop_launcher

    made = []

    def create_window(title, url=None, **kw):
        w = _Win(title, url, **kw)
        made.append(w)
        return w

    monkeypatch.setitem(
        sys.modules, "webview", types.SimpleNamespace(create_window=create_window)
    )
    a = desktop_launcher.PickerApi(3001)
    a._server = object()  # a company is open
    return a, made


def test_a_page_opens_in_its_own_window_on_the_company_address(api):
    a, made = api
    r = a.open_app_window("#/bills", "Bills")
    assert r == {"success": True}
    assert made[0].title == "Bills"
    assert made[0].url == "http://127.0.0.1:3001/?window=page#/bills"
    assert made[0].kw["js_api"] is a


def test_a_page_already_open_is_brought_forward_not_opened_twice(api):
    a, made = api
    a.open_app_window("#/bills", "Bills")
    r = a.open_app_window("#/bills", "Bills")
    assert r["existing"] is True and len(made) == 1 and made[0].shown == 1
    # closed, it opens again
    made[0].destroy()
    a.open_app_window("#/bills", "Bills")
    assert len(made) == 2


def test_only_the_apps_own_pages_and_only_with_a_company_open(api):
    a, made = api
    assert a.open_app_window("https://example.com", "x")["success"] is False
    a._server = None
    assert a.open_app_window("#/bills", "Bills")["success"] is False
    assert made == []


def test_the_page_windows_close_with_the_company(api):
    a, made = api
    a.open_app_window("#/bills", "Bills")
    a.open_app_window("#/invoices", "Invoices")
    a.close_app_windows()
    assert [w.destroyed for w in made] == [1, 1]
    assert a._children == {}


def test_the_sidebar_opens_pages_in_windows_home_stays():
    js = JS.read_text()
    assert "open_app_window" in js
    assert "route === '#/'" in js  # Home stays in the main window
    assert "evt.altKey" in js  # Option-click keeps the main window
    assert "'page-window', 'sidebar-hidden'" in js
