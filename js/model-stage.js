// 3D battle-model viewer (three.js) for the .glb files written by _tools/export_models.py.
// Needs an import map providing "three" and "three/addons/".
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

export class ModelStage {
  /** @param {HTMLElement} container element the canvas fills */
  constructor(container) {
    this.container = container;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.append(this.renderer.domElement);
    Object.assign(this.renderer.domElement.style, { width: '100%', height: '100%', display: 'block' });

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(30, 1, 0.01, 1000);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.userMoved = false;   // refit on resize until the user orbits/zooms
    this.controls.addEventListener('start', () => { this.userMoved = true; });

    this.hemi = new THREE.HemisphereLight(0xffffff, 0x8a8aa0, 1.6);
    this.sun = new THREE.DirectionalLight(0xffffff, 1.8);
    this.sun.position.set(2, 4, 3);
    this.scene.add(this.hemi, this.sun);

    this.clock = new THREE.Clock();
    this.mixer = null; this.action = null; this.model = null; this.clips = [];
    this.speed = 1; this.paused = false; this.lighting = 'lit';
    this.loop = true; this.ended = false;   // loop off: stop on the last frame (ended) instead of repeating
    this.backdrop = null;   // null (plain colour), { image } (a painted backdrop) or { floor } (a battlefield floor)
    this.backdropTex = null; this.floor = null;
    this.setBackground('#1d1d23');

    new ResizeObserver(() => this.#resize()).observe(container);
    this.#resize();
    this.renderer.setAnimationLoop(() => this.#tick());
  }

  async load(url) {
    this.#clear();
    const gltf = await new GLTFLoader().loadAsync(url);
    this.model = gltf.scene;
    this.clips = gltf.animations;
    this.model.traverse(o => {
      if (o.isMesh) {
        o.frustumCulled = false;   // skinned bounds don't follow the animation
        o.userData.original = o.material;
      }
    });
    this.scene.add(this.model);
    this.mixer = new THREE.AnimationMixer(this.model);
    this.setLighting(this.lighting);
    const first = this.clips.find(c => /idle_normal/.test(c.name)) || this.clips.find(c => /idle/.test(c.name)) || this.clips[0];
    if (first) this.play(first.name);
    this.mixer.update(0);
    this.#applyBackdrop();   // a battlefield floor is sized and placed for this model
    this.frame();
    return this;
  }

  get clipNames() { return this.clips.map(c => c.name); }
  get clipName() { return this.action?.getClip().name; }

  play(name) {
    const clip = this.clips.find(c => c.name === name);
    if (!clip) return;
    this.mixer.stopAllAction();
    this.action = this.mixer.clipAction(clip);
    this.action.reset().setLoop(THREE.LoopRepeat, Infinity).play();
    this.ended = false;
  }
  duration(name = this.clipName) { return this.clips.find(c => c.name === name)?.duration || 0; }

  get time() { const d = this.duration(); return this.action && d ? this.action.time % d : 0; }
  seek(t) { if (!this.action) return; this.action.time = Math.max(0, t); this.ended = false; this.mixer.update(0); }
  pause() { this.paused = true; }
  resume() {
    if (this.ended && this.action) { this.action.time = 0; this.ended = false; }   // play again from the start
    this.paused = false; this.clock.getDelta();
  }

  setBackground(color) {
    this.background = color;
    this.#applyBackdrop();
  }

  /**
   * Scenery: { image: url } shows a picture behind the model (fills the view, cropped like CSS "cover");
   * { floor: url } stands the model on a top-down battlefield capture, fading into the background colour.
   * null: just the background colour.
   */
  async setBackdrop(backdrop) {
    this.backdrop = backdrop;
    const url = backdrop?.image || backdrop?.floor;
    this.backdropTex?.dispose(); this.backdropTex = null;
    if (url) {
      const tex = await new THREE.TextureLoader().loadAsync(url).catch(() => null);
      if (this.backdrop !== backdrop) { tex?.dispose(); return; }   // changed again while loading
      if (tex) { tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8; this.backdropTex = tex; }
    }
    this.#applyBackdrop();
    this.frame();
  }

  #applyBackdrop() {
    const color = this.background ? new THREE.Color(this.background) : null, tex = this.backdropTex;
    if (this.floor) { this.scene.remove(this.floor); this.floor.geometry.dispose(); this.floor.material.dispose(); this.floor = null; }
    this.scene.fog = null;
    if (tex && this.backdrop?.image) {
      this.scene.background = tex;
      this.#coverBackground();
    } else {
      this.scene.background = color;
      if (tex && this.backdrop?.floor && this.model) {
        const box = this.#modelBox(), size = box.getSize(new THREE.Vector3()), centre = box.getCenter(new THREE.Vector3());
        const w = Math.max(size.y, 0.5) * 18, h = w * tex.image.height / tex.image.width;   // roughly a battle arena's scale
        this.floor = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex }));
        this.floor.rotation.x = -Math.PI / 2;
        this.floor.position.set(centre.x, box.min.y - 0.002, centre.z);
        this.scene.add(this.floor);
        if (color) this.scene.fog = new THREE.Fog(color, w * 0.18, w * 0.5);   // fade the arena's far edges
      }
    }
  }

  // Crop a background picture to the canvas shape instead of stretching it.
  #coverBackground() {
    const tex = this.scene.background;
    if (!tex?.isTexture || !tex.image) return;
    const c = this.renderer.domElement, canvas = c.width / c.height, img = tex.image.width / tex.image.height;
    tex.matrixAutoUpdate = true;
    if (canvas > img) { tex.repeat.set(1, img / canvas); tex.offset.set(0, (1 - img / canvas) / 2); }
    else { tex.repeat.set(canvas / img, 1); tex.offset.set((1 - canvas / img) / 2, 0); }
  }

  #modelBox() {
    this.model.updateMatrixWorld(true);
    const box = new THREE.Box3();
    this.model.traverse(o => { if (o.isSkinnedMesh) { o.computeBoundingBox?.(); box.union(o.boundingBox.clone().applyMatrix4(o.matrixWorld)); } });
    if (box.isEmpty()) box.setFromObject(this.model);
    return box;
  }

  // 'lit' (the model's own material under lights), 'toon' (cel-shaded), 'unlit' (flat texture colour).
  setLighting(mode) {
    this.lighting = mode;
    this.model?.traverse(o => {
      if (!o.isMesh) return;
      const orig = o.userData.original;
      const params = { map: orig.map, transparent: orig.transparent, alphaTest: orig.alphaTest, side: orig.side };
      o.material = mode === 'lit' ? orig
        : mode === 'toon' ? (o.userData.toon ||= new THREE.MeshToonMaterial({ ...params, gradientMap: toonRamp() }))
        : (o.userData.unlit ||= new THREE.MeshBasicMaterial(params));
    });
  }

  /** Points the camera at the whole model from the front. */
  frame() {
    if (!this.model) return;
    this.userMoved = false;
    const box = this.#modelBox();
    const size = box.getSize(new THREE.Vector3()), centre = box.getCenter(new THREE.Vector3());
    const fov = THREE.MathUtils.degToRad(this.camera.fov);
    const dist = Math.max(size.y, size.x / this.camera.aspect) / 2 / Math.tan(fov / 2) * 1.35;
    // glTF faces +Z; the converted Unity models face the camera from +Z too.
    // On a battlefield, look down a little so the ground reads as ground
    const lift = this.floor ? dist * 0.35 : size.y * 0.05;
    this.camera.position.set(centre.x, centre.y + lift, centre.z + Math.sqrt(dist * dist - (this.floor ? lift * lift : 0)));
    this.camera.near = dist / 100; this.camera.far = dist * 100; this.camera.updateProjectionMatrix();
    this.controls.target.copy(centre);
    this.controls.update();
  }

  /**
   * Deterministic rendering for export, from the current camera view.
   * turntable: rotate the model a full turn over the export.
   */
  beginCapture({ longEdge = 1024, fps = 30, still = false, turntable = false, turntableSeconds = 6 }) {
    const r = this.renderer, cam = this.camera, size = r.getSize(new THREE.Vector2());
    const aspect = size.x / size.y;
    let W, H;
    if (aspect >= 1) { W = longEdge; H = Math.round(longEdge / aspect); } else { H = longEdge; W = Math.round(longEdge * aspect); }
    W += W & 1; H += H & 1;
    const saved = { pixelRatio: r.getPixelRatio(), size, bg: this.scene.background, fog: this.scene.fog, rot: this.model?.rotation.y || 0, time: this.action?.time || 0, paused: this.paused };
    this.paused = true;
    r.setPixelRatio(1); r.setSize(W, H, false);
    this.#coverBackground();
    cam.aspect = W / H; cam.updateProjectionMatrix();
    const clipDur = this.duration();
    const seconds = turntable ? Math.max(turntableSeconds, clipDur) : clipDur;
    const frameCount = still ? 1 : Math.max(1, Math.round(seconds * fps));
    return {
      width: W, height: H, frameCount,
      drawFrame: (i, ctx, w, h, transparent) => {
        if (!still) {
          if (this.action) { this.action.time = clipDur ? (i / fps) % clipDur : 0; this.mixer.update(0); }
          if (turntable && this.model) this.model.rotation.y = saved.rot + 2 * Math.PI * i / frameCount;
        }
        r.render(this.scene, cam);
        ctx.drawImage(r.domElement, 0, 0);
      },
      setTransparent: on => {   // a transparent export leaves out all scenery
        this.scene.background = on ? null : saved.bg;
        if (this.floor) this.floor.visible = !on;
        this.scene.fog = on ? null : saved.fog;
        if (!on) this.#coverBackground();
      },
      done: () => {
        r.setPixelRatio(saved.pixelRatio); r.setSize(saved.size.x, saved.size.y, false);
        cam.aspect = saved.size.x / saved.size.y; cam.updateProjectionMatrix();
        this.scene.background = saved.bg; this.scene.fog = saved.fog;
        if (this.floor) this.floor.visible = true;
        this.#coverBackground();
        if (this.model) this.model.rotation.y = saved.rot;
        if (this.action) { this.action.time = saved.time; this.mixer.update(0); }
        this.paused = saved.paused;
      },
    };
  }

  dispose() {
    this.#clear();
    this.renderer.setAnimationLoop(null);
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }

  #clear() {
    if (this.model) {
      this.scene.remove(this.model);
      this.model.traverse(o => {
        if (!o.isMesh) return;
        o.geometry.dispose();
        for (const m of [o.userData.original, o.userData.toon, o.userData.unlit]) { m?.map?.dispose(); m?.dispose(); }
      });
    }
    this.model = null; this.mixer = null; this.action = null; this.clips = [];
  }

  #resize() {
    const w = this.container.clientWidth || 1, h = this.container.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
    this.#coverBackground();
    if (!this.userMoved) this.frame();
  }

  #tick() {
    const dt = this.clock.getDelta();
    if (this.mixer && !this.paused) {
      const step = dt * this.speed, d = this.duration();
      if (!this.loop && this.action && d && this.action.time + step >= d) {
        this.action.time = d - 1e-4; this.mixer.update(0);   // hold the last frame
        this.paused = true; this.ended = true;
      } else this.mixer.update(step);
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}

let ramp;
function toonRamp() {
  if (ramp) return ramp;
  const data = new Uint8Array([90, 90, 90, 255, 200, 200, 200, 255, 255, 255, 255, 255]);
  ramp = new THREE.DataTexture(data, 3, 1, THREE.RGBAFormat);
  ramp.minFilter = ramp.magFilter = THREE.NearestFilter;
  ramp.needsUpdate = true;
  return ramp;
}
