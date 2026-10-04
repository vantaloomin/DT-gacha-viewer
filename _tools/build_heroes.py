"""Builds heroes.json for the gallery: every hero with each of their outfits ("dresses") and,
per outfit, the matching Spine rig, static art, showcase videos and 3D battle model.

Links (all from the game's SQLite config, client/local_data/db):
  Heroes (h_n.db)                 id, LangTitle (personal name), LangHeroName (class), Quality, DefaultDress
  RoleDress (o_t.db)              BelongHero, LangName (outfit), SpineModel, Painting/Card/PaintScenes (+Harmony*
                                  censored variants), Icon, HeroShow/HeroShowLoop (videos), ModelID
  Model (m.db)                    id -> model_res (3D prefab name, converted to models/models.json by export_models.py)
Run after extract.py, make_manifest.py, convert_usm.py and export_models.py.
"""
import glob, json, os, re, sqlite3, struct

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
from config import DB


def text(b):
    return b[4:4 + struct.unpack('<I', b[:4])[0]].decode('utf-8', 'replace') if isinstance(b, bytes) and len(b) >= 4 else ''


dbs = {n: sqlite3.connect(f'file:{DB}/{n}?mode=ro', uri=True) for n in ('h_n.db', 'o_t.db', 'm.db')}
LANG = {}
for c in dbs.values():
    for (t,) in c.execute("select name from sqlite_master where type='table' and name like '%\\_Lang' escape '\\'"):
        if '__BIN__enUS' in [r[1] for r in c.execute(f'pragma table_info("{t}")')]:
            LANG.update((k, text(v)) for k, v in c.execute(f'select id, __BIN__enUS from "{t}"'))
en = lambda k: LANG.get(k, '') if k else ''


def rows(db, table):
    c = dbs[db]
    cols = [r[1] for r in c.execute(f'pragma table_info("{table}")')]
    return [dict(zip(cols, r)) for r in c.execute(f'select * from "{table}"')]


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, '/') if path else None


# Lookups for files we've extracted
def index_dir(sub):
    out = {}
    for p in glob.glob(os.path.join(ROOT, sub, '**', '*.png'), recursive=True):
        out.setdefault(os.path.basename(p).lower(), p)
    return out

paintings, cards, scenes, icons = index_dir('images/hero'), index_dir('images/herocard'), index_dir('images/herobg'), index_dir('images/heroicon')
cards.update({k: v for k, v in index_dir('images/cardicon').items() if k not in cards})
find = lambda table, name: rel(table.get((name or '').lower()))

prefab_dirs = json.load(open(os.path.join(HERE, 'prefab_dirs.json')))
manifest = json.load(open(os.path.join(ROOT, 'manifest.json'), encoding='utf-8'))
rig_by_dir = {r['skel'].rsplit('/', 1)[0]: r['skel'] for r in manifest}
def spine_for(prefab):
    d = prefab_dirs.get((prefab or '').lower())
    return rig_by_dir.get(d) if d else None

models_path = os.path.join(ROOT, 'models', 'models.json')
models = json.load(open(models_path, encoding='utf-8')) if os.path.exists(models_path) else {}
model_res = {r['id']: r['model_res'] for r in rows('m.db', 'Model')}

# Video original name -> converted .webm (convert_usm.py writes the source .usm path into its log)
videos = {}
log_path = os.path.join(ROOT, 'videos', 'convert_log.json')
if os.path.exists(log_path):
    for entry in json.load(open(log_path, encoding='utf-8')):
        with open(entry['src'], 'rb') as f:
            m = re.search(rb'([\w.-]+)\.usm', f.read(4096))
        if m:
            out = os.path.join(ROOT, 'videos', entry['out'])
            if os.path.exists(out):
                videos[m.group(1).decode().lower()] = rel(out)
video_for = lambda name: videos.get(name[:-4].lower()) if name and name.endswith('.usm') else None

heroes_tbl = {h['id']: h for h in rows('h_n.db', 'Heroes')}
heroes = {}
for d in sorted(rows('o_t.db', 'RoleDress'), key=lambda d: d['id']):
    h = heroes_tbl.get(d['BelongHero'])
    if not h:
        continue
    personal, cls = en(h['LangTitle']), en(h['LangHeroName'])
    hero = heroes.setdefault(h['id'], {
        'id': h['id'], 'name': personal or cls, 'title': cls if personal and cls != personal else '',
        'quality': h['Quality'], 'defaultDress': h['DefaultDress'], 'icon': None, 'skins': []})
    model_name = (model_res.get(d['ModelID']) or '')[:-7]   # strip ".prefab"
    skin = {
        'id': d['id'],
        'name': en(d['LangName']) or personal or cls,
        'spine': spine_for(d['SpineModel']),
        'art': {k: v for k, v in {
            'painting': find(paintings, d['Painting']),
            'paintingCensored': find(paintings, d['HarmonyPainting']) if d['HarmonyPainting'] != d['Painting'] else None,
            'card': find(cards, d['Card']),
            'cardCensored': find(cards, d['HarmonyCard']) if d['HarmonyCard'] != d['Card'] else None,
            'background': find(scenes, d['PaintScenes']),
        }.items() if v},
        'videos': {k: v for k, v in {'intro': video_for(d['HeroShow']), 'loop': video_for(d['HeroShowLoop'])}.items() if v},
        'model': model_name if model_name in models else None,
        'icon': find(icons, d['Icon']),
    }
    if d['DisplayType'] == 3:
        skin['multiScene'] = True
    hero['skins'].append(skin)

out = []
for hero in heroes.values():
    skins = [s for s in hero['skins'] if s['spine'] or s['art'] or s['videos'] or s['model']]
    # Skip internal placeholders and entries with nothing to look at but a model
    if not skins or 'test' in hero['name'].lower() or not any(s['spine'] or s['art'] or s['videos'] for s in skins):
        continue
    # Default outfit first, then by id
    skins.sort(key=lambda s: (s['id'] != hero['defaultDress'], s['id']))
    hero['skins'] = skins
    for s in skins:   # no icon: fall back to the outfit's card or portrait
        s['icon'] = s['icon'] or s['art'].get('card') or s['art'].get('painting')
    hero['icon'] = next((s['icon'] for s in skins if s['icon']), None)
    out.append(hero)
out.sort(key=lambda h: h['name'].lower())

json.dump({'heroes': out, 'models': models}, open(os.path.join(ROOT, 'heroes.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
n_skins = sum(len(h['skins']) for h in out)
print(f"{len(out)} heroes, {n_skins} outfits: "
      f"{sum(bool(s['spine']) for h in out for s in h['skins'])} with Spine, "
      f"{sum(bool(s['art']) for h in out for s in h['skins'])} with art, "
      f"{sum(bool(s['videos']) for h in out for s in h['skins'])} with videos, "
      f"{sum(bool(s['model']) for h in out for s in h['skins'])} with 3D models")
