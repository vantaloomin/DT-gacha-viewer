"""Reports atlas pages whose regions don't fit inside the page size the atlas declares."""
import glob, re, sys
def pages(path):
    cur = None; reg = None
    for line in open(path, encoding='utf-8').read().replace('\r', '').split('\n'):
        if not line.strip():
            continue
        if not line.startswith(('\t', ' ')):
            if line.strip().endswith('.png'):
                cur = {'name': line.strip(), 'regions': []}; yield cur; reg = None
            else:
                reg = {'name': line.strip()}; cur['regions'].append(reg)
            continue
        k, _, v = line.strip().partition(':'); v = v.strip()
        (reg if reg is not None else cur)[k] = v
for a in sorted(glob.glob(sys.argv[1] if len(sys.argv) > 1 else 'spine/**/*.atlas', recursive=True)):
    for pg in pages(a):
        W, H = map(int, pg['size'].split(','))
        mx = my = 0
        for r in pg['regions']:
            x, y, w, h = map(int, r['bounds'].split(','))
            if r.get('rotate') in ('90', 'true', '270'): w, h = h, w
            mx, my = max(mx, x + w), max(my, y + h)
        if mx > W or my > H:
            print(f"{a} | {pg['name']} declared {W}x{H} scale={pg.get('scale')} regions reach {mx}x{my}")
