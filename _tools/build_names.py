"""Builds names.json: English display names (and the game's default skin) for each
extracted Spine rig folder, read from the game's SQLite config databases.

Links used:
  RoleDress.SpineModel (o_t.db)        -> hero outfit rigs (lihui_*), via BelongHero -> Heroes
  GoddessRoom.SpineRole (b_g.db)       -> goddess room rigs (l2d_*)
  HeroesFriendshipBG.SpineLoop (h_n.db) -> ResSpine (o_t.db) -> affection scene rigs (haogandu_*)
  SpineRole / SpineRoleEx (o_t.db)     -> skin the game shows by default
Text columns named Lang* hold keys like "Heroes$LangHeroName_1301"; the English text is
in <Table>_Lang.__BIN__enUS as a uint32 length + UTF-8 bytes.
"""
import glob, json, os, re, sqlite3, struct

HERE = os.path.dirname(os.path.abspath(__file__))
from config import DB as DB_DIR


def text(b):
    if not isinstance(b, bytes) or len(b) < 4:
        return ''
    n = struct.unpack('<I', b[:4])[0]
    return b[4:4 + n].decode('utf-8', 'replace')


dbs = {os.path.basename(f): sqlite3.connect(f'file:{f}?mode=ro', uri=True) for f in glob.glob(DB_DIR + '/*.db')}

# Every *_Lang table, merged: key -> English
LANG = {}
for c in dbs.values():
    for (t,) in c.execute("select name from sqlite_master where type='table' and name like '%\\_Lang' escape '\\'"):
        cols = [r[1] for r in c.execute(f'pragma table_info("{t}")')]
        if '__BIN__enUS' in cols:
            LANG.update((k, text(v)) for k, v in c.execute(f'select id, __BIN__enUS from "{t}"'))
en = lambda key: LANG.get(key, '') if key else ''


def rows(db, table):
    c = dbs[db]
    cols = [r[1] for r in c.execute(f'pragma table_info("{table}")')]
    return [dict(zip(cols, r)) for r in c.execute(f'select * from "{table}"')]


prefab_dirs = json.load(open(os.path.join(HERE, 'prefab_dirs.json')))
def rig_dir(prefab):
    return prefab_dirs.get(prefab.lower() if prefab.endswith('.prefab') else prefab.lower() + '.prefab')

heroes = {h['id']: h for h in rows('h_n.db', 'Heroes')}
def hero_names(hid):
    h = heroes.get(hid)
    if not h:
        return '', ''
    return en(h['LangTitle']), en(h['LangHeroName'])  # personal name, class title

names = {}  # rig folder -> {title, subtitle, kind, skin}
def add(folder, title, subtitle, kind):
    if not folder or not title:
        return
    subtitle = ' · '.join(x for x in subtitle.split(' · ') if x and x != title)
    e = names.setdefault(folder, {'title': title, 'subtitle': subtitle, 'kind': kind})
    if e['title'] != title and title not in e.get('also', []):  # outfit shared by several heroes
        e.setdefault('also', []).append(title)

# 1. Hero outfits
dresses = sorted(rows('o_t.db', 'RoleDress'), key=lambda d: d['id'])
for d in dresses:
    folder = rig_dir(d['SpineModel']) if d['SpineModel'] else None
    if not folder:
        continue
    personal, cls = hero_names(d['BelongHero'])
    outfit = en(d['LangName'])
    sub = [cls if personal else '', outfit if outfit not in (personal, cls) else '']
    add(folder, personal or cls or outfit, ' · '.join(x for x in sub if x), 'hero')
    if d['DisplayType'] == 3:   # multi-scene outfits; not shown with the standard full-screen camera
        names[folder]['display'] = 3

# Hero rigs with no SpineModel link: match the folder's pinyin to the outfit's voice/emoji names.
for folder in [os.path.dirname(p).replace('\\', '/')[len(os.path.dirname(HERE)) + 1:]
               for p in glob.glob(os.path.join(os.path.dirname(HERE), 'spine/hero/*/'))]:
    if folder in names:
        continue
    token = folder.rsplit('/', 1)[1]
    for d in dresses:
        if any(re.search(rf'(_|^){re.escape(token)}(_|$)', (v or '').replace('.png', '')) for v in (d['AppearVol'], d['Icon2'])):
            personal, cls = hero_names(d['BelongHero'])
            add(folder, personal or cls or en(d['LangName']), cls if personal else '', 'hero')
            break

# 2. Goddess rooms
for g in rows('b_g.db', 'GoddessRoom'):
    m = re.search(r'icon_hero_(\d+)', g['GoddessIcon'] or '')
    personal, cls = hero_names(int(m.group(1))) if m else ('', '')
    add(rig_dir(g['SpineRole']), personal or cls, en(g['LangName']) or g['LangName'], 'goddess')

# 3. Affection (haogandu) scenes; the "Harmony" variant is the censored version.
res_spine = {r['id']: r for r in rows('o_t.db', 'ResSpine')}
for bg in rows('h_n.db', 'HeroesFriendshipBG'):
    r = res_spine.get(bg['SpineLoop'])
    if not r:
        continue
    scene = en(bg['LangName'])
    personal, cls = hero_names(bg['HeroId'])
    add(rig_dir(r['SpineName']), scene, 'Affection scene', 'scene')
    if r['HarmonySpineName'] != r['SpineName']:
        add(rig_dir(r['HarmonySpineName']), scene, 'Affection scene (censored version)', 'scene')

# Default skins the game uses
for r in rows('o_t.db', 'SpineRole'):
    f = rig_dir(r['id'])
    if f and r['NormalSkin']:
        names.setdefault(f, {})['skin'] = r['NormalSkin']
for r in rows('o_t.db', 'SpineRoleEx'):
    f = rig_dir(r['id'])
    if f and r['MainSkin']:
        names.setdefault(f, {})['skin'] = r['MainSkin']

json.dump(names, open(os.path.join(os.path.dirname(HERE), 'names.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
print(len(names), 'rig folders named')
