"""Paths shared by every tool: where the game client is installed and where output goes.

The game client folder is the one containing DragonTraveler.exe and DragonTraveler_Data
(for the launcher install that's usually ...\\DragonTraveler\\client). It is found by, in order:
  1. the DT_GAME_DIR environment variable
  2. config.local.json next to this file: {"game_dir": "D:/Games/DragonTraveler/client"}
  3. common install locations on every drive, then every Steam library (steamapps/common)
Run `python config.py` to see what was found, or `python config.py <path>` to save a location.
"""
import json, os, string, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # the site folder: pages + extracted content
LOCAL = os.path.join(HERE, 'config.local.json')


def is_client(path):
    return bool(path) and os.path.isdir(os.path.join(path, 'DragonTraveler_Data')) and os.path.isdir(os.path.join(path, 'local_data'))


def _candidates():
    subdirs = ['DragonTraveler/client', 'Games/DragonTraveler/client', 'Program Files/DragonTraveler/client',
               'Program Files (x86)/DragonTraveler/client', 'DragonTraveler']
    for drive in string.ascii_uppercase:
        root = f'{drive}:/'
        if os.path.exists(root):
            for sub in subdirs:
                yield root + sub
    for env in ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE'):
        if os.environ.get(env):
            yield os.path.join(os.environ[env], 'DragonTraveler', 'client')
    yield from _steam_candidates()


def _steam_candidates():
    """Every game folder in every Steam library (the Steam version installs under steamapps/common)."""
    import re
    roots = []
    try:
        import winreg
        for hive, key, name in ((winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
                                (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath')):
            try:
                with winreg.OpenKey(hive, key) as k:
                    roots.append(winreg.QueryValueEx(k, name)[0])
            except OSError:
                pass
    except ImportError:
        pass
    libraries = []
    for root in roots:
        libraries.append(root)
        vdf = os.path.join(root, 'steamapps', 'libraryfolders.vdf')
        if os.path.exists(vdf):
            text = open(vdf, encoding='utf-8', errors='replace').read()
            libraries += [p.replace('\\\\', '\\') for p in re.findall(r'"path"\s+"([^"]+)"', text)]
    for lib in dict.fromkeys(os.path.normcase(os.path.normpath(l)) for l in libraries):
        common = os.path.join(lib, 'steamapps', 'common')
        if os.path.isdir(common):
            for name in os.listdir(common):
                yield os.path.join(common, name)
                yield os.path.join(common, name, 'client')


def find_game_dir():
    env = os.environ.get('DT_GAME_DIR')
    if env:
        return env
    if os.path.exists(LOCAL):
        saved = json.load(open(LOCAL, encoding='utf-8')).get('game_dir')
        if saved:
            return saved
    return next((c for c in _candidates() if is_client(c)), None)


def save_game_dir(path):
    path = os.path.abspath(path.strip().strip('"'))
    if not is_client(path) and is_client(os.path.join(path, 'client')):
        path = os.path.join(path, 'client')
    if not is_client(path):
        raise SystemExit(f'Not a Dragon Traveler client folder (no DragonTraveler_Data/local_data inside): {path}')
    json.dump({'game_dir': path.replace(os.sep, '/')}, open(LOCAL, 'w', encoding='utf-8'), indent=1)
    return path


GAME = (find_game_dir() or '').replace(os.sep, '/')
DB = GAME + '/local_data/db'                                        # SQLite config tables
RES_BASE = GAME + '/DragonTraveler_Data/StreamingAssets/res'        # bundles shipped with the install
RES_UPDATE = GAME + '/local_data/res_update'                        # bundles downloaded by patches


def require_game():
    if not is_client(GAME):
        raise SystemExit('Dragon Traveler client folder not found. Set DT_GAME_DIR, or run:\n'
                         '    python _tools/config.py "D:/path/to/DragonTraveler/client"')
    return GAME


if __name__ == '__main__':
    if len(sys.argv) > 1:
        print('Saved game folder:', save_game_dir(sys.argv[1]))
    else:
        print('Game folder:', GAME or '(not found)', '' if is_client(GAME) else '(invalid)')
        print('Output folder:', ROOT)
