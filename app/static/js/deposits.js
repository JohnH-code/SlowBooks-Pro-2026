/**
 * Make Deposits — Move funds from Undeposited Funds to a bank account
 * Classic QB deposit slip workflow. A deposit remembers the payments it
 * took; voiding it (Recent deposits) puts them back on the list, which is
 * how one payment comes out of a deposit.
 */
const DepositsPage = {
    async render() {
        const [pending, accounts, classes, recent] = await Promise.all([
            API.get('/deposits/pending'),
            API.get('/accounts'),
            API.get('/classes').catch(() => []),
            API.get('/deposits?limit=20').catch(() => []),
        ]);
        // The Class picker starts on the system default; with Settings'
        // "Warn when a transaction is saved without a class" on (#243) it
        // starts blank, as every entry form does, so Deposit asks first.
        const blank = classes.length && ClassWarn.enabled();
        const classOpts = (blank ? `<option value="" selected>— choose a ${T('class').toLowerCase()} —</option>` : '') + classes.map(c =>
            `<option value="${c.id}" ${c.is_system_default && !blank ? 'selected' : ''}>${escapeHtml(c.name)}</option>`
        ).join('');

        const bankAccts = accounts.filter(a => a.bank_kind === 'bank');
        const bankOpts = bankAccts.map(a => `<option value="${a.id}">${escapeHtml(a.name)} (${formatCurrency(a.balance)})</option>`).join('');

        let html = `
            <div class="page-header">
                <h2>Make Deposits</h2>
                <div style="font-size:10px; color:var(--text-muted);">
                    Select payments to deposit from Undeposited Funds to a bank account
                </div>
            </div>
            <div class="toolbar" data-write>
                <label for="deposit-bank-acct" style="font-size:10px;font-weight:700;">Deposit To:</label>
                <select id="deposit-bank-acct">${bankOpts.length ? bankOpts : '<option>No bank accounts</option>'}</select>
                <label for="deposit-date" style="font-size:10px;font-weight:700;">Date:</label>
                <input type="date" id="deposit-date" value="${todayISO()}">
                <label for="deposit-ref" style="font-size:10px;font-weight:700;">Reference:</label>
                <input type="text" id="deposit-ref" placeholder="Deposit slip #" style="width:120px;">
                ${classOpts ? `<label for="deposit-class" style="font-size:10px;font-weight:700;">${T('Class')}:</label>
                <select id="deposit-class">${classOpts}</select>` : ''}
            </div>`;

        DepositsPage._accounts = accounts;
        if (pending.length === 0) {
            html += '<div class="empty-state" style="padding:12px;"><p>No payments waiting to be deposited</p></div>';
        } else {
            html += `<div class="table-container"><table>
                <thead><tr>
                    <th scope="col" style="width:30px;"><input type="checkbox" id="dep-select-all" data-write aria-label="Select all payments" onchange="DepositsPage.toggleAll()"></th>
                    <th scope="col">Date</th><th scope="col">Received From</th><th scope="col">Description</th>
                    <th scope="col">Check # / Ref</th><th scope="col">Method</th>
                    <th scope="col" class="amount">Amount</th>
                </tr></thead><tbody>`;
            for (const p of pending) {
                html += `<tr>
                    <td><input type="checkbox" class="dep-check" data-write data-lineid="${p.transaction_line_id}" data-amount="${p.amount}" aria-label="Deposit ${escapeHtml(p.description)}" onchange="DepositsPage.recalc()"></td>
                    <td>${formatDate(p.date)}</td>
                    <td>${escapeHtml(p.received_from || '')}</td>
                    <td>${escapeHtml(p.description)}${DepositsPage._paid(p)}</td>
                    <td>${escapeHtml(DepositsPage._ref(p))}</td>
                    <td>${escapeHtml(p.method || '')}</td>
                    <td class="amount">${formatCurrency(p.amount)}</td>
                </tr>`;
            }
            html += `</tbody></table></div>`;
        }
        // QuickBooks' other half of Make Deposits: money that goes straight
        // in from another account — interest, a shareholder loan, income
        // with no invoice behind it.
        html += `
            <h3 style="margin:16px 0 6px; font-size:13px;">Other deposits</h3>
            <div style="font-size:10px; color:var(--text-muted); margin-bottom:6px;">
                Money deposited straight from another account. A negative amount is cash back.
            </div>
            <div class="table-container" data-write><table>
                <thead><tr><th scope="col">Received From</th><th scope="col">From Account</th><th scope="col">Memo</th><th scope="col" class="amount">Amount</th><th scope="col"></th></tr></thead>
                <tbody id="deposit-other-rows"></tbody>
                <tfoot><tr><td colspan="5"><button type="button" class="btn btn-sm btn-secondary" onclick="DepositsPage.addOtherRow()">+ Add line</button></td></tr></tfoot>
            </table></div>
            <div style="margin-top:12px; display:flex; justify-content:space-between; align-items:center;" data-write>
                <div id="deposit-total" style="font-size:16px; font-weight:700; color:var(--qb-navy);">
                    Deposit total: $0.00
                </div>
                <button class="btn btn-primary" onclick="DepositsPage.makeDeposit()">Make Deposit</button>
            </div>`;
        html += DepositsPage._recentHtml(recent);
        return html;
    },

    // "Check 4420 · REF-9": the check number and the payment's own
    // reference, else whatever the posting carried.
    _ref(p) {
        const parts = [];
        if (p.check_number) parts.push(`Check ${p.check_number}`);
        if (p.payment_reference && p.payment_reference !== p.check_number) parts.push(p.payment_reference);
        return parts.length ? parts.join(' · ') : (p.reference || '');
    },

    // What a plain payment paid ("for Invoice #1001"); a sales receipt's
    // number is already its description.
    _paid(p) {
        if (!p.document || (p.description || '').includes(p.document)) return '';
        return ` <span style="color:var(--text-muted);">for ${escapeHtml(p.document)}</span>`;
    },

    _recentHtml(recent) {
        if (!recent.length) return '';
        const rows = recent.map(d => {
            const status = d.voided ? 'Void' : (d.reconciled ? 'Reconciled' : '');
            const canVoid = !d.voided && !d.reconciled;
            return `<tr style="${d.voided ? 'color:var(--gray-400); text-decoration:line-through;' : ''}">
                <td>${formatDate(d.date)}</td>
                <td>${escapeHtml(d.account_name || '')}</td>
                <td>${escapeHtml(d.reference || '')}</td>
                <td class="amount">${d.items == null ? '' : d.items}</td>
                <td class="amount">${formatCurrency(d.amount)}</td>
                <td>${escapeHtml(status)}</td>
                <td class="actions"><button class="btn btn-sm btn-secondary" onclick="DepositsPage.view(${d.id})">View</button>
                    ${d.voided ? '' : `<button class="btn btn-sm btn-secondary" onclick="window.open('/api/deposits/${d.id}/print-preview','_blank')" title="The deposit slip">Print</button>`}
                    ${canVoid ? `<button data-destructive class="btn btn-sm btn-secondary" onclick="DepositsPage.voidDeposit(${d.id})">Void</button>` : ''}</td>
            </tr>`;
        }).join('');
        return `
            <h3 style="margin:20px 0 8px; font-size:14px;">Recent deposits</h3>
            <div style="font-size:10px; color:var(--text-muted); margin-bottom:6px;">
                To take a payment out of a deposit, void the deposit: its payments go back on the list above to deposit again.
            </div>
            <div class="table-container"><table>
                <thead><tr><th scope="col">Date</th><th scope="col">Deposited To</th><th scope="col">Slip #</th>
                <th scope="col" class="amount">Payments</th><th scope="col" class="amount">Amount</th><th scope="col">Status</th><th scope="col"></th></tr></thead>
                <tbody>${rows}</tbody>
            </table></div>`;
    },

    // One deposit and the payments it took, with Void while it can still be
    // voided. The bank register links a deposit to #/deposits/{id}, which
    // said "Page not found" (explore 2.17.3).
    async view(id) {
        const d = await API.get(`/deposits/${id}`);
        const status = d.voided ? 'Void' : (d.reconciled ? 'Reconciled' : 'Deposited');
        const rows = (d.payments || []).map(p => `<tr>
                <td>${formatDate(p.date)}</td>
                <td>${escapeHtml(p.received_from || '')}</td>
                <td>${escapeHtml(p.description)}${DepositsPage._paid(p)}</td>
                <td>${escapeHtml(DepositsPage._ref(p))}</td>
                <td>${escapeHtml(p.method || '')}</td>
                <td class="amount">${formatCurrency(p.amount)}</td>
            </tr>`).join('');
        const payments = rows
            ? `<div class="table-container"><table>
                <thead><tr><th scope="col">Date</th><th scope="col">Received From</th><th scope="col">Description</th>
                <th scope="col">Check # / Ref</th><th scope="col">Method</th><th scope="col" class="amount">Amount</th></tr></thead>
                <tbody>${rows}</tbody></table></div>`
            : `<p style="font-size:11px; color:var(--text-muted);">${d.voided
                ? 'This deposit is void: its payments went back on the Make Deposits list.'
                : 'This deposit does not list its payments: it was recorded as an amount (imported, or made before deposits kept their list).'}</p>`;
        const otherRows = (d.other_lines || []).map(o => `<tr>
                <td>${escapeHtml(o.account_number ? o.account_number + ' · ' : '')}${escapeHtml(o.account_name)}</td>
                <td>${escapeHtml(o.description || '')}</td>
                <td class="amount">${formatCurrency(o.amount)}</td></tr>`).join('');
        const others = otherRows ? `<div class="table-container" style="margin-top:8px;"><table>
                <thead><tr><th scope="col">From Account</th><th scope="col">Received From / Memo</th><th scope="col" class="amount">Amount</th></tr></thead>
                <tbody>${otherRows}</tbody></table></div>` : '';
        const canVoid = !d.voided && !d.reconciled;
        openModal(`Deposit — ${formatDate(d.date)}`, `
            <div style="margin-bottom:12px;">
                <strong>Deposited to:</strong> ${escapeHtml(d.account_name || '')}<br>
                <strong>Date:</strong> ${formatDate(d.date)}<br>
                ${d.reference ? `<strong>Slip #:</strong> ${escapeHtml(d.reference)}<br>` : ''}
                <strong>Amount:</strong> ${formatCurrency(d.amount)}<br>
                <strong>Status:</strong> ${status}${d.reconciled && !d.voided ? ' — on a reconciled bank statement, so it can\'t be voided' : ''}
            </div>
            ${rows || !otherRows ? payments : ''}
            ${others}
            <div style="margin-top:12px; border-top:1px solid var(--gray-300); padding-top:8px;">
                <div style="font-weight:700; font-size:12px; margin-bottom:4px;">Attachments</div>
                <div id="deposit-attachments-list" style="margin-bottom:8px; font-size:11px;">Loading...</div>
                <div style="display:flex; gap:6px; align-items:center;" data-write>
                    <input type="file" id="deposit-attach-file" aria-label="File to attach" style="font-size:11px;">
                    <button class="btn btn-sm btn-secondary" onclick="DepositsPage.uploadAttachment(${d.id})">Attach</button>
                </div>
            </div>
            <div class="form-actions">
                ${canVoid ? `<button data-destructive type="button" class="btn btn-danger" onclick="DepositsPage.voidDeposit(${d.id})">Void</button>` : ''}
                ${d.voided ? '' : `<button type="button" class="btn btn-secondary" onclick="window.open('/api/deposits/${d.id}/pdf','_blank')">Save PDF</button>
                <button type="button" class="btn btn-secondary" onclick="window.open('/api/deposits/${d.id}/print-preview','_blank')">Print</button>
                ${(d.other_lines || []).length ? (typeof Memorized !== "undefined" ? Memorized.button({ transaction_id: d.id }, 'Deposit') : "") : ''}`}
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Close</button>
            </div>`);
        // the document's own address, so Back returns to the list and the Open group lists it (NEW-164)
        if (App.documentAddress) App.documentAddress(`#/deposits/${Number(id)}`);
        DepositsPage.loadAttachments(d.id);
    },

    addOtherRow() {
        const body = $('#deposit-other-rows');
        if (!body) return;
        const bankId = parseInt($('#deposit-bank-acct')?.value) || null;
        const opts = (DepositsPage._accounts || [])
            .filter(a => a.is_active !== false && a.id !== bankId && a.account_number !== '1200')
            .map(a => `<option value="${a.id}">${accountLabel(a)}</option>`).join('');
        const tr = document.createElement('tr');
        tr.innerHTML = `<td><input data-other="from" aria-label="Received from" maxlength="120"></td>
            <td><select data-other="account" aria-label="From account"><option value="">Select...</option>${opts}</select></td>
            <td><input data-other="memo" aria-label="Memo" maxlength="160"></td>
            <td class="amount"><input data-other="amount" aria-label="Amount" type="number" step="0.01" style="width:110px; text-align:right;" oninput="DepositsPage.recalc()"></td>
            <td><button type="button" class="btn btn-sm btn-danger" aria-label="Remove line" onclick="this.closest('tr').remove(); DepositsPage.recalc()">×</button></td>`;
        body.appendChild(tr);
    },

    _otherLines() {
        return [...document.querySelectorAll('#deposit-other-rows tr')].map(tr => ({
            received_from: tr.querySelector('[data-other="from"]').value.trim() || null,
            account_id: parseInt(tr.querySelector('[data-other="account"]').value) || null,
            memo: tr.querySelector('[data-other="memo"]').value.trim() || null,
            amount: parseFloat(tr.querySelector('[data-other="amount"]').value) || 0,
        })).filter(l => l.account_id || l.amount || l.received_from || l.memo);
    },

    async loadAttachments(id) {
        const el = $('#deposit-attachments-list');
        if (!el) return;
        try {
            const attachments = await API.get(`/attachments/deposit/${id}`);
            el.innerHTML = attachments.length === 0
                ? '<span style="color:var(--text-muted);">No attachments</span>'
                : attachments.map(a => `<div style="display:flex; flex-wrap:wrap; align-items:center; gap:0 8px; padding:2px 0;">
                    ${a.missing ? `<span>${escapeHtml(a.filename)}</span>` : `<a href="/api/attachments/download/${a.id}" target="_blank">${escapeHtml(a.filename)}</a>`}
                    ${a.file_size == null ? '' : `<span style="color:var(--gray-400);">(${formatFileSize(a.file_size)})</span>`}
                    <button data-destructive aria-label="Delete attachment" class="btn btn-sm btn-danger" onclick="DepositsPage.deleteAttachment(${a.id},${id})" style="padding:0 4px; font-size:10px;">X</button>
                </div>`).join('');
        } catch (e) { el.innerHTML = ''; }
    },

    async uploadAttachment(id) {
        const fileInput = $('#deposit-attach-file');
        if (!fileInput?.files[0]) { toast('Select a file first', 'error'); return; }
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        try {
            const resp = await fetch(`/api/attachments/deposit/${id}`, { method: 'POST', body: formData });
            if (!resp.ok) throw new Error(await API.responseError(resp, 'Upload failed'));
            toast('Attachment uploaded');
            fileInput.value = '';
            DepositsPage.loadAttachments(id);
        } catch (err) { toast(err.message, 'error'); }
    },

    async deleteAttachment(attachmentId, id) {
        if (!confirm('Delete this attachment?')) return;
        try {
            await API.del(`/attachments/${attachmentId}`);
            toast('Attachment deleted');
            DepositsPage.loadAttachments(id);
        } catch (err) { toast(err.message, 'error'); }
    },

    toggleAll() {
        const checked = $('#dep-select-all').checked;
        $$('.dep-check').forEach(cb => { cb.checked = checked; });
        DepositsPage.recalc();
    },

    recalc() {
        let cents = 0, count = 0;
        $$('.dep-check').forEach(cb => {
            if (cb.checked) {
                cents += Math.round((parseFloat(cb.dataset.amount) || 0) * 100);
                count++;
            }
        });
        const otherCents = DepositsPage._otherLines().reduce((t, l) => t + Math.round(l.amount * 100), 0);
        const el = $('#deposit-total');
        if (el) el.textContent = `Deposit total: ${formatCurrency((cents + otherCents) / 100)}`
            + (count ? ` (${count} payment${count === 1 ? '' : 's'})` : '');
    },

    async makeDeposit() {
        const lineIds = [];
        let cents = 0;
        $$('.dep-check').forEach(cb => {
            if (cb.checked) {
                lineIds.push(parseInt(cb.dataset.lineid));
                cents += Math.round((parseFloat(cb.dataset.amount) || 0) * 100);
            }
        });
        const total = cents / 100;
        const others = DepositsPage._otherLines();
        if (others.some(l => !l.account_id || !l.amount)) { toast('Each other deposit line needs an account and an amount', 'error'); return; }

        if (lineIds.length === 0 && others.length === 0) { toast('Select payments to deposit, or add a line', 'error'); return; }

        const bankAcctId = $('#deposit-bank-acct')?.value;
        if (!bankAcctId) { toast('Select a bank account', 'error'); return; }
        if ($('#deposit-class') && !ClassWarn.okValue($('#deposit-class').value)) return;

        try {
            const result = await API.post('/deposits', {
                deposit_to_account_id: parseInt(bankAcctId),
                date: $('#deposit-date').value,
                total: lineIds.length ? total : null,
                reference: $('#deposit-ref')?.value || null,
                class_id: $('#deposit-class')?.value ? parseInt($('#deposit-class').value) : null,
                line_ids: lineIds,
                other_lines: others,
            });
            toast(`Deposited ${formatCurrency(result.amount)}`);
            App.navigate('#/deposits');
        } catch (err) { toast(err.message, 'error'); }
    },

    async voidDeposit(id) {
        if (!confirm('Void this deposit? A reversing entry is posted, and its payments go back on the list to deposit again.')) return;
        try {
            await API.post(`/deposits/${id}/void`);
            toast('Deposit voided; its payments are back on the list');
            closeModal();
            // off a deposit's own address (#/deposits/12), back to the list
            if (location.hash === '#/deposits') App.navigate('#/deposits');
            else location.hash = '#/deposits';
        } catch (err) { toast(err.message, 'error'); }
    },
};
