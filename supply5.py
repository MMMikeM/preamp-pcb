"""Step 2d, L5 supply for the LANDSCAPE board (74 x 41): wide zones with a 0.6 mm scaffold track along each.
V-: a bar under the supply row, fingers down at each strip's V- column and one in the middle (right of the REF block).
V+: a finger at each strip's V+ column, one down the middle, joined by a bar along the bottom of the MIDDLE section only
    (never under the input stages, where the gate wire pads pierce every layer). The V+ source sits above the V- bar, so it
    gets ONE crossing on L3. Vias inside a zone need nothing; a via outside gets one straight stub to the nearest scaffold track.
Bias nets are routed afterwards by the router, kept clear of the zones (net clearance widened to the half-width).
usage: supply5.py IN OUT --nc OUT_net_clearances.json"""
import sys, json, uuid, argparse, math
import board as bd
from shapely.geometry import box, Point, LineString
from shapely.ops import unary_union, nearest_points
X, Y = 100, 80; HW = 1.5; W = 0.6; L5 = 'In4.Cu'; L3 = 'In2.Cu'
BOX = {'V-': [box(4.5, 7.4, 22.3, 9.4), box(4.5, 7.4, 7.5, 24.3), box(20.3, 7.4, 22.3, 12.4), box(20.3, 10.4, 59.9, 12.4), box(56.9, 8.9, 59.9, 24.3), box(40.2, 10.4, 43.2, 36.3)],
       'V+': [box(14.1, 11.3, 17.1, 27.9), box(14.1, 24.9, 23.0, 27.9), box(20.5, 24.9, 23.0, 39.8), box(20.5, 37.3, 53.3, 39.8), box(50.5, 13.3, 53.3, 39.8),
              box(50.5, 24.9, 69.6, 27.9), box(66.6, 11.3, 69.6, 27.9), box(30.5, 18.2, 33.5, 39.8)]}
LINES = {'V-': [((6.0, 8.4), (21.3, 8.4)), ((6.0, 8.4), (6.0, 23.9)), ((21.3, 8.4), (21.3, 11.4)), ((21.3, 11.4), (58.4, 11.4)), ((58.4, 9.6), (58.4, 23.9)), ((41.7, 11.4), (41.7, 35.8))],
         'V+': [((15.6, 11.8), (15.6, 26.4)), ((15.6, 26.4), (21.75, 26.4)), ((21.75, 26.4), (21.75, 38.55)), ((21.75, 38.55), (51.9, 38.55)), ((51.9, 14.3), (51.9, 38.55)),
                ((51.9, 26.4), (68.1, 26.4)), ((68.1, 11.8), (68.1, 26.4)), ((32.45, 18.7), (32.45, 38.55))]}
HOP_TOP = 14.3                                             # top of the V+ finger the crossing lands on
SOURCE = ('C301', 'V+')                                    # the V+ source pad above the V- bar; its via hops on L3 into the V+ finger at x = 51.9
def zones(): return BOX
def zone_text(net, poly, name):
    pts = ' '.join(f'(xy {x + X:.3f} {y + Y:.3f})' for x, y in list(poly.exterior.coords)[:-1])
    return (f'\n\t(zone\n\t\t(net "{net}")\n\t\t(layer "{L5}")\n\t\t(uuid "{uuid.uuid4()}")\n\t\t(name "{name}")\n\t\t(hatch edge 0.5)\n\t\t(priority 2)\n'
            f'\t\t(connect_pads yes\n\t\t\t(clearance 0.2)\n\t\t)\n\t\t(min_thickness 0.25)\n\t\t(fill yes\n\t\t\t(thermal_gap 0.4)\n\t\t\t(thermal_bridge_width 0.4)\n\t\t\t(island_removal_mode 0)\n\t\t)\n'
            f'\t\t(polygon\n\t\t\t(pts\n\t\t\t\t{pts}\n\t\t\t)\n\t\t)\n\t)\n')
def track_fits(B, net, layer, path, w=W):
    """True if a track along `path` (mm from the board corner) keeps its clearance from every other net's copper on that layer."""
    line = LineString([(x + X, y + Y) for x, y in path])
    return all(line.distance(g) >= bd.clearance(net, n) + w / 2 - bd.TOL for n, g, k, o in B.copper(layer) if n != net)
def run(B, log=print):
    import drops
    Z = {n: unary_union(b) for n, b in BOX.items()}; out = []
    assert Z['V+'].distance(Z['V-']) >= 0.5, f"V+ and V- zones only {Z['V+'].distance(Z['V-']):.2f} mm apart"
    S = lambda n, a, b, l=L5, w=W: out.append(B.seg_text(a[0] + X, a[1] + Y, b[0] + X, b[1] + Y, w, l, n))
    for n in LINES:
        for a, b in LINES[n]: S(n, a, b)
        scaf = unary_union([LineString(l) for l in LINES[n]]); other = Z['V+' if n == 'V-' else 'V-']
        foreign = [Point(v['x'] - X, v['y'] - Y).buffer(v['size'] / 2) for v in B.vias if v['net'] != n] + [Point(p['x'] - X, p['y'] - Y).buffer(max(p['w'], p['h']) / 2) for p in B.pads if p['drill'] and p['net'] != n]
        for a, b in LINES[n]:                                   # a scaffold track must clear foreign holes, or be cut later by trim_centres (vias) - through-hole pads are fatal
            hit = [1 for p in B.pads if p['drill'] and p['net'] != n and LineString([a, b]).distance(Point(p['x'] - X, p['y'] - Y)) < max(p['w'], p['h']) / 2 + bd.CLEAR + W / 2]
            if hit: raise SystemExit(f'{n} scaffold {a}->{b} hits a through-hole pad')
        for v in [v for v in B.vias if v['net'] == n]:
            p = Point(v['x'] - X, v['y'] - Y)
            if scaf.distance(p) < 0.05: continue
            if n == 'V+' and any(abs(q['x'] - v['x']) < 0.6 and abs(q['y'] - v['y']) < 0.6 for q in B.fps[SOURCE[0]]['pads'] if q['net'] == 'V+'): continue    # the source: joined by the L3 crossing below
            def snap(l):                                             # nearest point on a scaffold track; within 0.5 mm of its end, use the end itself (no near-miss endpoints)
                e = nearest_points(LineString(l), p)[0]; return next((Point(q) for q in l if e.distance(Point(q)) < 0.5), e)
            cands = sorted((snap(l) for l in LINES[n]), key=lambda e: e.distance(p))
            for e in cands:
                ln = LineString([(p.x, p.y), (e.x, e.y)])
                if min([ln.distance(f) for f in foreign] + [9]) >= bd.CLEAR + W / 2 and ln.distance(other) >= bd.CLEAR + W / 2:
                    S(n, (p.x, p.y), (e.x, e.y)); log(f'stub {n} ({p.x:.1f},{p.y:.1f}) -> ({e.x:.1f},{e.y:.1f}) {ln.length:.1f} mm' + ('' if Z[n].contains(p) else ' (via outside the zone)')); break
            else: raise SystemExit(f'no straight stub for {n} via at ({p.x:.1f},{p.y:.1f})')
        for i, g in enumerate(Z[n].geoms if Z[n].geom_type == 'MultiPolygon' else [Z[n]]): out.append(zone_text(n, g, f'{n}_In4_{i}'))
    # the one crossing: source via -> L3 -> a new via on the V+ finger at x = 51.9, as close below the V- bar as both the via and the L3 track are legal
    src = next(q for q in B.fps[SOURCE[0]]['pads'] if q['net'] == 'V+'); sv = next(v for v in B.vias if v['net'] == 'V+' and abs(v['x'] - src['x']) < 0.6 and abs(v['y'] - src['y']) < 0.6)
    B.add(out); out = []; P = drops.Placer(B); a = (sv['x'] - X, sv['y'] - Y); found = None        # this run's own copper is on the board before the crossing is judged against it
    for k in range(0, 200):
        land = (51.9, HOP_TOP - 0.5 + 0.05 * k); d = abs(land[0] - a[0])
        path = [a, (a[0], land[1] - d), land] if land[1] - a[1] > d else [a, land]
        if Z['V+'].contains(Point(land).buffer(0.3)) and P.legal(land[0] + X, land[1] + Y, 0.6, 0.3, 'V+') and track_fits(B, 'V+', L3, path): found = (land, path); break
    if not found: raise SystemExit('no legal landing via and L3 track for the V+ crossing')
    land, path = found; out.append(B.via_text(X + land[0], Y + land[1], 0.6, 0.3, 'V+'))
    for p, q in zip(path, path[1:]): S('V+', p, q, L3)
    if land[1] < HOP_TOP - 0.01: S('V+', land, (51.9, HOP_TOP))
    log(f'V+ crossing on L3: ({a[0]:.2f},{a[1]:.2f}) -> ({land[0]:.2f},{land[1]:.2f}), {math.dist(a, land):.1f} mm')
    B.add(out); trim_centres(B, log); return []
def is_centre(B, s):
    """A scaffold track: the filled zone makes it redundant, so a via may land on it (see trim_centres)."""
    if s.get('layer') != L5 or s.get('net') not in LINES or abs(s['w'] - W) > 1e-6: return False
    a = Point(s['x1'] - X, s['y1'] - Y); b = Point(s['x2'] - X, s['y2'] - Y); sc = unary_union([LineString(l) for l in LINES[s['net']]])
    return sc.distance(a) < 0.02 and sc.distance(b) < 0.02
def trim_centres(B, log=print):
    """Cut each scaffold track back from any other net's via that now sits on it; the zone carries the current round the via."""
    out = []; gone = []
    for s in [s for s in B.segs if is_centre(B, s)]:
        a = (s['x1'], s['y1']); b = (s['x2'], s['y2']); L = math.dist(a, b); ln = LineString([a, b]); cuts = []
        if L < 1e-6: continue
        for v in B.vias:
            m = v['size'] / 2 + bd.CLEAR + W / 2 + 0.05
            if v['net'] != s['net'] and ln.distance(Point(v['x'], v['y'])) < m - 0.05: t = ln.project(Point(v['x'], v['y'])); cuts.append((t - m, t + m))
        if not cuts: continue
        gone.append(s['uuid']); pos = 0.0
        for lo, hi in sorted(cuts) + [(L, L)]:
            if lo - pos > 0.3:
                p, q = ln.interpolate(pos), ln.interpolate(min(lo, L)); out.append(B.seg_text(p.x, p.y, q.x, q.y, W, L5, s['net']))
            pos = max(pos, hi)
        log(f"scaffold track of {s['net']} cut at {len(cuts)} via(s)")
    if gone: B.remove(gone); B.add(out)
    return len(gone)

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('inp'); ap.add_argument('out'); ap.add_argument('--nc'); a = ap.parse_args()
    B = bd.Board(a.inp); todo = run(B); B.save(a.out)
    if a.nc:
        import os; nc = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'net_clearances.json'))); nc.update({'V+': HW - W / 2 + bd.CLEAR, 'V-': HW - W / 2 + bd.CLEAR}); json.dump(nc, open(a.nc, 'w'), indent=1)
    print('TODO', *todo)
