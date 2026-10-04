"""Converts the game's Unity 3D hero models (skinned mesh + skeleton + Mecanim clips) to .glb.

Usage: python export_models.py [folder ...]   (no args = every hero folder; args = only those,
merged into the existing models.json). Output: ../models/<folder>/<prefab>.glb, ../models/models.json
(index for the viewer) and ../models/export_log.json (per prefab: notes, checks, errors).
Every model_*.prefab except *_lod*/*_timeline is converted; clips of the folder are attached when at
least half of their Transform bindings hit the prefab's skeleton.

Source layout (assets/res/model/pc/hero/<folder>/):
  model_<name>.prefab        GameObject tree; the bone hierarchy is "optimized" away, so the
                             SkinnedMeshRenderer has no m_Bones and the skeleton comes from the Avatar.
  anim/optimizedanim/<name>@<clip>.anim   Mecanim (generic) AnimationClips, other bundles.
  textures/*.png, materials/*.mat         referenced from the prefab bundle via external CABs.

Formats:
  Mesh      m_VertexData: channels {stream, offset, format, dimension} (0 pos, 1 normal, 2 tangent,
            3 color, 4-11 uv0-7, 12 weights, 13 bone indices); streams stored back to back, each
            16-byte aligned, stride = bytes per vertex of its channels. m_BindPose[i] / m_BoneNameHashes[i]
            (CRC32 of the bone path) describe bone i.
  Avatar    m_AvatarSkeleton: nodes (parent ids) + m_ID path hashes; m_TOS maps hash -> path;
            m_DefaultPose / m_AvatarSkeletonPose hold local TRS per node (rest pose).
  Clip      m_MuscleClip.m_Clip: curves numbered streamed [0,S), dense [S,S+D), constant [S+D,..).
            Streamed = frames {f32 time, u32 n, n x {u32 curve, f32 a,b,c,d}}; segment value
            a*x^3+b*x^2+c*x+d, x = t - key time. genericBindings consume curves in order
            (Transform typeID 4: attr 1 pos 3, 2 quat 4, 3 scale 3, 4 euler 3; others 1).
  Unity is left-handed: X is mirrored (pos -x, quat (x,-y,-z,w), matrices S*M*S, winding reversed).
Output: skeleton = Avatar nodes with the default pose as rest pose; the common boneWorld*bindpose is
baked into the vertices so the mesh node is identity. Weights are normalized uint16, rotations
normalized int16 (both glTF core). Clips are resampled at their sample rate (cubic evaluated) and
stored LINEAR; keys that linear interpolation reproduces within KEY_TOL are dropped, constant channels
equal to the rest pose omitted. Root-motion (Animator) curves are ignored, so clips play in place.
VFX meshes using particle shaders and static MeshRenderers are skipped. Base-colour texture is
embedded (JPEG if the material is opaque, else PNG). Bundles outside the hero folder (shaders, shared
meshes/textures) are found through a CAB-name -> bundle map read from the bundle headers.
"""
import io, json, lzma, os, re, struct, sys, traceback, zlib
from collections import Counter, defaultdict
from multiprocessing import Pool
import numpy as np
import UnityPy
from UnityPy.helpers.ResourceReader import get_resource_data
from UnityPy.helpers.CompressionHelper import decompress_lz4
from dtunpack import real_bundle

UnityPy.config.FALLBACK_UNITY_VERSION = '2020.3.25f1'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'models')
HERO = 'assets/res/model/pc/hero/'
SKIP_PREFAB = re.compile(r'_(lod\d*|timeline)$')
JPEG_QUALITY = 92
KEY_TOL = 5e-4          # max error of dropped animation keys (units / quaternion components)
REST_TOL = 5e-4         # constant channels this close to the rest pose are omitted (three.js
                        # blends untouched properties back to the rest pose, like Unity's write-defaults)

# ----------------------------------------------------------------------------- bundle access

class Assets:
    """Several bundles in one UnityPy environment; resolves PPtrs across CABs.
    paths must be ordered oldest first so a patched CAB overrides the original."""
    def __init__(self, paths, cab_map=None):
        self.env = UnityPy.Environment()
        self.files = {}       # lower-case CAB name -> SerializedFile
        self.containers = {}  # bundle path -> {container path: ObjectReader}
        self.cab_map = cab_map or {}
        for p in paths:
            self.load(p)

    def load(self, p):
        f = self.env.load_file(real_bundle(open(p, 'rb').read()), name=p)
        cont = self.containers.setdefault(p, {})
        for name, sf in getattr(f, 'files', {}).items():
            if hasattr(sf, 'objects'):
                self.files[name.lower()] = sf
                for c, ptr in sf.container.items():
                    o = sf.objects.get(ptr.m_PathID) if not ptr.m_FileID else None
                    if o is not None:
                        cont[c] = o

    def get(self, owner, pptr):
        """owner: ObjectReader the PPtr was read from. Returns ObjectReader or None."""
        fid, pid = pptr['m_FileID'], pptr['m_PathID']
        if not pid:
            return None
        sf = owner.assets_file
        if fid:
            name = os.path.basename(sf.externals[fid - 1].path).lower()
            sf = self.files.get(name)
            if sf is None and self.cab_map.get(name) and self.cab_map[name] not in self.containers:
                self.load(self.cab_map[name])  # dependency outside the hero folder
                sf = self.files.get(name)
            if sf is None:
                raise KeyError('external ' + name + ' not found')
        return sf.objects.get(pid)


# ----------------------------------------------------------------------------- math helpers

S = np.diag([-1.0, 1, 1, 1])

def mirror_q(q):
    q = np.array(q, dtype=np.float64)
    q[..., 1] *= -1; q[..., 2] *= -1
    return q

def quat_mat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])

def trs_mat(t, q, s):
    m = np.eye(4)
    m[:3, :3] = quat_mat(q) * np.asarray(s)[None, :]
    m[:3, 3] = t
    return m

def qmul(a, b):  # (..., 4) xyzw
    ax, ay, az, aw = np.moveaxis(a, -1, 0); bx, by, bz, bw = np.moveaxis(b, -1, 0)
    return np.stack([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz], -1)

def euler_to_quat(e):  # Unity degrees, applied Z then X then Y: q = qy * qx * qz
    h = np.radians(e) / 2
    z0 = np.zeros(h.shape[:-1])
    qx = np.stack([np.sin(h[..., 0]), z0, z0, np.cos(h[..., 0])], -1)
    qy = np.stack([z0, np.sin(h[..., 1]), z0, np.cos(h[..., 1])], -1)
    qz = np.stack([z0, z0, np.sin(h[..., 2]), np.cos(h[..., 2])], -1)
    return qmul(qmul(qy, qx), qz)

def xform(d):
    return ([d['t']['x'], d['t']['y'], d['t']['z']], [d['q']['x'], d['q']['y'], d['q']['z'], d['q']['w']],
            [d['s']['x'], d['s']['y'], d['s']['z']])


# ----------------------------------------------------------------------------- mesh

FMT = {0: ('<f4', 4), 1: ('<f2', 2), 2: ('u1', 1), 3: ('i1', 1), 4: ('<u2', 2), 5: ('<i2', 2),
       6: ('u1', 1), 7: ('i1', 1), 8: ('<u2', 2), 9: ('<i2', 2), 10: ('<u4', 4), 11: ('<i4', 4)}
NORM = {2: 255.0, 3: 127.0, 4: 65535.0, 5: 32767.0}

def read_mesh(obj, tt, notes):
    if tt.get('m_MeshCompression'):
        raise ValueError('compressed mesh (m_MeshCompression=%d) not supported' % tt['m_MeshCompression'])
    vd = tt['m_VertexData']; n = vd['m_VertexCount']
    data = vd['m_DataSize']
    sd = tt.get('m_StreamData') or {}
    if sd.get('size'):
        data = get_resource_data(sd['path'], obj.assets_file, sd['offset'], sd['size'])
        notes.add('external stream data')
    data = bytes(data)
    chans = vd['m_Channels']
    strides = defaultdict(int)
    for c in chans:
        d = c['dimension'] & 0xF
        if d:
            strides[c['stream']] = max(strides[c['stream']], c['offset'] + FMT[c['format']][1] * d)
    starts, pos = {}, 0
    for s in range(max(strides) + 1 if strides else 0):
        starts[s] = pos
        pos = (pos + strides.get(s, 0) * n + 15) & ~15
    out = {}
    for i, c in enumerate(chans):
        d = c['dimension'] & 0xF
        if not d:
            continue
        dt, size = FMT[c['format']]
        st = strides[c['stream']]
        raw = np.frombuffer(data, np.uint8, st * n, starts[c['stream']]).reshape(n, st)
        a = raw[:, c['offset']:c['offset'] + size * d].copy().view(dt).reshape(n, d)
        a = a.astype(np.float64) / NORM[c['format']] if c['format'] in NORM else a
        out[i] = a
    if tt.get('m_Shapes', {}).get('shapes'):
        notes.add('blend shapes ignored')
    if (tt.get('m_VariableBoneCountWeights') or {}).get('m_Data'):
        notes.add('variable bone weights ignored')
    ib = bytes(tt['m_IndexBuffer'])
    idt = '<u2' if tt['m_IndexFormat'] == 0 else '<u4'
    subs = []
    for sm in tt['m_SubMeshes']:
        if sm.get('topology', 0) != 0:
            notes.add('non-triangle submesh skipped'); subs.append(None); continue
        idx = np.frombuffer(ib, idt, sm['indexCount'], sm['firstByte']).astype(np.int64) + sm['baseVertex']
        subs.append(idx.reshape(-1, 3))
    return n, out, subs


# ----------------------------------------------------------------------------- animation

def binding_curves(b):
    if b['typeID'] == 4:
        return {1: 3, 2: 4, 3: 3, 4: 3}.get(b['attribute'], 1)
    return 1

def clip_sampler(tt):
    """Returns (start, stop, rate, f(curve_index, times) -> values)."""
    mc = tt['m_MuscleClip']; cd = mc['m_Clip']['data']
    start, stop = mc['m_StartTime'], mc['m_StopTime']
    sc = cd['m_StreamedClip']; S_ = sc['curveCount']
    keys = defaultdict(list)  # curve -> [(time, a, b, c, d)]
    b = np.asarray(sc['data'], dtype=np.uint32).tobytes(); o = 0
    while o + 8 <= len(b):
        t, k = struct.unpack_from('<fI', b, o); o += 8
        ks = np.frombuffer(b, dtype=[('i', '<u4'), ('c', '<f4', 4)], count=k, offset=o); o += 20 * k
        for i, c in zip(ks['i'].tolist(), ks['c'].tolist()):
            keys[i].append((t, *c))
    keys = {i: np.array(v, dtype=np.float64) for i, v in keys.items()}
    dc = cd['m_DenseClip']; D = dc['m_CurveCount']
    dense = np.asarray(dc['m_SampleArray'], dtype=np.float64)
    nf = len(dense) // D if D else 0
    dense = dense[:nf * D].reshape(nf, D) if D else dense
    const = np.asarray(cd['m_ConstantClip']['data'], dtype=np.float64)
    total = S_ + D + len(const)

    def f(ci, times):
        if ci < S_:
            k = keys.get(ci)
            if k is None or not len(k):
                return np.zeros_like(times)
            k = k[k[:, 0] < np.inf]  # drop the +inf end sentinel
            j = np.clip(np.searchsorted(k[:, 0], times, 'right') - 1, 0, len(k) - 1)
            kt = k[j, 0]
            x = np.where(kt < -1e30, 0.0, np.maximum(times - kt, 0.0))
            return ((k[j, 1] * x + k[j, 2]) * x + k[j, 3]) * x + k[j, 4]
        ci -= S_
        if ci < D:
            ft = dc['m_BeginTime'] + np.arange(nf) / dc['m_SampleRate']
            return np.interp(times, ft, dense[:, ci])
        return np.full_like(times, const[ci - D])
    return start, stop, tt['m_SampleRate'] or 30.0, total, f

def reduce_keys(t, v, tol):
    """Greedy removal of keys reproduced by linear interpolation. v: (n, k)."""
    n = len(t)
    if n <= 2:
        return np.arange(n)
    keep = [0]; a = 0; i = 2
    while i < n:
        seg = slice(a + 1, i)
        w = ((t[seg] - t[a]) / (t[i] - t[a]))[:, None]
        if np.abs(v[a] + (v[i] - v[a]) * w - v[seg]).max() > tol:
            keep.append(i - 1); a = i - 1
        i += 1
    keep.append(n - 1)
    return np.array(keep)


# ----------------------------------------------------------------------------- glTF writer

class GLB:
    def __init__(self):
        self.bin = bytearray()
        self.j = {'asset': {'version': '2.0', 'generator': 'DragonTraveler export_models.py'},
                  'scene': 0, 'scenes': [{'nodes': []}], 'nodes': [], 'meshes': [], 'skins': [],
                  'materials': [], 'textures': [], 'images': [], 'samplers': [], 'animations': [],
                  'accessors': [], 'bufferViews': [], 'buffers': []}
        self.cache = {}
        self.packed = bytearray(); self.packed_view = None  # small accessors share one bufferView

    def view(self, data, target=None):
        while len(self.bin) % 4:
            self.bin.append(0)
        bv = {'buffer': 0, 'byteOffset': len(self.bin), 'byteLength': len(data)}
        if target: bv['target'] = target
        self.bin += data
        self.j['bufferViews'].append(bv)
        return len(self.j['bufferViews']) - 1

    def acc(self, arr, ctype, typ, target=None, minmax=False, normalized=False, packed=False):
        """arr numpy array already in the final dtype; deduplicates identical data."""
        arr = np.ascontiguousarray(arr)
        data = arr.tobytes()
        key = (data, ctype, typ, normalized, target)
        if key in self.cache:
            return self.cache[key]
        ncomp = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}[typ]
        if packed:
            if self.packed_view is None:
                self.j['bufferViews'].append({'buffer': 0}); self.packed_view = len(self.j['bufferViews']) - 1
            while len(self.packed) % 4:
                self.packed.append(0)
            a = {'bufferView': self.packed_view, 'byteOffset': len(self.packed)}
            self.packed += data
        else:
            a = {'bufferView': self.view(data, target)}
        a.update(componentType=ctype, count=arr.size // ncomp, type=typ)
        if normalized: a['normalized'] = True
        if minmax:
            r = arr.reshape(-1, ncomp)
            a['min'] = [float(x) for x in r.min(0)]; a['max'] = [float(x) for x in r.max(0)]
        self.j['accessors'].append(a)
        self.cache[key] = len(self.j['accessors']) - 1
        return self.cache[key]

    def f32(self, arr, typ, **kw):
        return self.acc(np.asarray(arr, np.float32), 5126, typ, **kw)

    def node(self, **kw):
        self.j['nodes'].append({k: v for k, v in kw.items() if v is not None})
        return len(self.j['nodes']) - 1

    def save(self, path):
        if self.packed_view is not None:
            while len(self.bin) % 4:
                self.bin.append(0)
            self.j['bufferViews'][self.packed_view].update(byteOffset=len(self.bin), byteLength=len(self.packed))
            self.bin += self.packed
        j = {k: v for k, v in self.j.items() if v != []}
        j['buffers'] = [{'byteLength': len(self.bin)}]
        js = json.dumps(j, separators=(',', ':')).encode()
        js += b' ' * (-len(js) % 4)
        while len(self.bin) % 4:
            self.bin.append(0)
        out = struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(self.bin))
        out += struct.pack('<II', len(js), 0x4E4F534A) + js + struct.pack('<II', len(self.bin), 0x004E4942) + self.bin
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as fh:
            fh.write(out)
        return len(out)


# ----------------------------------------------------------------------------- material / texture

BASE_SLOTS = ('_BaseMap', '_MainTex', '_BaseColorMap', '_Albedo', '_BaseTex', '_Diffuse')

def material_info(assets, mat_obj, folder_textures, notes):
    """Returns (name, PIL image or None, alphaMode, cutoff, doubleSided)."""
    tt = mat_obj.read_typetree()
    props = tt['m_SavedProperties']
    floats = dict(props.get('m_Floats', []))
    tex = None
    envs = dict(props.get('m_TexEnvs', []))
    order = [s for s in BASE_SLOTS if s in envs] + [s for s in envs if s not in BASE_SLOTS]
    for slot in order:  # first base-colour slot, else any texture named *_b
        if not envs[slot]['m_Texture']['m_PathID']:
            continue
        try:
            o = assets.get(mat_obj, envs[slot]['m_Texture'])
        except KeyError as e:
            if slot in BASE_SLOTS: notes.add('texture %s unresolved (%s)' % (slot, e))
            continue
        if o is None or o.type.name != 'Texture2D':
            continue
        if slot in BASE_SLOTS or o.read_typetree()['m_Name'].lower().endswith('_b'):
            tex = o; break
    if tex is None and folder_textures:  # fall back to a *_b texture of the folder
        mn = tt['m_Name'].lower().replace('model_', '')
        cands = sorted(folder_textures, key=lambda c: (mn not in c[0], c[0]))
        tex = cands[0][1]
        notes.add('base texture picked by name: ' + cands[0][0])
    img = tex.read().image if tex is not None else None
    kw = tt.get('m_ShaderKeywords') or ''
    if isinstance(kw, list): kw = ' '.join(kw)
    alpha, cutoff = 'OPAQUE', None
    if floats.get('_Surface', 0) >= 1 or floats.get('_Mode', 0) >= 2:
        alpha = 'BLEND'
    elif floats.get('_AlphaClip', 0) >= 1 or '_ALPHATEST_ON' in kw:
        alpha, cutoff = 'MASK', floats.get('_Cutoff', 0.5)
    return tt['m_Name'], img, alpha, cutoff, floats.get('_Cull', 2) == 0


# ----------------------------------------------------------------------------- conversion

def components(assets, g, gt):
    out = {}
    for c in gt['m_Component']:
        co = assets.get(g, c['component'])
        if co is not None:
            out.setdefault(co.type.name, co)
    return out

def go_tree(assets, go):
    """Depth-first (parents first): (go, go_tt, transform, transform_tt, parent index, path)."""
    stack = [(go, -1, '')]; i = 0
    while stack:
        g, parent, path = stack.pop(); gt = g.read_typetree()
        cs = components(assets, g, gt)
        tr = cs.get('Transform') or cs.get('RectTransform')
        tt = tr.read_typetree()
        yield g, gt, tr, tt, parent, path
        me = i; i += 1
        for ch in reversed(tt['m_Children']):
            cto = assets.get(tr, ch)
            cg = assets.get(cto, cto.read_typetree()['m_GameObject'])
            name = cg.read_typetree()['m_Name']
            stack.append((cg, me, path + '/' + name if path else name))

def tr_local(tt):
    p, q, s = tt['m_LocalPosition'], tt['m_LocalRotation'], tt['m_LocalScale']
    return [p['x'], p['y'], p['z']], [q['x'], q['y'], q['z'], q['w']], [s['x'], s['y'], s['z']]

def build_skeleton(assets, go, prefab_name):
    """Skeleton nodes (parents before children) from the Avatar when the hierarchy is optimized away,
    otherwise from the prefab's Transform tree. ids = CRC32 of the node path (what clips bind to)."""
    tree = list(go_tree(assets, go))
    for t in tree:  # the Animator may sit on a nested prefab instead of the root
        anim = components(assets, t[0], t[1]).get('Animator')
        if anim is not None:
            if t[0].path_id != go.path_id:
                tree = list(go_tree(assets, t[0]))
            break
    at = anim.read_typetree() if anim is not None else {}
    av = assets.get(anim, at['m_Avatar']) if anim is not None else None
    sk = dict(tree=tree, by_tr={}, source='transforms')
    if av is not None and not at.get('m_HasTransformHierarchy', True):
        a = av.read_typetree()
        s = a['m_Avatar']['m_AvatarSkeleton']['data']
        sk['parents'] = [n['m_ParentId'] for n in s['m_Node']]
        sk['ids'] = [x & 0xFFFFFFFF for x in s['m_ID']]
        tos = {h & 0xFFFFFFFF: p for h, p in a['m_TOS']}
        sk['names'] = [tos.get(h, '').rsplit('/', 1)[-1] or (prefab_name if i == 0 else 'node%d' % i)
                       for i, h in enumerate(sk['ids'])]
        sk['poses'] = {k: [xform(x) for x in a['m_Avatar'][k]['data']['m_X']]
                       for k in ('m_DefaultPose', 'm_AvatarSkeletonPose')
                       if len(a['m_Avatar'][k]['data']['m_X']) == len(sk['ids'])}
        sk['source'] = 'avatar'
    else:
        sk['parents'] = [t[4] for t in tree]
        sk['ids'] = [zlib.crc32(t[5].encode()) for t in tree]
        sk['names'] = [prefab_name if i == 0 else t[1]['m_Name'] for i, t in enumerate(tree)]
        sk['poses'] = {'transforms': [tr_local(t[3]) for t in tree]}
        sk['by_tr'] = {t[2].path_id: i for i, t in enumerate(tree)}
    sk['hash2node'] = {h: i for i, h in enumerate(sk['ids'])}
    return sk

def mesh_attrs(gl, ch, n, M, notes):
    """Vertex attributes in glTF space; M (Unity space 4x4) is baked into positions/normals."""
    if 0 not in ch: raise ValueError('mesh without positions')
    pos = (np.c_[ch[0][:, :3], np.ones(n)] @ M.T)[:, :3] * [-1, 1, 1]
    attrs = {'POSITION': gl.f32(pos, 'VEC3', target=34962, minmax=True)}
    if 1 in ch:
        nr = (ch[1][:, :3] @ np.linalg.inv(M[:3, :3])) * [-1, 1, 1]  # inverse transpose
        ln = np.linalg.norm(nr, axis=1, keepdims=True)
        nr = np.where(ln > 1e-8, nr / np.maximum(ln, 1e-8), [0, 1, 0])
        attrs['NORMAL'] = gl.f32(nr, 'VEC3', target=34962)
    if 4 in ch:
        uv = ch[4][:, :2].astype(np.float64).copy(); uv[:, 1] = 1 - uv[:, 1]
        attrs['TEXCOORD_0'] = gl.f32(uv, 'VEC2', target=34962)
    return attrs, pos

def primitives(gl, assets, attrs, subs, mats, n, flip, mat_cache, folder_textures, notes):
    prims = []
    for si, tri in enumerate(subs):
        if tri is None or not len(tri): continue
        if tri.max() >= n or tri.min() < 0: raise ValueError('index out of range')
        if not flip: tri = tri[:, [0, 2, 1]]  # mirroring X reverses the winding
        idx = gl.acc(tri.astype(np.uint16 if n < 65536 else np.uint32), 5123 if n < 65536 else 5125, 'SCALAR', target=34963)
        mo = mats[min(si, len(mats) - 1)] if mats else None
        key = mo.path_id if mo is not None else None
        if key not in mat_cache:
            mat_cache[key] = add_material(gl, assets, mo, folder_textures, notes)
        prims.append({'attributes': attrs, 'indices': idx, 'material': mat_cache[key]})
    if len(mats) > len(subs):
        notes.add('more materials than submeshes')
    if len([s for s in subs if s is not None]) > 1:
        notes.add('multiple submeshes/materials')
    return prims

def quantize_weights(w):
    """Normalized uint16 weights whose rows sum to exactly 65535."""
    q = np.round(w * 65535).astype(np.int64)
    rows = np.arange(len(q)); top = np.argmax(w, 1)
    q[rows, top] += 65535 - q.sum(1)
    return q.astype(np.uint16)

SHADERS = {}

def shader_name(assets, owner, mat):
    """Shader name of material PPtr mat (read from object owner), '' if unavailable."""
    try:
        mo = assets.get(owner, mat)
        so = assets.get(mo, mo.read_typetree()['m_Shader'])
        key = (so.assets_file.name, so.path_id)
        if key not in SHADERS:
            SHADERS[key] = so.read_typetree()['m_ParsedForm']['m_Name']
        return SHADERS[key]
    except Exception:
        return ''

def convert_prefab(assets, go, prefab_name, sk, clips, folder_textures, out_path):
    notes = set(); stats = Counter(); comps = Counter(); smrs = []
    parents, ids, names, hash2node = sk['parents'], sk['ids'], sk['names'], sk['hash2node']
    for g, gt, tr, trt, parent, path in sk['tree']:
        cs = components(assets, g, gt)
        comps.update(cs.keys())
        if not gt.get('m_IsActive', 1):
            if 'SkinnedMeshRenderer' in cs or 'MeshRenderer' in cs:
                notes.add('inactive renderer skipped: ' + gt['m_Name'])
            continue
        if 'SkinnedMeshRenderer' in cs:
            smrs.append((g, gt, tr, cs['SkinnedMeshRenderer']))
        elif 'MeshRenderer' in cs:  # only VFX props use these in the hero prefabs
            notes.add('static MeshRenderer skipped: ' + gt['m_Name'])
    stats['skeleton'] = sk['source']
    # VFX meshes (particle shaders) sit next to the body; drop them unless they are all there is
    shaders = {id(x[3]): [shader_name(assets, x[3], m) for m in x[3].read_typetree()['m_Materials']] for x in smrs}
    body = [x for x in smrs if not any('Particles' in sh for sh in shaders[id(x[3])])]
    for x in smrs:
        if body and x not in body:
            notes.add('effect mesh skipped: ' + x[1]['m_Name'])
        elif not body:
            notes.add('effect shader only: ' + x[1]['m_Name'])
    smrs = body or smrs

    # ---- skinned meshes
    meshes = []
    for g, gt, tr, co in smrs:
        st = co.read_typetree()
        if not st.get('m_Enabled', 1):
            notes.add('disabled renderer skipped: ' + gt['m_Name']); continue
        mo = assets.get(co, st['m_Mesh'])
        if mo is None:
            notes.add('renderer without mesh: ' + gt['m_Name']); continue
        mt = mo.read_typetree()
        n, ch, subs = read_mesh(mo, mt, notes)
        if st['m_Bones'] and sk['by_tr']:
            joints = []
            for b in st['m_Bones']:
                bo = assets.get(co, b)
                if bo is None or bo.path_id not in sk['by_tr']: raise ValueError('bone transform outside prefab')
                joints.append(sk['by_tr'][bo.path_id])
        else:
            hs = [h & 0xFFFFFFFF for h in mt['m_BoneNameHashes']]
            missing = [h for h in hs if h not in hash2node]
            if missing: raise ValueError('%d of %d mesh bones not in skeleton' % (len(missing), len(hs)))
            joints = [hash2node[h] for h in hs]
        if not joints: raise ValueError('skinned mesh without bones: ' + mt['m_Name'])
        bp = np.array([[[m['e%d%d' % (r, c)] for c in range(4)] for r in range(4)] for m in mt['m_BindPose']])
        if len(bp) != len(joints): raise ValueError('bind pose count != bone count')
        if 12 in ch and 13 in ch:
            w = np.zeros((n, 4)); j = np.zeros((n, 4), np.int64)
            w[:, :ch[12].shape[1]] = ch[12][:, :4]; j[:, :ch[13].shape[1]] = ch[13][:, :4]
        elif 13 in ch:  # one bone per vertex
            w = np.zeros((n, 4)); w[:, 0] = 1; j = np.zeros((n, 4), np.int64); j[:, 0] = ch[13][:, 0]
        else:
            raise ValueError('skinned mesh without bone weights')
        w = np.where(w > 0, w, 0); j = np.where(w > 0, j, 0)
        sw = w.sum(1, keepdims=True)
        if (sw[:, 0] <= 0).any(): notes.add('vertices without weights bound to bone 0')
        w = np.where(sw > 0, w / np.where(sw > 0, sw, 1), [1, 0, 0, 0])
        if j.max() >= len(joints): raise ValueError('bone index out of range')
        use = np.zeros(len(joints))
        for k in range(4): np.add.at(use, j[:, k], w[:, k])
        meshes.append(dict(name=mt['m_Name'], n=n, ch=ch, subs=subs, joints=joints, bp=bp, w=w, j=j, use=use,
                           mats=[assets.get(co, m) for m in st['m_Materials']]))
    if not meshes:
        raise ValueError('no mesh renderer (components: %s)' % dict(comps))
    if len(meshes) > 1:
        notes.add('%d skinned meshes' % len(meshes))

    def worlds(pose):
        W = [None] * len(ids)
        for i, (t, q, s) in enumerate(pose):
            L = trs_mat(t, q, s)
            W[i] = L if parents[i] < 0 else W[parents[i]] @ L
        return W

    # ---- rest pose: joint world * bindpose should be one matrix (the mesh's bind-time placement)
    # for every bone; take the pose where the used bones agree best.
    best = None
    for k, pose in sk['poses'].items():
        W = worlds(pose); err = 0
        for m in meshes:
            P = np.array([W[x] @ b for x, b in zip(m['joints'], m['bp'])])
            ref = P[np.argmax(m['use'])]
            err = max(err, float(np.abs(P[m['use'] > 0] - ref).max()))
        if best is None or err < best[1] - 1e-6:
            best = (k, err, pose, W)
    pose_name, pose_err, pose, W = best
    stats['pose'] = pose_name; stats['pose_consistency_err'] = pose_err

    # ---- glTF
    gl = GLB()
    rest = []
    for i, (t, q, s) in enumerate(pose):
        t = [-t[0], t[1], t[2]]; q = mirror_q(q); q = list(q / np.linalg.norm(q))
        rest.append((t, q, list(s)))
        gl.node(name=names[i],
                translation=[float(x) for x in t] if np.abs(t).max() > 1e-9 else None,
                rotation=[float(x) for x in q] if abs(q[3]) < 1 - 1e-9 else None,
                scale=[float(x) for x in s] if np.abs(np.array(s) - 1).max() > 1e-7 else None)
    kids = defaultdict(list)
    for i, p in enumerate(parents):
        if p >= 0: kids[p].append(i)
    for p, c in kids.items():
        gl.j['nodes'][p]['children'] = c
    gl.j['scenes'][0]['nodes'].append(0)
    Wg = [S @ w @ S for w in W]

    mat_cache = {}; all_pos = []; vcount = 0; rest_err = 0.0
    for m in meshes:
        # Unity renders sum(w * boneWorld * bindpose * v); bake the common boneWorld * bindpose (M) into
        # the vertices so the stored positions are the rest pose (identity mesh node, as glTF expects).
        P = np.array([W[x] @ b for x, b in zip(m['joints'], m['bp'])])
        M = P[np.argmax(m['use'])]
        flip = np.linalg.det(M[:3, :3]) < 0
        attrs, pos = mesh_attrs(gl, m['ch'], m['n'], M, notes)
        nj = len(m['joints'])
        attrs['JOINTS_0'] = gl.acc(m['j'].astype(np.uint8 if nj < 256 else np.uint16), 5121 if nj < 256 else 5123, 'VEC4', target=34962)
        attrs['WEIGHTS_0'] = gl.acc(quantize_weights(m['w']), 5123, 'VEC4', target=34962, normalized=True)
        prims = primitives(gl, assets, attrs, m['subs'], m['mats'], m['n'], flip, mat_cache, folder_textures, notes)
        gl.j['meshes'].append({'name': m['name'], 'primitives': prims})
        ibm = np.array([S @ b @ np.linalg.inv(M) @ S for b in m['bp']])
        gl.j['skins'].append({'joints': m['joints'], 'skeleton': 0,
                              'inverseBindMatrices': gl.f32(ibm.transpose(0, 2, 1), 'MAT4')})
        gl.j['scenes'][0]['nodes'].append(gl.node(name=m['name'], mesh=len(gl.j['meshes']) - 1, skin=len(gl.j['skins']) - 1))
        # check: skinning the stored vertices with the rest pose reproduces them
        J = np.array([Wg[x] @ ib for x, ib in zip(m['joints'], ibm)])
        sk_pos = np.einsum('vk,vkij,vj->vi', m['w'], J[m['j']], np.c_[pos, np.ones(m['n'])])[:, :3]
        rest_err = max(rest_err, float(np.abs(sk_pos - pos).max()))
        all_pos.append(sk_pos); vcount += m['n']

    allp = np.concatenate(all_pos)
    bounds = [round(float(x), 5) for x in np.r_[allp.min(0), allp.max(0)]]

    # ---- animations
    clip_info = []
    for cname, ctt in clips:
        r = add_animation(gl, cname, ctt, hash2node, rest, notes, stats)
        if r is not None:
            clip_info.append(r)
    size = gl.save(out_path)
    joints = {x for m in meshes for x in m['joints']}
    return dict(clips=clip_info, bounds=bounds, vertices=vcount, bones=len(joints), nodes=len(ids), size=size,
                notes=sorted(notes), checks={'rest_skin_err': rest_err}, stats=dict(stats), components=dict(comps))

def add_material(gl, assets, mo, folder_textures, notes):
    if mo is None:
        gl.j['materials'].append({'name': 'default', 'pbrMetallicRoughness': {'metallicFactor': 0, 'roughnessFactor': 0.8}})
        return len(gl.j['materials']) - 1
    name, img, alpha, cutoff, double = material_info(assets, mo, folder_textures, notes)
    mat = {'name': name, 'pbrMetallicRoughness': {'metallicFactor': 0.0, 'roughnessFactor': 0.8}}
    if img is not None:
        buf = io.BytesIO()
        if alpha == 'OPAQUE':
            img.convert('RGB').save(buf, 'JPEG', quality=JPEG_QUALITY); mime = 'image/jpeg'
        else:
            img.convert('RGBA').save(buf, 'PNG', optimize=True); mime = 'image/png'
        if not gl.j['samplers']:
            gl.j['samplers'].append({'magFilter': 9729, 'minFilter': 9987, 'wrapS': 10497, 'wrapT': 10497})
        gl.j['images'].append({'name': name, 'mimeType': mime, 'bufferView': gl.view(buf.getvalue())})
        gl.j['textures'].append({'sampler': 0, 'source': len(gl.j['images']) - 1})
        mat['pbrMetallicRoughness']['baseColorTexture'] = {'index': len(gl.j['textures']) - 1}
    else:
        notes.add('no base texture for ' + name)
    if alpha != 'OPAQUE': mat['alphaMode'] = alpha
    if cutoff is not None: mat['alphaCutoff'] = cutoff
    if double: mat['doubleSided'] = True
    gl.j['materials'].append(mat)
    return len(gl.j['materials']) - 1

def add_animation(gl, cname, tt, hash2node, rest, notes, stats):
    start, stop, rate, total, f = clip_sampler(tt)
    bnd = tt['m_ClipBindingConstant']['genericBindings']
    need = sum(binding_curves(b) for b in bnd)
    if need != total:
        notes.add('clip %s: bindings need %d curves, clip has %d (skipped)' % (cname, need, total))
        return None
    dur = max(0.0, stop - start)
    nfr = int(round(dur * rate)) + 1
    times = np.float32(np.arange(nfr) / rate).astype(np.float64) + start
    times[-1] = start + dur
    rel = (times - start).astype(np.float32)
    channels, samplers = [], []
    ci = 0
    for b in bnd:
        k = binding_curves(b)
        node = hash2node.get(b['path'] & 0xFFFFFFFF)
        if b['typeID'] != 4 or b['attribute'] not in (1, 2, 3, 4) or node is None:
            stats['ignored_bindings'] += 1
            stats['ignored_typeID_%d' % b['typeID']] += 1
            ci += k; continue
        v = np.stack([f(ci + c, times) for c in range(k)], -1); ci += k
        if not np.isfinite(v).all():
            notes.add('clip %s: non-finite values' % cname); v = np.nan_to_num(v)
        a = b['attribute']
        if a == 1:
            path, v = 'translation', v * [-1, 1, 1]
        elif a == 3:
            path = 'scale'
        else:
            q = euler_to_quat(v) if a == 4 else v
            q = q / np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-12)
            q = mirror_q(q)
            for i in range(1, len(q)):  # keep neighbouring keys in the same hemisphere
                if np.dot(q[i], q[i - 1]) < 0: q[i] = -q[i]
            path, v = 'rotation', q
        if np.abs(v - v[0]).max() <= KEY_TOL * 0.1:
            r = np.array(rest[node][{'translation': 0, 'rotation': 1, 'scale': 2}[path]])
            if np.abs(v[0] * (np.sign(v[0] @ r) if path == 'rotation' else 1) - r).max() <= REST_TOL:
                stats['rest_channels_dropped'] += 1
                if channels or b is not bnd[-1]:
                    continue
            kt, kv = np.zeros(1, np.float32), v[:1]
        else:
            keep = reduce_keys(rel.astype(np.float64), v, KEY_TOL)
            # own (reduced) time track only when it beats the clip's shared full-rate track,
            # counting ~120 bytes of JSON for the extra input accessor
            vsize = 8 if path == 'rotation' else 12
            kt, kv = (rel[keep], v[keep]) if len(keep) * (4 + vsize) + 120 < nfr * vsize else (rel, v)
        stats['anim_keys'] += len(kt)
        inp = gl.f32(kt, 'SCALAR', minmax=True, packed=True)
        if path == 'rotation':  # normalized int16 quaternions (glTF core, half the size of float)
            out = gl.acc(np.round(np.clip(kv, -1, 1) * 32767).astype(np.int16), 5122, 'VEC4', normalized=True, packed=True)
        else:
            out = gl.f32(kv, 'VEC3', packed=True)
        samplers.append({'input': inp, 'output': out})
        channels.append({'sampler': len(samplers) - 1, 'target': {'node': node, 'path': path}})
    if not channels:
        notes.add('clip %s: no transform channels' % cname); return None
    gl.j['animations'].append({'name': cname, 'channels': channels, 'samplers': samplers})
    return {'name': cname, 'duration': round(float(dur), 4)}


# ----------------------------------------------------------------------------- per folder job

CAB_MAP = {}  # lower-case CAB name -> newest bundle path (set in each worker)

def init_worker(cab_map):
    CAB_MAP.update(cab_map)

def bundle_cabs(path):
    """CAB names in a bundle, read from the UnityFS directory only (no block decompression)."""
    size = os.path.getsize(path)
    with open(path, 'rb') as fh:
        head = fh.read(1 << 16)
        for m in re.finditer(b'UnityFS\x00', head):
            o = m.start(); p = o + 12
            ver = struct.unpack_from('>I', head, o + 8)[0]
            for _ in range(2):
                p = head.index(b'\x00', p) + 1
            total, csize, usize, flags = struct.unpack_from('>qIII', head, p); p += 20
            if total != size - o:
                continue  # decoy header
            if ver >= 7:
                p = o + ((p - o + 15) & ~15)
            fh.seek(o + total - csize if flags & 0x80 else p)
            blob = fh.read(csize)
            comp = flags & 0x3F
            info = blob if comp == 0 else lzma.decompress(blob) if comp == 1 else decompress_lz4(blob, usize)
            q = 20 + struct.unpack_from('>i', info, 16)[0] * 10  # skip hash + block table
            count = struct.unpack_from('>i', info, q)[0]; q += 4
            names = []
            for _ in range(count):  # node: i64 offset, i64 size, u32 flags, path
                e = info.index(b'\x00', q + 20)
                names.append(info[q + 20:e].decode()); q = e + 1
            return names
    raise ValueError('no UnityFS header')

def cab_worker(p):
    try:
        return p, bundle_cabs(p)
    except Exception:
        return p, []

def clip_fits(tt, hash2node):
    b = [x for x in tt['m_ClipBindingConstant']['genericBindings'] if x['typeID'] == 4]
    return bool(b) and sum((x['path'] & 0xFFFFFFFF) in hash2node for x in b) >= 0.5 * len(b)

def work(job):
    folder, prefabs, files = job
    results = {}
    try:
        assets = Assets(sorted(set(files.values()), key=rank), CAB_MAP)
    except Exception as e:
        return folder, {p.rsplit('/', 1)[-1][:-7]: {'error': 'load: ' + repr(e)[:300], 'folder': folder} for p in prefabs}
    def pick(c):
        return assets.containers.get(files[c], {}).get(c)
    textures = []
    for c in sorted(files):
        if re.search(r'/textures?/', c) and re.search(r'_b\.(png|tga|jpg)$', c):
            o = pick(c)
            if o is not None and o.type.name == 'Texture2D':
                textures.append((c.rsplit('/', 1)[-1], o))
    all_clips = []
    for c in sorted(files):
        if c.endswith('.anim') and pick(c) is not None:
            try:
                all_clips.append((c, pick(c).read_typetree(), None))
            except Exception as e:
                all_clips.append((c, None, repr(e)[:200]))
    for p in prefabs:
        base = p.rsplit('/', 1)[-1][:-7]
        try:
            go = pick(p)
            if go is None: raise ValueError('prefab object not found')
            sk = build_skeleton(assets, go, base)
            # clips that bind to this skeleton; for equal clip names prefer prefix == prefab name
            chosen = {}
            short = base[6:] if base.startswith('model_') else base
            for c, tt, err in all_clips:
                if tt is None or not clip_fits(tt, sk['hash2node']): continue
                stem = c.rsplit('/', 1)[-1][:-5]
                prefix, _, name = stem.partition('@')
                name = name or stem
                score = (prefix.lower() == short.lower(), short.lower().startswith(prefix.lower()))
                if name not in chosen or score > chosen[name][0]:
                    chosen[name] = (score, tt)
            clips = [(n, chosen[n][1]) for n in sorted(chosen)]
            res = convert_prefab(assets, go, base, sk, clips, textures, os.path.join(OUT, folder, base + '.glb'))
            res.update(glb='models/%s/%s.glb' % (folder, base), folder=folder,
                       clip_errors=[c for c, tt, err in all_clips if err],
                       clips_unmatched=len([1 for c, tt, err in all_clips if tt is not None]) - len(clips))
            results[base] = res
        except Exception as e:
            results[base] = {'error': repr(e)[:300], 'trace': traceback.format_exc()[-800:], 'folder': folder}
    return folder, results


def rank(p):
    """A patched asset ships in a new bundle while the original stays: patch folder wins, then mtime."""
    return ('res_update' in p.replace(os.sep, '/'), os.path.getmtime(p))

def build_jobs(only=None):
    idx = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.json')))
    winner = {}
    for k, p, cs, e in idx:
        for c in cs:
            if c.startswith(HERO) and (c not in winner or rank(p) > rank(winner[c])):
                winner[c] = p
    folders = defaultdict(dict)
    for c, p in winner.items():
        folders[c[len(HERO):].split('/', 1)[0]][c] = p
    jobs = []
    for folder, files in sorted(folders.items()):
        if only and folder not in only: continue
        prefabs = sorted(c for c in files if c.count('/') == HERO.count('/') + 1 and c.endswith('.prefab')
                         and c.rsplit('/', 1)[-1].startswith('model_') and not SKIP_PREFAB.search(c[:-7]))
        if prefabs:
            jobs.append((folder, prefabs, files))
    return jobs, [p for k, p, cs, e in idx]


if __name__ == '__main__':
    only = set(sys.argv[1:])
    jobs, bundles = build_jobs(only)
    print('folders', len(jobs), 'prefabs', sum(len(j[1]) for j in jobs), flush=True)
    with Pool(12) as pool:  # CAB name -> bundle, for references into bundles outside the hero folder
        cab_map = {}
        for p, names in sorted(pool.imap_unordered(cab_worker, bundles, chunksize=64), key=lambda x: rank(x[0])):
            for nm in names:
                cab_map[nm.lower()] = p
    mpath = os.path.join(OUT, 'models.json'); lpath = os.path.join(OUT, 'export_log.json')
    models = json.load(open(mpath, encoding='utf-8')) if only and os.path.exists(mpath) else {}
    log = json.load(open(lpath, encoding='utf-8')) if only and os.path.exists(lpath) else {}
    with Pool(min(10, len(jobs)) or 1, init_worker, (cab_map,)) as pool:
        for i, (folder, res) in enumerate(pool.imap_unordered(work, jobs)):
            for base, r in res.items():
                log[base] = r
                if 'error' in r:
                    print('FAIL', folder, base, r['error'], flush=True); models.pop(base, None)
                else:
                    models[base] = {k: r[k] for k in ('glb', 'folder', 'clips', 'bounds', 'vertices', 'bones')}
            if i % 20 == 0: print(i, len(jobs), flush=True)
    os.makedirs(OUT, exist_ok=True)
    json.dump(dict(sorted(models.items())), open(mpath, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump(dict(sorted(log.items())), open(lpath, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    ok = [r for r in log.values() if 'error' not in r]
    print('converted', len(ok), 'of', len(log), 'MB', round(sum(r['size'] for r in ok) / 2**20, 1))
