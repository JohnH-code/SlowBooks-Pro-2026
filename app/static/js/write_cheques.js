/**
 * Write Cheques / Enter Credit Card Charges — the Enter Expense form laid
 * out as QuickBooks Desktop 2020 lays it out (John's build).
 *
 * The same form underneath (expenses.js): the same field names and ids, so
 * ExpensesPage.save, recalc, QuickFill, the next cheque number and the scan
 * all work unchanged. What differs is the arrangement:
 *   - Bank Account and its Ending Balance across the top;
 *   - the cheque itself, tinted: No. and Date, Pay to the Order of and the
 *     $ amount, the amount in words, the payee's address, the memo; a credit
 *     card shows QuickBooks' charge instead (Purchased From, Ref No.);
 *   - the Expenses grid below in QuickBooks' column order (Account, Tax,
 *     Amount, Memo, Customer:Job, Billable), whose total is the cheque's
 *     amount, as QuickBooks keeps it;
 *   - Save & Close, Save & New, Clear; Memorize and Print on the toolbar.
 */
(function () {
    if (typeof ExpensesPage === 'undefined') return;

    const ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten',
        'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen'];
    const TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety'];

    function hundreds(n) {
        const out = [];
        if (n >= 100) { out.push(ONES[Math.floor(n / 100)], 'Hundred'); n %= 100; }
        if (n >= 20) { out.push(TENS[Math.floor(n / 10)] + (n % 10 ? '-' + ONES[n % 10] : '')); }
        else if (n > 0) { out.push(ONES[n]); }
        return out.join(' ');
    }

    // 1234.5 → "One Thousand Two Hundred Thirty-Four and 50/100"
    function amountInWords(value) {
        const cents = Math.round((Number(value) || 0) * 100);
        let dollars = Math.floor(cents / 100);
        const parts = [];
        for (const [size, word] of [[1e9, 'Billion'], [1e6, 'Million'], [1e3, 'Thousand'], [1, '']]) {
            if (dollars >= size) {
                parts.push(hundreds(Math.floor(dollars / size)) + (word ? ' ' + word : ''));
                dollars %= size;
            }
        }
        return `${parts.join(' ') || 'Zero'} and ${String(cents % 100).padStart(2, '0')}/100`;
    }
    ExpensesPage.amountInWords = amountInWords;

    // The list page under its QuickBooks name: Enter Cheques, with a
    // Write Cheque button.
    const baseRender = ExpensesPage.render;
    ExpensesPage.render = async function () {
        const html = await baseRender.apply(this, arguments);
        return html
            .replace('<h2>Expenses</h2>', '<h2>Enter Cheques</h2>')
            .replace('>+ Enter Expense</button>', '>+ Write Cheque</button>');
    };

    function vendorAddress(v) {
        if (!v) return '';
        const cityLine = [v.city, [v.state, v.zip].filter(Boolean).join('  ')].filter(Boolean).join(', ');
        return [v.name, v.address1, v.address2, cityLine].filter(Boolean).join('\n');
    }

    // The bank or card the form is on: the title, the balance and the face.
    ExpensesPage.qbAccountChanged = function () {
        const form = $('#expense-form');
        if (!form) return;
        const acct = (ExpensesPage._accounts || []).find(a => a.id === parseInt(form.paid_from_account_id.value, 10));
        const card = !!acct && acct.bank_kind === 'credit_card';
        const name = acct ? acct.name : '';
        $('#modal-title').textContent = (card ? `Enter Credit Card Charges - ${name}` : `Write Cheques - ${name}`)
            + (ExpensesPage._editId ? ' (editing)' : '');
        const bal = $('#qb-ending-balance');
        if (bal) bal.textContent = acct ? formatCurrency(Number(acct.balance || 0)) : '';
        const balLabel = $('#qb-balance-label');
        if (balLabel) balLabel.textContent = 'Ending Balance';
        const printLater = form.qb_print && form.qb_print.closest('label');
        if (printLater) printLater.style.display = card ? 'none' : '';
        const face = $('#qb-cheque');
        if (face) face.classList.toggle('qb-cheque--card', card);
        const label = (sel, text) => { const el = $(sel); if (el) el.textContent = text; };
        label('#qb-acct-label', card ? 'Credit Card' : 'Bank Account');
        label('#qb-no-label', card ? 'Ref No.' : 'No.');
        label('#qb-payee-label', card ? 'Purchased From' : 'Pay to the Order of');
        // a card: Purchase/Charge or Refund/Credit, as QuickBooks asks
        const kind = $('#qb-card-kind');
        if (kind) kind.style.display = card ? '' : 'none';
        const credit = card && !!form.querySelector('input[name="qb_card_kind"][value="credit"]:checked');
        ExpensesPage._qbCredit = credit;
        label('#qb-card-title', credit ? 'Credit Card Refund/Credit' : 'Credit Card Purchase/Charge');
        if (face) face.classList.toggle('qb-cheque--refund', credit);
        ExpensesPage.nextNumber();
    };

    // ── Amounts, as QuickBooks Canada keeps them ───────────────────────────
    // A line's Amount is the net expense; a line coded H carries its GST/HST
    // (row.dataset.tax), shown under the grid; the cheque is the nets plus
    // the tax. A cheque amount typed with one line is split back into the
    // net and the tax.
    const r2 = x => Math.round((Number(x) || 0) * 100) / 100;
    const rate = () => (parseFloat(ExpensesPage._hstRate) || 0) / 100;
    const taxed = row => ExpensesPage._canada && row.querySelector('.line-tax') && row.querySelector('.line-tax').value === 'H';
    const netOf = row => parseFloat(row.querySelector('.line-amt').value) || 0;
    const taxOf = row => (taxed(row) ? (parseFloat(row.dataset.tax || '0') || 0) : 0);

    function setLineTaxFromNet(row) {
        row.dataset.tax = taxed(row) ? r2(netOf(row) * rate()).toFixed(2) : '0';
    }

    // The words line, the Expenses tab, and the totals under the grid.
    ExpensesPage.qbAmountShown = function () {
        const form = $('#expense-form');
        if (!form) return;
        const amount = parseFloat(form.amount.value) || 0;
        const words = $('#qb-amount-words');
        if (words) words.textContent = amount ? amountInWords(amount) : '';
        const rows = ExpensesPage.rows();
        const net = r2(rows.reduce((t, r) => t + netOf(r), 0));
        const tax = r2(rows.reduce((t, r) => t + taxOf(r), 0));
        const tab = $('#qb-expenses-total');
        if (tab) tab.textContent = formatCurrency(net);
        const t = $('#qb-tax-total');
        if (t) t.textContent = formatCurrency(tax);
        const g = $('#qb-grand-total');
        if (g) g.textContent = formatCurrency(r2(net + tax));
    };

    // A line's amount or tax code changed: its tax follows, and the cheque
    // amount becomes the total, as QuickBooks keeps it.
    ExpensesPage.qbLineChanged = function (row) {
        const form = $('#expense-form');
        if (!form) return;
        if (row) setLineTaxFromNet(row);
        const total = r2(ExpensesPage.rows().reduce((t, r) => t + netOf(r) + taxOf(r), 0));
        form.amount.value = total ? total.toFixed(2) : '';
        ExpensesPage.recalc();
    };

    // H / E on a line. With one line the cheque amount stays and the line
    // is split again; with several, the line's tax changes the total.
    ExpensesPage.qbTaxChanged = function (sel) {
        const row = sel.closest('tr');
        if (ExpensesPage.rows().length === 1 && ($('#expense-form').amount.value || '') !== '') {
            ExpensesPage.amountChanged();
        } else {
            ExpensesPage.qbLineChanged(row);
        }
    };

    // The cheque amount typed: with one line, its net and tax are what is
    // left of it after the GST/HST.
    ExpensesPage.amountChanged = function () {
        const form = $('#expense-form');
        if (!form) return;
        const rows = ExpensesPage.rows();
        if (rows.length === 1) {
            const row = rows[0];
            const gross = r2(parseFloat(form.amount.value) || 0);
            const tax = taxed(row) ? r2(gross * rate() / (1 + rate())) : 0;
            row.querySelector('.line-amt').value = gross ? r2(gross - tax).toFixed(2) : '';
            row.dataset.tax = tax.toFixed(2);
        }
        ExpensesPage.recalc();
    };

    // What is left between the cheque amount and the lines with their tax.
    ExpensesPage.recalc = function () {
        const form = $('#expense-form');
        const rows = ExpensesPage.rows();
        const paid = r2(parseFloat(form && form.amount.value) || 0);
        const total = r2(rows.reduce((t, r) => t + netOf(r) + taxOf(r), 0));
        const left = r2(paid - total);
        const set = (sel, v) => { const el = $(sel); if (el) el.textContent = formatCurrency(v); };
        set('#expense-lines-total', total);
        set('#expense-paid-total', paid);
        set('#expense-left', left);
        const leftRow = $('#qb-left-row');
        if (leftRow) leftRow.style.display = left === 0 ? 'none' : '';
        document.querySelectorAll('#expense-lines .line-remove').forEach(b => { b.disabled = rows.length < 2; });
        ExpensesPage.qbAmountShown();
        return left;
    };

    // QuickFill: the last cheque's lines as nets, coded H when it had tax.
    ExpensesPage.applyQuickFill = function (last) {
        const form = $('#expense-form');
        if (!form || !last || !last.lines || !last.lines.length) return;
        if ((form.amount && form.amount.value) || ExpensesPage.rows().some(r => r.querySelector('.line-amt').value)) return;
        const isTax = l => ExpensesPage._canada && l.account_id === ExpensesPage._hstAccount;
        const lines = last.lines.filter(l => !isTax(l));
        const hadTax = lines.length < last.lines.length;
        $('#expense-lines').innerHTML = '';
        for (const l of lines) {
            ExpensesPage.addLine({ ...l, amount: r2(l.amount), tax_code: hadTax ? 'H' : 'E' });
        }
        ExpensesPage.rows().forEach(setLineTaxFromNet);
        ExpensesPage.qbLineChanged();
        const status = $('#expense-quickfill-note');
        if (status) status.textContent = `Filled in from the last one, ${formatDate(last.date)}: change anything that differs.`;
    };

    const baseVendorSelected = ExpensesPage.vendorSelected;
    ExpensesPage.vendorSelected = async function (vendorId) {
        const addr = $('#qb-address');
        if (addr) {
            const v = String(vendorId || '').startsWith('payee:') ? null
                : (ExpensesPage._vendors || []).find(x => x.id == vendorId);
            addr.value = v ? vendorAddress(v) : (String(vendorId || '').startsWith('payee:') ? String(vendorId).slice(6) : '');
        }
        // QuickFill fills the lines and the amount; the account stays the
        // one the form is on, as QuickBooks keeps it
        const form = $('#expense-form');
        const account = form ? form.paid_from_account_id.value : null;
        await baseVendorSelected.call(this, vendorId);
        if (form && account && form.paid_from_account_id.value !== account) {
            form.paid_from_account_id.value = account;
            ExpensesPage.qbAccountChanged();
        }
        ExpensesPage.qbAmountShown();
    };

    // After a save: Save & New opens a fresh cheque on the same account, and
    // "Print" sends a cheque from a bank account to the printer.
    const baseBackTo = ExpensesPage._backTo;
    ExpensesPage._backTo = function () {
        const again = ExpensesPage._qbAgain;
        const saved = ExpensesPage._qbSaved;
        const print = ExpensesPage._qbPrint;
        ExpensesPage._qbAgain = ExpensesPage._qbSaved = ExpensesPage._qbPrint = null;
        baseBackTo.apply(this, arguments);
        if (print && saved && saved.printable) {
            const url = `/api/checks/print?transaction_id=${saved.id}`;
            if (typeof printPdfUrl === 'function') printPdfUrl(url); else window.open(url, '_blank');
        }
        if (again) setTimeout(() => ExpensesPage.showForm(again), 250);
    };

    ExpensesPage.qbSubmit = function (mode) {
        const form = $('#expense-form');
        if (!form) return;
        ExpensesPage._qbAgain = mode === 'new' ? { paid_from_account_id: parseInt(form.paid_from_account_id.value, 10) } : null;
        ExpensesPage._qbPrint = !!(form.qb_print && form.qb_print.checked);
        form.requestSubmit();
    };

    ExpensesPage.qbClear = function () {
        const form = $('#expense-form');
        const keep = form ? parseInt(form.paid_from_account_id.value, 10) : null;
        ScanHelper.discard();
        // a cheque being edited goes back to what was saved
        if (ExpensesPage._editId) return ExpensesPage.edit(ExpensesPage._editId);
        ExpensesPage.showForm({ paid_from_account_id: keep });
    };

    // 2.31.5's Edit (#689) on a report line voids an expense and posts a
    // new one; here it opens the cheque in Write Cheques and saves it in
    // place instead.
    ExpensesPage.replace = function (id) { return ExpensesPage.edit(id); };

    // Open a saved cheque or card charge in the form, as QuickBooks opens
    // one from the register, to change and save in place.
    ExpensesPage.edit = async function (id) {
        let x;
        try { x = await API.get(`/expenses/${id}`); } catch (err) { toast(err.message, 'error'); return; }
        if (x.status === 'void') { toast('This cheque is void; enter it again instead.', 'error'); return; }
        closeModal();
        await ExpensesPage.showForm({ edit: x, paid_from_account_id: x.paid_from_account_id });
    };

    // The saved cheque on the form: its account, number, date, payee, memo,
    // and its lines as nets with their GST/HST. A GST/HST line in it is
    // spread back over the lines (H), the cents left on the largest, so the
    // form shows exactly what was saved.
    ExpensesPage.qbFillFrom = function (x) {
        const form = $('#expense-form');
        if (!form) return;
        if (x.paid_from_account_id) form.paid_from_account_id.value = x.paid_from_account_id;
        const kindRadio = form.querySelector(`input[name="qb_card_kind"][value="${x.is_credit ? 'credit' : 'charge'}"]`);
        if (kindRadio) kindRadio.checked = true;
        form.date.value = x.date;
        form.reference.value = x.reference || '';
        form.reference.dataset.auto = '';
        form.memo.value = x.memo || '';
        const vsel = $('#expense-vendor');
        if (vsel) {
            if (x.vendor_id) {
                vsel.value = String(x.vendor_id);
            } else if (x.payee) {
                const v = `payee:${x.payee}`;
                if (!Array.from(vsel.options).some(o => o.value === v)) {
                    vsel.insertAdjacentHTML('beforeend', `<option value="${escapeHtml(v)}">${escapeHtml(x.payee)}</option>`);
                }
                vsel.value = v;
            }
            const addr = $('#qb-address');
            const vendor = (ExpensesPage._vendors || []).find(v => v.id === x.vendor_id);
            if (addr) addr.value = vendor ? vendorAddress(vendor) : (x.payee || '');
        }
        const isTax = l => ExpensesPage._canada && l.account_id === ExpensesPage._hstAccount;
        const lines = (x.lines || []).filter(l => !isTax(l));
        const tax = r2((x.lines || []).filter(isTax).reduce((t, l) => t + Number(l.amount), 0));
        $('#expense-lines').innerHTML = '';
        for (const l of (lines.length ? lines : [{}])) {
            ExpensesPage.addLine({ ...l, amount: l.amount != null ? r2(l.amount) : '', tax_code: tax ? 'H' : 'E' });
        }
        const rows = ExpensesPage.rows();
        rows.forEach(setLineTaxFromNet);
        if (tax) {
            const shown = r2(rows.reduce((t, r) => t + taxOf(r), 0));
            if (shown !== tax && rows.length) {
                const big = rows.reduce((a, b) => (netOf(b) > netOf(a) ? b : a));
                big.dataset.tax = r2(taxOf(big) + tax - shown).toFixed(2);
            }
        }
        form.amount.value = Number(x.amount).toFixed(2);
    };

    // Memorize the cheque on the form, as QuickBooks' Memorize does: the
    // memorized-cheque form opens filled from it, to name and schedule.
    ExpensesPage.qbMemorize = function () {
        const form = $('#expense-form');
        if (!form || typeof MemorizedPage === 'undefined') return;
        const picked = ($('#expense-vendor') || {}).value || '';
        const lines = ExpensesPage.rows().map(r => ({
            account_id: parseInt(r.querySelector('.line-account').value, 10) || null,
            description: r.querySelector('.line-desc').value || '',
            // a memorized cheque keeps an H line's amount with its tax in it
            amount: r2(netOf(r) + taxOf(r)),
            tax_code: taxed(r) ? 'H' : '',
        })).filter(l => l.account_id && l.amount > 0);
        if (!lines.length) { toast('Fill in a line first: an account and an amount', 'error'); return; }
        const vendor = picked && !picked.startsWith('payee:') ? (ExpensesPage._vendors || []).find(v => v.id == picked) : null;
        const payee = picked.startsWith('payee:') ? picked.slice(6) : null;
        MemorizedPage.showChequeForm(null, {
            name: (vendor && vendor.name) || payee || 'Cheque',
            vendor_id: vendor ? vendor.id : null,
            payee,
            paid_from_account_id: parseInt(form.paid_from_account_id.value, 10),
            notes: form.memo.value || '',
            lines,
        });
    };

    // showForm({ card: true }) starts on a credit card;
    // showForm({ paid_from_account_id }) on that account.
    ExpensesPage.showForm = async function () {
        const opts = arguments[0] || {};
        ExpensesPage._qbAgain = ExpensesPage._qbSaved = ExpensesPage._qbPrint = null;
        ExpensesPage._qbForm = true;
        ExpensesPage._editId = opts.edit ? opts.edit.id : null;
        const [vendors, accounts, payees, settings] = await Promise.all([
            API.get('/vendors?active_only=true'),
            API.get('/accounts'),
            API.get('/expenses/payees').catch(() => []),
            API.get('/settings').catch(() => ({})),
        ]);
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
        const expenseAccts = PurchaseAccounts.filter(accounts);
        ExpensesPage._expenseAccounts = expenseAccts.concat(accounts.filter(a => !expenseAccts.includes(a) && a.is_active !== false));
        const paidFrom = ExpensesPage.paidFromAccounts(accounts).filter(a => a.is_active !== false);
        const start = (opts.paid_from_account_id && paidFrom.find(a => a.id === opts.paid_from_account_id))
            || (opts.card
                ? (paidFrom.find(a => a.bank_kind === 'credit_card' && a.account_number === '2100') || paidFrom.find(a => a.bank_kind === 'credit_card'))
                : (paidFrom.find(a => a.account_number === '1000') || paidFrom.find(a => a.bank_kind === 'bank')))
            || paidFrom[0];
        const acctOpt = a => `<option value="${a.id}"${start && a.id === start.id ? ' selected' : ''}>${escapeHtml(a.name)}</option>`;
        const canada = ExpensesPage._canada;
        const extraGroups = (classGroup || jobGroup) ? `<div class="form-grid qb-extra">${classGroup}${jobGroup}</div>` : '';

        openModal('Write Cheques', `
            <form id="expense-form" class="qb-write-cheques" data-skip-to="#expense-lines" data-skip-text="Skip to the lines" onsubmit="ExpensesPage.save(event)">
                <div class="qb-toolbar">
                    <button type="button" class="btn btn-sm btn-secondary" onclick="ExpensesPage.qbMemorize()" title="Keep this cheque to enter again, on a schedule or when you choose">Memorize</button>
                    <label class="qb-print-later" title="Print the cheque as soon as it is saved (a bank account only)"><input type="checkbox" name="qb_print"> Print when saved</label>
                </div>
                ${ScanHelper.scanRowHtml()}
                <div class="qb-account-row">
                    <label id="qb-acct-label" for="qb-paid-from">Bank Account</label>
                    <select id="qb-paid-from" name="paid_from_account_id" required onchange="ExpensesPage.qbAccountChanged()">${paidFrom.map(acctOpt).join('')}</select>
                    <span class="qb-card-kind" id="qb-card-kind">
                        <label><input type="radio" name="qb_card_kind" value="charge" checked onchange="ExpensesPage.qbAccountChanged()"> Purchase/Charge</label>
                        <label><input type="radio" name="qb_card_kind" value="credit" onchange="ExpensesPage.qbAccountChanged()"> Refund/Credit</label>
                    </span>
                    <span class="qb-balance"><span id="qb-balance-label">Ending Balance</span> <strong id="qb-ending-balance"></strong></span>
                </div>
                <div id="qb-cheque" class="qb-cheque">
                    <div class="qb-card-title" id="qb-card-title">Credit Card Purchase/Charge</div>
                    <div class="qb-cheque-top">
                        <div class="qb-field"><label id="qb-no-label" for="qb-no">No.</label>
                            <input id="qb-no" name="reference" oninput="this.dataset.auto=''"></div>
                        <div class="qb-field"><label for="qb-date">Date</label>
                            <input id="qb-date" name="date" type="date" required value="${todayISO()}"></div>
                    </div>
                    <div class="qb-cheque-payee">
                        <label id="qb-payee-label" for="expense-vendor">Pay to the Order of</label>
                        <div class="qb-payee-select">${VendorQuickAdd.html(vendors, { id: 'expense-vendor', onchange: 'ExpensesPage.vendorSelected(this.value)' })}</div>
                        <span class="qb-dollar">$</span>
                        <input name="amount" class="money qb-amount" type="number" step="0.01" min="0.01" required aria-label="Amount" oninput="ExpensesPage.amountChanged()">
                    </div>
                    <div class="qb-cheque-words"><span id="qb-amount-words"></span><span class="qb-dollars-word">Dollars</span></div>
                    <div class="qb-cheque-address">
                        <label for="qb-address">Address</label>
                        <textarea id="qb-address" rows="4" readonly tabindex="-1" title="From the vendor's record"></textarea>
                    </div>
                    <div class="qb-cheque-memo"><label for="qb-memo">Memo</label>
                        <input id="qb-memo" name="memo" maxlength="500"></div>
                </div>
                <div id="expense-quickfill-note" class="qb-note"></div>
                ${extraGroups}
                <div class="qb-tabs"><span class="qb-tab qb-tab--on">Expenses <strong id="qb-expenses-total">$0.00</strong></span></div>
                <div class="table-container table-container--scroll"><table class="line-items-table expense-lines-table qb-lines">
                    <thead><tr>
                        <th scope="col" title="Where the line is recorded">Account</th>
                        ${canada ? `<th scope="col" title="H: GST/HST applies at ${escapeHtml(ExpensesPage._hstRate)}% on the amount, claimed as an input tax credit · E: exempt">Tax</th>` : ''}
                        <th scope="col" class="col-amount">Amount</th>
                        <th scope="col">Memo</th>
                        ${ExpensesPage.jobHeadHtml().replace(`>${T('Job')}<`, `>Customer:${T('Job')}<`)}
                        <th scope="col" title="Billable to the job's customer">Billable?</th>
                        ${CostCodes.headHtml()}${CostTypes.headHtml()}${Nonprofit.headHtml()}
                        <th scope="col"></th>
                    </tr></thead>
                    <tbody id="expense-lines">${ExpensesPage.lineHtml()}</tbody>
                </table></div>
                <button type="button" class="btn btn-sm btn-secondary" style="margin-top:6px;" onclick="ExpensesPage.addLine()">+ Add Line</button>
                <div class="qb-totals" aria-live="polite">
                    ${canada ? `<div class="qb-total-row"><span>GST/HST (${escapeHtml(ExpensesPage._hstRate)}%)</span><strong id="qb-tax-total">$0.00</strong></div>` : ''}
                    <div class="qb-total-row qb-total-row--grand"><span>Total</span><strong id="qb-grand-total">$0.00</strong></div>
                    <div class="qb-total-row" id="qb-left-row" style="display:none;"><span>Left to assign (cheque <span id="expense-paid-total">$0.00</span>, lines <span id="expense-lines-total">$0.00</span>)</span><strong id="expense-left">$0.00</strong></div>
                </div>
                <div class="form-actions qb-actions">
                    <button type="button" class="btn btn-secondary" onclick="ExpensesPage.qbSubmit('close')">Save &amp; Close</button>
                    <button type="button" class="btn btn-primary" onclick="ExpensesPage.qbSubmit('new')">Save &amp; New</button>
                    <button type="button" class="btn btn-secondary" onclick="ExpensesPage.qbClear()">Clear</button>
                    <button type="button" class="btn btn-secondary" onclick="ScanHelper.discard(); closeModal()">Cancel</button>
                </div>
            </form>`, { wide: true });

        const vsel = $('#expense-vendor');
        if (vsel && payees && payees.length) {
            vsel.insertAdjacentHTML('beforeend', `<optgroup label="Other payees">${payees.map(n =>
                `<option value="payee:${escapeHtml(n)}">${escapeHtml(n)}</option>`).join('')}</optgroup>`);
        }
        // a change on any line keeps the cheque's amount at their total
        $('#expense-lines').addEventListener('input', e => {
            if (e.target.classList.contains('line-amt')) ExpensesPage.qbLineChanged(e.target.closest('tr'));
        });
        if (opts.edit) ExpensesPage.qbFillFrom(opts.edit);
        ExpensesPage.qbAccountChanged();
        ExpensesPage.recalc();
        ScanHelper.wire(ExpensesPage._applyScan, ExpensesPage._applyScanField, ExpensesPage._scanFieldTarget);
        if (vsel) vsel.focus();
    };

    // QuickBooks' column order for a line: Account, Tax, Amount, Memo,
    // Customer:Job, Billable, then this build's extra columns.
    ExpensesPage.lineHtml = function (line = null) {
        const l = line || {};
        const acctOpts = PurchaseAccounts.options(ExpensesPage._expenseAccounts, l.account_id);
        const jobs = ExpensesPage._jobs || [];
        const jobCell = jobs.length
            ? `<td><select class="line-job"><option value="">Same as header</option>${jobs.map(j => `<option value="${j.id}"${l.job_id === j.id ? ' selected' : ''}>${escapeHtml(j.full_name || j.name)}</option>`).join('')}</select></td>`
            : '';
        const exempt = l.tax_code === '' || l.tax_code === 'E';
        const taxCell = ExpensesPage._canada
            ? `<td><select class="line-tax" aria-label="GST/HST" title="H: GST/HST applies · E: exempt" onchange="ExpensesPage.qbTaxChanged(this)"><option value="H"${exempt ? '' : ' selected'}>H</option><option value="E"${exempt ? ' selected' : ''}>E</option></select></td>`
            : '';
        return `<tr data-tax="0">
                <td>${AccountQuickAdd.picker(`<select class="line-account" required><option value="">Choose...</option>${acctOpts}</select>`, 'expense')}</td>
                ${taxCell}
                <td class="col-amount"><input class="line-amt money" type="number" step="0.01" min="0.01" value="${l.amount ? Number(l.amount).toFixed(2) : ''}"></td>
                <td><input class="line-desc" value="${escapeHtml(l.description || '')}"></td>
                ${jobCell}
                <td style="text-align:center;"><input type="checkbox" class="line-billable" title="Billable"${l.is_billable ? ' checked' : ''}></td>
                ${CostCodes.cellHtml('line-cost-code', l.cost_code_id)}${CostTypes.cellHtml('line-cost-type', l.cost_type)}${ExpensesPage.fundCellsHtml(l)}
                <td><button type="button" class="btn btn-sm btn-secondary line-remove" aria-label="Remove line" title="Remove this line" onclick="ExpensesPage.removeLine(this)">&times;</button></td>
            </tr>`;
    };

    const baseRemove = ExpensesPage.removeLine;
    ExpensesPage.removeLine = function (btn) {
        baseRemove.call(this, btn);
        if ($('#expense-form.qb-write-cheques')) ExpensesPage.qbLineChanged();
    };
})();
