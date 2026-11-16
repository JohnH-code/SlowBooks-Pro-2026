/**
 * Reminders for memorized transactions (John's build), as QuickBooks'
 * Reminders window does them.
 *
 * A "Remind me" schedule only sat on Memorized Transactions' Due now list,
 * so a cheque came due with nothing to say so. Now:
 *   - when the app opens, and on the first Home of each new day while it
 *     stays open, a window lists every memorized transaction due within
 *     the reminder window (Settings: memorized_remind_days, 5 by default),
 *     overdue first, each with Enter (the Enter now dialog) beside it;
 *   - Home carries a line saying how many are due, while any are.
 * Page windows (?window=page) show the Home line but not the window.
 */
const MemorizedReminders = {
    _KEY: 'sb_memorized_reminded_on',

    async upcoming() {
        try {
            return await API.get('/memorized/upcoming');
        } catch (e) {
            return null;  // signed out, or a role that may not read schedules
        }
    },

    _whenText(r) {
        if (r.when === 'overdue') {
            const n = -r.days_away;
            return `<strong style="color:var(--danger, #b42318);">Overdue</strong> (${formatDate(r.next_date)}, ${n} day${n === 1 ? '' : 's'} ago)`;
        }
        if (r.when === 'today') return `<strong>Due today</strong> (${formatDate(r.next_date)})`;
        return `Due ${formatDate(r.next_date)} (in ${r.days_away} day${r.days_away === 1 ? '' : 's'})`;
    },

    _kindWord(kind) {
        return kind === 'expense' ? 'Cheque' : kind === 'bill' ? 'Bill' : kind === 'invoice' ? T('Invoice') : 'Journal entry';
    },

    // The window: what is due, with Enter beside each.
    async show(data) {
        data = data || await MemorizedReminders.upcoming();
        if (!data || !data.items || !data.items.length) return false;
        MemorizedReminders._items = data.items;
        const rows = data.items.map(r => `
            <tr data-mem="${escapeHtml(r.kind)}-${Number(r.id)}">
                <td>${MemorizedReminders._whenText(r)}</td>
                <td>${escapeHtml(MemorizedReminders._kindWord(r.kind))}</td>
                <td><strong>${escapeHtml(r.party || r.name)}</strong>${r.memo ? `<div style="font-size:11px; color:var(--text-muted);">${escapeHtml(r.memo)}</div>` : ''}</td>
                <td class="amount">${formatCurrency(r.amount)}</td>
                <td style="text-align:right;">${r.status === 'active' ? `<button type="button" class="btn btn-sm btn-primary" onclick="MemorizedReminders.enter('${escapeHtml(r.kind)}', ${Number(r.id)})">Enter</button>` : ''}</td>
            </tr>`).join('');
        openModal('Memorized transactions due', `
            <p style="margin-bottom:8px;">Due today or in the next ${data.days} day${data.days === 1 ? '' : 's'}:</p>
            <div class="table-container"><table>
                <thead><tr><th scope="col">When</th><th scope="col">Type</th><th scope="col">Payee / name</th><th scope="col" class="amount">Amount</th><th scope="col"></th></tr></thead>
                <tbody>${rows}</tbody>
            </table></div>
            <p class="hint" style="margin-top:8px;">Enter asks for the date (the scheduled one or today) and enters it; a cheque is then in the register to print. The reminder window is set on Memorized Transactions.</p>
            <div class="form-actions">
                <button type="button" class="btn btn-secondary" onclick="closeModal(); App.navigate('#/memorized')">Open Memorized Transactions</button>
                <button type="button" class="btn btn-primary" onclick="closeModal()">Remind me later</button>
            </div>`);
        return true;
    },

    // Enter: the page's own Enter now dialog, with the row it needs.
    enter(kind, id) {
        const r = (MemorizedReminders._items || []).find(x => x.kind === kind && Number(x.id) === Number(id));
        if (typeof MemorizedPage === 'undefined') return;
        if (r) {
            MemorizedPage._rows = MemorizedPage._rows || [];
            if (!MemorizedPage.row(kind, id)) MemorizedPage._rows.push(r);
        }
        closeModal();
        MemorizedPage.enter(kind, id);
    },

    _today() {
        return typeof todayISO === 'function' ? todayISO() : new Date().toISOString().slice(0, 10);
    },

    // Once a day per window: on opening, and on the first Home of a new day.
    async maybeShow() {
        if (/[?&]window=page\b/.test(location.search)) return;
        // not under browser automation (the test suite's shared server holds
        // other tests' schedules, and a window popping up over their pages
        // would stop them); the Home line still shows
        if (navigator.webdriver) return;
        let shownOn = null;
        try { shownOn = localStorage.getItem(MemorizedReminders._KEY); } catch (e) { /* no storage */ }
        if (shownOn === MemorizedReminders._today()) return;
        const data = await MemorizedReminders.upcoming();
        if (!data) return;  // not signed in yet: try again after sign-in
        try { localStorage.setItem(MemorizedReminders._KEY, MemorizedReminders._today()); } catch (e) { /* no storage */ }
        // not over a dialog someone is already working in
        const overlay = document.getElementById('modal-overlay');
        if (overlay && !overlay.classList.contains('hidden')) return;
        await MemorizedReminders.show(data);
    },

    // The line on Home while anything is due.
    async homeLine() {
        const data = await MemorizedReminders.upcoming();
        const host = document.getElementById('mem-reminder-line');
        if (!host) return;
        if (!data || !data.items || !data.items.length) { host.remove(); return; }
        const late = data.items.filter(r => r.when === 'overdue').length;
        const today = data.items.filter(r => r.when === 'today').length;
        const n = data.items.length;
        const parts = [];
        if (late) parts.push(`${late} overdue`);
        if (today) parts.push(`${today} due today`);
        host.innerHTML = `<span><strong>${n} memorized transaction${n === 1 ? '' : 's'}</strong> due within ${data.days} day${data.days === 1 ? '' : 's'}${parts.length ? ` (${parts.join(', ')})` : ''}.</span>
            <button type="button" class="btn btn-sm btn-primary" onclick="MemorizedReminders.show()">Review</button>`;
        host.hidden = false;
    },
};

(function () {
    if (typeof App === 'undefined') return;
    // on opening, beside the collections reminders
    if (typeof App.checkReminders === 'function') {
        const base = App.checkReminders;
        App.checkReminders = function () {
            const out = base.apply(this, arguments);
            setTimeout(() => MemorizedReminders.maybeShow(), 600);
            return out;
        };
    }
    // Home: the line, and the day's window when the app has been open
    // since an earlier day
    if (typeof DashboardPage !== 'undefined' && typeof DashboardPage.render === 'function') {
        const baseRender = DashboardPage.render;
        DashboardPage.render = async function () {
            const html = await baseRender.apply(this, arguments);
            setTimeout(() => {
                MemorizedReminders.homeLine();
                MemorizedReminders.maybeShow();
            }, 0);
            return `<div id="mem-reminder-line" class="mem-reminder-line" role="status" hidden></div>${html}`;
        };
    }
})();

// The reminder window, on Memorized Transactions beside the auto-enter box.
(function () {
    if (typeof MemorizedPage === 'undefined' || typeof MemorizedPage.render !== 'function') return;
    const baseRender = MemorizedPage.render;
    MemorizedPage.render = async function () {
        const html = await baseRender.apply(this, arguments);
        let days = 5;
        try {
            const s = await API.get('/settings');
            const n = parseInt(s.memorized_remind_days, 10);
            if (!Number.isNaN(n)) days = n;
        } catch (e) { /* keep 5 */ }
        const field = `<div class="form-group" style="margin:6px 0 10px;">
            <label for="mem-remind-days" style="font-weight:normal;">Remind me
            <input type="number" id="mem-remind-days" name="memorized_remind_days" min="0" max="60" value="${days}" style="width:60px; display:inline-block; margin:0 4px;" onchange="MemorizedReminders.setDays(this)" data-admin>
            days before a memorized transaction is due (when the app opens, and on Home)</label></div>`;
        const t = document.createElement('template');
        t.innerHTML = html;
        const box = t.content.getElementById('mem-auto-enter');
        const label = box && box.closest('label');
        if (label) {
            label.insertAdjacentHTML('afterend', field);
            return t.innerHTML;
        }
        return field + html;
    };
})();

MemorizedReminders.setDays = async function (input) {
    const n = Math.max(0, Math.min(60, parseInt(input.value, 10) || 0));
    input.value = n;
    try {
        await API.put('/settings', { memorized_remind_days: String(n) });
        toast(n ? `You'll be reminded ${n} day${n === 1 ? '' : 's'} before a memorized transaction is due` : 'You\'ll be reminded on the day a memorized transaction is due');
    } catch (err) {
        toast(err.message, 'error');
    }
};
