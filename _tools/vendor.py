"""Downloads pinned copies of the gallery's third-party libraries into extracted/vendor so the
pages work offline. Re-run to refresh (files already present are kept unless --force).

JavaScript modules are scanned for relative imports (e.g. GLTFLoader -> ../utils/BufferGeometryUtils.js)
and those are fetched too, preserving the directory layout so the imports resolve.
"""
import os, re, sys, urllib.request
from urllib.parse import urljoin

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(ROOT, 'vendor')
CDN = 'https://cdn.jsdelivr.net/npm/'
FORCE = '--force' in sys.argv

# (url, local path under vendor/, follow relative module imports?)
FILES = [
    (CDN + '@esotericsoftware/spine-player@4.1.56/dist/iife/spine-player.js', 'spine-player.js', False),
    (CDN + 'three@0.170.0/build/three.module.js', 'three/three.module.js', True),
    (CDN + 'three@0.170.0/examples/jsm/loaders/GLTFLoader.js', 'three/addons/loaders/GLTFLoader.js', True),
    (CDN + 'three@0.170.0/examples/jsm/controls/OrbitControls.js', 'three/addons/controls/OrbitControls.js', True),
    (CDN + 'gifenc@1.0.3/dist/gifenc.esm.js', 'gifenc.esm.js', False),
    (CDN + 'webm-muxer@5.0.3/build/webm-muxer.mjs', 'webm-muxer.mjs', False),
    (CDN + 'jszip@3.10.1/dist/jszip.min.js', 'jszip.min.js', False),
]
FONT_WEIGHTS = [400, 500, 600, 700]
FONT_URL = CDN + '@fontsource/inter@5.1.0/files/inter-latin-{w}-normal.woff2'

IMPORT_RE = re.compile(r'''(?:import|export)\s[^'"]*?from\s*['"](\.{1,2}/[^'"]+)['"]|import\s*\(\s*['"](\.{1,2}/[^'"]+)['"]\s*\)''')


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (vendor.py)'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def save(rel, data):
    path = os.path.join(VENDOR, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    print(f'  {rel} ({len(data) // 1024} KB)')


def get(url, rel, follow, seen):
    if rel in seen:
        return
    seen.add(rel)
    path = os.path.join(VENDOR, rel)
    if os.path.exists(path) and not FORCE:
        data = open(path, 'rb').read()
    else:
        data = fetch(url)
        save(rel, data)
    if follow:
        for m in IMPORT_RE.finditer(data.decode('utf-8', 'replace')):
            spec = m.group(1) or m.group(2)
            get(urljoin(url, spec), os.path.normpath(os.path.join(os.path.dirname(rel), spec)).replace(os.sep, '/'), True, seen)


def main():
    print('Vendoring libraries into', VENDOR)
    seen = set()
    for url, rel, follow in FILES:
        get(url, rel, follow, seen)
    css = []
    for w in FONT_WEIGHTS:
        rel = f'fonts/inter-latin-{w}.woff2'
        if FORCE or not os.path.exists(os.path.join(VENDOR, rel)):
            save(rel, fetch(FONT_URL.format(w=w)))
        css.append(f"@font-face {{ font-family: 'Inter'; font-style: normal; font-weight: {w}; font-display: swap; src: url('fonts/inter-latin-{w}.woff2') format('woff2'); }}")
    with open(os.path.join(VENDOR, 'inter.css'), 'w') as f:
        f.write('\n'.join(css) + '\n')
    print('Done:', len(seen), 'scripts +', len(FONT_WEIGHTS), 'font files')


if __name__ == '__main__':
    main()
