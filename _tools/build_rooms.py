"""Builds rooms.json: how the game assembles layered Spine rigs (goddess rooms and other "SpineRoleEx" rigs)
and the room background each goddess sits in. Keyed by the extracted .skel path (same keys as manifest.json).

These rigs don't work like hero illustrations: the game combines several skins at once (a base skin plus one
choice per part, e.g. hair colour, horns, throne) and, before each idle loop, applies a zero-length "pre"
animation that switches on the attachments that loop expects. Played on their own they show missing hair,
blank faces and so on.

Game data:
  o_t.db SpineRoleEx          id=prefab, MainSkin, SubSkin (pairs: part -> "optionA-optionB"),
                              MainAnimList (-> SpineRoleExMainAnim), DefaultMainAnim
  o_t.db SpineRoleExMainAnim  Anim (list of (track, animation)), PreAnim, InitSkin (pairs: part -> skin)
  b_g.db GoddessRoom          SpineRole (prefab), RoomPrefab (UI prefab, e.g. GoddessLoki.prefab, whose
                              background is gui/bigimage/goddess/bigimg_goddness<name>_bg.png)

Room placement: the background is scaled to the game's 1080-unit screen height and the skeleton origin sits at
GoddessRoom.Offset (0.5, 0.5: the background's centre). Checked by registering a render of Loki's rig against her
background: her throne lines up with the painted throne at 1 unit = 1411/1080 px, origin (0.4995, 0.505).
"""
import json, os, sqlite3, struct
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
from config import DB

SCREEN_H = 1080   # the game's screen height in skeleton units


class Reader:
    def __init__(self, b): self.b, self.o = b or b'\0\0\0\0', 0
    def u32(self): v = struct.unpack_from('<i', self.b, self.o)[0]; self.o += 4; return v
    def str(self): n = self.u32(); s = self.b[self.o:self.o + n].decode('utf-8', 'replace'); self.o += n; return s

def ints(b): r = Reader(b); return [r.u32() for _ in range(r.u32())]
def pairs(b): r = Reader(b); return [[r.str(), r.str()] for _ in range(r.u32())]
def act_list(b): r = Reader(b); return [[r.u32(), r.str()] for _ in range(r.u32())]


o = sqlite3.connect(f'file:{DB}/o_t.db?mode=ro', uri=True)
g = sqlite3.connect(f'file:{DB}/b_g.db?mode=ro', uri=True)
prefab_dirs = json.load(open(os.path.join(HERE, 'prefab_dirs.json')))
manifest = json.load(open(os.path.join(ROOT, 'manifest.json'), encoding='utf-8'))
skel_by_dir = {r['skel'].rsplit('/', 1)[0]: r['skel'] for r in manifest}
def skel_for(prefab):
    d = prefab_dirs.get((prefab or '').lower())
    return skel_by_dir.get(d) if d else None

main_anims = {id_: {'anims': act_list(anim), 'pre': pre or None, 'initSkin': pairs(init)}
              for id_, anim, pre, init in o.execute('select id, __BIN__Anim, PreAnim, __BIN__InitSkin from SpineRoleExMainAnim')}

out = {}
for prefab, main_skin, sub_skin, anim_list, default in o.execute(
        'select id, MainSkin, __BIN__SubSkin, __BIN__MainAnimList, DefaultMainAnim from SpineRoleEx'):
    skel = skel_for(prefab)
    if not skel:
        continue
    options = {part: choices.split('-') for part, choices in pairs(sub_skin)}
    first = main_anims.get(default) or next((main_anims[i] for i in ints(anim_list) if i in main_anims), None)
    chosen = dict(first['initSkin']) if first else {}
    for part, choices in options.items():
        chosen.setdefault(part, choices[0])
    pre = {}
    for i in ints(anim_list):
        m = main_anims.get(i)
        if m and m['pre']:
            for track, name in m['anims']:
                if track == 0:
                    pre.setdefault(name, m['pre'])
    out[skel] = {
        'skins': [s for s in [main_skin or 'default', *chosen.values()] if s],
        'skinOptions': options,
        'pre': pre,
        'anim': next((n for t, n in first['anims'] if t == 0), None) if first else None,
    }

# Goddess rooms: background image and placement
rooms = 0
for prefab, room_prefab, offset in g.execute('select SpineRole, RoomPrefab, __BIN__Offset from GoddessRoom'):
    skel = skel_for(prefab)
    room = (room_prefab or '').lower().replace('.prefab', '').replace('goddess', '', 1)
    bg = f'images/goddess/bigimg_goddness{room}_bg.png'
    if not skel or skel not in out or not os.path.exists(os.path.join(ROOT, bg)):
        continue
    w, h = Image.open(os.path.join(ROOT, bg)).size
    # The rig sits at the room's centre (GoddessRoom.Offset is the room's starting scroll position, not this)
    out[skel]['room'] = {'bg': bg, 'size': [w, h], 'origin': [0.5, 0.5], 'unitPx': h / SCREEN_H}
    rooms += 1

# ---- Tap interactions (the game's room behaviour; semantics from its hotfix code) ----
# SpineRoleExEvent: Type 1 switch main state, 2 one-shot, 3 change state (part on/off, track 1, additive, held),
# 4 drag a bone (played here as a tap), 5 switch a sub-skin. ClickArea "x_y_w_h_rot": centre/size in skeleton units
# (y up), rotation in degrees. Condition/ModCondition: state flags required/set; CountCondition/ModCountCondition:
# counters required/changed (0 resets, else adds); CountTrigger: {event: "counter-n"} fires when counter >= n.
class Bin:
    def __init__(s, b): s.b, s.o = b or bytes(4), 0
    def i(s): v = struct.unpack_from('<i', s.b, s.o)[0]; s.o += 4; return v
    def f(s): v = struct.unpack_from('<f', s.b, s.o)[0]; s.o += 4; return round(v, 4)
    def s(s): n = s.i(); v = s.b[s.o:s.o + n].decode('utf-8', 'replace'); s.o += n; return v
def blist(b, *fs):
    r = Bin(b); out = []
    for _ in range(r.i()):
        t = tuple(getattr(r, f)() for f in fs); out.append(t if len(t) > 1 else t[0])
    return out
def lang(con, t):
    if not con.execute('select 1 from sqlite_master where name=?', (t + '_Lang',)).fetchone():
        return {}
    return {k: v[4:4 + struct.unpack_from('<I', v)[0]].decode('utf-8', 'replace') for k, v in con.execute(f'select id, __BIN__enUS from "{t}_Lang"') if v}
caption = lang(o, 'SpineRoleExEvent')
audio_json = os.path.join(ROOT, 'audio', 'audio.json')
AJ = json.load(open(audio_json, encoding='utf-8')) if os.path.exists(audio_json) else {}
voice_names = {r[0]: {'ja': r[1], 'zh': r[2]} for r in o.execute('select id, jaJP, zhCN from ResVoice')}
def voice_files(cue):
    out = {}
    for k, name in (voice_names.get(cue) or {}).items():
        f = AJ.get('cueIndex', {}).get(name) or (AJ.get('multiCues', {}).get(name) or [None])[0]
        if f:
            out[k] = f
    return out or None
cur = o.execute('select * from SpineRoleExEvent'); cols = [d[0] for d in cur.description]
events = {}
for row in cur:
    r = dict(zip(cols, row))
    params = blist(r['__BIN__Param'], 's')
    e = {'type': r['Type'], 'group': r['Group'] or 0, 'block': r['BlockInteract'] or 0,
         'areas': [[float(v) for v in a.split('_')] + [0] * (5 - len(a.split('_'))) for a in blist(r['__BIN__ClickArea'], 's')],
         'when': dict(blist(r['__BIN__Condition'], 's', 'i')), 'set': dict(blist(r['__BIN__ModCondition'], 's', 'i')),
         'whenCount': dict(blist(r['__BIN__CountCondition'], 's', 'i')), 'count': dict(blist(r['__BIN__ModCountCondition'], 's', 'i')),
         'whenSkin': dict(blist(r['__BIN__SkinCondition'], 's', 's')),
         'trigger': [[i, t] for i, t in blist(r['__BIN__CountTrigger'], 'i', 's')], 'mix': blist(r['__BIN__MixDuration'], 'f')}
    t = e['type']
    if t == 1 and len(params) >= 3:
        e.update(play=[[int(params[0]), params[1]]], next=int(params[2]))
    elif t in (2, 3):
        e['play'] = [[int(params[i]), params[i + 1]] for i in range(0, len(params) - 1, 2)]
    elif t == 4 and len(params) >= 2:
        e.update(play=[[int(params[0]), params[1]]], bone=params[2] if len(params) > 2 else None)
    elif t == 5:
        e['skins'] = {params[i]: params[i + 1] for i in range(0, len(params) - 1, 2)}
    if r['PlayVoice']:
        e['voice'] = voice_files(r['PlayVoice'])
        e['caption'] = caption.get(r['LangCaptions']) or None
    events[r['id']] = {k: v for k, v in e.items() if v not in (None, {}, [])} | {'type': t}
mains = {}
cur = o.execute('select * from SpineRoleExMainAnim'); cols = [d[0] for d in cur.description]
for row in cur:
    r = dict(zip(cols, row))
    mains[r['id']] = {'loop': [list(a) for a in blist(r['__BIN__Anim'], 'i', 's')], 'pre': r['PreAnim'] or None,
                      'events': blist(r['__BIN__EventList'], 'i'), 'init': dict(blist(r['__BIN__InitParam'], 's', 'i')),
                      'initCount': dict(blist(r['__BIN__InitCountParam'], 's', 'i')),
                      # part -> the animation that leaves it in its non-initial state ("top-idle1_maorongpifeng_tuo#...")
                      'restore': {k: v for k, _, v in (x.partition('-') for x in (r['ModifyState'] or '').split('#')) if k and v}}
interactive = 0
for prefab, default, anim_list in o.execute('select id, DefaultMainAnim, __BIN__MainAnimList from SpineRoleEx'):
    skel = skel_for(prefab)
    if not skel or skel not in out or default not in mains:
        continue
    todo, used = [default, *ints(anim_list)], {}
    while todo:   # every main state reachable from the rig's list, through switch events
        m = todo.pop()
        if m in used or m not in mains:
            continue
        used[m] = mains[m]
        for eid in mains[m]['events']:
            ev = events.get(eid, {})
            todo += [ev['next']] if 'next' in ev else []
            todo += [int(t[0]) for t in ev.get('trigger', [])]
    ev_ids = {eid for m in used.values() for eid in m['events']}
    ev_ids |= {t[0] for eid in list(ev_ids) for t in events.get(eid, {}).get('trigger', [])}
    out[skel]['interact'] = {
        'start': default, 'states': mains[default]['init'], 'counts': mains[default]['initCount'],
        'mains': {str(k): v for k, v in used.items()},
        'events': {str(k): events[k] for k in sorted(ev_ids) if k in events},
    }
    interactive += 1

json.dump(out, open(os.path.join(ROOT, 'rooms.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f'{len(out)} layered rigs, {rooms} with a room background, {interactive} with tap interactions')
