"""A routed board's score, weighted by how much each net cares: a millimetre on a gate is not a millimetre on V+.
Read-only. Every net gets a weight (WEIGHT by class, NODE_WEIGHT by node, standing for the node's impedance; the author's
numbers of 24 Nov) and is scored in two parts:
  placement  weight x its shortest pad-to-pad tree: what the parts' positions force; only moving parts changes it
  routing    weight x (length - tree), + weight x VIA_MM per via, + weight x COUPLE_MM x its coupled length
Coupled length: a victim net's copper (the gates and P1, the drains, the servo inputs: VICTIM_NODES) beside an aggressor's (P5,
the outputs and jacks) on the same layer, weighted by edge-to-edge gap s: in full within 2h, then 5/(1+(s/h)^2), h being the
layer's dielectric to its nearest ground plane (DIELECTRIC, from setup6's stackup). A kilohm node is not a victim: a fraction
of a picofarad puts its corner in the gigahertz. L2 and L4 are ground, so the top layer and L3 do not see each other.
Two nets the circuit joins through a small impedance (one or two 2-pad parts, R <= EXEMPT_R or C >= EXEMPT_C, not by way of
ground, a rail or a bias net) are not charged: stray capacitance there sits beside a far lower path.
Pass/fail rules (gates top-only, nothing open, DRC) stay in checks.py, not here.
usage: score.py BOARD [OTHER] [--classes net_classes.json] [--json OUT]     (two boards: what changed from BOARD to OTHER, and why)"""
import sys, os, re, json, math, fnmatch, argparse
from shapely.geometry import LineString
from shapely.ops import unary_union
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import board as bd, checks, compare_channels as cc

WEIGHT = {1: 100.0, 2: 3.0, 3: 10.0, 4: 3.0, 5: 1.0, 6: 3.0, 7: 0.3, 8: 0.0}      # by class number (P1_Gate -> 1)
NODE_WEIGHT = [('*/GA', 100.0), ('*/GB', 100.0), ('*/LINK', 100.0),               # the pickup node: only 47M and 220p on it
               ('*/SV*', 10.0),                                                    # servo inputs: what lands there passes the integrator, cut ~40 dB
               ('*/DA', 10.0), ('*/DB', 10.0),                                     # op-amp inputs: stray capacitance there touches loop stability
               ('*/VB', 3.0)]                                                      # gate bias: shunted by C103, then 47M into the gate
UNCLASSED = 3.0                                                                    # a signal net no class names
VICTIM_NODES = ('*/DA', '*/DB', '*/SV*')                                           # and every P1 net
AGGRESSORS = {5: 1.0}                                                              # class -> strength; no P4 net is driven by an op-amp output
VIA_MM = 2.0; COUPLE_MM = 5.0
DIELECTRIC = {'F.Cu': 0.0994, 'B.Cu': 0.0994, 'In2.Cu': 0.1164}                    # mm to the nearest ground plane; L3 has 0.55 mm to L2 above
EDGES = (2, 3, 4, 6, 8, 12, 16)                                                    # band edges in units of h; beyond 16h the share is under 2 %
def share(x): return 1.0 if x <= 2 else 5.0 / (1 + x * x)                          # x = gap / h; equal to 1 at x = 2
SHARES = (1.0,) + tuple(share((a + b) / 2) for a, b in zip(EDGES, EDGES[1:]))      # each band at its middle
EXEMPT_R = 10e3; EXEMPT_C = 100e-12
CONSTANTS = dict(WEIGHT=WEIGHT, NODE_WEIGHT=NODE_WEIGHT, UNCLASSED=UNCLASSED, VICTIM_NODES=VICTIM_NODES, AGGRESSORS=AGGRESSORS, VIA_MM=VIA_MM,
                 COUPLE_MM=COUPLE_MM, DIELECTRIC=DIELECTRIC, EDGES=EDGES, SHARES=SHARES, EXEMPT_R=EXEMPT_R, EXEMPT_C=EXEMPT_C)

def classes_for(board, given=None):
    if isinstance(given, dict): return given
    if given: return json.load(open(given))
    return checks.classes_beside(board) or {}

def value(s):
    m = re.fullmatch(r'([0-9.]+)\s*([pnumkKM]?)', s.strip().replace('µ', 'u'))
    return float(m.group(1)) * {'p': 1e-12, 'n': 1e-9, 'u': 1e-6, 'm': 1e-3, 'k': 1e3, 'K': 1e3, 'M': 1e6, '': 1.0}[m.group(2)] if m else None

def exempt_pairs(B):
    """{net: {nets it is joined to through one or two low-impedance 2-pad parts}}, not by way of ground, a rail or a bias net"""
    edges = {}
    for r, f in B.fps.items():
        if r[0] not in 'RC' or len(f['pads']) != 2: continue
        v = value(f['val']); a, b = (p['net'] for p in f['pads'])
        if v is None or not a or not b or a == b: continue
        if (r[0] == 'R' and v <= EXEMPT_R) or (r[0] == 'C' and v >= EXEMPT_C):
            edges.setdefault(a, set()).add((b, f"{r} {f['val']}")); edges.setdefault(b, set()).add((a, f"{r} {f['val']}"))
    through = lambda n: n not in bd.GROUND and not bd.is_supply(n)
    out = {}
    for n in edges:
        for m, p1 in edges[n]:
            out.setdefault(n, {})[m] = p1
            if through(m):
                for k, p2 in edges.get(m, ()):
                    if k != n: out[n].setdefault(k, f'{p1}, {m}, {p2}')
    return out

def routing_total(path, classes=None):
    """The whole board's routing score: what a retry compares"""
    return round(sum(r['p_routing'] for r in score(path, classes)['rows'].values()), 1)

def net_rank(n, cl): return checks.priority(n, cl) or (6 if n in bd.BIAS else 8 if n in bd.GROUND else 7 if bd.is_supply(n) else None)
def net_weight(n, cl):
    """What one mm of the net's track costs"""
    node = next((w for pat, w in NODE_WEIGHT if fnmatch.fnmatchcase(n, pat)), None)
    return node if node is not None else WEIGHT.get(net_rank(n, cl), UNCLASSED)

def score(path, classes=None):
    B = bd.Board(path); cl = classes_for(path, classes)
    rank = lambda n: net_rank(n, cl); weight = lambda n: net_weight(n, cl)
    refs = {}
    for p in B.pads:
        if p['net']: refs.setdefault(p['net'], set()).add(p['ref'])
    exempt = exempt_pairs(B)
    aggressors = sorted({n for n in B.nets if rank(n) in AGGRESSORS})
    line = lambda s: (LineString([(s['x1'], s['y1']), (s['x2'], s['y2'])]), s['w'] / 2)
    agg_cu = {(l, a): unary_union([g for n, g, k, o in B.copper(l) if n == a]) for l in B.copper_layers for a in aggressors if any(n == a for n, *_ in B.copper(l))}
    agg_tracks = {(l, a): [line(s) for s in B.segs if s['net'] == a and s['layer'] == l] for l in B.copper_layers for a in aggressors}
    victim = lambda n: rank(n) == 1 or any(fnmatch.fnmatchcase(n, p) for p in VICTIM_NODES)
    rows = {}
    for n in B.nets:
        r = rank(n); w = weight(n)
        segs = [s for s in B.segs if s['net'] == n]; L = sum(math.dist((s['x1'], s['y1']), (s['x2'], s['y2'])) for s in segs)
        t = checks.tree_len([(p['x'], p['y']) for p in B.pads if p['net'] == n and not checks.is_tp(p)]); V = sum(v['net'] == n for v in B.vias)
        by_aggr = {}
        if victim(n):
            for l in B.copper_layers:
                mine = [line(s) for s in segs if s['layer'] == l]
                pads = [g for m, g, k, o in B.copper(l) if m == n and k in ('pad', 'via')]
                gaps = [e * DIELECTRIC.get(l, max(DIELECTRIC.values())) for e in EDGES]
                for a in aggressors:
                    if a in exempt.get(n, {}): continue
                    per = [0.0] * len(gaps)
                    if mine and (l, a) in agg_cu:                                    # the victim's tracks beside the aggressor's copper
                        per = [x + y for x, y in zip(per, banded(mine, agg_cu[(l, a)], gaps))]
                    if pads and agg_tracks[(l, a)]:                                  # the aggressor's tracks beside the victim's pads and vias
                        per = [x + y for x, y in zip(per, banded(agg_tracks[(l, a)], unary_union(pads), gaps))]
                    if any(x > 1e-6 for x in per):
                        was = by_aggr.get(a, dict(close=0.0, near=0.0, effective=0.0)); k = AGGRESSORS[rank(a)]
                        by_aggr[a] = dict(close=round(was['close'] + per[0], 2), near=round(was['near'] + sum(per), 2),
                                          effective=round(was['effective'] + k * sum(f * mm for f, mm in zip(SHARES, per)), 2))
        c = sum(v['effective'] for v in by_aggr.values())
        ex = max(0.0, L - t) if segs or V else 0.0
        rows[n] = dict(channel=cc.net_channel(n, refs.get(n, ())), cls=r, weight=w, length=round(L, 2), tree=round(t, 2), excess=round(ex, 2), vias=V,
                       coupled_by_aggressor=by_aggr, coupled=round(c, 2),
                       p_placement=round(w * t, 1), p_excess=round(w * ex, 1), p_vias=round(w * VIA_MM * V, 1), p_coupling=round(w * COUPLE_MM * c, 1))
        rows[n]['p_routing'] = round(rows[n]['p_excess'] + rows[n]['p_vias'] + rows[n]['p_coupling'], 1)
    unclassed = sorted(n for n in B.nets if rank(n) is None)
    shown = sorted((n, m, why) for n in B.nets if victim(n) for m, why in exempt.get(n, {}).items() if rank(m) in AGGRESSORS)
    return dict(board=path, rows=rows, unclassed=unclassed, exempt=shown)

def banded(lines, near, gaps):
    """mm of the centre lines [(LineString, half width)] within each of the edge-to-edge `gaps` of the copper `near`, band by band"""
    zone = {}                                                             # one buffer per (gap, half width), not per line
    inside = [sum(g.intersection(zone.get((gap, hw)) or zone.setdefault((gap, hw), near.buffer(gap + hw, 8))).length for g, hw in lines) for gap in gaps]
    return [inside[0]] + [inside[k] - inside[k - 1] for k in range(1, len(inside))]

TERMS = ('p_routing', 'p_excess', 'p_vias', 'p_coupling', 'p_placement')
def channel_totals(rows, ch):
    rs = [r for r in rows.values() if r['channel'] == ch]
    t = {k: round(sum(r[k] for r in rs), 1) for k in TERMS + ('length', 'excess', 'vias', 'coupled')}
    t['by_class'] = {}
    for r in rs:
        k = f"P{r['cls']}" if r['cls'] else 'unclassed'; c = t['by_class'].setdefault(k, dict(p_routing=0.0, excess=0.0, vias=0, coupled=0.0))
        c['p_routing'] = round(c['p_routing'] + r['p_routing'], 1); c['excess'] = round(c['excess'] + r['excess'], 1); c['vias'] += r['vias']; c['coupled'] = round(c['coupled'] + r['coupled'], 1)
    return t

def show_one(S):
    for ch in cc.GROUPS:
        t = channel_totals(S['rows'], ch)
        print(f"{ch:<7} routing {t['p_routing']:7.0f} = excess {t['p_excess']:6.0f} ({t['excess']:.0f} mm) + vias {t['p_vias']:5.0f} ({t['vias']}) + coupling {t['p_coupling']:5.0f} ({t['coupled']:.1f} mm)"
              f"   | placement {t['p_placement']:.0f} | {t['length']:.0f} mm in all")
        print('        by class: ' + ', '.join(f"{k} {v['p_routing']:.0f}" for k, v in sorted(t['by_class'].items()) if v['p_routing']))
        for n, r in sorted(((n, r) for n, r in S['rows'].items() if r['channel'] == ch), key=lambda x: -x[1]['p_routing'])[:6]:
            if r['p_routing'] < 1: break
            print(f"    {n:<22} P{r['cls'] or '?'} w{r['weight']:<5g} routing {r['p_routing']:6.0f}: {r['excess']:.1f} mm over its {r['tree']:.1f} mm tree, {r['vias']} vias, "
                  f"{r['coupled']:.1f} mm coupled" + (' (' + ', '.join(f"{g}: {v['close']:.1f} mm within 2h, {v['near']:.1f} within 16h" for g, v in r['coupled_by_aggressor'].items()) + ')' if r['coupled_by_aggressor'] else ''))

def show_diff(A, Bs):
    out = {}
    for ch in cc.GROUPS:
        ta, tb = channel_totals(A['rows'], ch), channel_totals(Bs['rows'], ch); d = {k: round(tb[k] - ta[k], 1) for k in TERMS}
        driver = max(('p_excess', 'p_vias', 'p_coupling'), key=lambda k: abs(d[k])); out[ch] = dict(before=ta, after=tb, delta=d, driver=driver)
        print(f"{ch:<7} routing {ta['p_routing']:7.0f} -> {tb['p_routing']:7.0f} ({d['p_routing']:+.0f}): excess {d['p_excess']:+.0f}, vias {d['p_vias']:+.0f}, coupling {d['p_coupling']:+.0f}"
              f"   [{ta['length']:.0f} -> {tb['length']:.0f} mm, {ta['vias']} -> {tb['vias']} vias]" + (f"; mostly {driver[2:]}" if abs(d['p_routing']) >= 1 else ''))
        rows = sorted(((n, Bs['rows'][n]['p_routing'] - A['rows'][n]['p_routing']) for n in A['rows'] if n in Bs['rows'] and A['rows'][n]['channel'] == ch), key=lambda x: -abs(x[1]))
        for n, dn in [x for x in rows if abs(x[1]) >= 1][:8]:
            a, b = A['rows'][n], Bs['rows'][n]
            ag = sorted(set(a['coupled_by_aggressor']) | set(b['coupled_by_aggressor']))
            cpl = ', '.join(f"{g} {a['coupled_by_aggressor'].get(g, {}).get('effective', 0):.1f}->{b['coupled_by_aggressor'].get(g, {}).get('effective', 0):.1f}" for g in ag)
            print(f"    {n:<22} P{a['cls'] or '?'} w{a['weight']:<5g} {dn:+6.0f}: excess {a['excess']:.1f}->{b['excess']:.1f} mm, vias {a['vias']}->{b['vias']}"
                  + (f", coupled to {cpl} effective mm" if cpl else ''))
    return out

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('board'); ap.add_argument('other', nargs='?'); ap.add_argument('--classes'); ap.add_argument('--json')
    a = ap.parse_args(); A = score(a.board, a.classes)
    print('weights by class:', ', '.join(f'P{k} {v:g}' for k, v in WEIGHT.items()), '| by node:', ', '.join(f'{p} {w:g}' for p, w in NODE_WEIGHT),
          f'| via = {VIA_MM:g} mm, coupled mm x {COUPLE_MM:g}, full within 2h then 5/(1+(s/h)^2), h {DIELECTRIC}')
    if A['unclassed']: print('no class (weighted', UNCLASSED, 'if a signal):', ', '.join(A['unclassed']))
    print('not charged, joined on purpose:', '; '.join(f'{n}-{m} ({why})' for n, m, why in A['exempt']))
    if a.other: Bs = score(a.other, a.classes); out = dict(constants=CONSTANTS, before=A, after=Bs, channels=show_diff(A, Bs))
    else: show_one(A); out = dict(constants=CONSTANTS, board=A, channels={ch: channel_totals(A['rows'], ch) for ch in cc.GROUPS})
    if a.json: json.dump(out, open(a.json, 'w'), indent=1)
