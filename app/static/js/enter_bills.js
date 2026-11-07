/**
 * Enter Bills as QuickBooks Desktop 2020 lays it out (John's build).
 *
 * Bill / Credit across the top (Credit opens a vendor credit); the pale
 * blue Bill panel with Vendor, Address, Terms and Memo on the left and
 * Date, Ref. No., Amount Due and Bill Due on the right; the Expenses and
 * Items tabs, each with its total; the GST/HST and the total under the
 * grid; Save & Close, Save & New and Clear (Revert on a saved bill). The
 * vendor's summary sits beside it, as QuickBooks' panel does.
 *
 * GST/HST as on Write Cheques: each line is H (applies) or E (exempt), a
 * line's amount is the net, and the tax is shown under the grid. It is
 * saved as a line of its own to the GST/HST account, as the bills imported
 * from QuickBooks carry it, so the GST/HST return counts it as an input
 * tax credit. Typing the Amount Due with one expense line splits it into
 * the net and its tax.
 *
 * The grid is the same #bill-lines the rest of Bills reads (collectLines,
 * recalc, LineOrder, the scan helper): expense rows and item rows are both
 * there, each showing on its own tab. Only Enter Bills changes; the
 * memorized bill's form keeps the grid it had.
 */
// Which lines of a saved bill or cheque carried the GST/HST: the set of
// lines whose tax at the rate makes the tax saved (to 2 cents), so a bill
// with taxed and exempt lines opens with each line's H or E as it was. More
// than 12 lines, or no set that fits: null (every line H).
window.qbGuessTaxCodes = function (nets, tax, rate) {
    const n = nets.length;
    if (!n || n > 12 || !(tax > 0)) return null;
    const cents = x => Math.round(x * 100);
    const want = cents(tax);
    let best = null;
    for (let mask = 1; mask < (1 << n); mask++) {
        let perLine = 0, base = 0, count = 0;
        for (let i = 0; i < n; i++) if (mask & (1 << i)) { perLine += cents(nets[i] * rate); base += nets[i]; count++; }
        const fits = Math.abs(perLine - want) <= 2 || Math.abs(cents(base * rate) - want) <= 2;
        if (fits && (!best || count > best.count)) best = { mask, count };
    }
    return best ? nets.map((_, i) => !!(best.mask & (1 << i))) : null;
};

(function () {
    if (typeof BillsPage === 'undefined') return;

    const r2 = x => Math.round((Number(x) || 0) * 100) / 100;
    const B = { canada: false, rate: 0.13, rateText: '13', hst: null, tab: 'exp' };
    const active = () => !!document.querySelector('#bill-form.qb-bill');
    const rows = () => Array.from(document.querySelectorAll('#bill-lines tr'));
    const taxed = row => B.canada && row.querySelector('.qbb-tax') && row.querySelector('.qbb-tax').value === 'H';
    const netOf = row => BillsPage.lineAmount(row);
    const taxOf = row => (taxed(row) ? (parseFloat(row.dataset.tax || '0') || 0) : 0);
    function vendorAddress(v) {
        if (!v) return '';
        const cityLine = [v.city, [v.state, v.zip].filter(Boolean).join('  ')].filter(Boolean).join(', ');
        return [v.name, v.address1, v.address2, cityLine].filter(Boolean).join('\n');
    }
    const setTax = row => { row.dataset.tax = taxed(row) ? r2(netOf(row) * B.rate).toFixed(2) : '0'; };

    function taxCell(code) {
        if (!B.canada) return '';
        const exempt = code !== 'H';
        return `<td><select class="qbb-tax" aria-label="GST/HST" title="H: GST/HST applies, claimed as an input tax credit · E: exempt" onchange="BillsPage.qbLineChanged(this)"><option value="H"${exempt ? '' : ' selected'}>H</option><option value="E"${exempt ? ' selected' : ''}>E</option></select></td>`;
    }

    // An Expenses line: Account, Tax, Amount, Memo, Billable.
    function expenseRow(idx, l = {}) {
        const acctOpts = PurchaseAccounts.options(BillsPage._accounts, l.account_id || BillsPage._defaultExpenseAccountId);
        return `<tr data-billline="${idx}" data-qbb="exp" data-po-line="${l.purchase_order_line_id || ''}"${B.tab === 'exp' ? '' : ' hidden'}>
            <td>${AccountQuickAdd.picker(`<select class="line-account" aria-label="Account"><option value="">Choose...</option>${acctOpts}</select>`, 'bill')}</td>
            ${taxCell(l.tax_code || (B.canada ? 'H' : 'E'))}
            <td class="col-amount"><input class="line-amt money" type="number" step="0.01" aria-label="Amount" value="${l.amount != null && l.amount !== '' ? r2(l.amount).toFixed(2) : ''}" oninput="BillsPage.qbLineChanged(this)"></td>
            <td><input class="line-desc" aria-label="Memo" value="${escapeHtml(l.description || '')}"></td>
            <td style="text-align:center;"><input type="checkbox" class="line-billable" title="Billable"${l.is_billable ? ' checked' : ''}></td>
            <td><button type="button" class="btn btn-sm btn-secondary" aria-label="Remove line" onclick="BillsPage.qbRemoveLine(this)">&times;</button></td>
        </tr>`;
    }

    // An Items line: Item, Description, Qty, Cost, Amount, Tax, Billable.
    // Its account stays as the item gives it (hidden), Inventory for stock.
    function itemRow(idx, l = {}) {
        const item = l.item_id ? (BillsPage._items || []).find(i => i.id == l.item_id) : null;
        const stock = !!(item && item.track_inventory);
        const amountOnly = l.item_id && !stock && Number(l.quantity) === 1 && Number(l.rate) === Number(l.amount);
        const qty = l.item_id && !amountOnly ? Number(l.quantity) : '';
        const rate = l.item_id && !amountOnly ? Number(l.rate) : '';
        const acctOpts = PurchaseAccounts.options(BillsPage._accounts, stock ? null : l.account_id);
        return `<tr data-billline="${idx}" data-qbb="items" data-po-line="${l.purchase_order_line_id || ''}"${B.tab === 'items' ? '' : ' hidden'}>
            <td><select class="line-item" aria-label="Item" onchange="BillsPage.itemSelected(this)">${ItemQuickAdd.options(BillsPage._items, l.item_id)}</select>
                <select class="line-account" hidden aria-hidden="true" tabindex="-1"${stock ? ' disabled' : ''}><option value=""></option>${acctOpts}</select></td>
            <td><input class="line-desc" aria-label="Description" value="${escapeHtml(l.description || '')}"></td>
            <td><input class="line-qty" type="number" step="0.0001" aria-label="Quantity" value="${qty}" oninput="BillsPage.qtyChanged(this)"></td>
            <td><input class="line-rate money" type="number" step="0.0001" aria-label="Cost" value="${rate}" oninput="BillsPage.qbLineChanged(this)"></td>
            <td class="col-amount"><input class="line-amt money" type="number" step="0.01" aria-label="Amount" value="${l.item_id ? r2(l.amount).toFixed(2) : ''}" oninput="BillsPage.qbLineChanged(this)" onchange="BillsPage.amtChanged(this)"></td>
            ${taxCell(l.tax_code || (B.canada ? 'H' : 'E'))}
            <td style="text-align:center;"><input type="checkbox" class="line-billable" title="Billable"${l.is_billable ? ' checked' : ''}></td>
            <td><button type="button" class="btn btn-sm btn-secondary" aria-label="Remove line" onclick="BillsPage.qbRemoveLine(this)">&times;</button></td>
        </tr>`;
    }

    // ── the grid's own handlers, in place of Bills' for Enter Bills ───────
    const baseAddLine = BillsPage.addLine;
    BillsPage.addLine = function (line = null) {
        if (!active()) return baseAddLine.call(BillsPage, line);
        const idx = BillsPage.lineCount++;
        const kind = line && line.item_id ? 'items' : (line ? 'exp' : B.tab);
        $('#bill-lines').insertAdjacentHTML('beforeend', kind === 'items' ? itemRow(idx, line || {}) : expenseRow(idx, line || {}));
        const row = $('#bill-lines').lastElementChild;
        if (line && line.tax_amount == null) setTax(row);
        else if (line) row.dataset.tax = String(line.tax_amount);
        return row;
    };

    const baseRecalc = BillsPage.recalc;
    BillsPage.recalc = function () {
        const total = baseRecalc.apply(BillsPage, arguments);
        if (!active()) return total;
        const all = rows();
        const sum = kind => r2(all.filter(r => r.dataset.qbb === kind).reduce((t, r) => t + netOf(r), 0));
        const tax = r2(all.reduce((t, r) => t + taxOf(r), 0));
        const grand = r2(total + tax);
        const set = (sel, v) => { const el = $(sel); if (el) el.textContent = formatCurrency(v); };
        set('#qbb-exp-total', sum('exp'));
        set('#qbb-items-total', sum('items'));
        set('#qbb-tax-total', tax);
        set('#bill-total', grand);
        const due = $('#qbb-amount-due');
        if (due && document.activeElement !== due) due.value = grand ? grand.toFixed(2) : '';
        return grand;
    };

    // The HST as a line of its own, to the GST/HST account.
    const baseCollect = BillsPage.collectLines;
    BillsPage.collectLines = function () {
        const out = baseCollect.apply(BillsPage, arguments);
        if (!active()) return out;
        const tax = r2(rows().reduce((t, r) => t + taxOf(r), 0));
        if (tax > 0 && B.hst) {
            out.lines.push({
                purchase_order_line_id: null, item_id: null, account_id: B.hst,
                description: 'GST/HST', amount: tax, cost_code_id: null, cost_type: null,
                class_id: null, is_billable: false, line_order: out.lines.length,
            });
        }
        return out;
    };

    BillsPage.qbLineChanged = function (el) {
        const row = el.closest('tr');
        if (row) setTax(row);
        BillsPage.recalc();
    };

    BillsPage.qbRemoveLine = function (el) {
        el.closest('tr').remove();
        if (!rows().some(r => r.dataset.qbb === B.tab)) BillsPage.addLine();
        BillsPage.recalc();
    };

    BillsPage.qbTab = function (tab) {
        B.tab = tab;
        document.querySelectorAll('.qbb-tabs .qb-tab').forEach(t => t.classList.toggle('qb-tab--on', t.dataset.tab === tab));
        document.querySelectorAll('.qbb-head').forEach(h => { h.hidden = h.dataset.tab !== tab; });
        rows().forEach(r => { r.hidden = r.dataset.qbb !== tab; });
        if (!rows().some(r => r.dataset.qbb === tab)) BillsPage.addLine();
    };

    // The Amount Due typed with one expense line (and no items): that line
    // is the net of it, the rest its GST/HST, as QuickBooks splits it.
    BillsPage.qbAmountDue = function (input) {
        const all = rows().filter(r => netOf(r) || r.dataset.qbb === 'exp');
        const exp = all.filter(r => r.dataset.qbb === 'exp');
        if (exp.length !== 1 || all.some(r => r.dataset.qbb === 'items' && netOf(r))) return;
        const row = exp[0];
        const gross = parseFloat(input.value) || 0;
        const net = taxed(row) ? r2(gross / (1 + B.rate)) : r2(gross);
        row.querySelector('.line-amt').value = gross ? net.toFixed(2) : '';
        row.dataset.tax = taxed(row) ? r2(gross - net).toFixed(2) : '0';
        BillsPage.recalc();
    };

    // A scanned receipt's total is the Amount Due, split as typed.
    const baseApplyScan = BillsPage._applyScan;
    BillsPage._applyScan = function (result) {
        baseApplyScan.call(BillsPage, result);
        const total = parseFloat((result && result.total) || '0');
        const due = $('#qbb-amount-due');
        if (active() && total > 0 && due) { due.value = total.toFixed(2); BillsPage.qbAmountDue(due); }
    };

    BillsPage.qbDueDate = async function () {
        const form = $('#bill-form');
        const due = form && form.due_date;
        if (!due || due.dataset.touched) return;
        const d = await PaymentTerms.dates(form.date.value, form.terms.value, 'bill', BillsPage._formBillId).catch(() => null);
        if (d && d.due_date) due.value = d.due_date;
    };

    const baseVendorSelected = BillsPage.vendorSelected;
    BillsPage.vendorSelected = function (vendorId) {
        baseVendorSelected.call(BillsPage, vendorId);
        if (!active()) return;
        const addr = $('#qbb-address');
        const v = (BillsPage._vendors || []).find(x => x.id == vendorId);
        if (addr) addr.value = vendorAddress(v);
        BillsPage.qbDueDate();
    };

    // ── the form ──────────────────────────────────────────────────────────
    async function open(id) {
        const startVendor = id ? null : BillsPage._startVendor;
        BillsPage._startVendor = null;
        const [vendors, items, accounts, bill, settings] = await Promise.all([
            API.get('/vendors?active_only=true'),
            API.get('/items?active_only=true'),
            API.get('/accounts'),
            id ? API.get(`/bills/${id}`) : Promise.resolve(null),
            API.get('/settings').catch(() => ({})),
        ]);
        if (bill && bill.status === 'void') { toast('A voided bill cannot be edited', 'error'); return; }
        if (bill && !vendors.some(v => v.id === bill.vendor_id)) {
            vendors.push({ id: bill.vendor_id, name: bill.vendor_name || `Vendor #${bill.vendor_id}` });
        }
        B.canada = settings.sales_tax_system === 'canada' && !!settings.hst_account_id;
        B.rate = (parseFloat(settings.hst_rate || '13') || 0) / 100;
        B.rateText = settings.hst_rate || '13';
        B.hst = parseInt(settings.hst_account_id, 10) || null;
        B.bill = bill;
        BillsPage._items = items;
        BillsPage._accounts = PurchaseAccounts.filter(accounts, ...(bill ? bill.lines.map(l => l.account_id) : []));
        BillsPage._defaultExpenseAccountId = null;
        BillsPage._taxRate = bill ? Number(bill.tax_rate) || 0 : 0;
        BillsPage.lineCount = 1;
        BillsPage._vendors = vendors;
        BillsPage._formBillId = bill ? bill.id : null;
        const classGroup = await classFormGroupHtml(bill ? bill.class_id : undefined);
        const jobGroup = await jobFormGroupHtml(bill ? bill.job_id : null);
        await PaymentTerms.load();
        const terms = bill && bill.terms ? bill.terms : 'Net 30';
        const lines = bill ? bill.lines.filter(l => !(B.canada && l.account_id === B.hst && !l.item_id)) : [];
        const tax = bill ? r2(bill.lines.filter(l => B.canada && l.account_id === B.hst && !l.item_id).reduce((t, l) => t + Number(l.amount), 0)) : 0;
        B.tab = lines.length && lines.every(l => l.item_id) ? 'items' : 'exp';
        // Currency and exchange rate only for a bill in another currency (a
        // rate other than 1); otherwise they ride along unseen, as they were
        const foreign = bill && Number(bill.exchange_rate || 1) !== 1;
        const currency = foreign
            ? currencyFormGroupsHtml(bill.currency, bill.exchange_rate)
            : `<input type="hidden" name="currency" value="${escapeHtml((settings.home_currency || 'USD').toUpperCase())}"><input type="hidden" name="exchange_rate" value="${escapeHtml(String((bill && bill.exchange_rate) || 1))}">`;
        const extra = (classGroup || jobGroup || foreign)
            ? `<div class="form-grid qb-extra">${classGroup}${jobGroup}${foreign ? currency : ''}</div>${foreign ? '' : currency}` : currency;
        const canada = B.canada;

        openModal(bill ? `Enter Bills — ${escapeHtml(bill.bill_number || '')} (editing)` : 'Enter Bills', `
            <div class="bill-with-summary"><div class="bill-with-summary__form">
            <form id="bill-form" class="qb-write-cheques qb-bill" aria-labelledby="modal-title" data-skip-to="#bill-lines" data-skip-text="Skip to the lines" onsubmit="event.preventDefault(); BillsPage.qbSave('close')">
                <div class="qb-account-row qbb-kind">
                    <label><input type="radio" name="qbb_kind" value="bill" checked> Bill</label>
                    ${bill ? '' : `<label title="A credit from the vendor: opens a vendor credit"><input type="radio" name="qbb_kind" value="credit" onchange="BillsPage.qbCredit()"> Credit</label>`}
                </div>
                ${bill ? '' : ScanHelper.scanRowHtml()}
                <div class="qb-cheque qbb-panel">
                    <div class="qbb-title">Bill</div>
                    <div class="qbb-cols">
                        <div class="qbb-left">
                            <div class="qbb-field"><label for="bill-vendor">Vendor</label>
                                <div class="qbb-vendor">${VendorQuickAdd.html(vendors, { id: 'bill-vendor', onchange: 'BillsPage.vendorSelected(this.value)' })}</div></div>
                            <div class="qbb-field"><label for="qbb-address">Address</label>
                                <textarea id="qbb-address" rows="4" readonly tabindex="-1" title="From the vendor's record"></textarea></div>
                            <div class="qbb-field"><label for="qbb-terms">Terms</label>
                                <select id="qbb-terms" name="terms" onchange="this.form.due_date.dataset.touched=''; BillsPage.qbDueDate()">
                                    ${PaymentTerms.optionsHtml(terms, null, !bill || bill.payment_term_id != null)}
                                </select></div>
                        </div>
                        <div class="qbb-right">
                            <div class="qbb-field"><label for="qbb-date">Date</label>
                                <input id="qbb-date" name="date" type="date" required value="${bill ? bill.date : todayISO()}" onchange="this.form.due_date.dataset.touched=''; BillsPage.qbDueDate()"></div>
                            <div class="qbb-field"><label for="qbb-ref">Ref. No.</label>
                                <input id="qbb-ref" name="bill_number" placeholder="the vendor's invoice no." value="${bill ? escapeHtml(bill.bill_number || '') : ''}"></div>
                            <div class="qbb-field"><label for="qbb-amount-due">Amount Due</label>
                                <input id="qbb-amount-due" class="money" type="number" step="0.01" min="0" oninput="BillsPage.qbAmountDue(this)" onblur="BillsPage.recalc()"></div>
                            <div class="qbb-field"><label for="qbb-due">Bill Due</label>
                                <input id="qbb-due" name="due_date" type="date" value="${bill && bill.due_date ? bill.due_date : ''}" oninput="this.dataset.touched='1'"></div>
                        </div>
                    </div>
                    <div class="qbb-field qbb-memo"><label for="qbb-memo">Memo</label>
                        <input id="qbb-memo" name="notes" maxlength="500" value="${bill ? escapeHtml(bill.notes || '') : ''}"></div>
                </div>
                ${extra}
                <div class="qb-tabs qbb-tabs">
                    <button type="button" class="qb-tab${B.tab === 'exp' ? ' qb-tab--on' : ''}" data-tab="exp" onclick="BillsPage.qbTab('exp')">Expenses <strong id="qbb-exp-total">$0.00</strong></button>
                    <button type="button" class="qb-tab${B.tab === 'items' ? ' qb-tab--on' : ''}" data-tab="items" onclick="BillsPage.qbTab('items')">Items <strong id="qbb-items-total">$0.00</strong></button>
                </div>
                <div class="table-container table-container--scroll"><table class="line-items-table bill-lines-table qb-lines">
                    <thead class="qbb-head" data-tab="exp"${B.tab === 'exp' ? '' : ' hidden'}><tr>
                        <th scope="col" title="Where the line is recorded">Account</th>
                        ${canada ? `<th scope="col" title="H: GST/HST at ${escapeHtml(B.rateText)}% on the amount, claimed as an input tax credit · E: exempt">Tax</th>` : ''}
                        <th scope="col" class="col-amount">Amount</th><th scope="col">Memo</th>
                        <th scope="col" title="Billable to the job's customer">Billable?</th><th scope="col"></th>
                    </tr></thead>
                    <thead class="qbb-head" data-tab="items"${B.tab === 'items' ? '' : ' hidden'}><tr>
                        <th scope="col">Item</th><th scope="col">Description</th><th scope="col" class="col-qty">Qty</th>
                        <th scope="col" class="col-rate">Cost</th><th scope="col" class="col-amount">Amount</th>
                        ${canada ? '<th scope="col" title="H: GST/HST applies · E: exempt">Tax</th>' : ''}
                        <th scope="col" title="Billable to the job's customer">Billable?</th><th scope="col"></th>
                    </tr></thead>
                    <tbody id="bill-lines"></tbody>
                </table></div>
                <button type="button" class="btn btn-sm btn-secondary" style="margin-top:6px;" onclick="BillsPage.addLine()">+ Add Line</button>
                <div class="qb-totals" aria-live="polite">
                    ${canada ? `<div class="qb-total-row"><span>GST/HST (${escapeHtml(B.rateText)}%)</span><strong id="qbb-tax-total">$0.00</strong></div>` : ''}
                    <div class="qb-total-row qb-total-row--grand"><span>Total</span><strong id="bill-total">$0.00</strong></div>
                </div>
                <div class="form-actions qb-actions">
                    <button type="button" class="btn btn-secondary" onclick="BillsPage.qbSave('close')">Save &amp; Close</button>
                    <button type="button" class="btn btn-primary" onclick="BillsPage.qbSave('new')">Save &amp; New</button>
                    <button type="button" class="btn btn-secondary" onclick="BillsPage.qbClear()" title="${bill ? 'Put the bill back as it was saved' : 'Start this bill over'}">${bill ? 'Revert' : 'Clear'}</button>
                </div>
            </form></div>
            <aside id="bill-vendor-summary" class="bill-vendor-summary" aria-label="Vendor summary" aria-live="polite" hidden></aside></div>`, { wide: true });

        BillsPage._summaryFor = null;
        typeof LineOrder !== 'undefined' && LineOrder.attach('#bill-lines', { add: () => BillsPage.addLine(), changed: () => BillsPage.recalc() });
        if (bill) {
            const vsel = document.getElementById('bill-vendor');
            if (vsel) vsel.value = bill.vendor_id;
            const v = vendors.find(x => x.id === bill.vendor_id);
            $('#qbb-address').value = v ? vendorAddress(v) : (bill.vendor_name || '');
            BillsPage.showVendorSummary(bill.vendor_id);
            BillsPage.lineCount = 0;
            const codes = tax ? qbGuessTaxCodes(lines.map(l => Number(l.amount)), tax, B.rate) : null;
            lines.forEach((l, i) => BillsPage.addLine({ ...l, tax_code: tax && (!codes || codes[i]) ? 'H' : 'E', tax_amount: null }));
            // the tax saved, spread back over the H lines, the cents left on
            // the largest, so the form shows exactly what was saved
            if (tax) {
                const all = rows();
                const shown = r2(all.reduce((t, r) => t + taxOf(r), 0));
                const taxedRows = all.filter(taxed);
                if (shown !== tax && taxedRows.length) {
                    const big = taxedRows.reduce((a, b) => (netOf(b) > netOf(a) ? b : a));
                    big.dataset.tax = r2(taxOf(big) + tax - shown).toFixed(2);
                }
            }
            if (!rows().some(r => r.dataset.qbb === B.tab)) BillsPage.addLine();
            $('#qbb-due').dataset.touched = '1';
        } else {
            BillsPage.addLine();
            ScanHelper.wire(BillsPage._applyScan, BillsPage._applyScanField, BillsPage._scanFieldTarget);
            if (startVendor) {
                const sel = document.getElementById('bill-vendor');
                if (sel) { sel.value = String(startVendor); BillsPage.vendorSelected(startVendor); }
            }
            BillsPage.qbDueDate();
        }
        BillsPage.termsHint();
        BillsPage.recalc();
        B.snap = state();
    }

    // What the form holds, to tell whether a saved bill was changed.
    function state() {
        const form = $('#bill-form');
        return form ? JSON.stringify(Array.from(form.elements)
            .filter(e => e.type !== 'button' && e.type !== 'radio')
            .map(e => (e.type === 'checkbox' ? e.checked : e.value))) : '';
    }

    BillsPage.showForm = function (id = null) { return open(id); };

    BillsPage.qbCredit = function () {
        ScanHelper.discard();
        closeModal();
        if (typeof VendorCreditsPage !== 'undefined') VendorCreditsPage.showForm();
    };

    BillsPage.qbClear = function () {
        ScanHelper.discard();
        open(B.bill ? B.bill.id : null);
    };

    // Save & Close also closes a blank bill or an unchanged one, as
    // QuickBooks' does; Save & New opens a fresh bill after saving.
    BillsPage.qbSave = async function (mode) {
        const form = $('#bill-form');
        if (!form) return;
        const id = B.bill ? B.bill.id : null;
        if (mode === 'close' && (id ? B.snap === state() : !rows().some(r => netOf(r)))) {
            ScanHelper.discard();
            closeModal();
            return;
        }
        const { lines, missing } = BillsPage.collectLines();
        if (BillsPage.recalc() <= 0) {
            toast('Enter what the vendor charged: an amount on at least one line.', 'error');
            return;
        }
        if (missing) {
            toast(`Choose an account for line ${missing.n}: where should it be recorded?`, 'error');
            if (missing.sel.hidden) BillsPage.qbTab('items'); else missing.sel.focus();
            return;
        }
        if (!(await TxnWarn.ok(form, { editing: !!id }))) return;
        if (!(await ClassWarn.ok(form, { rows: '#bill-lines tr', cls: 'line-function' }))) return;
        try {
            const vendorId = await VendorQuickAdd.ensure('bill-vendor');
            const termSel = PaymentTerms.selection(form.terms);
            const body = {
                vendor_id: vendorId,
                bill_number: form.bill_number.value.trim() || null,
                date: form.date.value,
                terms: termSel.terms,
                payment_term_id: termSel.payment_term_id,
                notes: form.notes.value || null,
                class_id: classIdFromForm(form),
                job_id: jobIdFromForm(form),
                ...currencyPayloadFromForm(form),
                lines,
            };
            if (form.due_date.value && form.due_date.dataset.touched) body.due_date = form.due_date.value;
            if (id) {
                const saved = await API.put(`/bills/${id}`, body);
                toastPosted('Bill updated');
                for (const w of (saved && saved.warnings) || []) toast(w, 'warning');
            } else {
                const result = await API.post('/bills', body);
                await ScanHelper.attachAfterSave('bill', result.id);
                toastPosted('Bill saved');
            }
            closeModal();
            if (location.hash.startsWith('#/bills')) App.navigate('#/bills'); else App.refresh();
            if (mode === 'new') setTimeout(() => open(null), 250);
        } catch (err) { toast(err.message, 'error'); }
    };
})();
