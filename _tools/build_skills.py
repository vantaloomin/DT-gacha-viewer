"""Builds skill_clips.json: which 3D model animation clip each hero skill plays, with the skill's English name,
so the gallery can show "Curse Blast" instead of "skill_02_01". Keyed by hero id.

Game data, followed in order:
  h_n.db Heroes            GeneralAttack (basic attack), HeroSkill (-> HeroesSkill.BaseHero)
  h_n.db HeroesSkill       Skill (list of BattleSkill ids), UltraSkill
  b_g.db BattleSkill       LangSkillName, Skill_Type, askill_id (list -> ASkill), ultraskill_id
  a.db   ASkill            step_list (list -> ASkillItem)
  a.db   ASkillItem        act_name ("luoji_skill_03_01.asset"), act_name_dress (outfit -> its own act)
  act/battle/<model>/<act>.asset   the action itself: its components name the clip ("animationName")
The action files are read from the game bundles; results are cached per bundle in act_clips.json.
"""
import json, os, re, sqlite3, struct, sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from config import DB

PREFIX = 'assets/res/act/battle/'
CACHE = os.path.join(HERE, 'act_clips.json')


def read_bundle(path):
    """{act name: [clip names]} for every battle action in one bundle."""
    from dtunpack import load
    env = load(path)
    objs = {o.path_id: o for o in env.objects}
    out = {}
    for c, ptr in env.container.items():
        if not c.startswith(PREFIX):
            continue
        try:
            tt = (ptr.deref() if hasattr(ptr, 'deref') else ptr).read_typetree()
            clips = []
            for comp in tt.get('components', []):
                o = objs.get(comp.get('m_PathID'))
                if o:
                    name = o.read_typetree().get('animationName')
                    if name and name not in clips:
                        clips.append(name)
            # a container path lists the action and its components: merge, don't overwrite
            have = out.setdefault(c.rsplit('/', 1)[1].removesuffix('.asset').lower(), [])
            have += [x for x in clips if x not in have]
        except Exception:
            pass
    return out


def act_clips():
    idx = json.load(open(os.path.join(HERE, 'index.json')))
    rank = lambda p: ('res_update' in p.replace(os.sep, '/'), os.path.getmtime(p))
    winner = {}
    for k, p, cs, e in idx:
        for c in cs:
            if c.startswith(PREFIX) and (c not in winner or rank(p) > rank(winner[c])):
                winner[c] = p
    bundles = sorted(set(winner.values()))
    stamp = lambda p: f'{os.path.getsize(p)}:{round(os.path.getmtime(p), 3)}'
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    todo = [p for p in bundles if cache.get(p, {}).get('stamp') != stamp(p)]
    if todo:
        print(f'    reading {len(todo)} of {len(bundles)} action bundles...', flush=True)
        with ProcessPoolExecutor() as ex:
            for p, acts in zip(todo, ex.map(read_bundle, todo, chunksize=4)):
                cache[p] = {'stamp': stamp(p), 'acts': acts}
    cache = {p: v for p, v in cache.items() if p in set(bundles)}
    json.dump(cache, open(CACHE, 'w'))
    acts = {}
    for p in bundles:   # newest bundle last, so it wins
        acts.update(cache[p]['acts'])
    return acts


def ints(b):
    if not isinstance(b, bytes) or len(b) < 4:
        return []
    n = struct.unpack('<I', b[:4])[0]
    return list(struct.unpack(f'<{n}i', b[4:4 + 4 * n]))


def dress_acts(b):
    """act_name_dress: uint32 count, then (outfit id, act name) pairs."""
    out, o = [], 4
    if not isinstance(b, bytes) or len(b) < 4:
        return out
    for _ in range(struct.unpack('<I', b[:4])[0]):
        o += 4
        n = struct.unpack_from('<I', b, o)[0]; o += 4
        out.append(b[o:o + n].decode('utf-8', 'replace')); o += n
    return out


if __name__ == '__main__':
    acts = act_clips()
    con = {n: sqlite3.connect(f'file:{DB}/{n}?mode=ro', uri=True) for n in ('h_n.db', 'b_g.db', 'a.db')}
    lang = {}
    for (t,) in con['b_g.db'].execute("select name from sqlite_master where name = 'BattleSkill_Lang'"):
        lang = {k: v[4:4 + struct.unpack('<I', v[:4])[0]].decode('utf-8', 'replace')
                for k, v in con['b_g.db'].execute('select id, __BIN__enUS from BattleSkill_Lang') if v}
    skills = {i: (lang.get(n, ''), t, ints(a), u) for i, n, t, a, u in
              con['b_g.db'].execute('select id, LangSkillName, Skill_Type, __BIN__askill_id, ultraskill_id from BattleSkill')}
    steps = {i: ints(s) for i, s in con['a.db'].execute('select id, __BIN__step_list from ASkill')}
    items = {i: [a, *dress_acts(d)] for i, a, d in con['a.db'].execute('select id, act_name, __BIN__act_name_dress from ASkillItem')}
    hero_skills = {}
    for base, skill, ultra in con['h_n.db'].execute('select BaseHero, __BIN__Skill, UltraSkill from HeroesSkill order by Star desc'):
        hero_skills[base] = ints(skill) + ([ultra] if ultra and ultra > 0 else [])   # lowest star last: base kit

    out = {}
    for hero_id, general, hero_skill in con['h_n.db'].execute('select id, __BIN__GeneralAttack, HeroSkill from Heroes'):
        clips = {}
        for sid in ints(general) + hero_skills.get(hero_skill or hero_id, []):
            if sid not in skills:
                continue
            name, kind, askills, ultra = skills[sid]
            if not name:
                continue
            kind = 'Basic attack' if sid in ints(general) else 'Ultimate' if (ultra and ultra > 0) else 'Skill'
            found = []
            for aid in askills + ([ultra] if ultra and ultra > 0 else []):
                for item in steps.get(aid, []):
                    for act in items.get(item, []):
                        empowered = 'qianghua' in act.lower()
                        for clip in acts.get(act.lower().removesuffix('.asset'), []):
                            found.append((clip, empowered))
            plain = [c for c, e in found if not e]
            for i, clip in enumerate(dict.fromkeys(plain)):
                n = len(dict.fromkeys(plain))
                clips.setdefault(clip, [name + (f' ({i + 1}/{n})' if n > 1 else ''), kind])
            for clip, e in found:
                if e:
                    clips.setdefault(clip, [name + ' (empowered)', kind])
        if clips:
            out[str(hero_id)] = clips
    json.dump(out, open(os.path.join(HERE, 'skill_clips.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'{len(out)} heroes with named skill clips, {sum(len(v) for v in out.values())} clips')
