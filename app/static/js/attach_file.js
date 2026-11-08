/**
 * Attach File on the entry screens, as QuickBooks has it (John's build).
 *
 * Enter Bills, Write Cheques / Enter Credit Card Charges and Make Deposits
 * get an "Attach File" button: the files chosen are listed on the form and
 * attached to the transaction when it is saved, so a supplier's statement
 * goes on the bill in the same step that enters it. A saved transaction
 * opened to be changed lists the files it already has (each opens; × takes
 * one off). Nothing is uploaded until the save succeeds.
 *
 * One button for documents (8 Nov): where the form can read a document
 * (Enter Bills, Write Cheques — the scan), a PDF or picture waiting to be
 * attached has "Fill in from this document": the scan reads it into the
 * form, with its review boxes, and the file is attached on save as the
 * scan's own. The separate Scan Receipt button is hidden on those forms.
 *
 * The files go up the same way the View dialogs' Upload sends them
 * (POST /api/attachments/{type}/{id}); the types are the server's own:
 * bill, expense, deposit.
 */
const AttachFile = {
    pending: [],      // File objects waiting for the save
    _saved: [],       // the saved transaction's own files
    _entity: null,    // { type, id } of the saved one being changed

    // The button, its hidden picker and the list; `type`/`id` name a saved
    // transaction whose files are listed too.
    _n: 0,
    html(type, id) {
        AttachFile.pending = [];
        AttachFile._entity = id ? { type, id } : null;
        AttachFile._saved = [];
        AttachFile._read = null;
        const n = ++AttachFile._n;  // the newest form's list is the one drawn
        AttachFile._listId = `qb-attach-list-${n}`;
        if (id) setTimeout(() => AttachFile._loadSaved(), 0);
        return `<div class="qb-attach">
            <button type="button" class="btn btn-sm btn-secondary" onclick="this.parentElement.querySelector('input[type=file]').click()" title="Attach a document (the supplier's bill or statement, a receipt, a deposit slip); it is saved with the transaction">📎 Attach File</button>
            <input type="file" multiple hidden aria-label="Choose files to attach" onchange="AttachFile.add(this)">
            <span class="qb-attach-list" id="qb-attach-list-${n}" aria-live="polite"></span>
        </div>`;
    },

    add(input) {
        for (const f of Array.from(input.files || [])) {
            if (f.size > 50 * 1024 * 1024) { toast(`${f.name} is over 50 MB and can't be attached`, 'error'); continue; }
            AttachFile.pending.push(f);
        }
        input.value = '';
        AttachFile._draw();
    },

    remove(i) {
        AttachFile.pending.splice(i, 1);
        AttachFile._draw();
    },

    async _loadSaved() {
        const e = AttachFile._entity;
        if (!e) return;
        try { AttachFile._saved = await API.get(`/attachments/${e.type}/${e.id}`); } catch (err) { AttachFile._saved = []; }
        AttachFile._draw();
    },

    async removeSaved(attachId) {
        if (!confirm('Delete this attachment?')) return;
        try {
            await API.del(`/attachments/${attachId}`);
            toast('Attachment deleted');
            AttachFile._loadSaved();
        } catch (err) { toast(err.message, 'error'); }
    },

    // Can this form read a document? (the scan row is on it, and the scan
    // engine is installed)
    _canRead(f) {
        return !!document.getElementById('scan-row') && typeof ScanHelper !== 'undefined'
            && ScanHelper._status && ScanHelper._status.available && ScanHelper._applyCb
            && /^(image\/(png|jpeg|webp)|application\/pdf)$/.test(f.type || '');
    },

    // Read a waiting file into the form: the scan fills the fields and keeps
    // the file to attach on save, so it leaves this list.
    read(i) {
        const f = AttachFile.pending[i];
        if (!f || !AttachFile._canRead(f)) return;
        if (ScanHelper._intakeId && !confirm('Another document was read into this form already; read this one instead?')) return;
        AttachFile.pending.splice(i, 1);
        AttachFile._read = f.name;
        const row = document.getElementById('scan-row');
        if (row) row.classList.add('scan-row--used');
        ScanHelper.scan(f, ScanHelper._applyCb);
        AttachFile._draw();
    },

    _draw() {
        const el = document.getElementById(AttachFile._listId);
        if (!el) return;
        const saved = (AttachFile._entity ? AttachFile._saved : []).map(a => `<span class="qb-attach-file">
                ${a.missing ? escapeHtml(a.filename) : `<a href="/api/attachments/download/${a.id}" target="_blank">${escapeHtml(a.filename)}</a>`}
                <button type="button" data-destructive class="qb-attach-x" aria-label="Delete attachment ${escapeHtml(a.filename)}" onclick="AttachFile.removeSaved(${a.id})">×</button></span>`);
        const read = AttachFile._read && document.getElementById('scan-row')?.classList.contains('scan-row--used')
            ? [`<span class="qb-attach-file qb-attach-file--new" title="Read into the form; attached when saved">${escapeHtml(AttachFile._read)} <span class="qb-attach-when">(read · on save)</span></span>`] : [];
        const waiting = AttachFile.pending.map((f, i) => `<span class="qb-attach-file qb-attach-file--new" title="Attached when saved">
                ${escapeHtml(f.name)} <span class="qb-attach-when">(on save)</span>
                ${AttachFile._canRead(f) ? `<button type="button" class="qb-attach-read" onclick="AttachFile.read(${i})" title="Read the vendor, date, number and amounts from it into the form">Fill in from this document</button>` : ''}
                <button type="button" class="qb-attach-x" aria-label="Don't attach ${escapeHtml(f.name)}" onclick="AttachFile.remove(${i})">×</button></span>`);
        el.innerHTML = saved.concat(read, waiting).join('');
    },

    // After the save: the waiting files go on the saved transaction. A file
    // that fails is said so; the transaction itself is saved either way.
    async flush(type, id) {
        const files = AttachFile.pending.slice();
        AttachFile.pending = [];
        if (!files.length || !id) return;
        let done = 0;
        for (const f of files) {
            const fd = new FormData();
            fd.append('file', f);
            try {
                const resp = await fetch(`/api/attachments/${type}/${id}`, { method: 'POST', body: fd });
                if (!resp.ok) throw new Error(await API.responseError(resp, 'Upload failed'));
                done++;
            } catch (err) {
                toast(`Saved, but ${f.name} couldn't be attached: ${err.message}`, 'error');
            }
        }
        if (done) toast(done === 1 ? 'File attached' : `${done} files attached`);
    },
};

// The scan's form callback, kept for "Fill in from this document".
if (typeof ScanHelper !== 'undefined') {
    const baseWire = ScanHelper.wire;
    ScanHelper.wire = function (applyCallback, applyField, fieldTargets) {
        ScanHelper._applyCb = applyCallback || null;
        const r = baseWire.apply(ScanHelper, arguments);
        // once the scan engine's status is known, the links can show
        Promise.resolve(r).then(() => AttachFile._draw());
        return r;
    };
}
