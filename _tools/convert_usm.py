"""Converts the game's CRIWARE .usm videos to .webm (lossless remux, no re-encode).

USM layout: a sequence of chunks, each
  sig[4] ('CRID' | '@SFV' video | '@SFA' audio | '@ALP' alpha), size u32 BE,
  +9 data offset u8, +10 padding u16 BE, +12 channel u8, +15 type (low 2 bits: 0 = data).
Payload = bytes [8 + data_offset, 8 + size - padding). In this game the video payloads
(unencrypted) concatenate into a VP9 IVF stream, which ffmpeg copies into WebM.
Names come from RoleDress.HeroShow / HeroShowLoop (hero showcase videos); others keep
the original filename stored in the CRID header, sorted into folders by prefix.
"""
import glob, json, os, re, sqlite3, struct, subprocess, sys, tempfile
from multiprocessing import Pool

from config import GAME, DB, RES_BASE, RES_UPDATE
ROOTS = [RES_BASE + '/raw', RES_UPDATE]
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'videos')


def chunks(d):
    o = 0
    while o + 16 <= len(d):
        size = struct.unpack('>I', d[o + 4:o + 8])[0]
        doff, pad = d[o + 9], struct.unpack('>H', d[o + 10:o + 12])[0]
        yield d[o:o + 4], d[o + 12], d[o + 15] & 3, d[o + 8 + doff:o + 8 + size - pad]
        o += 8 + size


def original_name(d):
    m = re.search(rb'([\w.-]+)\.usm', d[:4096])
    return m.group(1).decode() if m else None


def text(b):
    return b[4:4 + struct.unpack('<I', b[:4])[0]].decode('utf-8', 'replace') if isinstance(b, bytes) and len(b) >= 4 else ''


def hero_show_names():
    """original video name (no .usm) -> 'Title - Subtitle - intro|loop'"""
    o = sqlite3.connect(f'file:{DB}/o_t.db?mode=ro', uri=True)
    h = sqlite3.connect(f'file:{DB}/h_n.db?mode=ro', uri=True)
    lang = {k: text(v) for c in (o, h) for t in ('Heroes_Lang', 'RoleDress_Lang')
            if c.execute('select 1 from sqlite_master where name=?', (t,)).fetchone()
            for k, v in c.execute(f'select id, __BIN__enUS from {t}')}
    heroes = {i: (lang.get(t, ''), lang.get(n, '')) for i, n, t in h.execute('select id, LangHeroName, LangTitle from Heroes')}
    names = {}
    for hid, dress, show, loop in o.execute('select BelongHero, LangName, HeroShow, HeroShowLoop from RoleDress order by id'):
        personal, cls = heroes.get(hid, ('', ''))
        outfit = lang.get(dress, '')
        title = personal or cls or outfit
        sub = ' · '.join(dict.fromkeys(x for x in (cls if personal else '', outfit if outfit not in (personal, cls) else '') if x and x != title))
        base = re.sub(r'[\\/:*?"<>|]+', '', f'{title} - {sub}' if sub else title).strip()
        for vid, kind in ((show, 'intro'), (loop, 'loop')):
            if vid and title:
                names.setdefault(vid[:-4].lower(), f'{base} - {kind}')
    return names


def category(name):
    n = name.lower()
    for prefix, folder in (('plot_', 'story'), ('gacha', 'gacha'), ('hexie_gacha', 'gacha'), ('job_', 'class'),
                           ('myth', 'myths'), ('hero_ultraskill', 'ultimate_skills'), ('av', 'events')):
        if n.startswith(prefix):
            return folder
    return 'other'


def convert(job):
    """Video is remuxed as-is. An @SFA track (CRI ADX audio) is encoded to Opus; an @ALP
    track (MPEG greyscale alpha mask) is merged in, which requires re-encoding the VP9."""
    src, dest = job
    if os.path.exists(dest) and os.path.getmtime(dest) >= os.path.getmtime(src) and '--full' not in sys.argv:
        return src, dest, 'up to date', []
    d = open(src, 'rb').read()
    streams = {}
    for sig, ch, typ, payload in chunks(d):
        if typ == 0 and ch == 0:
            streams.setdefault(sig, bytearray()).extend(payload)
    kinds = sorted(s.decode(errors='replace') for s in streams)
    video = streams.get(b'@SFV', b'')
    if not video.startswith(b'DKIF'):
        return src, dest, 'skipped: video stream is not IVF/VP9', kinds
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmps = []
    def tmpfile(data, suffix):
        fd, path = tempfile.mkstemp(suffix=suffix); os.write(fd, data); os.close(fd); tmps.append(path); return path
    inputs = ['-i', tmpfile(video, '.ivf')]
    opts = ['-map', '0:v', '-c:v', 'copy']
    if b'@ALP' in streams:
        inputs += ['-i', tmpfile(streams[b'@ALP'], '.m2v')]
        w, h = struct.unpack('<HH', video[12:16])  # the alpha mask is padded to a multiple of 16; crop it
        opts = ['-filter_complex', f'[1:v]crop={w}:{h}:0:0,format=gray[a];[0:v][a]alphamerge[v]', '-map', '[v]',
                '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p', '-crf', '20', '-b:v', '0', '-row-mt', '1']
    if b'@SFA' in streams:
        audio_index = len(inputs) // 2
        inputs += ['-f', 'adx', '-i', tmpfile(streams[b'@SFA'], '.adx')]
        opts += ['-map', f'{audio_index}:a', '-c:a', 'libopus', '-b:a', '160k']
    try:
        r = subprocess.run(['ffmpeg', '-v', 'error', '-y', *inputs, *opts, dest], capture_output=True, text=True)
    finally:
        for t in tmps:
            os.remove(t)
    return src, dest, (r.stderr.strip()[:200] or 'ok') if r.returncode else 'ok', kinds


if __name__ == '__main__':
    shows = hero_show_names()
    # Original name -> newest file (res_update overrides the base install).
    files = {}
    for root in ROOTS:
        for p in glob.glob(root + '/**/*.usm', recursive=True):
            with open(p, 'rb') as f:
                orig = original_name(f.read(4096)) or os.path.basename(p)[:-4]
            files[orig.lower()] = (orig, p)
    jobs, used = [], set()
    for key, (orig, p) in sorted(files.items()):
        if key in shows:
            rel = os.path.join('hero_shows', shows[key])
            if rel.lower() in used:
                rel += f' ({orig})'
        else:
            rel = os.path.join(category(orig), orig)
        used.add(rel.lower())
        jobs.append((p, os.path.join(OUT, rel + '.webm')))
    print(len(jobs), 'videos', flush=True)
    log = []
    with Pool(8) as pool:
        for i, (src, dest, status, kinds) in enumerate(pool.imap_unordered(convert, jobs)):
            log.append({'src': src, 'out': os.path.relpath(dest, OUT), 'status': status, 'streams': kinds})
            if status not in ('ok', 'up to date') or set(kinds) - {'@SFV'}:
                print(status, kinds, os.path.relpath(dest, OUT), flush=True)
            if i % 50 == 0:
                print(i, flush=True)
    json.dump(log, open(os.path.join(OUT, 'convert_log.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('done:', sum(l['status'] == 'ok' for l in log), 'converted,', sum(l['status'] == 'up to date' for l in log), 'up to date, of', len(log))
