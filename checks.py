"""One report after every routing step. Exit code 1 if anything in FAIL is non-empty.
usage: checks.py BOARD [--json OUT] [--final] [--no-justify]
Checks: unconnected nets, copper clearance (per layer, plus vias and holes through every layer), copper to board edge,
high-impedance nets top-only with no vias, no vias in the hand-swap resistor pads, placement symmetry (mirror or copy),
unjustified vias (via_justify.py). KiCad's own DRC stays the final authority; this is the fast inner loop."""
import sys, json, math, re, argparse, itertools
from shapely.strtree import STRtree
from shapely.geometry import Point
import board as bd

def _uf(n):
    par = list(range(n))
    def f(i):
        while par[i] != i: par[i] = par[par[i]]; i = par[i]
        return i
    return par, f

def is_tp(pad): return pad['ref'].startswith('TP')
def label(pad): return f"{pad['ref']}.{pad['num']}"

def pad_groups(B, net):
    """The net's pads as lists of pads joined by copper.
    A net with a zone counts everything on that zone's layers (vias, through-hole pads, pads lying in the pour) as joined."""
    zoned = set()
    for z in B.zones:
        if z['net'] == net: zoned.update(z['layers'])
    items = []                                                     # (layerset, geom, pad or None)
    for p in B.pads:
        if p['net'] == net and p['layers']: items.append((p['layers'], B.pad_geom(p), p))
    for s in B.segs:
        if s['net'] == net: items.append(({s['layer']}, B.seg_geom(s), None))
    for v in B.vias:
        if v['net'] == net: items.append((set(bd.LAYERS6), B.via_geom(v), None))
    if not items: return []
    par, f = _uf(len(items)); tree = STRtree([g for _, g, _ in items])
    for i, (L, g, _) in enumerate(items):
        for j in tree.query(g, predicate='intersects'):
            j = int(j)
            if j > i and L & items[j][0]: par[f(i)] = f(j)
    pl = [i for i, (L, g, p) in enumerate(items) if L & zoned]     # anything on a layer that carries this net's zone
    for i in pl[1:]: par[f(i)] = f(pl[0])
    groups = {}
    for i, (L, g, p) in enumerate(items):
        if p: groups.setdefault(f(i), []).append(p)
    return list(groups.values())

def unconnected(B, nets=None):
    """nets whose pads are not all joined by copper, each with its pieces except the largest"""
    out = []
    for net in (nets or B.nets):
        groups = [[label(p) for p in g] for g in pad_groups(B, net)]
        if len(groups) > 1: out.append(dict(net=net, pieces=len(groups), pads=sorted(groups, key=len)[:-1]))
    return out

def tp_only(group): return all(is_tp(p) for p in group)

def top_incomplete(B, net):
    """A top-only pass cannot reach a bottom-side test point, so step 2e judges a net by its other pads."""
    return sum(not tp_only(g) for g in pad_groups(B, net)) > 1

def tp_joined(B, pad):
    return any(pad in g and not tp_only(g) for g in pad_groups(B, pad['net']))

def loose_testpoint_nets(B):
    out = []
    for net in B.nets:
        loose = [tp_only(g) for g in pad_groups(B, net)]
        if any(loose) and not all(loose): out.append(net)
    return out

def clearances(B, eps=bd.TOL):
    out = []
    for layer in B.copper_layers:
        cu = B.copper(layer); tree = STRtree([g for _, g, _, _ in cu])
        for i, (n, g, k, o) in enumerate(cu):
            for j in tree.query(g.buffer(bd.CLEAR_HZ + 0.01)):
                j = int(j)
                if j <= i: continue
                m, h, k2, o2 = cu[j]
                if m == n and n: continue
                if k == 'pad' and k2 == 'pad' and o['ref'] == o2['ref']: continue      # footprint-internal spacing is the library's business
                need = bd.clearance(n, m); d = g.distance(h)
                if d < need - eps:
                    c = g.centroid; out.append(dict(layer=layer, a_net=n, b_net=m, a=k, b=k2, d=round(d, 3), need=need, at=[round(c.x, 2), round(c.y, 2)]))
    return out

def holes(B, need=bd.HOLE_GAP):
    H = [(v['x'], v['y'], v['drill'], 'via ' + v['net']) for v in B.vias] + [(p['x'], p['y'], p['drill'], f"{p['ref']}.{p['num']}") for p in B.pads if p['drill']]
    out = []
    for a, b in itertools.combinations(H, 2):
        d = math.dist(a[:2], b[:2]) - a[2] / 2 - b[2] / 2
        if d < need - 1e-3: out.append(dict(a=a[3], b=b[3], d=round(d, 3)))
    return out

def edge(B, need=bd.EDGE):
    ol = B.outline(); out = []
    for s in B.segs:
        m = float(min(bd.edge_room(ol, s['x1'], s['y1'], s['w'] / 2), bd.edge_room(ol, s['x2'], s['y2'], s['w'] / 2)))
        if m < need - bd.TOL: out.append(dict(net=s['net'], d=round(m, 3)))
    for v in B.vias:
        m = float(bd.edge_room(ol, v['x'], v['y'], v['size'] / 2))
        if m < need - bd.TOL: out.append(dict(net=v['net'], d=round(m, 3), via=True))
    return out

def hz_rule(B):
    out = [dict(net=s['net'], why='track on ' + s['layer']) for s in B.segs if bd.is_hz(s['net']) and s['layer'] != 'F.Cu']
    return out + [dict(net=v['net'], why='via', at=[v['x'], v['y']]) for v in B.vias if bd.is_hz(v['net'])]

def no_via_pads(B):
    out = []
    for p in B.pads:
        if p['ref'] in bd.NO_VIA_REFS:
            g = B.pad_geom(p)
            out += [dict(ref=p['ref'], pad=p['num']) for v in B.vias if g.contains(Point(v['x'], v['y']))]
    return out

def symmetry(B, cx=None, shift=19.45, tol=0.02):
    """every X1nn part must have its X2nn twin either mirrored about the board centre or shifted by `shift` mm"""
    x0, _, x1, _ = B.outline(); cx = cx if cx is not None else (x0 + x1) / 2; out = []
    for r, f in B.fps.items():
        m = re.match(r'([A-Z]+)1(\d\d)$', r)
        if not m or r.startswith('TP'): continue
        t = B.fps.get(f'{m.group(1)}2{m.group(2)}')
        if not t: continue
        mir = abs(2 * cx - f['x'] - t['x']) < tol and abs(f['y'] - t['y']) < tol
        cl = abs(f['x'] + shift - t['x']) < tol and abs(f['y'] - t['y']) < tol
        if not (mir or cl): out.append(dict(ref=r, twin=t['ref'], dx_mirror=round(2 * cx - f['x'] - t['x'], 3), dx_copy=round(f['x'] + shift - t['x'], 3), dy=round(f['y'] - t['y'], 3)))
    return out

def report(B, justify=True):
    R = dict(unconnected=unconnected(B), clearance=clearances(B), holes=holes(B), edge=edge(B), hz=hz_rule(B), no_via_pads=no_via_pads(B), symmetry=symmetry(B))
    if justify:
        import via_justify; R['unjustified_vias'] = [{k: v for k, v in x.items() if k != 'path'} for x in via_justify.check(B)]
    R['stats'] = dict(tracks=len(B.segs), vias=len(B.vias),
                      length={l: round(sum(math.dist((s['x1'], s['y1']), (s['x2'], s['y2'])) for s in B.segs if s['layer'] == l), 1) for l in B.copper_layers})
    return R
FAIL = ('clearance', 'holes', 'edge', 'hz', 'no_via_pads', 'krt_drc')   # must be empty at every stage; krt_drc is stage_route's second opinion
FINAL = ('unconnected', 'unjustified_vias')                        # must be empty at the end; symmetry is always informational (some differences are deliberate)
def must_fix(R, final=False): return {k: len(R[k]) for k in FAIL + (FINAL if final else ()) if R.get(k)}

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('board'); ap.add_argument('--json'); ap.add_argument('--no-justify', action='store_true'); ap.add_argument('--final', action='store_true')
    a = ap.parse_args(); B = bd.Board(a.board); R = report(B, not a.no_justify); must = must_fix(R, a.final)
    for k, v in R.items():
        if k == 'stats': print('stats', v); continue
        tag = 'FAIL' if k in must else ('note' if v else 'ok  ')
        print(f'{tag} {k:<17} {len(v)}')
        for x in v[:6]: print('       ', x)
    if a.json: json.dump(R, open(a.json, 'w'), indent=1)
    sys.exit(1 if must else 0)
