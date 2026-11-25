import json, os, re, sys
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
    # skill icons for the Profile page
    'assets/res/gui/texture/icon/skillicon/': 'images/skillicon/',
    # goddess room backgrounds and the collectible props drawn over them
    'assets/res/gui/bigimage/goddess/': 'images/goddess/',
    # class and faction icons used by the gallery's filters
    'assets/res/gui/texture/common/common_jobicon_': 'images/ui/class_',
    'assets/res/gui/texture/common/common_jobdepartment_': 'images/ui/faction_',
}
# Optional command-line filter: only extract outputs under these prefixes, e.g. `python extract.py images/heroicon/`
ONLY = [a for a in sys.argv[1:] if not a.startswith('--')]
FULL = '--full' in sys.argv   # ignore extract_state.json and re-extract everything
# Battle arenas: each battle scene ships a top-down capture of its ground (scenecapturetexture.png); the 3D model
# viewer can stand a hero on it. Flattened to images/battlefield/<scene>.png.
ARENA = re.compile(r'assets/res/scenes/scene_fight/([^/]+)/(?:texture/)?scenecapturetexture\.png$')
def target(c):
    m = ARENA.match(c)
    if m:
        t = f'images/battlefield/{m[1]}.png'
        return t if not ONLY or any(t.startswith(o) for o in ONLY) else None
    for p, d in PREFIXES.items():
        if c.startswith(p):
            t = d + c[len(p):]
            return t if not ONLY or any(t.startswith(o) for o in ONLY) else None
def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'wb').write(data)
def is_spine(t):
    return t.startswith(('spine/', 'spine_pc/'))


def local(objs, ref):
    """The object a PPtr points to, if it lives in this bundle."""
    return objs.get(ref['m_PathID']) if ref and not ref.get('m_FileID') and ref.get('m_PathID') else None


def text_bytes(ta):
    s = ta.m_Script
    return s.encode('utf-8', 'surrogateescape') if isinstance(s, str) else bytes(s)


def save_material_page(objs, mat, folder, done):
    """Writes the texture a Spine material draws (one atlas page) as <texture name>.png."""
    envs = dict(mat.read_typetree()['m_SavedProperties']['m_TexEnvs'])
    tex = local(objs, envs.get('_MainTex', {}).get('m_Texture'))
    if not tex:
        return 0
    t = tex.read()
    dest = os.path.join(folder, t.m_Name + '.png')
    if dest in done:
        return 0
    done.add(dest)
    os.makedirs(folder, exist_ok=True)
    t.image.save(dest)
    return 1


def save_prefab_rigs(objs, root, folder, done):
    """The Taiwanese client's bundles name only the Spine prefab: the skeleton, atlas and texture pages sit
    beside it without asset paths of their own. Walk the prefab's objects to its Spine components and
    write what they reference (SkeletonDataAsset -> skeleton, atlas assets -> atlas text and pages)."""
    n = 0
    stack, seen = [root], set()
    while stack:
        go = stack.pop()
        if go.path_id in seen: continue
        seen.add(go.path_id)
        for entry in go.read_typetree().get('m_Component', []):
            comp = local(objs, entry.get('component'))
            if not comp: continue
            if comp.type.name in ('Transform', 'RectTransform'):
                for child in comp.read_typetree().get('m_Children', []):
                    tr = local(objs, child)
                    child_go = local(objs, tr.read_typetree().get('m_GameObject')) if tr else None
                    if child_go: stack.append(child_go)
            elif comp.type.name == 'MonoBehaviour':
                try:
                    tt = comp.read_typetree()
                except Exception:
                    continue
                data = local(objs, tt.get('skeletonDataAsset'))
                if not data: continue
                sd = data.read_typetree()
                files = [local(objs, sd.get('skeletonJSON'))]
                for ref in sd.get('atlasAssets', []):
                    atlas = local(objs, ref)
                    if not atlas: continue
                    at = atlas.read_typetree()
                    files.append(local(objs, at.get('atlasFile')))
                    for m in at.get('materials', []):
                        mat = local(objs, m)
                        if mat: n += save_material_page(objs, mat, folder, done)
                for f in files:
                    if not f: continue
                    ta = f.read()
                    dest = os.path.join(folder, ta.m_Name)
                    if dest in done: continue
                    done.add(dest)
                    save(dest, text_bytes(ta)); n += 1
    return n


def work(job):
    path, wanted = job
    env = load(path); n = 0
    objs = {o.path_id: o for o in env.objects}
    done = set()
    # Folders whose skeleton/atlas assets are listed by path (English client): the branch below handles them.
    listed = {c.rsplit('/', 1)[0] for c in env.container if c.endswith('.asset')}
    for c, ptr in env.container.items():
        t = target(c)
        if not t or c not in wanted: continue
        obj = ptr.deref() if hasattr(ptr, 'deref') else ptr
        name = obj.type.name
        dest = os.path.join(OUT, t)
        if is_spine(t) and name == 'GameObject' and c.endswith('.prefab'):
            if c.rsplit('/', 1)[0] not in listed:
                n += save_prefab_rigs(objs, obj, os.path.dirname(dest), done)
        elif is_spine(t) and name == 'Material':
            # a rig whose texture pages were packed into another bundle, listed there by material
            n += save_material_page(objs, obj, os.path.dirname(dest), done)
        elif name in ('Texture2D', 'Sprite'):
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
    # A Spine prefab whose folder holds no skeleton or atlas yet is extracted again even if the state file
    # lists it: versions before prefab-driven extraction recorded those prefabs without writing anything.
    def unextracted(c):
        t = target(c)
        if not (t and is_spine(t) and c.endswith('.prefab')):
            return False
        folder = os.path.join(OUT, os.path.dirname(t))
        return not (os.path.isdir(folder) and any(not f.lower().endswith('.png') for f in os.listdir(folder)))
    changed = [c for c in winner if state.get(c) != current[c] or unextracted(c)]
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
        # 'size: w, h' (older atlas format) or 'size:w,h' (Spine 4.1)
        for m in re.finditer(r'^(\S[^\n]*\.png)\n\s*size: ?(\d+), ?(\d+)', text, re.M):
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
