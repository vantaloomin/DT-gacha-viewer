// Frame-by-frame exporters shared by the Spine and 3D views.
//
// exportAnimation() asks the caller to draw each frame (deterministically, frame i of n) into a
// 2D canvas, then encodes the frames as animated WebP, GIF, WebM (VP9) or a zip of PNGs.
// exportStill() does the same for a single frame as a PNG.

// Yield to the event loop between frames. MessageChannel isn't throttled in background tabs like setTimeout is.
export const nextTask = () => new Promise(r => { const ch = new MessageChannel(); ch.port1.onmessage = () => r(); ch.port2.postMessage(0); });
const toBlob = (c, type, q) => new Promise(r => c.toBlob(r, type, q));

export const FORMATS = {
  webp: { label: 'WebP', ext: 'webp', hint: 'Animated image · full colour, soft transparency', quality: true },
  webm: { label: 'WebM', ext: 'webm', hint: 'Video · smallest files, plays anywhere video does', quality: true },
  gif: { label: 'GIF', ext: 'gif', hint: 'Most compatible · 256 colours, hard-edged transparency' },
  png: { label: 'PNG frames', ext: 'zip', hint: 'Zip of lossless frames · for editing or ffmpeg' },
};

export function safeFilename(s) {
  return String(s).replace(/[\\/:*?"<>|]+/g, '').replace(/\s+/g, ' ').trim();
}

export function download(blob, filename) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 30000);
}

/**
 * @param {object} o
 * @param {'webp'|'webm'|'gif'|'png'} o.format
 * @param {number} o.width  @param {number} o.height (rounded to even)
 * @param {number} o.fps    @param {number} o.frameCount
 * @param {number} [o.quality=0.9]  0..1 (WebP quality / WebM bitrate scale)
 * @param {string} [o.background]   CSS colour, or '' for transparent
 * @param {(i:number, ctx:CanvasRenderingContext2D) => void|Promise<void>} o.drawFrame
 * @param {(done:number, total:number) => void} [o.onProgress]
 * @param {AbortSignal} [o.signal]  cancels the export (rejects with an AbortError)
 * @returns {Promise<{blob: Blob, ext: string, alphaLost?: boolean}>}
 */
export async function exportAnimation(o) {
  const W = o.width + (o.width & 1), H = o.height + (o.height & 1);
  const canvas = document.createElement('canvas'); canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d', { willReadFrequently: o.format === 'gif' });
  const enc = await makeEncoder(o.format, W, H, o.fps, o.quality ?? 0.9, !o.background, o.frameCount);
  try {
    for (let i = 0; i < o.frameCount; i++) {
      if (o.signal?.aborted) throw new DOMException('Export cancelled', 'AbortError');
      ctx.clearRect(0, 0, W, H);
      if (o.background) { ctx.fillStyle = o.background; ctx.fillRect(0, 0, W, H); }
      await o.drawFrame(i, ctx, W, H);
      await enc.add(canvas, i);
      o.onProgress?.(i + 1, o.frameCount);
      await nextTask();
    }
    return { blob: await enc.finish(), ext: enc.ext, alphaLost: !!enc.alphaLost };
  } catch (e) {
    enc.cancel?.();
    throw e;
  }
}

export async function exportStill({ width, height, background, drawFrame }) {
  const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (background) { ctx.fillStyle = background; ctx.fillRect(0, 0, width, height); }
  await drawFrame(0, ctx, width, height);
  return toBlob(canvas, 'image/png');
}

async function makeEncoder(fmt, W, H, fps, quality, transparent, frameCount) {
  // Per-frame durations that add up exactly (avoids drift from rounding 1000/fps).
  const dur = (i, unit) => Math.round((i + 1) * 1000 / fps / unit) * unit - Math.round(i * 1000 / fps / unit) * unit;

  if (fmt === 'png') {
    if (!window.JSZip) await loadScript(new URL('../vendor/jszip.min.js', import.meta.url).href);
    const zip = new JSZip();
    return {
      ext: 'zip',
      add: async (c, i) => zip.file(`frame_${String(i).padStart(4, '0')}.png`, await toBlob(c, 'image/png')),
      finish: () => zip.generateAsync({ type: 'blob', compression: 'STORE' }),
    };
  }

  if (fmt === 'gif') {
    const { GIFEncoder, quantize, applyPalette } = await import('../vendor/gifenc.esm.js');
    const gif = GIFEncoder();
    return {
      ext: 'gif',
      add: async (c, i) => {
        const { data } = c.getContext('2d').getImageData(0, 0, W, H);
        const palette = quantize(data, 256, transparent ? { format: 'rgba4444', oneBitAlpha: true } : {});
        const index = applyPalette(data, palette, transparent ? 'rgba4444' : 'rgb565');
        const ti = transparent ? palette.findIndex(p => p[3] === 0) : -1;
        gif.writeFrame(index, W, H, { palette, delay: dur(i, 10), transparent: ti >= 0, transparentIndex: Math.max(ti, 0), dispose: transparent ? 2 : -1 });
      },
      finish: () => { gif.finish(); return new Blob([gif.bytes()], { type: 'image/gif' }); },
    };
  }

  if (fmt === 'webm') return makeWebmEncoder(W, H, fps, quality, transparent, frameCount);

  // Animated WebP: encode each frame with the browser's WebP encoder, then mux into ANMF chunks.
  const frames = [];
  return {
    ext: 'webp',
    add: async (c, i) => {
      const buf = new Uint8Array(await (await toBlob(c, 'image/webp', quality)).arrayBuffer());
      frames.push({ chunks: webpImageChunks(buf), duration: dur(i, 1) });
    },
    finish: () => muxAnimatedWebP(frames, W, H),
  };
}

// WebM: WebCodecs VP9 encoder + webm-muxer. Keeps transparency when the browser's encoder supports alpha.
async function makeWebmEncoder(W, H, fps, quality, transparent, frameCount) {
  if (!('VideoEncoder' in window)) throw new Error('This browser has no WebCodecs VideoEncoder (use Chrome or Edge).');
  const { Muxer, ArrayBufferTarget } = await import('../vendor/webm-muxer.mjs');
  const base = { codec: 'vp09.00.40.08', width: W, height: H, framerate: fps,
                 bitrate: Math.round(W * H * fps * 0.25 * (0.4 + quality)), latencyMode: 'quality' };
  let config = { ...base, alpha: transparent ? 'keep' : 'discard' };
  let alpha = transparent;
  if (transparent && !(await VideoEncoder.isConfigSupported(config)).supported) { config = { ...base, alpha: 'discard' }; alpha = false; }
  if (!(await VideoEncoder.isConfigSupported(config)).supported) throw new Error('VP9 encoding is not supported by this browser.');
  const target = new ArrayBufferTarget();
  const muxer = new Muxer({ target, video: { codec: 'V_VP9', width: W, height: H, frameRate: fps, alpha } });
  let error = null;
  const encoder = new VideoEncoder({ output: (chunk, meta) => muxer.addVideoChunk(chunk, meta), error: e => { error = e; } });
  encoder.configure(config);
  return {
    ext: 'webm',
    alphaLost: transparent && !alpha,
    add: async (c, i) => {
      if (error) throw error;
      const frame = new VideoFrame(c, { timestamp: Math.round(i * 1e6 / fps), duration: Math.round(1e6 / fps) });
      encoder.encode(frame, { keyFrame: i % Math.max(1, Math.round(fps * 2)) === 0 });
      frame.close();
      while (encoder.encodeQueueSize > 4) await new Promise(r => setTimeout(r, 1));
    },
    cancel: () => { try { encoder.close(); } catch {} },
    finish: async () => {
      await encoder.flush(); encoder.close();
      if (error) throw error;
      muxer.finalize();
      return new Blob([target.buffer], { type: 'video/webm' });
    },
  };
}

export function loadScript(src) {
  return new Promise((res, rej) => { const s = document.createElement('script'); s.src = src; s.onload = res; s.onerror = () => rej(new Error('Could not load ' + src)); document.head.append(s); });
}

// Returns the raw ALPH/VP8/VP8L chunks (header+payload+padding) from a still WebP file.
function webpImageChunks(buf) {
  const dv = new DataView(buf.buffer), parts = [];
  for (let off = 12; off + 8 <= buf.length;) {
    const id = String.fromCharCode(...buf.subarray(off, off + 4)), size = dv.getUint32(off + 4, true);
    const end = off + 8 + size + (size & 1);
    if (id === 'ALPH' || id === 'VP8 ' || id === 'VP8L') parts.push(buf.subarray(off, end));
    off = end;
  }
  return parts;
}

function muxAnimatedWebP(frames, W, H) {
  const u24 = v => [v & 255, (v >> 8) & 255, (v >> 16) & 255];
  const u32 = v => [v & 255, (v >> 8) & 255, (v >> 16) & 255, (v >>> 24) & 255];
  const chunk = (id, payload) => {
    const out = new Uint8Array(8 + payload.length + (payload.length & 1));
    out.set([...id].map(c => c.charCodeAt(0)), 0); out.set(u32(payload.length), 4); out.set(payload, 8);
    return out;
  };
  const concat = arrs => { const o = new Uint8Array(arrs.reduce((s, a) => s + a.length, 0)); let k = 0; for (const a of arrs) { o.set(a, k); k += a.length; } return o; };
  const vp8x = chunk('VP8X', new Uint8Array([0x12, 0, 0, 0, ...u24(W - 1), ...u24(H - 1)])); // alpha + animation flags
  const anim = chunk('ANIM', new Uint8Array([0, 0, 0, 0, 0, 0]));                          // transparent bg, loop forever
  const anmf = frames.map(f => chunk('ANMF', concat([
    new Uint8Array([0, 0, 0, 0, 0, 0, ...u24(W - 1), ...u24(H - 1), ...u24(f.duration), 0x02]), // x,y,w,h,duration, no-blend
    ...f.chunks,
  ])));
  const body = concat([new Uint8Array([87, 69, 66, 80]), vp8x, anim, ...anmf]); // "WEBP"
  return new Blob([new Uint8Array([82, 73, 70, 70, ...u32(body.length)]), body], { type: 'image/webp' }); // "RIFF"
}
