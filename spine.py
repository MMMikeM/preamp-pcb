"""L5 supply spines: an interdigitated comb. V- enters top-left, V+ top-right.
V-: bar across the top, fingers down at the left of each op-amp column. V+: right finger down the board, bar across the bottom, finger back up.
Finger x and bar y are searched near nominal for the most clearance to other-net holes. Stubs are left to the router."""
import sys, math
import board as bd
from shapely.geometry import LineString, Point
W = 0.6; L = 'In4.Cu'
def obstacles(B, net):
    o = [Point(v['x'], v['y']).buffer(v.get('size', 0.6) / 2) for v in B.vias if v['net'] != net]
    o += [Point(p['x'], p['y']).buffer(max(p['w'], p['h']) / 2) for p in B.pads if p['drill'] and p['net'] != net]
    return o
def clear(obs, a, b): return min([LineString([a, b]).distance(o) for o in obs] or [9]) - W / 2
def best(obs, mk, lo, hi, nominal, step=0.05):
    c = [(lo + i * step) for i in range(int((hi - lo) / step) + 1)]
    ok = [(abs(v - nominal), v) for v in c if clear(obs, *mk(v)) >= 0.3]
    if not ok: v = max(c, key=lambda v: clear(obs, *mk(v))); raise SystemExit(f'no clear line near {nominal}: best {v:.2f} has {clear(obs, *mk(v)):.2f}')
    return round(min(ok)[1], 2)
def plan(B):
    X, Y = 100, 80; out = []
    def line(net, a, b): out.append(B.seg_text(a[0], a[1], b[0], b[1], W, L, net))
    om = obstacles(B, 'V-'); op = obstacles(B, 'V+')
    yb = best(om, lambda y: ((X + 4, y), (X + 27, y)), Y + 8.5, Y + 12.5, Y + 10)
    xl = best(om, lambda x: ((x, yb), (x, Y + 57)), X + 4.5, X + 8, X + 6.0)
    xr = best(om, lambda x: ((x, yb), (x, Y + 57)), X + 23.5, X + 27, X + 25.4)
    line('V-', (xl, yb), (xr, yb)); line('V-', (xl, yb), (xl, Y + 57)); line('V-', (xr, yb), (xr, Y + 57))
    yq = best(op, lambda y: ((X + 14, y), (X + 37, y)), Y + 59, Y + 62.5, Y + 60)
    pl = best(op, lambda x: ((x, Y + 17.5), (x, yq)), X + 13.5, X + 17.5, X + 15.6)
    pr = best(op, lambda x: ((x, Y + 7.5), (x, yq)), X + 33.5, X + 38.6, X + 35.1)
    line('V+', (pl, yq), (pr, yq)); line('V+', (pl, Y + 17.5), (pl, yq)); line('V+', (pr, Y + 7.5), (pr, yq))
    print(f'V- bar y {yb-Y:.2f} fingers x {xl-X:.2f} {xr-X:.2f} | V+ bar y {yq-Y:.2f} fingers x {pl-X:.2f} {pr-X:.2f}')
    return out
if __name__ == '__main__':
    B = bd.Board(sys.argv[1]); B.add(plan(B)); B.save(sys.argv[2])
