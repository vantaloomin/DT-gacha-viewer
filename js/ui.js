// Small UI kit: styled replacements for native controls and browser dialogs. Styles in css/app.css.

// ---------- Icons (Lucide-style, 24px grid, stroke) ----------
const PATHS = {
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  pause: '<rect x="14" y="4" width="4" height="16" rx="1"/><rect x="6" y="4" width="4" height="16" rx="1"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
  sliders: '<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  chevronDown: '<path d="m6 9 6 6 6-6"/>',
  chevronLeft: '<path d="m15 18-6-6 6-6"/>',
  chevronRight: '<path d="m9 18 6-6-6-6"/>',
  sparkles: '<path d="M12 3l1.9 5.8L20 11l-6.1 2.2L12 19l-1.9-5.8L4 11l6.1-2.2z"/><path d="M19 3v4"/><path d="M21 5h-4"/>',
  box: '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
  film: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M7 3v18"/><path d="M3 7.5h4"/><path d="M3 12h18"/><path d="M3 16.5h4"/><path d="M17 3v18"/><path d="M17 7.5h4"/><path d="M17 16.5h4"/>',
  image: '<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
  maximize: '<path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/>',
  reset: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  checkCircle: '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
  alert: '<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  camera: '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/>',
  keyboard: '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h.01M12 12h.01M16 12h.01M7 16h10"/>',
  volume: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>',
  mute: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="22" x2="16" y1="9" y2="15"/><line x1="16" x2="22" y1="9" y2="15"/>',
  grid: '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
  arrowLeft: '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
  menu: '<line x1="4" x2="20" y1="12" y2="12"/><line x1="4" x2="20" y1="6" y2="6"/><line x1="4" x2="20" y1="18" y2="18"/>',
  zoomIn: '<circle cx="11" cy="11" r="8"/><line x1="21" x2="16.65" y1="21" y2="16.65"/><line x1="11" x2="11" y1="8" y2="14"/><line x1="8" x2="14" y1="11" y2="11"/>',
  rotate: '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>',
  pointer: '<path d="M22 14a8 8 0 0 1-8 8"/><path d="M18 11v-1a2 2 0 0 0-2-2a2 2 0 0 0-2 2"/><path d="M14 10V9a2 2 0 0 0-2-2a2 2 0 0 0-2 2v1"/><path d="M10 9.5V4a2 2 0 0 0-2-2a2 2 0 0 0-2 2v10"/><path d="M18 11a2 2 0 1 1 4 0v3a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/>',
  mic: '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/>',
  share: '<path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" x2="12" y1="2" y2="15"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/>',
};
export const icon = (name, cls = '') => `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${PATHS[name] || ''}</svg>`;

export const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
export function h(html) { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; }
export function store(k, v) { try { localStorage.setItem(k, typeof v === 'string' ? v : JSON.stringify(v)); } catch {} }
export function recall(k, fallback = null) { try { const v = localStorage.getItem(k); return v === null ? fallback : v; } catch { return fallback; } }
export const fmtTime = s => { s = Math.max(0, s || 0); const m = Math.floor(s / 60); return `${m}:${(s - m * 60).toFixed(1).padStart(4, '0')}`; };
export const fmtBytes = n => n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';

// Places a floating element next to an anchor, flipping above when there isn't room below.
function place(el, anchor, { gap = 6, align = 'start', prefer = 'below' } = {}) {
  const r = anchor.getBoundingClientRect(), vw = innerWidth, vh = innerHeight, margin = 8;
  el.style.minWidth = Math.max(r.width, 0) + 'px';
  el.style.maxWidth = (vw - 2 * margin) + 'px';
  const cap = parseFloat(getComputedStyle(el).maxHeight) || Infinity;   // the stylesheet's own limit, if any
  const natural = el.offsetHeight;
  const below = vh - r.bottom - gap - margin, above = r.top - gap - margin;
  const up = prefer === 'above' ? above >= natural || above > below : below < natural && above > below;
  // Limit the height to the space on the chosen side *before* measuring, so the position is computed
  // from the height it will really have (taller content scrolls inside).
  el.style.maxHeight = Math.max(120, Math.min(cap, up ? above : below)) + 'px';
  const w = el.offsetWidth, hgt = el.offsetHeight;
  const top = up ? r.top - gap - hgt : r.bottom + gap;
  let left = align === 'end' ? r.right - w : align === 'center' ? r.left + r.width / 2 - w / 2 : r.left;
  left = Math.min(Math.max(margin, left), vw - w - margin);
  Object.assign(el.style, { top: Math.min(Math.max(margin, top), vh - hgt - margin) + 'px', left: left + 'px' });
}

// Only one floating layer (menu/popover) open at a time; closes on outside click / Escape.
let openLayer = null;
function closeLayer() { if (openLayer) { const l = openLayer; openLayer = null; l.close(); } }
document.addEventListener('pointerdown', e => {
  if (openLayer && !openLayer.el.contains(e.target) && !openLayer.anchor.contains(e.target)) closeLayer();
}, true);
document.addEventListener('keydown', e => { if (e.key === 'Escape' && openLayer) { e.stopPropagation(); const a = openLayer.anchor; closeLayer(); a.focus(); } }, true);
addEventListener('resize', closeLayer);
export const anyLayerOpen = () => !!openLayer;

// ---------- Dropdown ----------
/**
 * items: [{ value, label, group?, hint? }]. Returns an element with .value (get/set) and .setItems(items).
 */
export function dropdown({ items = [], value, onChange, searchable = false, prefix = '', placeholder = 'Select…', title = '', prefer = 'below', align = 'start' } = {}) {
  const btn = h(`<button type="button" class="dd" aria-haspopup="listbox" aria-expanded="false">
    ${prefix ? `<span class="dd-prefix">${esc(prefix)}</span>` : ''}<span class="dd-label"></span>${icon('chevronDown')}</button>`);
  if (title) btn.dataset.tip = title;
  let current = value, list = items;
  const render = () => { const it = list.find(i => i.value === current); btn.querySelector('.dd-label').textContent = it ? it.label : placeholder; };
  const select = v => { current = v; render(); onChange?.(v); };

  function open() {
    const menu = h(`<div class="menu" role="listbox">${searchable ? `<label class="field">${icon('search')}<input type="text" placeholder="Search…" aria-label="Search"></label>` : ''}<div class="menu-list"></div></div>`);
    const listEl = menu.querySelector('.menu-list'), input = menu.querySelector('input');
    let shown = [], active = 0;
    const draw = () => {
      const q = (input?.value || '').trim().toLowerCase();
      shown = list.filter(i => !q || (i.label + ' ' + (i.group || '')).toLowerCase().includes(q));
      listEl.innerHTML = shown.length ? '' : '<div class="empty">No matches</div>';
      let group = null;
      shown.forEach((it, idx) => {
        if (it.group && it.group !== group) { group = it.group; listEl.append(h(`<div class="menu-group">${esc(group)}</div>`)); }
        const o = h(`<button type="button" class="opt" role="option" aria-selected="${it.value === current}">${icon('check')}<span class="opt-label">${esc(it.label)}</span>${it.hint ? `<span class="opt-hint">${esc(it.hint)}</span>` : ''}</button>`);
        o.onclick = () => { closeLayer(); select(it.value); btn.focus(); };
        o.onpointermove = () => setActive(idx);
        listEl.append(o);
      });
      active = Math.max(0, shown.findIndex(i => i.value === current));
      setActive(active, true);
    };
    const opts = () => listEl.querySelectorAll('.opt');
    const setActive = (i, scroll) => {
      active = i; opts().forEach((o, k) => o.classList.toggle('active', k === i));
      if (scroll) opts()[i]?.scrollIntoView({ block: 'nearest' });
    };
    menu.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); setActive((active + (e.key === 'ArrowDown' ? 1 : -1) + shown.length) % shown.length, true); }
      else if (e.key === 'Enter') { e.preventDefault(); const it = shown[active]; if (it) { closeLayer(); select(it.value); btn.focus(); } }
      else if (e.key === 'Tab') closeLayer();
    });
    input?.addEventListener('input', draw);
    document.body.append(menu);
    draw();
    place(menu, btn, { prefer, align });
    btn.setAttribute('aria-expanded', 'true');
    (input || opts()[active] || menu).focus();
    openLayer = { el: menu, anchor: btn, close: () => { menu.remove(); btn.setAttribute('aria-expanded', 'false'); } };
  }
  btn.onclick = () => { const wasMine = openLayer?.anchor === btn; closeLayer(); if (!wasMine) open(); };
  btn.addEventListener('keydown', e => { if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); if (openLayer?.anchor !== btn) open(); } });
  Object.defineProperty(btn, 'value', { get: () => current, set: v => { current = v; render(); } });
  btn.setItems = (newItems, v = current) => { list = newItems; current = v; render(); };
  btn.setSearchable = v => { searchable = v; };
  render();
  return btn;
}

// ---------- Segmented control ----------
export function segmented({ options, value, onChange, block = false, label = '' }) {
  const el = h(`<div class="seg${block ? ' block' : ''}" role="group"${label ? ` aria-label="${esc(label)}"` : ''}></div>`);
  let current = value;
  const draw = () => el.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', b.dataset.v === String(current)));
  for (const o of options) {
    const b = h(`<button type="button" data-v="${esc(o.value)}">${o.icon ? icon(o.icon) : ''}<span>${esc(o.label)}</span></button>`);
    if (o.tip) b.dataset.tip = o.tip;
    b.onclick = () => { current = o.value; draw(); onChange?.(o.value); };
    el.append(b);
  }
  Object.defineProperty(el, 'value', { get: () => current, set: v => { current = v; draw(); } });
  draw();
  return el;
}

// ---------- Toggle switch ----------
export function toggle({ label, checked = false, onChange }) {
  const el = h(`<label class="toggle"><input type="checkbox" role="switch"><span class="track"></span><span>${esc(label)}</span></label>`);
  const input = el.querySelector('input');
  input.checked = checked;
  input.onchange = () => onChange?.(input.checked);
  Object.defineProperty(el, 'checked', { get: () => input.checked, set: v => { input.checked = v; } });
  return el;
}

// ---------- Slider (styled native range, with filled track) ----------
export function slider({ min = 0, max = 100, step = 1, value = 0, onInput, label = '' }) {
  const el = h(`<input type="range" class="slider" min="${min}" max="${max}" step="${step}"${label ? ` aria-label="${esc(label)}"` : ''}>`);
  const fill = () => el.style.setProperty('--p', ((el.value - el.min) / (el.max - el.min || 1) * 100) + '%');
  el.value = value; fill();
  el.addEventListener('input', () => { fill(); onInput?.(+el.value); });
  el.setValue = v => { el.value = v; fill(); };
  el.setRange = (mn, mx) => { el.min = mn; el.max = mx; fill(); };
  return el;
}

// ---------- Swatches ----------
export function swatches({ options, value, onChange }) {
  const el = h('<div class="swatches" role="group"></div>');
  let current = value;
  const draw = () => el.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', b.dataset.v === current));
  for (const o of options) {
    const b = h(`<button type="button" class="swatch${o.value ? '' : ' transparent'}" data-v="${esc(o.value)}" aria-label="${esc(o.label)}" data-tip="${esc(o.label)}"></button>`);
    if (o.value) b.style.background = o.value;
    b.onclick = () => { current = o.value; draw(); onChange?.(o.value); };
    el.append(b);
  }
  Object.defineProperty(el, 'value', { get: () => current, set: v => { current = v; draw(); } });
  draw();
  return el;
}

// ---------- Popover ----------
export function popover(anchor, build, { prefer = 'below', align = 'end' } = {}) {
  anchor.setAttribute('aria-haspopup', 'dialog');
  anchor.addEventListener('click', () => {
    const wasMine = openLayer?.anchor === anchor;
    closeLayer();
    if (wasMine) return;
    const el = h('<div class="pop" role="dialog"></div>');
    el.append(build());
    document.body.append(el);
    place(el, anchor, { prefer, align });
    anchor.setAttribute('aria-expanded', 'true');
    openLayer = { el, anchor, close: () => { el.remove(); anchor.setAttribute('aria-expanded', 'false'); } };
  });
}
export const closePopovers = closeLayer;

// ---------- Tooltips (any element with data-tip; optional data-kbd shortcut) ----------
let tipEl = null, tipFor = null, tipTimer = 0;
export function initTooltips() {
  const hide = () => { clearTimeout(tipTimer); tipEl?.remove(); tipEl = null; tipFor = null; };
  document.addEventListener('pointerover', e => {
    const t = e.target.closest?.('[data-tip]');
    if (t === tipFor) return;
    hide();
    if (!t || !t.dataset.tip) return;
    tipFor = t;
    tipTimer = setTimeout(() => {
      if (!t.isConnected || openLayer?.anchor === t) return;
      tipEl = h(`<div class="tip" role="tooltip">${esc(t.dataset.tip)}${t.dataset.kbd ? `<kbd>${esc(t.dataset.kbd)}</kbd>` : ''}</div>`);
      document.body.append(tipEl);
      const r = t.getBoundingClientRect(), w = tipEl.offsetWidth, ht = tipEl.offsetHeight;
      let top = r.top - ht - 8; if (top < 6) top = r.bottom + 8;
      tipEl.style.top = top + 'px';
      tipEl.style.left = Math.min(Math.max(6, r.left + r.width / 2 - w / 2), innerWidth - w - 6) + 'px';
    }, 380);
  });
  document.addEventListener('pointerdown', hide, true);
  document.addEventListener('scroll', hide, true);
}

// ---------- Toasts ----------
let toastBox;
export function toast(title, { message = '', type = 'info', duration = 4500, action } = {}) {
  toastBox ||= document.body.appendChild(h('<div class="toasts" aria-live="polite"></div>'));
  const ic = { success: 'checkCircle', error: 'alert', info: 'info' }[type];
  const el = h(`<div class="toast ${type}" role="status">${icon(ic)}<div class="t-body"><div class="t-title">${esc(title)}</div>${message ? `<div class="t-msg">${esc(message)}</div>` : ''}</div>
    ${action ? `<button class="btn sm">${esc(action.label)}</button>` : ''}<button class="t-close" aria-label="Dismiss">${icon('x')}</button></div>`);
  const close = () => { el.classList.add('out'); setTimeout(() => el.remove(), 200); };
  el.querySelector('.t-close').onclick = close;
  if (action) el.querySelector('.btn').onclick = () => { action.onClick(); close(); };
  toastBox.append(el);
  if (duration) setTimeout(close, duration);
  return { close };
}

// ---------- Modal ----------
export function modal({ title, body }) {
  const scrim = h('<div class="scrim"></div>');
  const el = h(`<div class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}"><header><h3>${esc(title)}</h3>
    <button class="btn ghost icon" aria-label="Close">${icon('x')}</button></header><div class="m-body"></div></div>`);
  el.querySelector('.m-body').append(typeof body === 'string' ? h(`<div>${body}</div>`) : body);
  const close = () => { scrim.remove(); el.remove(); removeEventListener('keydown', onKey, true); };
  const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
  scrim.onclick = close; el.querySelector('header .btn').onclick = close;
  addEventListener('keydown', onKey, true);
  document.body.append(scrim, el);
  el.querySelector('header .btn').focus();
  return { close };
}

// ---------- Lightbox ----------
/** items: [{ src, title, download }] */
export function lightbox(items, start = 0) {
  let i = start;
  const el = h(`<div class="lightbox" role="dialog" aria-modal="true">
    <div class="lb-bar"><b class="lb-title"></b><span class="lb-meta"></span><span class="spacer"></span>
      <button class="btn ghost icon lb-zoom" data-tip="Actual size" data-kbd="Z">${icon('zoomIn')}</button>
      <a class="btn ghost icon lb-dl" data-tip="Download">${icon('download')}</a>
      <button class="btn ghost icon lb-close" data-tip="Close" data-kbd="Esc">${icon('x')}</button></div>
    <div class="lb-view"><img alt=""></div>
    <button class="btn icon round lb-nav lb-prev" aria-label="Previous">${icon('chevronLeft')}</button>
    <button class="btn icon round lb-nav lb-next" aria-label="Next">${icon('chevronRight')}</button></div>`);
  const img = el.querySelector('img');
  const show = () => {
    const it = items[i];
    el.classList.remove('zoomed');
    img.src = it.src;
    el.querySelector('.lb-title').textContent = it.title;
    el.querySelector('.lb-meta').textContent = items.length > 1 ? `${i + 1} / ${items.length}` : '';
    const a = el.querySelector('.lb-dl'); a.href = it.src; a.download = it.download || '';
    el.querySelectorAll('.lb-nav').forEach(b => b.style.display = items.length > 1 ? '' : 'none');
  };
  img.onload = () => { el.querySelector('.lb-meta').textContent = `${img.naturalWidth}×${img.naturalHeight}` + (items.length > 1 ? ` · ${i + 1} / ${items.length}` : ''); };
  const step = d => { i = (i + d + items.length) % items.length; show(); };
  const zoom = () => el.classList.toggle('zoomed');
  const close = () => { el.remove(); removeEventListener('keydown', onKey, true); };
  const onKey = e => {
    if (e.key === 'Escape') { e.stopPropagation(); close(); }
    else if (e.key === 'ArrowLeft') step(-1);
    else if (e.key === 'ArrowRight') step(1);
    else if (e.key.toLowerCase() === 'z') zoom();
    else return;
    e.preventDefault();
  };
  el.querySelector('.lb-prev').onclick = () => step(-1);
  el.querySelector('.lb-next').onclick = () => step(1);
  el.querySelector('.lb-close').onclick = close;
  el.querySelector('.lb-zoom').onclick = zoom;
  img.onclick = zoom;
  el.querySelector('.lb-view').onclick = e => { if (e.target === e.currentTarget) close(); };
  addEventListener('keydown', onKey, true);
  document.body.append(el);
  show();
  el.querySelector('.lb-close').focus();
}

export const typing = e => e.target.closest?.('input, textarea, [contenteditable]') && e.target.type !== 'range' && e.target.type !== 'checkbox';
