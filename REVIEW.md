# route6: reviewer feedback (20 Nov 2026, second round)

Reply to the landscape run feedback (`landscape_runs.zip`). The reply to the five bridge-run points and the twelve
questions is in git (`7696024`). How to run the pipeline is in `README.md`.

## What this is based on
- Router: KiCadRoutingTools tag v0.24.1 (`31049fd`).
- Board: `humbucker-preamp.kicad_pcb` at `25a2cbd`, with its `.kicad_pro`, now on the reviewer's machine.
- My run of setup to 2e on `7696024` matched `workR` exactly: the same track and via counts at 2b, 2c and 2d, and the same
  2e result (OB open, CLD 99 mm, OA 32 mm alone). The router is deterministic. The CLD lengths of 53, 61, 99 and 50 mm came
  from different commits and placements, so read them as sensitivity to small changes elsewhere, not as noise.
- 42 tests pass with `ROUTER_DIR` set.

## Fixed
### `/Neck/OB` open at R121.1: the retry was not at standard clearances
Pass 3 calls the router with `--clearance 0.3` as well as the widened clearance file. The retry for nets left open only
went back to the standard file and kept `--clearance 0.3`. Routed alone at the real standard clearances on the failed
board, OB joins at 46 mm for a 32 mm tree. Q103-C, which holds L3 where OB ran in 2i, was not the cause: removing it did
not change the result. The retry now drops `--clearance` too, and with that 2e joins OB.

New finding 3 (one step beat neck first) can be dropped: the open net in the neck-first runs was this bug.

### Step 2f failing `guard` on V+
Reproduced on `workR/2i.kicad_pcb`. The router's own clean-up ("Cycle prune", "Strict collapse") removed V+ scaffold.
`router(..., add_only=True)` also locks the given nets' earlier copper for the call. The router still routes a net with
locked copper, so 2f uses it. On the same board, 2f then passes and joins V+, V-, REF and `/Neck/SA` to their test points.
It is kept to 2f because the router's rescue and rip passes skip locked nets, which could cost completions in 2e and 2i.

### A failed step said "must-fix: none"
The failure now shows inside that field: `must-fix: step failed: 2e left ...`. A script that greps for "none" stops.

### Solo retry falls back to standard clearances, with the squeeze test
As agreed:
1. Solo at the pass-3 clearances. Joined within the length limit: kept.
2. Otherwise solo at standard clearances, starting the net again from its state before the step (its earlier pieces and
   pad vias were placed for the wider gap and box it in). Kept only if it joins, is within the length limit and is not
   squeezed (two or more foreign pads within 0.25 mm, a pass under a two-pad part excepted).
3. Otherwise the step fails, as before.

The shared pass-3 call's own retry at standard clearances is held to the same squeeze test: a squeezed pass-3 route is
dropped before pass 4.

## Where 2e stands on `25a2cbd`
2e fails on one net. `/Neck/CLD` is 99 mm for a 41 mm tree (limit 74). At standard clearances it routes at 72 mm, but
squeezed between C302.2 and R120.1, so the fallback refuses it. That is the rule doing its job; CLD needs a hand route or a
placement change near C302 and R120.

## Not done
- Partial copy (point 3): still the largest gain, not built.
- Bias tracks blocking the copy (point 2): not built.
- Five test points stay loose after 2f (`/Bridge/OA`, `/Bridge/SO`, `/Neck/OA`, `/VR`, `PB`): placement, on the author's side.
- I have not yet run 2h to 2f on my own board with these changes.

## What I would not trust yet
1. **A widened clearance blocks a net at its own pads.** The retry works round it; it does not cure it.
2. **supply5's zone shapes are constants** for one placement.
3. **2e and 2i fail where they used to pass, by design.** The board is rolled back, so the routed result is only in
   `work/<step>.kicad_pcb`.
4. **Untested code from the landscape patch:** via sizing by pad, pad vias for signals, the four-pass logic as a whole,
   `trim_centres`, the timing code.

The SVP loop is closed for the landscape board (9.2 mm for a 9.4 mm tree).
