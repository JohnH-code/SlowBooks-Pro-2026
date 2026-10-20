/**
 * Memorized Transactions — QuickBooks' Memorized Transaction List: cheques,
 * bills, deposits, journal entries and invoices kept as patterns, entered
 * again by hand, when their reminder comes due, or automatically.
 */
const Memorized = {
    KINDS: { expense: 'Cheque / Expense', bill: 'Bill', deposit: 'Deposit', journal: 'Journal Entry', invoice: 'invoice' },
    FREQ: [['never', 'Never (enter by hand)'], ['weekly', 'Weekly'], ['biweekly', 'Every two weeks'], ['monthly', 'Monthly'],
           ['quarterly', 'Quarterly'], ['semiannually', 'Twice a year'], ['annually', 'Annually']],
    ACTIONS: [['remind', 'Remind me'], ['auto', 'Automatically enter'], ['none', "Don't remind me"]],

    _scheduleFields(m) {
        const opt = (list, v) => list.map(([k, l]) => `<option value="${k}" ${k === v ? 'selected' : ''}>${l}</option>`).join('');
        return `
            <div class="form-grid">
                <div class="form-group full-width"><label>Name *</label><input name="name" required maxlength="200" value="${escapeHtml(m.name || '')}"></div>
                <div class="form-group"><label>When</label><select name="action">${opt(Memorized.ACTIONS, m.action || 'remind')}</select></div>
                <div class="form-group"><label>How often</label><select name="frequency">${opt(Memorized.FREQ, m.frequency || 'monthly')}</select></div>
                <div class="form-group"><label>Next date</label><input name="next_date" type="date" value="${m.next_date || ''}"></div>
                <div class="form-group"><label>Days in advance to remind / enter</label><input name="days_in_advance" type="number" min="0" max="365" value="${m.days_in_advance || 0}"></div>
                <div class="form-group"><label>Number remaining</label><input name="remaining" type="number" min="0" placeholder="no end" value="${m.remaining ?? ''}"></div>
            </div>`;
    },

    // Fields by name: form.name and form.action are the form's own
    // properties, not the inputs called "name" and "action".
    _field(form, name) { return form.querySelector(`[name="${name}"]`); },

    _read(form) {
        const v = n => { const el = Memorized._field(form, n); return el ? el.value : ''; };
        return {
            name: v('name').trim(),
            action: v('action'),
            frequency: v('frequency'),
            next_date: v('next_date') || null,
            days_in_advance: parseInt(v('days_in_advance')) || 0,
            remaining: v('remaining') === '' ? null : parseInt(v('remaining')),
        };
    },

    // Memorize an entered transaction: ref is {transaction_id} | {bill_id} | {invoice_id}.
    open(ref, suggestedName) {
        const next = new Date(); next.setMonth(next.getMonth() + 1);
        openModal('Memorize Transaction', `
            <form id="memorize-form" onsubmit="Memorized.save(event)">
                ${Memorized._scheduleFields({ name: suggestedName || '', next_date: next.toISOString().slice(0, 10) })}
                <p style="font-size:11px; color:var(--gray-500);">The accounts, amounts and memos are kept as they are now. Enter it again from Lists → Memorized Transactions, or from the reminder on the Snapshot.</p>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Memorize</button>
                </div>
            </form>`);
        Memorized._ref = ref;
    },

    async save(e) {
        e.preventDefault();
        try {
            await API.post('/memorized/from-transaction', { ...Memorized._ref, ...Memorized._read(e.target) });
            toast('Memorized');
            closeModal();
        } catch (err) { toast(err.message, 'error'); }
    },

    button(ref, name) {
        return `<button type="button" class="btn btn-secondary" data-write onclick='Memorized.open(${JSON.stringify(ref)}, ${escapeHtml(JSON.stringify(name || ''))})'>Memorize</button>`;
    },
};

const MemorizedPage = {
    async render() {
        const rows = await API.get('/memorized');
        const kind = k => k === 'invoice' ? T('Invoice') : (Memorized.KINDS[k] || k);
        const freq = f => (Memorized.FREQ.find(x => x[0] === f) || [f, f])[1];
        const act = a => (Memorized.ACTIONS.find(x => x[0] === a) || [a, a])[1];
        const body = rows.map(m => `<tr${m.is_active ? '' : ' style="color:var(--gray-400)"'}>
            <td>${escapeHtml(m.name)}</td><td>${kind(m.kind)}</td><td>${escapeHtml(m.account)}</td>
            <td class="amount">${formatCurrency(m.amount)}</td><td>${freq(m.frequency)}</td>
            <td>${m.next_date ? formatDate(m.next_date) : '—'}</td><td>${act(m.action)}</td>
            <td style="white-space:nowrap;">
                <button class="btn btn-sm btn-primary" data-write onclick="MemorizedPage.enter(${m.id})">Enter</button>
                <button class="btn btn-sm btn-secondary" data-write onclick="MemorizedPage.edit(${m.id})">Edit</button>
                ${m.next_date ? `<button class="btn btn-sm btn-secondary" data-write onclick="MemorizedPage.skip(${m.id})">Skip</button>` : ''}
                <button class="btn btn-sm btn-danger" data-destructive onclick="MemorizedPage.remove(${m.id})">Delete</button>
            </td></tr>`).join('');
        MemorizedPage._rows = rows;
        return `
            <div class="page-header"><h2>Memorized Transactions</h2></div>
            <p style="font-size:11px; color:var(--gray-500); margin:-4px 0 8px;">To add one, open an entered cheque, bill, deposit, journal entry or invoice and choose Memorize.</p>
            <div class="table-container"><table>
                <thead><tr><th scope="col">Name</th><th scope="col">Type</th><th scope="col">Account</th><th scope="col" class="amount">Amount</th>
                    <th scope="col">How often</th><th scope="col">Next date</th><th scope="col">When</th><th scope="col">Actions</th></tr></thead>
                <tbody>${body || '<tr><td colspan="8" style="text-align:center; color:var(--gray-400);">Nothing memorized yet</td></tr>'}</tbody>
            </table></div>`;
    },

    _row(id) { return (MemorizedPage._rows || []).find(m => m.id === id) || {}; },

    // Enter: the date (its next date, else today) and, for a one-line cheque
    // or deposit, the amount — a hydro bill differs every month.
    enter(id) {
        const m = MemorizedPage._row(id);
        const lines = (m.payload && (m.payload.lines || m.payload.other_lines)) || [];
        const oneLine = (m.kind === 'expense' || m.kind === 'deposit') && lines.length === 1;
        openModal(`Enter ${escapeHtml(m.name)}`, `
            <form onsubmit="MemorizedPage.doEnter(event, ${id})">
                <div class="form-grid">
                    <div class="form-group"><label>Date</label><input name="date" type="date" required value="${m.next_date || todayISO()}"></div>
                    ${oneLine ? `<div class="form-group"><label>Amount</label><input name="amount" type="number" step="0.01" value="${Number(m.amount).toFixed(2)}"></div>` : `<div class="form-group"><label>Amount</label><div style="padding-top:6px;">${formatCurrency(m.amount)}</div></div>`}
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Enter</button>
                </div>
            </form>`);
    },

    async doEnter(e, id) {
        e.preventDefault();
        const f = e.target;
        const body = { date: f.date.value };
        if (f.amount && f.amount.value !== '') {
            const m = MemorizedPage._row(id);
            if (Math.abs(parseFloat(f.amount.value) - m.amount) >= 0.005) body.amount = parseFloat(f.amount.value);
        }
        try {
            const r = await API.post(`/memorized/${id}/enter`, body);
            toast(`Entered ${r.memorized.name}`);
            closeModal();
            App.refresh();
        } catch (err) { toast(err.message, 'error'); }
    },

    // Edit: the pattern (payee, accounts, lines) and the schedule together,
    // as QuickBooks' Edit Memorized Transaction does.
    _COLS: {
        expense: [['account_id', 'Account', 'account'], ['memo', 'Memo', 'text'], ['amount', 'Amount', 'money']],
        deposit: [['account_id', 'From account', 'account'], ['memo', 'Memo', 'text'], ['amount', 'Amount', 'money']],
        journal: [['account_id', 'Account', 'account'], ['description', 'Memo', 'text'], ['debit', 'Debit', 'money'], ['credit', 'Credit', 'money']],
        bill:    [['account_id', 'Account', 'account'], ['description', 'Description', 'text'], ['quantity', 'Qty', 'number'], ['rate', 'Rate', 'money']],
        invoice: [['item_id', 'Item', 'item'], ['description', 'Description', 'text'], ['quantity', 'Qty', 'number'], ['rate', 'Rate', 'money']],
    },

    async edit(id) {
        const m = MemorizedPage._row(id);
        const [accounts, vendors, customers, items] = await Promise.all([
            API.get('/accounts'),
            m.kind === 'bill' ? API.get('/vendors?active_only=true') : [],
            m.kind === 'invoice' ? API.get('/customers?active_only=true') : [],
            m.kind === 'invoice' ? API.get('/items?active_only=true').catch(() => []) : [],
        ]);
        MemorizedPage._lists = { accounts: accounts.filter(a => a.is_active !== false), items };
        const p = m.payload || {};
        const sel = (name, list, value, label) => `<select name="${name}"><option value="">Select…</option>${list.map(x =>
            `<option value="${x.id}" ${String(x.id) === String(value) ? 'selected' : ''}>${escapeHtml(label(x))}</option>`).join('')}</select>`;
        const acctLabel = a => `${a.account_number || ''} ${a.name}`.trim();
        const banks = accounts.filter(a => a.bank_kind);
        let head = '';
        if (m.kind === 'expense') {
            head = `<div class="form-group"><label>Payee</label><input name="payee" value="${escapeHtml(p.payee || '')}"></div>
                <div class="form-group"><label>Paid from</label>${sel('paid_from_account_id', banks, p.paid_from_account_id, acctLabel)}</div>`;
        } else if (m.kind === 'deposit') {
            head = `<div class="form-group"><label>Deposit to</label>${sel('deposit_to_account_id', banks, p.deposit_to_account_id, acctLabel)}</div>`;
        } else if (m.kind === 'journal') {
            head = `<div class="form-group full-width"><label>Description</label><input name="description" value="${escapeHtml(p.description || '')}"></div>`;
        } else if (m.kind === 'bill') {
            head = `<div class="form-group"><label>Vendor</label>${sel('vendor_id', vendors, p.vendor_id, v => v.name)}</div>
                <div class="form-group"><label>Terms</label><input name="terms" value="${escapeHtml(p.terms || 'Net 30')}"></div>`;
        } else if (m.kind === 'invoice') {
            head = `<div class="form-group"><label>${T('Customer')}</label>${sel('customer_id', customers, p.customer_id, c => c.name)}</div>
                <div class="form-group"><label>Terms</label><input name="terms" value="${escapeHtml(p.terms || 'Net 30')}"></div>`;
        }
        const cols = MemorizedPage._COLS[m.kind];
        const lines = (m.kind === 'deposit' ? p.other_lines : p.lines) || [];
        openModal(`Edit ${escapeHtml(m.name)}`, `
            <form id="memorized-edit" onsubmit="MemorizedPage.saveEdit(event, ${id})">
                <div class="form-grid">${head}</div>
                <table class="split-lines" style="width:100%; margin:8px 0;">
                    <thead><tr>${cols.map(c => `<th scope="col"${c[2] === 'money' || c[2] === 'number' ? ' class="amount"' : ''}>${c[1]}</th>`).join('')}<th scope="col"></th></tr></thead>
                    <tbody id="memorized-lines"></tbody>
                    <tfoot><tr><td colspan="${cols.length + 1}"><button type="button" class="btn btn-sm btn-secondary" onclick="MemorizedPage.addLine('${m.kind}')">+ Add line</button></td></tr></tfoot>
                </table>
                <h3 style="font-size:12px; margin:10px 0 4px;">Schedule</h3>
                ${Memorized._scheduleFields(m)}
                <div class="form-group"><label style="font-weight:normal;"><input type="checkbox" name="is_active" ${m.is_active ? 'checked' : ''} style="width:auto;"> Active</label></div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save</button>
                </div>
            </form>`, { wide: true });
        for (const l of lines) MemorizedPage.addLine(m.kind, l);
        if (!lines.length) MemorizedPage.addLine(m.kind);
    },

    addLine(kind, line = {}) {
        const body = $('#memorized-lines');
        if (!body) return;
        const { accounts, items } = MemorizedPage._lists;
        const cell = ([key, label, type]) => {
            const v = line[key];
            if (type === 'account' || type === 'item') {
                const list = type === 'account' ? accounts : items;
                return `<td><select data-key="${key}" aria-label="${label}"><option value="">Select…</option>${list.map(x =>
                    `<option value="${x.id}" ${String(x.id) === String(v) ? 'selected' : ''}>${escapeHtml(`${x.account_number || ''} ${x.name}`.trim())}</option>`).join('')}</select></td>`;
            }
            if (type === 'text') return `<td><input data-key="${key}" aria-label="${label}" maxlength="300" value="${escapeHtml(v || '')}"></td>`;
            const num = v === undefined || v === null || v === '' || Number(v) === 0 && type === 'money' && (key === 'debit' || key === 'credit') ? '' : Number(v);
            return `<td class="amount"><input data-key="${key}" data-type="${type}" aria-label="${label}" type="number" step="${type === 'number' ? 'any' : '0.01'}" style="width:100px; text-align:right;" value="${num}"></td>`;
        };
        const tr = document.createElement('tr');
        tr.innerHTML = MemorizedPage._COLS[kind].map(cell).join('') +
            `<td><button type="button" class="btn btn-sm btn-danger" aria-label="Remove line" onclick="this.closest('tr').remove()">×</button></td>`;
        tr._extra = line;  // keys the editor doesn't show (class, job, tax code) ride along
        body.appendChild(tr);
    },

    async saveEdit(e, id) {
        e.preventDefault();
        const f = e.target;
        const m = MemorizedPage._row(id);
        const payload = { ...(m.payload || {}) };
        const val = name => { const el = Memorized._field(f, name); return el ? el.value : undefined; };
        const int = name => (val(name) ? parseInt(val(name)) : null);
        if (m.kind === 'expense') { payload.payee = val('payee') || null; payload.paid_from_account_id = int('paid_from_account_id'); }
        if (m.kind === 'deposit') payload.deposit_to_account_id = int('deposit_to_account_id');
        if (m.kind === 'journal') payload.description = val('description') || 'Journal entry';
        if (m.kind === 'bill') { payload.vendor_id = int('vendor_id'); payload.terms = val('terms') || 'Net 30'; }
        if (m.kind === 'invoice') { payload.customer_id = int('customer_id'); payload.terms = val('terms') || 'Net 30'; }
        const lines = [...document.querySelectorAll('#memorized-lines tr')].map((tr, i) => {
            const out = { ...(tr._extra || {}) };
            tr.querySelectorAll('[data-key]').forEach(el => {
                const k = el.dataset.key;
                if (k === 'account_id' || k === 'item_id') out[k] = el.value ? parseInt(el.value) : null;
                else if (el.dataset.type === 'money') out[k] = el.value === '' ? '0.00' : Number(el.value).toFixed(2);
                else if (el.dataset.type === 'number') out[k] = el.value === '' ? 1 : Number(el.value);
                else out[k] = el.value.trim() || null;
            });
            if ('line_order' in out || m.kind === 'bill' || m.kind === 'invoice') out.line_order = i;
            return out;
        }).filter(l => l.account_id || l.item_id || l.description || Number(l.amount || l.debit || l.credit || l.rate || 0));
        if (m.kind === 'bill' || m.kind === 'invoice') lines.forEach(l => { l.rate = Number(l.rate || 0); });
        if (m.kind === 'deposit') payload.other_lines = lines; else payload.lines = lines;
        if (m.kind === 'expense') { delete payload.expense_account_id; delete payload.amount; }
        try {
            await API.put(`/memorized/${id}`, { ...Memorized._read(f), is_active: Memorized._field(f, 'is_active').checked, payload });
            toast('Saved');
            closeModal();
            App.refresh();
        } catch (err) { toast(err.message, 'error'); }
    },

    async skip(id) {
        try { await API.post(`/memorized/${id}/skip`); toast('Skipped to the next date'); App.refresh(); }
        catch (err) { toast(err.message, 'error'); }
    },

    async remove(id) {
        if (!confirm('Delete this memorized transaction? What was already entered stays.')) return;
        try { await API.del(`/memorized/${id}`); toast('Deleted'); App.refresh(); }
        catch (err) { toast(err.message, 'error'); }
    },

    // The Snapshot's reminder: enter what is set to enter itself, then
    // list what is due.
    async reminderHtml() {
        try {
            const auto = await API.post('/memorized/auto-enter').catch(() => ({ entered: [] }));
            const ok = (auto.entered || []).filter(x => !x.error);
            const failed = (auto.entered || []).filter(x => x.error);
            const due = await API.get('/memorized/due');
            MemorizedPage._rows = due;
            if (!due.length && !ok.length && !failed.length) return '';
            const rows = due.map(m => `<li>${formatDate(m.next_date)} — ${escapeHtml(m.name)} (${formatCurrency(m.amount)})
                <button class="btn btn-sm btn-primary" data-write style="margin-left:6px;" onclick="MemorizedPage.enter(${m.id})">Enter</button></li>`).join('');
            return `<div class="dash-reminders" style="border:1px solid var(--gray-300); background:var(--primary-light); padding:8px 12px; margin-bottom:12px; font-size:12px;">
                <strong>Reminders</strong> · <a href="#/memorized">Memorized Transactions</a>
                ${ok.length ? `<div>Entered automatically: ${ok.map(x => `${escapeHtml(x.name)} (${formatDate(x.date)})`).join(', ')}</div>` : ''}
                ${failed.length ? `<div style="color:var(--danger);">Could not enter: ${failed.map(x => `${escapeHtml(x.name)} — ${escapeHtml(x.error)}`).join('; ')}</div>` : ''}
                ${due.length ? `<ul style="margin:4px 0 0 18px;">${rows}</ul>` : ''}
            </div>`;
        } catch (e) { return ''; }
    },
};
