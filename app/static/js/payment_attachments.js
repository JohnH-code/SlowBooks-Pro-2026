/**
 * Documents on customer payments and bill payments (John's build).
 *
 * The cheque received with a payment, or the remittance with a bill
 * payment, kept on the payment itself as QuickBooks keeps it: an
 * Attachments box on the payment's view (as on a deposit's), and Attach
 * File on Receive Payments, attached once the payment is saved.
 */
const RecordFiles = {
    box(type, id) {
        return `<div class="record-files" data-type="${type}" data-id="${Number(id)}" style="margin-top:12px; border-top:1px solid var(--gray-300); padding-top:8px;">
            <div style="font-weight:700; font-size:12px; margin-bottom:4px;">Attachments</div>
            <div class="record-files-list" style="margin-bottom:8px; font-size:11px;">Loading...</div>
            <div style="display:flex; gap:6px; align-items:center;" data-write>
                <input type="file" class="record-files-input" aria-label="File to attach" style="font-size:11px;">
                <button type="button" class="btn btn-sm btn-secondary" onclick="RecordFiles.upload(this)">Attach</button>
            </div>
        </div>`;
    },

    // Put the box into the open view, above its buttons.
    insert(type, id) {
        const body = document.getElementById('modal-body');
        if (!body || body.querySelector('.record-files')) return;
        const actions = body.querySelector('.form-actions');
        const holder = document.createElement('div');
        holder.innerHTML = RecordFiles.box(type, id);
        const box = holder.firstElementChild;
        if (actions) actions.before(box); else body.appendChild(box);
        RecordFiles.load(box);
    },

    async load(box) {
        const el = box.querySelector('.record-files-list');
        const { type, id } = box.dataset;
        try {
            const files = await API.get(`/attachments/${type}/${id}`);
            el.innerHTML = files.length === 0
                ? '<span style="color:var(--text-muted);">No attachments</span>'
                : files.map(a => `<div style="display:flex; flex-wrap:wrap; align-items:center; gap:0 8px; padding:2px 0;">
                    ${a.missing ? `<span>${escapeHtml(a.filename)}</span>` : `<a href="/api/attachments/download/${a.id}" target="_blank">${escapeHtml(a.filename)}</a>`}
                    ${a.file_size == null ? '' : `<span style="color:var(--gray-400);">(${formatFileSize(a.file_size)})</span>`}
                    <button data-destructive aria-label="Delete attachment" class="btn btn-sm btn-danger" data-attachment="${a.id}" onclick="RecordFiles.remove(this)" style="padding:0 4px; font-size:10px;">X</button>
                </div>`).join('');
        } catch (e) { el.innerHTML = ''; }
    },

    async upload(button) {
        const box = button.closest('.record-files');
        const input = box.querySelector('.record-files-input');
        if (!input?.files[0]) { toast('Select a file first', 'error'); return; }
        const formData = new FormData();
        formData.append('file', input.files[0]);
        try {
            const resp = await fetch(`/api/attachments/${box.dataset.type}/${box.dataset.id}`, { method: 'POST', body: formData });
            if (!resp.ok) throw new Error(await API.responseError(resp, 'Upload failed'));
            toast('Attachment uploaded');
            input.value = '';
            RecordFiles.load(box);
        } catch (err) { toast(err.message, 'error'); }
    },

    async remove(button) {
        if (!confirm('Delete this attachment?')) return;
        const box = button.closest('.record-files');
        try {
            await API.del(`/attachments/${button.dataset.attachment}`);
            toast('Attachment deleted');
            RecordFiles.load(box);
        } catch (err) { toast(err.message, 'error'); }
    },
};
window.RecordFiles = RecordFiles;

document.addEventListener('DOMContentLoaded', () => {
    // a customer payment's view
    if (typeof PaymentsPage !== 'undefined' && PaymentsPage.view) {
        const baseView = PaymentsPage.view;
        PaymentsPage.view = async function (id) {
            const r = await baseView.apply(PaymentsPage, arguments);
            RecordFiles.insert('payment', id);
            return r;
        };
    }
    // a bill payment's view
    if (typeof BillsPage !== 'undefined' && BillsPage.viewPayment) {
        const baseViewPayment = BillsPage.viewPayment;
        BillsPage.viewPayment = async function (id) {
            const r = await baseViewPayment.apply(BillsPage, arguments);
            RecordFiles.insert('bill_payment', id);
            return r;
        };
    }
    // Receive Payments: Attach File, attached once the payment is saved
    if (typeof PaymentsPage !== 'undefined' && PaymentsPage.qbSave && typeof AttachFile !== 'undefined') {
        const baseShow = PaymentsPage.showForm;
        PaymentsPage.showForm = async function () {
            const r = await baseShow.apply(PaymentsPage, arguments);
            const form = document.getElementById('payment-form');
            const memo = form && form.querySelector('.qbr-memo');
            if (memo && !form.querySelector('.qb-attach')) {
                const holder = document.createElement('div');
                holder.innerHTML = AttachFile.html('payment', null);
                memo.after(...holder.childNodes);
            }
            return r;
        };
        const baseSave = PaymentsPage.qbSave;
        PaymentsPage.qbSave = async function () {
            const basePost = API.post;
            let saved = null;
            API.post = async function (url) {
                const res = await basePost.apply(API, arguments);
                if (typeof url === 'string' && url.startsWith('/payments') && res && res.id) saved = res;
                return res;
            };
            try {
                const r = await baseSave.apply(PaymentsPage, arguments);
                if (saved && AttachFile.pending.length) await AttachFile.flush('payment', saved.id);
                return r;
            } finally {
                API.post = basePost;
            }
        };
    }
});
