// Voice-line playback for the game's cue ids (see _tools/build_interactions.py and audio/audio.json).
import { recall, store } from './ui.js';

export const voiceSettings = {
  enabled: recall('soundOn', 'false') === 'true',  // sound is off until the user turns it on
  lang: recall('voiceLang', 'ja') === 'zh' ? 'zh' : 'ja',
  volume: +recall('voiceVolume', 0.9),
  greet: recall('voiceGreet', 'true') === 'true',  // play the outfit's greeting when it opens
};
export function saveVoiceSettings() {
  store('soundOn', String(voiceSettings.enabled)); store('voiceLang', voiceSettings.lang); store('voiceVolume', String(voiceSettings.volume)); store('voiceGreet', String(voiceSettings.greet));
}

let index = null, multi = {}, pending = null, current = null;
async function cueIndex() {
  if (index) return index;
  pending ||= fetch('audio/audio.json', { cache: 'no-cache' }).then(r => r.ok ? r.json() : {}).catch(() => ({}));
  const data = await pending;
  index = data.cueIndex || {};
  multi = data.multiCues || {};   // cues that play one of several takes
  return index;
}

/** Resolves a voice entry ({ id, ja, zh, tw }) to an audio file for the chosen language, or null. */
export async function voiceFile(v, lang = voiceSettings.lang) {
  if (!v) return null;
  const idx = await cueIndex();
  const order = lang === 'zh' ? ['zh', 'id', 'tw', 'ja'] : ['ja', 'tw', 'zh', 'id'];
  for (const k of order) {
    const name = v[k];
    if (name && idx[name]) return idx[name];
    if (name && multi[name]?.length) return multi[name][Math.floor(Math.random() * multi[name].length)];
  }
  return null;
}

export async function playVoice(v, { force = false } = {}) {
  if (!voiceSettings.enabled && !force) return false;
  const file = await voiceFile(v);
  if (!file) return false;
  stopVoice();
  current = new Audio(file);
  current.volume = voiceSettings.volume;
  try { await current.play(); return true; } catch { return false; }   // autoplay may be blocked before the first click
}

export function stopVoice() { if (current) { current.pause(); current = null; } }
export function setSoundEnabled(on) { voiceSettings.enabled = on; saveVoiceSettings(); if (!on) stopVoice(); }
export const audioAvailable = async () => Object.keys(await cueIndex()).length > 0;
