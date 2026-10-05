"""Builds profiles.json: each hero's Profile page — biography, skills (with their 3D animation clips),
star upgrades and voice lines (with the extracted audio files). Keyed by hero id.

Game data:
  h_n.db HeroesInfo          LangStory1..5, LangHeight, LangWeight, LangIP (mythology of origin); id = Heroes.id
  h_n.db Heroes              LangGetSSR (summon line), LangGetLines, LangJobDescribe (role), LangTalentSummary,
                             GetSSRVoice (summon voice cue), GeneralAttack, HeroSkill (-> HeroesSkill.BaseHero)
  h_n.db HeroesSkill         per star: Skill, UltraSkill, TalentSkill; TalentDes 1/2 -> LangTalentDes / LangShortTalentDes
  b_g.db BattleSkill         LangSkillName, LangSkillDes ({0} {1}... filled from SkillDesValue: one "a-b-c" per level),
                             SkillIcon, Skill_Type (0 basic, 1 talent, 2 ultimate, 3-5 skills), SkillCold (float64 list)
  o_t.db RoleDress           per outfit: AppearVol (greeting), ClickVol (tap: animation -> cue)
  u_z.db UltraSkill          ClutchVol (ultimate line), ClutchVol_dress (per-outfit override)
  o_t.db SpineRoleExEvent    goddess room lines: PlayVoice + LangCaptions (the only voice lines with subtitles)
  o_t.db ResVoice            cue -> per-language audio names, found in audio/audio.json
Note: Heroes' column names are swapped in the game data (LangTitle holds the name, LangHeroName the epithet).
"""
import glob, html, json, os, re, sqlite3, struct

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
from config import DB

cons = {os.path.basename(p): sqlite3.connect(f'file:{p}?mode=ro', uri=True) for p in glob.glob(os.path.join(DB, '*.db'))}
def find(t):
    for c in cons.values():
        if c.execute('select 1 from sqlite_master where name=?', (t,)).fetchone():
            return c
def has(t, col):
    c = find(t)
    return bool(c) and col in [r[1] for r in c.execute(f'pragma table_info("{t}")')]
def s1(v):
    if not isinstance(v, bytes) or len(v) < 4:
        return v
    return v[4:4 + struct.unpack('<I', v[:4])[0]].decode('utf-8', 'replace')
_lang = {}
def lang(t):
    if t not in _lang:
        c = find(t + '_Lang')
        _lang[t] = {k: s1(v) for k, v in c.execute(f'select id, __BIN__enUS from "{t}_Lang"')} if c else {}
    return _lang[t]

class R:
    def __init__(s, b): s.b, s.o = b or b'\0\0\0\0', 0
    def i(s): v = struct.unpack_from('<i', s.b, s.o)[0]; s.o += 4; return v
    def s(s): n = s.i(); v = s.b[s.o:s.o + n].decode('utf-8', 'replace'); s.o += n; return v
def ints(b): r = R(b); return [r.i() for _ in range(r.i())]
def strs(b): r = R(b); return [r.s() for _ in range(r.i())]
def pairs_ss(b): r = R(b); return [(r.s(), r.s()) for _ in range(r.i())]
def pairs_is(b): r = R(b); return [(r.i(), r.s()) for _ in range(r.i())]
def floats64(b):
    if not isinstance(b, bytes) or len(b) < 12:
        return []
    return [struct.unpack_from('<d', b, 4 + 8 * i)[0] for i in range(struct.unpack('<I', b[:4])[0])]


def rich(s):
    """Unity rich text -> small safe HTML (italics, bold, colours); other tags dropped."""
    if not s or s.strip() in ('None', '?'):
        return None
    s = html.escape(s, quote=False)
    s = re.sub(r'&lt;color=(#[0-9A-Fa-f]{6,8})&gt;', lambda m: f'<span style="color:{m[1][:7]}">', s)
    s = re.sub(r'&lt;/color&gt;', '</span>', s)
    s = re.sub(r'&lt;(/?)(i|b)&gt;', r'<\1\2>', s)
    s = re.sub(r'&lt;/?(link|size|u)[^&]*&gt;', '', s)
    return s.strip().replace('\n', '<br>')


def fill(des, vals, level):
    if not vals:
        return des
    parts = vals[min(level, len(vals)) - 1].split('-')
    return re.sub(r'\{(\d+)\}', lambda m: parts[int(m[1])] if int(m[1]) < len(parts) else m[0], des or '')


# ---- audio: cue -> {ja, zh} files ----
audio_json = os.path.join(ROOT, 'audio', 'audio.json')
AJ = json.load(open(audio_json, encoding='utf-8')) if os.path.exists(audio_json) else {}
CI, MC = AJ.get('cueIndex', {}), AJ.get('multiCues', {})
RV = {r[0]: {'ja': r[1], 'zh': r[2]} for r in find('ResVoice').execute('select id, jaJP, zhCN from ResVoice')}
def files(cue):
    out = {}
    for k, name in (RV.get(cue) or {}).items():
        if name in CI:
            out[k] = CI[name]
        elif MC.get(name):
            out[k] = MC[name][0]
    return out

# ---- skill icons (extracted to images/skillicon/ by extract.py) ----
ICONS = {os.path.basename(p): os.path.relpath(p, ROOT).replace(os.sep, '/')
         for p in glob.glob(os.path.join(ROOT, 'images', 'skillicon', '**', '*.png'), recursive=True)}

BL, HL, HIL, HSL, DL = lang('BattleSkill'), lang('Heroes'), lang('HeroesInfo'), lang('HeroesSkill'), lang('RoleDress')
BS = {r[0]: r for r in find('BattleSkill').execute(
    'select id, LangSkillName, LangSkillDes, __BIN__SkillDesValue, SkillIcon, Skill_Type, __BIN__SkillCold from BattleSkill')}
KIND = {0: 'Basic attack', 1: 'Talent', 2: 'Ultimate', 3: 'Skill', 4: 'Skill', 5: 'Skill'}
skill_clips_path = os.path.join(HERE, 'skill_clips.json')
SKILL_CLIPS = json.load(open(skill_clips_path, encoding='utf-8')) if os.path.exists(skill_clips_path) else {}


def skill(sid, hero_id, kind=None):
    r = BS.get(sid)
    if not r:
        return None
    i, n, d, v, icon, t, cold = r
    name = BL.get(n, '')
    if not name:
        return None
    vals = strs(v)
    des = BL.get(d, '')
    if re.search(r'temporarily unavailable', des or '', re.I):   # the game's placeholder text
        des = ''
    base = lambda label: re.sub(r' \((\d+/\d+|empowered)\)$', '', label)
    clips = [c for c, (label, _) in SKILL_CLIPS.get(str(hero_id), {}).items() if base(label) == name]
    cd = floats64(cold)
    return {'id': i, 'name': name, 'kind': kind or KIND.get(t, 'Skill'),
            'desc': rich(fill(des, vals, 1)), 'descMax': rich(fill(des, vals, len(vals))) if len(vals) > 1 else None,
            'levels': len(vals), 'cooldown': round(cd[0], 1) if cd and cd[0] > 0 else None,
            'icon': ICONS.get(icon), 'clips': sorted(clips)}


ult = {}
for uid, cv, cvd, hid in find('UltraSkill').execute('select id, ClutchVol, __BIN__ClutchVol_dress, correspondingHeroID from UltraSkill'):
    if cv and hid:
        ult.setdefault(hid, (cv, pairs_is(cvd)))
dresses = {}
for did, bh, nm, ap, cl in find('RoleDress').execute('select id, BelongHero, LangName, AppearVol, __BIN__ClickVol from RoleDress order by id'):
    dresses.setdefault(bh, []).append((did, DL.get(nm, ''), ap, pairs_ss(cl)))
# goddess room lines (with subtitles), by the hero shown on the room's icon
room_hero = {}
for rid, icon in find('GoddessRoom').execute('select id, GoddessIcon from GoddessRoom'):
    m = re.search(r'(\d+)', icon or '')
    if m:
        room_hero[rid] = int(m[1])
EL = lang('SpineRoleExEvent')
goddess = {}
if has('SpineRoleExEvent', 'PlayVoice'):
    for eid, cue, cap in find('SpineRoleExEvent').execute('select id, PlayVoice, LangCaptions from SpineRoleExEvent'):
        hid = room_hero.get(eid // 100)
        if hid and cue:
            seen = goddess.setdefault(hid, {})
            if cue not in seen or (not seen[cue] and EL.get(cap)):
                seen[cue] = EL.get(cap) or None


def voices(hero_id, ssr_cue, ssr_text):
    out, used = [], set()
    def add(group, cue, **kw):
        f = files(cue)
        if cue and f and cue not in used:
            used.add(cue)
            out.append({'group': group, 'cue': cue, 'files': f, **kw})
    add('Summon', ssr_cue, text=ssr_text)
    for did, dname, appear, clicks in dresses.get(hero_id, []):
        add('Greeting', appear, outfit=dname)
        for anim, cue in clicks:
            add('Tap reactions', cue, outfit=dname, label=anim)
    if hero_id in ult:
        cue, overrides = ult[hero_id]
        add('Ultimate', cue)
        names = {d[0]: d[1] for d in dresses.get(hero_id, [])}
        for did, c in overrides:
            add('Ultimate', c, outfit=names.get(did))
    # lines the outfit tables don't reference (extra tap takes, etc.), found by the hero's cue name
    slug = (ssr_cue or '').removeprefix('sound_vol_zh_')
    if slug:
        for cue in sorted(RV):
            m = re.fullmatch(rf'sound_vol_(click|dc|dz)_{re.escape(slug)}(\d*)', cue)
            if m:
                add({'click': 'Tap reactions', 'dc': 'Greeting', 'dz': 'Ultimate'}[m[1]], cue)
    for cue, text in goddess.get(hero_id, {}).items():
        add('Goddess room', cue, text=text)
    return out


heroes = json.load(open(os.path.join(ROOT, 'heroes.json'), encoding='utf-8'))['heroes']
info_cols = [r[1] for r in find('HeroesInfo').execute('pragma table_info(HeroesInfo)')]
info = {r[info_cols.index('id')]: dict(zip(info_cols, r)) for r in find('HeroesInfo').execute('select * from HeroesInfo')}
out = {}
for h in heroes:
    hid = h['id']
    row = find('Heroes').execute('select LangGetSSR, LangGetLines, LangJobDescribe, LangTalentSummary, GetSSRVoice, '
                                 '__BIN__GeneralAttack, HeroSkill from Heroes where id=?', (hid,)).fetchone()
    if not row:
        continue
    ssr, lines, job, talent, ssr_cue, general, hero_skill = row
    hi = info.get(hid, {})
    val = lambda k: (lambda t: t if t and t != '?' else None)(HIL.get(hi.get(k)))
    bio = {
        'origin': val('LangIP'), 'height': val('LangHeight'), 'weight': val('LangWeight'),
        'quote': HL.get(ssr) or None, 'quote2': HL.get(lines) or None,
        'role': HL.get(job) or None, 'talentSummary': rich(HL.get(talent)),
        'stories': [s for s in (rich(val(f'LangStory{i}')) for i in range(1, 6)) if s],
    }
    rows = find('HeroesSkill').execute('select Star, __BIN__Skill, UltraSkill, TalentSkill, TalentDes, LangTalentDes, '
                                      'LangShortTalentDes from HeroesSkill where BaseHero=? order by Star', (hero_skill or hid,)).fetchall()
    skills = [skill(s, hid, 'Basic attack') for s in ints(general)]
    if rows:
        _, sk, ul, ta, *_ = rows[0]
        skills += [skill(s, hid) for s in ints(sk)]
        if ul and ul > 0:
            skills.append(skill(ul, hid, 'Ultimate'))
        if ta and ta > 0:
            skills.append(skill(ta, hid, 'Talent'))
    stars = [{'star': st, 'text': rich(HSL.get(lt) if td == 1 else HSL.get(sd))}
             for st, _, _, _, td, lt, sd in rows if td in (1, 2) and HSL.get(lt if td == 1 else sd)]
    entry = {'bio': {k: v for k, v in bio.items() if v}, 'skills': [s for s in skills if s],
             'stars': stars, 'voices': voices(hid, ssr_cue, HL.get(ssr) or None)}
    if entry['bio'].get('stories') or entry['skills'] or entry['voices']:
        out[str(hid)] = entry

json.dump(out, open(os.path.join(ROOT, 'profiles.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print(f'{len(out)} profiles: {sum(bool(p["bio"].get("stories")) for p in out.values())} with a biography, '
      f'{sum(len(p["skills"]) for p in out.values())} skills, {sum(len(p["voices"]) for p in out.values())} voice lines')
