"""One report after every routing step. Exit code 1 if anything in FAIL is non-empty.
usage: checks.py BOARD [--json OUT] [--final] [--no-justify] [--classes work/net_classes.json]
Checks: unconnected nets, copper clearance (per layer, plus vias and holes through every layer), copper to board edge,
high-impedance nets top-only with no vias, no vias in the hand-swap resistor pads, placement symmetry (mirror or copy),
unjustified vias (via_justify.py). KiCad's own DRC stays the final authority; this is the fast inner loop."""
import sys, os, json, math, re, argparse, itertools, fnmatch
from shapely.strtree import STRtree
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
import board as bd

def _uf(n):
    par = list(range(n))
    def f(i):
        while par[i] != i: par[i] = par[par[i]]; i = par[i]
        return i
    return par, f

def is_tp(pad): return pad['ref'].startswith('TP')
def label(pad): return f"{pad['ref']}.{pad['num']}"

def pad_groups(B, net, without=()):
    """The net's pads as lists of pads joined by copper, leaving out the tracks and vias whose uuids are in `without`.
    A net with a zone counts everything on that zone's layers that lies on the zone (vias, through-hole pads, pads in the pour) as joined."""
    zoned = {}
    for z in B.zones:
        if z['net'] == net and len(z['pts']) > 2:
            for l in z['layers']: zoned.setdefault(l, []).append(Polygon(z['pts']))
    items = []                                                     # (layerset, geom, pad or None)
    for p in B.pads:
        if p['net'] == net and p['layers']: items.append((p['layers'], B.pad_geom(p), p))
    for s in B.segs:
        if s['net'] == net and s['uuid'] not in without: items.append(({s['layer']}, B.seg_geom(s), None))
    for v in B.vias:
        if v['net'] == net and v['uuid'] not in without: items.append((set(bd.LAYERS6), B.via_geom(v), None))
    if not items: return []
    par, f = _uf(len(items)); tree = STRtree([g for _, g, _ in items])
    for i, (L, g, _) in enumerate(items):
        for j in tree.query(g, predicate='intersects'):
            j = int(j)
            if j > i and L & items[j][0]: par[f(i)] = f(j)
    pl = [i for i, (L, g, p) in enumerate(items) if not (p and p['zone_none']) and any(g.intersects(z) for l in L for z in zoned.get(l, ()))]
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
    H = [(v['x'], v['y'], v['drill'], 'via ' + v['net']) for v in B.vias] + [(p['x'], p['y'], p['drill'], label(p)) for p in B.pads if p['drill']]
    out = []
    for a, b in itertools.combinations(H, 2):
        d = math.dist(a[:2], b[:2]) - a[2] / 2 - b[2] / 2
        if d < need - bd.TOL: out.append(dict(a=a[3], b=b[3], d=round(d, 3)))
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
        if B.fps[p['ref']]['hand']:
            g = B.pad_geom(p)
            out += [dict(ref=p['ref'], pad=p['num']) for v in B.vias if g.contains(Point(v['x'], v['y']))]
    return out

def via_layers(B, v):
    """The layers on which the via meets copper of its own net: a track, a pad or one of the net's zones. A track lying wholly
    inside the via leads nowhere, so it does not count."""
    g = B.via_geom(v); near = lambda x, y, r: math.dist((v['x'], v['y']), (x, y)) < r + v['size'] / 2
    out = {s['layer'] for s in B.segs if s['net'] == v['net'] and near(s['x1'], s['y1'], math.dist((s['x1'], s['y1']), (s['x2'], s['y2'])) + s['w'])
           and g.intersects(B.seg_geom(s)) and not (near(s['x1'], s['y1'], 0) and near(s['x2'], s['y2'], 0))}
    out |= {l for p in B.pads if p['net'] == v['net'] and near(p['x'], p['y'], max(p['w'], p['h'])) and g.intersects(B.pad_geom(p)) for l in p['layers']}
    return out | {l for z in B.zones if z['net'] == v['net'] and len(z['pts']) > 2 and Polygon(z['pts']).intersects(g) for l in z['layers']}

def ends_in(B, v):
    """The ends of its net's tracks whose round end reaches the via and that lie outside its pads, as {(layer, x, y): width}: without
    the via, two of them at different points would not meet. The round end counts, as in the router's DRC, which otherwise reports
    the two ends left overlapping as a segment-endpoint-gap. Tracks wholly inside the via lead nowhere and are left out."""
    inside = lambda x, y, r=0: math.dist((v['x'], v['y']), (x, y)) < v['size'] / 2 + r
    pads = [(p['layers'], B.pad_geom(p)) for p in B.pads if p['net'] == v['net'] and math.dist((v['x'], v['y']), (p['x'], p['y'])) < max(p['w'], p['h']) + v['size']]
    return {(s['layer'], round(x, 4), round(y, 4)): s['w'] for s in B.segs if s['net'] == v['net'] and not (inside(s['x1'], s['y1']) and inside(s['x2'], s['y2']))
            for x, y in ((s['x1'], s['y1']), (s['x2'], s['y2'])) if inside(x, y, s['w'] / 2) and not any(s['layer'] in L and g.contains(Point(x, y)) for L, g in pads)}

def dangling_vias(B, nets=None):
    """Vias that meet their net's copper on fewer than two layers, whatever touches them on that one (KiCad DRC: via is connected
    on only one layer)"""
    return [v for v in B.vias if (nets is None or v['net'] in nets) and len(via_layers(B, v)) < 2]

def dangling_tracks(B, nets=None):
    """Tracks with an end point that lies in no other copper of their net on their layer, and without which the net's pads stay joined
    as they are (KiCad DRC: track has an unconnected end). The end point, not the round end of the track: KiCad joins a track end
    only where the point itself is inside other copper, so a stub lying alongside a track is still loose."""
    out = []
    for s in B.segs:
        if nets is not None and s['net'] not in nets: continue
        mine = [g for n, g, k, o in B.copper(s['layer']) if n == s['net'] and o is not s]
        mine += [Polygon(z['pts']) for z in B.zones if z['net'] == s['net'] and s['layer'] in z['layers'] and len(z['pts']) > 2]
        loose = any(not any(g.distance(Point(x, y)) < 1e-3 for g in mine) for x, y in ((s['x1'], s['y1']), (s['x2'], s['y2'])))
        if loose and len(pad_groups(B, s['net'], {s['uuid']})) == len(pad_groups(B, s['net'])): out.append(s)
    return out

def classes_beside(board):
    """{class: [net patterns]} from the .kicad_pro beside the board, or None"""
    pro = os.path.splitext(board)[0] + '.kicad_pro'
    if not os.path.exists(pro): return None
    cl = {}
    for p in json.load(open(pro)).get('net_settings', {}).get('netclass_patterns') or []: cl.setdefault(p['netclass'], []).append(p['pattern'])
    return cl
def tree_len(pts):
    if len(pts) < 2: return 0.0
    inn = {0}; L = 0.0
    while len(inn) < len(pts):
        d, j = min((math.dist(pts[i], pts[j]), j) for i in inn for j in range(len(pts)) if j not in inn); inn.add(j); L += d
    return L
def length_and_tree(B, net):
    """(track length, shortest tree through the pads) of a net, test points aside"""
    return (sum(math.dist((x['x1'], x['y1']), (x['x2'], x['y2'])) for x in B.segs if x['net'] == net),
            tree_len([(p['x'], p['y']) for p in B.pads if p['net'] == net and not is_tp(p)]))
def priority(net, classes):
    """The number of the highest-priority class the net is in (P1_Gate -> 1), or None"""
    return min((int(m.group(1)) for c, pats in (classes or {}).items() for m in [re.match(r'P(\d+)_', c)]
                if m and any(fnmatch.fnmatchcase(net, p) for p in pats)), default=None)

def zone_integrity(B):
    """A supply zone must still join all of its own vias once every other net's copper on its layer, with clearance, is cut out of it.
    Ground pours are not judged: they cover the board and are cut everywhere by design."""
    out = []
    for z in B.zones:
        if not z['net'] or z['net'] in bd.GROUND or len(z['pts']) < 3: continue
        outline = Polygon(z['pts']); half = z['min_thickness'] / 2
        for layer in z['layers']:
            cut = unary_union([g.buffer(max(z['clearance'], bd.clearance(z['net'], n))) for n, g, k, o in B.copper(layer) if n != z['net'] and g.distance(outline) < 1.0])
            fill = outline.difference(cut).buffer(-half).buffer(half)                # KiCad drops fill narrower than the zone's minimum width
            own = [g for n, g, k, o in B.copper(layer) if n == z['net'] and k == 'seg']   # KiCad joins fill pieces through the net's own tracks
            if own: fill = unary_union([fill] + [g for g in own if g.intersects(outline)])
            pieces = [g for g in getattr(fill, 'geoms', [fill]) if not g.is_empty]
            mine = [v for v in B.vias if v['net'] == z['net'] and outline.contains(Point(v['x'], v['y']))]
            home = [next((i for i, g in enumerate(pieces) if g.intersects(B.via_geom(v))), None) for v in mine]
            if len(set(home)) > 1 or None in home:
                groups = {}
                for v, h in zip(mine, home): groups.setdefault(h, []).append([round(v['x'], 2), round(v['y'], 2)])
                main = max((h for h in groups if h is not None), key=lambda h: len(groups[h]), default=None)
                out.append(dict(zone=z['name'], net=z['net'], layer=layer, pieces=len(pieces), cut_off=sorted((vs for h, vs in groups.items() if h != main or h is None), key=len)))
    return out

def symmetry(B, cx=None, shift=None, tol=0.02):
    """every X1nn part must have its X2nn twin either mirrored about the board centre or shifted by `shift` mm"""
    shift = shift if shift is not None else bd.channel_shift(B)
    x0, _, x1, _ = B.outline(); cx = cx if cx is not None else (x0 + x1) / 2; out = []
    for r, f in B.fps.items():
        m = re.match(r'([A-Z]+)1(\d\d)$', r)
        if not m or r.startswith('TP'): continue
        t = B.fps.get(f'{m.group(1)}2{m.group(2)}')
        if not t: continue
        mir = abs(2 * cx - f['x'] - t['x']) < tol and abs(f['y'] - t['y']) < tol
        cl = shift is not None and abs(f['x'] + shift - t['x']) < tol and abs(f['y'] - t['y']) < tol
        if not (mir or cl): out.append(dict(ref=r, twin=t['ref'], dx_mirror=round(2 * cx - f['x'] - t['x'], 3), dx_copy=round(f['x'] + (shift or 0) - t['x'], 3), dy=round(f['y'] - t['y'], 3)))
    return out

def report(B, justify=True, timing=None, classes=None):
    """timing: a dict that receives seconds per check, so a slow step can be traced to the check that costs it.
    classes: the net classes ({class: [patterns]}); with them an unjustified via is must-fix on P1-P3, a warning on P4-P6 and not
    reported on any other net (power and battery nets are low-impedance, so a via costs nothing there)"""
    import time; R = {}
    def run(key, fn):
        t0 = time.perf_counter(); R[key] = fn()
        if timing is not None: timing[key] = round(time.perf_counter() - t0, 3)
    for key, fn in (('unconnected', unconnected), ('clearance', clearances), ('holes', holes), ('edge', edge), ('hz', hz_rule), ('no_via_pads', no_via_pads), ('zone_integrity', zone_integrity), ('symmetry', symmetry)):
        run(key, lambda fn=fn: fn(B))
    run('dangling_vias', lambda: [dict(net=v['net'], at=[round(v['x'], 2), round(v['y'], 2)]) for v in dangling_vias(B)])
    run('dangling_tracks', lambda: [dict(net=s['net'], layer=s['layer'], at=[round(s['x1'], 2), round(s['y1'], 2), round(s['x2'], 2), round(s['y2'], 2)]) for s in dangling_tracks(B)])
    if justify:
        import via_justify; run('unjustified_vias', lambda: [{k: v for k, v in x.items() if k != 'path'} for x in via_justify.check(B)])
        if classes is not None:
            rank = lambda x: priority(x['net'], classes) or 99
            R['unjustified_warnings'] = [x for x in R['unjustified_vias'] if 4 <= rank(x) <= 6]
            R['unjustified_vias'] = [x for x in R['unjustified_vias'] if rank(x) <= 3]
    R['stats'] = dict(tracks=len(B.segs), vias=len(B.vias),
                      length={l: round(sum(math.dist((s['x1'], s['y1']), (s['x2'], s['y2'])) for s in B.segs if s['layer'] == l), 1) for l in B.copper_layers})
    return R
FAIL = ('clearance', 'holes', 'edge', 'hz', 'no_via_pads', 'zone_integrity', 'krt_drc')   # must be empty at every stage; krt_drc is stage_route's second opinion
FINAL = ('unconnected', 'unjustified_vias', 'dangling_vias', 'dangling_tracks', 'too_long')   # too_long is stage_route's; must be empty at the end; symmetry is always informational (some differences are deliberate)
def must_fix(R, final=False): return {k: len(R[k]) for k in FAIL + (FINAL if final else ()) if R.get(k)}

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('board'); ap.add_argument('--json'); ap.add_argument('--no-justify', action='store_true'); ap.add_argument('--final', action='store_true')
    ap.add_argument('--classes', help='net classes as setup saves them (work/net_classes.json)')
    a = ap.parse_args(); B = bd.Board(a.board); R = report(B, not a.no_justify, classes=json.load(open(a.classes)) if a.classes else None); must = must_fix(R, a.final)
    for k, v in R.items():
        if k == 'stats': print('stats', v); continue
        tag = 'FAIL' if k in must else ('note' if v else 'ok  ')
        print(f'{tag} {k:<17} {len(v)}')
        for x in v[:6]: print('       ', x)
    if a.json: json.dump(R, open(a.json, 'w'), indent=1)
    sys.exit(1 if must else 0)
