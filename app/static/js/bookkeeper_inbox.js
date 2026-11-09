/**
 * Bookkeeper Inbox (John's build).
 *
 * What the agent bookkeeper prepared from the month's statements, waiting
 * in the company's bookkeeper folder ("To review"). Nothing here is in the
 * books until it is entered: Review opens an item with its vendor, date,
 * number and lines, every one of them editable; Enter posts it through the
 * ordinary routes (a bill, a cheque or card charge, a bill payment), with
 * their checks, and the statement is attached to it. Dismiss leaves an
 * item out for good. "Enter all ready" enters, one by one, every item with
 * no question and nothing to fix.
 */
const BookkeeperInbox = {
    _files: [],
    _accounts: [],
    _vendors: [],

    KIND: { bill: 'Bill', expense: 'Cheque / card charge', bill_payment: 'Bill payment' },

    async render() {
        const [box, accounts, vendors] = await Promise.all([
            API.get('/bookkeeper/inbox'),
            API.get('/accounts?active_only=true').catch(() => []),
            API.get('/vendors?active_only=true').catch(() => []),
        ]);
        this._files = box.files || [];
        this._accounts = accounts;
        this._vendors = vendors;
        let html = `<div class="page-header"><h2>Bookkeeper Inbox</h2>
            ${this._ready().length ? `<button class="btn btn-primary" data-write onclick="BookkeeperInbox.enterReady()">Enter all ready (${this._ready().length})</button>` : ''}</div>`;
        if (!box.folder) {
            return html + `<div class="empty-state"><p>No bookkeeper folder is set for this company.</p>
                <p>Set it in <a href="#/settings">Settings</a>, Company: <em>Bookkeeper folder</em>.</p></div>`;
        }
        if (box.exists === false) {
            return html + `<div class="empty-state"><p>The bookkeeper folder <code>${escapeHtml(box.folder)}</code> isn't there.</p><p style="font-size:12px;">In <a href="#/settings">Settings</a>, Company, type it from your home folder, e.g. <code>~/DATA/Alderella/Bookkeeper</code>.</p></div>`;
        }
        const open = this._files.filter(f => f.error || f.items.length);
        if (!open.length) {
            return html + `<div class="empty-state"><p>Nothing to review.</p>
                <p style="font-size:12px; color:var(--text-muted);">The agent leaves what it prepares in <code>${escapeHtml(box.folder)}/To review</code>.</p></div>`;
        }
        for (const f of open) {
            html += `<div class="card" style="margin-bottom:16px;">
                <h3 style="margin:0 0 4px;">${escapeHtml(f.title || f.file)}</h3>
                <div style="font-size:12px; color:var(--text-muted); margin-bottom:8px;">
                    ${f.prepared ? `Prepared ${escapeHtml(String(f.prepared))} &middot; ` : ''}
                    ${(f.source || []).map(s => `<a href="/api/bookkeeper/source/${encodeURIComponent(s)}" target="_blank" rel="noopener">${escapeHtml(s)}</a>`).join(' &middot; ') || 'no statement'}
                </div>`;
            if (f.error) {
                html += `<p class="error">${escapeHtml(f.error)}</p></div>`;
                continue;
            }
            html += `<div class="table-container"><table><thead><tr>
                <th scope="col">Date</th><th scope="col">Vendor</th><th scope="col">What</th><th scope="col">Account</th>
                <th scope="col" class="amount">Amount</th><th scope="col" class="amount">HST</th><th scope="col">Check</th><th scope="col"></th></tr></thead><tbody>`;
            for (const it of f.items) {
                const flags = [...it.problems.map(p => `<span class="badge badge-rejected" title="${escapeHtml(p)}">Fix</span>`),
                    ...(it.questions.length ? [`<span class="badge badge-pending" title="${escapeHtml(it.questions.join('\n'))}">Question</span>`] : [])];
                html += `<tr>
                    <td>${it.date ? formatDate(it.date) : ''}</td>
                    <td>${escapeHtml(it.vendor || '')}</td>
                    <td>${escapeHtml(this._what(it))}</td>
                    <td>${escapeHtml(this._accountsOf(it))}</td>
                    <td class="amount">${formatCurrency(it.total || 0)}</td>
                    <td class="amount">${this._hstOf(it)}</td>
                    <td>${flags.join(' ') || '<span style="color:var(--success, green);">Ready</span>'}</td>
                    <td style="white-space:nowrap;"><button class="btn btn-sm btn-primary" data-write data-file="${escapeHtml(f.file)}" data-item="${escapeHtml(it.id)}" onclick="BookkeeperInbox.review(this.dataset.file, this.dataset.item)">Review</button>
                        <button class="btn btn-sm btn-secondary" data-write data-destructive data-file="${escapeHtml(f.file)}" data-item="${escapeHtml(it.id)}" onclick="BookkeeperInbox.dismiss(this.dataset.file, this.dataset.item)">Dismiss</button></td>
                </tr>`;
            }
            html += '</tbody></table></div></div>';
        }
        return html;
    },

    // The accounts an item posts to, its tax line left out ("Meals",
    // "Meals, Benefits, Promotion"); a payment's is the account it comes from.
    _isTax: ln => /GST|HST|PST|QST|sales tax/i.test(ln.account || ''),
    _accountsOf(it) {
        if (it.kind === 'bill_payment') return `from ${it.paid_from || ''}`;
        const names = [];
        for (const ln of it.lines || []) if (!this._isTax(ln) && ln.account && !names.includes(ln.account)) names.push(ln.account);
        return names.join(', ');
    },

    // The HST on an item, or "No HST" (a payment has none to show).
    _hstOf(it) {
        if (it.kind === 'bill_payment') return '';
        const tax = (it.lines || []).filter(ln => this._isTax(ln)).reduce((s, ln) => s + (Number(ln.amount) || 0), 0);
        return tax ? formatCurrency(Math.round(tax * 100) / 100) : '<span style="color:var(--text-muted);">No HST</span>';
    },

    // "Card charge" for an expense on a credit card account, "Cheque" for
    // one from the bank; a bill or a payment says so.
    _what(it) {
        if (it.kind === 'bill') return `Bill ${it.number || ''}`.trim();
        if (it.kind === 'bill_payment') return `Payment of ${it.bill_number || 'bill'}`;
        const from = this._accounts.find(a => a.id === it.paid_from_id);
        if (from && from.bank_kind === 'credit_card') return 'Card charge';
        if ((it.lines || []).some(ln => ln.account_id && this._accounts.find(a => a.id === ln.account_id && a.bank_kind === 'credit_card'))) return `Card payment (${it.paid_from || ''})`;
        return `Cheque (${it.paid_from || ''})`;
    },

    _ready() {
        const out = [];
        for (const f of this._files) for (const it of f.items || []) {
            if (!it.problems.length && !it.questions.length) out.push([f.file, it]);
        }
        return out;
    },

    _find(file, id) {
        const f = this._files.find(x => x.file === file);
        return f ? f.items.find(i => String(i.id) === String(id)) : null;
    },

    _acctOptions(selected) {
        return '<option value="">— pick an account —</option>' + this._accounts.map(a =>
            `<option value="${a.id}" ${a.id === selected ? 'selected' : ''}>${escapeHtml(accountLabel(a))}</option>`).join('');
    },

    _lineRow(ln = {}) {
        return `<tr class="bk-line">
            <td><select class="bk-acct" aria-label="Account">${this._acctOptions(ln.account_id)}</select></td>
            <td><input class="bk-amt" type="number" step="0.01" aria-label="Amount" value="${ln.amount == null ? '' : Number(ln.amount).toFixed(2)}" oninput="BookkeeperInbox.total()" style="width:110px; text-align:right;"></td>
            <td><input class="bk-memo" aria-label="Memo" value="${escapeHtml(ln.memo || '')}"></td>
            <td><button type="button" class="btn btn-sm btn-secondary" aria-label="Remove line" onclick="this.closest('tr').remove(); BookkeeperInbox.total()">&times;</button></td>
        </tr>`;
    },

    total() {
        let t = 0;
        document.querySelectorAll('#bk-lines .bk-amt').forEach(i => { t += parseFloat(i.value) || 0; });
        const el = document.getElementById('bk-total');
        if (el) el.textContent = formatCurrency(Math.round(t * 100) / 100);
    },

    review(file, id) {
        const it = this._find(file, id);
        if (!it) return;
        this._open = { file, id, kind: it.kind, bill_id: it.bill_id };
        const vendorOpts = '<option value="">— pick a vendor —</option>' + this._vendors.map(v =>
            `<option value="${v.id}" ${v.id === it.vendor_id ? 'selected' : ''}>${escapeHtml(v.name)}</option>`).join('');
        const notes = [...it.problems.map(p => `<li class="error">${escapeHtml(p)}</li>`),
            ...it.questions.map(q => `<li>${escapeHtml(q)}</li>`)].join('');
        const source = (this._files.find(f => f.file === file) || {}).source || [];
        const paidFrom = it.kind !== 'bill' ? `<div class="form-group"><label for="bk-from">${it.kind === 'bill_payment' ? 'Pay from' : 'Paid from'}</label>
            <select id="bk-from">${this._acctOptions(it.paid_from_id)}</select></div>` : '';
        const body = it.kind === 'bill_payment'
            ? `<div class="form-group"><label for="bk-amount">Amount</label><input id="bk-amount" type="number" step="0.01" value="${it.total == null ? '' : Number(it.total).toFixed(2)}"></div>
               <div class="form-group"><label>Bill</label><div>${escapeHtml(it.bill_number || '')}${it.bill_balance != null ? ` (open ${formatCurrency(it.bill_balance)})` : ''}</div></div>
               <div class="form-group"><label for="bk-ref">Cheque no. / reference</label><input id="bk-ref" value="${escapeHtml(it.reference || '')}"></div>`
            : `<table style="width:100%; margin-top:8px;"><thead><tr><th scope="col">Account</th><th scope="col" class="amount">Amount</th><th scope="col">Memo</th><th scope="col"><span class="visually-hidden">Remove</span></th></tr></thead>
                <tbody id="bk-lines">${it.lines.map(l => this._lineRow(l)).join('')}</tbody></table>
               <div style="display:flex; justify-content:space-between; margin-top:6px;">
                 <button type="button" class="btn btn-sm btn-secondary" onclick="document.getElementById('bk-lines').insertAdjacentHTML('beforeend', BookkeeperInbox._lineRow())">+ Line</button>
                 <strong>Total <span id="bk-total"></span></strong></div>`;
        openModal(`Review — ${this.KIND[it.kind] || it.kind}`, `
            ${notes ? `<ul style="margin:0 0 10px; padding-left:18px;">${notes}</ul>` : ''}
            ${source.length ? `<p style="font-size:12px;">Statement: ${source.map(s => `<a href="/api/bookkeeper/source/${encodeURIComponent(s)}" target="_blank" rel="noopener">${escapeHtml(s)}</a>`).join(' &middot; ')}</p>` : ''}
            <form onsubmit="event.preventDefault(); BookkeeperInbox.enter()">
              <div class="form-grid">
                <div class="form-group"><label for="bk-vendor">Vendor</label><select id="bk-vendor">${vendorOpts}</select></div>
                <div class="form-group"><label for="bk-date">Date</label><input id="bk-date" type="date" value="${escapeHtml(it.date || '')}"></div>
                ${it.kind !== 'bill_payment' ? `<div class="form-group"><label for="bk-number">${it.kind === 'bill' ? 'Bill no.' : 'Reference'}</label><input id="bk-number" value="${escapeHtml(it.number || '')}"></div>` : ''}
                ${paidFrom}
                <div class="form-group full-width"><label for="bk-memo">Memo</label><input id="bk-memo" value="${escapeHtml(it.memo || '')}"></div>
              </div>
              ${body}
              <div class="form-actions">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button type="submit" class="btn btn-primary" data-write>Enter</button>
              </div>
            </form>`, { wide: true });
        document.getElementById('modal')?.classList.add('modal--wide');
        this.total();
    },

    // The item as the form now has it (or, for Enter all ready, as prepared).
    _payload(it, fromForm) {
        const v = id => document.getElementById(id)?.value;
        const num = x => Math.round((parseFloat(x) || 0) * 100) / 100;
        const vendorId = fromForm ? parseInt(v('bk-vendor'), 10) || null : it.vendor_id;
        const date = fromForm ? v('bk-date') : it.date;
        const memo = fromForm ? v('bk-memo') : it.memo;
        const number = fromForm ? (v('bk-number') || '').trim() : it.number;
        const fromId = fromForm ? parseInt(v('bk-from'), 10) || null : it.paid_from_id;
        const lines = fromForm
            ? Array.from(document.querySelectorAll('#bk-lines .bk-line')).map(tr => ({
                account_id: parseInt(tr.querySelector('.bk-acct').value, 10) || null,
                amount: num(tr.querySelector('.bk-amt').value),
                description: tr.querySelector('.bk-memo').value || null,
            })).filter(l => l.account_id || l.amount)
            : it.lines.map(l => ({ account_id: l.account_id, amount: num(l.amount), description: l.memo || null }));
        if (!vendorId) throw new Error('Pick the vendor.');
        if (!date) throw new Error('Enter the date.');
        if (it.kind === 'bill_payment') {
            const amount = num(fromForm ? v('bk-amount') : it.total);
            if (!it.bill_id) throw new Error('The bill this pays isn\'t entered yet.');
            if (!fromId) throw new Error('Pick the account it was paid from.');
            return ['/bill-payments', {
                vendor_id: vendorId, date, amount, method: it.method || 'ach',
                check_number: (fromForm ? v('bk-ref') : it.reference) || null,
                pay_from_account_id: fromId, notes: memo || null,
                allocations: [{ bill_id: it.bill_id, amount }],
            }];
        }
        if (!lines.length || lines.some(l => !l.account_id)) throw new Error('Every line needs an account.');
        if (it.kind === 'bill') {
            return ['/bills', {
                vendor_id: vendorId, date, bill_number: number || null, notes: memo || null,
                terms: 'Due on receipt', tax_rate: 0,
                lines: lines.map(l => ({ account_id: l.account_id, amount: l.amount, description: l.description })),
            }];
        }
        if (!fromId) throw new Error('Pick the account it was paid from.');
        return ['/expenses', {
            date, vendor_id: vendorId, paid_from_account_id: fromId,
            amount: Math.round(lines.reduce((s, l) => s + l.amount, 0) * 100) / 100,
            lines, reference: number || null, memo: memo || null,
        }];
    },

    async _post(file, it, fromForm) {
        const [url, body] = this._payload(it, fromForm);
        const saved = await API.post(url, body);
        const type = it.kind === 'bill' ? 'bill' : (it.kind === 'expense' ? 'expense' : 'bill_payment');
        return API.post(`/bookkeeper/inbox/${encodeURIComponent(file)}/${encodeURIComponent(it.id)}/entered`,
            { entity_type: type, entity_id: saved.id });
    },

    async enter() {
        const { file, id } = this._open || {};
        const it = this._find(file, id);
        if (!it) return;
        try {
            await this._post(file, it, true);
            closeModal();
            toast(`Entered: ${it.vendor || ''} ${formatCurrency(it.total || 0)}`);
            App.navigate('#/bookkeeper');
        } catch (err) { toast(err.message, 'error'); }
    },

    async enterReady() {
        const ready = this._ready();
        let done = 0;
        const failed = [];
        for (const [file, it] of ready) {
            try { await this._post(file, it, false); done += 1; } catch (err) { failed.push(`${it.vendor} ${it.date}: ${err.message}`); }
        }
        toast(`Entered ${done} of ${ready.length}${failed.length ? `; not entered: ${failed.join('; ')}` : ''}`, failed.length ? 'error' : 'success');
        App.navigate('#/bookkeeper');
    },

    async dismiss(file, id) {
        const it = this._find(file, id);
        if (!it || !confirm(`Leave out ${it.vendor || 'this item'} ${formatCurrency(it.total || 0)}? It won't be entered.`)) return;
        try {
            await API.post(`/bookkeeper/inbox/${encodeURIComponent(file)}/${encodeURIComponent(id)}/dismiss`, {});
            App.navigate('#/bookkeeper');
        } catch (err) { toast(err.message, 'error'); }
    },
};
