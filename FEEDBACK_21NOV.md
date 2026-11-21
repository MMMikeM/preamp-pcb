# Landscape feedback, 21 Nov 2026

From the author's side, after a day of placement changes on the landscape board. Three small code changes are in this
branch; the rest is a request and the evidence for it.

## The board
`fixtures/landscape-74f5949/` holds `humbucker-preamp.kicad_pcb` and `.kicad_pro` at kicad-repo commit `74f5949`, the
current placement. Changes since `25a2cbd` that matter to the pipeline:

1. **The neck strip is now the bridge strip copied.** Strip parts (x >= 54.3 on the bridge) are shifted by -52.45; middle
   parts are mirrored about x = 37. Exceptions, left alone: C103/C203, J103/J203, C301/C302, R136/R236.
2. **Neck U3 uses op-amp units B and C swapped.** `channel.kicad_sch` stores the unit per sheet instance: the neck
   instance has B and C exchanged, the bridge instance does not. So U3 and U4 carry different nets on pins 5 to 10:

   | Pin | 5 | 6 | 7 | 8 | 9 | 10 |
   |---|---|---|---|---|---|---|
   | U3 (neck) | REF | Q103-C | BO | OBN | U3B- | GND |
   | U4 (bridge) | GND | U4B- | OBN | BO | Q203-C | REF |

   **Anything that maps one channel onto the other by pad number is now wrong on U3/U4** (2h's copy, the partial copy
   when it is built, twin checks). Map by net name instead, or treat U3/U4 pins 5 to 10 as not twinned.
3. **Test points are off.** All test point symbols are "exclude from board" and the footprints are gone. 2f has nothing to
   join on this board. Their old positions are in the kicad repo as `tp_positions.json`; they come back later.
4. **U3/U4 and their passives moved down 3.7 mm**, towards the JFETs.

## Code changes in this branch
- `stage_route.py`, the pass-2 L3 join: `add_only=True`. Without it, `guard` failed on `/OUT_NK`: the router removed the
  pad vias the same pass had just placed. This is the local change mentioned in earlier feedback. You kept `add_only`
  to 2f because locked nets are skipped by the rescue and rip passes; this applies it only to the L3 join in pass 2, and
  no completion was lost in any of the runs below. Revert it if you see a loss.
- `supply5.py`: `R6_SKIP_SUPPLY=1` skips the supply shapes. Every comparison below was run with it, because the shape
  constants stop matching after placement changes (see "Supply shapes" below).
- `compare_channels.py`: per-channel totals (top, L3, vias) for two routed boards, then the nets that changed most. This
  is how every comparison below was made. Channel is decided by the mean x of a net's pads.

`pytest tests`: 42 passed.

## Request: P2 and P4 nets get the top layer before supply links
### The evidence
`Net-(Q203-C)` is the bridge second-stage collector, a P4 net that feeds an op-amp input. It flips between a clean
top-layer route and an L3 route with 3 vias, including in runs where nothing near it moved:

| Run | What changed | Q203-C |
|---|---|---|
| A | B/C swap on the neck, test points off | 19 mm, 0 vias |
| B | Author moved R227, C211, C112, C302, C309 | 16 mm, 3 vias |
| C | B with C211 turned vertical | 16 mm, 3 vias |
| D | C with R227 moved back | 19 mm, 0 vias |
| E | D with R127 and C112 moved, **neck only** | 16 mm, 3 vias |
| F | E with U3/U4 blocks down 3.7 mm (the fixture) | 15 mm, 0 vias |

D to E changed two neck parts and nothing within 30 mm of Q203-C. Earlier, on the portrait-to-landscape runs, the same
net went from 0 to 3 vias when a new 2b V+ link (R224.1 to C312) crossed its corridor. In E the mechanism is not
confirmed; it may be ordering inside 2e/2i rather than a 2b link. Either way a P4 net should not depend on the order the
router happens to pick.

### The rule
1. Before 2b, route the P2 and P4 nets of each channel on the top layer only (no vias), as 2a does for the
   high-impedance nets. Keep what joins within the length limit; leave the rest for 2e as now.
2. In 2b, refuse a supply link (V+, V-, REF, PB) that comes within 0.4 mm of P2 or P4 copper placed in step 1. Those
   supply pads drop to L5 with their own vias. Supply never needs the top-layer link.
3. Order inside step 1: drains first (DA, DB), then P4 (collector, base and emitter nets, the inverter summing node), then
   the rest of P2. The sources (SA, SB) sit on a low-impedance resistor ladder and can take a via.

Net lists come from `kicad/netclasses-priority.json` (P2_FrontEnd, P4_Stage2) in the kicad repo, or the `.kicad_pro`
netclass patterns in the fixture. Reading the classes is better than another name list in `board.py`.

### Checks
- Test: a supply link that would cross a P2/P4 track placed in step 1 is not made.
- Test: a P2/P4 net that joins on top in step 1 is not re-routed later.
- On the fixture: `Net-(Q203-C)`, `Net-(Q103-C)`, `/Bridge/DB` and `/Bridge/DA` on top with no vias.
- Then, on the fixture with R127/C112 nudged by 0.1 mm: Q203-C should not change.

## Supply shapes
`supply5.py`'s boxes and lines are constants for one placement. They were patched locally three times for earlier
placements, and have not been checked against the fixture: the U3/U4 move and the neck copy have changed where the
strips' supply columns are. Suggested: derive the fingers and bars from the
supply pad and via positions after 2c (each strip's V+ and V- columns, the middle column), with the constants only as
keep-outs. Not urgent: the author treats supply as easy and wants it to stop blocking placement comparisons.

## Current numbers on the fixture
Supply skipped, test points off, setup to 2i (2i "fails" only on V+ and V-, as expected with supply skipped).

| | Signal track | Vias |
|---|---|---|
| Neck | 427 mm | 16 |
| Bridge | 436 mm | 19 |

For reference, the same pipeline on the portrait board gave 1122 mm and 63 signal vias for both channels together.
