/**
 * Edit beside Void, everywhere (John's build).
 *
 * 2.31.5 (#689) made every kind of transaction changeable: an invoice, a
 * bill, a deposit, a journal entry and a register entry in place, and an
 * expense, a card charge, a transfer, a credit memo, a vendor credit, a
 * customer payment and a bill payment by Void and Replace. Its Edit button
 * is on the report drill-downs and the General Ledger only. Here the same
 * Edit sits beside each of those kinds' Void button — on their lists, their
 * views and the bank register — as QuickBooks opens any transaction from
 * where it is listed. A cheque or card charge entered as an expense opens
 * Write Cheques and saves in place (write_cheques.js).
 *
 * The buttons are added to what the pages draw (a MutationObserver), so no
 * page's own file changes: an update that redraws a page keeps them as
 * long as its Void buttons keep their names.
 */
const EditEverywhere = {
    // a Void button's onclick → the kind its Edit opens, and the id in it
    VOIDS: [
        [/^ExpensesPage\.void\((\d+)\)/, 'expense'],
        [/^CCChargesPage\.voidCharge\((\d+)\)/, 'cc_charge'],
        [/^CreditMemosPage\.void\((\d+)\)/, 'credit_memo'],
        [/^VendorCreditsPage\.void\((\d+)\)/, 'vendor_credit'],
        [/^PaymentsPage\.void\((\d+)/, 'payment'],
        [/^BillsPage\.voidBillPayment\((\d+)/, 'bill_payment'],
        [/^BankingPage\.voidTransfer\((\d+)\)/, 'transfer'],
        [/^DepositsPage\.voidDeposit\((\d+)\)/, 'deposit'],
    ],

    open(kind, id) {
        if (kind === 'expense' && typeof ExpensesPage.edit === 'function') return ExpensesPage.edit(id);
        if (typeof TxnEdit !== 'undefined') return TxnEdit.open(kind, id);
        toast('This transaction cannot be edited here; void it and enter it again', 'error');
    },

    buttonHtml(kind, id, cls) {
        const word = (typeof TxnEdit !== 'undefined' && TxnEdit.WORDS[kind]) || 'transaction';
        const replace = kind !== 'expense' && kind !== 'deposit';
        const title = replace
            ? `Edit this ${word}: saving voids it and posts the corrected one in its place`
            : `Edit this ${word}`;
        return `<button type="button" class="${cls}" data-write data-edit-everywhere="1" title="${escapeHtml(title)}" onclick="EditEverywhere.open('${kind}', ${Number(id)})">Edit</button> `;
    },

    scan(root) {
        root.querySelectorAll('button[onclick]:not([data-edit-checked])').forEach(b => {
            b.dataset.editChecked = '1';
            const onclick = b.getAttribute('onclick') || '';
            for (const [re, kind] of EditEverywhere.VOIDS) {
                const m = onclick.match(re);
                if (!m) continue;
                // an Edit already beside it (the cheque list's own, a report's)
                const near = Array.from(b.parentElement ? b.parentElement.querySelectorAll('button') : [])
                    .some(x => x !== b && /^\s*Edit\s*$/.test(x.textContent || ''));
                if (near) return;
                const cls = (b.className || 'btn btn-sm btn-secondary')
                    .replace(/\bbtn-danger\b/, 'btn-secondary');
                b.insertAdjacentHTML('beforebegin', EditEverywhere.buttonHtml(kind, m[1], cls));
                return;
            }
        });
    },

    start() {
        let queued = false;
        const run = () => { queued = false; EditEverywhere.scan(document); };
        new MutationObserver(() => {
            if (!queued) { queued = true; requestAnimationFrame(run); }
        }).observe(document.body, { childList: true, subtree: true });
        run();
    },
};

// The bank register: a payment, bill payment, transfer, card charge or
// cheque there opens its Edit too, beside the register's own.
if (typeof BankingPage !== 'undefined' && typeof BankingPage._editButton === 'function') {
    const baseEditButton = BankingPage._editButton;
    const KINDS = {
        expense: ['expense', 'txn'], cc_charge: ['cc_charge', 'txn'], transfer: ['transfer', 'txn'],
        payment: ['payment', 'source'], bill_payment: ['bill_payment', 'source'],
        credit_memo: ['credit_memo', 'source'], vendor_credit: ['vendor_credit', 'source'],
    };
    BankingPage._editButton = function (e, accountId) {
        const own = baseEditButton.call(this, e, accountId);
        if (own || e.voided) return own;
        const hit = KINDS[e.source_type];
        const id = hit && (hit[1] === 'txn' ? e.transaction_id : e.source_id);
        if (!hit || !id) return '';
        return EditEverywhere.buttonHtml(hit[0], id, 'btn btn-sm btn-secondary');
    };
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => EditEverywhere.start());
else EditEverywhere.start();
