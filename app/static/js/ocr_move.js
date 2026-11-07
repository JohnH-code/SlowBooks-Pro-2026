/**
 * Move and resize a box on the scanned receipt (John's build).
 *
 * The scan's review canvas reads a box drawn around a value; a box in the
 * wrong place could only be drawn again. Here a box can also be dragged
 * where it belongs, or made bigger or smaller from its bottom-right corner,
 * and is read again where it is dropped: drag the "Invoice / Ref #" box
 * from the total onto the invoice number and the form gets the number.
 * Dragging anywhere else still draws a new box, as before.
 */
(function () {
    if (typeof OcrCanvas === 'undefined') return;
    const C = OcrCanvas;
    const GRIP = 9;  // canvas pixels around the bottom-right corner

    const scaleOf = canvas => {
        const r = canvas.getBoundingClientRect();
        return { r, kx: r.width ? canvas.width / r.width : 1, ky: r.height ? canvas.height / r.height : 1 };
    };
    const posOf = (canvas, evt) => {
        const { r, kx, ky } = scaleOf(canvas);
        return { x: (evt.clientX - r.left) * kx, y: (evt.clientY - r.top) * ky };
    };

    // The box under a point, topmost first: the box being placed, then the
    // read ones. `corner` when the point is on its bottom-right grip.
    function boxAt(p) {
        const s = C._scale || 1;
        const hit = b => b && p.x >= b.left * s - GRIP && p.x <= (b.left + b.width) * s + GRIP
            && p.y >= b.top * s - GRIP && p.y <= (b.top + b.height) * s + GRIP;
        const corner = b => Math.abs(p.x - (b.left + b.width) * s) <= GRIP && Math.abs(p.y - (b.top + b.height) * s) <= GRIP;
        const inside = b => p.x >= b.left * s && p.x <= (b.left + b.width) * s && p.y >= b.top * s && p.y <= (b.top + b.height) * s;
        if (C._pendingBox && !C._pendingSug && hit(C._pendingBox)) {
            const b = C._pendingBox;
            if (corner(b)) return { box: b, sug: null, mode: 'resize' };
            if (inside(b)) return { box: b, sug: null, mode: 'move' };
        }
        for (let i = C._suggestions.length - 1; i >= 0; i--) {
            const sug = C._suggestions[i];
            if (sug.reading || !hit(sug.box)) continue;
            if (corner(sug.box)) return { box: sug.box, sug, mode: 'resize' };
            if (inside(sug.box)) return { box: sug.box, sug, mode: 'move' };
        }
        return null;
    }

    C._bind = function (canvas) {
        if (canvas._ocrBound) return;
        canvas._ocrBound = true;
        canvas.title = 'Drag around a value to read it; drag a box to move it, or its corner to resize it';
        canvas.addEventListener('mousedown', evt => {
            const p = posOf(canvas, evt);
            const at = boxAt(p);
            if (at) {
                evt.preventDefault();
                C._move = { ...at, x0: p.x, y0: p.y, orig: { ...at.box }, moved: false };
                return;
            }
            C._drag = { x0: p.x, y0: p.y, x1: p.x, y1: p.y };
        });
        canvas.addEventListener('mousemove', evt => {
            const p = posOf(canvas, evt);
            if (C._move) {
                const m = C._move;
                const s = C._scale || 1;
                const dx = (p.x - m.x0) / s, dy = (p.y - m.y0) / s;
                if (Math.abs(p.x - m.x0) > 3 || Math.abs(p.y - m.y0) > 3) m.moved = true;
                if (m.mode === 'move') {
                    m.box.left = Math.max(0, Math.round(m.orig.left + dx));
                    m.box.top = Math.max(0, Math.round(m.orig.top + dy));
                } else {
                    m.box.width = Math.max(6, Math.round(m.orig.width + dx));
                    m.box.height = Math.max(6, Math.round(m.orig.height + dy));
                }
                C._draw();
                return;
            }
            if (C._drag) {
                C._drag.x1 = p.x; C._drag.y1 = p.y;
                C._draw();
                return;
            }
            const at = boxAt(p);
            canvas.style.cursor = !at ? 'crosshair' : (at.mode === 'resize' ? 'nwse-resize' : 'move');
        });
        if (C._winBound) return;
        C._winBound = true;
        window.addEventListener('mouseup', evt => {
            const cv = document.getElementById('ocr-canvas');
            if (C._move) {
                const m = C._move;
                C._move = null;
                if (!cv) return;
                if (!m.moved) {
                    // a click on a box: select it, as before
                    C._click(posOf(cv, evt));
                    C._draw();
                    return;
                }
                if (m.sug) {
                    // a read box moved or resized: read it again where it is
                    C._pendingBox = { ...m.box };
                    C._pendingSug = m.sug;
                    C._assign(m.sug.key);
                } else {
                    C._refreshToolbar();
                    C._draw();
                    C._msg('Box moved — tap what it is on the toolbar below.');
                }
                return;
            }
            if (!C._drag) return;
            if (!cv) { C._drag = null; return; }
            const d = C._drag;
            C._drag = null;
            const w = Math.abs(d.x1 - d.x0), h = Math.abs(d.y1 - d.y0);
            if (w < 6 && h < 6) { C._click(posOf(cv, evt)); C._draw(); return; }
            const s = C._scale || 1;
            C._pendingBox = {
                left: Math.max(0, Math.round(Math.min(d.x0, d.x1) / s)),
                top: Math.max(0, Math.round(Math.min(d.y0, d.y1) / s)),
                width: Math.round(w / s),
                height: Math.round(h / s),
            };
            C._pendingSug = null;
            C._draw();
            if (C._armed) {
                const key = C._armed;
                C._armed = null;
                C._assign(key);
            } else {
                C._refreshToolbar();
                C._msg('Box drawn — tap what it is on the toolbar below, or drag it into place.');
            }
        });
    };
})();
