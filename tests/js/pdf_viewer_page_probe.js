// Run the Save PDF viewer page's script (desktop_launcher._VIEWER_PAGE)
// against a stub page and bridge: the buttons wake when the bridge is
// ready, each calls its bridge method, a refusal shows in the page, and
// Cmd/Ctrl+P prints and Cmd/Ctrl+S is Save… (John's build). Prints JSON.
//
//   node tests/js/pdf_viewer_page_probe.js <file holding the page's script>
const fs = require('fs'), vm = require('vm');

const script = fs.readFileSync(process.argv[2], 'utf8');
const el = () => ({ disabled: true, textContent: '', listeners: {}, addEventListener(t, f) { this.listeners[t] = f; } });
const els = { 'print-doc': el(), 'open-in-app': el(), 'save-copy': el(), note: el() };
const docListeners = {};
const winListeners = {};
const calls = [];
const answers = { open_in_default_app: { success: false, error: 'No app opens PDFs on this computer.' }, save_copy: { success: true, path: '/Users/j/Documents/x.pdf' }, print_document: { success: true } };
const win = { addEventListener: (t, f) => { winListeners[t] = f; } };
const ctx = {
  window: win,
  document: {
    getElementById: (id) => els[id],
    addEventListener: (t, f) => { docListeners[t] = f; },
  },
};
vm.createContext(ctx);
vm.runInContext(script, ctx);

(async () => {
  const out = { before_ready: [els['open-in-app'].disabled, els['save-copy'].disabled] };
  win.pywebview = { api: {
    open_in_default_app: async () => { calls.push('open_in_default_app'); return answers.open_in_default_app; },
    save_copy: async () => { calls.push('save_copy'); return answers.save_copy; },
    print_document: async () => { calls.push('print_document'); return answers.print_document; },
  } };
  winListeners.pywebviewready();
  out.after_ready = [els['open-in-app'].disabled, els['save-copy'].disabled];
  els['save-copy'].listeners.click();
  await new Promise((r) => setTimeout(r, 5));
  out.note_after_show = els.note.textContent;
  els['open-in-app'].listeners.click();
  await new Promise((r) => setTimeout(r, 5));
  out.note_after_open = els.note.textContent;
  out.print_ready = !els['print-doc'].disabled;
  let prevented = 0;
  for (const key of ['p', 's', 'x']) {
    docListeners.keydown({ metaKey: true, ctrlKey: false, key, preventDefault: () => { prevented++; } });
  }
  await new Promise((r) => setTimeout(r, 5));
  out.prevented = prevented;
  out.calls = calls;
  console.log(JSON.stringify(out));
})();
