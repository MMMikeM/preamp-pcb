"""Unjustified-via check: every time one net exists as two separate pieces on the top layer that are close together,
ask whether they could have been joined on the top layer instead of through vias and another layer.
Flag when a legal top-layer path exists with length <= max(RATIO * gap, gap + EXTRA).
usage: via_justify.py BOARD [--json OUT] [--max-gap 8] [--include-gnd] [--include-decaps]"""
import sys, json, math, argparse, itertools
import board as bd, toplink as tl
RATIO = 1.5; EXTRA = 3.0; MAX_GAP = 8.0

def is_decap(B, pad):
    nets = {p['net'] for p in B.fps[pad['ref']]['pads']}
    return pad['ref'].startswith('C') and 'GND' in nets and nets & (bd.RAILS | bd.BIAS)

def check(B, max_gap=MAX_GAP, include_gnd=False, include_decaps=False, nets=None, width=0.2):
    flags = []
    for net in (nets or B.nets):
        if net in bd.GROUND and not include_gnd: continue
        comps = tl.components(B, net)
        if len(comps) < 2: continue
        cand = []
        for a, b in itertools.combinations(range(len(comps)), 2):
            A, C = comps[a], comps[b]
            if not include_decaps and bd.is_supply(net) and any(len(c['pads']) == 1 and not c['segs'] and is_decap(B, c['pads'][0]) for c in (A, C)): continue
            g, pa, pb = tl.gap(A, C)
            if g <= max_gap: cand.append((g, a, b, pa, pb))
        par = list(range(len(comps)))
        def f(i):
            while par[i] != i: par[i] = par[par[i]]; i = par[i]
            return i
        for g, a, b, pa, pb in sorted(cand):
            if f(a) == f(b): continue                      # already explained by a shorter flagged link
            lim = max(RATIO * g, g + EXTRA)
            r = tl.top_path(B, net, comps[a], comps[b], width, max_len=lim)
            if r and r[0] <= lim:
                par[f(a)] = f(b)
                flags.append(dict(net=net, a=pa[2], b=pb[2], at=[round(pa[0], 2), round(pa[1], 2)], to=[round(pb[0], 2), round(pb[1], 2)],
                                  gap=round(g, 2), top_path=round(r[0], 2), limit=round(lim, 2),
                                  vias=[[round(v['x'], 2), round(v['y'], 2)] for c in (comps[a], comps[b]) for v in c['vias']],
                                  path=[[round(x, 3), round(y, 3)] for x, y in r[1]]))
    return flags

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('board'); ap.add_argument('--json'); ap.add_argument('--max-gap', type=float, default=MAX_GAP)
    ap.add_argument('--include-gnd', action='store_true'); ap.add_argument('--include-decaps', action='store_true'); ap.add_argument('--nets', nargs='*')
    a = ap.parse_args(); B = bd.Board(a.board)
    fl = check(B, a.max_gap, a.include_gnd, a.include_decaps, a.nets)
    for x in sorted(fl, key=lambda x: x['gap']):
        print(f"{x['net']:<22} {x['a']:>10} -> {x['b']:<10} gap {x['gap']:5.2f}  top path {x['top_path']:5.2f} (limit {x['limit']:.2f})  vias {len(x['vias'])}")
    print(len(fl), 'unjustified links')
    if a.json: json.dump(fl, open(a.json, 'w'), indent=1)
    sys.exit(1 if fl else 0)
