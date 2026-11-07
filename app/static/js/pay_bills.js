/**
 * Pay Bills as QuickBooks Desktop 2020 lays it out (John's build).
 *
 * Select Bills to be Paid: Show bills due on or before a date or all of
 * them, Filter By vendor, Sort By; the grid ✓ | Date Due | Vendor | Ref.
 * No. | Disc. Date | Amt. Due | Disc. Used | Amt. To Pay with its totals and
 * Select All Bills. Information for the highlighted bill (vendor, ref. no.,
 * terms, suggested discount) with Go to Bill and Set Discount. Payment:
 * Date, Method, To be printed or Assign cheque no., Account and its ending
 * balance. Pay Selected Bills and Cancel.
 *
 * Only the layout is new: the boxes keep the names and classes Bills'
 * own Pay reads (pay-check, pay-discount, pay-amount, pay_from_account_id,
 * date, method, check_number), so the payment is made exactly as before —
 * one per vendor, discounts, the expired-COI check, Print Cheques for
 * cheques to be printed, and Void and Replace of a bill payment.
 */
(function () {
    if (typeof BillsPage === 'undefined') return;

    const P = { bills: [], vendors: [], accounts: [] };
    const METHODS = [['check', 'Cheque'], ['ach', 'Online / EFT'], ['cash', 'Cash'], ['credit_card', 'Credit Card']];
    const num = x => parseFloat(x) || 0;

    function rowHtml(b, con) {
        return `<tr class="qbp-row" data-bill="${b.id}" data-vendor="${b.vendor_id}" data-due="${escapeHtml(b.due_date || '')}" onclick="BillsPage.qbHighlight(this, event)">
            <td><input type="checkbox" class="pay-check" data-bill="${b.id}" data-balance="${b.balance_due}" aria-label="Pay bill ${escapeHtml(b.bill_number)}"></td>
            <td>${formatDate(b.due_date)}</td>
            <td>${escapeHtml(b.vendor_name || '')}${con ? BillsPage.complianceFlagHtml(b.vendor_compliance) : ''}</td>
            <td>${escapeHtml(b.bill_number || '')}</td>
            <td>${b.discount_date ? formatDate(b.discount_date) : ''}</td>
            <td class="amount">${formatCurrency(b.balance_due)}</td>
            <td class="amount"><input type="number" step="0.01" min="0" class="pay-discount money" data-bill="${b.id}" value="" aria-label="Discount used on bill ${escapeHtml(b.bill_number)}" oninput="BillsPage.payDiscountChanged(); BillsPage.qbPayTotals()"></td>
            <td class="amount"><input type="number" step="0.01" class="pay-amount money" data-bill="${b.id}" data-vendor="${b.vendor_id}" data-vendor-name="${escapeHtml(b.vendor_name || '')}" data-coi-expires="${con && b.vendor_compliance && b.vendor_compliance.is_sub && b.vendor_compliance.coi_expires ? b.vendor_compliance.coi_expires : ''}" value="0" aria-label="Amount to pay on bill ${escapeHtml(b.bill_number)}"></td>
            ${con ? `<td>${BillsPage.lienWaiverSelectHtml(b)}</td>` : ''}
        </tr>`;
    }

    BillsPage.showPayForm = async function (vendorId = null) {
        BillsPage._payKey = null;
        const [vendors, bills, accounts, allAccounts, , recent] = await Promise.all([
            API.get('/vendors?active_only=true'),
            fetchAllPages('/bills?open_only=true'),
            API.get('/accounts?bank=1&active_only=true'),
            API.get('/accounts?active_only=true'),
            PaymentClass.load(),
            API.get('/bill-payments?limit=1').catch(() => []),
        ]);
        const last = (Array.isArray(recent) ? recent : (recent && recent.items) || [])[0];
        // replacing a bill payment (#689): the bills it paid, at the balance
        // its void gives back
        for (const [billId, amt] of Object.entries(BillsPage._giveBack || {})) {
            let bill = bills.find(b => String(b.id) === String(billId));
            if (!bill) {
                try { bill = await API.get(`/bills/${Number(billId)}`); } catch (e) { bill = null; }
                if (bill) bills.push(bill);
            }
            if (bill) bill.balance_due = Math.round((num(bill.balance_due) + amt) * 100) / 100;
        }
        BillsPage._payBills = bills;
        P.bills = bills; P.vendors = vendors; P.accounts = accounts;
        const con = Terms.isConstruction();
        const withBills = vendors.filter(v => bills.some(b => b.vendor_id === v.id));
        const vendorOpts = withBills.map(v => `<option value="${v.id}"${String(v.id) === String(vendorId) ? ' selected' : ''}>${escapeHtml(v.name)}</option>`).join('');
        // the account the last bills were paid from, as QuickBooks remembers
        const start = (last && accounts.find(a => a.id === last.pay_from_account_id))
            || accounts.find(a => a.account_number === '1000') || accounts.find(a => a.bank_kind === 'bank') || accounts[0];
        const acctOpts = accounts.map(a => `<option value="${a.id}"${start && a.id === start.id ? ' selected' : ''}>${escapeHtml(a.name)}</option>`).join('');
        const soon = new Date(Date.now() + 10 * 86400000).toISOString().slice(0, 10);

        openModal('Pay Bills', `
            <form class="qb-pay-bills" onsubmit="BillsPage.savePay(event)">
                <div class="qbp-section">Select Bills to be Paid</div>
                <div class="qbp-filters">
                    <div class="qbp-show"><span>Show bills</span>
                        <label><input type="radio" name="qbp_show" value="due" onchange="BillsPage.qbPayFilter()"> Due on or before</label>
                        <input type="date" id="qbp-due-by" value="${soon}" onchange="BillsPage.qbPayFilter()" aria-label="Due on or before">
                        <label><input type="radio" name="qbp_show" value="all" checked onchange="BillsPage.qbPayFilter()"> Show all bills</label>
                    </div>
                    <label for="qbp-vendor">Filter By</label>
                    <select id="qbp-vendor" onchange="BillsPage.qbPayFilter()"><option value="">All vendors</option>${vendorOpts}</select>
                    <label for="qbp-sort">Sort By</label>
                    <select id="qbp-sort" onchange="BillsPage.qbPayFilter()">
                        <option value="due">Due Date</option><option value="vendor">Vendor</option>
                        <option value="disc">Discount Date</option><option value="amt">Amount Due</option>
                    </select>
                </div>
                <div class="table-container table-container--scroll qbp-grid-wrap"><table class="line-items-table qbp-grid">
                    <thead><tr>
                        <th scope="col" style="width:30px;" aria-label="Pay">✓</th>
                        <th scope="col">Date Due</th><th scope="col">Vendor</th><th scope="col">Ref. No.</th>
                        <th scope="col" title="The last day the vendor's early-payment discount can be taken">Disc. Date</th>
                        <th scope="col" class="amount">Amt. Due</th><th scope="col" class="amount">Disc. Used</th><th scope="col" class="amount">Amt. To Pay</th>
                        ${con ? '<th scope="col">Lien waiver</th>' : ''}
                    </tr></thead>
                    <tbody id="qbp-rows">${bills.map(b => rowHtml(b, con)).join('') || `<tr><td colspan="8" class="qbp-none">No open bills</td></tr>`}</tbody>
                    <tfoot><tr class="qbp-totals"><td colspan="5" style="text-align:right;">Totals</td>
                        <td class="amount" id="qbp-tot-due">$0.00</td><td class="amount" id="qbp-tot-disc">$0.00</td><td class="amount" id="qbp-tot-pay">$0.00</td>${con ? '<td></td>' : ''}</tr></tfoot>
                </table></div>
                <button type="button" class="btn btn-sm btn-secondary" id="qbp-select-all" onclick="BillsPage.qbSelectAll()">Select All Bills</button>
                <div class="form-group" id="pay-discount-account-row" hidden style="margin-top:8px; max-width:360px;">
                    <label for="pay-discount-account">Discount account</label>
                    <select id="pay-discount-account" data-no-search>${PaymentTerms.discountAccountOptions(allAccounts, 'purchases')}</select>
                    <div class="hint">Where the discounts we take post, as a vendor credit applied to each bill.</div></div>

                <div class="qbp-section">Information for Highlighted Bill</div>
                <div class="qbp-info" id="qbp-info">
                    <div><span>Vendor</span><strong id="qbp-i-vendor"></strong></div>
                    <div><span>Terms</span><strong id="qbp-i-terms"></strong></div>
                    <div><span>Bill Ref. No.</span><strong id="qbp-i-ref"></strong></div>
                    <div><span>Sugg. Discount</span><strong id="qbp-i-disc">0.00</strong></div>
                    <div class="qbp-info-buttons">
                        <button type="button" class="btn btn-sm btn-secondary" id="qbp-go" disabled onclick="BillsPage.qbGoToBill()">Go to Bill</button>
                        <button type="button" class="btn btn-sm btn-secondary" id="qbp-setdisc" disabled onclick="BillsPage.qbSetDiscount()">Set Discount</button>
                    </div>
                </div>

                <div class="qbp-section">Payment</div>
                <div class="qbp-payment">
                    <div class="form-group"><label for="qbp-date">Date</label>
                        <input id="qbp-date" name="date" type="date" required value="${todayISO()}" onchange="BillsPage.suggestPayDiscounts()"></div>
                    <div class="form-group"><label for="qbp-method">Method</label>
                        <select id="qbp-method" name="method" onchange="BillsPage.qbMethodChanged()">${METHODS.map(([v, t]) => `<option value="${v}">${t}</option>`).join('')}</select></div>
                    <div class="form-group qbp-cheque-opts" id="qbp-cheque-opts">
                        <label><input type="radio" name="qbp_print" value="print" checked onchange="BillsPage.qbChequeNo()"> To be printed</label>
                        <label><input type="radio" name="qbp_print" value="assign" onchange="BillsPage.qbChequeNo()"> Assign cheque no.</label>
                        <input name="check_number" id="qbp-chq" placeholder="Cheque no." aria-label="Cheque number" hidden>
                    </div>
                    <div class="form-group"><label for="qbp-account">Account</label>
                        <select id="qbp-account" name="pay_from_account_id" onchange="BillsPage.qbPayBalance()">${acctOpts}</select>
                        <div class="qbp-balance">Ending Balance <strong id="qbp-balance"></strong></div></div>
                    ${PaymentClass.groupHtml('pay-class')}
                </div>
                <div class="form-actions qb-actions">
                    <button type="submit" class="btn btn-primary">Pay Selected Bills</button>
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                </div>
            </form>`, { wide: true });

        $$('.pay-check').forEach(cb => cb.addEventListener('change', () => { BillsPage.fillPayRow(cb); BillsPage.qbPayTotals(); }));
        $$('.pay-amount').forEach(i => i.addEventListener('input', () => { BillsPage.followPayClass(); BillsPage.qbPayTotals(); }));
        BillsPage.qbPayBalance();
        BillsPage.qbPayFilter();
    };

    // Show bills / Filter By / Sort By: rows hidden or reordered; a hidden
    // row's tick and amount stay as they were, as QuickBooks keeps them.
    BillsPage.qbPayFilter = function () {
        const body = $('#qbp-rows');
        if (!body) return;
        const dueOnly = (document.querySelector('input[name="qbp_show"]:checked') || {}).value === 'due';
        const by = ($('#qbp-due-by') || {}).value || '';
        const vendor = ($('#qbp-vendor') || {}).value || '';
        const sort = ($('#qbp-sort') || {}).value || 'due';
        const bill = tr => P.bills.find(b => String(b.id) === tr.dataset.bill) || {};
        const rows = Array.from(body.querySelectorAll('tr.qbp-row'));
        const key = tr => {
            const b = bill(tr);
            if (sort === 'vendor') return [(b.vendor_name || '').toLowerCase(), b.due_date || ''];
            if (sort === 'disc') return [b.discount_date || '9999', b.due_date || ''];
            if (sort === 'amt') return [-num(b.balance_due), ''];
            return [b.due_date || '', (b.vendor_name || '').toLowerCase()];
        };
        rows.sort((a, b) => { const x = key(a), y = key(b); return x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : (x[1] < y[1] ? -1 : x[1] > y[1] ? 1 : 0); });
        rows.forEach(tr => {
            body.appendChild(tr);
            tr.hidden = (vendor && tr.dataset.vendor !== vendor) || (dueOnly && by && tr.dataset.due > by);
        });
        BillsPage.qbPayTotals();
    };

    BillsPage.qbPayTotals = function () {
        const rows = Array.from(document.querySelectorAll('#qbp-rows tr.qbp-row')).filter(tr => !tr.hidden);
        const sum = f => rows.reduce((t, tr) => t + f(tr), 0);
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = formatCurrency(Math.round(v * 100) / 100); };
        set('qbp-tot-due', sum(tr => num((P.bills.find(b => String(b.id) === tr.dataset.bill) || {}).balance_due)));
        set('qbp-tot-disc', sum(tr => num(tr.querySelector('.pay-discount').value)));
        set('qbp-tot-pay', sum(tr => num(tr.querySelector('.pay-amount').value)));
        const all = rows.length && rows.every(tr => tr.querySelector('.pay-check').checked);
        const btn = $('#qbp-select-all');
        if (btn) btn.textContent = all ? 'Clear Selections' : 'Select All Bills';
    };

    BillsPage.qbSelectAll = function () {
        const rows = Array.from(document.querySelectorAll('#qbp-rows tr.qbp-row')).filter(tr => !tr.hidden);
        const tick = !rows.every(tr => tr.querySelector('.pay-check').checked);
        rows.forEach(tr => {
            const cb = tr.querySelector('.pay-check');
            if (cb.checked !== tick) { cb.checked = tick; BillsPage.fillPayRow(cb); }
        });
        BillsPage.qbPayTotals();
    };

    BillsPage.qbHighlight = function (tr) {
        document.querySelectorAll('#qbp-rows tr.qbp-highlight').forEach(r => r.classList.remove('qbp-highlight'));
        tr.classList.add('qbp-highlight');
        const b = P.bills.find(x => String(x.id) === tr.dataset.bill) || {};
        P.highlight = b.id;
        const payDate = ($('#qbp-date') || {}).value;
        const sugg = PaymentTerms.suggestedCents ? PaymentTerms.suggestedCents(b, payDate) : 0;
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
        set('qbp-i-vendor', b.vendor_name || '');
        set('qbp-i-ref', b.bill_number || '');
        set('qbp-i-terms', b.terms || '');
        set('qbp-i-disc', (sugg / 100).toFixed(2));
        $('#qbp-go').disabled = !b.id;
        $('#qbp-setdisc').disabled = !b.id;
    };

    BillsPage.qbGoToBill = function () {
        if (P.highlight) BillsPage.showForm(P.highlight);
    };

    BillsPage.qbSetDiscount = function () {
        const box = document.querySelector(`.pay-discount[data-bill="${P.highlight}"]`);
        if (box) { box.focus(); box.select(); }
    };

    BillsPage.qbPayBalance = function () {
        const sel = $('#qbp-account');
        const a = sel && P.accounts.find(x => String(x.id) === sel.value);
        const el = $('#qbp-balance');
        if (el) el.textContent = a ? formatCurrency(num(a.balance)) : '';
    };

    // To be printed leaves the cheque number blank (Print Cheques numbers
    // it after); Assign cheque no. takes one now. Not a cheque: neither.
    BillsPage.qbChequeNo = function () {
        const assign = (document.querySelector('input[name="qbp_print"]:checked') || {}).value === 'assign';
        const box = $('#qbp-chq');
        if (!box) return;
        box.hidden = !assign;
        if (!assign) box.value = '';
        else box.focus();
    };

    BillsPage.qbMethodChanged = function () {
        const opts = $('#qbp-cheque-opts');
        const cheque = ($('#qbp-method') || {}).value === 'check';
        if (opts) opts.querySelectorAll('input[type=radio]').forEach(r => { r.disabled = !cheque; });
        // another method may still carry a reference number
        const box = $('#qbp-chq');
        if (!box) return;
        if (!cheque) { box.hidden = false; box.placeholder = 'Reference no.'; } else { box.placeholder = 'Cheque no.'; BillsPage.qbChequeNo(); }
    };

    // Void and Replace fills the form: the payment's cheque number decides
    // To be printed or Assign cheque no.
    const baseReplace = BillsPage.replacePayment;
    BillsPage.replacePayment = async function (id) {
        await baseReplace.call(BillsPage, id);
        const box = $('#qbp-chq');
        if (!box) return;
        const assign = document.querySelector(`input[name="qbp_print"][value="${box.value ? 'assign' : 'print'}"]`);
        if (assign) assign.checked = true;
        BillsPage.qbMethodChanged();
        BillsPage.qbPayBalance();
        BillsPage.qbPayTotals();
    };
})();
