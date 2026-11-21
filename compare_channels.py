"""Per-channel comparison of two routed boards: signal track on top and L3, and vias, for each channel, then the nets that
changed most. Supply, GND, REF, PB and VR are left out.

A net's channel comes from its name (/Neck/..., /Bridge/...) or else from the parts on it: X1nn, U1 and U3 are the neck,
X2nn, U2 and U4 the bridge. Nets touching only shared parts (X3nn, U5, U6, J1-J3), or both channels, are 'Shared'.
Nothing depends on where the parts sit on the board.
Usage: python3 compare_channels.py A.kicad_pcb B.kicad_pcb"""
import math, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import board as bd

NECK_ICS, BRIDGE_ICS = {'U1', 'U3'}, {'U2', 'U4'}
GROUPS = ('Neck', 'Bridge', 'Shared')

def ref_channel(ref):
    if ref in NECK_ICS: return 'Neck'
    if ref in BRIDGE_ICS: return 'Bridge'
    m = re.fullmatch(r'[A-Z]+([12])\d\d', ref)
    return ('Neck' if m.group(1) == '1' else 'Bridge') if m and not ref.startswith('TP') else None

def net_channel(net, refs):
    if net.startswith('/Neck/'): return 'Neck'
    if net.startswith('/Bridge/'): return 'Bridge'
    found = {c for c in map(ref_channel, refs) if c}
    return found.pop() if len(found) == 1 else 'Shared'

def is_signal(n): return bool(n) and n != 'GND' and not bd.is_supply(n) and n not in ('REF', 'PB', '/VR')

def stats(path):
    """net -> (channel, top mm, L3 mm, vias)"""
    B = bd.Board(path); refs = {}
    for p in B.pads:
        if is_signal(p['net']): refs.setdefault(p['net'], set()).add(p['ref'])
    out = {n: [net_channel(n, r), 0.0, 0.0, 0] for n, r in refs.items()}
    for s in B.segs:
        if s['net'] in out: out[s['net']][1 if s['layer'] == 'F.Cu' else 2] += math.dist((s['x1'], s['y1']), (s['x2'], s['y2']))
    for v in B.vias:
        if v['net'] in out: out[v['net']][3] += 1
    return {n: tuple(v) for n, v in out.items()}

def totals(S, c):
    rows = [v for v in S.values() if v[0] == c]
    return sum(r[1] for r in rows), sum(r[2] for r in rows), sum(r[3] for r in rows)

def changes(a, b, c, n=12):
    zero = (c, 0.0, 0.0, 0)
    nets = {k for k, v in a.items() if v[0] == c} | {k for k, v in b.items() if v[0] == c}
    rows = [(b.get(k, zero)[1] + b.get(k, zero)[2] - a.get(k, zero)[1] - a.get(k, zero)[2], b.get(k, zero)[3] - a.get(k, zero)[3], k) for k in nets]
    return sorted(rows, key=lambda t: -abs(t[0]) - 3 * abs(t[1]))[:n]

if __name__ == '__main__':
    a, b = stats(sys.argv[1]), stats(sys.argv[2]); zero = lambda c: (c, 0.0, 0.0, 0)
    for c in GROUPS:
        (ta, la, va), (tb, lb, vb) = totals(a, c), totals(b, c)
        print('%-6s A: top %.0f L3 %.0f total %.0f vias %d   ->  B: top %.0f L3 %.0f total %.0f vias %d' % (c, ta, la, ta + la, va, tb, lb, tb + lb, vb))
        for d, dv, k in changes(a, b, c):
            x, y = a.get(k, zero(c)), b.get(k, zero(c))
            print('      %-22s %+6.1f mm %+d vias   (%.0f/%d -> %.0f/%d)' % (k, d, dv, x[1] + x[2], x[3], y[1] + y[2], y[3]))
