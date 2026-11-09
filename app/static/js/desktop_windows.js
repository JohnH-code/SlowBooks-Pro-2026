/**
 * Each page in a window of its own, in the desktop app (John's build).
 *
 * As QuickBooks opens each list and form in its own window: in the desktop
 * app a sidebar item opens its page in a new window (one already open is
 * brought forward), and closing that window closes the page. The main
 * window stays where it is. Option-click (Alt-click) a sidebar item to open
 * it in the main window instead. A page window has no sidebar; its links
 * move within it, and its forms open over it as before.
 *
 * In a browser, and where the desktop app cannot open windows, the sidebar
 * works as it always has.
 */
const PageWindows = {
    // this window is a page window (?window=page in its address)
    isPage: new URLSearchParams(location.search).get('window') === 'page',

    api() {
        const api = window.pywebview && window.pywebview.api;
        return api && typeof api.open_app_window === 'function' ? api : null;
    },

    async open(route, title) {
        const api = PageWindows.api();
        if (!api) return false;
        try {
            const r = await api.open_app_window(route, title || 'SlowBooks Pro 2026');
            if (r && r.success) return true;
            if (r && r.error) toast(`Could not open a new window: ${r.error}`, 'error');
        } catch (err) { /* fall back to this window */ }
        return false;
    },

    start() {
        if (PageWindows.isPage) {
            // a page window: the page alone, no sidebar or its toggle
            document.body.classList.add('page-window', 'sidebar-hidden');
            return;
        }
        document.addEventListener('click', async evt => {
            const a = evt.target.closest && evt.target.closest('#sidebar a.nav-link[href^="#/"]');
            if (!a || evt.metaKey || evt.ctrlKey || evt.shiftKey || evt.button !== 0) return;
            const route = a.getAttribute('href');
            if (evt.altKey) {  // Option-click: this window, as before
                evt.preventDefault();
                evt.stopPropagation();
                App.navigate(route);
                return;
            }
            if (route === '#/' || !PageWindows.api()) return;  // Home stays in the main window
            evt.preventDefault();
            evt.stopPropagation();
            const title = (a.textContent || '').replace(/\s+/g, ' ').trim().replace(/^[^\p{L}\p{N}]+/u, '');
            if (!(await PageWindows.open(route, title))) App.navigate(route);
        }, true);
    },
};

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => PageWindows.start());
else PageWindows.start();

// Home redraws when you come back to it (John's build). With each page in
// its own window, the import or a bill entered in another window left the
// main window's Home as it was drawn: an empty company's $0 receivables and
// a starting chart's Checking / Savings / Credit Card, after the import had
// finished. Coming back to the window (after more than a second away, and
// with no dialog open) draws Home again from the books.
(function () {
    if (typeof window === 'undefined' || typeof window.addEventListener !== 'function') return;
    const onHome = () => {
        const h = (location.hash || '#/').split('?')[0];
        return h === '#/' || h === '#' || h === '#/dashboard';
    };
    const dialogOpen = () => {
        const o = document.getElementById('modal-overlay');
        return !!(o && !o.classList.contains('hidden'));
    };
    let away = 0;
    const left = () => { away = Date.now(); };
    const back = () => {
        const was = away;
        away = 0;
        if (!was || Date.now() - was < 1000) return;
        if (!onHome() || dialogOpen() || typeof App === 'undefined' || !App.navigate) return;
        App.navigate(location.hash || '#/');
    };
    window.addEventListener('blur', left);
    window.addEventListener('focus', back);
    document.addEventListener('visibilitychange', () => (document.hidden ? left() : back()));
})();
