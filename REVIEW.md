# route6: review brief

Scripts for re-routing the humbucker preamp board (41 x 74 mm) on 6 layers. Nothing here has been run against the real
board file. Please review the code against the rules and guarantees below, run the tests, and report anything that
breaks a guarantee, any rule the code does not actually enforce, and anything fragile.

## Why this exists
The 4-layer routing was done net by net with fixed layers per net class. Results we do not want again:
- two supply pads 2.9 mm apart joined through two vias and an inner layer (Q303.2 / R306.2 on BAT-);
- trunks that changed layer several times; detours fixed only by clean-up passes after the fact;
- neck and bridge channels drifting apart; checks run by hand and late.

## Layer plan (JLC default 6-layer, 1.6 mm)
| Layer | KiCad name | Use |
|---|---|---|
| L1 | F.Cu | parts, local links, every high-impedance net |
| L2 | In1.Cu | solid ground, never cut |
| L3 | In2.Cu | hops and crossings only |
| L4 | In3.Cu | solid ground |
| L5 | In4.Cu | supply (V+, V-, battery) and bias (REF, PB, VR) trunks, ground fill elsewhere |
| L6 | B.Cu | ground pour, test-point pads, wire pads; no tracks if avoidable |

## Rules the scripts must enforce
1. High-impedance nets (`board.HZ_SUFFIX`) are on F.Cu only and have no vias. Clearance to them is 0.4 mm; everything else 0.2 mm.
2. Other nets keep 1.0 mm from high-impedance copper where they can (a cost, not a hard limit). Rule 3 wins where they conflict.
3. **A via must be justified.** Two pieces of one net that could be joined on the top layer with a path no longer than
   `max(1.5 x gap, gap + 3 mm)` must be joined on the top layer. Step 2b uses the tighter `max(1.5 x gap, gap + 1 mm)`, gap <= 4 mm.
4. Ground: one via in every surface-mount ground pad. No ground tracks on top.
5. Supply and bias: one via per top-layer piece; decoupling caps always get their own.
6. No via in the pads of R109, R117, R209, R217 (hand-swapped parts). No via in through-hole pads.
7. Via in pad is allowed (the fab fills and caps vias; `setup6` sets that as the board's via default so the file says so).
   0.6/0.3 mm where the pad is >= 0.9 mm both ways, else 0.5/0.3 mm.
   Minimum annular ring 0.1 mm, hole to hole 0.25 mm, copper to board edge 0.5 mm.
8. Above the op-amps the two channels are mirror images; from U3/U4 down the bridge is the neck shifted 19.45 mm.
   Routing is done on one channel and copied (step 2h) wherever a net's pads map consistently.
9. Scripts only add or remove tracks and vias. They never move a part.

## Steps (`stage_route.py`)
setup -> 2a (high-impedance, router) -> 2b (neighbour links) -> 2c (ground vias)
-> 2d (supply top links at the rule 3 limit, supply drops, L5 trunks with the router)
-> 2e (other signals: top first, L3 only if needed, router) -> 2h (copy to other channel)
-> 2i (what the copy did not cover: links, then the router as in 2a and 2e) -> 2f (test points) -> check.
2a, 2b and 2e leave alone the nets 2h will make by copying and the other channel's own nets; routed first, they are in the copy's way.
2g (tidy) is manual for now. A human reviews after every step.
2d links supply pieces at the rule 3 limit before dropping vias because 2b's tighter limit would otherwise leave pieces that get a
via and are then flagged by `via_justify`. With `ROUTER_DIR` set, every step also runs the router's own DRC and connectivity check.

## What each file must guarantee
| File | Guarantee |
|---|---|
| `board.py` | Reads pads (absolute position, size, rotation, round-rect corners, layers, drill), tracks, vias, zones. Refuses a board with arc tracks, which it cannot read. `add`/`remove` change only track and via blocks; the rest of the file stays byte-identical. `save` keeps the source file's line endings. |
| `toplink.py` | `components`: pieces of a net joined on one layer. `top_path`: a path that keeps `clearance + width/2` from all other-net copper on that layer and 0.5 mm + width/2 from the board edge (rule 7), uses 45/90 degree moves, never turns more than 90 degrees, starts on an anchor that is itself legal. Inside its own copper it is free only where the whole track width stays inside. It minimises cost (length, a turn penalty and the rule 2 keep-away penalty); when that leaves no path within `max_len` it searches again without the keep-away, so rule 3 beats rule 2 (`LIMIT_BEATS_KEEP_AWAY`; `HZ_COST = 0` switches the keep-away off). Returns None if none exists within `max_len`. |
| `neighbour_links.py` | Adds only F.Cu tracks; never joins two pieces twice; skips ground and (by default) high-impedance nets; result passes `checks.clearances`. `--rule3` uses `via_justify`'s limits instead of 2b's. |
| `via_justify.py` | Flags every pair of top-layer pieces of a net that rule 3 says should be joined. Ground and lone decoupling-cap pads are excluded by default. |
| `drops.py` | Rules 4-7, including the board edge. Reports pads where no legal via fits, once per supply piece, and exits 2 (1 is a crash); never forces one. Test points: surface-mount only, never on a high-impedance net, skipped when already joined to their net. A pad can still be blocked by a test point on the other side (TP205 under U4.10 on this placement, avoided because 2d joins U4.10 to U4.12 first); the tool reports it. |
| `mirror_route.py` | Copies a net only if every pad has a twin at the mirrored or shifted position on one single twin net with the same pad count. A net with no routing is not copied, nor is one whose copy would come within clearance of copper that is staying, a hole or the board edge; its twin is left alone and step 2i routes it. `waits_for_copy` names the nets the earlier steps must leave for this one. Exit 1 if a copied net's connectivity differs from its source or a clearance breaks. |
| `setup6.py` | Adds In3/In4, the 6-layer stackup and ground zones on In1, In3, In4, B; sets the board's via defaults to filled and capped; removes the In2 zone and all stale fills; rips all routing except top-only routing of the named nets that is still connected and legal. |
| `checks.py` | `FAIL` lists must be empty after every step; `FINAL` lists at the end (`--final`). `top_incomplete`, `tp_joined` and `loose_testpoint_nets` judge a net without letting a bottom-side test point count against a top-only route. `holes` counts a via inside a through-hole pad as an error. |
| `krt_checks.py` | Runs KiCadRoutingTools' `run_drc` and connectivity check on a saved board with this project's clearances. Needs `ROUTER_DIR`, scipy and Pillow, not the compiled router. |
| `stage_route.py` | Runs one step, saves `work/<step>.kicad_pcb` and `work/<step>_checks.json`. Exits 1 on any must-fix item, on any script or router call that exits non-zero, and with `--final` on unconnected nets or unjustified vias. A step that exits 1 puts `work/board.kicad_pcb` back to what it was before the step. In 2f a test point with no room for a via is not a failure: the router reaches it by a track. The router's DRC items are must-fix; nets only it calls unconnected are listed as `krt_unconnected_extra`. |

## Tests (`python -m pytest -q tests`, about 2 minutes, needs `pip install -r requirements.txt`)
- `tests/board_4layer_rev1.kicad_pcb`: the finished 4-layer board (KiCad DRC clean). Our own checks must also find it clean.
  `via_justify` must flag BAT- between Q302.2 and R304.2 (2.8 mm apart, joined through two vias).
- `tests/board_placed_19nov.kicad_pcb`: current placement. After `setup6` and rip-up, `neighbour_links` must produce a direct
  0.4 mm BAT- track between Q303.2 and R306.2 under 3 mm long (the case from the screenshots), with no clearance errors.
- Ground drops must cover every eligible ground pad; copied nets must match their source's connectivity.
- After the rule 3 supply links and the drops, `via_justify` must flag no supply pair.
- Constructed cases: a link from a track end routed at exact clearance, a link beside the board edge, a twin net whose source has
  no routing, a test point already joined to its net, a pad with no angle in a rotated footprint, a join that only fits inside the
  keep-away, a board with an arc track, a via in a through-hole pad, a step that fails part-way.
- With `ROUTER_DIR` set, the router's DRC must find links plus drops clean. Each test gets its own copy of the board.

## What has been checked so far
- All 24 tests pass (Python 3.9, shapely 2, numpy 2), one of them only with `ROUTER_DIR` set.
- Every step was run end to end on the 19 Nov placement with KiCadRoutingTools v0.24.1: each exits 0 with no clearance, hole, edge,
  high-impedance or hand-swap-pad item from our checks and none from the router's DRC. 2h copied 20 nets with no clearance problem
  (6 more were skipped because their copy would collide, 13 have no twin mapping). The result: 857 tracks, 108 vias.
- `check --final` on that result exits 1: 8 nets are not fully connected and 4 pairs are flagged by `via_justify` (see weak spots).
- On that output and on the finished 4-layer board, the router's clearance, hole and edge results match ours.
- Nothing from this version has been opened in KiCad. An earlier output of setup + 2b + 2c + supply drops was, with DRC clean.

## Known weak spots (please look hard at these)
1. **The router does not finish the board.** After all steps on the 19 Nov placement: `REF` is in 5 pieces (the bias trunk on L5 is
   incomplete), `/Bridge/DA` in 3, `/Neck/SVP` and `/Bridge/SVP` each have one pad the router could not reach top-only, and four test
   points are not joined (TP104, TP105, TP203, TP205). Four pairs are flagged as unjustified. These need a human in KiCad.
   The router exits 0 when nets stay open, so only the unconnected count shows it. It does connect to vias already in pads and
   keeps input tracks with their ids. With no `.kicad_pro` beside the board it falls back to its own limits, so `stage_route` passes
   clearance, hole gap and edge explicitly; it also writes `work/board.kicad_pcb.kicad_pro`, which later router steps read.
2. **`via_justify` only sees what is still possible.** On the old board it does not flag the exact pair from the screenshots
   (Q303.2 / R306.2): another net had been routed between them. Order of routing is the real protection, the check is a backstop.
   The router's compiled extension has `identify_blocking_obstacles`, which could name the net in the way; not used yet.
3. **2e works per net, not per connection.** A net goes to L3 whole if its top-only route is too long.
4. **L5 uses wide tracks for V+ and V-, not shaped pours.** Pours need a designed split and are not automated.
5. **Path ends.** `top_path` leaves its first anchor exactly, but may arrive up to one grid step (0.05 mm) off the far pad's
   centre, with a final short leg to the centre only when that leg stays inside the pad. That leg can be at any angle.
6. **Pad shapes** other than rectangle, round-rect, circle and oval are treated as their bounding rectangle. Zone fills are not
   modelled: a net with a zone is assumed joined wherever it has copper on that zone's layer (via, through-hole pad, pad in the pour).
   The router's check models the pour from the zone outline instead and, on the current placement, calls `GND` unconnected at
   J105 pin 1 and J205 pin 1 (through-hole pads 1.4 mm from the bottom edge). Not yet settled in KiCad.
7. **Symmetry check** reports seven deliberate differences (R107, R110-R112 region, pickup pads). It is informational.
8. Thresholds (1.5x, +1 mm, +3 mm, 4 mm, 8 mm) are first guesses. At the rule 3 limit, 2d adds supply links up to about 11 mm long
   on the top layer at 0.3 to 0.4 mm; whether that is wanted is a design call.
9. **A full run takes about ten minutes.** Roughly half is the router retrying nets that cannot be routed top-only (rip-up in the
   first pass of 2e and 2i); a quarter is `via_justify` run in full after every step, where most flags are nets not routed yet.
10. **Fill and cap is board-wide.** Every via, not only those in pads, is marked filled and capped. Not yet opened in KiCad.

## Not in this folder
The router (KiCadRoutingTools, MIT, https://github.com/drandyhaas/KiCadRoutingTools; point `ROUTER_DIR` at a checkout) and the older 4-layer helpers in `../mike` (detour check, clean-up passes,
island check). Those older helpers assume two routing layers and are not used by these steps.
