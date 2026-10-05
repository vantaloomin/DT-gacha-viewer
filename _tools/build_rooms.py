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
    n = struct.unpack_from('<I', offset or bytes(4))[0]
    origin = list(struct.unpack_from(f'<{n}f', offset, 4)) if n == 2 else [0.5, 0.5]   # skeleton origin, fraction of the background
    out[skel]['room'] = {'bg': bg, 'size': [w, h], 'origin': origin, 'unitPx': h / SCREEN_H}
    rooms += 1

json.dump(out, open(os.path.join(ROOT, 'rooms.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f'{len(out)} layered rigs, {rooms} with a room background')
