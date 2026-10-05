"""One-click update: re-runs the whole extraction pipeline after a game patch, then reports what's new.

Steps (each is its own script in this folder and can be run alone):
  index.py               which assets each bundle holds (incremental)
  extract.py             Spine rigs + images (incremental)
  build_names.py         English names for rigs
  make_manifest.py       manifest.json (list of rigs)
  convert_usm.py         showcase/story videos -> WebM (incremental)
  extract_audio.py       voice/sound banks -> Ogg (incremental; optional)
  export_models.py       3D battle models -> glTF
  build_interactions.py  tap zones, reactions and voice cue ids
  build_rooms.py         goddess rooms: layered skins, pre-animations, backgrounds
  build_heroes.py        heroes.json for the gallery
  vendor.py              local copies of the web libraries (only fetches missing files)
Then compares heroes.json before/after and writes whatsnew.json (shown in the gallery).

Usage: python update.py [--full]   (--full ignores incremental state and redoes everything)
"""
import datetime, glob, json, os, re, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
from config import GAME, is_client, save_game_dir
FULL = '--full' in sys.argv
FULL_AWARE = {'index.py', 'extract.py', 'convert_usm.py'}   # steps that understand --full

STEPS = [
    ('Indexing game bundles', 'index.py', True),
    ('Mapping Spine prefabs', 'build_prefab_dirs.py', True),
    ('Extracting Spine rigs and images', 'extract.py', True),
    ('Naming rigs', 'build_names.py', True),
    ('Building rig manifest', 'make_manifest.py', True),
    ('Converting videos', 'convert_usm.py', True),
    ('Extracting voice lines and sounds', 'extract_audio.py', False),
    ('Converting 3D models', 'export_models.py', True),
    ('Building tap interactions', 'build_interactions.py', True),
    ('Building goddess rooms', 'build_rooms.py', True),
    ('Building hero list', 'build_heroes.py', True),
    ('Checking local web libraries', 'vendor.py', False),
]


def game_version():
    maps = glob.glob(os.path.join(GAME, 'local_data', 'res_tmp', 'bundlemap_*.txt'))
    nums = [int(m) for p in maps for m in re.findall(r'bundlemap_(\d+)', p)]
    return f'resource version {max(nums)}' if nums else 'base install'


def summarize(old, new):
    """What changed between two heroes.json files."""
    def caps(s): return {k for k in ('spine', 'model') if s.get(k)} | ({'video'} if s.get('videos') else set())
    old_heroes = {h['id']: h for h in old.get('heroes', [])}
    old_skins = {s['id']: s for h in old.get('heroes', []) for s in h['skins']}
    out = {'newHeroes': [], 'newOutfits': [], 'upgradedOutfits': []}
    for h in new.get('heroes', []):
        if h['id'] not in old_heroes:
            out['newHeroes'].append({'hero': h['id'], 'name': h['name'], 'outfits': len(h['skins'])})
            continue
        for s in h['skins']:
            prev = old_skins.get(s['id'])
            if not prev:
                out['newOutfits'].append({'hero': h['id'], 'skin': s['id'], 'name': f"{h['name']} - {s['name']}"})
            elif caps(s) - caps(prev):
                out['upgradedOutfits'].append({'hero': h['id'], 'skin': s['id'], 'name': f"{h['name']} - {s['name']}", 'added': sorted(caps(s) - caps(prev))})
    return out


def main():
    global GAME
    if not is_client(GAME):
        print('Could not find the Dragon Traveler client folder (the one containing DragonTraveler_Data).')
        try:
            path = input(r'Paste its full path here (e.g. D:\Games\DragonTraveler\client): ')
        except EOFError:
            sys.exit('No game folder given. Set DT_GAME_DIR or run: python _tools/config.py "<path>"')
        GAME = save_game_dir(path).replace(os.sep, '/')
        print('Saved to _tools/config.local.json:', GAME)
    print(f'Dragon Traveler gallery update - {game_version()}' + (' (full rebuild)' if FULL else ''))
    heroes_path = os.path.join(ROOT, 'heroes.json')
    old = json.load(open(heroes_path, encoding='utf-8')) if os.path.exists(heroes_path) else {}
    started = time.time()
    for n, (label, script, required) in enumerate(STEPS, 1):
        path = os.path.join(HERE, script)
        if not os.path.exists(path):
            print(f'\n[{n}/{len(STEPS)}] {label}: skipped ({script} not found)')
            continue
        # Models only come from game bundles: if index.py saw no new or changed bundle, nothing to redo.
        if script == 'export_models.py' and not FULL and os.path.exists(os.path.join(ROOT, 'models', 'models.json')):
            changed_path = os.path.join(HERE, 'index_changed.json')
            if os.path.exists(changed_path) and json.load(open(changed_path)) == []:
                print(f'\n[{n}/{len(STEPS)}] {label}: skipped (no game files changed)')
                continue
        print(f'\n[{n}/{len(STEPS)}] {label}...', flush=True)
        t = time.time()
        args = [sys.executable, '-u', script] + (['--full'] if FULL and script in FULL_AWARE else [])
        proc = subprocess.Popen(args, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        for line in proc.stdout:
            if line.startswith('Error parsing file') or 'You can set the key' in line or 'brute' in line or 'key_sig' in line:
                continue   # harmless UnityPy noise about the decoy headers
            print('    ' + line.rstrip(), flush=True)
        proc.wait()
        if proc.returncode:
            msg = f'{label} failed (exit code {proc.returncode}).'
            if required:
                sys.exit('\n' + msg + ' Fix the error above and run the update again; finished steps are kept.')
            print('    ' + msg + ' Continuing - this step is optional.')
        print(f'    done in {time.time() - t:.0f}s')

    new = json.load(open(heroes_path, encoding='utf-8'))
    changes = summarize(old, new) if old else {'newHeroes': [], 'newOutfits': [], 'upgradedOutfits': []}
    total = sum(len(v) for v in changes.values())
    today = datetime.date.today().isoformat()
    wn_path = os.path.join(ROOT, 'whatsnew.json')
    if total or not os.path.exists(wn_path):
        whats_new = {'date': today, 'gameVersion': game_version(), **changes}
    else:   # nothing new: keep the last update's list, just note when we last checked
        whats_new = json.load(open(wn_path, encoding='utf-8'))
    whats_new['lastChecked'] = today
    json.dump(whats_new, open(wn_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\nUpdate finished in {(time.time() - started) / 60:.1f} min.')
    print(f"What's new: {len(changes['newHeroes'])} heroes, {len(changes['newOutfits'])} outfits, {len(changes['upgradedOutfits'])} outfits with new content."
          if total else "Nothing new since the last update.")
    for h in changes['newHeroes'][:20]: print('  + hero  ', h['name'])
    for s in changes['newOutfits'][:20]: print('  + outfit', s['name'])
    for s in changes['upgradedOutfits'][:20]: print('  ~ outfit', s['name'], '(+' + ', '.join(s['added']) + ')')


if __name__ == '__main__':
    main()
