# route6: reviewer feedback (21 Nov 2026, late)

Reply to the ordering you proposed after `138aa21`. Earlier rounds are in git (`138aa21` and before). How to run the
pipeline is in `README.md`.

## 1. The flagged-via retry: done in `138aa21`
At the end of 2e and 2i, `top_again` re-routes on F.Cu, alone and with no vias, each signal pair `via_justify` flags, and
keeps it only if the whole net stays joined and passes `judge_top`. On `eacfa31`, `/Bridge/BO` went from 19 mm with 2 vias
to 15.1 mm with none. Supply, battery, ground and high-impedance nets are left out (`/BAT-` is on L5 by design), and so are
nets with locked copper and pairs whose L3 track also serves a third pad.

## 2. The small batch: done
- **C, one clearance loader.** `bd.net_clearances(over)` and `bd.write_clearances(path, over)`; pass 3, 2d's widening,
  `krt_checks` and the router default all go through them.
- **`R6_SKIP_SUPPLY` fix.** With the switch set, `supply5.py --nc` writes the standard clearances, so the bias call no
  longer keeps 1.4 mm from V+/V- copper on a board with no fingers.
- **`/VR` is a bias net.** `BIAS = {'REF', 'PB', '/VR'}`. It is now routed in 2d with REF and PB: on `eacfa31` 10.6 mm with
  2 vias on L5, where as a signal it was 9.5 mm on top with none. `zone_integrity` is clean.
- **E.** `supply5_portrait.py` and `spine.py` are deleted.

48 tests pass.

### New baseline: `eacfa31`, setup to 2i, `R6_SKIP_SUPPLY=1`, `BIAS_L3_COST=1.0`
Compare only against runs made from this commit on.

| | Before the batch (`138aa21`) | New baseline |
|---|---|---|
| Neck signal track / vias | 429 mm / 14 | 427 mm / 13 |
| Bridge signal track / vias | 428 mm / 14 | 425 mm / 17 |
| Unjustified vias after 2i | 2 (`/BAT-`, `/Bridge/SB`) | 1 (`/BAT-`) |

The bridge's three extra vias come from nets that now route round bias tracks laid at 0.2 mm instead of 1.4 mm:
`/Bridge/OB` +2 (25 to 35 mm), `/Bridge/CLD` +2, `/Bridge/OA` +1 but 12 mm shorter, `/Bridge/SB` -2.

## 3. The supply-shape rewrite, with A and B: next, after your rule
Agreed on all three conditions:
- measured against the new baseline above;
- signals must not move: a full `eacfa31` run with supply on is compared per channel against the same run with supply
  skipped, and more than a few mm or a couple of vias means the shapes are in the wrong place;
- a written rule first. Yes please: write it from what the current constants do on `eacfa31` and push it to this branch.
  Covering the four points you listed (one V+ and one V- finger per strip along the op-amp and JFET supply pins, the
  spine across the middle, REF and PB kept out of the gaps, and what happens when a pad's via can't reach a finger) is
  enough to start. Two things worth saying in it too: where the V+ crossing on L3 goes, and whether a finger may run under
  a part or only between rows.

A (scaffold from the zones) and B (the copy step using the via placer's check) go in the same change.

## 4. D: whenever
Board origin and centre from the outline. `compare_channels.py` should split channels by part name rather than x, as you
say.

## Still open
Partial copy, and bias tracks blocking the copy.
