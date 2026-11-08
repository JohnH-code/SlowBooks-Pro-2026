/**
 * Make General Journal Entries as QuickBooks Desktop 2020 lays it out
 * (John's build).
 *
 * Date and Entry No. across the top; the grid Account | Debit | Credit |
 * Memo (then Job, Class and the like when the company has them); the
 * totals under it; Save & Close, Save & New and Clear (Revert on a saved
 * entry), and Reverse on a saved one.
 *
 * As QuickBooks does, moving to the next line fills in what still balances
 * the entry, on the other side, with the memo from the line above; there is
 * always a blank line at the bottom. The entry's description, which
 * QuickBooks doesn't have, is the first line's memo unless one is typed
 * (under More).
 *
 * Only the layout is new: the boxes keep the names and classes Journal
 * Entries' own save reads (date, reference, description, is_adjusting,
 * basis; je-account, je-desc, je-debit, je-credit), so the entry is saved
 * exactly as before.
 */
(function () {
    if (typeof JournalPage === 'undefined') return;

    const J = {};
    const num = x => parseFloat(x) || 0;
    const r2 = x => Math.round((Number(x) || 0) * 100) / 100;
    const form = () => document.querySelector('#modal-body form.qb-journal');
    const rows = () => Array.from(document.querySelectorAll('#je-lines tr'));
    const cell = (tr, cls) => { const el = tr.querySelector('.' + cls); return el ? el.closest('td') : null; };

    // A row in QuickBooks' order: Account, Debit, Credit, Memo, the rest.
    function arrange(tr) {
        if (tr.dataset.qbj) return;
        tr.dataset.qbj = '1';
        const acct = cell(tr, 'je-account');
        const desc = cell(tr, 'je-desc');
        const debit = cell(tr, 'je-debit');
        const credit = cell(tr, 'je-credit');
        const remove = tr.lastElementChild;
        if (!acct || !desc || !debit || !credit) return;
        const extras = Array.from(tr.children).filter(c => ![acct, desc, debit, credit, remove].includes(c));
        tr.replaceChildren(acct, debit, credit, desc, ...extras, remove);
        tr.querySelector('.je-desc').setAttribute('aria-label', 'Memo');
        tr.querySelector('.je-debit').setAttribute('aria-label', 'Debit');
        tr.querySelector('.je-credit').setAttribute('aria-label', 'Credit');
        tr.querySelectorAll('.je-debit, .je-credit').forEach(i => { if (!num(i.value)) i.value = ''; });
        const btn = remove.querySelector('button');
        if (btn) { btn.className = 'btn btn-sm btn-secondary'; btn.innerHTML = '&times;'; }
    }

    function arrangeHead() {
        const tr = document.querySelector('#modal-body form.qb-journal thead tr');
        if (!tr || tr.dataset.qbj) return;
        tr.dataset.qbj = '1';
        const ths = Array.from(tr.children);
        const [acct, desc] = ths;
        const debit = ths[ths.length - 3], credit = ths[ths.length - 2], remove = ths[ths.length - 1];
        const extras = ths.slice(2, ths.length - 3);
        desc.textContent = 'Memo';
        tr.replaceChildren(acct, debit, credit, desc, ...extras, remove);
    }

    const filled = tr => !!(tr.querySelector('.je-account')?.value || num(tr.querySelector('.je-debit')?.value) || num(tr.querySelector('.je-credit')?.value));

    // Always one blank line at the bottom.
    function keepBlank() {
        const all = rows();
        if (!all.length || filled(all[all.length - 1])) JournalPage.addLine();
    }

    // Entering a blank line: what still balances the entry, on the other
    // side, with the memo from the line above.
    function suggest(tr) {
        if (filled(tr)) return;
        let d = 0;
        rows().forEach(r => { if (r !== tr) d += num(r.querySelector('.je-debit')?.value) - num(r.querySelector('.je-credit')?.value); });
        d = r2(d);
        if (!d) return;
        tr.querySelector(d > 0 ? '.je-credit' : '.je-debit').value = Math.abs(d).toFixed(2);
        const prev = tr.previousElementSibling;
        const memo = tr.querySelector('.je-desc');
        if (prev && memo && !memo.value) memo.value = prev.querySelector('.je-desc')?.value || '';
        JournalPage.recalc();
    }

    // A debit typed clears the credit on the same line, and the other way.
    function oneSide(input) {
        const tr = input.closest('tr');
        if (!tr || !num(input.value)) return;
        const other = tr.querySelector(input.classList.contains('je-debit') ? '.je-credit' : '.je-debit');
        if (other) other.value = '';
    }

    const baseAddLine = JournalPage.addLine;
    JournalPage.addLine = function () {
        const r = baseAddLine.apply(JournalPage, arguments);
        if (form()) { const last = rows().pop(); if (last) arrange(last); }
        return r;
    };

    const baseRecalc = JournalPage.recalc;
    JournalPage.recalc = function () {
        const r = baseRecalc.apply(JournalPage, arguments);
        if (!form()) return r;
        let dr = 0, cr = 0;
        rows().forEach(tr => { dr += num(tr.querySelector('.je-debit')?.value); cr += num(tr.querySelector('.je-credit')?.value); });
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = formatCurrency(v); };
        set('qbj-debits', dr);
        set('qbj-credits', cr);
        return r;
    };

    function state() {
        const f = form();
        return f ? JSON.stringify(Array.from(f.elements)
            .filter(e => e.type !== 'button' && e.type !== 'submit' && !(e.classList && e.classList.contains('cbx-input')))
            .filter(e => !(e.closest('tr') && !filled(e.closest('tr'))))
            .map(e => (e.type === 'checkbox' ? e.checked : e.value))) : '';
    }

    const baseShowForm = JournalPage.showForm;
    JournalPage.showForm = async function (entry = null) {
        J.entry = entry || null;
        await baseShowForm.call(JournalPage, entry);
        const f = document.querySelector('#modal-body form');
        if (!f || !document.getElementById('je-lines')) return;
        f.classList.add('qb-journal');
        document.getElementById('modal')?.classList.add('modal--wide');
        const title = document.getElementById('modal-title');
        if (title) title.textContent = entry ? `Make General Journal Entries — #${entry.id} (editing)` : 'Make General Journal Entries';

        // the header: Date and Entry No.; the rest under More
        const grid = f.querySelector('.form-grid');
        const date = f.date, ref = f.reference, desc = f.description;
        ref.placeholder = 'optional';
        desc.required = false;
        desc.placeholder = "the first line's memo";
        const head = document.createElement('div');
        head.className = 'qbj-head';
        head.innerHTML = `<div class="qbj-field"><label for="qbj-date">Date</label></div>
            <div class="qbj-field"><label for="qbj-ref">Entry No.</label></div>`;
        date.id = 'qbj-date';
        ref.id = 'qbj-ref';
        head.children[0].appendChild(date);
        head.children[1].appendChild(ref);
        // the boxes' own labels went with their groups; drop the emptied ones
        grid.querySelectorAll('.form-group').forEach(g => { if (!g.querySelector('input, select, textarea')) g.remove(); });
        const descGroup = desc.closest('.form-group');
        if (descGroup) { const l = descGroup.querySelector('label'); if (l) l.textContent = 'Description'; }
        const more = document.createElement('details');
        more.className = 'qbj-more';
        more.innerHTML = '<summary>More: description, adjusting entry, basis, class</summary>';
        more.appendChild(grid);
        f.insertBefore(head, f.firstChild);
        head.after(more);
        if (entry && (entry.is_adjusting || (entry.basis && entry.basis !== 'both'))) more.open = true;
        const h3 = f.querySelector('h3');
        if (h3) h3.remove();

        // the grid
        arrangeHead();
        rows().forEach(arrange);
        keepBlank();
        const body = document.getElementById('je-lines');
        body.addEventListener('focusin', e => { const tr = e.target.closest('tr'); if (tr && !e.target.matches('button')) suggest(tr); });
        body.addEventListener('input', e => { if (e.target.matches('.je-debit, .je-credit')) oneSide(e.target); keepBlank(); });
        body.addEventListener('change', () => { keepBlank(); JournalPage.recalc(); });

        // totals and the buttons, as QuickBooks has them
        const old = f.querySelector('#je-totals')?.closest('div')?.parentElement;
        const status = document.createElement('div');
        status.className = 'qbj-totals';
        status.innerHTML = `<span>Totals</span><strong id="qbj-debits">$0.00</strong><strong id="qbj-credits">$0.00</strong>
            <span id="je-totals" hidden></span><span id="je-balance"></span>`;
        const actions = document.createElement('div');
        actions.className = 'form-actions qb-actions';
        actions.innerHTML = `${entry ? '<button type="button" class="btn btn-secondary" onclick="JournalPage.qbReverse()" title="A new entry with the debits and credits swapped, dated the first of next month">Reverse</button><span style="flex:1"></span>' : ''}
            <button type="button" class="btn btn-secondary" onclick="JournalPage.qbSave('close')">Save &amp; Close</button>
            <button type="submit" class="btn btn-primary" id="je-submit" onclick="event.preventDefault(); JournalPage.qbSave('new')">Save &amp; New</button>
            <button type="button" class="btn btn-secondary" onclick="JournalPage.qbClear()" title="${entry ? 'Put the entry back as it was saved' : 'Start this entry over'}">${entry ? 'Revert' : 'Clear'}</button>`;
        if (old) old.replaceWith(status); else f.appendChild(status);
        status.after(actions);
        JournalPage.recalc();
        J.snap = state();
        const first = rows()[0];
        if (!entry && first) first.querySelector('.je-account')?.focus();
    };

    JournalPage.qbClear = function () {
        return JournalPage.showForm(J.entry);
    };

    // Reverse: a new entry, the lines' sides swapped, dated the first of
    // the month after this one's, its memo saying what it reverses.
    JournalPage.qbReverse = async function () {
        const e = J.entry;
        if (!e) return;
        const d = new Date(`${e.date}T00:00:00`);
        const first = new Date(d.getFullYear(), d.getMonth() + 1, 1);
        const iso = `${first.getFullYear()}-${String(first.getMonth() + 1).padStart(2, '0')}-01`;
        const rev = {
            ...e, id: null, date: iso,
            reference: e.reference ? `${e.reference}R` : '',
            description: `Reverses journal entry #${e.id}${e.description ? ` (${e.description})` : ''}`,
            lines: (e.lines || []).map(l => ({ ...l, debit: l.credit, credit: l.debit })),
        };
        await JournalPage.showForm(null);
        const f = form();
        if (!f) return;
        f.date.value = rev.date;
        f.reference.value = rev.reference;
        f.description.value = rev.description;
        if (f.is_adjusting) f.is_adjusting.checked = !!e.is_adjusting;
        if (f.basis) f.basis.value = e.basis || 'both';
        document.getElementById('je-lines').innerHTML = '';
        JournalPage._lineCount = 0;
        rev.lines.forEach(l => { JournalPage.addLine(); const tr = rows().pop(); JournalPage.fillLine(tr, l); tr.querySelectorAll('.je-debit, .je-credit').forEach(i => { if (!num(i.value)) i.value = ''; }); });
        keepBlank();
        JournalPage.recalc();
    };

    // Save & Close also closes a blank or unchanged entry; Save & New opens
    // a fresh one once this one is saved. The description, if none was
    // typed, is the first line's memo.
    JournalPage.qbSave = async function (mode) {
        const f = form();
        if (!f) return;
        const blank = !rows().some(filled);
        if (mode === 'close' && (J.entry ? J.snap === state() : blank)) { closeModal(); return; }
        if (!f.description.value.trim()) {
            const memo = rows().map(tr => tr.querySelector('.je-desc')?.value.trim()).find(Boolean);
            f.description.value = memo || 'General journal entry';
        }
        if (!f.reportValidity()) return;
        await JournalPage.save({ preventDefault() {}, target: f });
        const saved = !!document.getElementById('modal-overlay')?.classList.contains('hidden');
        if (saved && mode === 'new') setTimeout(() => JournalPage.showForm(), 250);
    };
})();
