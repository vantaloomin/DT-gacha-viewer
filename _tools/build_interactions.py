"""Builds interactions.json: how the game makes each hero illustration react to taps, plus the
voice cue ids it plays. Keyed by the extracted .skel path (same keys as manifest.json).

Game data (o_t.db):
  SpineRole        id=prefab, SpineDefaultAct, Click (int list -> SpineRoleClick), NormalSkin, RestrictedSkin
  SpineRoleClick   id, ClickAct (-> SpineRoleAct), ClickArea (strings "x_y_w_h": centre + size in skeleton units,
                   origin at the 2340x1080 screen centre)
  SpineRoleAct     a small state machine. NormalLoopAct / NormalOnceAct / SpecialLoopAct / SpecialOnceAct are
                   lists of (track, animation). "Special" entries are the restricted layer (extra motion on
                   track 1). NextAct follows once the act's one-shot animations finish (or after
                   MinimumSwitchTime for loop-only acts); Cancel lists the clicks allowed to interrupt it;
                   RestrictedTag acts only exist in restricted mode.
  RoleDress        SpineModel (prefab), AppearVol (voice cue id), ClickVol (pairs: animation -> voice cue id)
  ResVoice         voice cue id -> per-language cue names (jaJP / zhCN / zhTW)
Binary columns (__BIN__*) are little-endian: uint32 count, then items; strings are uint32 length + UTF-8.
"""
import json, os, sqlite3, struct

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
from config import DB


class Reader:
    def __init__(self, b): self.b, self.o = b or b'\0\0\0\0', 0
    def u32(self): v = struct.unpack_from('<i', self.b, self.o)[0]; self.o += 4; return v
    def str(self): n = self.u32(); s = self.b[self.o:self.o + n].decode('utf-8', 'replace'); self.o += n; return s

def ints(b): r = Reader(b); return [r.u32() for _ in range(r.u32())]
def strs(b): r = Reader(b); return [r.str() for _ in range(r.u32())]
def act_list(b): r = Reader(b); return [[r.u32(), r.str()] for _ in range(r.u32())]
def pairs(b): r = Reader(b); return [[r.str(), r.str()] for _ in range(r.u32())]


o = sqlite3.connect(f'file:{DB}/o_t.db?mode=ro', uri=True)
prefab_dirs = json.load(open(os.path.join(HERE, 'prefab_dirs.json')))
manifest = json.load(open(os.path.join(ROOT, 'manifest.json'), encoding='utf-8'))
skel_by_dir = {r['skel'].rsplit('/', 1)[0]: r['skel'] for r in manifest}
def skel_for(prefab):
    d = prefab_dirs.get((prefab or '').lower())
    return skel_by_dir.get(d) if d else None

acts = {}
for id_, cancel, min_sw, nxt, nl, no, restricted, sl, so in o.execute(
        'select id, __BIN__Cancel, MinimumSwitchTime, NextAct, __BIN__NormalLoopAct, __BIN__NormalOnceAct, '
        'RestrictedTag, __BIN__SpecialLoopAct, __BIN__SpecialOnceAct from SpineRoleAct'):
    acts[id_] = {'next': nxt or 0, 'minSwitch': min_sw or 0, 'cancel': ints(cancel), 'restricted': bool(restricted),
                 'normalLoop': act_list(nl), 'normalOnce': act_list(no), 'specialLoop': act_list(sl), 'specialOnce': act_list(so)}
clicks = {id_: {'id': id_, 'act': act, 'areas': [[float(v) for v in a.split('_')] for a in strs(area)]}
          for id_, act, area in o.execute('select id, ClickAct, __BIN__ClickArea from SpineRoleClick')}

voice_cols = [r[1] for r in o.execute('pragma table_info(ResVoice)')]
res_voice = {r[0]: {'ja': r[1], 'zh': r[2], 'tw': r[3]} for r in o.execute('select id, jaJP, zhCN, zhTW from ResVoice')}
def voice(cue_id):
    if not cue_id:
        return None
    v = res_voice.get(cue_id, {})
    return {'id': cue_id, **{k: x for k, x in v.items() if x}}

out = {}
for prefab, default_act, click_ids, normal_skin, restricted_skin in o.execute(
        'select id, SpineDefaultAct, __BIN__Click, NormalSkin, RestrictedSkin from SpineRole'):
    skel = skel_for(prefab)
    if not skel:
        continue
    cl = [clicks[c] for c in ints(click_ids) if c in clicks]
    # every act reachable from the default act and the clicks
    reach, todo = {}, [default_act] + [c['act'] for c in cl]
    while todo:
        a = todo.pop()
        if a in reach or a not in acts:
            continue
        reach[a] = acts[a]
        todo += [acts[a]['next']] + [clicks[c]['act'] for c in acts[a]['cancel'] if c in clicks]
    out[skel] = {'defaultAct': default_act if default_act in acts else None, 'acts': {str(k): v for k, v in reach.items()},
                 'clicks': cl, 'normalSkin': normal_skin or None, 'restrictedSkin': restricted_skin or None, 'voices': {}}

# Voices come from the outfit that uses the rig
for prefab, appear, click_vol in o.execute('select SpineModel, AppearVol, __BIN__ClickVol from RoleDress where SpineModel != ""'):
    skel = skel_for(prefab)
    if not skel:
        continue
    entry = out.setdefault(skel, {'defaultAct': None, 'acts': {}, 'clicks': [], 'normalSkin': None, 'restrictedSkin': None, 'voices': {}})
    v = entry['voices']
    if appear and 'appear' not in v:
        v['appear'] = voice(appear)
    for anim, cue in pairs(click_vol):
        v.setdefault('anims', {}).setdefault(anim, voice(cue))

json.dump(out, open(os.path.join(ROOT, 'interactions.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f"{len(out)} rigs: {sum(1 for e in out.values() if e['clicks'])} with tap zones, "
      f"{sum(1 for e in out.values() if e['voices'])} with voice lines, "
      f"{sum(len(e['clicks']) for e in out.values())} tap zones total")
