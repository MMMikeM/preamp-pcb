"""Hand-swap access rule (author's rule, 21 Nov 2026).

A part meant to be swapped by hand passes if either
  edge:  its pads are within EDGE_MM of a board edge, with no other part's pad in the strip between it and that edge; or
  space: no other part's pad is within SPACE_MM of its pads.

Hand-swap parts are the footprints whose Description contains "Swap by hand" (board.Board reads it), so renumbering does not break the list.
Usage: python3 hand_access.py board.kicad_pcb
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shapely.geometry import box
from shapely.ops import unary_union
import board as bd

EDGE_MM, SPACE_MM = 3.0, 2.0

def hand_refs(B): return {r for r, f in B.fps.items() if f['hand']}

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
    B = bd.Board(sys.argv[1]); res = check(B, hand_refs(B)); bad = [r for r, v in res.items() if not v['ok']]
    for r, v in res.items(): print(f"{r:6s} {'PASS' if v['ok'] else 'FAIL'}  edge {v['edge'] or '-'}  nearest pad {v['nearest_mm']} mm")
    sys.exit(1 if bad else 0)
