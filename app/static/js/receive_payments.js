/**
 * Receive Payments as QuickBooks Desktop 2020 lays it out (John's build).
 *
 * "Customer Payment": Received From with the Customer Balance, Payment
 * Amount and Date, Pmt. Method and Reference #, and where the payment goes
 * (Undeposited Funds, or a bank); the grid ✓ | Date | Number | Orig. Amt. |
 * Amt. Due | Payment with its totals; Amounts for Selected Invoices (Amount
 * Due, Applied, Discount and Credits Applied); Memo; Save & Close, Save &
 * New and Clear. Ticking an invoice pays what it owes, raising the Payment
 * Amount to cover it, as QuickBooks does; typing the amount fills the
 * invoices oldest first.
 *
 * Only the layout is new: the boxes keep the names and classes Payments'
 * own save reads (customer_id, amount, date, method, check_number,
 * deposit_to_account_id, notes; alloc-amount, alloc-discount), so the
 * payment is recorded exactly as before, credits and discounts included.
 */
(function () {
    if (typeof PaymentsPage === 'undefined') return;

    const cents = x => Math.round((parseFloat(x) || 0) * 100);
    const active = () => !!document.querySelector('#payment-form.qb-receive');
    const R = {};
    const METHODS = [['', ''], ['Check', 'Cheque'], ['Cash', 'Cash'], ['ACH/EFT', 'E-Transfer / EFT'], ['Credit Card', 'Credit Card'], ['Other', 'Other']];

    function state() {
        const form = document.getElementById('payment-form');
        return form ? JSON.stringify(Array.from(form.elements)
            .filter(e => e.type !== 'button' && e.type !== 'submit' && !(e.classList && e.classList.contains('cbx-input')) && !/-new-name$/.test(e.id || ''))
            .map(e => (e.type === 'checkbox' ? e.checked : e.value))) : '';
    }

    PaymentsPage.showForm = async function (_ignoredId = null, prefillCustomerId = null) {
        PaymentsPage._requestKey = null;
        PaymentsPage._giveBack = null;
        const [customers, accounts] = await Promise.all([
            API.get('/customers?active_only=true&tree=1'),
            API.get('/accounts'),
            PaymentClass.load(),
        ]);
        const bankAccts = accounts.filter(a => a.bank_kind === 'bank' && a.is_active !== false);
        PaymentsPage._accounts = accounts;
        R.customers = customers;
        const custOpts = customers.map(c => `<option value="${c.id}"${prefillCustomerId === c.id ? ' selected' : ''}>${escapeHtml(customerLabel(c))}</option>`).join('');
        const bankOpts = bankAccts.map(a => `<option value="${a.id}">${escapeHtml(a.name)}</option>`).join('');
        const undeposited = accounts.some(a => a.is_control && a.account_number === '1200');

        openModal('Receive Payments', `
            <form id="payment-form" class="qb-receive" onsubmit="event.preventDefault(); PaymentsPage.qbSave('close')">
                <div class="qbr-title">${T('Customer')} Payment</div>
                <div class="qbr-head">
                    <label for="qbr-customer">Received From</label>
                    <select id="qbr-customer" name="customer_id" required onchange="PaymentsPage.loadInvoices(this.value)">
                        <option value=""></option>${custOpts}</select>
                    <label>${T('Customer')} Balance</label>
                    <strong id="qbr-cust-balance" class="qbr-balance">0.00</strong>

                    <label for="qbr-amount">Payment Amount</label>
                    <input id="qbr-amount" name="amount" class="money" type="number" step="0.01" min="0.01" required oninput="PaymentsPage._autoApply()">
                    <label for="qbr-date">Date</label>
                    <input id="qbr-date" name="date" type="date" required value="${todayISO()}" onchange="PaymentsPage._suggestDiscounts()">

                    <label for="qbr-method">Pmt. Method</label>
                    <select id="qbr-method" name="method">${METHODS.map(([v, t]) => `<option value="${v}">${t}</option>`).join('')}</select>
                    <label for="qbr-ref">Reference #</label>
                    <input id="qbr-ref" name="check_number" maxlength="40" title="The cheque or transfer number">
                    <input type="hidden" name="reference">
                </div>
                <div class="qbr-goes">
                    <label for="qbr-deposit">Where does this payment go?</label>
                    <select id="qbr-deposit" name="deposit_to_account_id">
                        <option value="">${undeposited ? 'Undeposited Funds (group with other deposits)' : '--'}</option>${bankOpts}</select>
                    ${PaymentClass.groupHtml('payment-class')}
                </div>
                <div id="payment-invoices" class="qbr-invoices"><div class="qbr-empty">Select the ${T('customer')} or job in the Received From field</div></div>
                <div class="qbr-lower">
                    <div class="qbr-left">
                        <div id="keep-credit-row" hidden style="font-size:13px;">
                            <label style="font-weight:normal;"><input type="checkbox" id="keep-credit"> <span id="keep-credit-text"></span></label>
                        </div>
                        <div id="payment-credits"></div>
                        <div class="qbr-memo"><label for="qbr-memo">Memo</label><input id="qbr-memo" name="notes" maxlength="500"></div>
                    </div>
                    <div class="qbr-selected" aria-live="polite">
                        <div class="qbr-selected-head">Amounts for Selected ${T('Invoices')}</div>
                        <div><span>Amount Due</span><strong id="qbr-sel-due">0.00</strong></div>
                        <div><span>Applied</span><strong id="qbr-sel-applied">0.00</strong></div>
                        <div><span>Discount and Credits Applied</span><strong id="qbr-sel-disc">0.00</strong></div>
                    </div>
                </div>
                <div class="form-actions qb-actions">
                    <button type="button" class="btn btn-secondary" onclick="PaymentsPage.qbSave('close')">Save &amp; Close</button>
                    <button type="button" class="btn btn-primary" onclick="PaymentsPage.qbSave('new')">Save &amp; New</button>
                    <button type="button" class="btn btn-secondary" onclick="PaymentsPage.showForm()">Clear</button>
                </div>
            </form>`, { wide: true });
        R.snap = state();
        if (prefillCustomerId) PaymentsPage.loadInvoices(prefillCustomerId);
    };

    // Payments draws its Apply table; here it is laid out as QuickBooks'
    // grid. The inputs are the same ones, moved.
    const baseLoad = PaymentsPage.loadInvoices;
    PaymentsPage.loadInvoices = async function (customerId) {
        await baseLoad.call(PaymentsPage, customerId);
        if (!active()) return;
        const host = $('#payment-invoices');
        const invs = PaymentsPage._invoices || [];
        const bal = document.getElementById('qbr-cust-balance');
        if (bal) bal.textContent = PaymentsPage._fmt(invs.reduce((t, i) => t + (parseFloat(i.balance_due) || 0), 0));
        if (!customerId) { host.innerHTML = `<div class="qbr-empty">Select the ${T('customer')} or job in the Received From field</div>`; return; }
        const table = host.querySelector('table');
        if (!table) return;
        const discCol = invs.some(i => i.discount_date);
        const rows = invs.map(inv => {
            const disc = host.querySelector(`.alloc-discount[data-invoice="${inv.id}"]`);
            const amt = host.querySelector(`.alloc-amount[data-invoice="${inv.id}"]`);
            const tr = document.createElement('tr');
            tr.dataset.invoice = inv.id;
            tr.innerHTML = `<td><input type="checkbox" class="qbr-tick" aria-label="Pay ${escapeHtml(inv.invoice_number)}" onchange="PaymentsPage.qbTick(this)"></td>
                <td>${formatDate(inv.date)}</td>
                <td>${escapeHtml(inv.invoice_number)}${inv.status === 'draft' ? ' <span class="qbr-muted">(draft)</span>' : ''}</td>
                <td class="amount">${PaymentsPage._fmt(inv.total)}</td>
                <td class="amount">${PaymentsPage._fmt(inv.balance_due)}</td>
                <td class="amount qbr-disc"${discCol ? '' : ' hidden'}></td>
                <td class="amount qbr-pay"></td>`;
            if (disc) tr.querySelector('.qbr-disc').appendChild(disc);
            if (amt) tr.querySelector('.qbr-pay').appendChild(amt);
            return tr;
        });
        const grid = document.createElement('table');
        grid.className = 'line-items-table qbr-grid';
        grid.innerHTML = `<thead><tr><th scope="col" aria-label="Pay" style="width:30px;">✓</th><th scope="col">Date</th><th scope="col">Number</th>
            <th scope="col" class="amount">Orig. Amt.</th><th scope="col" class="amount">Amt. Due</th>
            <th scope="col" class="amount"${discCol ? '' : ' hidden'} title="The early-payment discount the terms allow">Discount</th><th scope="col" class="amount">Payment</th></tr></thead>
            <tbody></tbody>
            <tfoot><tr class="qbr-totals"><td></td><td colspan="2" style="text-align:right;">Totals</td>
                <td class="amount" id="qbr-tot-orig"></td><td class="amount" id="qbr-tot-due"></td><td class="amount"${discCol ? '' : ' hidden'} id="qbr-tot-disc"></td><td class="amount" id="qbr-tot-pay"></td></tr></tfoot>`;
        rows.forEach(r => grid.tBodies[0].appendChild(r));
        table.closest('.table-container').replaceChildren(grid);
        host.querySelector('h4')?.remove();
        const auto = Array.from(host.querySelectorAll('button')).find(b => /Apply oldest first/.test(b.textContent));
        if (auto) { auto.textContent = 'Auto Apply Payment'; auto.title = 'Apply the amount received to the oldest invoices first'; }
        PaymentsPage._updateAllocStatus();
    };

    // A tick pays what the invoice owes (less its discount); the Payment
    // Amount rises to cover what is ticked. Unticked, nothing is applied.
    PaymentsPage.qbTick = function (box) {
        const tr = box.closest('tr');
        const amt = tr.querySelector('.alloc-amount');
        const disc = tr.querySelector('.alloc-discount');
        if (!amt) return;
        if (box.checked) {
            const d = disc ? cents(disc.dataset.edited ? disc.value : disc.dataset.suggested) : 0;
            const owed = cents(amt.dataset.max) - d;
            amt.value = (owed / 100).toFixed(2);
            if (disc && d) disc.value = (d / 100).toFixed(2);
            const { total, allocated } = PaymentsPage._remainingCents();
            if (allocated > total) $('#qbr-amount').value = (allocated / 100).toFixed(2);
        } else {
            amt.value = '';
            if (disc) disc.value = '';
        }
        PaymentsPage._discountChanged(null);
    };

    // After Payments' own status: the ticks, the totals and the amounts for
    // the selected invoices.
    const baseStatus = PaymentsPage._updateAllocStatus;
    PaymentsPage._updateAllocStatus = function () {
        baseStatus.apply(PaymentsPage, arguments);
        if (!active()) return;
        const rows = Array.from(document.querySelectorAll('#payment-invoices .qbr-grid tbody tr'));
        if (!rows.length) return;
        let orig = 0, due = 0, disc = 0, pay = 0, selDue = 0;
        rows.forEach(tr => {
            const inv = (PaymentsPage._invoices || []).find(i => String(i.id) === tr.dataset.invoice) || {};
            const a = cents(tr.querySelector('.alloc-amount')?.value);
            const d = cents(tr.querySelector('.alloc-discount')?.value);
            orig += cents(inv.total); due += cents(inv.balance_due); disc += d; pay += a;
            if (a || d) selDue += cents(inv.balance_due);
            const tick = tr.querySelector('.qbr-tick');
            if (tick) tick.checked = a > 0 || d > 0;
        });
        const set = (id, c) => { const el = document.getElementById(id); if (el) el.textContent = PaymentsPage._fmt(c / 100); };
        set('qbr-tot-orig', orig); set('qbr-tot-due', due); set('qbr-tot-disc', disc); set('qbr-tot-pay', pay);
        set('qbr-sel-due', selDue); set('qbr-sel-applied', pay); set('qbr-sel-disc', disc);
    };

    // Save & Close also closes a blank form; Save & New opens a fresh one
    // once the payment is recorded.
    PaymentsPage.qbSave = async function (mode) {
        const form = document.getElementById('payment-form');
        if (!form) return;
        if (mode === 'close' && !form.customer_id.value && !cents(form.amount.value)) { closeModal(); return; }
        if (!form.reportValidity()) return;
        await PaymentsPage.save({ preventDefault() {}, target: form });
        const saved = !!document.getElementById('modal-overlay')?.classList.contains('hidden');
        if (saved && mode === 'new') setTimeout(() => PaymentsPage.showForm(), 250);
    };
})();
