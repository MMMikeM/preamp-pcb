# route6: reviewer feedback (21 Nov 2026, evening)

Reply to `FEEDBACK_21NOV_PM.md`. Earlier rounds are in git (`6c27adb` and before). How to run the pipeline is in `README.md`.

## Basis
- Router: KiCadRoutingTools v0.24.1 (`31049fd`).
- Board: `fixtures/landscape-eacfa31`, setup to 2i, `R6_SKIP_SUPPLY=1`, `BIAS_L3_COST=1.0`. 2i fails only on V+ and V-.
- 48 tests pass with `ROUTER_DIR` set.

## Flagged vias routed again on top: built
At the end of `route_signals` (so in 2e and 2i), `top_again` takes each pair `via_justify` flags on a signal net:
1. It removes the pair's vias and the inner-layer track joined to them.
2. It routes the net on F.Cu alone, with no vias, its remaining copper locked.
3. It keeps the result only if the whole net is joined and passes `judge_top`; otherwise the board goes back.

Left out: supply, battery, ground and high-impedance nets (`/BAT-` is routed on L5 by design), nets with locked copper, and
pairs whose inner-layer track also serves a third pad (another via or a through-hole pad). A router failure inside a retry
puts the board back and carries on; it no longer fails the step.

On `eacfa31`:

| | Your run | With `top_again` |
|---|---|---|
| Neck | 429 mm / 14 vias | 429 mm / 14 vias |
| Bridge | 432 mm / 16 vias | 428 mm / 14 vias |
| `/Bridge/BO` | 19 mm, 2 vias | 15.1 mm, 0 vias |

`/Bridge/SB` was retried and not kept: the top route did not join. Unjustified vias at the end of 2i: 2 (`/BAT-`, `/Bridge/SB`).

## Code review and simplify pass over the whole branch
Fixed from the review:
- The standard-clearance retry ran for any router call given a clearance file, including 2d's bias call, where the
  widened V+/V- clearance is what keeps REF and PB out of the fingers. It now lives in pass 3 only (`wide_then_standard`).
- Pass 4's L3 join now locks the pad vias it just placed, as pass 2 does.
- A crash or Ctrl-C mid-step now puts the board back, as a `StepFailed` does.
- `Board.lock` treated `(locked no)` as locked.
- `supply5.py` stops with a message, not a `StopIteration`, when C301 has no V+ via.
- `eval2e.py` finds its modules from its own folder, not the working directory and `../mike`.

Not changed: `drops.py` exiting 2 when a pad gets no via still fails 2c and 2d. A ground or supply pad joins its plane only
through a via, so failing there is right.

Simplify: one helper each for things written several times in `stage_route.py` (removing new copper, length against tree,
the top-layer judging with "open", pad vias then L3, the router argument lists), the board's own via and track shapes,
`bd.is_signal` and `bd.is_battery`, and dead code removed (`drops.via_size`, unused parameters in `board.py`,
`neighbour_links.py` and `r6render.py`, `supply5.zones`, `supply5`'s empty TODO list, unused imports). The test file has
one work-folder fixture and shared helpers. A full `eacfa31` run before and after gives the same board at every step.

Log changes: pass 2 and pass 4 now print and count in the same form (`2e pass 4 pad vias` and so on), and the pass-4
counters are named like pass 2's.

## For you
- **`R6_SKIP_SUPPLY` still widens V+/V- for the bias call.** The switch skips the fingers, but `supply5.py --nc` still
  writes V+/V- at 1.4 mm, so in every comparison run so far REF and PB kept 1.4 mm from V+/V- copper on a board with no
  fingers. Moving the `--nc` block under the same switch would fix it, but it changes your comparison numbers, so it's
  your call.
- **`/VR` is not a bias net to the code.** `board.BIAS` has `'VR'`, but the net is `/VR` on every board, so
  `is_supply('/VR')` is false and it is routed as a signal. The `.kicad_pro` puts `/VR` in P6_Bias. Which one is right?
- `supply5_portrait.py` and `spine.py` are not imported or run by anything. Delete them if they're done with.

## Not done
- Partial copy, bias tracks blocking the copy, supply shapes from pad positions.
