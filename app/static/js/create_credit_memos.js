/**
 * Create Credit Memos/Refunds as QuickBooks Desktop 2020 lays it out
 * (John's build).
 *
 * Customer:Job across the top; "Credit Memo" with the customer's address on
 * the left and Date, Credit No. and For Invoice on the right; the grid
 * Item | Description | Qty | Rate | Amount | Tax (H or E); Subtotal,
 * GST/HST, Total and Remaining Credit; Customer Message; Save & Close,
 * Save & New and Clear (Revert when changing a saved one).
 *
 * On save QuickBooks asks what to do with the credit: keep it as an
 * available credit, or apply it to an invoice now (Apply opens the memo's
 * own Apply Credit, with the invoice it was for filled in).
 *
 * Only the layout is new. The boxes keep the names and classes Credit
 * Memos' own save and Edit read (customer_id, date, original_invoice_id,
 * tax_rate, class_id, notes; line-item, line-desc, line-qty, line-rate,
 * line-taxable, line-class), so a memo is saved exactly as before. A line's
 * H or E is its taxable box (kept, hidden, beside it); the rate is the
 * company's GST/HST rate.
 */
(function () {
    if (typeof CreditMemosPage === 'undefined') return;

    const C = {};
    const num = x => parseFloat(x) || 0;
    const active = () => !!document.querySelector('#cm-form.qb-credit-memo');

    function custAddress(c) {
        if (!c) return '';
        const city = [c.bill_city, [c.bill_state, c.bill_zip].filter(Boolean).join('  ')].filter(Boolean).join(', ');
        return [c.company_name || c.name, c.bill_address1, c.bill_address2, city].filter(Boolean).join('\n');
    }

    // A line as Credit Memos draws it, laid out as QuickBooks': Item,
    // Description, (Class), Qty, Rate, Amount, then H/E in the taxable
    // box's place.
    function qbRow(idx) {
        const t = document.createElement('tbody');
        t.innerHTML = CreditMemosPage._baseRowHtml(idx);
        const tr = t.firstElementChild;
        const cells = Array.from(tr.children);
        const [item, desc] = cells;
        const qty = tr.querySelector('.line-qty').closest('td');
        const rate = tr.querySelector('.line-rate').closest('td');
        const amount = tr.querySelector('.line-amount');
        const taxBox = tr.querySelector('.line-taxable');
        const taxTd = taxBox.closest('td');
        const remove = tr.querySelector('td:last-child');
        const extras = cells.filter(c => ![item, desc, qty, rate, amount, taxTd, remove].includes(c));
        taxBox.hidden = true;
        taxTd.insertAdjacentHTML('afterbegin', `<select class="qbi-tax" aria-label="GST/HST" title="H: GST/HST applies · E: exempt" onchange="CreditMemosPage.qbTaxChanged(this)"><option value="H"${taxBox.checked ? ' selected' : ''}>H</option><option value="E"${taxBox.checked ? '' : ' selected'}>E</option></select>`);
        const btn = remove.querySelector('button');
        if (btn) { btn.className = 'btn btn-sm btn-secondary'; btn.innerHTML = '&times;'; }
        tr.replaceChildren(item, desc, ...extras, qty, rate, amount, taxTd, remove);
        return tr.outerHTML;
    }

    CreditMemosPage._baseRowHtml = CreditMemosPage.lineRowHtml;
    CreditMemosPage.lineRowHtml = function (idx) {
        return active() || C.drawing ? qbRow(idx) : CreditMemosPage._baseRowHtml(idx);
    };

    CreditMemosPage.qbTaxChanged = function (sel) {
        const box = sel.closest('tr').querySelector('.line-taxable');
        if (box) box.checked = sel.value === 'H';
        CreditMemosPage.recalc();
    };

    // After the totals: the H/E pickers follow their boxes (a tax-exempt
    // customer unticks them, Edit sets them), and Remaining Credit.
    const baseRecalc = CreditMemosPage.recalc;
    CreditMemosPage.recalc = function () {
        const t = baseRecalc.apply(CreditMemosPage, arguments);
        if (!active()) return t;
        document.querySelectorAll('#cm-lines tr').forEach(tr => {
            const box = tr.querySelector('.line-taxable');
            const sel = tr.querySelector('.qbi-tax');
            if (box && sel) { sel.value = box.checked ? 'H' : 'E'; sel.disabled = box.disabled; }
        });
        const el = document.getElementById('qbc-remaining');
        if (el) el.textContent = formatCurrency(num(t && t.total));
        return t;
    };

    const baseCustomerSelected = CreditMemosPage.customerSelected;
    CreditMemosPage.customerSelected = async function (customerId) {
        const box = document.getElementById('qbc-customer');
        if (box) box.value = custAddress((CreditMemosPage._customers || []).find(c => c.id == customerId));
        return baseCustomerSelected.call(CreditMemosPage, customerId);
    };

    // The rate stays the company's GST/HST rate when an invoice is picked
    // (base switches to the invoice's own; a Canadian invoice has the same).
    function state() {
        const form = document.getElementById('cm-form');
        return form ? JSON.stringify(Array.from(form.elements)
            .filter(e => e.type !== 'button' && e.type !== 'submit' && !(e.classList && e.classList.contains('cbx-input')) && !/-new-name$/.test(e.id || ''))
            .map(e => (e.type === 'checkbox' ? e.checked : e.value))) : '';
    }

    CreditMemosPage.showForm = async function () {
        const [customers, items, settings] = await Promise.all([
            API.get('/customers?active_only=true&tree=1'),
            API.get('/items?active_only=true'),
            API.get('/settings'),
        ]);
        CreditMemosPage._items = items;
        CreditMemosPage._customers = customers;
        CreditMemosPage._invoices = [];
        CreditMemosPage.lineCount = 1;
        C.id = null;
        const classGroup = await classFormGroupHtml();
        if (CreditMemosPage.lineClasses()) await Nonprofit.loadFunds();
        const canada = settings.sales_tax_system === 'canada' && !!settings.hst_account_id;
        const pct = +(parseFloat((canada ? settings.hst_rate || '13' : settings.default_tax_rate) || '0') || 0).toFixed(4);
        const taxLabel = canada ? `GST/HST (${escapeHtml(String(pct))}%)` : 'Tax';
        const custOpts = customers.map(c => `<option value="${c.id}">${escapeHtml(customerLabel(c))}</option>`).join('');

        C.drawing = true;
        const firstRow = CreditMemosPage.lineRowHtml(0);
        C.drawing = false;

        openModal('Create Credit Memos/Refunds', `
            <form id="cm-form" class="qb-invoice qb-credit-memo" aria-labelledby="modal-title" onsubmit="event.preventDefault(); CreditMemosPage.qbSave('close')">
                <div class="qbi-bar">
                    <label for="cm-customer-select">${T('Customer')}:${T('Job')}</label>
                    <select name="customer_id" id="cm-customer-select" required onchange="CreditMemosPage.customerSelected(this.value)"><option value="">Select...</option>${custOpts}</select>
                </div>
                <div class="qbi-paper">
                    <div class="qbi-head">
                        <div class="qbi-title">Credit Memo</div>
                        <div class="qbi-billto"><label for="qbc-customer">${T('Customer')}</label>
                            <textarea id="qbc-customer" rows="4" readonly tabindex="-1" title="From the ${T('customer')}'s record"></textarea></div>
                        <div class="qbi-fields">
                            <div><label for="qbc-date">Date</label>
                                <input id="qbc-date" name="date" type="date" required value="${todayISO()}"></div>
                            <div><label>Credit No.</label>
                                <input id="qbc-number" placeholder="next number" readonly tabindex="-1" title="Numbered when it is saved"></div>
                            <div style="grid-column:1 / -1;"><label for="cm-invoice-select">For ${T('Invoice')}</label>
                                <select name="original_invoice_id" id="cm-invoice-select" onchange="CreditMemosPage.invoiceSelected(this.value)" title="The ${T('invoice')} this credits (optional): Apply offers it first"><option value="">None</option></select></div>
                        </div>
                    </div>
                    ${classGroup.trim() ? `<div class="form-grid qb-extra">${classGroup}</div>` : ''}
                    ${canada ? `<input type="hidden" name="tax_rate" value="${pct}">` : `<div class="form-grid qb-extra"><div class="form-group"><label>Tax Rate (%)</label>
                        <input name="tax_rate" type="number" step="0.0001" value="${pct}" oninput="CreditMemosPage.recalc()"></div></div>`}
                    <div class="table-container table-container--scroll"><table class="line-items-table qbi-grid">
                        <thead><tr>
                            <th scope="col">Item</th><th scope="col">Description</th>
                            ${CreditMemosPage.lineClasses() ? Nonprofit.classHeadHtml() : ''}
                            <th scope="col" class="col-qty">Qty</th><th scope="col" class="col-rate">Rate</th><th scope="col" class="col-amount">Amount</th>
                            <th scope="col" title="H: ${canada ? 'GST/HST' : 'sales tax'} applies · E: exempt">Tax</th><th scope="col" class="col-actions"></th>
                        </tr></thead>
                        <tbody id="cm-lines">${firstRow}</tbody>
                    </table></div>
                    <button type="button" class="btn btn-sm btn-secondary" style="margin-top:6px;" onclick="CreditMemosPage.addLine()">+ Add Line</button>
                    <div class="qbi-bottom">
                        <div class="qbi-message">
                            <label for="qbc-notes">${T('Customer')} Message</label>
                            <textarea id="qbc-notes" name="notes" rows="2" aria-label="Message printed on the credit memo"></textarea>
                        </div>
                        <div class="qb-totals invoice-totals" id="cm-totals" aria-live="polite">
                            <div class="qb-total-row"><span>Subtotal</span><strong id="cm-subtotal">$0.00</strong></div>
                            <div class="qb-total-row"><span>${taxLabel}</span><strong id="cm-tax">$0.00</strong></div>
                            <div class="qb-total-row qb-total-row--grand"><span>Total</span><strong id="cm-total">$0.00</strong></div>
                            <div class="qb-total-row qb-total-row--grand"><span>Remaining Credit</span><strong id="qbc-remaining">$0.00</strong></div>
                        </div>
                    </div>
                </div>
                <div class="form-actions qb-actions">
                    <button type="button" class="btn btn-secondary" onclick="CreditMemosPage.qbSave('close')">Save &amp; Close</button>
                    <button type="submit" class="btn btn-primary" onclick="event.preventDefault(); CreditMemosPage.qbSave('new')">Save &amp; New</button>
                    <button type="button" class="btn btn-secondary" id="qbc-clear" onclick="CreditMemosPage.qbClear()" title="Start this credit memo over">Clear</button>
                </div>
            </form>`, { wide: true });
        typeof LineOrder !== 'undefined' && LineOrder.attach('#cm-lines', { add: () => CreditMemosPage.addLine(), changed: () => CreditMemosPage.recalc() });
        CreditMemosPage.recalc();
        C.snap = state();
    };

    // Edit (a saved memo is changed by Void and Replace): the form filled in,
    // its number shown, Clear becomes Revert, and the state it opened with
    // is what Save & Close compares to.
    const baseReplace = CreditMemosPage.replace;
    CreditMemosPage.replace = async function (id) {
        await baseReplace.call(CreditMemosPage, id);
        const form = document.getElementById('cm-form');
        if (!form || !active()) return;
        C.id = id;
        try {
            const cm = await API.get(`/credit-memos/${id}`);
            const n = document.getElementById('qbc-number');
            if (n) n.value = cm.memo_number || '';
            const box = document.getElementById('qbc-customer');
            if (box) box.value = custAddress((CreditMemosPage._customers || []).find(c => c.id == cm.customer_id));
        } catch (e) { /* shown without them */ }
        const clear = document.getElementById('qbc-clear');
        if (clear) { clear.textContent = 'Revert'; clear.title = 'Put the credit memo back as it was saved'; }
        const submit = form.querySelector('button[type="submit"]');
        if (submit) submit.textContent = 'Save & New';
        CreditMemosPage.recalc();
        C.snap = state();
    };

    CreditMemosPage.qbClear = function () {
        return C.id ? CreditMemosPage.replace(C.id) : CreditMemosPage.showForm();
    };

    // Save & Close also closes a blank or unchanged memo. Once saved,
    // QuickBooks' question: keep the credit, or apply it now.
    CreditMemosPage.qbSave = async function (mode) {
        const form = document.getElementById('cm-form');
        if (!form) return;
        const blank = !form.customer_id.value && !Array.from(document.querySelectorAll('#cm-lines .line-rate')).some(i => num(i.value));
        if (mode === 'close' && (C.id ? C.snap === state() : blank)) { closeModal(); return; }
        if (!form.reportValidity()) return;
        const forInvoice = form.original_invoice_id.value || null;
        CreditMemosPage._lastSaved = null;
        await CreditMemosPage.save({ preventDefault() {}, target: form });
        const saved = CreditMemosPage._lastSaved;
        if (!saved) return;
        CreditMemosPage.qbAfterSave(saved, forInvoice, mode);
    };

    CreditMemosPage.qbAfterSave = function (cm, forInvoice, mode) {
        C.after = { id: cm.id, forInvoice, mode };
        openModal('Available Credit', `
            <form id="qbc-after" onsubmit="event.preventDefault(); CreditMemosPage.qbAfterChosen()">
                <p style="margin:0 0 10px;">Credit memo ${escapeHtml(cm.memo_number || '')} leaves <strong>${formatCurrency(cm.balance_remaining != null ? cm.balance_remaining : cm.total)}</strong> of credit for ${escapeHtml(cm.customer_name || '')}. What would you like to do with it?</p>
                <label style="display:block; margin:4px 0;"><input type="radio" name="qbc_use" value="retain" ${forInvoice ? '' : 'checked'}> Retain as an available credit</label>
                <label style="display:block; margin:4px 0;"><input type="radio" name="qbc_use" value="apply" ${forInvoice ? 'checked' : ''}> Apply to an ${T('invoice')}</label>
                <div class="form-actions">
                    <button type="submit" class="btn btn-primary">OK</button>
                </div>
            </form>`);
    };

    CreditMemosPage.qbAfterChosen = async function () {
        const a = C.after || {};
        const use = (document.querySelector('input[name="qbc_use"]:checked') || {}).value || 'retain';
        closeModal();
        if (use === 'apply') {
            await CreditMemosPage.showApply(a.id);
            // the invoice it was for gets the credit, up to what it owes
            const inp = a.forInvoice && document.querySelector(`.apply-amt[data-inv="${Number(a.forInvoice)}"]`);
            if (inp) {
                try {
                    const cm = await API.get(`/credit-memos/${a.id}`);
                    const owed = num(inp.closest('tr').querySelector('td.amount')?.textContent.replace(/[^0-9.-]/g, ''));
                    inp.value = Math.min(num(cm.balance_remaining), owed || Infinity).toFixed(2);
                } catch (e) { /* left at 0 */ }
            }
            return;
        }
        if (a.mode === 'new') CreditMemosPage.showForm();
    };
})();
