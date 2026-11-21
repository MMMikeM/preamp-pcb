"""Hand-swap access rule (author's rule, 21 Nov 2026).

A part meant to be swapped by hand passes if either
  edge:  its pads are within EDGE_MM of a board edge, with no other part's pad in the strip between it and that edge; or
  space: no other part's pad is within SPACE_MM of its pads.

Hand-swap parts are found by their footprint Description containing "Swap by hand", so renumbering does not break the list.
Usage: python3 hand_access.py board.kicad_pcb
"""
import re, sys
from shapely.geometry import box
from shapely.ops import unary_union
import board as bd

EDGE_MM, SPACE_MM = 3.0, 2.0

def hand_refs(path):
    """References whose footprint Description says the part is swapped by hand."""
    s = open(path).read(); out = set()
    for m in re.finditer(r'\(property "Reference" "([^"]+)"[\s\S]*?\(property "Description" "([^"]*)"', s):
        if 'swap by hand' in m.group(2).lower(): out.add(m.group(1))
    return out

def check(B, refs):
    x0, y0, x1, y1 = B.outline(); res = {}
    for r in sorted(refs):
        mine = unary_union([B.pad_geom(p) for p in B.fps[r]['pads']]); bx = mine.bounds
        others = [B.pad_geom(p) for s, g in B.fps.items() if s != r for p in g['pads']]
        gap = min(g.distance(mine) for g in others)
        strips = {'left': (bx[0] - x0, box(x0, bx[1], bx[0], bx[3])), 'right': (x1 - bx[2], box(bx[2], bx[1], x1, bx[3])),
                  'top': (bx[1] - y0, box(bx[0], y0, bx[2], bx[1])), 'bottom': (y1 - bx[3], box(bx[0], bx[3], bx[2], y1))}
        edge = [k for k, (d, st) in strips.items() if d <= EDGE_MM and not any(g.intersects(st) for g in others)]
        res[r] = dict(ok=bool(edge) or gap >= SPACE_MM, edge=edge, nearest_mm=round(gap, 2))
    return res

if __name__ == '__main__':
    p = sys.argv[1]; B = bd.Board(p); res = check(B, hand_refs(p)); bad = [r for r, v in res.items() if not v['ok']]
    for r, v in res.items(): print(f"{r:6s} {'PASS' if v['ok'] else 'FAIL'}  edge {v['edge'] or '-'}  nearest pad {v['nearest_mm']} mm")
    sys.exit(1 if bad else 0)
