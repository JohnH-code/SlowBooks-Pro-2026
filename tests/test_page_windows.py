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


def test_a_mac_gets_a_window_menu_listing_the_windows(monkeypatch):
    """The Window menu becomes the application's windows menu, which macOS
    fills with the open windows to switch between."""
    import desktop_launcher

    calls = {}

    class _Menu:
        def __init__(self):
            self.items = []

        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return self

        def initWithTitle_(self, title):
            self.title = title
            return self

        def addItemWithTitle_action_keyEquivalent_(self, t, a, k):
            self.items.append((t, a, k))

        def addItem_(self, item):
            self.items.append(item)

    class _Item:
        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return self

        @staticmethod
        def separatorItem():
            return "-"

        def setTitle_(self, t):
            self.title = t

        def setSubmenu_(self, m):
            self.submenu = m

    class _App:
        @staticmethod
        def sharedApplication():
            return _App()

        def setWindowsMenu_(self, m):
            calls["windows_menu"] = m

    class _BrowserView:
        def _recreate_menus(self, user_menu):
            return _Menu()

    appkit = types.SimpleNamespace(NSMenu=_Menu, NSMenuItem=_Item, NSApplication=_App)
    cocoa = types.SimpleNamespace(BrowserView=_BrowserView)
    monkeypatch.setattr(desktop_launcher.sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "webview.platforms", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "webview.platforms.cocoa", cocoa)
    assert desktop_launcher.install_mac_window_menu() is True
    bar = _BrowserView()._recreate_menus(None)
    window_item = bar.items[-1]
    assert window_item.title == "Window"
    titles = [i[0] for i in window_item.submenu.items if isinstance(i, tuple)]
    assert titles == ["Minimize", "Zoom", "Bring All to Front"]
    assert calls["windows_menu"] is window_item.submenu


def test_the_closing_handler_answers_none():
    """pywebview adds each handler's answer to a set: a dict there is
    "unhashable type: 'dict'" in the log on every quit."""
    import inspect

    import desktop_launcher

    src = inspect.getsource(desktop_launcher)
    assert "events.closing += lambda *_a: api.close_app_windows()\n" not in src
    assert "lambda *_a: (api.close_app_windows(), None)[1]" in src
