/**
 * Create Invoices as QuickBooks Desktop 2020 lays it out (John's build).
 *
 * Customer:Job across the top; the invoice with Bill To on the left and
 * Date, Invoice #, Terms, Due Date and P.O. No. on the right; the grid
 * Item | Qty | Description | Rate | Amount | Tax (H or E); the GST/HST and
 * Total under it with Payments Applied and Balance Due; Customer Message
 * and Memo; Save & Close, Save & New and Clear (Revert on a saved one).
 *
 * Only the layout is new. The boxes keep the names and classes Invoices'
 * own save reads (customer_id, date, terms, due_date, po_number, tax_rate,
 * notes; line-item, line-desc, line-qty, line-rate, line-taxable), so an
 * invoice is saved exactly as before. A line's H or E is its taxable box
 * (kept, hidden, beside it); the rate is the company's GST/HST rate, or the
 * invoice's own when it has one. Save & Close on a blank invoice or an
 * unchanged one just closes.
 */
(function () {
    if (typeof InvoicesPage === 'undefined') return;

    const I = {};
    const num = x => parseFloat(x) || 0;
    const active = () => !!document.querySelector('#invoice-form.qb-invoice');

    function custAddress(c) {
        if (!c) return '';
        const city = [c.bill_city, [c.bill_state, c.bill_zip].filter(Boolean).join('  ')].filter(Boolean).join(', ');
        return [c.company_name || c.name, c.bill_address1, c.bill_address2, city].filter(Boolean).join('\n');
    }

    // A line as Invoices draws it, laid out as QuickBooks': its taxable
    // box hidden, an H/E picker shown in its place.
    function qbRow(idx, line, items) {
        const html = InvoicesPage._baseRowHtml(idx, line, items);
        const t = document.createElement('tbody');
        t.innerHTML = html;
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
        taxTd.insertAdjacentHTML('afterbegin', `<select class="qbi-tax" aria-label="GST/HST" title="H: GST/HST applies · E: exempt" onchange="InvoicesPage.qbTaxChanged(this)"><option value="H"${taxBox.checked ? ' selected' : ''}>H</option><option value="E"${taxBox.checked ? '' : ' selected'}>E</option></select>`);
        const btn = remove.querySelector('button');
        if (btn) { btn.className = 'btn btn-sm btn-secondary'; btn.innerHTML = '&times;'; }
        tr.replaceChildren(item, qty, desc, ...extras, rate, amount, taxTd, remove);
        return tr.outerHTML;
    }

    InvoicesPage._baseRowHtml = InvoicesPage.lineRowHtml;
    InvoicesPage.lineRowHtml = function (idx, line, items) {
        return active() || I.drawing ? qbRow(idx, line, items) : InvoicesPage._baseRowHtml(idx, line, items);
    };

    InvoicesPage.qbTaxChanged = function (sel) {
        const box = sel.closest('tr').querySelector('.line-taxable');
        if (box) box.checked = sel.value === 'H';
        InvoicesPage.recalc();
    };

    // After the totals: the H/E pickers follow their boxes (a tax-exempt
    // customer unticks them), and Total, Payments Applied, Balance Due.
    const baseRecalc = InvoicesPage.recalc;
    InvoicesPage.recalc = function () {
        const t = baseRecalc.apply(InvoicesPage, arguments);
        if (!active()) return t;
        document.querySelectorAll('#inv-lines tr').forEach(tr => {
            const box = tr.querySelector('.line-taxable');
            const sel = tr.querySelector('.qbi-tax');
            if (box && sel) { sel.value = box.checked ? 'H' : 'E'; sel.disabled = box.disabled; }
        });
        const paid = I.inv ? num(I.inv.amount_paid) : 0;
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = formatCurrency(v); };
        set('qbi-paid', paid);
        set('qbi-balance', Math.round((num(t && t.total) - paid) * 100) / 100);
        return t;
    };

    const baseCustomerSelected = InvoicesPage.customerSelected;
    InvoicesPage.customerSelected = function (customerId) {
        baseCustomerSelected.call(InvoicesPage, customerId);
        const box = document.getElementById('qbi-billto');
        if (box) box.value = custAddress((InvoicesPage._customers || []).find(c => c.id == customerId));
    };

    function state() {
        const form = document.getElementById('invoice-form');
        return form ? JSON.stringify(Array.from(form.elements)
            .filter(e => e.type !== 'button' && e.type !== 'submit' && !(e.classList && e.classList.contains('cbx-input')) && !/-new-name$/.test(e.id || ''))
            .map(e => (e.type === 'checkbox' ? e.checked : e.value))) : '';
    }

    InvoicesPage.showForm = async function (id = null, prefillCustomerId = null) {
        const [customers, items, settings, messages] = await Promise.all([
            API.get('/customers?active_only=true&tree=1'),
            API.get('/items?active_only=true'),
            API.get('/settings'),
            API.get('/invoice-messages').catch(() => []),
            PaymentTerms.load(),
        ]);
        InvoicesPage._messages = messages;
        const defaultMessage = messages.find(m => m.is_default);
        const canada = settings.sales_tax_system === 'canada' && !!settings.hst_account_id;
        const hstRate = settings.hst_rate || '13';
        let inv = {
            customer_id: prefillCustomerId || '',
            date: todayISO(),
            terms: settings.default_terms || 'Net 30',
            po_number: '',
            tax_rate: (parseFloat((canada ? hstRate : settings.default_tax_rate) || '0') || 0) / 100,
            notes: defaultMessage ? defaultMessage.body : (settings.invoice_notes || ''),
            lines: [],
        };
        if (id) inv = await API.get(`/invoices/${id}`);
        I.inv = id ? inv : null;
        I.id = id;
        InvoicesPage._formInvoiceId = id || null;
        InvoicesPage._keptTax = id && !(parseFloat(inv.tax_rate) > 0) && parseFloat(inv.tax_amount) > 0
            ? parseFloat(inv.tax_amount) : null;
        InvoicesPage._editing = id ? { total: num(inv.total), paid: num(inv.amount_paid) } : null;
        const classGroup = await classFormGroupHtml(inv.class_id);
        const jobGroup = await jobFormGroupHtml(inv.job_id, 'inv-customer-select');
        if (InvoicesPage.lineClasses()) await Nonprofit.loadFunds();
        const pledgeGroup = Terms.isNonprofit() ? `<div class="form-group"><label>Document</label><label style="font-weight:normal;"><input type="checkbox" name="is_pledge" ${(id ? inv.is_pledge : true) ? 'checked' : ''}> This is a pledge (prints as PLEDGE)</label></div>` : '';
        if (inv.lines.length === 0) inv.lines = [{ item_id: '', description: '', quantity: 1, rate: 0 }];
        InvoicesPage.lineCount = inv.lines.length;
        InvoicesPage._items = items;
        InvoicesPage._customers = customers;
        const custOpts = customers.map(c => `<option value="${c.id}" ${inv.customer_id == c.id ? 'selected' : ''}>${escapeHtml(customerLabel(c))}</option>`).join('');
        const ratePct = +((inv.tax_rate || 0) * 100).toFixed(4);
        // a rate of its own (an imported or US-style invoice) stays visible;
        // the company's GST/HST rate rides along unseen
        const showRate = !canada || (id && Math.abs(ratePct - parseFloat(hstRate)) > 0.0001 && InvoicesPage._keptTax == null);
        // A document at a rate of 1 is in the home currency, whatever code it
        // was stored with (the imports kept the default, USD): it shows and
        // saves as the home currency. One at another rate shows its own.
        const home = (settings.home_currency || 'USD').toUpperCase();
        const foreign = id && Number(inv.exchange_rate || 1) !== 1;
        const currency = foreign
            ? currencyFormGroupsHtml(inv.currency, inv.exchange_rate)
            : `<input type="hidden" name="currency" value="${escapeHtml(home)}"><input type="hidden" name="exchange_rate" value="${escapeHtml(String(inv.exchange_rate || 1))}">`;
        const extraGroups = `${classGroup}${jobGroup}${pledgeGroup}${foreign ? currency : ''}${showRate ? `<div class="form-group"><label>Tax Rate (%)</label>
                <input name="tax_rate" type="number" step="0.0001" value="${ratePct}" oninput="InvoicesPage.recalc()"></div>` : ''}`;
        const taxLabel = canada ? `GST/HST (${escapeHtml(showRate ? String(ratePct) : hstRate)}%)` : 'Tax';

        I.drawing = true;
        const lineRows = inv.lines.map((l, i) => InvoicesPage.lineRowHtml(i, l, items)).join('');
        I.drawing = false;

        openModal(id ? `Create Invoices — ${escapeHtml(inv.invoice_number || '')} (editing)` : Terms.text('Create Invoices'), `
            <form id="invoice-form" class="qb-invoice" aria-labelledby="modal-title" data-skip-to="#inv-lines" data-skip-text="Skip to the line items" onsubmit="event.preventDefault(); InvoicesPage.qbSave('close')">
                <div class="qbi-bar">
                    <label for="inv-customer-select">${T('Customer')}:${T('Job')}</label>
                    <select name="customer_id" id="inv-customer-select" required onchange="InvoicesPage.customerSelected(this.value)"><option value="">Select...</option><option value="__new__">+ ${T('New Customer')}</option>${custOpts}</select>
                    <span class="qbi-logo">${InvoicesPage.logoOptionHtml(settings)}</span>
                </div>
                <div id="inv-new-customer-form" style="display:none; margin:8px 0; padding:8px; border:1px solid var(--gray-300); border-radius:4px; background:var(--primary-light); max-width:360px;">
                    <div style="font-weight:700; font-size:11px; margin-bottom:6px;">Quick Add ${T('Customer')}</div>
                    <input id="inv-new-cust-name" placeholder="Name *" aria-label="${T('Customer')} name" aria-required="true" style="width:100%; margin-bottom:4px;">
                    <input id="inv-new-cust-email" placeholder="Email" style="width:100%; margin-bottom:4px;">
                    <input id="inv-new-cust-phone" placeholder="Phone" style="width:100%; margin-bottom:4px;">
                    <div style="display:flex; gap:6px;">
                        <button type="button" class="btn btn-sm btn-primary" onclick="InvoicesPage.saveNewCustomer()">Save</button>
                        <button type="button" class="btn btn-sm btn-secondary" onclick="InvoicesPage.cancelNewCustomer()">Cancel</button>
                    </div>
                </div>
                <div class="qbi-paper">
                    <div class="qbi-head">
                        <div class="qbi-title">${Terms.text('Invoice')}</div>
                        <div class="qbi-billto"><label for="qbi-billto">Bill To</label>
                            <textarea id="qbi-billto" rows="4" readonly tabindex="-1" title="From the ${T('customer')}'s record"></textarea></div>
                        <div class="qbi-fields">
                            <div><label for="qbi-date">Date</label>
                                <input id="qbi-date" name="date" type="date" required value="${inv.date}" onchange="InvoicesPage._recomputeDueDate()"></div>
                            <div><label>${T('Invoice')} #</label>
                                <input value="${escapeHtml(id ? (inv.invoice_number || '') : '')}" placeholder="next number" readonly tabindex="-1" title="Numbered when it is saved"></div>
                            <div><label for="invoice-terms">Terms</label>
                                <select name="terms" id="invoice-terms" onchange="InvoicesPage._recomputeDueDate()">
                                    ${PaymentTerms.optionsHtml(inv.terms, null, !id || inv.payment_term_id != null)}
                                </select></div>
                            <div><label for="qbi-due">Due Date</label>
                                <input id="qbi-due" name="due_date" type="date" value="${inv.due_date || ''}" title="From Date + Terms; change it to override"></div>
                            <div><label for="qbi-po">P.O. No.</label>
                                <input id="qbi-po" name="po_number" value="${escapeHtml(inv.po_number || '')}"></div>
                            <div class="hint" id="invoice-terms-hint">${PaymentTerms.hintHtml({ note: inv.terms_note, discount_line: inv.discount_line })}</div>
                        </div>
                    </div>
                    ${extraGroups.trim() ? `<div class="form-grid qb-extra">${extraGroups}</div>` : ''}
                    ${showRate ? '' : `<input type="hidden" name="tax_rate" value="${ratePct}">`}
                    ${foreign ? '' : currency}
                    ${InvoicesPage._keptTax != null ? `<div class="hint" id="inv-kept-tax">Tax stays at ${formatCurrency(InvoicesPage._keptTax)}, the amount it came in with.</div>` : ''}
                    <div class="table-container table-container--scroll"><table class="line-items-table qbi-grid">
                        <thead><tr>
                            <th scope="col">Item</th><th scope="col" class="col-qty">Qty</th><th scope="col">Description</th>
                            ${InvoicesPage.lineClasses() ? Nonprofit.classHeadHtml() : ''}
                            <th scope="col" class="col-rate">Rate</th><th scope="col" class="col-amount">Amount</th>
                            <th scope="col" title="H: ${canada ? 'GST/HST' : 'sales tax'} applies · E: exempt">Tax</th><th scope="col" class="col-actions"></th>
                        </tr></thead>
                        <tbody id="inv-lines">${lineRows}</tbody>
                    </table></div>
                    <button type="button" class="btn btn-sm btn-secondary" style="margin-top:6px;" onclick="InvoicesPage.addLine()">+ Add Line</button>
                    <div class="qbi-bottom">
                        <div class="qbi-message">
                            ${messages.length ? `<label for="inv-message-select">${T('Customer')} Message</label>
                                <select name="message_id" id="inv-message-select" onchange="InvoicesPage.messageChosen(this.value)">
                                    <option value=""></option>
                                    ${messages.map(m => `<option value="${m.id}" ${(inv.notes || '').trim() === m.body.trim() ? 'selected' : ''}>${escapeHtml(m.name)}</option>`).join('')}
                                </select>` : `<label for="qbi-notes">${T('Customer')} Message</label>`}
                            <textarea id="qbi-notes" name="notes" rows="2" aria-label="Message printed on the ${T('invoice')}">${escapeHtml(inv.notes || '')}</textarea>
                        </div>
                        <div class="qb-totals invoice-totals" id="inv-totals" aria-live="polite">
                            <div class="qb-total-row"><span>Subtotal</span><strong id="inv-subtotal">$0.00</strong></div>
                            <div class="qb-total-row"><span>${taxLabel}</span><strong id="inv-tax">$0.00</strong></div>
                            <div class="qb-total-row qb-total-row--grand"><span>Total</span><strong id="inv-total">$0.00</strong></div>
                            <div class="qb-total-row"><span>Payments Applied</span><strong id="qbi-paid">$0.00</strong></div>
                            <div class="qb-total-row qb-total-row--grand"><span>Balance Due</span><strong id="qbi-balance">$0.00</strong></div>
                        </div>
                    </div>
                </div>
                <div class="form-actions qb-actions">
                    <button type="button" class="btn btn-secondary" onclick="InvoicesPage.qbSave('close')" data-invoice-logo-action>Save &amp; Close</button>
                    <button type="button" class="btn btn-primary" onclick="InvoicesPage.qbSave('new')">Save &amp; New</button>
                    <button type="button" class="btn btn-secondary" onclick="InvoicesPage.qbClear()" title="${id ? `Put the ${T('invoice')} back as it was saved` : `Start this ${T('invoice')} over`}">${id ? 'Revert' : 'Clear'}</button>
                </div>
            </form>`, { wide: true });

        if (!id && inv.customer_id) InvoicesPage.customerSelected(inv.customer_id);
        else if (id) $('#qbi-billto').value = custAddress(customers.find(c => c.id == inv.customer_id));
        $('#invoice-form [name="currency"]')?.addEventListener('change', () => InvoicesPage.recalc());
        typeof LineOrder !== 'undefined' && LineOrder.attach('#inv-lines', { add: () => InvoicesPage.addLine(), changed: () => InvoicesPage.recalc() });
        InvoicesPage.recalc();
        if (!inv.due_date) await InvoicesPage._recomputeDueDate();
        InvoicesPage._payAppInvoice = !!inv.pay_application_id;
        if (InvoicesPage._payAppInvoice) {
            $$('#invoice-form input, #invoice-form select, #invoice-form textarea').forEach(el => {
                if (el.name !== 'notes') el.disabled = true;
            });
            $('#invoice-form .form-actions').insertAdjacentHTML('beforebegin',
                '<div class="form-hint">This invoice comes from a payment application. Change the application to change the amounts; only the notes can be edited here.</div>');
        }
        I.snap = state();
    };

    InvoicesPage.qbClear = function () {
        InvoicesPage.showForm(I.id || null);
    };

    // Save & Close also closes a blank or unchanged invoice; Save & New
    // opens a fresh one once this one is saved.
    InvoicesPage.qbSave = async function (mode) {
        const form = document.getElementById('invoice-form');
        if (!form) return;
        const blank = !form.customer_id.value && !Array.from(document.querySelectorAll('#inv-lines .line-rate')).some(i => num(i.value));
        if (mode === 'close' && (I.id ? I.snap === state() : blank)) { closeModal(); return; }
        if (!form.reportValidity()) return;
        // Invoices' own save; it redraws the page when the invoice is saved,
        // which closes this window
        await InvoicesPage.save({ preventDefault() {}, target: form }, I.id || null);
        const saved = !!document.getElementById('modal-overlay')?.classList.contains('hidden');
        if (saved && mode === 'new') setTimeout(() => InvoicesPage.showForm(), 250);
    };
})();
