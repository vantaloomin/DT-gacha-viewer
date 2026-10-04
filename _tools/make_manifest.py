import glob, json, os
os.chdir(os.path.join(os.path.dirname(__file__), '..'))
names = json.load(open('names.json', encoding='utf-8')) if os.path.exists('names.json') else {}
rigs = []
for skel in sorted(glob.glob('spine*/**/*.skel', recursive=True)):
    d = os.path.dirname(skel); base = os.path.basename(skel)[:-5]
    atlas = os.path.join(d, base + '.atlas')
    if not os.path.exists(atlas):
        cands = glob.glob(os.path.join(d, '*.atlas'))
        if not cands: continue
        atlas = cands[0]
    pma = 'pma: true' in open(atlas, encoding='utf-8', errors='replace').read()
    parts = skel.replace(os.sep, '/').split('/')
    rigs.append({'name': base, 'group': '/'.join(parts[:2]), 'skel': skel.replace(os.sep, '/'),
                 'atlas': atlas.replace(os.sep, '/'), 'pma': pma})
    info = names.get(d.replace(os.sep, '/'), {})
    for k in ('title', 'subtitle', 'skin', 'also', 'display'):
        if info.get(k):
            rigs[-1][k] = info[k]
json.dump(rigs, open('manifest.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
print(len(rigs), 'rigs,', sum('title' in r for r in rigs), 'with English names')
