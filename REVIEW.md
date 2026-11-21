# route6: reviewer feedback (22 Nov 2026)

Reply to `RULES_21NOV.md` and `SUPPLY_RULE.md` (`ecb0475`). Earlier rounds are in git (`6497575` and before).

## Basis
- Router: KiCadRoutingTools v0.24.1 (`31049fd`). `BIAS_L3_COST=1.0` throughout.
- Boards: `fixtures/landscape-rev06` and `fixtures/landscape-eacfa31`, setup to 2i.
- 50 tests pass with `ROUTER_DIR` set.

## Rev 0.6, hand-swap rule, tie-break: done (`0ef07a5`)
- **Hand-swap parts come from the footprint description.** `board.Board` reads "Swap by hand" into `fps[ref]['hand']`;
  `NO_VIA_REFS` is gone. Every fixture carries the marking, so the old ones keep R109/R117/R209/R217 and rev06 gets
  R106/R114/R206/R214. Nothing else in code or tests named a renumbered part or a `Net-(R...)` net.
- **Access check in `setup`, as a warning.** On rev06 it names R106 and R206 (0.76 mm). `hand_access.hand_refs` now takes a
  `Board`, not a path, and the script finds its modules from its own folder.
- **Tie-break.** A signal's pad via goes on the passive pad nearest the rest of the net, then the bigger pad. On eacfa31
  `/Bridge/SA` is 5.2 mm shorter, as you predicted.

## Supply: the router's split plane, not hand-built shapes (this commit)
Before building either written rule I tried the router's own multi-net plane (`route_planes.py`, the "spine split") with
GND as L5's background and V+ and V- as the two nets on it. It lays one V+ zone and one V- zone, each grown round its own
pads and vias and joined by corridors, and on this placement the two **never cross**: V+ runs from its source along the top,
V- from its source round the bottom of the middle. No L3 crossing, no stubs, no coordinates. The reviewer and the user
agreed to take it and judge it by both rules' checks rather than their shapes.

What 2d does now: `drops.py --supply` as before, then the split plane on a copy of the board, keeping only its V+ and V-
zones (its own GND pieces would replace setup's pour; `guard` confirms it added no copper), then the battery and bias
calls at the standard clearances. `supply5.py` is deleted, and with it the scaffold tracks, `trim_centres`, `LINES`/`BOX`,
the widened 2d clearance and points A and B. `R6_SKIP_SUPPLY=1` still leaves the zones out.

### Checks from both rules
| Check | rev06 | eacfa31 |
|---|---|---|
| Every step to 2i passes | yes | yes |
| `zone_integrity`; one piece per rail; open nets | clean; yes; none | clean; yes; none |
| Neck signal, supply skipped -> on | 422 -> 428 mm, 14 -> 13 vias | 427 -> 432 mm, 14 -> 13 vias |
| Bridge signal, supply skipped -> on | 408 -> 410 mm, 15 -> 16 vias | 409 -> 409 mm, 16 -> 17 vias |
| P1, P2 or P4 net gains a via or a layer | none | none |
| Bias on L3 / L5 | 143 / 64 mm -> 167 / 34 mm | same |

- Within §4's 10 mm and 2 vias everywhere. Against `SUPPLY_RULE.md`'s 5 mm, rev06's neck is 1 mm over (+6 mm, one via fewer):
  `/Neck/CLD` +3 mm and `/Neck/OB` +2.5 mm, round bias that moved to L3.
- **Robustness:** rev06 with the neck op-amp block (U3, C309, C310 and the resistor and cap columns beside it) 1 mm down,
  and with C301 1 mm left: both build one whole zone per rail with all bias joined, no code change.
- **§4's "a via within 1.5 mm of every supply pad" fails for 15 pads on both boards** (U3.4, U3.11, U4.4, U4.11, U6.4, U6.11,
  U2.3, U5.3, Q301.3, Q303.3, C303.2, C305.1, R307.1, R312.2, R221.1). These pads are joined on top by 2b's links to a pad
  that has the via: `drops` places one via per top-layer piece. Making every pad take its own via would add about 15 vias
  in the busiest places. Your call; I'd drop that line from the rule.

### Baselines from this commit on
| | Neck (skip / on) | Bridge (skip / on) |
|---|---|---|
| rev06 | 422 mm, 14 vias / 428 mm, 13 vias | 408 mm, 15 vias / 410 mm, 16 vias |
| eacfa31 | 427 mm, 14 vias / 432 mm, 13 vias | 409 mm, 16 vias / 409 mm, 17 vias |

Flagged vias left after 2i with supply on: rev06 `/BAT-` (by design), `/Bridge/OA` R208.2-R225.1 and `/Bridge/OBN`;
eacfa31 `/BAT-` and `/Bridge/SO` U6.14-R231.2.

## Still open
- Partial copy, and bias tracks blocking the copy.
- D: board origin from the outline; `compare_channels.py` splitting by part name (yours).
- R106/R206 placement, and re-routing the gates on rev06 (yours).
