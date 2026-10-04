"""prefab_dirs.json: Spine prefab file name -> extracted rig folder (e.g. "lihui_airenzhanshi.prefab" ->
"spine/hero/airenzhanshi"). The game's tables refer to rigs by prefab name; this maps them to the
folders extract.py writes. Built from index.json, so run it after index.py.
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
PREFIXES = [('assets/res/model/common/spinemodel/', 'spine/'), ('assets/res/model/pc/spinemodel/', 'spine_pc/')]

out = {}
for key, bundle, containers, err in json.load(open(os.path.join(HERE, 'index.json'))):
    for c in containers:
        for prefix, dest in PREFIXES:
            if c.startswith(prefix) and c.endswith('.prefab'):
                out[c.rsplit('/', 1)[1].lower()] = dest + c[len(prefix):].rsplit('/', 1)[0]
json.dump(out, open(os.path.join(HERE, 'prefab_dirs.json'), 'w'), indent=0, sort_keys=True)
print(len(out), 'Spine prefabs mapped')
