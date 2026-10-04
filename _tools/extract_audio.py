"""Extracts the game's CRI ADX2 (CRIWARE Atom) sound banks to browser-playable .ogg (Opus) files
plus an index `audio/audio.json` mapping cue names to files.

Inputs: StreamingAssets/res/raw/*.acb|*.awb and local_data/res_update/**/*.acb|*.awb (hashed names).
A bank whose internal Name exists in both places is taken from res_update (else newest mtime).

Formats (everything in @UTF is big-endian, everything in AFS2 little-endian):

@UTF table ('.acb' files, and nested tables in its data columns)
  0x00 '@UTF', 0x04 u32 table size (offsets below are relative to 0x08),
  0x0a u16 rows offset, 0x0c u32 strings offset, 0x10 u32 data offset, 0x14 u32 table-name
  string offset, 0x18 u16 column count, 0x1a u16 row width, 0x1c u32 row count.
  Columns from 0x20: flag u8 [+ u32 name string offset if flag&0x10]
  [+ constant value if flag&0x20]; flag&0x40 = value stored per row. Type = flag&0x0f:
  0..9 = u8 s8 u16 s16 u32 s32 u64 s64 f32 f64, 0xa = string (u32 offset into the
  NUL-terminated string pool), 0xb = data (u32 offset, u32 size into the data pool).
  Data columns that start with '@UTF' are sub-tables (CueTable, WaveformTable, ...).

ACB (header table 'Header', one row; this game is all 'ACB Format/PC Ver.1.40.0')
  CueNameTable(CueName, CueIndex) -> CueTable(ReferenceType, ReferenceIndex). Reference types:
    1 Waveform, 2 Synth, 3 Sequence, 8 BlockSequence.
  SynthTable.ReferenceItems = array of (u16 type, u16 index): 1 Waveform, 2 Synth, 3 Sequence.
  SequenceTable.TrackIndex = u16 array -> TrackTable.EventIndex -> TrackEventTable.Command,
    a list of (u16 code, u8 size, payload) commands; code 2000 (noteOn) / 2003 carry
    (u16 type, u16 index) with type 2 = Synth, 3 = Sequence.
  BlockSequenceTable(TrackIndex, BlockIndex) -> BlockTable(TrackIndex) -> tracks as above.
  WaveformTable: EncodeType (0 ADX, 2 HCA, 6 HCA-MX), Streaming (0 memory, 1 streaming,
    2 both = memory prefetch + full stream), MemoryAwbId / StreamAwbId (AFS2 file *ids*),
    StreamAwbPortNo (row of StreamAwbHash), NumChannels, SamplingRate, NumSamples, LoopFlag.
  AwbFile = embedded memory AFS2 archive.  StreamAwbHash(Name, Hash) = the streaming .awb;
  in this game the 16-byte Hash, hex-encoded, is exactly the hashed .awb filename.
  StreamAwbAfs2Header.Header = copy of that .awb's AFS2 header; it is used to verify the
  file found by hash, and to search all .awb files by header if the hash file is missing.

AFS2 ('.awb')
  0x00 'AFS2', 0x04 u8 version, 0x05 u8 offset size, 0x06 u8 id size, 0x08 u32 file count,
  0x0c u16 alignment, 0x0e u16 HCA key subkey; then count ids, then count+1 offsets.
  File i = [align_up(offset[i], alignment), offset[i+1]).

HCA ('HCA\\0', chunk names may carry 0x80 mask bits): 'fmt ' (channels, rate, frame count, encoder
  delay, padding), 'comp' (frame size, min/max resolution, track count, channel config, total/base/
  stereo band counts, bands per HFR group), optional 'ciph' (0 = plain, 1 = static key, 56 = keyed),
  'rva ' volume, 'loop'; then fixed-size frames, each 8 subframes x 128 MDCT coefficients per channel.
  All ~7k streams in this game are v3.0 and unencrypted (encrypted ones would be skipped: keys unknown).
  Decoding is done here in Python/numpy (hca_decode, a port of vgmstream's clHCA), not by ffmpeg:
  ffmpeg 8.1's 'hca' decoder mis-parses these v3.0 streams - its output has the right loudness and
  spectral envelope but is noise-like (no linear relation to the real MDCT coefficients, low speech
  periodicity, and the HFR/intensity-stereo BGM comes out heavily clipped). The bitstream parse here
  is self-checking: each frame's coefficient data must end inside the frame (it does, for every file).
  Decoded once through (loops not expanded), encoder delay/padding trimmed, piped to ffmpeg -> Opus 96k.
  ADX (EncodeType 0; none in this game) would go through ffmpeg's adx decoder.

Output: audio/<bank>/<cue>.ogg ('<cue>_<n>.ogg' when a cue plays several waveforms, e.g.
random/sequence/layered; such cues are listed in the bank's 'multi' and in the top-level 'multiCues'
{cue: [files]} instead of under their plain name in 'cueIndex'), audio/audio.json,
audio/extract_log.json (notes, cue-name collisions, per-file decode checks: decoded vs WaveformTable
duration, peak/RMS dB, clipped fraction, HCA frame overruns).
Incremental: existing outputs newer than their source are kept.
Usage: python extract_audio.py [bank-name-substring ...]   (filter = only those banks)
"""
import glob, json, os, re, struct, subprocess, sys, tempfile, time
from multiprocessing import Pool

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')  # one BLAS thread per worker process
import numpy as np

from config import GAME, RES_BASE, RES_UPDATE
BASE = RES_BASE + '/raw'
UPDATE = RES_UPDATE
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'audio')
CODEC = ['-c:a', 'libopus', '-b:a', '96k']
EXT = '.ogg'

# ---------------------------------------------------------------- @UTF

TYPES = {0: '>B', 1: '>b', 2: '>H', 3: '>h', 4: '>I', 5: '>i', 6: '>Q', 7: '>q', 8: '>f', 9: '>d'}


class Blob(bytes):
    """Data column value; .off is its absolute offset in the file it was parsed from."""


def utf(buf, off=0):
    """Parse the @UTF table at buf[off:] -> list of row dicts. Sub-tables are parsed recursively
    (in place, so Blob offsets stay absolute)."""
    if buf[off:off + 4] != b'@UTF':
        raise ValueError('not a @UTF table')
    rows_off, str_off, data_off, name_off, ncol, row_w, nrows = struct.unpack_from('>2xHIIIHHI', buf, off + 8)
    base = off + 8

    def string(o):
        st = base + str_off + o
        return buf[st:buf.index(b'\0', st)].decode('utf-8', 'replace')

    def value(t, p):
        if t in TYPES:
            return struct.unpack_from(TYPES[t], buf, p)[0], struct.calcsize(TYPES[t])
        if t == 0xA:
            return string(struct.unpack_from('>I', buf, p)[0]), 4
        if t == 0xB:
            o, n = struct.unpack_from('>II', buf, p)
            st = base + data_off + o
            if n >= 32 and buf[st:st + 4] == b'@UTF':
                return utf(buf, st), 8
            b = Blob(buf[st:st + n]); b.off = st
            return b, 8
        raise ValueError(f'unknown @UTF column type {t:#x}')

    cols, p = [], off + 32
    for _ in range(ncol):
        flag = buf[p]; p += 1
        name = ''
        if flag & 0x10:
            name = string(struct.unpack_from('>I', buf, p)[0]); p += 4
        const = None
        if flag & 0x20:
            const, n = value(flag & 0xF, p); p += n
        cols.append((name, flag, const))
    rows = []
    for r in range(nrows):
        p, row = base + rows_off + r * row_w, {}
        for name, flag, const in cols:
            if flag & 0x40:
                row[name], n = value(flag & 0xF, p); p += n
            else:
                row[name] = const
        rows.append(row)
    return rows


def table(header, name):
    v = header.get(name)
    return v if isinstance(v, list) else []


# ---------------------------------------------------------------- AFS2

def afs2(buf, off=0):
    """-> {id: (absolute offset, size)}, header length"""
    if buf[off:off + 4] != b'AFS2':
        raise ValueError('not an AFS2 archive')
    osz, isz = buf[off + 5], buf[off + 6]
    count, align = struct.unpack_from('<IH', buf, off + 8)
    fmt = {2: 'H', 4: 'I'}
    ids = struct.unpack_from('<%d%s' % (count, fmt[isz]), buf, off + 16)
    po = off + 16 + count * isz
    offs = struct.unpack_from('<%d%s' % (count + 1, fmt[osz]), buf, po)
    files = {}
    for i, fid in enumerate(ids):
        st = (offs[i] + align - 1) // align * align
        files[fid] = (off + st, offs[i + 1] - st)
    return files, po + (count + 1) * osz - off


# ---------------------------------------------------------------- cue resolution

def commands(blob):
    p = 0
    while p + 3 <= len(blob):
        code, size = struct.unpack_from('>HB', blob, p)
        yield code, blob[p + 3:p + 3 + size]
        p += 3 + size


def u16s(blob):
    return list(struct.unpack('>%dH' % (len(blob) // 2), blob)) if blob else []


class Resolver:
    def __init__(self, h):
        self.h = h
        self.t = {k: table(h, k) for k in ('SynthTable', 'SequenceTable', 'TrackTable', 'TrackEventTable',
                                            'CommandTable', 'BlockSequenceTable', 'BlockTable')}
        self.unknown = []

    def ref(self, kind, idx, depth=0):
        """-> ordered waveform indexes reached from (kind, idx); kind 1 wave, 2 synth, 3 sequence, 8 block seq"""
        if depth > 32 or idx == 0xFFFF:
            return []
        t = self.t
        if kind == 1:
            return [idx]
        if kind == 2:
            items = u16s(t['SynthTable'][idx]['ReferenceItems'])
            return [w for i in range(0, len(items) - 1, 2) for w in self.ref(items[i], items[i + 1], depth + 1)]
        if kind == 3:
            return [w for tr in u16s(t['SequenceTable'][idx]['TrackIndex']) for w in self.track(tr, depth)]
        if kind == 8:
            bs = t['BlockSequenceTable'][idx]
            out = [w for tr in u16s(bs['TrackIndex']) for w in self.track(tr, depth)]
            for b in u16s(bs['BlockIndex']):
                out += [w for tr in u16s(t['BlockTable'][b]['TrackIndex']) for w in self.track(tr, depth)]
            return out
        if kind:
            self.unknown.append(('reference type', kind))
        return []

    def track(self, tr, depth):
        ev = self.t['TrackTable'][tr]['EventIndex']
        events = self.t['TrackEventTable'] or self.t['CommandTable']
        if ev == 0xFFFF or ev >= len(events):
            return []
        out = []
        for code, payload in commands(events[ev]['Command']):
            if code in (2000, 2003) and len(payload) >= 4:
                typ, idx = struct.unpack_from('>HH', payload)
                if typ in (2, 3):
                    out += self.ref(typ, idx, depth + 1)
                else:
                    self.unknown.append(('noteOn type', typ))
        return out


# ---------------------------------------------------------------- bank discovery

def discover():
    acbs = [(p, p.replace('\\', '/').startswith(UPDATE)) for p in
            glob.glob(BASE + '/*.acb') + glob.glob(UPDATE + '/**/*.acb', recursive=True)]
    banks = {}
    for p, upd in acbs:
        name = utf(open(p, 'rb').read())[0]['Name']
        banks.setdefault(name, []).append(((upd, os.path.getmtime(p)), p))
    awbs = {}
    for p in sorted(glob.glob(BASE + '/*.awb')) + sorted(glob.glob(UPDATE + '/**/*.awb', recursive=True)):
        awbs[os.path.basename(p)[:-4].lower()] = p  # res_update listed last -> wins
    # name -> candidate .acb paths, preferred first (res_update, then newest)
    return {n: [p for k, p in sorted(c, reverse=True)] for n, c in banks.items()}, awbs


def afs2_file(path):
    """AFS2 table of contents of an .awb file without reading the audio."""
    with open(path, 'rb') as f:
        head = f.read(16)
        count = struct.unpack_from('<I', head, 8)[0]
        return afs2(head + f.read(count * (head[5] + head[6]) + head[5]))[0]


def find_stream_awb(hash_hex, header, awbs, notes):
    """Locate the streaming .awb: the file named after the hash, verified against the stored AFS2 header;
    else any .awb whose first bytes equal the stored header."""
    def head(q):
        with open(q, 'rb') as f:
            return f.read(len(header))
    p = awbs.get(hash_hex)
    if p and (not header or head(p) == header):
        return p
    notes.append(f'stream awb {hash_hex}: ' + ('header mismatch' if p else 'not found by hash') + ', searched by header')
    if header:
        for q in awbs.values():
            if head(q) == header:
                return q
    return None


def safe(name):
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', name).strip(' .') or '_'


def plan_bank(name, acb, awbs):
    """-> (bank json entry, jobs, notes)"""
    d = open(acb, 'rb').read()
    h = utf(d)[0]
    notes = []
    waves = table(h, 'WaveformTable')
    cues = table(h, 'CueTable')
    mem = afs2(d, h['AwbFile'].off)[0] if h.get('AwbFile') else {}
    streams = []  # per port: (path, {id: (off, size)})
    hashes = table(h, 'StreamAwbHash')
    headers = table(h, 'StreamAwbAfs2Header')
    for i, row in enumerate(hashes):
        hdr = bytes(headers[i]['Header']) if i < len(headers) else b''
        p = find_stream_awb(row['Hash'].hex(), hdr, awbs, notes)
        if p:
            streams.append((p, afs2_file(p)))
        else:
            streams.append((None, {}))
            notes.append(f'MISSING stream awb {row["Name"]} ({row["Hash"].hex()}.awb)')
    res = Resolver(h)
    entry = {'source': acb.replace('\\', '/'), 'cues': {}, 'multi': {}}
    jobs, used = [], set()
    names = {r['CueName'] for r in table(h, 'CueNameTable')}
    for cn in sorted(table(h, 'CueNameTable'), key=lambda r: r['CueIndex']):
        cue = cues[cn['CueIndex']]
        wl = list(dict.fromkeys(res.ref(cue['ReferenceType'], cue['ReferenceIndex'])))
        if not wl:
            notes.append(f'cue {cn["CueName"]}: empty cue, references no waveform '
                         f'(ReferenceType {cue["ReferenceType"]}, NumRelatedWaveforms {cue.get("NumRelatedWaveforms")})')
            continue
        for n, wi in enumerate(wl):
            w = waves[wi]
            cue_key = cn['CueName']
            if len(wl) > 1:  # '<cue>_<n>', kept distinct from real cue names such as '<cue>_2'
                cue_key = f'{cue_key}_{n}'
                while cue_key in names or cue_key in entry['cues']:
                    cue_key += '_'
            fn = safe(cue_key)
            while fn.lower() in used:
                fn += '_'
            used.add(fn.lower())
            st = w.get('Streaming', 0)
            src = None
            if st in (1, 2):
                port = w.get('StreamAwbPortNo') or 0
                sid = w.get('StreamAwbId', w.get('Id'))
                if port < len(streams) and sid in streams[port][1]:
                    src = (streams[port][0],) + streams[port][1][sid]
            if src is None and st == 0:
                mid = w.get('MemoryAwbId', w.get('Id'))
                if mid in mem:
                    src = (acb,) + mem[mid]
            if src is None:
                # (Streaming 2 waveforms only keep a few-frame prefetch in memory: not worth exporting)
                notes.append(f'MISSING {cue_key}: waveform {wi} data not found (Streaming {st})')
                continue
            rel = f'{safe(name)}/{fn}{EXT}'
            # duration/channels/rate from the stream's own header (a few WaveformTable NumSamples disagree with it)
            with open(src[0], 'rb') as f:
                f.seek(src[1])
                head = f.read(min(src[2], 1024))
            try:
                hh = hca_header(head)
                info = (hh['samples'] / hh['rate'], hh['channels'], hh['rate'])
            except (ValueError, KeyError, struct.error):
                info = (w['NumSamples'] / w['SamplingRate'], w['NumChannels'], w['SamplingRate'])
            entry['cues'][cue_key] = {'file': 'audio/' + rel, 'duration': round(info[0], 3), 'channels': info[1], 'rate': info[2]}
            if len(wl) > 1:
                entry['multi'].setdefault(cn['CueName'], []).append(cue_key)
            jobs.append({'src': src, 'dest': os.path.join(OUT, rel), 'encode': w['EncodeType'],
                         'samples': w['NumSamples'], 'rate': w['SamplingRate'], 'cue': cue_key, 'bank': name})
    if not entry['multi']:
        del entry['multi']
    for u in dict.fromkeys(res.unknown):
        notes.append(f'unhandled {u[0]} {u[1]}')
    return entry, jobs, notes


# ---------------------------------------------------------------- HCA decoder
# A port of the HCA v2/v3 decoding steps (as documented by vgmstream's clHCA). ffmpeg 8.1's own 'hca'
# decoder mis-parses this game's v3.0 streams (its output has the right spectral envelope but noise-like
# content; see the module docstring), so ffmpeg is only used for encoding.

MAX_BITS = (0, 2, 3, 3, 4, 4, 4, 4, 5, 6, 7, 8, 9, 10, 11, 12)
# prefix-code tables for resolutions 1..7, indexed [resolution << 4 | next MAX_BITS bits]
READ_BITS = (0,) * 16 + (
    1, 1, 2, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  2, 2, 2, 2, 2, 2, 3, 3, 0, 0, 0, 0, 0, 0, 0, 0,
    2, 2, 3, 3, 3, 3, 3, 3, 0, 0, 0, 0, 0, 0, 0, 0,  3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 4, 4,
    3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4,  3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4,
    3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4)
READ_VAL = (0,) * 16 + (
    0, 0, 1, -1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  0, 0, 1, 1, -1, -1, 2, -2, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 1, -1, 2, -2, 3, -3, 0, 0, 0, 0, 0, 0, 0, 0,  0, 0, 1, 1, -1, -1, 2, 2, -2, -2, 3, 3, -3, -3, 4, -4,
    0, 0, 1, 1, -1, -1, 2, 2, -2, -2, 3, -3, 4, -4, 5, -5,  0, 0, 1, 1, -1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -6,
    0, 0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -6, 7, -7)
INVERT = (14, 14, 14, 14, 14, 14, 13, 13, 13, 13, 13, 13, 12, 12, 12, 12, 12, 12, 11, 11, 11, 11, 11, 11,
          10, 10, 10, 10, 10, 10, 10, 9, 9, 9, 9, 9, 9, 8, 8, 8, 8, 8, 8, 7, 6, 6, 5, 4, 4, 4, 3, 3, 3,
          2, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1)
SCALING = [float(np.float32(np.sqrt(128) * 2 ** ((i - 63) * 53 / 128))) for i in range(64)]  # scalefactor -> gain
RANGE = [0.0] + [2 / (2 * r + 1) for r in range(1, 8)] + [2 / (2 ** (r - 3) - 1) for r in range(8, 16)]
CONVERT = [0.0] + [2 ** ((i - 63) * 53 / 128) for i in range(1, 128)]  # scalefactor difference -> ratio
INTENSITY = [(14 - i) / 7 for i in range(15)] + [0.0]
# MDCT window: rising half as float32 bits; the second half follows from Princen-Bradley (w[i]^2 + w[127-i]^2 = 1)
_W = struct.unpack('>64f', bytes.fromhex(
    '3A3504F03B0183B83B70C5383BBB92683C04A8093C3082003C61284C3C8B3F173CA839923CC77FBD3CE911103D0677CD'
    '3D198FC43D2DD35C3D4346433D59ECC13D71CBA83D85741E3D92A4133DA078B43DAEF5223DBE1C9E3DCDF27B3DDE7A1D'
    '3DEFB6ED3E00D62B3E0A2EDA3E13E72A3E1E00B13E287CF23E335D553E3EA3213E4A4F753E56633F3E62DF373E6FC3D1'
    '3E7D11383E8563A23E8C72B73E93B5613E9B2AEF3EA2D26F3EAAAAAB3EB2B2223EBAE7063EC347373ECBD03D3ED47F46'
    '3EDD51283EE6425C3EEF4EFF3EF872D73F00D4A93F0576CA3F0A1D3B3F0EC5483F136C253F180EF23F1CAAC23F213CA2'
    '3F25C1A53F2A36E73F2E99983F32E705'))
WINDOW = np.concatenate([_W, -np.sqrt(1 - np.array(_W[::-1]) ** 2)])
_k = np.arange(128)
DCT4 = np.sqrt(2 / 128) * np.cos(np.pi / 128 * (_k[:, None] + 0.5) * (_k[None, :] + 0.5))


def hca_header(b):
    """-> dict of the HCA header fields (chunk names may have their high bits set as a mask)."""
    if bytes(c & 0x7F for c in b[:4]) != b'HCA\0':
        raise ValueError('not HCA')
    version, hsize = struct.unpack_from('>HH', b, 4)
    h = {'version': version, 'header_size': hsize, 'ath': 0 if version >= 0x200 else 1, 'cipher': 0,
         'volume': 1.0, 'hfr_group': 0}
    p = 8
    while p + 4 <= hsize:
        sig = bytes(c & 0x7F for c in b[p:p + 4])
        if sig == b'fmt\0':
            h['channels'], h['rate'] = b[p + 4], int.from_bytes(b[p + 5:p + 8], 'big')
            h['frames'], h['delay'], h['padding'] = struct.unpack_from('>IHH', b, p + 8); p += 16
        elif sig == b'comp':
            (h['frame_size'], h['min_res'], h['max_res'], h['tracks'], h['chconfig'], h['total_bands'],
             h['base_bands'], h['stereo_bands'], h['hfr_group']) = struct.unpack_from('>HBBBBBBBB', b, p + 4); p += 16
        elif sig == b'dec\0':
            h['dec'] = True; p += 12
        elif sig == b'vbr\0':
            h['vbr'] = True; p += 8
        elif sig == b'ath\0':
            h['ath'] = struct.unpack_from('>H', b, p + 4)[0]; p += 6
        elif sig == b'loop':
            p += 16
        elif sig == b'ciph':
            h['cipher'] = struct.unpack_from('>H', b, p + 4)[0]; p += 6
        elif sig == b'rva\0':
            h['volume'] = struct.unpack_from('>f', b, p + 4)[0]; p += 8
        else:  # 'comm', 'pad\0': nothing needed after these
            break
    h['samples'] = h['frames'] * 1024 - h['delay'] - h['padding']
    return h


def hca_decode(b, stats=None):
    """HCA bytes -> (header, float32 PCM array (samples, channels)), encoder delay/padding trimmed.
    stats (optional dict) receives 'overrun' (frames whose data ran past the frame) and 'slack' (unused bits)."""
    h = hca_header(b)
    if h['cipher']:
        raise ValueError(f'encrypted (ciph type {h["cipher"]})')
    if h.get('dec') or h.get('vbr') or h['ath'] or h['version'] < 0x200:
        raise NotImplementedError('HCA v1 / VBR / ATH-curve streams are not implemented')
    v3 = h['version'] >= 0x300
    nch, base, stereo, total, bpg = h['channels'], h['base_bands'], h['stereo_bands'], h['total_bands'], h['hfr_group']
    hfr_groups = (total - base - stereo + bpg - 1) // bpg if bpg else 0
    types = [0] * nch  # 0 discrete, 1 stereo primary, 2 stereo secondary (intensity stereo)
    per_track = nch // h['tracks']
    if stereo and per_track > 1:
        if per_track > 4 or (per_track == 4 and h['chconfig']):
            raise NotImplementedError(f'{nch}-channel intensity stereo layout')
        for t in range(0, nch, per_track):
            types[t:t + 2] = [1, 2]
            if per_track == 4:
                types[t + 2:t + 4] = [1, 2]
    coded = [base + stereo if t != 2 else base for t in types]
    fsz, minr, maxr, hp = h['frame_size'], h['min_res'], h['max_res'], h['header_size']
    nframes = min(h['frames'], (len(b) - hp) // fsz)
    spectra = np.zeros((nframes, nch, 8, 128), np.float32)
    rnd, overrun, slack = 1, 0, 0
    for f in range(nframes):
        v = int.from_bytes(b[hp + f * fsz: hp + (f + 1) * fsz], 'big')
        nbits = fsz * 8
        pos = 0

        def read(k):
            nonlocal pos
            pos += k
            return (v >> (nbits - pos)) & ((1 << k) - 1) if pos <= nbits else 0
        if read(16) != 0xFFFF:
            raise ValueError(f'bad frame sync at frame {f}')
        packed_noise = (read(9) << 8) - read(7)
        chs = []
        for c in range(nch):
            t, cc = types[c], coded[c]
            # scalefactors (v3: the HFR group scales follow as extra scalefactors)
            cs = cc + (hfr_groups if t != 2 and v3 else 0)
            sf = [0] * 128
            dbits = read(3)
            if dbits >= 6:
                for i in range(cs):
                    sf[i] = read(6)
            elif dbits:
                emax = (1 << dbits) - 1
                val = sf[0] = read(6)
                for i in range(1, cs):
                    d = read(dbits)
                    val = read(6) if d == emax else (val - (emax >> 1) + d) & 0x3F
                    sf[i] = val
            inten = None
            if t == 2:  # intensity ratios for the 8 subframes
                val = read(4)
                if val >= 15:
                    inten = [7] * 8 if v3 else [15] * 8
                elif not v3:
                    inten = [val] + [read(4) for _ in range(7)]
                else:
                    db2 = read(2)
                    inten = [val]
                    if db2 == 3:
                        inten += [read(4) for _ in range(7)]
                    else:
                        bmax = (2 << db2) - 1
                        for _ in range(7):
                            d = read(db2 + 1)
                            val = read(4) if d == bmax else val - (bmax >> 1) + d
                            inten.append(min(max(val, 0), 15))
            elif not v3 and hfr_groups:
                sf[128 - hfr_groups:] = [read(6) for _ in range(hfr_groups)]
            # bit allocation per band (the ATH curve is all zero for v2+ type-0 streams)
            res = [0] * 128
            noises = [0] * 128
            nn = nv = 0
            for i in range(cc):
                s = sf[i]
                if s:
                    cp = ((packed_noise + i) >> 8) + 1 - ((5 * s) >> 1)
                    r = 15 if cp < 0 else (INVERT[cp] if cp <= 65 else 0)
                    r = maxr if r > maxr else minr if r < minr else r
                    res[i] = r
                    if r:
                        noises[127 - nv] = i; nv += 1
                    else:
                        noises[nn] = i; nn += 1
            gain = [SCALING[sf[i]] * RANGE[res[i]] for i in range(cc)]
            hfr = (sf[cc:cc + hfr_groups] if v3 else sf[128 - hfr_groups:]) if hfr_groups and t != 2 else None
            chs.append((t, cc, sf, inten, res, noises, nn, nv, gain, hfr))
        for sub in range(8):
            spec = spectra[f, :, sub]
            for c in range(nch):  # dequantize
                cc, res, gain, sp = coded[c], chs[c][4], chs[c][8], spec[c]
                for i in range(cc):
                    r = res[i]
                    if r > 7:
                        code = read(MAX_BITS[r])
                        q = (code >> 1) * (1 - ((code & 1) << 1))
                        if not q:
                            pos -= 1  # zero has no sign bit
                    elif r:
                        bits = MAX_BITS[r]
                        idx = (r << 4) + read(bits)
                        pos += READ_BITS[idx] - bits
                        q = READ_VAL[idx]
                    else:
                        continue
                    sp[i] = gain[i] * q
            for c in range(nch):
                t, cc, sf, inten, res, noises, nn, nv, gain, hfr = chs[c]
                sp = spec[c]
                if minr == 0 and nv and nn:  # noise fill for bands that got no bits (v3)
                    for i in range(nn):
                        rnd = (0x343FD * rnd + 0x269EC3) & 0xFFFFFFFF
                        ni, vi = noises[i], noises[128 - nv + (((rnd & 0x7FFF) * nv) >> 15)]
                        sc = sf[ni] - sf[vi] + 62
                        sp[ni] = CONVERT[sc if sc > 0 else 0] * sp[vi]
                if hfr:  # high-frequency reconstruction: mirror lower bands scaled by the group scale
                    hb = base + stereo
                    lb = hb - 1
                    limit = hfr_groups >> 1 if v3 else hfr_groups
                    for g in range(hfr_groups):
                        step = 1 if g < limit else 0
                        for _ in range(bpg):
                            if hb >= total or lb < 0:
                                break
                            sc = hfr[g] - sf[lb] + 63
                            sp[hb] = CONVERT[sc if sc > 0 else 0] * sp[lb]
                            hb += 1
                            lb -= step
                    sp[127] = 0
            for c in range(nch - 1):  # intensity stereo
                if types[c] == 1:
                    rl = INTENSITY[chs[c + 1][3][sub]]
                    spec[c + 1, base:total] = spec[c, base:total] * (2.0 - rl)
                    spec[c, base:total] *= rl
        if pos > nbits - 16:
            overrun += 1
        slack += nbits - 16 - pos
    if stats is not None:
        stats.update(overrun=overrun, slack=slack / max(nframes, 1))
    # IMDCT: DCT-IV per 128-sample subframe, windowed overlap-add
    out = np.zeros((nframes * 1024, nch), np.float32)
    for c in range(nch):
        D = spectra[:, c].reshape(-1, 128) @ DCT4
        y = np.empty_like(D)
        y[:, :64] = WINDOW[:64] * D[:, 64:]
        y[:, 64:] = WINDOW[64:] * D[:, ::-1][:, :64]
        y[1:, :64] += WINDOW[::-1][:64] * D[:-1, :64][:, ::-1]
        y[1:, 64:] -= WINDOW[:64][::-1] * D[:-1, :64]
        out[:, c] = y.ravel()
    out *= h['volume']
    return h, out[h['delay']:h['delay'] + h['samples']]


# ---------------------------------------------------------------- per-batch job

BATCH_FILES, BATCH_SAMPLES = 40, 40_000_000  # per ffmpeg launch (launching ffmpeg is the slow part on Windows)


def encode(items):
    """items: [(raw pcm path or (fmt, path), rate, channels, part path)] -> ffmpeg returncode, stderr.
    One ffmpeg process with one input/output pair per item."""
    args = ['ffmpeg', '-v', 'error', '-y']
    for src, rate, ch, part in items:
        if isinstance(src, tuple):
            args += ['-f', src[0], '-i', src[1]]
        else:
            args += ['-f', 'f32le', '-ar', str(rate), '-ac', str(ch), '-i', src]
    for i, (src, rate, ch, part) in enumerate(items):
        args += ['-map', f'{i}:a', *CODEC, part]
    r = subprocess.run(args, capture_output=True)
    return r.returncode, r.stderr.decode(errors='replace').strip()[-300:]


def decode_batch(jobs):
    """Decode a batch of waveforms to temporary raw PCM, then encode them with a single ffmpeg call.
    Outputs are written as '<dest>.part.ogg' and renamed, so an interrupted run leaves no truncated files."""
    tmpdir = tempfile.mkdtemp(prefix='extract_audio_')
    results, items = [], []
    try:
        for n, job in enumerate(jobs):
            path, off, size = job['src']
            with open(path, 'rb') as f:
                f.seek(off)
                data = f.read(size)
            res = {'cue': job['cue'], 'bank': job['bank'], 'out': os.path.relpath(job['dest'], OUT).replace('\\', '/'),
                   'expected': round(job['samples'] / job['rate'], 4)}
            results.append(res)
            raw = os.path.join(tmpdir, f'{n}.raw')
            if bytes(c & 0x7F for c in data[:4]) == b'HCA\0':
                stats = {}
                try:
                    h, pcm = hca_decode(data, stats)
                except Exception as e:
                    res['status'] = f'skipped: {e}'
                    continue
                res['frame_overruns'] = stats['overrun']
                res['clipped'] = round(float((np.abs(pcm) > 1).mean()), 5) if len(pcm) else 0.0
                np.clip(pcm, -1, 1, out=pcm)  # what the game's 16-bit output stage does anyway
                res['decoded'] = round(len(pcm) / h['rate'], 4)
                p64 = pcm.astype(np.float64)
                res['peak_db'] = round(20 * np.log10(max(float(np.abs(p64).max(initial=0)), 1e-10)), 1)
                res['rms_db'] = round(10 * np.log10(max(float(np.mean(p64 ** 2)) if len(p64) else 0, 1e-20)), 1)
                pcm.tofile(raw)
                items.append((raw, h['rate'], h['channels'], res, job))
            elif data[:2] == b'\x80\x00':  # CRI ADX: ffmpeg's decoder handles it
                open(raw, 'wb').write(data)
                items.append((('adx', raw), 0, 0, res, job))
            else:
                res['status'] = f'skipped: unsupported data (EncodeType {job["encode"]}, magic {data[:4].hex()})'
        for src, rate, ch, res, job in items:
            os.makedirs(os.path.dirname(job['dest']), exist_ok=True)
        part = lambda job: job['dest'] + '.part' + EXT
        code, err = encode([(src, rate, ch, part(job)) for src, rate, ch, res, job in items]) if items else (0, '')
        for src, rate, ch, res, job in items:
            if code:  # find the culprit: redo one by one
                code1, err1 = encode([(src, rate, ch, part(job))])
                if code1:
                    res['status'] = 'ffmpeg error: ' + err1
                    if os.path.exists(part(job)):
                        os.remove(part(job))
                    continue
            os.replace(part(job), job['dest'])
            res['status'] = 'ok'
    finally:
        for f in os.listdir(tmpdir):
            os.remove(os.path.join(tmpdir, f))
        os.rmdir(tmpdir)
    return results


def batches(jobs):
    cur, total = [], 0
    for j in jobs:
        n = j['samples'] * 2
        if cur and (len(cur) >= BATCH_FILES or total + n > BATCH_SAMPLES):
            yield cur
            cur, total = [], 0
        cur.append(j)
        total += n
    if cur:
        yield cur


def main():
    t0 = time.time()
    only = [a.lower() for a in sys.argv[1:]]
    banks, awbs = discover()
    print(len(banks), 'banks,', len(awbs), 'awb files', flush=True)
    index = {'banks': {}, 'cueIndex': {}}
    jobs, notes, collisions = [], {}, []
    for name in sorted(banks, key=str.lower):
        if only and not any(o in name.lower() for o in only):
            continue
        # Use the preferred copy of the bank unless its streaming .awb is missing and an older copy is complete.
        plans = []
        for acb in banks[name]:
            plans.append(plan_bank(name, acb, awbs))
            if not any(n.startswith('MISSING') for n in plans[-1][2]):
                break
        entry, bj, bn = plans[-1] if not any(n.startswith('MISSING') for n in plans[-1][2]) else plans[0]
        if len(plans) > 1:
            bn = bn + [f'preferred copy {banks[name][0]} incomplete ({sum(n.startswith("MISSING") for n in plans[0][2])} '
                       f'missing), ' + (f'used {entry["source"]}' if entry is not plans[0][0] else 'no complete copy')]
        index['banks'][name] = entry
        if bn:
            notes[name] = bn
        for cue, c in entry['cues'].items():
            if cue in index['cueIndex']:
                collisions.append((cue, name))
            else:
                index['cueIndex'][cue] = c['file']
        jobs += bj
    todo = [j for j in jobs if not (os.path.exists(j['dest']) and os.path.getmtime(j['dest']) >= os.path.getmtime(j['src'][0]))]
    print(f'{len(index["banks"])} banks, {len(jobs)} files, {len(todo)} to decode, {len(collisions)} cue-name collisions', flush=True)
    log = []
    if todo:
        with Pool(min(16, os.cpu_count() or 4)) as pool:
            for rs in pool.imap_unordered(decode_batch, list(batches(todo))):
                for r in rs:
                    log.append(r)
                    if r['status'] != 'ok':
                        print(r['status'], r['out'], flush=True)
                    if len(log) % 500 == 0:
                        print(len(log), '/', len(todo), f'{time.time() - t0:.0f}s', flush=True)
    os.makedirs(OUT, exist_ok=True)
    failed = {'audio/' + r['out'] for r in log if r['status'] != 'ok'}
    for entry in index['banks'].values():  # don't index files that could not be produced
        entry['cues'] = {k: c for k, c in entry['cues'].items() if c['file'] not in failed}
    index['cueIndex'] = {k: f for k, f in index['cueIndex'].items() if f not in failed}
    index['banks'] = dict(sorted(index['banks'].items()))
    # Only rewrite the full index on an unfiltered run; a filtered run merges into the existing one.
    path = os.path.join(OUT, 'audio.json')
    if only and os.path.exists(path):
        old = json.load(open(path, encoding='utf-8'))
        old['banks'].update(index['banks'])
        index = {'banks': dict(sorted(old['banks'].items())), 'cueIndex': {}}
        for name, entry in index['banks'].items():
            for cue, c in entry['cues'].items():
                index['cueIndex'].setdefault(cue, c['file'])
    # cues that play several waveforms: cue name -> its '<cue>_<n>' files (not in cueIndex under the plain name)
    index['multiCues'] = {}
    for name, entry in index['banks'].items():
        for cue, keys in entry.get('multi', {}).items():
            files = [entry['cues'][k]['file'] for k in keys if k in entry['cues']]
            if files:
                index['multiCues'].setdefault(cue, files)
    json.dump(index, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    logpath = os.path.join(OUT, 'extract_log.json')
    if os.path.exists(logpath):  # carry over the checks of files kept from earlier runs
        done = {r['out'] for r in log}
        wanted = {os.path.relpath(j['dest'], OUT).replace('\\', '/') for j in jobs}
        log += [r for r in json.load(open(logpath, encoding='utf-8')).get('decoded', [])
                if r['out'] not in done and r['out'] in wanted and r['status'] == 'ok']
    bad = [r for r in log if r['status'] != 'ok']
    ok = [r for r in log if r['status'] == 'ok']
    mism = [r for r in ok if 'decoded' in r and abs(r['decoded'] - r['expected']) > 0.001]
    silent = [r for r in ok if r.get('peak_db', 0) < -50]
    overrun = [r for r in ok if r.get('frame_overruns')]
    json.dump({'notes': notes, 'collisions': collisions, 'failed': bad, 'duration_mismatch': mism, 'silent': silent,
               'frame_overruns': overrun, 'decoded': log},
              open(os.path.join(OUT, 'extract_log.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'done in {time.time() - t0:.0f}s: {len(ok)} decoded, {len(bad)} failed/skipped, {len(mism)} duration mismatches, '
          f'{len(silent)} near-silent (peak < -50 dB), {len(overrun)} with HCA frame overruns, '
          f'{sum(map(len, notes.values()))} notes, {len(collisions)} cue-name collisions')


if __name__ == '__main__':
    main()
