/**
 * Expenses — record a receipt that's already been paid.
 * DR Expense Account, CR the bank / credit-card account it was paid from.
 *
 * This is where most scanned receipts belong: a bill is money you still
 * owe, a sales receipt is money you took in — a paid receipt is neither.
 * One form, one save, scan attached as evidence.
 */
const ExpensesPage = {
    _vendors: [],
    _accounts: [],

    async render() {
        const expenses = await API.get('/expenses');
        let html = `
            <div class="page-header">
                <h2>Expenses</h2>
                <button class="btn btn-primary" ${App.shortcutAttrs('E', 'Enter Expense')} onclick="ExpensesPage.showForm()">+ Enter Expense</button>
            </div>`;

        if (expenses.length === 0) {
            html += `<div class="empty-state"><p>No expenses recorded yet</p>
                <p style="font-size:12px; color:var(--gray-600);">Enter a receipt you've already paid — by card, cash, or check. Scan it to fill the form.</p></div>`;
        } else {
            html += `<div class="table-container"><table>
                <thead><tr><th scope="col">Date</th><th scope="col">Payee</th><th scope="col">Expense Account</th><th scope="col">Paid From</th><th scope="col">Reference</th>
                <th scope="col">Status</th><th scope="col" class="amount">Amount</th><th scope="col"></th></tr></thead><tbody>`;
            for (const x of expenses) {
                const isVoid = x.status === 'void';
                html += `<tr data-status="${x.status}"${isVoid ? ' class="row--dim" style="text-decoration:line-through;"' : ''}>
                    <td>${formatDate(x.date)}</td>
                    <td>${escapeHtml(x.payee || '')}</td>
                    <td>${ExpensesPage.accountsText(x)}</td>
                    <td>${escapeHtml(x.paid_from_account_name || '')}</td>
                    <td>${escapeHtml(x.reference || '')}</td>
                    <td style="text-decoration:none;">${statusBadge(x.status)}</td>
                    <td class="amount">${formatCurrency(x.amount)}</td>
                    <td class="actions" style="text-decoration:none;">
                        <button class="btn btn-sm btn-secondary" onclick="ExpensesPage.showDetail(${x.id})">View</button>
                        ${isVoid || typeof ExpensesPage.edit !== 'function' ? '' : `<button data-write class="btn btn-sm btn-secondary" onclick="ExpensesPage.edit(${x.id})">Edit</button>`}
                        ${isVoid ? '' : `<button data-destructive class="btn btn-sm btn-danger" onclick="ExpensesPage.void(${x.id})">Void</button>`}
                    </td>
                </tr>`;
            }
            html += '</tbody></table></div>';
        }
        return html;
    },

    // The account column: the one account, or how many a split spreads over.
    accountsText(x) {
        const n = (x.lines || []).length;
        return n > 1 ? `Split (${n} accounts)` : escapeHtml(x.expense_account_name || '');
    },

    // Accounts money can leave from: the chart's bank and credit-card
    // accounts (bank_kind), nothing else.
    paidFromAccounts(accounts) {
        return accounts.filter(a => a.bank_kind);
    },

    // Back to the list the form or the void came from: Credit Card Charges
    // lists card charges too.
    _backTo() {
        if ((location.hash || '').startsWith('#/cc-charges')) App.refresh();
        else App.navigate('#/expenses');
    },

    // showForm({ card: true }): a credit card charge, the form starting on
    // the card
    async showForm() {
        const opts = arguments[0] || {};
        const [vendors, accounts, payees, settings] = await Promise.all([
            API.get('/vendors?active_only=true'),
            API.get('/accounts'),
            API.get('/expenses/payees').catch(() => []),
            API.get('/settings').catch(() => ({})),
        ]);
        // A Canadian registrant's lines carry a GST/HST code; the amounts
        // typed include the tax, as a receipt shows them.
        ExpensesPage._canada = settings.sales_tax_system === 'canada' && !!settings.hst_account_id;
        ExpensesPage._hstRate = settings.hst_rate || '13';
        ExpensesPage._hstAccount = parseInt(settings.hst_account_id, 10) || null;
        ExpensesPage._vendors = vendors;
        ExpensesPage._accounts = accounts;
        const classGroup = await classFormGroupHtml();
        const jobGroup = await jobFormGroupHtml(null);
        try { ExpensesPage._jobs = await API.get('/jobs'); } catch (e) { ExpensesPage._jobs = []; }
        await CostCodes.load();
        await CostTypes.load();
        await Nonprofit.loadFunds();
        // Expense and cost-of-goods accounts: materials are bought against
        // 5100 Materials Cost as often as against an expense (W-L18).
        const expenseAccts = PurchaseAccounts.filter(accounts);
        // A cheque can go to any account, as QuickBooks' Write Cheques
        // allows: a loan, an advance, a card it pays off. The expense and
        // cost-of-goods accounts come first, the rest under Other.
        ExpensesPage._expenseAccounts = expenseAccts.concat(accounts.filter(a => !expenseAccts.includes(a) && a.is_active !== false));
        const paidFrom = ExpensesPage.paidFromAccounts(accounts);
        const acctOpt = a => `<option value="${a.id}">${accountLabel(a)}</option>`;
        const checking = opts.card
            ? (paidFrom.find(a => a.bank_kind === 'credit_card' && a.account_number === '2100') || paidFrom.find(a => a.bank_kind === 'credit_card') || paidFrom[0])
            : (paidFrom.find(a => a.account_number === '1000') || paidFrom.find(a => /checking/i.test(a.name || '')) || paidFrom[0]);

        openModal('Enter Expense', `
            <form id="expense-form" data-skip-to="#expense-lines" data-skip-text="Skip to the lines" onsubmit="ExpensesPage.save(event)">
                ${ScanHelper.scanRowHtml()}
                <div class="form-grid">
                    <div class="form-group"><label>Payee *</label>
                        ${VendorQuickAdd.html(vendors, { id: 'expense-vendor', onchange: 'ExpensesPage.vendorSelected(this.value)' })}</div>
                    <div class="form-group"><label>Date *</label>
                        <input name="date" type="date" required value="${todayISO()}"></div>
                    <div class="form-group"><label>Paid From *</label>
                        <select name="paid_from_account_id" required onchange="ExpensesPage.nextNumber()">${paidFrom.map(acctOpt).join('')}</select></div>
                    <div class="form-group"><label title="What left the account; the lines below add up to it">Amount Paid *</label>
                        <input name="amount" class="money" type="number" step="0.01" min="0.01" required oninput="ExpensesPage.amountChanged()"></div>
                    <div class="form-group"><label>Reference</label>
                        <input name="reference" placeholder="Receipt / cheque #" oninput="this.dataset.auto=''"></div>
                    <div class="form-group full-width" id="expense-quickfill-note" style="font-size:11px; color:var(--text-muted);"></div>
                    ${classGroup}${jobGroup}
                    <div class="form-group full-width"><label>Memo</label>
                        <textarea name="memo"></textarea></div>
                </div>
                <h3 style="margin:12px 0 8px;font-size:14px;">Lines</h3>
                <div class="table-container table-container--scroll"><table class="line-items-table expense-lines-table">
                    <thead><tr><th scope="col" title="Where the line is recorded">Account *</th><th scope="col">Memo</th>${ExpensesPage.jobHeadHtml()}${CostCodes.headHtml()}${CostTypes.headHtml()}${Nonprofit.headHtml()}${ExpensesPage._canada ? `<th scope="col" title="H: the amount includes GST/HST at ${escapeHtml(ExpensesPage._hstRate)}%, claimed as an input tax credit">Tax</th>` : ''}<th scope="col" title="Billable to the job's customer">Bill?</th><th scope="col" class="col-amount">Amount</th><th scope="col"></th></tr></thead>
                    <tbody id="expense-lines">${ExpensesPage.lineHtml()}</tbody>
                </table></div>
                <button type="button" class="btn btn-sm btn-secondary" style="margin-top:8px;" onclick="ExpensesPage.addLine()">+ Add Line</button>
                <div class="invoice-totals">
                    <div class="total-row"><span class="label">Lines</span><span class="value" id="expense-lines-total">$0.00</span></div>
                    <div class="total-row grand-total"><span class="label">Amount Paid</span><span class="value" id="expense-paid-total">$0.00</span></div>
                    <div class="total-row"><span class="label">Left to assign</span><span class="value" id="expense-left">$0.00</span></div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="ScanHelper.discard(); closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save Expense</button>
                </div>
            </form>`, { wide: true });
        const pf = document.querySelector('#expense-form [name="paid_from_account_id"]');
        if (pf && checking) pf.value = checking.id;
        // Names cheques were written to that are not vendors (employees, the
        // Receiver General, QuickBooks' Other Names), after the vendors.
        const vsel = $('#expense-vendor');
        if (vsel && payees && payees.length) {
            vsel.insertAdjacentHTML('beforeend', `<optgroup label="Other payees">${payees.map(n =>
                `<option value="payee:${escapeHtml(n)}">${escapeHtml(n)}</option>`).join('')}</optgroup>`);
        }
        ExpensesPage.nextNumber();
        ScanHelper.wire(ExpensesPage._applyScan, ExpensesPage._applyScanField, ExpensesPage._scanFieldTarget);
    },

    async vendorSelected(vendorId) {
        if (!vendorId || vendorId === VendorQuickAdd.NEW) return;
        const isPayee = String(vendorId).startsWith('payee:');
        const vendor = isPayee ? null : ExpensesPage._vendors.find(v => v.id == vendorId);
        // the vendor's usual account goes on a line still waiting for one
        const sel = Array.from(document.querySelectorAll('#expense-lines .line-account')).find(a => !a.value);
        if (vendor && vendor.default_expense_account_id && sel) {
            sel.value = vendor.default_expense_account_id;
        }
        // QuickFill: start from the last cheque or charge to this payee
        const q = isPayee ? `payee=${encodeURIComponent(String(vendorId).slice(6))}` : `vendor_id=${vendorId}`;
        let last = null;
        try { last = await API.get(`/expenses/quickfill?${q}`); } catch (e) { return; }
        ExpensesPage.applyQuickFill(last);
    },

    // Fill the form from an earlier expense, unless an amount was typed.
    applyQuickFill(last) {
        const form = $('#expense-form');
        if (!form || !last || !last.lines || !last.lines.length) return;
        const typed = (form.amount && form.amount.value) || ExpensesPage.rows().some(r => r.querySelector('.line-amt').value);
        if (typed) return;
        // a GST/HST line in the last one is figured again from the H lines
        const isTax = l => ExpensesPage._canada && l.account_id === ExpensesPage._hstAccount;
        const lines = last.lines.filter(l => !isTax(l));
        const taxed = lines.length < last.lines.length;
        $('#expense-lines').innerHTML = '';
        for (const l of lines) {
            const share = taxed ? Number(l.amount) * (1 + parseFloat(ExpensesPage._hstRate) / 100) : Number(l.amount);
            ExpensesPage.addLine({ ...l, amount: Math.round(share * 100) / 100, tax_code: taxed ? 'H' : '' });
        }
        form.amount.value = Number(last.amount).toFixed(2);
        if (last.paid_from_account_id && form.paid_from_account_id.querySelector(`option[value="${last.paid_from_account_id}"]`)) {
            form.paid_from_account_id.value = last.paid_from_account_id;
            ExpensesPage.nextNumber();
        }
        // a cent lost to rounding the tax back in goes on the first line
        const left = ExpensesPage.recalc();
        if (left !== 0 && Math.abs(left) <= 0.05) {
            const first = ExpensesPage.rows()[0].querySelector('.line-amt');
            first.value = (parseFloat(first.value) + left).toFixed(2);
            ExpensesPage.recalc();
        }
        const status = $('#expense-quickfill-note');
        if (status) status.textContent = `Filled in from the last one, ${formatDate(last.date)}: change anything that differs.`;
    },

    // The next cheque number for the bank account paid from, unless a
    // number was typed. A credit card has none.
    async nextNumber() {
        const form = $('#expense-form');
        if (!form) return;
        const ref = form.reference;
        if (ref.value && ref.dataset.auto !== '1') return;
        const account = form.paid_from_account_id.value;
        let next = null;
        try { next = (await API.get(`/expenses/next-number?account_id=${account}`)).number; } catch (e) { /* none */ }
        // the account changed while this one was asked: its answer is stale
        if (form.paid_from_account_id.value !== account) return;
        if (ref.value && ref.dataset.auto !== '1') return;
        ref.value = next || '';
        ref.dataset.auto = next ? '1' : '';
    },

    jobHeadHtml() { return (ExpensesPage._jobs || []).length ? `<th scope="col">${T('Job')}</th>` : ''; },

    // One line of the expense: where it is recorded, its words, its job,
    // cost code, cost type, function and class, and its share.
    lineHtml(line = null) {
        const l = line || {};
        const acctOpts = PurchaseAccounts.options(ExpensesPage._expenseAccounts, l.account_id);
        const jobs = ExpensesPage._jobs || [];
        const jobCell = jobs.length
            ? `<td><select class="line-job"><option value="">Same as header</option>${jobs.map(j => `<option value="${j.id}"${l.job_id === j.id ? ' selected' : ''}>${escapeHtml(j.full_name || j.name)}</option>`).join('')}</select></td>`
            : '';
        return `<tr>
                <td>${AccountQuickAdd.picker(`<select class="line-account" required><option value="">Choose...</option>${acctOpts}</select>`, 'expense')}</td>
                <td><input class="line-desc" value="${escapeHtml(l.description || '')}"></td>
                ${jobCell}${CostCodes.cellHtml('line-cost-code', l.cost_code_id)}${CostTypes.cellHtml('line-cost-type', l.cost_type)}${ExpensesPage.fundCellsHtml(l)}
                ${ExpensesPage._canada ? `<td><select class="line-tax" aria-label="GST/HST"><option value="H"${l.tax_code === '' ? '' : ' selected'}>H</option><option value=""${l.tax_code === '' ? ' selected' : ''}>—</option></select></td>` : ''}
                <td style="text-align:center;"><input type="checkbox" class="line-billable" title="Billable"${l.is_billable ? ' checked' : ''}></td>
                <td class="col-amount"><input class="line-amt money" type="number" step="0.01" min="0.01" value="${l.amount ? Number(l.amount).toFixed(2) : ''}" oninput="ExpensesPage.recalc()"></td>
                <td><button type="button" class="btn btn-sm btn-secondary line-remove" aria-label="Remove line" title="Remove this line" onclick="ExpensesPage.removeLine(this)">&times;</button></td>
            </tr>`;
    },

    // The class and function cells of a line (cellHtml's, without its
    // allocation-rule Split button: an expense line has no split-by-rule).
    fundCellsHtml(l) {
        return Nonprofit.classCellHtml('line-function', l.class_id) + (Nonprofit.enabled()
            ? `<td><select class="line-function">${Nonprofit.optionsHtml(l.function, '—')}</select></td>` : '');
    },

    rows() { return Array.from(document.querySelectorAll('#expense-lines tr')); },

    addLine(line = null) {
        $('#expense-lines').insertAdjacentHTML('beforeend', ExpensesPage.lineHtml(line));
        ExpensesPage.recalc();
    },

    removeLine(btn) {
        if (ExpensesPage.rows().length > 1) btn.closest('tr').remove();
        ExpensesPage.recalc();
    },

    // With one line the form is today's: the line takes the amount paid.
    // From the second line on, the shares are typed and must add up to it.
    amountChanged() {
        const rows = ExpensesPage.rows();
        const form = $('#expense-form');
        if (rows.length === 1 && form) {
            rows[0].querySelector('.line-amt').value = form.amount.value;
        }
        ExpensesPage.recalc();
    },

    // Running total of the lines against the amount paid; returns the cents
    // still to assign.
    recalc() {
        const form = $('#expense-form');
        const rows = ExpensesPage.rows();
        const paid = PurchaseLines.cents(parseFloat(form && form.amount.value) || 0);
        const lines = PurchaseLines.cents(rows.reduce((sum, r) => sum + (parseFloat(r.querySelector('.line-amt').value) || 0), 0));
        const left = PurchaseLines.cents(paid - lines);
        $('#expense-lines-total').textContent = formatCurrency(lines);
        $('#expense-paid-total').textContent = formatCurrency(paid);
        const leftEl = $('#expense-left');
        leftEl.textContent = formatCurrency(left);
        leftEl.style.color = left === 0 ? '' : 'var(--text-danger)';
        document.querySelectorAll('#expense-lines .line-remove').forEach(b => { b.disabled = rows.length < 2; });
        return left;
    },

    // Where each canvas field lands — the canvas outlines these inputs in
    // the field's color so the form doubles as the legend.
    _scanFieldTarget(fieldKey) {
        const form = $('#expense-form');
        if (!form) return null;
        if (fieldKey === 'date') return form.querySelector('[name="date"]');
        if (fieldKey === 'merchant') return VendorQuickAdd.nameInput('expense-vendor') || form.querySelector('#expense-vendor');
        if (fieldKey === 'total') return form.querySelector('[name="amount"]');
        if (fieldKey === 'subtotal' || fieldKey === 'tax') return form.querySelector('[name="memo"]');
        if (fieldKey === 'reference') return form.querySelector('[name="reference"]');
        return null;
    },

    _noteLine(form, label, value) {
        const memo = form.querySelector('[name="memo"]');
        if (!memo) return;
        const re = new RegExp(`^${label}:`);
        const kept = memo.value.split('\n').filter(l => !re.test(l)).join('\n').replace(/\s*$/, '');
        memo.value = (kept ? kept + '\n' : '') + `${label}: $${value}`;
    },

    // Box-to-fix canvas: apply one re-read field. Returns {error} when the
    // value can't land, otherwise nothing.
    _applyScanField(fieldKey, value) {
        const form = $('#expense-form');
        if (!form) return;
        if (fieldKey === 'date') {
            form.querySelector('[name="date"]').value = value;
        } else if (fieldKey === 'merchant') {
            VendorQuickAdd.prefill('expense-vendor', value, ExpensesPage._vendors);
        } else if (fieldKey === 'total') {
            // The receipt total is what left the account — tax included.
            form.querySelector('[name="amount"]').value = parseFloat(value).toFixed(2);
            ExpensesPage.amountChanged();
        } else if (fieldKey === 'reference') {
            const ref = form.querySelector('[name="reference"]');
            if (ref) ref.value = value;
        } else if (fieldKey === 'subtotal') {
            ExpensesPage._noteLine(form, 'Subtotal', value);
        } else if (fieldKey === 'tax') {
            ExpensesPage._noteLine(form, 'Tax', value);
        }
    },

    _applyScan(result) {
        const form = $('#expense-form');
        if (!form) return;
        if (result.date) form.querySelector('[name="date"]').value = result.date;
        const ref = form.querySelector('[name="reference"]');
        if (result.reference && ref && !ref.value) ref.value = result.reference;

        const merchant = result.merchant && result.merchant.value;
        if (merchant) {
            const match = VendorQuickAdd.prefill('expense-vendor', merchant, ExpensesPage._vendors);
            if (match) {
                ExpensesPage.vendorSelected(match.id);
            } else {
                const statusEl = $('#scan-status');
                if (statusEl) {
                    statusEl.textContent = `Detected: ${merchant} — new vendor; it's added when you save (or pick one from the list).`;
                }
            }
        }

        const total = parseFloat(result.total || '0');
        if (total > 0) {
            form.querySelector('[name="amount"]').value = total.toFixed(2);
            ExpensesPage.amountChanged();  // the scan fills the first line
        }
        if (result.tax_detected && result.tax) ExpensesPage._noteLine(form, 'Tax', result.tax);
    },

    async save(e) {
        e.preventDefault();
        const form = e.target;
        const paidFrom = parseInt(form.paid_from_account_id.value);
        // a lone line takes the amount paid, as an amount typed a moment ago
        // has had no change event yet
        if (ExpensesPage.rows().length === 1) ExpensesPage.amountChanged();
        const lines = [];
        let missing = null;
        ExpensesPage.rows().forEach((row, i) => {
            const acct = row.querySelector('.line-account');
            if (!missing && !acct.value) missing = { n: i + 1, sel: acct };
            const job = row.querySelector('.line-job');
            lines.push({
                account_id: acct.value ? parseInt(acct.value) : null,
                amount: parseFloat(row.querySelector('.line-amt').value) || 0,
                description: row.querySelector('.line-desc').value || null,
                job_id: job && job.value ? parseInt(job.value) : null,
                cost_code_id: CostCodes.fromRow(row, 'line-cost-code'),
                cost_type: CostTypes.fromRow(row, 'line-cost-type'),
                class_id: Nonprofit.fundFromRow(row, 'line-function'),
                ...Nonprofit.linePayload(row, 'line-function'),
                is_billable: !!row.querySelector('.line-billable')?.checked,
                ...(row.querySelector('.line-tax')?.value === 'H' ? { tax_code: 'H' } : {}),
                // Write Cheques (write_cheques.js): the line is the net and
                // its GST/HST is the one the form shows
                ...(ExpensesPage._qbForm && row.querySelector('.line-tax')?.value === 'H'
                    ? { tax_amount: parseFloat(row.dataset.tax || '0') || 0 } : {}),
            });
        });
        if (missing) {
            toast(`Choose an account for line ${missing.n}: where should it be recorded?`, 'error');
            missing.sel.focus();
            return;
        }
        if (lines.some(l => !(l.amount > 0))) {
            toast('Every line needs an amount above 0.00; remove a line that is not used.', 'error');
            return;
        }
        const left = ExpensesPage.recalc();
        if (left !== 0) {
            toast(`The lines must add up to the amount paid: ${formatCurrency(Math.abs(left))} ${left > 0 ? 'left to assign' : 'over'}.`, 'error');
            return;
        }
        if (!(await Overdraft.confirm(paidFrom, parseFloat(form.amount.value) || 0))) return;
        if (!(await TxnWarn.ok(form))) return;
        if (!(await ClassWarn.ok(form, { rows: '#expense-lines tr', cls: 'line-function' }))) return;
        try {
            const picked = ($('#expense-vendor') || {}).value || '';
            const otherPayee = picked.startsWith('payee:') ? picked.slice(6) : null;
            const vendorId = otherPayee ? null : await VendorQuickAdd.ensure('expense-vendor');
            const body = {
                date: form.date.value,
                vendor_id: vendorId,
                ...(otherPayee ? { payee: otherPayee } : {}),
                // a line's GST/HST is inside its amount, as on the receipt
                ...(ExpensesPage._canada && !ExpensesPage._qbForm ? { amounts_include_tax: true } : {}),
                paid_from_account_id: paidFrom,
                amount: parseFloat(form.amount.value),
                lines,
                reference: form.reference.value || null,
                memo: form.memo.value || null,
                class_id: classIdFromForm(form),
                job_id: jobIdFromForm(form),
            };
            // a check number the bank account already has (#481)
            // an expense opened for editing (write_cheques.js) is saved in place
            const editId = ExpensesPage._editId;
            const result = await CheckNumberWarn.send(
                q => (editId
                    ? API.put(`/expenses/${editId}`, body, q ? { query: q } : undefined)
                    : API.post('/expenses', body, q ? { query: q } : undefined)), form.reference);
            if (!result) return;
            ExpensesPage._qbSaved = result;  // write_cheques.js: print when saved
            await ScanHelper.attachAfterSave('expense', result.id);
            if (editId) toastPosted('Cheque saved');
            else toastPosted('Expense recorded');
            closeModal();
            ExpensesPage._backTo();
        } catch (err) { toast(err.message, 'error'); }
    },

    /** Wrong account, wrong amount? Void posts the mirror-image entry
     *  (the original stays in the ledger) — then enter it again. */
    async void(id) {
        if (!confirm('Void this expense? A reversing entry will be posted; enter it again to correct it.')) return;
        try {
            await API.post(`/expenses/${id}/void`);
            toast('Expense voided');
            closeModal();
            ExpensesPage._backTo();
        } catch (err) { toast(err.message, 'error'); }
    },

    async showDetail(id) {
        const x = await API.get(`/expenses/${id}`);
        const isVoid = x.status === 'void';
        openModal(`Expense — ${escapeHtml(x.payee || '')}${isVoid ? ' (VOID)' : ''}`, `
            <div style="font-size:13px; line-height:1.7;">
                <strong>Date:</strong> ${formatDate(x.date)}<br>
                <strong>Payee:</strong> ${escapeHtml(x.payee || '')}<br>
                ${(x.lines || []).length > 1
                    ? `<table class="line-items-table" style="margin:4px 0;"><thead><tr><th scope="col">Account</th><th scope="col">Memo</th><th scope="col" class="amount">Amount</th></tr></thead><tbody>${x.lines.map(l => `<tr><td>${escapeHtml(l.account_name || '')}</td><td>${escapeHtml(l.description || '')}</td><td class="amount">${formatCurrency(l.amount)}</td></tr>`).join('')}</tbody></table>`
                    : `<strong>Expense Account:</strong> ${escapeHtml(x.expense_account_name || '')}<br>`}
                <strong>Paid From:</strong> ${escapeHtml(x.paid_from_account_name || '')}<br>
                <strong>Amount:</strong> ${formatCurrency(x.amount)}<br>
                ${x.reference ? `<strong>Reference:</strong> ${escapeHtml(x.reference)}<br>` : ''}
                ${x.memo ? `<strong>Memo:</strong> ${escapeHtml(x.memo).replace(/\n/g, '<br>')}<br>` : ''}
            </div>
            <div style="margin-top:12px; border-top:1px solid var(--gray-300); padding-top:8px;">
                <div style="font-weight:700; font-size:12px; margin-bottom:4px;">Attachments</div>
                <div id="expense-attachments-list" style="margin-bottom:8px; font-size:11px;">Loading...</div>
                <div style="display:flex; gap:6px; align-items:center;">
                    <input type="file" id="expense-attach-file" aria-label="File to attach" style="font-size:11px;">
                    <button class="btn btn-sm btn-secondary" onclick="ExpensesPage.uploadAttachment(${x.id})">Attach</button>
                </div>
            </div>
            <div class="form-actions">
                ${isVoid || typeof ExpensesPage.edit !== 'function' ? '' : `<button type="button" class="btn btn-primary" data-write onclick="ExpensesPage.edit(${x.id})">Edit</button>`}
                ${x.printable ? `<button type="button" class="btn btn-secondary" onclick="window.open('/api/checks/print?transaction_id=${x.id}','_blank')">Print Check</button>` : ''}
                ${isVoid ? '' : `<button type="button" class="btn btn-secondary" data-write title="Keep this cheque as a memorized transaction, to enter again on a schedule" onclick="MemorizedPage.memorizeExpense(${x.id})">Memorize</button>`}
                ${isVoid ? '' : `<button data-destructive type="button" class="btn btn-danger" onclick="ExpensesPage.void(${x.id})">Void</button>`}
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Close</button>
            </div>`);
        if (App.documentAddress) App.documentAddress(`#/expenses/${Number(id)}`);  // the document's own address (NEW-164)
        ExpensesPage.loadAttachments(x.id);
    },

    async loadAttachments(id) {
        const el = $('#expense-attachments-list');
        if (!el) return;
        try {
            const attachments = await API.get(`/attachments/expense/${id}`);
            if (attachments.length === 0) {
                el.innerHTML = '<span style="color:var(--text-muted);">No attachments</span>';
            } else {
                el.innerHTML = attachments.map(a =>
                    `<div style="display:flex; flex-wrap:wrap; align-items:center; gap:0 8px; padding:2px 0;">
                        ${a.missing ? `<span>${escapeHtml(a.filename)}</span>` : `<a href="/api/attachments/download/${a.id}" target="_blank">${escapeHtml(a.filename)}</a>`}
                        ${a.file_size == null ? '' : `<span style="color:var(--gray-400);">(${formatFileSize(a.file_size)})</span>`}
                        <button data-destructive aria-label="Delete attachment" class="btn btn-sm btn-danger" onclick="ExpensesPage.deleteAttachment(${a.id},${id})" style="padding:0 4px; font-size:10px;">X</button>
                        ${storedFileNote(a)}
                    </div>`
                ).join('');
            }
        } catch (e) { el.innerHTML = ''; }
    },

    async uploadAttachment(id) {
        const fileInput = $('#expense-attach-file');
        if (!fileInput?.files[0]) { toast('Select a file first', 'error'); return; }
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        try {
            const resp = await fetch(`/api/attachments/expense/${id}`, { method: 'POST', body: formData });
            if (!resp.ok) throw new Error(await API.responseError(resp, 'Upload failed'));
            toast('Attachment uploaded');
            fileInput.value = '';
            ExpensesPage.loadAttachments(id);
        } catch (err) { toast(err.message, 'error'); }
    },

    async deleteAttachment(attachmentId, id) {
        if (!confirm('Delete this attachment?')) return;
        try {
            await API.del(`/attachments/${attachmentId}`);
            toast('Attachment deleted');
            ExpensesPage.loadAttachments(id);
        } catch (err) { toast(err.message, 'error'); }
    },
};

/**
 * Money leaving a bank account: before an expense or a bill payment is
 * saved, say so when it takes the account below zero, and let the user go
 * ahead or stop (macbase1 S-a: an expense and a pay run overdrew Checking
 * to -$2,986.90 without a word). The balance is the ledger balance the
 * register shows. A card is left alone — its balance is money owed, not
 * money in the bank. A failed lookup never blocks the save.
 */
const Overdraft = {
    // accountId, or null for "the server's default" named by defaultNumber.
    async confirm(accountId, amount, defaultNumber, action = 'Save') {
        if (!(amount > 0)) return true;
        let accounts;
        try { accounts = await API.get('/banking/overview'); } catch (e) { return true; }
        const acct = accounts.find(a => accountId ? a.account_id === accountId : a.account_number === defaultNumber);
        if (!acct || acct.bank_kind !== 'bank') return true;
        const after = PurchaseLines.cents(Number(acct.balance) - amount);
        if (after >= 0) return true;
        return confirm(`${acct.name} will be overdrawn by ${formatCurrency(-after)}. ${action} anyway?`);
    },
};

// The expense's account adds an expense or cost of goods account (#485),
// picked when it is saved; the panel opens under the picker.
if (typeof AccountQuickAdd !== 'undefined') {
    AccountQuickAdd.register('expense', {
        types: AccountQuickAdd.PURCHASE_TYPES,
        compact: true,
        chart: () => (ExpensesPage._expenseAccounts = ExpensesPage._expenseAccounts || []),
        added: () => AccountQuickAdd.refillPurchase($$('#expense-lines select.line-account'), ExpensesPage._expenseAccounts),
    });
}
