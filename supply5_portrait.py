"""Step 2d, L5 supply: an interdigitated comb of wide fingers (zones) with a 0.6 mm centre track in each.
V-: bar across the top, fingers down the left of each op-amp column. V+: two fingers, joined by ONE crossing on L3 (C305 -> R224).
Vias inside a finger need nothing; vias outside get one straight sideways stub. Bias nets (REF, PB) are routed afterwards by the
router with L5 = north-south, L3 = east-west, kept clear of the fingers (net clearance widened to the finger half-width).
usage: supply5.py IN OUT --nc OUT_net_clearances.json"""
import sys, json, uuid, argparse
import board as bd
from shapely.geometry import box, Point, LineString
from shapely.ops import unary_union
X, Y = 100, 80; HW = 1.5; W = 0.6; L5 = 'In4.Cu'; L3 = 'In2.Cu'
XL, XR, PL, PR, YB = 5.65, 24.6, 16.4, 35.35, 9.55          # found by spine.py's clearance search on this placement
HOP_PADS = (('C305', 'V+'), ('R224', 'V+'))                # the one V+ crossing over the V- finger, on L3
def zones():
    return {'V-': [box(XL - HW, YB - 1.2, XR + HW, YB + 1.0), box(XL - HW, YB, XL + HW, 57.4), box(XR - HW, YB, XR + HW, 57.4)],
            'V+': [box(PL - HW, 17.0, PL + HW, 58.6), box(PR - HW, 7.0, PR + HW, 58.6)]}
def zone_text(net, poly, name):
    pts = ' '.join(f'(xy {x + X:.3f} {y + Y:.3f})' for x, y in list(poly.exterior.coords)[:-1])
    return (f'\n\t(zone\n\t\t(net "{net}")\n\t\t(layer "{L5}")\n\t\t(uuid "{uuid.uuid4()}")\n\t\t(name "{name}")\n\t\t(hatch edge 0.5)\n\t\t(priority 2)\n'
            f'\t\t(connect_pads yes\n\t\t\t(clearance 0.2)\n\t\t)\n\t\t(min_thickness 0.25)\n\t\t(fill yes\n\t\t\t(thermal_gap 0.4)\n\t\t\t(thermal_bridge_width 0.4)\n\t\t\t(island_removal_mode 0)\n\t\t)\n'
            f'\t\t(polygon\n\t\t\t(pts\n\t\t\t\t{pts}\n\t\t\t)\n\t\t)\n\t)\n')
def run(B, log=print):
    Z = zones(); out = []; todo = []
    S = lambda n, a, b, l=L5, w=W: out.append(B.seg_text(a[0] + X, a[1] + Y, b[0] + X, b[1] + Y, w, l, n))
    FE = {(XL, 'b'): 57.0, (XR, 'b'): 57.0, (PL, 't'): 17.5, (PL, 'b'): 58.2, (PR, 't'): 7.5, (PR, 'b'): 58.2}     # finger ends; snapped to a stub that lands within 0.5 mm, so no near-miss endpoints
    (ax, ay), (bx, by) = [next((p['x'] - X, p['y'] - Y) for p in B.fps[r]['pads'] if p['net'] == n) for r, n in HOP_PADS]
    for hx, hy in ((ax, ay), (bx, by)):
        if not any(abs(v['x'] - X - hx) < 0.5 and abs(v['y'] - Y - hy) < 0.5 and v['net'] == 'V+' for v in B.vias): out.append(B.via_text(X + hx, Y + hy, 0.6, 0.3, 'V+'))
        else: hv = next(v for v in B.vias if abs(v['x'] - X - hx) < 0.5 and abs(v['y'] - Y - hy) < 0.5 and v['net'] == 'V+'); (ax, ay) if False else None
    ends2 = []
    for hx, hy in ((ax, ay), (bx, by)):
        v = next((v for v in B.vias if abs(v['x'] - X - hx) < 0.5 and abs(v['y'] - Y - hy) < 0.5 and v['net'] == 'V+'), None); ends2.append((v['x'] - X, v['y'] - Y) if v else (hx, hy))
    (ax, ay), (bx, by) = ends2; d = min(abs(bx - ax), abs(by - ay)); sx = 1 if bx > ax else -1; sy = 1 if by > ay else -1
    mid1 = (ax, by - sy * d) if abs(by - ay) > abs(bx - ax) else (bx - sx * d, ay)       # straight first, then one 45 degree run into the far via
    if mid1 != (ax, ay): S('V+', (ax, ay), mid1, L3)
    S('V+', mid1, (bx, by), L3); log(f'V+ crossing on L3: ({ax:.2f},{ay:.2f}) -> ({bx:.2f},{by:.2f})')
    for n, cs in (('V-', ((XL, YB, 57), (XR, YB, 57))), ('V+', ((PL, 17.5, 58.2), (PR, 7.5, 58.2)))):                      # centre tracks must clear foreign holes
        for c, y0, y1 in cs:
            hit = [(round(v['x'] - X, 2), round(v['y'] - Y, 2), v['net']) for v in B.vias if v['net'] != n and y0 - 0.5 < v['y'] - Y < y1 + 0.5 and abs(v['x'] - X - c) < W / 2 + v['size'] / 2 + bd.CLEAR]
            if hit: raise SystemExit(f'{n} finger centre track at x={c} hits {hit}: re-run the spine search')
    for n in Z:
        zu = unary_union(Z[n]); other = unary_union(Z['V+' if n == 'V-' else 'V-'])
        foreign = [Point(v['x'] - X, v['y'] - Y).buffer(v['size'] / 2) for v in B.vias if v['net'] != n] + [Point(p['x'] - X, p['y'] - Y).buffer(max(p['w'], p['h']) / 2) for p in B.pads if p['drill'] and p['net'] != n]
        for v in [v for v in B.vias if v['net'] == n]:
            p = Point(v['x'] - X, v['y'] - Y)
            if zu.contains(p.buffer(v['size'] / 2)): continue
            cs = sorted((XL, XR) if n == 'V-' else (PL, PR), key=lambda c: abs(c - p.x)); ends = [(c, p.y) for c in cs]
            if n == 'V-' and p.y < YB: ends = [(min(max(p.x, XL), XR), YB)]
            for e in ends:
                ln = LineString([(p.x, p.y), e])
                if min([ln.distance(f) for f in foreign] + [9]) >= bd.CLEAR + W / 2 and ln.distance(other) >= bd.CLEAR + W / 2 and zu.buffer(0.01).contains(Point(e)):
                    for k in FE:
                        if k[0] == e[0] and abs(FE[k] - e[1]) < 0.5: FE[k] = e[1]
                    S(n, (p.x, p.y), e); log(f'stub {n} ({p.x:.1f},{p.y:.1f}) -> ({e[0]:.1f},{e[1]:.1f}) {ln.length - (HW if e[1] == p.y else 0):.1f} mm'); break
            else: todo.append(n); log(f'no straight stub for {n} via at ({p.x:.1f},{p.y:.1f}): left to the router')
        for i, g in enumerate(zu.geoms if zu.geom_type == 'MultiPolygon' else [zu]): out.append(zone_text(n, g, f'{n}_In4_{i}'))
    S('V-', (XL, YB), (XR, YB)); S('V-', (XL, YB), (XL, FE[(XL, 'b')])); S('V-', (XR, YB), (XR, FE[(XR, 'b')]))
    S('V+', (PL, FE[(PL, 't')]), (PL, FE[(PL, 'b')])); S('V+', (PR, FE[(PR, 't')]), (PR, FE[(PR, 'b')]))
    B.add(out); return sorted(set(todo))
def is_centre(B, s):
    """A finger's centre track: scaffolding that the filled zone makes redundant, so a via may land on it (see trim_centres)."""
    if s.get('layer') != L5 or s.get('net') not in ('V+', 'V-') or abs(s['w'] - W) > 1e-6: return False
    zu = unary_union(zones()[s['net']]).buffer(0.02)
    return zu.contains(Point(s['x1'] - X, s['y1'] - Y)) and zu.contains(Point(s['x2'] - X, s['y2'] - Y))
def trim_centres(B, log=print):
    """Cut each centre track back from any other net's via that now sits on it; the zone carries the current round the via."""
    import math; out = []; gone = []
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
        log(f"centre track of {s['net']} cut at {len(cuts)} via(s)")
    if gone: B.remove(gone); B.add(out)
    return len(gone)

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('inp'); ap.add_argument('out'); ap.add_argument('--nc'); a = ap.parse_args()
    B = bd.Board(a.inp); todo = run(B); B.save(a.out)
    if a.nc:
        import os; nc = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'net_clearances.json'))); nc.update({'V+': HW - W / 2 + bd.CLEAR, 'V-': HW - W / 2 + bd.CLEAR}); json.dump(nc, open(a.nc, 'w'), indent=1)
    print('TODO', *todo)
