# Feedback, 22 Nov 2026: bridge SB loses to OB/CLD on L3

All runs: this branch at `091e208`, KiCadRoutingTools v0.24.1, `BIAS_L3_COST=1.0`, supply on, setup to 2f.

## Placement since the last fixture
The author made the bridge a mirror of the neck about x = 37 (kicad `a8664a2`, U2 rotated to 0°), swapped U4's units
A and D in the schematic (`1a62674`: U4 pins 1/2 trade with 14/13; 3 and 12 are both REF), and then tidied
(`b9c8a4f`). On that board the pipeline joins everything with supply on: neck 454 mm / 20 vias, bridge 453 / 20.
(Earlier, the neck layout of `11393a0` made 2e fail `zone_integrity`: 2e's vias cut the V+ L5 stub to R110 at
(5.5, 25.3). It has not come back since, but a pad via that splits a supply zone should be refused in 2e rather than
caught afterwards.)

## The case: `fixtures/landscape-mirrorB`
R108 and C105 moved up (neck), with R208 and C205 at their mirror positions:

| | Neck | Bridge |
|---|---|---|
| `b9c8a4f` | 454 mm / 20 vias | 453 / 20 |
| mirrorB | 418 / 16 | 456 / 23 |

On the neck, OB −16 mm, CLD −19 mm / −2 vias, SB −10 mm. On the bridge the same moves give OB −24 and CLD −18, but:
- `/Bridge/SB` 25 → 46 mm: via at R208.2 (64.9, 19.7), then 34 mm on L3 out to x 43.8 and back to R207.1 (50.0, 36.1).
  The straight line is about 20 mm.
- `/Bridge/DB` +11 mm, `/Bridge/OA` +9 mm / +1 via, `Net-(C205-Pad1)` +5 mm / **+2 vias** (the 330k node to R204).

A placement search puts R208's best position (shortest OB + SB) back on the mirrored spot, so this is order, not
placement. SB is P2 (front end), OB and CLD are P4/P5, yet on L3 SB is laid after them and has to go round.

**Request:** on L3, route front-end (P2) pieces before P4/P5 pieces, the way 2p already does on top. Or, if a P2 net
finishes at more than 1.5× its straight-line length, rip the lower-priority L3 copper in its bounding box, route it first
and keep the result if the total is shorter. Test: this fixture, `/Bridge/SB` within 30 mm and `Net-(C205-Pad1)` with no vias.
The author has applied only the neck half for now and will mirror the bridge once this routes.

## Addendum (evening): two things that stop a run on a good board
1. **2h fails instead of skipping.** The author's channels are now laid out by hand and are no longer an exact mirror or
   shift of each other (kicad `cf1471a`). `mirror_route.py` then exits 1 with "no net of this channel has a twin,
   mirrored or shifted", and 2h fails. Running 2i and 2f after it gives a complete board with nothing must-fix. When there
   is nothing to copy, 2h should log that and pass.
2. **The off-top length limit stops a run over 0.2 mm on a P5 net.** On the author's board before `cf1471a`,
   `/Neck/OB` (a P5 op-amp output) came out at 38 mm against a 37.8 mm limit (`L3_RATIO` 1.8 × its 21 mm tree), and 2e
   failed. With 1.9 everything else was identical and the board completed. Suggest a larger ratio for P5 (and P4), which
   are low-impedance, or a warning instead of a failure for those classes. Keep 1.8 for P2 and P3.

## Answers (late evening)
**1. Bias retry: yes, build it,** with these conditions:
- Keep the result only if the front-end net gets shorter **and** has no more vias than before, the re-routed bias net
  stays within its own length limit, and `zone_integrity` stays clean (a bias track may still never cut a supply zone on
  L5). Compare on the weighted total, not raw mm: a P2 millimetre is worth more than a P6 one.
- It must not change anything on the other fixtures when no front-end net is long (same result, same vias).
- Test it on **`fixtures/landscape-83962f0`** as well as mirrorB. That's the author's current board (placement since
  reworked by hand, neck tuned by a placement search, GND links in). mirrorB is now a historical case. On 83962f0 the
  full run (with 2h skipped and `L3_RATIO` 1.9) gives neck 416 mm / 17 vias, bridge ~393-403 / 18-20; please report
  both channels before and after.

**2. Commit and push: yes.** "Drop dangling vias, link unpoured GND, 2h skip" is fine as one commit. Please say in the
body what each check now does on 83962f0 (the GND link should be a no-op there: the author's board has the links).
The P5 off-top limit (addendum point 2) is still open; a separate commit is fine.
