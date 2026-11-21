"""Step 2h: copy one channel's routing to the other so both sides are identical.
For every net that only touches source-channel parts (X1nn, plus its test points and wire pads), find how its pads map to the
twin parts (X2nn): mirrored about the board centre, or shifted by the channel offset (board.channel_shift). If every pad of the net maps the same way,
its tracks and vias are transformed the same way and written on the twin net (whatever was on the twin net is removed first).
A net with no routing of its own is not copied, and neither is one whose copy would crowd copper that is staying (a supply
track, a net left for individual routing, an earlier copy made with the other mapping). Its twin then keeps whatever it has.
Nets that mix both mappings, or touch shared parts (3xx, U5, U6), are listed and left for individual routing.
usage: mirror_route.py IN OUT [--from 1] [--dry-run] [--json OUT.json]"""
import sys, re, json, math, argparse
from shapely.strtree import STRtree
import board as bd, checks
TOL = 0.03

def is_src(ref, src): return bool(re.match(r'[A-Z]+%s\d\d$' % src, ref)) and not ref.startswith('TP')
def is_dst(ref, src): return bool(re.match(r'[A-Z]+%s\d\d$' % ('2' if src == '1' else '1'), ref)) and not ref.startswith('TP')

def plan(B, src='1'):
    """Pads are paired by position, not by name, so shared parts with one half per channel (U6) pair up too.
    Test points are ignored here: they are connected after this step."""
    x0, _, x1, _ = B.outline(); cx = (x0 + x1) / 2; sgn = 1 if src == '1' else -1
    shift = bd.channel_shift(B); T = {'mirror': lambda x: 2 * cx - x}
    if shift is not None: T['copy'] = lambda x: x + sgn * shift
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

def waits_for_copy(B, src='1'):
    """Nets to leave unrouted until the copy is made: the twins it will fill. The other channel's own nets are routed with this
    channel's in each step, so a placement where the strips do not line up is not routed one channel after the other."""
    return {t['twin'] for t in plan(B, src)[0]}

def blocker(B, twin, segs, vias):
    """what a copy onto the twin net would crowd, or None; the twin's present routing does not count, it is replaced"""
    outline = B.outline()
    if any(bd.edge_room(outline, x, y, half) < bd.EDGE - bd.TOL for x, y, half in
           [(s[a], s[b], s['w'] / 2) for s in segs for a, b in (('x1', 'y1'), ('x2', 'y2'))] + [(v['x'], v['y'], v['size'] / 2) for v in vias]): return 'the board edge'
    holes = [(v['x'], v['y'], v['drill']) for v in B.vias if v['net'] != twin] + [(p['x'], p['y'], p['drill']) for p in B.pads if p['drill']]
    if any(math.dist((v['x'], v['y']), h[:2]) - v['drill'] / 2 - h[2] / 2 < bd.HOLE_GAP - bd.TOL for v in vias for h in holes): return 'a hole'
    for layer in B.copper_layers:
        new = [B.seg_geom(s) for s in segs if s['layer'] == layer] + [B.via_geom(v) for v in vias]
        if not new: continue
        staying = [(n, g) for n, g, k, o in B.copper(layer) if n != twin]; tree = STRtree([g for _, g in staying])   # a via may land on a scaffold track: run() trims it back, as drops does
        for g in new:
            for j in tree.query(g.buffer(bd.CLEAR_HZ + 0.01)):
                n, h = staying[int(j)]
                if g.distance(h) < bd.clearance(twin, n) - bd.TOL: return n or 'unconnected copper'

def other_side(B, net, src='1'):
    """The nets on the other channel's copies of this net's pads (same pad of the part with the other channel's number)."""
    num = {(p['ref'], p['num']): p['net'] for p in B.pads}; flip = '2' if src == '1' else '1'
    return {num[k] for k in ((re.sub(r'^([A-Z]+)%s(\d\d)$' % src, r'\g<1>%s\2' % flip, p['ref']), p['num']) for p in B.pads if p['net'] == net and is_src(p['ref'], src)) if num.get(k)}

def run(B, src='1', dry=False):
    planned, skipped, T = plan(B, src); todo = []
    for t in planned:
        f = T[t['mode']]
        segs = [dict(s, x1=f(s['x1']), x2=f(s['x2'])) for s in B.segs if s['net'] == t['net']]
        vias = [dict(v, x=f(v['x'])) for v in B.vias if v['net'] == t['net']]
        if not segs and not vias:
            skipped.append(dict(net=t['net'], why='it has no routing to copy, so its twin is left as it is')); continue
        if any(x['locked'] for x in B.segs + B.vias if x['net'] == t['twin']):
            skipped.append(dict(net=t['net'], why=f"its twin {t['twin']} has locked copper, which is left as it is")); continue
        hit = blocker(B, t['twin'], segs, vias)
        if hit:
            skipped.append(dict(net=t['net'], why=f"its copy would crowd {hit}, so its twin {t['twin']} is left as it is")); continue
        todo.append(t)
        if dry: continue
        B.remove([x['uuid'] for x in B.segs + B.vias if x['net'] == t['twin']])
        B.add([B.seg_text(s['x1'], s['y1'], s['x2'], s['y2'], s['w'], s['layer'], t['twin']) for s in segs] +
              [B.via_text(v['x'], v['y'], v['size'], v['drill'], t['twin']) for v in vias])
    routed = lambda n: any(x['net'] == n for x in B.segs + B.vias) and not checks.unconnected(B, [n])
    for s in skipped:                                     # a net with nothing to do on the other channel is not work for step 2i, and the report should not say so
        theirs = other_side(B, s['net'], src) - {s['net']}
        if theirs and all(routed(n) for n in theirs): s['already_routed_as'] = sorted(theirs)
    return todo, skipped

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('inp'); ap.add_argument('out'); ap.add_argument('--from', dest='src', default='1', choices=['1', '2'])
    ap.add_argument('--dry-run', action='store_true'); ap.add_argument('--json'); a = ap.parse_args(); B = bd.Board(a.inp)
    if not plan(B, a.src)[0]: sys.exit('no net of this channel has a twin, mirrored or shifted: the placement does not match what this step copies')
    todo, skipped = run(B, a.src, a.dry_run)
    print(len(todo), 'nets copied:', {m: sum(t['mode'] == m for t in todo) for m in ('mirror', 'copy')})
    for s in skipped:
        if 'already_routed_as' in s: print('  already routed on the other channel:', s['net'], 'as', ', '.join(s['already_routed_as']))
        else: print('  left for individual routing:', s['net'], '-', s['why'])
    if a.json: json.dump(dict(copied=todo, skipped=skipped), open(a.json, 'w'), indent=1)
    if not a.dry_run:
        diff = []; cl = []
        if todo:                                          # checks.unconnected treats an empty list as every net
            pieces = lambda nets: {u['net']: u['pieces'] for u in checks.unconnected(B, nets)}
            ps = pieces([t['net'] for t in todo]); pt = pieces([t['twin'] for t in todo])
            diff = [(t['net'], ps.get(t['net'], 1), t['twin'], pt.get(t['twin'], 1)) for t in todo if ps.get(t['net'], 1) != pt.get(t['twin'], 1)]
            twins = {t['twin'] for t in todo}; cl = [c for c in checks.clearances(B) if c['a_net'] in twins or c['b_net'] in twins]
        print('after copy: twin nets whose connectivity differs from the source', len(diff), '| clearance problems', len(cl))
        for x in (diff + cl)[:10]: print('   ', x)
        B.save(a.out)
        if diff or cl: sys.exit(1)
