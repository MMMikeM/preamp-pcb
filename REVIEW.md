# route6: review brief (20 Nov 2026)

This replaces the earlier review notes. Everything below describes the code as committed; history is in git.

## What this is
A staged pipeline that routes the humbucker preamp on 6 layers. It drives KiCadRoutingTools (Python driver, Rust search core;
tag v0.24.1, commit 31049fd) and wraps it with the project's own rules: what is routed, in which order, on which layer, and
whether a result is kept. The board is landscape, 74 x 41 mm: one channel strip at each end, shared blocks in the middle
(project doc `claude/landscape-layout.md`).

## Layers
| Layer | KiCad | Use |
|---|---|---|
| L1 | F.Cu | parts, local links, every high-impedance net |
| L2 | In1.Cu | solid ground |
| L3 | In2.Cu | signal crossings and the one V+ crossing |
| L4 | In3.Cu | solid ground |
| L5 | In4.Cu | V+/V- zones, battery, REF/PB; ground fill elsewhere |
| L6 | B.Cu | ground pour, test points, wire pads |

## Running it
```
export ROUTER_DIR=/path/to/KiCadRoutingTools
export R6_WORK=/path/to/workdir        # default: route6/work
python stage_route.py setup --from BOARD.kicad_pcb
python stage_route.py 2a               # then 2b 2c 2d 2e 2h 2i 2f
pytest -q tests                        # 38 tests, one needs ROUTER_DIR
```
Each step writes `<step>.kicad_pcb` and `<step>_checks.json` to the work folder and rolls the board back if a must-fix check fails.
The neck-to-bridge copy shift is read from the placement (`board.channel_shift`); step 2h fails if no net has a twin.

## Steps
| Step | What it does | Main code |
|---|---|---|
| setup | 6-layer stack, ground zones, strips old routing except hand-routed gate nets | setup6.py |
| 2a | high-impedance nets, top layer only, no vias | stage_route.route_hz |
| 2b | neighbour links on top before anything else | neighbour_links.py, toplink.py |
| 2c | one ground via per SMD ground pad | drops.py |
| 2d | supply: drop vias, L5 zones and stubs, the V+ crossing, battery nets, REF/PB | drops.py, supply5.py |
| 2e | remaining signals of the source channel, four passes (below) | stage_route.route_signals |
| 2h | copy the source channel's routing to the other channel (mirror or shift per net); a twin with locked copper is left alone | mirror_route.py |
| 2i | route what the copy could not cover | stage_route |
| 2f | test points | drops.py |

## Rules the code enforces
- High-impedance nets (GA, GB, GA_M, GB_M, VB, SVN, SVP, SVN_I, SVP_I, SVN_R, SVP_R): top layer, no vias, 0.4 mm clearance.
- A via must be justified: same-net pieces are joined on top first if a short path exists (via_justify.py). Signals and the
  battery nets: pieces up to 8 mm apart, path within max(1.5 x gap, gap + 3 mm). V+, V- and the bias nets: step 2b's limits,
  4 mm and max(1.5 x gap, gap + 1 mm), read from `neighbour_links`; what 2b could not join goes to L5 by design.
- Vias: 0.3 mm hole; the largest of 0.7 / 0.6 / 0.5 mm that fits inside the pad and is legal there. No vias in R109, R117, R209, R217.
- Ground: one via per SMD ground pad. Decoupling caps get their own supply via.
- Supply on top: only the links step 2b makes (pads up to 4 mm apart). Step 2d adds none.
- Step 2e passes:
  1. top layer only;
  2. a net that is incomplete, too long (`TOP_RATIO`, `TOP_EXTRA`), squeezed (`PINCH`: within 0.25 mm of two or more foreign pads,
     not counting a pass under a two-pad part or the net's own parts) or running more than `HZ_RUN` mm inside `HZ_NEAR` of
     high-impedance copper gets one via in a pad per top-layer piece, joined on L3 with no new vias;
  3. nets still open, or whose L3-only join wandered (`L3_RATIO`, `L3_EXTRA`), go to the router with its own vias allowed, at
     0.3 mm clearance and 1.0 mm from high-impedance nets;
  4. pad vias again for anything still open.

## Supply on L5 (supply5.py)
- V+ and V- are zones (`BOX`) with a 0.6 mm scaffold track along each (`LINES`), so the router and the checks can see them before
  KiCad fills the zones.
- A supply via off the scaffold gets one straight stub to the nearest scaffold track that is legal.
- V+ needs one crossing over V-, on L3, from the source cap C301 into the V+ finger at x = 51.9.
- A via of another net may land inside a zone: `drops.Placer` ignores scaffold tracks, and `trim_centres` cuts the scaffold back
  round the via afterwards.
- The V+ zone is kept out from under the input stages, because the gate wire pads pierce every layer.

## Timing and counters
Every step writes `<step>_timing.json` to the work folder and prints one summary line, for example:
`[2e] time 512 s: router 4 call(s) 470 s (path search 6.0 s) | other scripts 0 s | own work 9 s | checks 31 s | untimed 2 s`
- `parts`: one record per sub-step with its seconds. Kinds: `router` (a whole router call), `script` (another script as a subprocess),
  `own` (work inside stage_route) and `check` (the checks at the end of a step, each check timed separately in `per_check_s`).
- A router record also carries the router's own figures scraped from its log (wall time, path-search time, iterations, rip-ups of
  earlier copper, failed retries), what it achieved (nets given, nets completed, tracks and vias added) and how many earlier pieces were locked for the call.
- `counts`: router calls, nets given and completed, and for step 2e the nets in each pass, each rejection reason, pad vias placed.
- The timing code only observes. The one behavioural difference is that the router's output is now read line by line and passed
  through, instead of going straight to the terminal.
- Tested only by a `check` run and by feeding `run_router` a few sample log lines. No full step has been run with it.

What is already known about speed:
- In a router call, the path search (the Rust part) is about 1% of the wall time: 1.3 s of 134 s, 3.0 s of 125 s. The rest is the
  router's Python driver, paid again on every call. Step 2e makes three or four calls.
- In this project's own checks, `via_justify.check` is almost everything: 27.3 s of a 27.6 s `check` run on a board with 93 vias.
  Clearance, edge and connectivity checks together take about 0.2 s. That check runs at the end of every step from 2b on.

## State
- Placement: second-pass landscape, on the board and committed (d0408b9). Only the hand-routed gate nets are routed on it.
- On that placement, steps setup to 2d pass with no must-fix items: both supply rails connected, 68 vias, no clearance errors.
- Step 2e has not completed cleanly on it. Two runs ended with one earlier-step net open each (/Neck/SB, then /Neck/GB) because
  the router ripped copper from earlier steps (problem 1). A third run, with `guard` added, was interrupted before it finished.
- On the first-pass landscape placement, before the rip problem showed, 2e connected every neck and shared net with no
  clearance errors.
- Steps 2h, 2i and 2f have not been run on the landscape board.

## Known problems, most important first
1. **The router rips earlier copper.** With `KICAD_RIP_PREEXISTING=0` and `KICAD_FINALIZE_RIP=0` set in the environment
   (stage_route.py sets both at import), its log still shows "PRE-EXISTING rip" for nets it was not given, including the
   hand-routed gate nets. Either the variables are not reaching the code path that rips, or a different path is involved.
   The cause, as traced in the failing runs' logs on router `8a4432d`, is a third switch: at the end of a call the router's final
   reconciliation grants itself rip authority over the nets that blocked a failed one, unless
   `KICAD_RECONCILE_RIP_ESCALATION=0` (`route.py:8751` at v0.24.1, which has the same `route.py`). stage_route.py now sets all three. As a second line of
   defence, `stage_route.router` locks every track and via of the nets the router was not given for the length of the call (the
   router never rips a net with locked copper) and unlocks them afterwards; locks that were already in the board are left alone.
   `stage_route.guard` no longer repairs anything: if an earlier piece is missing or changed, or copper appears for a net the
   router was not given, the step fails and names the nets. Checked on router v0.24.1 with steps 2a, 2e and 2h on the 19 Nov
   portrait placement only; not on the landscape board, and the rip itself was not reproduced. The locked pieces are
   listed in `locked_for_router.json` in the work folder for the length of the call, so a run that is killed outright is
   unlocked by the next step.
2. **supply5's zone shapes are constants** derived by hand from the via positions of one placement. Moving a part with a supply
   via can silently break them; the only protection is the checks inside `run` (zone separation, stub legality, scaffold against
   through-hole pads).
3. **Zone connectivity is emulated.** `checks.unconnected` treats anything on a zone's layer as joined to that zone's net. Real
   connectivity is only known after KiCad fills the zones. `checks.zone_integrity` (must-fix at every step) covers the commonest
   way that goes wrong: it cuts every other net's copper, with clearance, out of each supply zone's outline and fails if the
   zone's own vias are no longer all in one piece. It does not judge ground pours, or a supply via that sits outside its zone.
   It has only been run on a constructed zone in the tests, never on supply5's real ones.
4. **Nothing added since the first review has tests**: via sizing by pad, pad vias for signals, the four-pass 2e and its rejection
   rules, supply5, `trim_centres`, the timing code. (Locking, `guard`, `zone_integrity` and the shift read from the board have tests.)
5. **The pinch rule let one through**: the final board of the last complete run still listed Net-(R307-Pad2) within 0.24 mm of
   R308.2 and R307.1, which are its own parts. The pass-1 rule now excludes own parts; eval2e.py's report does not yet.
6. `mirror_route` and `checks.symmetry` report 7 part pairs that are neither mirrored nor shifted (R107/R207, R110/R210, J101/J201
   and others). These are real asymmetries in the strips, older than this work; nets touching them fall to step 2i.

7. **A widened net clearance also blocks that net's neighbours at their own ends.** Measured on router 0.24.1: with V+ at
   1.4 mm, a battery via 0.5 mm from a V+ via could not be routed at all; at the standard 0.2 mm it routed. `stage_route.router`
   therefore retries, once and at the standard clearances, whatever a widened call left open (the bias call in 2d, pass 3 of
   2e). The retry is free to run where the widened call would not: `zone_integrity` catches a track that cuts a supply finger,
   and a pass-3 route that then runs beside high-impedance copper (the pass-1 test) is dropped and left to pass 4. The battery
   call uses standard clearances.
8. **The V+ crossing in supply5 is now tested against other copper before it is placed** and moves to the next landing position
   if it does not fit, but `supply5.run` itself has never been run on any board from this tree.

## Questions for the reviewer
1. Answered: a third rip switch, plus locking; see problem 1.
2. Should supply5 derive `BOX` and `LINES` from the via positions rather than carry them as constants?
3. Are the pass-2 rejection rules better expressed as router clearances than as checks after routing? Pass 3 already does this
   for its own run.
4. `stage_route.py` has grown to hold routing policy, router invocation, repair and timing. Worth splitting?
5. `via_justify.check` costs about 27 s per step. Is the path search inside it needed for every via on every step, or only for
   vias added since the last step?

## Files
| File | Role |
|---|---|
| board.py | board loader and writer, pad geometry, net classification |
| checks.py, krt_checks.py | this project's checks; the router's own checks as a second opinion |
| toplink.py, neighbour_links.py, via_justify.py | top-layer links and the via-justification rule |
| drops.py | via placement in pads |
| supply5.py | L5 supply for the landscape board (supply5_portrait.py: the portrait version, reference only) |
| mirror_route.py | channel copy |
| setup6.py | 6-layer setup |
| stage_route.py | the pipeline |
| spine.py, eval2e.py | helpers: finger-position search (portrait), reporting. eval2e.py needs r6render.py beside it and matplotlib |
