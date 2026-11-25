"""Paths shared by every tool for either PC client layout.

Global clients use DragonTraveler_Data and usually keep their database and patches in
local_data. Taiwanese Dragon Soul clients use dragonsoul_Data and keep those files in
StreamingAssets. A second client can be configured as a text reference.
"""
import json, os, string, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # the site folder: pages + extracted content
LOCAL = os.path.join(HERE, 'config.local.json')


def local_settings():
    if not os.path.exists(LOCAL):
        return {}
    try:
        return json.load(open(LOCAL, encoding='utf-8'))
    except (OSError, ValueError):
        return {}


SETTINGS = local_settings()


def data_dir(path):
    if not path:
        return None
    for name in ('DragonTraveler_Data', 'dragonsoul_Data'):
        candidate = os.path.join(path, name)
        if os.path.isdir(os.path.join(candidate, 'StreamingAssets')):
            return candidate
    return None


def is_client(path):
    data = data_dir(path)
    if not data:
        return False
    streaming = os.path.join(data, 'StreamingAssets')
    return os.path.isdir(os.path.join(streaming, 'res')) and (
        os.path.isdir(os.path.join(path, 'local_data', 'db')) or
        os.path.isdir(os.path.join(streaming, 'db')))


def client_kind(path):
    data = data_dir(path)
    if not data:
        return None
    return 'tw' if os.path.basename(data).lower() == 'dragonsoul_data' else 'global'


def _candidates():
    # Check the established Global folder names first to preserve the old default when
    # both editions are installed. Users can always select a specific client with
    # DT_GAME_DIR or config.local.json.
    subdirs = ['DragonTraveler/client', 'Games/DragonTraveler/client',
               'Program Files/DragonTraveler/client',
               'Program Files (x86)/DragonTraveler/client', 'DragonTraveler',
               'DragonTraveler-TW/dragonSoul/client', 'DragonTraveler-TW/dragonSoul',
               'DragonSoul/client', 'DragonSoul']
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
    """Every game folder in every Steam library (Steam installs under steamapps/common)."""
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
    selection = (os.environ.get('DT_CLIENT') or SETTINGS.get('client') or 'auto').lower()
    if selection not in ('auto', 'global', 'tw'):
        raise SystemExit('DT_CLIENT must be auto, global, or tw.')
    saved = SETTINGS.get('game_dir')
    if saved and is_client(saved) and (selection == 'auto' or client_kind(saved) == selection):
        return saved
    found = []
    seen = set()
    for candidate in _candidates():
        normalized = os.path.normcase(os.path.abspath(candidate))
        if normalized not in seen and is_client(candidate):
            found.append(candidate)
            seen.add(normalized)
    if selection != 'auto':
        return next((c for c in found if client_kind(c) == selection), None)
    return next((c for c in found if client_kind(c) == 'global'), found[0] if found else None)


def save_game_dir(path):
    path = os.path.abspath(path.strip().strip('"'))
    if not is_client(path) and is_client(os.path.join(path, 'client')):
        path = os.path.join(path, 'client')
    if not is_client(path):
        raise SystemExit(f'Not a Dragon Traveler client folder (missing game data, resources, or config DBs): {path}')
    SETTINGS['game_dir'] = path.replace(os.sep, '/')
    json.dump(SETTINGS, open(LOCAL, 'w', encoding='utf-8'), indent=1)
    return path


GAME = (find_game_dir() or '').replace(os.sep, '/')
DATA = data_dir(GAME) or ''
STREAMING = os.path.join(DATA, 'StreamingAssets').replace(os.sep, '/') if DATA else ''
LOCAL_DATA = os.path.join(GAME, 'local_data').replace(os.sep, '/') if GAME else ''
DB = (os.path.join(LOCAL_DATA, 'db') if os.path.isdir(os.path.join(LOCAL_DATA, 'db'))
      else os.path.join(STREAMING, 'db')).replace(os.sep, '/')
RES_BASE = os.path.join(STREAMING, 'res').replace(os.sep, '/')
RES_UPDATE = (os.path.join(LOCAL_DATA, 'res_update')
              if os.path.isdir(os.path.join(LOCAL_DATA, 'res_update'))
              else os.path.join(STREAMING, 'res_update')).replace(os.sep, '/')
RES_TMP = (os.path.join(LOCAL_DATA, 'res_tmp')
           if os.path.isdir(os.path.join(LOCAL_DATA, 'res_tmp'))
           else os.path.join(STREAMING, 'res_tmp')).replace(os.sep, '/')
IS_TW = client_kind(GAME) == 'tw'
REFERENCE_GAME = os.environ.get('DT_REFERENCE_GAME_DIR') or SETTINGS.get('reference_game_dir', '')
REFERENCE_DATA = data_dir(REFERENCE_GAME) or ''
REFERENCE_STREAMING = os.path.join(REFERENCE_DATA, 'StreamingAssets') if REFERENCE_DATA else ''
REFERENCE_LOCAL = os.path.join(REFERENCE_GAME, 'local_data') if REFERENCE_GAME else ''
REFERENCE_DB = (os.path.join(REFERENCE_LOCAL, 'db') if os.path.isdir(os.path.join(REFERENCE_LOCAL, 'db'))
                else os.path.join(REFERENCE_STREAMING, 'db') if REFERENCE_STREAMING else '')
LOCALE = os.environ.get('DT_LOCALE') or SETTINGS.get('locale') or ('zhTW' if IS_TW else 'enUS')


def require_game():
    if not is_client(GAME):
        raise SystemExit('Dragon Traveler client folder not found. Set DT_GAME_DIR, or run:\n'
                         '    python _tools/config.py "D:/path/to/DragonTraveler/client"')
    return GAME


if __name__ == '__main__':
    if len(sys.argv) > 1:
        print('Saved game folder:', save_game_dir(sys.argv[1]))
    else:
        print('Game folder:', GAME or '(not found)',
              f'({"TW" if IS_TW else "Global"})' if is_client(GAME) else '(invalid)')
        print('Reference game folder:', REFERENCE_GAME or '(not set)')
        print('Locale:', LOCALE)
        print('Output folder:', ROOT)
