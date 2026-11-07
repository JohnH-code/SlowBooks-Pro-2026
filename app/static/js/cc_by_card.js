/**
 * Credit Card Charges one card at a time (John's build).
 *
 * As QuickBooks keeps each card on its own: a tab for each credit card
 * account, with what is owed on it, and the charges and refunds on that
 * card only ("All cards" lists them together, as before). + Enter Charge
 * opens on the card shown. The card picked is remembered for the visit.
 */
(function () {
    if (typeof CCChargesPage === 'undefined') return;

    CCChargesPage._card = null;  // the card shown; 'all' for every card

    CCChargesPage.render = async function () {
        const [charges, accounts] = await Promise.all([
            API.get('/cc-charges'),
            API.get('/accounts').catch(() => []),
        ]);
        const used = new Set(charges.map(c => c.card_account_id));
        // the cards with charges or something owed; a card never used (an
        // unused placeholder in the chart) gets a tab once it has a charge
        const cards = accounts.filter(a => a.bank_kind === 'credit_card' && (used.has(a.id) || (a.is_active !== false && Number(a.balance || 0) !== 0)))
            .sort((a, b) => (used.has(b.id) - used.has(a.id)) || String(a.name).localeCompare(String(b.name)));
        if (CCChargesPage._card !== 'all' && !cards.some(a => a.id === CCChargesPage._card)) {
            CCChargesPage._card = (cards.find(a => used.has(a.id)) || cards[0] || {}).id || 'all';
        }
        const sel = CCChargesPage._card;
        const card = cards.find(a => a.id === sel);
        const shown = sel === 'all' ? charges : charges.filter(c => c.card_account_id === sel);
        const tab = (id, label, extra = '') => `<button type="button" class="qb-tab${id === sel ? ' qb-tab--on' : ''}" role="tab" aria-selected="${id === sel}" onclick="CCChargesPage.pickCard(${id === 'all' ? "'all'" : id})">${escapeHtml(label)}${extra}</button>`;
        const owed = a => {
            const n = Number(a.balance || 0);
            return ` <span class="cc-owed">${formatCurrency(Math.abs(n))}</span>`;
        };

        let html = `
            <div class="page-header">
                <h2>Credit Card Charges${card ? ` — ${escapeHtml(card.name)}` : ''}</h2>
                <button class="btn btn-primary" onclick="ExpensesPage.showForm(${card ? `{ card: true, paid_from_account_id: ${card.id} }` : '{ card: true }'})" title="On the expense form: split across accounts, GST/HST, memorize">+ Enter Charge</button>
            </div>
            <div class="qb-tabs cc-card-tabs" role="tablist" aria-label="Credit cards">
                ${cards.map(a => tab(a.id, a.name, owed(a))).join('')}
                ${cards.length > 1 ? tab('all', 'All cards') : ''}
            </div>`;
        if (card) {
            html += `<p class="cc-card-note">${escapeHtml(card.name)}: ${formatCurrency(Math.abs(Number(card.balance || 0)))} owed.
                <a href="#/banking/${card.id}">Open its register</a></p>`;
        }
        if (shown.length === 0) {
            html += `<div class="empty-state"><p>No charges on ${card ? escapeHtml(card.name) : 'any card'} yet</p></div>`;
            return html;
        }
        html += `<div class="table-container"><table>
            <thead><tr><th scope="col">Date</th><th scope="col">Payee</th><th scope="col">Account</th>${sel === 'all' ? '<th scope="col">Card</th>' : ''}<th scope="col">Reference</th>
            <th scope="col" class="amount">Amount</th><th scope="col"></th></tr></thead><tbody>`;
        for (const c of shown) {
            const voided = c.status === 'void';
            html += `<tr style="${voided ? 'color:var(--gray-400); text-decoration:line-through;' : ''}">
                <td>${formatDate(c.date)}</td>
                <td>${escapeHtml(c.description || '')}</td>
                <td>${escapeHtml(c.account_name || '')}</td>
                ${sel === 'all' ? `<td>${escapeHtml(c.card_account_name || '')}</td>` : ''}
                <td>${escapeHtml(c.reference || '')}</td>
                <td class="amount">${formatCurrency(c.amount)}</td>
                <td>${c.kind === 'expense'
                    ? `<button class="btn btn-sm btn-secondary" onclick="ExpensesPage.showDetail(${c.id})">View</button>${voided ? '' : ` <button data-destructive class="btn btn-sm btn-secondary" onclick="ExpensesPage.void(${c.id})">Void</button>`}`
                    : (voided ? '' : `<button data-destructive class="btn btn-sm btn-secondary" onclick="CCChargesPage.voidCharge(${c.id})">Void</button>`)}</td>
            </tr>`;
        }
        html += '</tbody></table></div>';
        return html;
    };

    CCChargesPage.pickCard = function (id) {
        CCChargesPage._card = id;
        App.refresh();
    };
})();
