/**
 * Customize the top bar (John's build), as QuickBooks' Customize Icon Bar.
 *
 * The shortcuts between Home and the search box were fixed (New Customer,
 * Create Invoice, Receive Payment, Quick Entry, Bill Entry, Reports). They
 * are now chosen per company in Settings → Top Bar: which ones, and in
 * what order. Home, the company name, Back, Search and the right-hand
 * buttons always stay. The choice is the company setting topbar_shortcuts
 * (shortcut ids, comma separated). Left blank, the bar is Slowbooks' own
 * and is not touched.
 */
const TopbarShortcuts = {
    // id: [label, how it opens: a page ('#/…') or a form (Page.method)]
    ALL: {
        write_cheques:    ['Write Cheques', 'ExpensesPage.showForm'],
        make_deposits:    ['Make Deposits', '#/deposits'],
        enter_bills:      ['Enter Bills', 'BillsPage.showForm'],
        pay_bills:        ['Pay Bills', 'BillsPage.showPayForm'],
        bookkeeper:       ['Bookkeeper Inbox', '#/bookkeeper'],
        cc_charges:       ['CC Charges', '#/cc-charges'],
        banking:          ['Bank Accounts', '#/banking'],
        enter_cheques:    ['Enter Cheques', '#/expenses'],
        create_invoice:   ['Create Invoice', 'InvoicesPage.showForm'],
        receive_payment:  ['Receive Payment', 'PaymentsPage.showForm'],
        new_customer:     ['New Customer', 'CustomersPage.showForm'],
        customers:        ['Customers', '#/customers'],
        vendors:          ['Vendors', '#/vendors'],
        quick_entry:      ['Quick Entry', '#/quick-entry'],
        bill_entry:       ['Bill Entry', '#/bill-entry'],
        journal:          ['Journal Entries', '#/journal'],
        memorized:        ['Memorized Transactions', '#/memorized'],
        accounts:         ['Chart of Accounts', '#/accounts'],
        reports:          ['Reports', '#/reports'],
    },
    // Slowbooks' own bar, for a company that has not chosen
    DEFAULT: ['new_customer', 'create_invoice', 'receive_payment', 'quick_entry', 'bill_entry', 'reports'],

    parse(value) {
        if (value == null || value === '') return TopbarShortcuts.DEFAULT.slice();
        if (value === 'none') return [];
        return String(value).split(',').map(s => s.trim()).filter(id => TopbarShortcuts.ALL[id]);
    },

    // The pages' objects are top-level consts in their own scripts, so not
    // on window: reached here by name.
    _PAGES() {
        return {
            ExpensesPage: typeof ExpensesPage !== 'undefined' ? ExpensesPage : null,
            BillsPage: typeof BillsPage !== 'undefined' ? BillsPage : null,
            InvoicesPage: typeof InvoicesPage !== 'undefined' ? InvoicesPage : null,
            PaymentsPage: typeof PaymentsPage !== 'undefined' ? PaymentsPage : null,
            CustomersPage: typeof CustomersPage !== 'undefined' ? CustomersPage : null,
        };
    },

    _run(how) {
        if (how.startsWith('#/')) { if (typeof App !== 'undefined' && App.navigate) App.navigate(how); return; }
        const [page, method] = how.split('.');
        const obj = TopbarShortcuts._PAGES()[page] || window[page];
        if (obj && typeof obj[method] === 'function') obj[method]();
    },

    // The bar: the chosen buttons after Home, then the separator before Search.
    apply(ids) {
        const bar = document.getElementById('topbar');
        const home = bar && bar.querySelector('.tb-btn[data-nav="#/"]');
        if (!home) return;
        // the old shortcuts (and the separator that set Reports apart)
        let n = home.nextElementSibling;
        while (n && n.id !== 'global-search') {
            const next = n.nextElementSibling;
            if (n.classList.contains('tb-btn') || n.classList.contains('tb-sep')) n.remove();
            n = next;
        }
        const frag = document.createDocumentFragment();
        ids.forEach(id => {
            const [label, how] = TopbarShortcuts.ALL[id];
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'tb-btn';
            b.dataset.shortcut = id;
            if (how.startsWith('#/')) b.dataset.nav = how; else b.dataset.action = how;
            b.textContent = label;
            b.addEventListener('click', () => TopbarShortcuts._run(how));
            frag.appendChild(b);
        });
        const sep = document.createElement('div');
        sep.className = 'tb-sep';
        frag.appendChild(sep);
        home.after(frag);
        if (window.SlowbooksTopbar && SlowbooksTopbar.fit) SlowbooksTopbar.fit();
    },

    async load() {
        try {
            const s = await API.get('/settings');
            TopbarShortcuts._ids = TopbarShortcuts.parse(s.topbar_shortcuts);
            // not chosen: Slowbooks' own bar stays as the page drew it
            if (s.topbar_shortcuts) TopbarShortcuts.apply(TopbarShortcuts._ids);
        } catch (e) { /* not signed in yet: the next load tries again */ }
    },

    // Settings → Top Bar: tick the shortcuts, move them up or down, Save.
    sectionHtml(ids) {
        const order = ids.concat(Object.keys(TopbarShortcuts.ALL).filter(id => !ids.includes(id)));
        const rows = order.map(id => `
            <li data-id="${id}" style="display:flex; align-items:center; gap:6px; padding:2px 0;">
                <input type="checkbox" id="tbs-${id}" ${ids.includes(id) ? 'checked' : ''} style="width:auto;">
                <label for="tbs-${id}" style="font-weight:normal; flex:1; margin:0;">${escapeHtml(TopbarShortcuts.ALL[id][0])}</label>
                <button type="button" class="btn btn-sm btn-secondary" aria-label="Move ${escapeHtml(TopbarShortcuts.ALL[id][0])} up" onclick="TopbarShortcuts.move(this, -1)">&#9650;</button>
                <button type="button" class="btn btn-sm btn-secondary" aria-label="Move ${escapeHtml(TopbarShortcuts.ALL[id][0])} down" onclick="TopbarShortcuts.move(this, 1)">&#9660;</button>
            </li>`).join('');
        return `<div class="settings-section" data-group="company" id="settings-topbar" role="group" aria-labelledby="settings-h-topbar">
            <h3 id="settings-h-topbar">Top Bar</h3>
            <p style="font-size:11px; color:var(--text-muted); margin:0 0 8px;">The shortcuts across the top, after Home, for this company: tick the ones you want and put them in order. Home, Search and Sign Out always stay.</p>
            <ul id="tbs-list" style="list-style:none; padding:0; margin:0 0 8px; max-width:420px;">${rows}</ul>
            <button type="button" class="btn btn-sm btn-primary" onclick="TopbarShortcuts.save()" data-admin>Save Top Bar</button>
            <button type="button" class="btn btn-sm btn-secondary" onclick="TopbarShortcuts.reset()" data-admin>Start again</button>
        </div>`;
    },

    move(button, step) {
        const li = button.closest('li');
        const other = step < 0 ? li.previousElementSibling : li.nextElementSibling;
        if (!other) return;
        if (step < 0) other.before(li); else other.after(li);
        button.focus();
    },

    chosen() {
        return [...document.querySelectorAll('#tbs-list li')]
            .filter(li => li.querySelector('input').checked)
            .map(li => li.dataset.id);
    },

    async save() {
        const ids = TopbarShortcuts.chosen();
        try {
            await API.put('/settings', { topbar_shortcuts: ids.length ? ids.join(',') : 'none' });
            TopbarShortcuts._ids = ids;
            TopbarShortcuts.apply(ids);
            toast('Top bar saved');
        } catch (err) { toast(err.message, 'error'); }
    },

    reset() {
        const host = document.getElementById('settings-topbar');
        if (!host) return;
        const t = document.createElement('template');
        t.innerHTML = TopbarShortcuts.sectionHtml(TopbarShortcuts.DEFAULT);
        host.replaceWith(t.content.firstElementChild);
    },
};
window.TopbarShortcuts = TopbarShortcuts;

(function () {
    // after sign-in and on switching company: the app loads the company's
    // settings then (loadCompanySettings)
    if (typeof App !== 'undefined' && typeof App.loadCompanySettings === 'function') {
        const base = App.loadCompanySettings;
        App.loadCompanySettings = async function () {
            const out = await base.apply(this, arguments);
            TopbarShortcuts.load();
            return out;
        };
    }

    // Settings: the Top Bar section, put in the page's markup (as a string,
    // the rest untouched) before Company Logo. No waiting here: Settings
    // sets up its groups straight after its render returns.
    if (typeof SettingsPage !== 'undefined' && typeof SettingsPage.render === 'function') {
        const baseRender = SettingsPage.render;
        SettingsPage.render = async function () {
            const html = await baseRender.apply(this, arguments);
            const at = html.indexOf('<div class="settings-section" data-group="company" role="group" aria-labelledby="settings-h-company-logo">');
            if (at < 0) return html;
            return html.slice(0, at) + TopbarShortcuts.sectionHtml(TopbarShortcuts._ids || TopbarShortcuts.DEFAULT) + html.slice(at);
        };
    }
})();
