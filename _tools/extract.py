import json, os, sys
from multiprocessing import Pool
from dtunpack import load
from config import ROOT as OUT
PREFIXES = {
    'assets/res/model/common/spinemodel/': 'spine/',
    'assets/res/model/pc/spinemodel/': 'spine_pc/',
    'assets/res/gui/bigimage/hero/': 'images/hero/',
    'assets/res/gui/bigimage/herobg/': 'images/herobg/',
    'assets/res/gui/bigimage/herocard/': 'images/herocard/',
    'assets/res/gui/bigimage/herogacha/': 'images/herogacha/',
    'assets/res/gui/texture/icon/heroicon/': 'images/heroicon/',
    'assets/res/gui/bigimage/cardicon/': 'images/cardicon/',
}
# Optional command-line filter: only extract outputs under these prefixes, e.g. `python extract.py images/heroicon/`
ONLY = [a for a in sys.argv[1:] if not a.startswith('--')]
FULL = '--full' in sys.argv   # ignore extract_state.json and re-extract everything
def target(c):
    for p, d in PREFIXES.items():
        if c.startswith(p):
            t = d + c[len(p):]
            return t if not ONLY or any(t.startswith(o) for o in ONLY) else None
def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'wb').write(data)
def work(job):
    path, wanted = job
    env = load(path); n = 0
    for c, ptr in env.container.items():
        t = target(c)
        if not t or c not in wanted: continue
        obj = ptr.deref() if hasattr(ptr, 'deref') else ptr
        name = obj.type.name
        dest = os.path.join(OUT, t)
        if name in ('Texture2D', 'Sprite'):
            img = obj.read().image
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            img.save(os.path.splitext(dest)[0] + '.png'); n += 1
        elif name == 'MonoBehaviour':  # Spine SkeletonData / Atlas asset -> pull referenced TextAsset
            tt = obj.read_typetree()
            ref = tt.get('skeletonJSON') or tt.get('atlasFile')
            if not ref: continue
            for o in env.objects:
                if o.path_id == ref['m_PathID']:
                    ta = o.read(); s = ta.m_Script
                    b = s.encode('utf-8', 'surrogateescape') if isinstance(s, str) else bytes(s)
                    save(os.path.join(os.path.dirname(dest), ta.m_Name), b); n += 1
    return n
if __name__ == '__main__':
    idx = json.load(open('index.json'))
    # A patched asset is shipped in a new bundle while the original stays on disk, so the same
    # container path can appear twice. Take each path from the newest copy: patch folder first,
    # then latest modification time.
    def rank(p):
        return ('res_update' in p.replace(os.sep, '/'), os.path.getmtime(p))
    winner = {}
    for k, p, cs, e in idx:
        for c in cs:
            if target(c) and (c not in winner or rank(p) > rank(winner[c])):
                winner[c] = p
    # Incremental: only containers whose winning bundle (or its size/mtime) changed since last time.
    def stamp(p):
        st = os.stat(p)
        return [p, st.st_size, round(st.st_mtime, 3)]
    state = json.load(open('extract_state.json')) if os.path.exists('extract_state.json') and not FULL else {}
    current = {c: stamp(p) for c, p in winner.items()}
    changed = [c for c in winner if state.get(c) != current[c]]
    by_bundle = {}
    for c in changed:
        by_bundle.setdefault(winner[c], set()).add(c)
    jobs = sorted(by_bundle.items())
    print(f'{len(winner)} assets: {len(winner) - len(changed)} up to date, {len(changed)} to extract from {len(jobs)} bundles', flush=True)
    tot = 0
    if jobs:
        with Pool(12) as pool:
            for i, n in enumerate(pool.imap_unordered(work, jobs, chunksize=4)):
                tot += n
                if i % 300 == 0: print(' ', i, '/', len(jobs), flush=True)
    state.update({c: current[c] for c in changed})
    json.dump(state, open('extract_state.json', 'w'))
    print('files written', tot)


def fix_atlas_pages(root=OUT):
    """Unity can import a Spine page smaller than the atlas says (max texture size) or stretch it to a
    power of two. Unity's Spine runtime maps by the atlas's declared size, but the web runtime uses the
    image's real size for meshes, so mismatched pages render with scrambled textures. Resize each such
    page back to its declared size (the inverse of Unity's import resize)."""
    import glob, re, struct
    from PIL import Image
    fixed = []
    for atlas in glob.glob(os.path.join(root, 'spine*', '**', '*.atlas'), recursive=True):
        text = open(atlas, encoding='utf-8', errors='replace').read().replace('\r', '')
        for m in re.finditer(r'^(\S[^\n]*\.png)\n\s*size: (\d+), ?(\d+)', text, re.M):
            page = os.path.join(os.path.dirname(atlas), m.group(1).strip())
            want = (int(m.group(2)), int(m.group(3)))
            if not os.path.exists(page):
                continue
            with open(page, 'rb') as f:
                have = struct.unpack('>II', f.read(24)[16:24])
            if have == want or have == (1, 1):   # 1x1 = placeholder texture shipped by the game; nothing to recover
                continue
            Image.open(page).resize(want, Image.LANCZOS).save(page)
            fixed.append(f'{os.path.relpath(page, root)} {have[0]}x{have[1]} -> {want[0]}x{want[1]}')
    for f in fixed:
        print('  resized page', f)
    return fixed


if __name__ == '__main__' and not ONLY:
    fix_atlas_pages()
