"""Dragon Traveler bundle de-obfuscation helpers.
Bundles are UnityFS files prefixed with a fake header + junk (and decoy UnityFS
headers). The real bundle is the UnityFS occurrence whose size field (int64 BE
at +0x1e) equals len(file) - offset."""
import re, struct, os, glob
import UnityPy

from config import GAME, RES_BASE, RES_UPDATE
ROOTS = [RES_BASE, RES_UPDATE]

def real_bundle(data: bytes) -> bytes:
    n = len(data)
    for m in re.finditer(b'UnityFS\x00', data):
        o = m.start()
        hdr_end = data.find(b'\x00', data.find(b'\x00', o + 12) + 1) + 1  # after two strings
        size = struct.unpack('>q', data[hdr_end:hdr_end + 8])[0]
        if size == n - o:
            return data[o:]
    raise ValueError('no matching UnityFS header')

def load(path):
    return UnityPy.load(real_bundle(open(path, 'rb').read()))

def all_bundles():
    """category/hash -> path; res_update overrides base install."""
    out = {}
    for root in ROOTS:
        for p in glob.glob(root + '/**/*.b', recursive=True):
            out[os.path.relpath(p, root).replace(os.sep, '/')] = p
    return out
