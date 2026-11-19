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
2. Other nets keep 1.0 mm from high-impedance copper where they can (a cost, not a hard limit).
3. **A via must be justified.** Two pieces of one net that could be joined on the top layer with a path no longer than
   `max(1.5 x gap, gap + 3 mm)` must be joined on the top layer. Step 2b uses the tighter `max(1.5 x gap, gap + 1 mm)`, gap <= 4 mm.
4. Ground: one via in every surface-mount ground pad. No ground tracks on top.
5. Supply and bias: one via per top-layer piece; decoupling caps always get their own.
6. No via in the pads of R109, R117, R209, R217 (hand-swapped parts). No via in through-hole pads.
7. Via in pad is allowed (the fab fills and caps vias). 0.6/0.3 mm where the pad is >= 0.9 mm both ways, else 0.5/0.3 mm.
   Minimum annular ring 0.1 mm, hole to hole 0.25 mm, copper to board edge 0.5 mm.
8. Above the op-amps the two channels are mirror images; from U3/U4 down the bridge is the neck shifted 19.45 mm.
   Routing is done on one channel and copied (step 2h) wherever a net's pads map consistently.
9. Scripts only add or remove tracks and vias. They never move a part.

## Steps (`stage_route.py`)
setup -> 2a (high-impedance, router) -> 2b (neighbour links) -> 2c (ground vias) -> 2d (supply drops + L5 trunks, router)
-> 2e (other signals: top first, L3 only if needed, router) -> 2h (copy to other channel) -> 2f (test points) -> check.
2g (tidy) is manual for now. A human reviews after every step.

## What each file must guarantee
| File | Guarantee |
|---|---|
| `board.py` | Reads pads (absolute position, size, rotation, round-rect corners, layers, drill), tracks, vias, zones. `add`/`remove` change only track and via blocks; the rest of the file stays byte-identical. `save` keeps the source file's line endings. |
| `toplink.py` | `components`: pieces of a net joined on one layer. `top_path`: a path that keeps `clearance + width/2` from all other-net copper on that layer and 0.3 mm + width/2 from the board edge, uses 45/90 degree moves, never turns more than 90 degrees, starts on an anchor. Returns None if none exists within `max_len`. |
| `neighbour_links.py` | Adds only F.Cu tracks; never joins two pieces twice; skips ground and (by default) high-impedance nets; result passes `checks.clearances`. |
| `via_justify.py` | Flags every pair of top-layer pieces of a net that rule 3 says should be joined. Ground and lone decoupling-cap pads are excluded by default. |
| `drops.py` | Rules 4-7. Reports pads where no legal via fits; never forces one. |
| `mirror_route.py` | Copies a net only if every pad has a twin at the mirrored or shifted position on one single twin net with the same pad count. Exit 1 if a copied net's connectivity differs from its source or a clearance breaks. |
| `setup6.py` | Adds In3/In4, the 6-layer stackup and ground zones on In1, In3, In4, B; removes the In2 zone and all stale fills; rips all routing except top-only routing of the named nets that is still connected and legal. |
| `checks.py` | `FAIL` lists must be empty after every step; `FINAL` lists at the end. |
| `stage_route.py` | Runs one step, saves `work/<step>.kicad_pcb` and `work/<step>_checks.json`, exits 1 on any must-fix item. |

## Tests (`python -m pytest -q tests`, about 3 minutes, needs `pip install -r requirements.txt`)
- `tests/board_4layer_rev1.kicad_pcb`: the finished 4-layer board (KiCad DRC clean). Our own checks must also find it clean.
  `via_justify` must flag BAT- between Q302.2 and R304.2 (2.8 mm apart, joined through two vias).
- `tests/board_placed_19nov.kicad_pcb`: current placement. After `setup6` and rip-up, `neighbour_links` must produce a direct
  0.4 mm BAT- track between Q303.2 and R306.2 under 3 mm long (the case from the screenshots), with no clearance errors.
- Ground drops must cover every eligible ground pad; copied nets must match their source's connectivity.

## What has been checked so far
- All eight tests pass in the author's environment (Python 3, shapely 2, numpy).
- The output of setup + 2b + 2c + supply drops was opened in KiCad 10 and DRC run: no clearance, short or hole errors.
  Remaining items were the expected unconnected nets and dangling supply vias (trunks not routed yet).

## Known weak spots (please look hard at these)
1. **Steps 2a, 2d (trunks), 2e and 2f call the external router and have not been run.** The flags in `stage_route.router` are
   carried over from the 4-layer runs. Unknown: whether `--layers F.Cu` with a huge via cost leaves unroutable nets cleanly open,
   whether the router connects to vias already in pads, and whether `--keep-input-copper` is the right flag.
2. **`via_justify` only sees what is still possible.** On the old board it does not flag the exact pair from the screenshots
   (Q303.2 / R306.2): another net had been routed between them. Order of routing is the real protection, the check is a backstop.
3. **2e works per net, not per connection.** A net goes to L3 whole if its top-only route is too long.
4. **L5 uses wide tracks for V+ and V-, not shaped pours.** Pours need a designed split and are not automated.
5. **`drops.py` can be blocked by a bottom-side test point.** Real case in the test board: TP205 (BO) sits under U4 pin 10 (REF).
   The tool reports it; the fix is to move the test point or reach that pin on the top layer.
6. **Path ends.** `top_path` leaves its first anchor exactly, but may arrive up to one grid step (0.05 mm) off the far pad's
   centre, with a final short leg to the centre only when that leg stays inside the pad.
7. **Pad shapes** other than rectangle, round-rect, circle and oval are treated as their bounding rectangle. Zone fills are not
   modelled: a net with a zone is assumed joined wherever it has copper on that zone's layer (via, through-hole pad, pad in the pour).
8. **Symmetry check** reports seven deliberate differences (R107, R110-R112 region, pickup pads). It is informational.
9. `neighbour_links.run.failed` is module-level state; `board.outline` re-parses the file on every call (slow, not wrong).
10. `checks.holes` skips a via that lies inside a through-hole pad's hole area; that case should not occur and should be an error.
11. Thresholds (1.5x, +1 mm, +3 mm, 4 mm, 8 mm) are first guesses.

## Not in this folder
The router (KiCadRoutingTools, open source) and the older 4-layer helpers in `../mike` (detour check, clean-up passes,
island check). Those older helpers assume two routing layers and are not used by these steps.
