/**
 * One-step attach (John's build).
 *
 * A record's Attachments box (deposit, cheque, card charge, journal entry,
 * bill, invoice, payment) had a file chooser and, beside it, an Attach (or
 * Upload) button: choose the file, then attach it. Now the button alone
 * does it: "Attach File…" opens the Mac file chooser, and the file chosen
 * is attached at once. The chooser itself is hidden.
 *
 * It works on the boxes as each page draws them (a file input whose next
 * sibling is the Attach/Upload button), so every page's own upload code
 * stays as it is: the button's click runs it once a file is chosen.
 */
const OneStepAttach = {
    SELECTOR: 'input[type="file"].record-files-input, input[type="file"][id$="-attach-file"]',

    _buttonFor(input) {
        const b = input.nextElementSibling;
        return b && b.tagName === 'BUTTON' && /^(attach|upload)$/i.test(b.textContent.trim()) ? b : null;
    },

    fit(root) {
        (root || document).querySelectorAll(OneStepAttach.SELECTOR).forEach(input => {
            if (input.dataset.oneStep) return;
            const button = OneStepAttach._buttonFor(input);
            if (!button) return;
            input.dataset.oneStep = '1';
            input.hidden = true;
            button.dataset.oneStep = '1';
            button.textContent = 'Attach File…';
            button.setAttribute('aria-label', 'Choose a file and attach it');
            input.addEventListener('change', () => {
                if (!input.files || !input.files.length) return;
                // the page's own Attach: it reads the file from this input
                button.dataset.oneStepGo = '1';
                button.click();
                delete button.dataset.oneStepGo;
            });
        });
    },
};

// Before the button's own onclick: with no file chosen yet, open the
// chooser instead (the upload runs when a file is picked).
document.addEventListener('click', e => {
    const button = e.target.closest && e.target.closest('button[data-one-step]');
    if (!button || button.dataset.oneStepGo) return;
    const input = button.previousElementSibling;
    if (!input || input.type !== 'file') return;
    e.preventDefault();
    e.stopImmediatePropagation();
    input.value = '';
    input.click();
}, true);

(function () {
    const run = () => {
        OneStepAttach.fit(document);
        new MutationObserver(records => {
            for (const r of records) {
                if (r.addedNodes.length) { OneStepAttach.fit(document); return; }
            }
        }).observe(document.body, { childList: true, subtree: true });
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run);
    else run();
})();
