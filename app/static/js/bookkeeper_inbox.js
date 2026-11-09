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
                    ${(f.source || []).map(s => this._link(f.file, s)).join(' &middot; ') || 'no statement'}
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
        if (it.kind === 'reconciliation') return it.account || '';
        if (it.kind === 'hst_return') return 'GST/HST Payable';
        const names = [];
        for (const ln of it.lines || []) if (!this._isTax(ln) && ln.account && !names.includes(ln.account)) names.push(ln.account);
        return names.join(', ');
    },

    // The HST on an item, or "No HST" (a payment has none to show).
    _hstOf(it) {
        if (['bill_payment', 'reconciliation', 'hst_return'].includes(it.kind)) return '';
        const tax = (it.lines || []).filter(ln => this._isTax(ln)).reduce((s, ln) => s + (Number(ln.amount) || 0), 0);
        return tax ? formatCurrency(Math.round(tax * 100) / 100) : '<span style="color:var(--text-muted);">No HST</span>';
    },

    // "Card charge" for an expense on a credit card account, "Cheque" for
    // one from the bank; a bill or a payment says so.
    _what(it) {
        if (it.kind === 'hst_return') return `GST/HST return ${it.start ? formatDate(it.start) : ''} to ${it.end ? formatDate(it.end) : ''}`;
        if (it.kind === 'reconciliation') return `Reconcile to ${it.statement_date ? formatDate(it.statement_date) : 'statement'}`;
        if (it.kind === 'bill') return `Bill ${it.number || ''}`.trim();
        if (it.kind === 'bill_payment') return `Payment of ${it.bill_number || 'bill'}`;
        const from = this._accounts.find(a => a.id === it.paid_from_id);
        if (from && from.bank_kind === 'credit_card') return 'Card charge';
        if ((it.lines || []).some(ln => ln.account_id && this._accounts.find(a => a.id === ln.account_id && a.bank_kind === 'credit_card'))) return `Card payment (${it.paid_from || ''})`;
        return `Cheque (${it.paid_from || ''})`;
    },

    // A bank statement: what matched, what's on the statement but not in
    // the books (enter those first), what's in the books but not on the
    // statement (outstanding), and the difference it would start at.
    reviewReconciliation(file, it) {
        this._open = { file, id: it.id, kind: it.kind };
        const row = r => `<tr><td>${r.date ? formatDate(r.date) : ''}</td><td>${escapeHtml(r.description || '')}</td><td class="amount">${formatCurrency(r.amount || 0)}</td></tr>`;
        const table = (title, rows, note) => rows.length ? `<h4 style="margin:14px 0 4px;">${title} (${rows.length})</h4>
            ${note ? `<p style="font-size:12px; margin:0 0 4px; color:var(--text-muted);">${note}</p>` : ''}
            <div class="table-container" style="max-height:220px; overflow:auto;"><table><thead><tr><th scope="col">Date</th><th scope="col">Description</th><th scope="col" class="amount">Amount</th></tr></thead>
            <tbody>${rows.map(row).join('')}</tbody></table></div>` : '';
        const source = (this._files.find(f => f.file === file) || {}).source || [];
        const ok = !it.problems.length;
        openModal(`Reconcile ${escapeHtml(it.account || '')}`, `
            ${source.length ? `<p style="font-size:12px;">Statement: ${source.map(s => this._link(file, s)).join(' &middot; ')}</p>` : ''}
            <div class="form-grid">
              <div class="form-group"><label>Statement date</label><div>${it.statement_date ? formatDate(it.statement_date) : ''}</div></div>
              <div class="form-group"><label>Opening balance</label><div>${formatCurrency(it.opening_balance ?? it.beginning ?? 0)}</div></div>
              <div class="form-group"><label>Closing balance</label><div>${formatCurrency(it.closing_balance || 0)}</div></div>
              <div class="form-group"><label>Difference after matching</label><div><strong style="color:${Math.abs(it.difference || 0) < 0.005 ? 'var(--success, green)' : 'var(--danger, #b00)'};">${formatCurrency(it.difference || 0)}</strong></div></div>
            </div>
            ${it.problems.length ? `<ul style="margin:8px 0; padding-left:18px;">${it.problems.map(p => `<li class="error">${escapeHtml(p)}</li>`).join('')}</ul>` : ''}
            ${it.questions.length ? `<ul style="margin:8px 0; padding-left:18px;">${it.questions.map(q => `<li>${escapeHtml(q)}</li>`).join('')}</ul>` : ''}
            ${table('On the statement, not in the books', it.missing || [], 'Enter these first (the agent may have prepared them above in this inbox); they match as soon as they are in the books.')}
            ${table('Matched', it.matched || [])}
            ${table('In the books, not on the statement (outstanding)', it.outstanding || [])}
            <div class="form-actions">
              <button type="button" class="btn btn-secondary" onclick="closeModal()">Close</button>
              <button type="button" class="btn btn-primary" data-write ${ok ? '' : 'disabled title="Fix the items above first"'} onclick="BookkeeperInbox.startReconciliation()">Start reconciliation</button>
            </div>`, { wide: true });
        document.getElementById('modal')?.classList.add('modal--wide');
    },

    async startReconciliation() {
        const { file, id } = this._open || {};
        try {
            const r = await API.post(`/bookkeeper/inbox/${encodeURIComponent(file)}/${encodeURIComponent(id)}/reconcile`, {});
            closeModal();
            toast('Reconciliation started with the statement\'s items ticked. Check the difference is $0.00 and finish it.');
            await App.navigate('#/banking');
            BankingPage.showReconcileView(r.reconciliation_id);
        } catch (err) { toast(err.message, 'error'); }
    },

    // The quarter's return, line by line as NETFILE asks for it, with the
    // late ITCs and the carry-forward (held back / claimed, both editable),
    // then the payment once it's filed and paid.
    reviewHst(file, it) {
        this._open = { file, id: it.id, kind: it.kind, hst: it };
        const money = v => formatCurrency(v || 0);
        const row = (line, label, value, extra = '') => `<tr><td>${line}</td><td>${label}</td><td class="amount" ${extra}>${value}</td></tr>`;
        openModal(`GST/HST return — ${formatDate(it.start)} to ${formatDate(it.end)}`, `
            ${it.problems.length ? `<ul style="margin:0 0 8px; padding-left:18px;">${it.problems.map(p => `<li class="error">${escapeHtml(p)}</li>`).join('')}</ul>` : ''}
            ${it.questions.length ? `<ul style="margin:0 0 8px; padding-left:18px;">${it.questions.map(q => `<li>${escapeHtml(q)}</li>`).join('')}</ul>` : ''}
            <div class="table-container"><table><thead><tr><th scope="col">Line</th><th scope="col">For NETFILE</th><th scope="col" class="amount">Amount</th></tr></thead><tbody>
              ${row('101', 'Sales and other revenue', money(it.line_101))}
              ${row('103', 'GST/HST collected or collectible', money(it.line_103))}
              ${row('105', 'Total GST/HST and adjustments', money(it.line_105))}
              ${row('106', 'ITCs (see below)', `<strong id="hst-106">${money(it.line_106)}</strong>`)}
              ${row('108', 'Total ITCs and adjustments', `<span id="hst-108">${money(it.line_108)}</span>`)}
              ${row('109', 'Net tax', `<strong id="hst-109">${money(it.line_109)}</strong>`)}
              ${row('115', 'Amount owing', `<strong id="hst-115">${money(it.line_115)}</strong>`)}
            </tbody></table></div>
            <h4 style="margin:14px 0 4px;">Line 106, ITCs</h4>
            <div class="table-container"><table><tbody>
              ${row('', 'ITCs in the books for the quarter', money(it.itc_period))}
              ${row('', 'ITCs entered after the last return was filed', money(it.late_itc))}
              <tr><td></td><td><label for="hst-claimed">Carried forward ITCs claimed</label> <span style="font-size:11px; color:var(--text-muted);">(${money(it.carry_before)} available)</span></td>
                  <td class="amount"><input id="hst-claimed" type="number" step="0.01" min="0" value="${Number(it.claimed || 0).toFixed(2)}" oninput="BookkeeperInbox.hstRecalc()" style="width:120px; text-align:right;"></td></tr>
              <tr><td></td><td><label for="hst-held">ITCs held back to carry forward</label></td>
                  <td class="amount"><input id="hst-held" type="number" step="0.01" min="0" value="${Number(it.held || 0).toFixed(2)}" oninput="BookkeeperInbox.hstRecalc()" style="width:120px; text-align:right;"></td></tr>
              ${row('', 'Carried forward after this return', `<span id="hst-carry">${money(it.carry_after)}</span>`)}
            </tbody></table></div>
            <p style="font-size:11px; color:var(--text-muted); margin:6px 0 0;">Suggested: hold back the smallest multiple of $5,000 that keeps the return payable; claim the largest multiple of $5,000 carried forward that keeps it payable. ITCs can be claimed within four years.</p>
            <h4 style="margin:14px 0 4px;">Once it's filed and paid</h4>
            <div class="form-grid">
              <div class="form-group"><label for="hst-date">Date paid</label><input id="hst-date" type="date" value="${todayISO()}"></div>
              <div class="form-group"><label for="hst-amount">Amount paid</label><input id="hst-amount" type="number" step="0.01" value="${Number(it.line_115 || 0).toFixed(2)}"></div>
              <div class="form-group"><label for="hst-from">Paid from</label><select id="hst-from">${this._accounts.filter(a => a.bank_kind === 'bank').map(a => `<option ${a.name === 'RBC - Can $' ? 'selected' : ''}>${escapeHtml(a.name)}</option>`).join('')}</select></div>
              <div class="form-group"><label for="hst-ref">Confirmation no.</label><input id="hst-ref" placeholder="RBC's confirmation number"></div>
            </div>
            <div class="form-actions">
              <button type="button" class="btn btn-secondary" onclick="closeModal()">Close</button>
              <button type="button" class="btn btn-primary" data-write ${it.problems.length ? 'disabled' : ''} onclick="BookkeeperInbox.hstPaid()">Record payment</button>
            </div>`, { wide: true });
        document.getElementById('modal')?.classList.add('modal--wide');
    },

    hstRecalc() {
        const it = (this._open || {}).hst;
        if (!it) return;
        const n = id => parseFloat(document.getElementById(id)?.value) || 0;
        const r2 = x => Math.round(x * 100) / 100;
        const l106 = r2(it.itc_period + it.late_itc + n('hst-claimed') - n('hst-held'));
        const l109 = r2(it.line_103 - l106);
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = formatCurrency(v); };
        set('hst-106', l106); set('hst-108', l106); set('hst-109', l109); set('hst-115', Math.max(l109, 0));
        set('hst-carry', r2(it.carry_before + n('hst-held') - n('hst-claimed')));
        const amt = document.getElementById('hst-amount');
        if (amt) amt.value = Math.max(l109, 0).toFixed(2);
    },

    async hstPaid() {
        const { file, id } = this._open || {};
        const v = x => document.getElementById(x)?.value;
        try {
            const r = await API.post(`/bookkeeper/inbox/${encodeURIComponent(file)}/${encodeURIComponent(id)}/hst-paid`, {
                date: v('hst-date'), amount: parseFloat(v('hst-amount')) || 0, paid_from: v('hst-from'),
                reference: (v('hst-ref') || '').trim() || null,
                held: parseFloat(v('hst-held')) || 0, claimed: parseFloat(v('hst-claimed')) || 0,
            });
            closeModal();
            toast(`GST/HST payment recorded. ITCs carried forward: ${formatCurrency(r.carry_forward)}`);
            App.navigate('#/bookkeeper');
        } catch (err) { toast(err.message, 'error'); }
    },

    _link(file, s) {
        return `<a href="/api/bookkeeper/statement/${encodeURIComponent(file)}/${Number(s.n)}" target="_blank" rel="noopener">${escapeHtml(s.name)}</a>`;
    },

    _ready() {
        const out = [];
        for (const f of this._files) for (const it of f.items || []) {
            if (!['reconciliation', 'hst_return'].includes(it.kind) && !it.problems.length && !it.questions.length) out.push([f.file, it]);
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
        if (it.kind === 'reconciliation') return this.reviewReconciliation(file, it);
        if (it.kind === 'hst_return') return this.reviewHst(file, it);
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
            ${source.length ? `<p style="font-size:12px;">Statement: ${source.map(s => this._link(file, s)).join(' &middot; ')}</p>` : ''}
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
