"""Indexes every game bundle: which asset paths ("containers") each one holds -> index.json.

Incremental: bundles whose size and modification time are unchanged since the last run
(index_stamps.json) reuse their previous entry, so re-running after a patch only opens new or
changed bundles. index.json format: [[key, bundle_path, [container paths], error], ...].
"""
import json, os, sys
from multiprocessing import Pool
import UnityPy
from dtunpack import load, all_bundles
UnityPy.config.FALLBACK_UNITY_VERSION = '2020.3.25f1'

def work(item):
    key, path = item
    try:
        env = load(path)
        return key, path, list(env.container.keys()), None
    except Exception as e:
        return key, path, [], repr(e)[:200]

def stamp(path):
    st = os.stat(path)
    return [st.st_size, round(st.st_mtime, 3)]

if __name__ == '__main__':
    items = sorted(all_bundles().items())
    old, stamps = {}, {}
    if os.path.exists('index.json') and os.path.exists('index_stamps.json') and '--full' not in sys.argv:
        old = {e[1]: e for e in json.load(open('index.json'))}
        stamps = json.load(open('index_stamps.json'))
    res, todo = [], []
    for key, path in items:
        prev = old.get(path)
        if prev and stamps.get(path) == stamp(path) and prev[3] is None:
            res.append(prev)
        else:
            todo.append((key, path))
    print(f'{len(items)} bundles: {len(res)} unchanged, {len(todo)} to index', flush=True)
    errs = 0
    if todo:
        with Pool(12) as p:
            for i, r in enumerate(p.imap_unordered(work, todo, chunksize=16)):
                res.append(r); errs += r[3] is not None
                if i % 2000 == 0: print(' ', i, '/', len(todo), flush=True)
    res.sort(key=lambda e: e[1])
    json.dump(res, open('index.json', 'w'))
    json.dump({p: stamp(p) for _, p in items}, open('index_stamps.json', 'w'))
    print('done', len(res), 'bundles,', errs, 'errors;', len(todo), 'newly indexed')
    # Tell the caller which bundles changed (used by extract.py for incremental extraction)
    json.dump([p for _, p in todo], open('index_changed.json', 'w'))
