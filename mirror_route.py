"""Step 2h: copy one channel's routing to the other so both sides are identical.
For every net that only touches source-channel parts (X1nn, plus its test points and wire pads), find how its pads map to the
twin parts (X2nn): mirrored about the board centre, or shifted by SHIFT mm. If every pad of the net maps the same way,
its tracks and vias are transformed the same way and written on the twin net (whatever was on the twin net is removed first).
Nets that mix both mappings, or touch shared parts (3xx, U5, U6), are listed and left for individual routing.
usage: mirror_route.py IN OUT [--from 1] [--dry-run] [--json OUT.json]"""
import sys, re, json, argparse
import board as bd
SHIFT = 19.45; TOL = 0.03

def is_src(ref, src): return bool(re.match(r'[A-Z]+%s\d\d$' % src, ref)) and not ref.startswith('TP')
def is_dst(ref, src): return bool(re.match(r'[A-Z]+%s\d\d$' % ('2' if src == '1' else '1'), ref)) and not ref.startswith('TP')

def plan(B, src='1'):
    """Pads are paired by position, not by name, so shared parts with one half per channel (U6) pair up too.
    Test points are ignored here: they are connected after this step."""
    x0, _, x1, _ = B.outline(); cx = (x0 + x1) / 2; sgn = 1 if src == '1' else -1
    T = {'mirror': lambda x: 2 * cx - x, 'copy': lambda x: x + sgn * SHIFT}
    at = {}
    for p in B.pads:
        if not p['ref'].startswith('TP'): at.setdefault((round(p['x'] / 0.05), round(p['y'] / 0.05)), []).append(p)
    def lookup(x, y):
        k = (round(x / 0.05), round(y / 0.05))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for q in at.get((k[0] + dx, k[1] + dy), []):
                    if abs(q['x'] - x) < TOL and abs(q['y'] - y) < TOL: return q
    byn = {}
    for p in B.pads:
        if p['net'] and not p['ref'].startswith('TP'): byn.setdefault(p['net'], []).append(p)
    todo = []; skipped = []
    for net, pads in sorted(byn.items()):
        if net in bd.GROUND or bd.is_supply(net): continue
        if not any(is_src(p['ref'], src) for p in pads) or any(is_dst(p['ref'], src) for p in pads): continue
        found = None
        for mode, f in T.items():
            qs = [lookup(f(p['x']), p['y']) for p in pads]
            if any(q is None for q in qs): continue
            tn = {q['net'] for q in qs}
            if len(tn) == 1 and net not in tn and len(byn.get(next(iter(tn)), [])) == len(pads): found = (mode, tn.pop()); break
        if found: todo.append(dict(net=net, twin=found[1], mode=found[0]))
        else: skipped.append(dict(net=net, why='its pads have no consistent mirrored or shifted twins'))
    return todo, skipped, T

def run(B, src='1', dry=False):
    todo, skipped, T = plan(B, src); new = []; rm = []
    for t in todo:
        f = T[t['mode']]
        rm += [s['uuid'] for s in B.segs if s['net'] == t['twin']] + [v['uuid'] for v in B.vias if v['net'] == t['twin']]
        for s in B.segs:
            if s['net'] == t['net']: new.append(B.seg_text(f(s['x1']), s['y1'], f(s['x2']), s['y2'], s['w'], s['layer'], t['twin']))
        for v in B.vias:
            if v['net'] == t['net']: new.append(B.via_text(f(v['x']), v['y'], v['size'], v['drill'], t['twin']))
    if not dry: B.remove(rm); B.add(new)
    return todo, skipped

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('inp'); ap.add_argument('out'); ap.add_argument('--from', dest='src', default='1', choices=['1', '2'])
    ap.add_argument('--dry-run', action='store_true'); ap.add_argument('--json'); a = ap.parse_args(); B = bd.Board(a.inp)
    todo, skipped = run(B, a.src, a.dry_run)
    print(len(todo), 'nets copied:', {m: sum(t['mode'] == m for t in todo) for m in ('mirror', 'copy')})
    for s in skipped: print('  left for individual routing:', s['net'], '-', s['why'])
    if not a.dry_run:
        import checks
        pieces = lambda nets: {u['net']: u['pieces'] for u in checks.unconnected(B, nets)}
        ps = pieces([t['net'] for t in todo]); pt = pieces([t['twin'] for t in todo])
        diff = [(t['net'], ps.get(t['net'], 1), t['twin'], pt.get(t['twin'], 1)) for t in todo if ps.get(t['net'], 1) != pt.get(t['twin'], 1)]
        twins = {t['twin'] for t in todo}; cl = [c for c in checks.clearances(B) if c['a_net'] in twins or c['b_net'] in twins]
        print('after copy: twin nets whose connectivity differs from the source', len(diff), '| clearance problems', len(cl))
        for x in (diff + cl)[:10]: print('   ', x)
        B.save(a.out, crlf=False)
        if diff or cl: sys.exit(1)
    if a.json: json.dump(dict(copied=todo, skipped=skipped), open(a.json, 'w'), indent=1)
