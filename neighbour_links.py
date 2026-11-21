"""Step 2b: join same-net pads that sit close together with a direct top-layer track, whatever the net class.
A link is added when a legal top path exists with length <= max(RATIO * gap, gap + EXTRA) and gap <= MAX_GAP.
Shortest gaps first; a net's pieces are never joined twice (no loops). Ground is skipped (it gets a via per pad),
high-impedance nets are skipped unless --include-hz (they are routed by hand-reviewed step 2a).
usage: neighbour_links.py IN OUT [--max-gap 4] [--nets ...] [--dry-run] [--json OUT.json]"""
import sys, json, math, argparse, itertools
import board as bd, toplink as tl
RATIO = 1.5; EXTRA = 1.0; MAX_GAP = 4.0          # via_justify judges the supply rails and bias nets by these same three, so the step and its check agree
def widths(net): return (0.4, 0.3, 0.2) if bd.is_supply(net) else (0.2,)

def run(B, max_gap=MAX_GAP, nets=None, include_hz=False, dry=False, log=print):
    added = []; failed = set()
    todo = [n for n in (nets or B.nets) if n not in bd.GROUND and (include_hz or not bd.is_hz(n))]
    while True:
        cand = []
        for net in todo:
            comps = tl.components(B, net)
            for a, b in itertools.combinations(range(len(comps)), 2):
                g, pa, pb = tl.gap(comps[a], comps[b])
                if g <= max_gap: cand.append((g, net, a, b, pa, pb))
        cand.sort(key=lambda c: c[0]); done = None
        for g, net, a, b, pa, pb in cand:
            if (net, pa[2], pb[2], round(g, 3)) in failed: continue
            comps = tl.components(B, net); lim = max(RATIO * g, g + EXTRA)
            for w in widths(net):
                r = tl.top_path(B, net, comps[a], comps[b], w, max_len=lim)
                if r and r[0] <= lim:
                    done = dict(net=net, a=pa[2], b=pb[2], gap=round(g, 2), length=round(r[0], 2), width=w, path=r[1]); break
            if done: break
            failed.add((net, pa[2], pb[2], round(g, 3)))
        if not done: break
        pts = done['path']
        if not dry: B.add([B.seg_text(*pts[k], *pts[k + 1], done['width'], 'F.Cu', done['net']) for k in range(len(pts) - 1)])
        else: failed.add((done['net'], done['a'], done['b'], round(done['gap'], 3)))
        added.append(done); log(f"link {done['net']:<22} {done['a']:>9} -> {done['b']:<9} gap {done['gap']:.2f} len {done['length']:.2f} w {done['width']}")
    return added

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('inp'); ap.add_argument('out'); ap.add_argument('--max-gap', type=float, default=MAX_GAP)
    ap.add_argument('--nets', nargs='*'); ap.add_argument('--include-hz', action='store_true'); ap.add_argument('--dry-run', action='store_true'); ap.add_argument('--json')
    a = ap.parse_args(); B = bd.Board(a.inp)
    added = run(B, a.max_gap, a.nets, a.include_hz, a.dry_run)
    print(len(added), 'links,', round(sum(x['length'] for x in added), 1), 'mm')
    if not a.dry_run: B.save(a.out)
    if a.json: json.dump(added, open(a.json, 'w'), indent=1)
