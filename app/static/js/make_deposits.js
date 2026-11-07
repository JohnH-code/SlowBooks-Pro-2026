/**
 * Make Deposits as QuickBooks Desktop 2020 lays it out (John's build).
 *
 * Deposit To, Date and Memo across the top; the payments waiting in
 * Undeposited Funds ticked in Payments to Deposit; one grid below for the
 * payments picked and any other amounts (Received From, From Account, Memo,
 * Chq No., Pmt Meth., Tax, Amount); then Deposit Subtotal, the GST/HST
 * collected on lines coded H, cash back, and the Deposit Total; Save &
 * Close, Save & New and Clear. A saved deposit opens in the same screen to
 * be changed (the register's Edit, the list's Edit) and is saved in place.
 *
 * The same calls as the page it replaces: POST /api/deposits for a new one
 * (line_ids + other_lines), PUT /api/deposits/{id} with other_lines for a
 * change. An other line's Amount is the net; an H line's GST/HST is shown
 * under the grid and sent with it (tax_amount), so what is saved is what
 * was on screen. Cash back is sent as a negative other line.
 *
 * Each form keeps its own state (form._qbd), so the page's new deposit and
 * an edit dialog opened over it don't mix. The page's form keeps the old
 * page's field ids (deposit-bank-acct, deposit-date, deposit-ref,
 * deposit-class) and its picker boxes the class dep-check.
 */
(function () {
    if (typeof DepositsPage === 'undefined') return;

    const r2 = x => Math.round((Number(x) || 0) * 100) / 100;
    const ctx = el => {
        const form = el && el.closest ? el.closest('form.qb-deposit') : null;
        return form ? form._qbd : null;
    };
    const q = (c, sel) => c.form.querySelector(sel);
    const qa = (c, sel) => Array.from(c.form.querySelectorAll(sel));

    async function load(editId) {
        const [pending, accounts, classes, settings, deposit] = await Promise.all([
            API.get('/deposits/pending'),
            API.get('/accounts'),
            API.get('/classes').catch(() => []),
            API.get('/settings').catch(() => ({})),
            editId ? API.get(`/deposits/${editId}`) : Promise.resolve(null),
        ]);
        const c = {
            accounts, classes, deposit,
            canada: settings.sales_tax_system === 'canada' && !!settings.hst_account_id,
            rate: (parseFloat(settings.hst_rate || '13') || 0) / 100,
            rateText: settings.hst_rate || '13',
            hstAccount: parseInt(settings.hst_account_id, 10) || null,
            id: deposit ? 'deposit-edit' : 'deposit',
        };
        // a deposit being changed lists the payments it holds, then those
        // still waiting
        const held = deposit ? (deposit.payments || []) : [];
        const heldIds = new Set(held.map(p => p.transaction_line_id));
        c.payments = held.concat(pending.filter(p => !heldIds.has(p.transaction_line_id)));
        c.picked = new Set(heldIds);
        return c;
    }

    function acctOptions(c, selected, skip) {
        return c.accounts
            .filter(a => (a.is_active !== false || a.id === selected) && a.id !== skip && a.account_number !== '1200')
            .map(a => `<option value="${a.id}"${a.id === selected ? ' selected' : ''}>${accountLabel(a)}</option>`).join('');
    }

    const refOf = p => (DepositsPage._ref ? DepositsPage._ref(p) : (p.check_number || p.reference || ''));

    // ── the form ──────────────────────────────────────────────────────────
    function formHtml(c) {
        const d = c.deposit;
        const id = c.id;
        const banks = c.accounts.filter(a => a.bank_kind === 'bank' && (a.is_active !== false || (d && a.id === d.account_id)));
        // a new deposit goes where the last one went, as QuickBooks remembers
        c.bankId = d ? d.account_id
            : ((banks.find(a => a.id === c.lastBank) || banks.find(a => a.account_number === '1000') || banks[0] || {}).id);
        // the Class picker starts blank with Settings' "Warn when a
        // transaction is saved without a class" on, as the old page did
        const blank = !d && c.classes.length && typeof ClassWarn !== 'undefined' && ClassWarn.enabled();
        const classOpts = c.classes.length
            ? `<label for="${id}-class">${T('Class')}</label><select id="${id}-class" name="class_id">${blank
                ? `<option value="" selected>— choose a ${T('class').toLowerCase()} —</option>` : '<option value=""></option>'}${c.classes.map(k =>
                `<option value="${k.id}"${(d ? d.class_id === k.id : (k.is_system_default && !blank)) ? ' selected' : ''}>${escapeHtml(k.name)}</option>`).join('')}</select>` : '';
        const waiting = c.payments.filter(p => !c.picked.has(p.transaction_line_id)).length;
        return `
        <form class="qb-deposit" data-mode="${d ? 'edit' : 'new'}" onsubmit="event.preventDefault(); DepositsPage.qbSave(this, 'close')">
            <div class="qb-toolbar">
                <button type="button" class="btn btn-sm btn-secondary" onclick="DepositsPage.qbTogglePayments(this)">Payments… <span class="qbd-badge"${waiting ? '' : ' style="display:none"'}>${waiting}</span></button>
                ${d ? `<button type="button" class="btn btn-sm btn-secondary" onclick="window.open('/api/deposits/${d.id}/print-preview','_blank')">Print</button>` : ''}
            </div>
            <div class="qbd-top">
                <label for="${id}-bank-acct">Deposit To</label>
                <select id="${id}-bank-acct" name="bank" onchange="DepositsPage.qbBankChanged(this)" ${d ? 'disabled title="A saved deposit stays on its bank account; void it and deposit again to move it"' : ''}>${banks.length ? banks.map(a =>
                    `<option value="${a.id}"${a.id === c.bankId ? ' selected' : ''}>${escapeHtml(a.name)}</option>`).join('') : '<option value="">No bank accounts</option>'}</select>
                <label for="${id}-date">Date</label>
                <input id="${id}-date" name="date" type="date" required value="${escapeHtml(d ? d.date : todayISO())}" ${d && d.reconciled ? 'disabled' : ''}>
                <label for="${id}-ref">Memo</label>
                <input id="${id}-ref" name="memo" value="${escapeHtml(d ? (d.reference || '') : 'Deposit')}" maxlength="120">
                ${classOpts}
            </div>
            <div class="qbd-hint">Click Payments to select customer payments that you have received. List any other amounts to deposit below.</div>
            <div class="qbd-payments" style="display:none;"></div>
            <div class="table-container table-container--scroll"><table class="line-items-table qbd-grid">
                <thead><tr>
                    <th scope="col">Received From</th><th scope="col">From Account</th><th scope="col">Memo</th>
                    <th scope="col">Chq No.</th><th scope="col">Pmt Meth.</th>
                    ${c.canada ? `<th scope="col" title="H: GST/HST at ${escapeHtml(c.rateText)}% is collected on the amount · E: exempt">Tax</th>` : ''}
                    <th scope="col" class="col-amount">Amount</th><th scope="col"><span class="sr-only">Remove</span></th>
                </tr></thead>
                <tbody class="qbd-lines"></tbody>
            </table></div>
            <button type="button" class="btn btn-sm btn-secondary qbd-add" onclick="DepositsPage.qbAddLine(this)">+ Add Line</button>
            <div class="qbd-sub"><span>Deposit Subtotal</span><strong class="qbd-subtotal">$0.00</strong></div>
            ${c.canada ? `<div class="qbd-sub"><span>GST/HST (${escapeHtml(c.rateText)}%)</span><strong class="qbd-tax-total">$0.00</strong></div>` : ''}
            <div class="qbd-cashback">
                <div class="qbd-hint">To get cash back from this deposit, enter the amount below. Indicate the account where you want this money to go, such as your Petty Cash account.</div>
                <div class="qbd-cashback-row">
                    <div><label for="${id}-cb-acct">Cash back goes to</label>
                        <select id="${id}-cb-acct" class="qbd-cb-acct"><option value=""></option>${acctOptions(c, null, c.bankId)}</select></div>
                    <div><label for="${id}-cb-memo">Cash back memo</label><input id="${id}-cb-memo" class="qbd-cb-memo" maxlength="120"></div>
                    <div><label for="${id}-cb-amt">Cash back amount</label><input id="${id}-cb-amt" class="qbd-cb-amt money" type="number" step="0.01" min="0" oninput="DepositsPage.qbRecalc(this)"></div>
                </div>
            </div>
            <div class="qbd-sub qbd-total"><span>Deposit Total</span><strong class="qbd-total-amt">$0.00</strong></div>
            ${d && d.reconciled ? `<div class="qbd-hint" role="status">This deposit was reconciled with a bank statement, so its amount and date stay as they are; its memo and accounts can still be corrected.</div>` : ''}
            <div class="form-actions qb-actions">
                <button type="button" class="btn btn-secondary" onclick="DepositsPage.qbSave(this, 'close')">Save &amp; Close</button>
                <button type="button" class="btn btn-primary" onclick="DepositsPage.qbSave(this, 'new')">Save &amp; New</button>
                <button type="button" class="btn btn-secondary" onclick="DepositsPage.qbClear(this)">${d ? 'Revert' : 'Clear'}</button>
                ${d ? '<button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>'
                    : '<button type="button" class="btn btn-secondary" onclick="DepositsPage.qbClose(this)">Close</button>'}
            </div>
        </form>`;
    }

    function paymentsPanel(c) {
        const rows = c.payments.map(p => `<tr>
                <td><input type="checkbox" class="dep-check qbd-pick" data-lineid="${p.transaction_line_id}" data-amount="${p.amount}"${c.picked.has(p.transaction_line_id) ? ' checked' : ''} aria-label="Deposit ${escapeHtml(p.description || '')}" onchange="DepositsPage.qbPick(this)"></td>
                <td>${formatDate(p.date)}</td>
                <td>${escapeHtml(p.received_from || '')}</td>
                <td>${escapeHtml(p.description || '')}</td>
                <td>${escapeHtml(refOf(p))}</td>
                <td>${escapeHtml(p.method || '')}</td>
                <td class="amount">${formatCurrency(p.amount)}</td>
            </tr>`).join('');
        return `<div class="qbd-payments-head">Payments to Deposit</div>
            ${rows ? `<div class="table-container"><table class="line-items-table">
                <thead><tr><th scope="col"><input type="checkbox" aria-label="Select all payments" onchange="DepositsPage.qbPickAll(this)"></th>
                <th scope="col">Date</th><th scope="col">Name</th><th scope="col">Description</th><th scope="col">Chq / Ref</th><th scope="col">Pmt Meth.</th><th scope="col" class="amount">Amount</th></tr></thead>
                <tbody>${rows}</tbody></table></div>` : '<div class="qbd-hint">No payments are waiting in Undeposited Funds.</div>'}
            <div class="qbd-payments-ok">
                <button type="button" class="btn btn-sm btn-primary" onclick="DepositsPage.qbTogglePayments(this, false)">OK</button>
            </div>`;
    }

    function paymentRow(c, p) {
        return `<tr class="qbd-payment" data-lineid="${p.transaction_line_id}" data-amount="${p.amount}">
            <td>${escapeHtml(p.received_from || '')}</td>
            <td>Undeposited Funds</td>
            <td>${escapeHtml(p.description || '')}</td>
            <td>${escapeHtml(refOf(p))}</td>
            <td>${escapeHtml(p.method || '')}</td>
            ${c.canada ? '<td></td>' : ''}
            <td class="amount">${formatCurrency(p.amount)}</td>
            <td><button type="button" class="btn btn-sm btn-secondary" aria-label="Take this payment off the deposit" title="Take this payment off the deposit" onclick="DepositsPage.qbUnpick(this, ${p.transaction_line_id})">&times;</button></td>
        </tr>`;
    }

    function otherRow(c, l = {}) {
        const exempt = l.tax_code !== 'H';
        return `<tr class="qbd-other" data-tax="${escapeHtml(String(l.tax_amount || 0))}">
            <td><input class="qbd-from" value="${escapeHtml(l.received_from || '')}" maxlength="120" aria-label="Received from"></td>
            <td><select class="qbd-acct" aria-label="From account"><option value="">Choose...</option>${acctOptions(c, l.account_id || null, c.bankId)}</select></td>
            <td><input class="qbd-memo" value="${escapeHtml(l.memo || '')}" maxlength="160" aria-label="Memo"></td>
            <td><input class="qbd-chq" value="${escapeHtml(l.check_number || '')}" maxlength="20" aria-label="Cheque number"></td>
            <td></td>
            ${c.canada ? `<td><select class="qbd-tax" aria-label="GST/HST" title="H: GST/HST applies · E: exempt" onchange="DepositsPage.qbLineChanged(this)"><option value="H"${exempt ? '' : ' selected'}>H</option><option value="E"${exempt ? ' selected' : ''}>E</option></select></td>` : ''}
            <td class="col-amount"><input class="qbd-amt money" type="number" step="0.01" value="${l.amount ? r2(l.amount).toFixed(2) : ''}" oninput="DepositsPage.qbLineChanged(this)" aria-label="Amount"></td>
            <td><button type="button" class="btn btn-sm btn-secondary" aria-label="Remove line" onclick="DepositsPage.qbRemoveLine(this)">&times;</button></td>
        </tr>`;
    }

    function drawPayments(c) {
        const body = q(c, '.qbd-lines');
        body.querySelectorAll('tr.qbd-payment').forEach(tr => tr.remove());
        const first = body.querySelector('tr.qbd-other');
        const html = c.payments.filter(p => c.picked.has(p.transaction_line_id)).map(p => paymentRow(c, p)).join('');
        if (first) first.insertAdjacentHTML('beforebegin', html); else body.insertAdjacentHTML('beforeend', html);
        const waiting = c.payments.filter(p => !c.picked.has(p.transaction_line_id)).length;
        const badge = q(c, '.qbd-badge');
        if (badge) { badge.textContent = waiting; badge.style.display = waiting ? '' : 'none'; }
        recalc(c);
    }

    function addLine(c, l) {
        q(c, '.qbd-lines').insertAdjacentHTML('beforeend', otherRow(c, l || {}));
    }

    const taxed = (c, tr) => c.canada && tr.querySelector('.qbd-tax') && tr.querySelector('.qbd-tax').value === 'H';
    const netOf = tr => parseFloat(tr.querySelector('.qbd-amt').value) || 0;
    const taxOf = (c, tr) => (taxed(c, tr) ? (parseFloat(tr.dataset.tax || '0') || 0) : 0);

    function recalc(c) {
        const payments = qa(c, '.qbd-lines tr.qbd-payment').reduce((t, tr) => t + (parseFloat(tr.dataset.amount) || 0), 0);
        const others = qa(c, '.qbd-lines tr.qbd-other');
        const net = others.reduce((t, tr) => t + netOf(tr), 0);
        const tax = others.reduce((t, tr) => t + taxOf(c, tr), 0);
        const cash = parseFloat(q(c, '.qbd-cb-amt').value) || 0;
        const set = (sel, v) => { const el = q(c, sel); if (el) el.textContent = formatCurrency(v); };
        set('.qbd-subtotal', r2(payments + net));
        set('.qbd-tax-total', r2(tax));
        set('.qbd-total-amt', r2(payments + net + tax - cash));
    }

    // ── handlers (each finds its own form) ───────────────────────────────
    DepositsPage.qbTogglePayments = function (el, show) {
        const c = ctx(el);
        if (!c) return;
        const panel = q(c, '.qbd-payments');
        const open = show === undefined ? panel.style.display === 'none' : show;
        panel.innerHTML = open ? paymentsPanel(c) : '';
        panel.style.display = open ? '' : 'none';
    };

    DepositsPage.qbPick = function (box) {
        const c = ctx(box);
        const id = parseInt(box.dataset.lineid, 10);
        if (box.checked) c.picked.add(id); else c.picked.delete(id);
        drawPayments(c);
    };

    DepositsPage.qbPickAll = function (box) {
        const c = ctx(box);
        qa(c, '.qbd-pick').forEach(b => {
            b.checked = box.checked;
            const id = parseInt(b.dataset.lineid, 10);
            if (box.checked) c.picked.add(id); else c.picked.delete(id);
        });
        drawPayments(c);
    };

    DepositsPage.qbUnpick = function (el, lineId) {
        const c = ctx(el);
        c.picked.delete(lineId);
        const box = q(c, `.qbd-pick[data-lineid="${lineId}"]`);
        if (box) box.checked = false;
        drawPayments(c);
    };

    DepositsPage.qbAddLine = function (el) {
        const c = ctx(el);
        addLine(c);
        recalc(c);
    };

    DepositsPage.qbRemoveLine = function (el) {
        const c = ctx(el);
        el.closest('tr').remove();
        recalc(c);
    };

    DepositsPage.qbLineChanged = function (el) {
        const c = ctx(el);
        const tr = el.closest('tr');
        tr.dataset.tax = taxed(c, tr) ? r2(netOf(tr) * c.rate).toFixed(2) : '0';
        recalc(c);
    };

    DepositsPage.qbRecalc = function (el) { const c = ctx(el); if (c) recalc(c); };

    // another bank: its own account comes off the From Account lists
    DepositsPage.qbBankChanged = function (el) {
        const c = ctx(el);
        c.bankId = parseInt(el.value, 10) || null;
        qa(c, 'select.qbd-acct, select.qbd-cb-acct').forEach(s => {
            const keep = parseInt(s.value, 10) || null;
            s.innerHTML = `<option value="">${s.classList.contains('qbd-acct') ? 'Choose...' : ''}</option>${acctOptions(c, keep === c.bankId ? null : keep, c.bankId)}`;
        });
    };

    function otherLinesPayload(c) {
        const out = [];
        let bad = null;
        qa(c, '.qbd-lines tr.qbd-other').forEach((tr, i) => {
            const account = parseInt(tr.querySelector('.qbd-acct').value, 10) || null;
            const amount = r2(netOf(tr));
            const from = tr.querySelector('.qbd-from').value.trim();
            const memo = tr.querySelector('.qbd-memo').value.trim();
            const chq = tr.querySelector('.qbd-chq').value.trim();
            if (!account && !amount && !from && !memo && !chq) return;  // a blank line
            if (!account || !amount) { bad = bad || `Line ${i + 1} needs a From Account and an amount`; return; }
            out.push({
                account_id: account, amount,
                received_from: from || null, memo: memo || null, check_number: chq || null,
                ...(taxed(c, tr) ? { tax_code: 'H', tax_amount: r2(taxOf(c, tr)) } : {}),
            });
        });
        const cash = r2(parseFloat(q(c, '.qbd-cb-amt').value) || 0);
        if (cash) {
            const acct = parseInt(q(c, '.qbd-cb-acct').value, 10) || null;
            if (!acct) bad = bad || 'Choose the account the cash back goes to';
            out.push({ account_id: acct, amount: -cash, memo: q(c, '.qbd-cb-memo').value.trim() || 'Cash back' });
        }
        return { lines: out, error: bad };
    }

    DepositsPage.qbSave = async function (el, mode) {
        const c = ctx(el);
        if (!c) return;
        const form = c.form;
        const { lines, error } = otherLinesPayload(c);
        if (error) { toast(error, 'error'); return; }
        const payRows = qa(c, '.qbd-lines tr.qbd-payment');
        const lineIds = payRows.map(tr => parseInt(tr.dataset.lineid, 10));
        if (!lineIds.length && !lines.some(l => l.amount > 0)) { toast('Select payments to deposit, or list an amount', 'error'); return; }
        const classSel = form.class_id;
        const classId = classSel && classSel.value ? parseInt(classSel.value, 10) : null;
        const d = c.deposit;
        const dateField = form.date;
        if (!(await TxnWarn.ok(null, { date: dateField.disabled ? '' : dateField.value, editing: !!d }))) return;
        if (classSel && !d && typeof ClassWarn !== 'undefined' && !ClassWarn.okValue(classSel.value)) return;
        try {
            if (d) {
                const body = { reference: form.memo.value || null, line_ids: lineIds, other_lines: lines };
                if (!dateField.disabled) body.date = dateField.value;
                if (classSel) body.class_id = classId;
                const saved = await API.put(`/deposits/${d.id}`, body);
                toastPosted(saved && saved.note ? `Deposit saved. ${saved.note}` : 'Deposit saved');
                closeModal();
                if (mode === 'new') { App.navigate('#/deposits'); return; }
                App.navigate(location.hash.startsWith('#/banking') ? location.hash : '#/deposits');
            } else {
                if (!form.bank.value) { toast('Select a bank account', 'error'); return; }
                const ticked = r2(payRows.reduce((t, tr) => t + (parseFloat(tr.dataset.amount) || 0), 0));
                const result = await API.post('/deposits', {
                    deposit_to_account_id: parseInt(form.bank.value, 10),
                    date: dateField.value,
                    total: lineIds.length ? ticked : null,
                    reference: form.memo.value || null,
                    class_id: classId,
                    line_ids: lineIds,
                    other_lines: lines,
                });
                toastPosted(`Deposited ${formatCurrency(result.amount)}`);
                if (mode === 'close') leave(); else App.navigate('#/deposits');
            }
        } catch (err) { toast(err.message, 'error'); }
    };

    // Save & Close and Close leave the screen, as QuickBooks closes its
    // window: back to the page it was opened from, or Home
    function leave() {
        App.navigate(DepositsPage._cameFrom || '#/');
    }

    function started(c) {
        return c.picked.size > 0 || qa(c, '.qbd-lines tr.qbd-other').some(tr =>
            netOf(tr) || tr.querySelector('.qbd-acct').value || tr.querySelector('.qbd-from').value.trim())
            || !!(parseFloat(q(c, '.qbd-cb-amt').value) || 0);
    }

    DepositsPage.qbClose = function (el) {
        const c = ctx(el);
        if (c && started(c) && !confirm('Close Make Deposits without saving this deposit?')) return;
        leave();
    };

    DepositsPage.qbClear = function (el) {
        const c = ctx(el);
        if (c && c.deposit) { DepositsPage.editDeposit(c.deposit.id); return; }
        App.navigate('#/deposits');
    };

    // A saved deposit's other lines back on the form: its GST/HST lines
    // folded into the lines they were collected on, a negative line as the
    // cash back.
    function fillFrom(c) {
        const other = (c.deposit.other_lines || []).slice();
        const taxLines = other.filter(l => c.canada && l.account_id === c.hstAccount && Number(l.amount) > 0 && /^GST\/HST — /.test(l.description || ''));
        const rest = other.filter(l => !taxLines.includes(l));
        const parse = text => {
            const parts = String(text || '').split(' — ');
            let chq = '';
            if (parts.length > 1 && /^Chq /.test(parts[parts.length - 1])) chq = parts.pop().slice(4);
            if (parts.length >= 2) return { received_from: parts[0], memo: parts.slice(1).join(' — '), check_number: chq };
            return { received_from: '', memo: parts[0] || '', check_number: chq };
        };
        let cashBack = null;
        for (const l of rest) {
            if (Number(l.amount) < 0 && !cashBack) { cashBack = l; continue; }
            const tax = taxLines.find(t => t.description === `GST/HST — ${l.description || ''}`);
            if (tax) taxLines.splice(taxLines.indexOf(tax), 1);
            addLine(c, { ...parse(l.description), account_id: l.account_id, amount: Number(l.amount), tax_code: tax ? 'H' : 'E', tax_amount: tax ? Number(tax.amount) : 0 });
        }
        // a GST/HST line not matched to one stays a line of its own
        for (const t of taxLines) addLine(c, { ...parse(t.description), account_id: t.account_id, amount: Number(t.amount), tax_code: 'E' });
        if (cashBack) {
            q(c, '.qbd-cb-acct').value = String(cashBack.account_id);
            const w = parse(cashBack.description);
            q(c, '.qbd-cb-memo').value = [w.received_from, w.memo].filter(Boolean).join(' — ');
            q(c, '.qbd-cb-amt').value = r2(-Number(cashBack.amount)).toFixed(2);
        }
    }

    function attach(root, c) {
        c.form = root.querySelector('form.qb-deposit');
        c.form._qbd = c;
    }

    // ── the page and the edit ─────────────────────────────────────────────
    const baseRecent = DepositsPage._recentHtml;
    DepositsPage.render = async function () {
        // the page Make Deposits was opened from (not itself, after a
        // Save & New), for Save & Close and Close to go back to
        const from = history.state && history.state.from;
        if (from && !String(from).startsWith('#/deposits')) DepositsPage._cameFrom = from;
        else if (!from) DepositsPage._cameFrom = null;
        const c = await load(null);
        const recent = await API.get('/deposits?limit=20').catch(() => []);
        c.lastBank = (recent.find(r => !r.voided) || {}).account_id;
        DepositsPage._accounts = c.accounts;
        // drawn once the page is in place
        setTimeout(() => {
            const root = document.getElementById('qbd-page');
            if (!root) return;
            attach(root, c);
            addLine(c);
            drawPayments(c);
            if (c.payments.length) DepositsPage.qbTogglePayments(c.form, true);
        }, 0);
        return `<div class="page-header"><h2>Make Deposits</h2></div>
            <div class="qbd-window" id="qbd-page" data-write>${formHtml(c)}</div>
            ${baseRecent.call(DepositsPage, recent)}`;
    };

    DepositsPage.editDeposit = async function (id) {
        let c;
        try { c = await load(id); } catch (err) { toast(err.message, 'error'); return; }
        if (c.deposit.voided) { toast('A void deposit is not edited.', 'error'); return; }
        openModal(`Make Deposits — ${formatDate(c.deposit.date)}`, `<div class="qbd-window">${formHtml(c)}</div>`, { wide: true });
        attach($('#modal-body'), c);
        fillFrom(c);
        if (!q(c, '.qbd-lines tr.qbd-other')) addLine(c);
        drawPayments(c);
    };
})();
