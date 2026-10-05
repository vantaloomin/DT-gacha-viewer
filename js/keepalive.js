// Keeps the local gallery server (_tools/serve.py) running while a gallery page is open: the server
// stops by itself about a minute and a half after the last page stops pinging.
const PING = '/__ping', EVERY = 20000;
let warned = false;

async function ping() {
  try {
    const r = await fetch(PING, { cache: 'no-store' });
    if (r.status === 404) return false;   // served by something else (no keep-alive needed): stop pinging
    warned = false;
  } catch {
    // The server has stopped (e.g. the tab sat discarded in the background). Say so once.
    if (!warned) {
      warned = true;
      import('./ui.js').then(({ toast }) => toast('The gallery server has stopped', { type: 'error', duration: 0,
        message: 'Run “Open Gallery.bat” again to restart it, then refresh this page.' })).catch(() => {});
    }
  }
  return true;
}

export function keepAlive() {
  if (location.protocol === 'file:') return;
  ping().then(go => { if (go) setInterval(ping, EVERY); });
  addEventListener('visibilitychange', () => document.visibilityState === 'visible' && ping());
}
