// Playback dock, export drawer and video player shared by the gallery and the rig browser.
import { icon, h, esc, dropdown, segmented, toggle, slider, swatches, popover, closePopovers, toast, store, recall, fmtTime, fmtBytes } from './ui.js';
import { exportAnimation, exportStill, download, safeFilename, FORMATS } from './export.js';

/*
 Stage adapter contract (see index.html / viewer.html):
   kind: 'spine' | 'model'
   ready(): boolean
   paused, time, duration (getters); pause(), resume(), seek(t)
   animations(): [{ value, label, group? }]; current(): name; setAnimation(name)
   settings(): Element for the dock's settings popover
   beginCapture(opts): { width, height, frameCount, drawFrame, done, setTransparent? }
   aspect(framing): output aspect ratio (w/h), or null if unknown until capture
   filename({ still, turntable }): base filename without extension
*/

// Groups long clip lists (3D models have up to ~100) so the picker is scannable.
export function groupClip(name) {
  if (/^(idle|run|walk|birth|switch|jiezhan)/.test(name)) return 'Idle & movement';
  if (/^skill/.test(name)) return 'Skills';
  if (/^juqing/.test(name)) return 'Story';
  if (/(hit|beat|repel|stun|knock|dead|die|get_up|zhengzha|behit|float)/.test(name)) return 'Reactions';
  return 'Other';
}

export function createDock(stage, adapter, { onSnapshot, sound } = {}) {
  const el = h(`<div class="dock" role="toolbar" aria-label="Playback">
    <button class="btn play" data-tip="Play / pause" data-kbd="Space" aria-label="Play or pause">${icon('pause')}</button>
    <span class="time t-cur">0:00.0</span><span class="scrub-wrap" style="flex:1;display:flex"></span><span class="time t-dur">0:00.0</span>
    <span class="dock-sep"></span><span class="anim-wrap"></span>
    <button class="btn icon ghost sound" data-kbd="M" aria-label="Sound" style="display:none"></button>
    <button class="btn icon ghost snap" data-tip="Save still image" data-kbd="S" aria-label="Save still image">${icon('camera')}</button>
    <button class="btn icon ghost opts" data-tip="View settings" aria-label="View settings">${icon('sliders')}</button></div>`);
  const play = el.querySelector('.play');
  const scrub = slider({ min: 0, max: 1, step: 0.001, value: 0, label: 'Timeline' });
  scrub.classList.add('scrub');
  el.querySelector('.scrub-wrap').append(scrub);
  const anim = dropdown({ items: [], placeholder: 'Animation', prefer: 'above', searchable: false, onChange: v => adapter.setAnimation(v), title: 'Animation' });
  el.querySelector('.anim-wrap').append(anim);
  play.onclick = () => { adapter.paused ? adapter.resume() : adapter.pause(); };
  el.querySelector('.snap').onclick = () => onSnapshot?.();
  // Optional sound toggle: sound = { get on(), set(on) }
  const soundBtn = el.querySelector('.sound');
  const drawSound = () => {
    soundBtn.innerHTML = icon(sound.on ? 'volume' : 'mute');
    soundBtn.dataset.tip = sound.on ? 'Sound on (click to mute)' : 'Sound off (click for voice lines)';
    soundBtn.setAttribute('aria-pressed', sound.on);
    soundBtn.style.color = sound.on ? 'var(--accent)' : '';
  };
  if (sound) { soundBtn.style.display = ''; soundBtn.onclick = () => { sound.set(!sound.on); drawSound(); }; drawSound(); }
  popover(el.querySelector('.opts'), () => adapter.settings(), { prefer: 'above', align: 'end' });

  let dragging = false, wasPaused = false;
  scrub.addEventListener('pointerdown', () => { if (!adapter.ready()) return; dragging = true; wasPaused = adapter.paused; adapter.pause(); });
  scrub.addEventListener('input', () => adapter.ready() && adapter.seek(+scrub.value));
  const endDrag = () => { if (!dragging) return; dragging = false; if (!wasPaused) adapter.resume(); };
  scrub.addEventListener('pointerup', endDrag); scrub.addEventListener('change', endDrag);

  let lastPaused = null;
  (function loop() {
    requestAnimationFrame(loop);
    if (!el.isConnected || !adapter.ready()) return;
    const d = adapter.duration || 0;
    if (!dragging) { scrub.setRange(0, d || 1); scrub.setValue(adapter.time); }
    el.querySelector('.t-cur').textContent = fmtTime(dragging ? +scrub.value : adapter.time);
    el.querySelector('.t-dur').textContent = fmtTime(d);
    if (adapter.paused !== lastPaused) { lastPaused = adapter.paused; play.innerHTML = icon(lastPaused ? 'play' : 'pause'); }
  })();

  stage.append(el);
  return {
    el,
    refresh() {
      const items = adapter.animations();
      anim.setItems(items, adapter.current());
      anim.setSearchable(items.length > 12);   // a search box only helps for long lists
      anim.style.display = items.length ? '' : 'none';
    },
    sync() { anim.value = adapter.current(); },
    syncSound() { if (sound) drawSound(); },
  };
}

// ---------- Export drawer ----------
const SIZE_OPTS = [512, 1024, 1536, 2048, 2340];
const FPS_OPTS = [15, 24, 30, 60];
const BG_OPTS = [
  { value: '', label: 'Transparent' }, { value: '#000000', label: 'Black' }, { value: '#1d1d23', label: 'Dark' },
  { value: '#ffffff', label: 'White' }, { value: '#00b140', label: 'Green screen' },
];

export function createExportDrawer() {
  const saved = JSON.parse(recall('exportSettings', '{}') || '{}');
  const s = Object.assign({ mode: 'animation', format: 'webp', framing: 'phone', turntable: false, size: 1024, fps: 30, bg: '', quality: 90 }, saved);
  const persist = () => store('exportSettings', JSON.stringify(s));
  let adapter = null, running = null;

  const scrim = h('<div class="scrim" style="display:none"></div>');
  const el = h(`<aside class="drawer" aria-label="Export" aria-hidden="true">
    <header><div><h3>Export</h3><div class="sub"></div></div><button class="btn ghost icon x-close" aria-label="Close" data-kbd="Esc">${icon('x')}</button></header>
    <div class="d-body">
      <section><h4>Output</h4><div class="x-mode"></div></section>
      <section class="x-formats-sec"><h4>Format</h4><div class="formats"></div></section>
      <section class="x-framing-sec"><h4>Framing</h4><div class="x-framing"></div></section>
      <section class="x-turn-sec"><div class="x-turn"></div></section>
      <section><div class="row-between"><h4>Size</h4><span class="x-dims" style="color:var(--dim);font-size:12px"></span></div><div class="x-size"></div></section>
      <section class="x-fps-sec"><h4>Frame rate</h4><div class="x-fps"></div></section>
      <section><h4>Background</h4><div class="x-bg"></div></section>
      <section class="x-q-sec"><div class="row-between"><h4>Quality</h4><span class="x-qv" style="color:var(--dim);font-size:12px"></span></div><div class="x-q"></div></section>
      <div class="x-notes" style="display:grid;gap:8px"></div>
    </div>
    <footer><div class="summary"><span class="x-sum"></span><span class="x-pct"></span></div>
      <div class="progress" style="display:none"><div></div></div>
      <div class="row-between"><button class="btn ghost x-cancel">Close</button><button class="btn primary x-go">${icon('download')}<span>Export</span></button></div></footer></aside>`);
  document.body.append(scrim, el);
  const $ = sel => el.querySelector(sel);

  const mode = segmented({ block: true, value: s.mode, options: [{ value: 'animation', label: 'Animation', icon: 'film' }, { value: 'still', label: 'Still image', icon: 'camera' }], onChange: v => { s.mode = v; update(); } });
  $('.x-mode').append(mode);
  for (const [k, f] of Object.entries(FORMATS)) {
    const b = h(`<button type="button" class="format" data-v="${k}"><b>${esc(f.label)}</b><span>${esc(f.hint)}</span></button>`);
    b.onclick = () => { s.format = k; update(); };
    $('.formats').append(b);
  }
  const framing = segmented({ block: true, value: s.framing, options: [{ value: 'phone', label: 'Phone screen', tip: 'Exactly what the phone shows' }, { value: 'tight', label: 'Character only', tip: 'Cropped to everything the animation draws' }], onChange: v => { s.framing = v; update(); } });
  $('.x-framing').append(framing);
  const turn = toggle({ label: '360° turntable — spin the model while it animates', checked: s.turntable, onChange: v => { s.turntable = v; update(); } });
  $('.x-turn').append(turn);
  const size = segmented({ block: true, value: s.size, options: SIZE_OPTS.map(v => ({ value: v, label: v === 2340 ? 'Native' : String(v), tip: v === 2340 ? '2340 px — the game\'s screen width' : `${v} px long edge` })), onChange: v => { s.size = v; update(); } });
  $('.x-size').append(size);
  const fps = segmented({ block: true, value: s.fps, options: FPS_OPTS.map(v => ({ value: v, label: `${v} fps` })), onChange: v => { s.fps = v; update(); } });
  $('.x-fps').append(fps);
  const bg = swatches({ options: BG_OPTS, value: s.bg, onChange: v => { s.bg = v; update(); } });
  $('.x-bg').append(bg);
  const q = slider({ min: 10, max: 100, step: 5, value: s.quality, label: 'Quality', onInput: v => { s.quality = v; update(); } });
  q.style.width = '100%';
  $('.x-q').append(q);

  function dims() {
    const a = adapter?.aspect(s.framing);
    if (!a) return null;
    let w, hh; if (a >= 1) { w = s.size; hh = Math.round(s.size / a); } else { hh = s.size; w = Math.round(s.size * a); }
    return [w + (w & 1), hh + (hh & 1)];
  }

  function update() {
    persist();
    const still = s.mode === 'still', f = FORMATS[s.format];
    $('.x-formats-sec').style.display = still ? 'none' : '';
    $('.x-fps-sec').style.display = still ? 'none' : '';
    $('.x-q-sec').style.display = !still && f.quality ? '' : 'none';
    $('.x-framing-sec').style.display = adapter?.kind === 'spine' ? '' : 'none';
    $('.x-turn-sec').style.display = adapter?.kind === 'model' && !still ? '' : 'none';
    el.querySelectorAll('.format').forEach(b => b.setAttribute('aria-pressed', b.dataset.v === s.format));
    $('.x-qv').textContent = s.quality + '%';
    const d = dims();
    $('.x-dims').textContent = d ? `${d[0]} × ${d[1]} px` : 'long edge ' + s.size + ' px';
    const notes = [];
    if (!still && s.format === 'gif' && !s.bg) notes.push('GIF transparency is all-or-nothing, so soft edges turn jagged. Pick a background colour for cleaner results.');
    if (!still && s.format === 'webm' && !s.bg) notes.push('Transparent WebM needs a browser that can encode VP9 alpha; otherwise it falls back to black.');
    if (!still && s.size >= 2048 && s.format === 'gif') notes.push('Large GIFs take a while to encode and can be very big.');
    $('.x-notes').innerHTML = notes.map(n => `<div class="note">${icon('info')}<span>${esc(n)}</span></div>`).join('');
    if (adapter?.ready()) {
      const dur = adapter.duration || 0;
      const secs = adapter.kind === 'model' && s.turntable ? Math.max(6, dur) : dur;
      const frames = Math.max(1, Math.round(secs * s.fps));
      $('.x-sum').textContent = still ? 'Current frame as PNG' : `${frames} frames · ${secs.toFixed(1)} s`;
    }
    $('.x-go span').textContent = still ? 'Save PNG' : `Export ${f.label}`;
    mode.value = s.mode; framing.value = s.framing; size.value = s.size; fps.value = s.fps; bg.value = s.bg; turn.checked = s.turntable;
  }

  function open(a) {
    adapter = a;
    if (!adapter.ready()) return toast('Nothing to export yet', { message: 'Wait for the animation to finish loading.', type: 'info' });
    $('.sub').textContent = adapter.current() ? `Animation: ${adapter.current()}` : '';
    update();
    scrim.style.display = ''; el.classList.add('open'); el.setAttribute('aria-hidden', 'false'); document.body.classList.add('drawer-open');
    $('.x-go').focus();
  }
  function close() {
    if (running) return;
    scrim.style.display = 'none'; el.classList.remove('open'); el.setAttribute('aria-hidden', 'true'); document.body.classList.remove('drawer-open');
  }
  scrim.onclick = close; $('.x-close').onclick = close;
  $('.x-cancel').onclick = () => running ? running.abort() : close();
  addEventListener('keydown', e => { if (e.key === 'Escape' && el.classList.contains('open') && !running) { e.stopPropagation(); close(); } }, true);
  $('.x-go').onclick = () => run(s.mode === 'still');

  async function run(still) {
    if (!adapter?.ready() || running) return;
    closePopovers();
    const ctrl = new AbortController(); running = ctrl;
    const bar = $('.progress'), fill = bar.firstElementChild;
    bar.style.display = ''; fill.style.width = '0';
    $('.x-go').disabled = true; $('.x-cancel').textContent = 'Cancel';
    el.querySelectorAll('.d-body button, .d-body input').forEach(b => b.disabled = true);
    const turntable = adapter.kind === 'model' && s.turntable && !still;
    const cap = adapter.beginCapture({ framing: s.framing, longEdge: s.size, fps: s.fps, still, turntable });
    cap.setTransparent?.(true);   // the exporter draws its own background
    const base = safeFilename(adapter.filename({ still, turntable }));
    try {
      if (still) {
        const blob = await exportStill({ width: cap.width, height: cap.height, background: s.bg, drawFrame: cap.drawFrame });
        download(blob, base + '.png');
        toast('Saved still image', { type: 'success', message: `${base}.png · ${cap.width}×${cap.height} · ${fmtBytes(blob.size)}` });
      } else {
        const { blob, ext, alphaLost } = await exportAnimation({
          format: s.format, width: cap.width, height: cap.height, fps: s.fps, frameCount: cap.frameCount, background: s.bg,
          quality: s.quality / 100, drawFrame: cap.drawFrame, signal: ctrl.signal,
          onProgress: (i, n) => { fill.style.width = (i / n * 100) + '%'; $('.x-pct').textContent = `Frame ${i} of ${n}`; },
        });
        $('.x-pct').textContent = 'Encoding…';
        download(blob, `${base}.${ext}`);
        toast(`Saved ${FORMATS[s.format].label}`, { type: 'success', message: `${base}.${ext} · ${cap.width}×${cap.height} · ${cap.frameCount} frames · ${fmtBytes(blob.size)}` });
        if (alphaLost) toast('Saved without transparency', { type: 'info', message: 'This browser can\'t encode transparent WebM, so the background is black. Use WebP or PNG frames for transparency.', duration: 8000 });
      }
    } catch (e) {
      if (e.name === 'AbortError') toast('Export cancelled', { type: 'info', duration: 2500 });
      else { toast('Export failed', { type: 'error', message: e.message, duration: 8000 }); console.error(e); }
    } finally {
      cap.done();
      running = null;
      bar.style.display = 'none'; $('.x-pct').textContent = '';
      $('.x-go').disabled = false; $('.x-cancel').textContent = 'Close';
      el.querySelectorAll('.d-body button, .d-body input').forEach(b => b.disabled = false);
      update();
    }
  }

  return { open, close, snapshot: a => { adapter = a; run(true); }, get isOpen() { return el.classList.contains('open'); } };
}

// ---------- Video player ----------
export function createVideoPlayer(container) {
  const el = h(`<div class="vwrap"><div class="row-between v-top"><div class="v-switch"></div><div class="v-opts"><span class="v-auto"></span><span class="v-loop"></span><a class="btn v-dl">${icon('download')}<span>Download WebM</span></a></div></div>
    <div class="vplayer"><video playsinline preload="metadata"></video>
      <button class="big-play" aria-label="Play">${icon('play')}</button>
      <div class="vbar"><button class="btn icon ghost v-play" aria-label="Play or pause" data-kbd="Space">${icon('play')}</button>
        <span class="time v-cur" style="font-variant-numeric:tabular-nums;font-size:12px;color:var(--muted)">0:00.0</span><span class="v-scrub" style="flex:1;display:flex"></span>
        <span class="time v-dur" style="font-variant-numeric:tabular-nums;font-size:12px;color:var(--muted)">0:00.0</span>
        <button class="btn icon ghost v-mute" aria-label="Mute" data-tip="Mute / unmute">${icon('volume')}</button>
        <button class="btn icon ghost v-full" aria-label="Fullscreen" data-tip="Fullscreen" data-kbd="F">${icon('maximize')}</button></div></div></div>`);
  container.append(el);
  const v = el.querySelector('video'), player = el.querySelector('.vplayer');
  const scrub = slider({ min: 0, max: 1, step: 0.01, value: 0, label: 'Video position' });
  scrub.style.flex = '1';
  el.querySelector('.v-scrub').append(scrub);
  let sources = [], current = 0, sw = null, idleTimer = 0;
  // Auto-play is off by default; the choice is remembered
  let autoplay = recall('videoAutoplay') === 'true';
  el.querySelector('.v-auto').append(toggle({ label: 'Auto-play', checked: autoplay, onChange: on => { autoplay = on; store('videoAutoplay', on); } }));
  // Loop is off by default too: a video plays to the end and stops; Play starts it again.
  v.loop = recall('videoLoop') === 'true';
  el.querySelector('.v-loop').append(toggle({ label: 'Loop', checked: v.loop, onChange: on => { v.loop = on; store('videoLoop', on); } }));

  const togglePlay = () => v.paused ? v.play() : v.pause();
  el.querySelector('.big-play').onclick = togglePlay;
  el.querySelector('.v-play').onclick = togglePlay;
  v.onclick = togglePlay;
  v.onplay = v.onpause = () => {
    player.classList.toggle('playing', !v.paused);
    el.querySelector('.v-play').innerHTML = icon(v.paused ? 'play' : 'pause');
    wake();
  };
  v.onloadedmetadata = () => { scrub.setRange(0, v.duration || 1); el.querySelector('.v-dur').textContent = fmtTime(v.duration); };
  v.ontimeupdate = () => { scrub.setValue(v.currentTime); el.querySelector('.v-cur').textContent = fmtTime(v.currentTime); };
  scrub.addEventListener('input', () => { v.currentTime = +scrub.value; });
  el.querySelector('.v-mute').onclick = () => { v.muted = !v.muted; el.querySelector('.v-mute').innerHTML = icon(v.muted ? 'mute' : 'volume'); };
  el.querySelector('.v-full').onclick = () => document.fullscreenElement ? document.exitFullscreen() : player.requestFullscreen();
  const wake = () => { player.classList.remove('idle'); clearTimeout(idleTimer); if (!v.paused) idleTimer = setTimeout(() => player.classList.add('idle'), 2200); };
  player.addEventListener('pointermove', wake);

  function load(i) {
    current = i;
    const s = sources[i];
    v.src = s.src; v.load();
    player.classList.remove('playing');
    const a = el.querySelector('.v-dl'); a.href = s.src; a.download = s.download;
    scrub.setValue(0);
    if (autoplay) v.play().catch(() => {});   // allowed for muted video; otherwise the big play button shows
  }
  return {
    el,
    setSources(list) {
      sources = list;
      sw?.remove(); sw = null;
      if (list.length > 1) { sw = segmented({ value: 0, options: list.map((s, i) => ({ value: i, label: s.label })), onChange: load }); el.querySelector('.v-switch').append(sw); }
      else el.querySelector('.v-switch').innerHTML = `<span style="color:var(--muted)">${esc(list[0]?.label || '')}</span>`;
      v.muted = true; el.querySelector('.v-mute').innerHTML = icon('mute');
      if (list.length) load(0);
    },
    stop() { v.pause(); },
    toggle: togglePlay,
    fullscreen: () => el.querySelector('.v-full').click(),
  };
}

// ---------- Tap interactions on a Spine screen ----------
/** Wires taps on the phone screen to stage.tap(), with a ripple, pointer cursor and optional zone overlay. */
export function attachTaps(screen, stage) {
  const overlay = h('<div class="zones" aria-hidden="true"></div>');
  screen.append(overlay);
  let show = recall('showZones') === 'true';
  const local = e => { const r = screen.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  const hit = (x, y) => stage.zones().find(z => z.enabled && x >= z.left && x <= z.left + z.width && y >= z.top && y <= z.top + z.height);
  screen.addEventListener('pointerdown', e => {
    if (stage.mode !== 'interactive' || e.button !== 0) return;
    const [x, y] = local(e);
    if (!stage.tap(x, y)) return;
    const r = h(`<span class="ripple" style="left:${x}px;top:${y}px"></span>`);
    screen.append(r); setTimeout(() => r.remove(), 600);
  });
  screen.addEventListener('pointermove', e => { screen.style.cursor = stage.mode === 'interactive' && hit(...local(e)) ? 'pointer' : ''; });
  (function loop() {
    requestAnimationFrame(loop);
    if (!screen.isConnected) return;
    const zones = show && stage.player?.skeleton ? stage.zones() : [];
    while (overlay.children.length > zones.length) overlay.lastChild.remove();
    zones.forEach((z, i) => {
      const el = overlay.children[i] || overlay.appendChild(h('<div class="zone"></div>'));
      Object.assign(el.style, { left: z.left + 'px', top: z.top + 'px', width: z.width + 'px', height: z.height + 'px' });
      el.classList.toggle('off', !z.enabled);
    });
  })();
  return {
    get show() { return show; },
    set show(v) { show = v; store('showZones', String(v)); },
  };
}

// ---------- Spine settings popover (shared by the gallery and the rig browser) ----------
/**
 * opts: { zoom: () => number, setZoom(v), taps (from attachTaps), voice: { settings, save, greet() } | null }
 */
export function spineSettings(stage, opts) {
  const el = h(`<div style="display:grid;gap:16px;width:290px">
    <div class="pop-row"><div class="row-between"><h4>Phone size</h4><span class="zv" style="color:var(--dim);font-size:12px"></span></div><div class="row-between z"></div></div>
    <div class="pop-row"><h4>Camera</h4><div class="cam"></div></div>
    <div class="pop-row"><h4>Speed</h4><div class="spd"></div></div>
    <div class="pop-row inter-row"><h4>Interaction</h4><div class="inter" style="display:grid;gap:10px"></div></div>
    <div class="pop-row voice-row"><h4>Voice</h4><div class="voice" style="display:grid;gap:10px"></div></div>
    <div class="pop-row skin-row"><h4>Skin</h4><div class="sk"></div></div></div>`);
  const zv = el.querySelector('.zv'); zv.textContent = opts.zoom() + '%';
  const z = slider({ min: 25, max: 300, step: 5, value: opts.zoom(), label: 'Phone size', onInput: v => { opts.setZoom(v); zv.textContent = v + '%'; } });
  z.style.flex = '1';
  const fit = h('<button class="btn sm" data-tip="Fit the phone to the window">Fit</button>');
  fit.onclick = () => { opts.setZoom(100); z.setValue(100); zv.textContent = '100%'; };
  el.querySelector('.z').append(z, fit);
  el.querySelector('.cam').append(segmented({ block: true, value: stage.camMode, onChange: v => { stage.setCameraMode(v); store('camMode', v); },
    options: [{ value: 'screen', label: 'Game screen', tip: 'The fixed 2340×1080 screen the game uses' }, { value: 'rig', label: 'Whole rig', tip: 'Everything the artists drew, including off-screen parts' }] }));
  el.querySelector('.spd').append(segmented({ block: true, value: stage.player?.speed ?? 1, onChange: v => { if (stage.player) stage.player.speed = v; },
    options: [0.25, 0.5, 1, 1.5, 2].map(v => ({ value: v, label: v + '×' })) }));

  const inter = el.querySelector('.inter');
  const hasRestricted = stage.inter && (stage.inter.restrictedSkin || Object.values(stage.inter.acts).some(a => a.restricted || a.specialLoop.length || a.specialOnce.length));
  if (stage.inter?.clicks.length) inter.append(toggle({ label: 'Show tap zones', checked: opts.taps.show, onChange: v => { opts.taps.show = v; } }));
  if (hasRestricted) {
    inter.append(toggle({ label: 'Restricted layer', checked: stage.restricted, onChange: v => { stage.setRestricted(v); store('restricted', String(v)); } }));
    inter.append(h('<div class="hint">The game’s restricted setting: uncensored skin, extra motion and extra tap reactions.</div>'));
  }
  if (!inter.children.length) el.querySelector('.inter-row').remove();

  if (opts.voice) {
    const vs = opts.voice.settings, box = el.querySelector('.voice');
    box.append(toggle({ label: 'Sound', checked: vs.enabled, onChange: v => opts.voice.setEnabled(v) }));
    box.append(segmented({ block: true, value: vs.lang, onChange: v => { vs.lang = v; opts.voice.save(); },
      options: [{ value: 'ja', label: 'Japanese' }, { value: 'zh', label: 'Chinese' }] }));
    const vol = slider({ min: 0, max: 1, step: 0.05, value: vs.volume, label: 'Voice volume', onInput: v => { vs.volume = v; opts.voice.save(); } });
    vol.style.flex = '1';
    const play = h(`<button class="btn sm" data-tip="Play this outfit’s greeting">${icon('mic')}Greeting</button>`);
    play.onclick = () => opts.voice.greet();
    const row = h('<div class="row-between"></div>'); row.append(vol, play);
    box.append(row, toggle({ label: 'Greet when an outfit opens', checked: vs.greet, onChange: v => { vs.greet = v; opts.voice.save(); } }));
  } else el.querySelector('.voice-row').remove();

  const parts = Object.entries(stage.skinParts || {});
  if (parts.length || stage.hasRoom) {
    // Layered rigs (goddess rooms): one choice per part, as the game offers them, plus the room behind her.
    const box = el.querySelector('.sk'); box.style.cssText = 'display:grid;gap:10px';
    for (const [part, choices] of parts) {
      const dd = dropdown({ prefix: part + ':', items: choices.map(c => ({ value: c, label: c.split('/').pop() })), value: stage.partSkin(part), onChange: v => stage.setPart(part, v) });
      dd.style.width = '100%';
      box.append(dd);
    }
    if (stage.hasRoom) box.append(toggle({ label: 'Room background', checked: stage.showRoom, onChange: v => { stage.roomVisible = v; store('showRoom', String(v)); } }));
  } else if (stage.skins.length > 1) {
    const sk = dropdown({ items: stage.skins.map(s => ({ value: s, label: s, hint: s === 'hexie' ? 'censored' : s === 'feihexie' ? 'uncensored' : '' })), value: stage.skin, onChange: v => stage.setSkin(v) });
    sk.style.width = '100%';
    el.querySelector('.sk').append(sk);
  } else el.querySelector('.skin-row').remove();
  return el;
}

/** Animation picker items for a Spine stage: the game's interactive mode first, then every animation. */
export function spineAnimItems(stage) {
  const items = stage.animations.map(a => ({ value: a, label: a, group: stage.interactive ? 'Single animation' : undefined }));
  return stage.interactive ? [{ value: '__interactive', label: 'Interactive', group: 'Game behaviour', hint: stage.inter.clicks.length ? 'tap to react' : '' }, ...items] : items;
}
