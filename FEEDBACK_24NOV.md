# Feedback, 24 Nov 2026: split plane leaves V- in two pieces, and nothing fails

New fixture: `fixtures/landscape-e68324c` (the author's latest placement: transistor blocks lowered, R118/C109/C108/R116,
R122/R222, C112/C212, C110/C210, C301 moved; `.kicad_pro` with the `Net-(U3C--)` pattern). Routed at `2cc1234` from setup:
`check --final` passes (must-fix none), but **KiCad DRC reports V- unconnected**.

## What happened
In 2d, `route_planes.py` on In4.Cu ends "Best result: 4 failed edge(s)" with V- at 7/8 MST edges, and lists unconnected pads
C302, Q303, C310, U3 and U1 on V- (and R110 on V+). The V+ zone now runs from R110 (106.8, 107.6) up past (117, 92),
closing off the left V- region (U1/U3/C310/C302/Q303) from the main V- region (the right side and bottom). In
`landscape-7bccb83` the V- band ran under it at y 108. `l5_split.png` shows both boards' L5 zones.

The step still passes: its own line is `[2d] ... must-fix: none`, and the second opinion only says "nets only it calls
unconnected: ... (and ['V+', 'V-'], by its estimate of the pour only)". Nothing later joins the two V- pieces, and `check --final`
passes with the same note. KiCad: "unconnected_items: Track [V-] on F.Cu (122.125, 85.633) to Via [V-] (134.17, 103.229)".

## Asks
1. A supply net split into pieces on its plane layer must be a must-fix (from 2d on), not a note. KiCad's own fill decides; if
   the estimate cannot tell, run the zone fill and test connectivity.
2. When the split fails, retry with the other order (V- before V+) or let the failed net cross on L3, before giving up.
3. Same fixture, for scale: against `landscape-7bccb83` routed at `2cc1234` (both from setup), the score is neck 558 -> 559,
   bridge 609 -> 610, shared 201 -> 237 (PB excess 6.2 -> 13.8 mm, REF 8.9 -> 12.5). The PB/REF growth may come from the same
   L5 layout; worth checking once the split is fixed.
