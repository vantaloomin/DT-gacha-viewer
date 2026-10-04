// Spine rig playback inside a landscape "phone" screen, the way the game shows it.
// Requires the spine-player IIFE (global `spine`) to be loaded first.
//
// Notes on matching the game:
//  - Hero rigs are authored against a 2340x1080 screen centred on the skeleton origin, so the
//    camera is that rectangle (not the animation's bounds, which jump between animations).
//  - The game plays "birth" first and loops the others; those loops only key what they move, so
//    every other animation starts from birth's final pose.
//  - Animations switch with a hard cut: crossfades blend whole scenes together on multi-scene rigs.

export const SCREEN = { x: -1170, y: -540, w: 2340, h: 1080 };
export const ASPECT = SCREEN.w / SCREEN.h;

// Grow a rect around its centre to the given aspect ratio (so it fits entirely), plus a margin.
export function containRect(b, aspect, margin = 0) {
  let w = b.w * (1 + margin), h = b.h * (1 + margin);
  if (w / h > aspect) h = w / aspect; else w = h * aspect;
  return { x: b.x + b.w / 2 - w / 2, y: b.y + b.h / 2 - h / 2, w, h };
}

/** Sizes a .phone/.screen pair inside a scrolling stage. zoom: 100 = largest that fits. */
export function layoutPhone(stage, phone, screen, zoom, aspect = ASPECT) {
  const cs = getComputedStyle(stage);
  // -4px of slack so rounding never tips the stage into scrolling at 100%
  const availW = stage.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - 4;
  const availH = stage.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom) - 4;
  const bezel = 0.022;   // bezel thickness relative to screen width
  const fitW = Math.max(120, Math.min(availW / (1 + 2 * bezel), availH / (1 / aspect + 2 * bezel)));
  const w = Math.floor(fitW * zoom / 100), h = Math.floor(w / aspect);
  phone.style.setProperty('--bezel', Math.max(6, Math.round(w * bezel)) + 'px');
  Object.assign(screen.style, { width: w + 'px', height: h + 'px' });
}

export class SpineStage {
  /** @param {HTMLElement} screen element the player fills (position:relative, overflow:hidden) */
  constructor(screen) {
    this.screen = screen;
    this.player = null;
    this.rig = null;
    this.anim = null;
    this.camMode = 'screen';
    this.camRect = null;
    this.exportRect = null;
    this.mode = 'manual';        // 'manual' (one animation) or 'interactive' (the game's tap state machine)
    this.inter = null;           // interactions.json entry for the rig
    this.restricted = false;     // the game's restricted layer: uncensored skin, extra motion, restricted acts
    this.onAct = null;           // (actId, animationNames) => void, e.g. to play voice lines
  }

  /**
   * rig: { skel, atlas, pma, skin?, group? }; interaction: optional interactions.json entry.
   * Resolves once loaded. Starts in interactive mode when the rig has a default act.
   */
  load(rig, interaction = null) {
    this.dispose();
    this.rig = rig;
    this.inter = interaction?.defaultAct ? { ...interaction, act: null, elapsed: 0, onceDur: 0 } : null;
    const host = document.createElement('div');
    host.style.cssText = 'position:absolute;inset:0';
    this.screen.append(host);
    this.host = host;
    return new Promise((resolve, reject) => {
      this.player = new spine.SpinePlayer(host, {
        skelUrl: rig.skel, atlasUrl: rig.atlas,
        premultipliedAlpha: !!rig.pma,
        alpha: true,
        backgroundColor: '#000000ff',
        showControls: false,  // the page provides its own playback controls
        showLoading: false,
        defaultMix: 0,
        frame: (p, delta) => { this.#tick(delta); this.#applyCamera(p); },   // every frame, before the camera is positioned
        success: p => { try {
          const data = p.skeleton.data;
          // The game's configured default skin, else the first non-empty one.
          const skin = this.#skinFor(rig) || data.skins.find(s => s.name !== 'default')?.name || 'default';
          p.skeleton.setSkinByName(skin); p.skeleton.setSlotsToSetupPose();
          const first = this.animations.find(a => /idle/i.test(a)) || this.animations[0];
          // play() starts the skeleton's first animation unless config.animation is set, so set it first.
          if (first) p.config.animation = first;
          p.play();
          if (this.inter) this.startInteractive();
          else if (first) this.play(first);
          this.camRect = this.#cameraFor();
          resolve(this);
        } catch (e) { reject(e); } },
        error: (p, e) => reject(new Error(e)),
      });
    });
  }

  get animations() { return this.player?.skeleton?.data.animations.map(a => a.name) || []; }
  get skins() { return this.player?.skeleton?.data.skins.map(s => s.name) || []; }
  get skin() { return this.player?.skeleton?.skin?.name || 'default'; }

  setSkin(name) {
    const s = this.player.skeleton;
    s.setSkinByName(name); s.setSlotsToSetupPose();
    if (this.mode === 'interactive') this.#enterAct(this.inter.act ?? this.inter.defaultAct, true);
    else if (this.anim) this.play(this.anim);
  }

  /** Plays one animation on a loop (leaves interactive mode). */
  play(name) {
    this.mode = 'manual';
    this.anim = name;
    this.#startClean(name);
    this.player.play();
  }

  // ---------- Interactive mode (the game's tap behaviour) ----------
  get interactive() { return !!this.inter; }

  startInteractive() {
    if (!this.inter) return;
    this.mode = 'interactive';
    this.#enterAct(this.inter.defaultAct, true);
    this.player.play();
  }

  /** Restricted layer on/off: switches to the rig's restricted skin and enables special animations. */
  setRestricted(on) {
    this.restricted = on;
    if (!this.player?.skeleton) return;
    const skin = this.#skinFor(this.rig);
    if (skin) { this.player.skeleton.setSkinByName(skin); this.player.skeleton.setSlotsToSetupPose(); }
    if (this.mode === 'interactive') this.#enterAct(this.inter.defaultAct, true);
    else if (this.anim) this.play(this.anim);
  }

  /** Tap zones for the current act, in pixels relative to the screen element. */
  zones() {
    if (this.mode !== 'interactive' || !this.camRect) return [];
    const act = this.inter.acts[this.inter.act], r = this.camRect, W = this.screen.clientWidth, H = this.screen.clientHeight;
    return this.inter.clicks.flatMap(c => c.areas.map(([cx, cy, w, h]) => ({
      id: c.id, enabled: !!act?.cancel.includes(c.id),
      left: (cx - w / 2 - r.x) / r.w * W, top: (1 - (cy + h / 2 - r.y) / r.h) * H, width: w / r.w * W, height: h / r.h * H,
    })));
  }

  /** Handles a tap at screen-element pixel (x, y). Returns true if it triggered a reaction. */
  tap(x, y) {
    const z = this.zones().find(z => z.enabled && x >= z.left && x <= z.left + z.width && y >= z.top && y <= z.top + z.height);
    if (!z) return false;
    this.#enterAct(this.inter.clicks.find(c => c.id === z.id).act);
    if (this.player.paused) this.player.play();
    return true;
  }

  #skinFor(rig) {
    const d = this.player.skeleton.data, i = this.inter;
    const want = this.restricted ? (i?.restrictedSkin || 'feihexie') : (i?.normalSkin || rig.skin);
    return (want && d.findSkin(want)?.name) || (rig.skin && d.findSkin(rig.skin)?.name) || null;   // findSkin('') throws
  }

  #enterAct(id, clean = false, depth = 0, silent = false) {
    const i = this.inter, a = i?.acts[id];
    if (!a || depth > 8) return;
    if (a.restricted && !this.restricted) return a.next && a.next !== id ? this.#enterAct(a.next, clean, depth + 1, silent) : undefined;
    const p = this.player, st = p.animationState, data = p.skeleton.data;
    const entries = [...a.normalLoop.map(e => [...e, true]), ...a.normalOnce.map(e => [...e, false])];
    if (this.restricted) entries.push(...a.specialLoop.map(e => [...e, true]), ...a.specialOnce.map(e => [...e, false]));
    if (clean) this.#startClean(null);
    const used = new Set(), names = [];
    let onceDur = 0;
    for (const [track, name, loop] of entries) {
      const anim = data.findAnimation(name);
      if (used.has(track) || !anim) continue;
      used.add(track); names.push(name);
      const cur = st.getCurrent(track);
      // Keep a loop that's already playing (restarting it would visibly jump)
      if (!(loop && cur && cur.loop && cur.animation === anim)) st.setAnimationWith(track, anim, loop).mixDuration = clean ? 0 : 0.2;
      if (!loop) onceDur = Math.max(onceDur, anim.duration);
      if (track === 0) this.anim = name;
    }
    for (const track of [1, 2]) if (!used.has(track) && st.getCurrent(track)) st.setEmptyAnimation(track, clean ? 0 : 0.2);
    Object.assign(i, { act: id, elapsed: 0, onceDur });
    if (!silent) this.onAct?.(id, names);
  }

  // Puts the live skeleton back after a helper posed it for measuring.
  #restore() {
    if (this.mode === 'interactive') this.#enterAct(this.inter.act ?? this.inter.defaultAct, true, 0, true);
    else if (this.anim) this.#startClean(this.anim);
  }

  #tick(delta) {
    if (this.mode !== 'interactive' || !this.inter?.act || !delta) return;
    const i = this.inter, a = i.acts[i.act];
    i.elapsed += delta;
    if (a?.next && i.elapsed >= Math.max(i.onceDur, a.minSwitch)) this.#enterAct(a.next);
  }

  get paused() { return this.player?.paused; }
  get time() {
    const e = this.player?.animationState.getCurrent(0);
    const d = e?.animation.duration || 0;
    return d ? e.trackTime % d : 0;
  }
  seek(t) {
    const p = this.player, e = p?.animationState.getCurrent(0);
    if (!e) return;
    e.trackTime = Math.max(0, t);
    p.animationState.apply(p.skeleton); p.skeleton.updateWorldTransform();
  }
  pause() { this.player?.pause(); }
  resume() { this.player?.play(); }

  setCameraMode(mode) { this.camMode = mode; if (this.player?.skeleton) this.camRect = this.#cameraFor(); }

  duration(name = this.anim) { return this.player.skeleton.data.findAnimation(name)?.duration || 0; }

  /**
   * Prepares deterministic rendering for export. framing: 'phone' (what the screen shows) or
   * 'tight' (everything the animation draws). Returns { width, height, frameCount, drawFrame, done }.
   * For a still (frameCount 1, still: true) the current pose is captured instead.
   */
  beginCapture({ framing = 'phone', longEdge = 1024, fps = 30, still = false }) {
    const p = this.player, renderer = p.sceneRenderer, canvas = p.canvas;
    if (framing === 'tight') {
      const b = this.#animBounds(this.anim), pad = 0.03;
      this.exportRect = { x: b.x - b.w * pad, y: b.y - b.h * pad, w: b.w * (1 + 2 * pad), h: b.h * (1 + 2 * pad) };
    } else {
      this.exportRect = { ...this.camRect };
    }
    const r = this.exportRect;
    let W, H;
    if (r.w >= r.h) { W = longEdge; H = Math.round(longEdge * r.h / r.w); } else { H = longEdge; W = Math.round(longEdge * r.w / r.h); }
    W += W & 1; H += H & 1;
    const saved = { resize: renderer.resize, bg: [p.bg.r, p.bg.g, p.bg.b, p.bg.a], paused: p.paused };
    // Take over rendering: fixed canvas size, transparent clear, no RAF loop.
    p.pause(); p.stopRequestAnimationFrame = true;
    renderer.resize = function () {
      if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
      this.context.gl.viewport(0, 0, W, H); this.camera.setViewport(W, H); this.camera.update();
    };
    p.bg.set(0, 0, 0, 0);
    if (!still) this.#startClean(this.anim);
    const state = p.animationState, skel = p.skeleton;
    return {
      width: W, height: H,
      frameCount: still ? 1 : Math.max(1, Math.round(this.duration() * fps)),
      drawFrame: (i, ctx) => {
        if (!still) {
          state.update(i === 0 ? 0 : 1 / fps);
          state.apply(skel); skel.updateWorldTransform();
        }
        p.drawFrame(false);               // render into the WebGL canvas…
        ctx.drawImage(canvas, 0, 0);      // …and copy before the browser presents/clears it
      },
      done: () => {
        this.exportRect = null;
        renderer.resize = saved.resize; p.bg.set(...saved.bg);
        p.stopRequestAnimationFrame = false;
        if (!still) { if (this.mode === 'interactive') this.#enterAct(this.inter.defaultAct, true); else this.#startClean(this.anim); }
        if (saved.paused) p.pause(); else p.play();
        p.drawFrame();
      },
    };
  }

  dispose() {
    if (this.player) { this.player.dispose(); this.player = null; }
    this.host?.remove(); this.host = null;
    this.camRect = null; this.anim = null;
  }

  // Hard cut to an animation, starting from birth's final pose (see notes at the top).
  #startClean(name) {
    const p = this.player, state = p.animationState, skel = p.skeleton, birth = skel.data.findAnimation('birth');
    state.clearTracks();
    skel.setToSetupPose();
    if (birth && name !== 'birth')
      birth.apply(skel, birth.duration, birth.duration, false, [], 1, spine.MixBlend.setup, spine.MixDirection.mixIn);
    if (name) state.setAnimation(0, name, true).mixDuration = 0;
    p.playTime = 0;
  }

  #cameraFor() {
    const d = this.player.skeleton.data;
    const authoredForScreen = this.rig.group === 'spine/hero' ||
      (Math.abs(d.width - SCREEN.w) < 4 && Math.abs(d.height - SCREEN.h) < 4 && Math.abs(d.x - SCREEN.x) < 4 && Math.abs(d.y - SCREEN.y) < 4);
    if (this.camMode === 'screen' && authoredForScreen) return { ...SCREEN };
    let b = d.width > 0 && d.height > 0 ? { x: d.x, y: d.y, w: d.width, h: d.height } : null;
    if (!b) {
      const s = this.player.skeleton, o = new spine.Vector2(), z = new spine.Vector2();
      s.setToSetupPose(); s.updateWorldTransform(); s.getBounds(o, z, []);
      b = { x: o.x, y: o.y, w: z.x, h: z.y };
      this.#restore();
    }
    return containRect(b, ASPECT, 0.06);
  }

  #applyCamera(p) {
    const r = this.exportRect || this.camRect;
    if (!r) return;
    p.currentViewport = { x: r.x, y: r.y, width: r.w, height: r.h, padLeft: 0, padRight: 0, padTop: 0, padBottom: 0 };
    p.previousViewport = null;   // no animated viewport transitions
  }

  // Everything an animation draws over its duration, starting from the same pose #startClean uses.
  #animBounds(name) {
    const skel = this.player.skeleton, anim = skel.data.findAnimation(name), birth = skel.data.findAnimation('birth');
    const o = new spine.Vector2(), z = new spine.Vector2(), steps = 60;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (let i = 0; i < steps; i++) {
      const t = anim.duration * i / steps;
      skel.setToSetupPose();
      if (birth && anim !== birth) birth.apply(skel, birth.duration, birth.duration, false, [], 1, spine.MixBlend.setup, spine.MixDirection.mixIn);
      anim.apply(skel, t, t, false, [], 1, spine.MixBlend.setup, spine.MixDirection.mixIn);
      skel.updateWorldTransform(); skel.getBounds(o, z, []);
      if (!isFinite(o.x) || !isFinite(z.x)) continue;
      x0 = Math.min(x0, o.x); y0 = Math.min(y0, o.y); x1 = Math.max(x1, o.x + z.x); y1 = Math.max(y1, o.y + z.y);
    }
    this.#restore();
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }
}
