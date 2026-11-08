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

    _draw() {
        const el = document.getElementById(AttachFile._listId);
        if (!el) return;
        const saved = (AttachFile._entity ? AttachFile._saved : []).map(a => `<span class="qb-attach-file">
                ${a.missing ? escapeHtml(a.filename) : `<a href="/api/attachments/download/${a.id}" target="_blank">${escapeHtml(a.filename)}</a>`}
                <button type="button" class="qb-attach-x" aria-label="Delete attachment ${escapeHtml(a.filename)}" onclick="AttachFile.removeSaved(${a.id})">×</button></span>`);
        const waiting = AttachFile.pending.map((f, i) => `<span class="qb-attach-file qb-attach-file--new" title="Attached when saved">
                ${escapeHtml(f.name)} <span class="qb-attach-when">(on save)</span>
                <button type="button" class="qb-attach-x" aria-label="Don't attach ${escapeHtml(f.name)}" onclick="AttachFile.remove(${i})">×</button></span>`);
        el.innerHTML = saved.concat(waiting).join('');
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
