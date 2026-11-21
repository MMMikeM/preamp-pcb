"""Steps 2c / 2d / 2f: vias in pads.
 --ground   one via in every surface-mount ground pad (down to the ground planes)
 --supply   one via per top-layer piece of each supply or bias net; decoupling caps always get their own
 --testpoints  one via in every surface-mount test-point pad that is not yet joined to its net (never on a high-impedance net)
Never puts a via in a part swapped by hand (its footprint description says so) or in through-hole pads (they already reach every layer).
Via size: the largest of 0.7/0.3, 0.6/0.3, 0.5/0.3 that fits inside the pad and is legal there (0.5/0.3 = 0.1 mm ring, the project minimum).
A via is placed at the pad centre; if that breaks a clearance it is slid along the pad's long axis; if nothing fits it is reported, not forced.
Exit 2 when a pad could not take its via (the board is still saved), 0 otherwise.
usage: drops.py IN OUT [--ground] [--supply] [--testpoints] [--json OUT.json]"""
import sys, json, math, argparse
from shapely.geometry import Point
from shapely.strtree import STRtree
import board as bd, toplink as tl, checks
FAT = (0.7, 0.3); BIG = (0.6, 0.3); SMALL = (0.5, 0.3)
NO_ROOM = 2          # exit code: apart from a crash's 1, so a caller can carry on where another step can still reach the pad

def via_sizes(p):
    """Largest ring first; a via never overhangs its pad, so narrow pads (IC pins, SOT) only get 0.5/0.3."""
    m = min(p['w'], p['h']); return [s for s in (FAT, BIG, SMALL) if s[0] <= m + 1e-6] or [SMALL]

class Placer:
    def __init__(self, B):
        self.B = B; self.outline = B.outline(); self.refresh()
    def refresh(self):
        B = self.B; self.cu = []
        for l in B.copper_layers: self.cu += [(n, g) for n, g, k, o in B.copper(l)]
        self.tree = STRtree([g for _, g in self.cu])
        self.holes = [(v['x'], v['y'], v['drill']) for v in B.vias] + [(p['x'], p['y'], p['drill']) for p in B.pads if p['drill']]
    def legal(self, x, y, size, drill, net):
        if bd.edge_room(self.outline, x, y, size / 2) < bd.EDGE - 1e-6: return False
        g = Point(x, y).buffer(size / 2, 16)
        for j in self.tree.query(g.buffer(bd.CLEAR_HZ + 0.01)):
            n, h = self.cu[int(j)]
            if n != net and g.distance(h) < bd.clearance(net, n) - 1e-6: return False
        return all(math.dist((x, y), h[:2]) - drill / 2 - h[2] / 2 >= bd.HOLE_GAP - 1e-6 for h in self.holes)
    def spot(self, p):
        horiz = p['w'] >= p['h']; reach = max(abs(p['w'] - p['h']) / 2, 0)
        for size, drill in via_sizes(p):                      # the centre at a smaller size beats a slide at a bigger one only if the bigger fits nowhere
            for k in range(0, int(reach / 0.05) + 1):
                for s in ((0,) if k == 0 else (1, -1)):
                    x = p['x'] + (s * k * 0.05 if horiz else 0); y = p['y'] + (0 if horiz else s * k * 0.05)
                    if self.legal(x, y, size, drill, p['net']): return x, y, size, drill
        return None

def has_via(B, p):
    g = B.pad_geom(p); return any(v['net'] == p['net'] and g.contains(Point(v['x'], v['y'])) for v in B.vias)
def smd_top(p): return p['kind'] == 'smd' and p['layers'] == {'F.Cu'}

def run(B, ground=False, supply=False, testpoints=False, signals=(), log=print):
    P = Placer(B); added = []; failed = []
    def drop(p, why, report=True):
        if B.fps[p['ref']]['hand'] or has_via(B, p): return False
        s = P.spot(p)
        if not s:
            if report: failed.append(dict(pad=checks.label(p), net=p['net'], why=why))
            return False
        B.add([B.via_text(*s, p['net'])]); P.refresh(); added.append(dict(pad=checks.label(p), net=p['net'], at=[round(s[0], 3), round(s[1], 3)], size=s[2], why=why)); return True
    if ground:
        for p in list(B.pads):
            if p['net'] in bd.GROUND and smd_top(p) and not checks.is_tp(p): drop(p, 'ground')
    if supply:
        import via_justify
        for net in [n for n in B.nets if bd.is_supply(n)]:
            for c in tl.components(B, net):
                pads = [q for q in c['pads'] if smd_top(q) and not B.fps[q['ref']]['hand']]
                for q in pads:
                    if via_justify.is_decap(B, q): drop(q, 'decoupling cap')
                if any(q['drill'] for q in c['pads']): continue                       # a through-hole pad already reaches the layer
                if c['vias'] or any(has_via(B, q) for q in pads): continue
                order = sorted(pads, key=lambda q: (q['ref'][0] == 'U', -min(q['w'], q['h'])))   # passives before IC pins, bigger pads first
                if not any(drop(q, 'supply piece', report=False) for q in order) and pads:
                    failed.append(dict(pad='+'.join(checks.label(q) for q in pads), net=net, why='no legal via anywhere in this piece'))
    for net in signals:                                                              # a signal that must leave the top layer: one via IN a pad per top-layer piece
        comps = tl.components(B, net)
        for c in comps:
            pads = [q for q in c['pads'] if smd_top(q) and not B.fps[q['ref']]['hand'] and not checks.is_tp(q)]
            if any(q['drill'] for q in c['pads']) or c['vias'] or any(has_via(B, q) for q in pads) or not pads: continue
            rest = [(o['x'], o['y']) for d in comps if d is not c for o in d['pads'] if not checks.is_tp(o)]
            reach = lambda q: min((math.dist((q['x'], q['y']), o) for o in rest), default=0.0)
            # passives before IC and transistor pins, then the pad nearest the rest of the net (the L3 join starts there), then bigger pads
            order = sorted(pads, key=lambda q: (q['ref'][0] in 'UQ', reach(q), -min(q['w'], q['h'])))
            if not any(drop(q, 'signal leaves the top layer', report=False) for q in order):
                failed.append(dict(pad='+'.join(checks.label(q) for q in pads), net=net, why='no legal via in any pad of this piece'))
    if testpoints:
        for p in list(B.pads):
            if not checks.is_tp(p) or not p['net'] or p['net'] in bd.GROUND or bd.is_hz(p['net']) or p['drill']: continue
            if not checks.tp_joined(B, p): drop(p, 'test point')
    for a in added: log(f"via {a['pad']:<10} {a['net']:<20} {a['size']} ({a['why']})")
    for f in failed: log(f"NO ROOM {f['pad']} {f['net']} ({f['why']})")
    return added, failed

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('inp'); ap.add_argument('out')
    for k in ('ground', 'supply', 'testpoints'): ap.add_argument('--' + k, action='store_true')
    ap.add_argument('--json'); a = ap.parse_args(); B = bd.Board(a.inp)
    added, failed = run(B, a.ground, a.supply, a.testpoints, log=lambda *_: None)
    print(len(added), 'vias added;', len(failed), 'could not be placed'); [print('  NO ROOM', f) for f in failed]
    B.save(a.out)
    if a.json: json.dump(dict(added=added, failed=failed), open(a.json, 'w'), indent=1)
    sys.exit(NO_ROOM if failed else 0)
