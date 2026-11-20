# route6: reviewer feedback (20 Nov 2026)

Reply to the five points from the bridge run, plus where the pipeline stands. This replaces the earlier review brief; that
text is in git (`874be79` and before). How to run the pipeline is in `README.md`.

## What this feedback is based on
- Router: KiCadRoutingTools tag v0.24.1 (`31049fd`).
- Board: the 19 Nov **portrait** placement in `tests/board_placed_19nov.kicad_pcb`. The landscape board (`25a2cbd` in the
  kicad repo) is not on the reviewer's machine, so nothing below has been run on it.
- On that fixture: 40 tests pass, and steps setup, 2a, 2b, 2c, 2e, 2h and 2i run with the real router. Step 2d cannot run
  there, because supply5's zone shapes are for the landscape board. Step 2f was not run.

## The five points

### 1. Step 2i has the same gaps as 2e: done
2i runs the same four-pass code as 2e, so the pass-3 length test and the retry-alone step already applied to it. What was
missing was the failure. 2i now fails if any net on the board is still open (test points aside) or over the
`L3_RATIO` / `L3_EXTRA` length when it ends, and names the nets. The result that failed is kept in `work/2i.kicad_pcb`.

On the fixture, 2i routed every signal net and then failed on the six supply nets. That is expected there: without 2d the
supply is never routed.

### 2. Bias nets routed board-wide block the copy: agreed, not done
Take the second option: 2h removes a bias track that blocks a copy, and 2i re-routes the bias nets afterwards. The first
option needs the router to route part of a net, and it only routes whole nets.

What it takes:
- `mirror_route.blocker` returns the blocking pieces, not just the net name;
- when the blocker is a bias net, 2h removes those pieces and then prunes the dead ends left behind, so no stub stays on
  the board;
- 2i gains the bias call 2d has (L3 east-west, L5 north-south, the widened clearance file, the standard-clearance retry),
  before its signal passes;
- `zone_integrity` already covers a re-routed bias track cutting a supply finger.

Not written, because the fixture has no bias tracks to test it against.

### 3. Only 23 of 39 nets copy; the rest could be copied in part: agreed, not done
This is probably the largest gain of the five, and it attacks the noise in point 1 at its source: 2i would invent 16 short
links, not 16 whole nets. It is a new feature, not a fix:
- split each net's pads into those with a shifted twin and those with a mirrored twin;
- give each track piece to the group whose pads it joins, and copy each group by its own rule;
- leave the stretch between the groups unrouted for 2i, and record it so 2i knows the net is deliberately in two pieces;
- transistor nets (a SOT-23 cannot be mirrored) stay with 2i.

It should be designed against the real placement, not the portrait fixture.

### 4. 2h reports hand-routed nets as failures: done
A net whose counterpart on the other channel is already fully routed is reported as "already routed on the other
channel", not "left for individual routing". The counterpart is found by part number (the same pad of `X2nn` for `X1nn`),
so it does not depend on net names. On the fixture this covers GA, GB, GA_M, GB_M and VB.

2h also no longer replaces a twin that has locked copper; it leaves that net alone.

### 5. Small things
- **Counter labels: done.** A 2i run labels its counters and timing parts "2i pass 1" and so on.
- **Test points in 2i router calls: cannot be fixed here.** The router routes whole nets and has no option to leave named
  pads out, so it will go on trying the test-point pads of any net 2i gives it. It is log noise, not wrong copper.
- **2f dry run: not done.** Needs the landscape board.

## Changes since the landscape patch, in one place
- Three rip switches set (`KICAD_RIP_PREEXISTING`, `KICAD_FINALIZE_RIP`, `KICAD_RECONCILE_RIP_ESCALATION`).
- Every router call locks the copper of the nets it was not given and unlocks it afterwards. Locks already in the board are
  left alone. A killed run is unlocked by the next step (`work/locked_for_router.json`).
- `guard` only checks: earlier copper missing or changed, or copper for a net the router was not given, fails the step.
- `checks.zone_integrity` (must-fix): a supply zone must still join all of its own vias once other nets' copper is cut out.
- `via_justify`: V+, V- and the bias nets are judged by step 2b's limits (`neighbour_links.MAX_GAP`, `RATIO`, `EXTRA`);
  battery nets and signals keep the 8 mm window. Pairs where neither piece leaves the top layer are skipped.
- Step 2d no longer makes its own supply links; 2b's are the only ones. The rule-3 join is deleted.
- A router call with widened clearances retries what it left open at the standard clearances, once.
- The channel shift is read from the placement (`board.channel_shift`). `R6_SHIFT` is no longer read.
- supply5: the V+ crossing track is tested before it is placed; the V+ middle scaffold line is at x = 32.45.
- Step 2e: pass-3 length test, retry alone, drop of pass-3 routes beside high-impedance copper, and failure on open or
  over-length nets.

## What I would not trust yet
1. **Nothing here has run on the landscape board from this tree.** Step 2d in its current form, `supply5.run`, the zone
   check on real zones and the derived shift (it should come out as 52.45) have only been reasoned about.
2. **A widened clearance blocks a net at its own pads.** Measured: with V+ at 1.4 mm, a battery via 0.5 mm from a V+ via
   could not be routed; at 0.2 mm it routed. The retry at standard clearances is the workaround, not a cure.
3. **supply5's zone shapes are constants** for one placement. The x = 32.45 change is that weakness showing up for real.
4. **/Neck/SVP takes 33 mm for a 10.7 mm tree** on the portrait placement, and 2h copies the loop to the bridge. C114's
   other pad sits between C114.1 and U6.3 with 0.85 mm to the U6 pins; a 0.2 mm track at 0.4 mm clearance needs 1.0 mm.
   Routing order does not fix it. Turning C114 round would. Left as it is by decision. Step 2a has no too-long test.
5. **2e and 2i now fail where they used to pass.** That is intended, but the board is rolled back when they do, so the
   routed result is only in `work/<step>.kicad_pcb`.
6. **Untested code from the landscape patch:** via sizing by pad, pad vias for signals, the four-pass logic as a whole,
   `trim_centres`, the timing code.

## What I need
The board at `25a2cbd` on the reviewer's machine. With it: a full run setup to 2f, points 2 and 3 built and verified, and
the 2f dry run.
