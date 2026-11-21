"""Shared core for neighbour_links.py and via_justify.py.
 - components(B, net): groups of that net's copper that are already joined on the top layer
 - top_path(B, net, A, Bc, width): shortest legal top-layer path between two components (octilinear, grid search)"""
import math, heapq
import numpy as np, shapely
from shapely.ops import unary_union
from shapely.strtree import STRtree
import board as bd

GRID = 0.05
DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
TURN = 0.15            # mm-equivalent per 45 degrees of turn: keeps paths from stair-stepping
HZ_KEEP = 1.0          # soft keep-away from high-impedance copper for other nets
HZ_COST = 1.5          # extra cost per mm travelled inside that keep-away
LIMIT_BEATS_KEEP_AWAY = True   # rule 3 over rule 2: a join that fits the length limit is made even if it runs inside the keep-away

def components(B, net, layer='F.Cu'):
    """list of dicts: geom (union), anchors [(x, y, label)], pads [...], vias [...] for one net on the top layer"""
    items = [(g, k, o) for n, g, k, o in B.copper(layer) if n == net]
    if not items: return []
    par = list(range(len(items)))
    def f(i):
        while par[i] != i: par[i] = par[par[i]]; i = par[i]
        return i
    tree = STRtree([g for g, _, _ in items])
    for i, (g, _, _) in enumerate(items):
        for j in tree.query(g, predicate='intersects'):
            if j > i: par[f(i)] = f(int(j))
    groups = {}
    for i, it in enumerate(items): groups.setdefault(f(i), []).append(it)
    out = []
    for its in groups.values():
        anchors = []
        for g, k, o in its:
            if k == 'pad': anchors.append((o['x'], o['y'], f"{o['ref']}.{o['num']}"))
            elif k == 'via': anchors.append((o['x'], o['y'], 'via'))
            else: anchors += [(o['x1'], o['y1'], 'track'), (o['x2'], o['y2'], 'track')]
        out.append(dict(net=net, geom=unary_union([g for g, _, _ in its]), anchors=anchors,
                        pads=[o for _, k, o in its if k == 'pad'], vias=[o for _, k, o in its if k == 'via'],
                        segs=[o for _, k, o in its if k == 'seg']))
    return out

def gap(a, b):
    """smallest anchor-to-anchor distance and the two anchors"""
    return min((math.dist(p[:2], q[:2]), p, q) for p in a['anchors'] for q in b['anchors'])

def top_path(B, net, A, Bc, width, margin=3.0, layer='F.Cu', max_len=None):
    """Returns (length, [(x, y), ...]) or None. Starts and ends exactly on an anchor (pad centre, via centre or track end)."""
    g, pa, pb = gap(A, Bc)
    x0 = min(pa[0], pb[0]) - margin; x1 = max(pa[0], pb[0]) + margin; y0 = min(pa[1], pb[1]) - margin; y1 = max(pa[1], pb[1]) + margin
    outline = B.outline(); ox0, oy0, ox1, oy1 = outline
    x0, y0, x1, y1 = max(x0, ox0), max(y0, oy0), min(x1, ox1), min(y1, oy1)
    # grid is anchored on pa so the path leaves that anchor exactly
    i0 = int(math.floor((x0 - pa[0]) / GRID)); j0 = int(math.floor((y0 - pa[1]) / GRID))
    nx = int((x1 - x0) / GRID) + 1; ny = int((y1 - y0) / GRID) + 1
    xs = pa[0] + (i0 + np.arange(nx)) * GRID; ys = pa[1] + (j0 + np.arange(ny)) * GRID
    X, Y = np.meshgrid(xs, ys, indexing='ij')
    win = shapely.box(x0 - 2, y0 - 2, x1 + 2, y1 + 2)
    blocked = np.zeros((nx, ny), bool); soft = np.zeros((nx, ny), bool)
    for n, geom, kind, o in B.copper(layer):
        if n == net or not geom.intersects(win): continue
        blocked |= shapely.contains_xy(geom.buffer(bd.clearance(net, n) + width / 2, 8), X, Y)
        if bd.is_hz(n) and not bd.is_hz(net): soft |= shapely.contains_xy(geom.buffer(HZ_KEEP, 8), X, Y)
    own = shapely.contains_xy(A['geom'], X, Y) | shapely.contains_xy(Bc['geom'], X, Y)
    # A track centred at least width/2 inside our own copper adds no copper, so it is legal wherever it runs.
    # Nearer the rim it sticks out and must keep clearance like any other track. The tolerance keeps the centre line
    # of an own track of the same width usable.
    inside = width / 2 - bd.TOL
    blocked &= ~(shapely.contains_xy(A['geom'].buffer(-inside), X, Y) | shapely.contains_xy(Bc['geom'].buffer(-inside), X, Y))
    # checks.edge measures a track by its extents, own pad or not, so the edge is never waived
    blocked |= bd.edge_room(outline, X, Y, width / 2) < bd.EDGE - 1e-9
    tgt = np.zeros((nx, ny), bool)
    for q in Bc['anchors']:
        ti = int(round((q[0] - xs[0]) / GRID)); tj = int(round((q[1] - ys[0]) / GRID))
        if 0 <= ti < nx and 0 <= tj < ny: tgt[ti, tj] = True
    tgt |= shapely.contains_xy(Bc['geom'].buffer(-width / 2 - 0.02), X, Y)   # any point well inside the other component
    src = []
    for p in A['anchors']:
        si = int(round((p[0] - xs[0]) / GRID)); sj = int(round((p[1] - ys[0]) / GRID))
        on_grid = 0 <= si < nx and 0 <= sj < ny and abs(xs[si] - p[0]) < 1e-6 and abs(ys[sj] - p[1]) < 1e-6
        if on_grid and not blocked[si, sj]: src.append((si, sj))   # the track's end cap sits on the anchor, so the anchor must be legal too
    if not src: return None
    keep_away = soft & ~own; INF = 1e18; cap = max_len if max_len is not None else INF; unreachable = []
    def search(penalised):
        dist = {}; prev = {}; pq = []
        for s in src:
            for d in range(8): dist[(s[0], s[1], d)] = 0.0; heapq.heappush(pq, (0.0, s[0], s[1], d))
        end = None
        while pq:
            c, i, j, d = heapq.heappop(pq)
            if c > dist.get((i, j, d), INF) + 1e-12: continue
            if c > cap + 2.0: break
            if tgt[i, j]: end = (i, j, d); break
            for nd in range(8):
                turn = min((nd - d) % 8, (d - nd) % 8)
                if turn > 2 and c > 0: continue                      # no hairpins / acute corners
                di, dj = DIRS[nd]; a, b = i + di, j + dj
                if not (0 <= a < nx and 0 <= b < ny) or blocked[a, b]: continue
                if di and dj and (blocked[i + di, j] or blocked[i, j + dj]): continue
                step = GRID * (1.41421356 if di and dj else 1.0)
                nc = c + step + (TURN * turn if c > 0 else 0) + (HZ_COST * step if penalised and keep_away[a, b] else 0)
                if nc < dist.get((a, b, nd), INF) - 1e-12:
                    dist[(a, b, nd)] = nc; prev[(a, b, nd)] = (i, j, d); heapq.heappush(pq, (nc, a, b, nd))
        else: unreachable.append(penalised)                       # the queue ran dry before the cut-off: no path at any cost
        if end is None: return None
        cells = [end]
        while cells[-1] in prev: cells.append(prev[cells[-1]])
        cells.reverse(); pts = [(float(xs[i]), float(ys[j])) for i, j, _ in cells]
        # snap the end to the nearest anchor of the other component if that keeps the last leg inside its copper
        e = pts[-1]; q = min(Bc['anchors'], key=lambda q: math.dist(q[:2], e))
        if math.dist(q[:2], e) > 1e-6 and shapely.LineString([e, q[:2]]).within(Bc['geom'].buffer(1e-6)): pts.append((q[0], q[1]))
        out = [pts[0]]                                               # merge collinear runs
        for k in range(1, len(pts) - 1):
            ax, ay = pts[k][0] - out[-1][0], pts[k][1] - out[-1][1]; bx, by = pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]
            if abs(ax * by - ay * bx) > 1e-9: out.append(pts[k])
        out.append(pts[-1])
        return sum(math.dist(out[k], out[k + 1]) for k in range(len(out) - 1)), out
    best = search(penalised=True)
    # The search minimises cost, so the keep-away can push it onto a path over the limit, or past the cut-off above,
    # while a shorter legal path exists. Only then is the keep-away dropped.
    too_long = max_len is not None and (best is None or best[0] > max_len)
    # the keep-away changes costs, not which cells can be reached, so a target the first search could not reach at all stays out of reach
    if too_long and LIMIT_BEATS_KEEP_AWAY and keep_away.any() and not unreachable:
        direct = search(penalised=False)
        if direct and (best is None or direct[0] < best[0]): best = direct
    return best
