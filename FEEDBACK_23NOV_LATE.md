# Feedback, 23 Nov 2026 (late): L3 joins need netclass priority

Run on `bf12262` (no newer commits to pull). New fixture: `fixtures/landscape-aligned`.

## The fixture
Same circuit as `landscape-7bccb83`; placement changed by hand:
- each channel's input side (strip, U1/U3, J104/J105, JP102/JP202, Q101, R102, R109, R125, R123, C106, R111, C309,
  C111, C112 and the bridge twins) moved 1.27 mm inward; the transistor blocks (Q103/Q104, R116-R121, C108-C110 and
  twins) 1.20 mm (1.27 puts Q103's courtyard 0.05 mm into J103);
- U3 and U4 levelled and raised, each with its top row (R113/R122/C112, R213/R222/C212): both courtyard tops at y 6.95;
- U2 raised 0.25 mm to U1's height; U4 x set to U2's;
- C302 vertical (mirror of C301).

With the current pipeline **2e fails: `/Neck/SA` left open**. With the change below it routes:
neck 481 mm / 16 vias, bridge 464 / 17, `check --final` must-fix none, KiCad DRC 0 errors, 0 unconnected
(after removing one dangling stub, see 3).

## 1. L3 joins ignore netclass (the important one)
`pad_vias_then_l3` hands every leftover net to one `router(nets, ['In2.Cu'], ...)` call. On this placement Neck
OBN (P5) takes the L3 lane down the left edge and OB/CLD (P5) the one under U3, before SA (P2) is tried; SA then has
no way from the RS101.2 via to the R105/R106 cluster.

What I tried (test copy only, not pushed): route the L3 joins one class at a time, highest priority first:
```python
cl = net_classes(); groups = {}
for n in nets: groups.setdefault(checks.priority(n, cl) or 99, []).append(n)
for k in sorted(groups): router(groups[k], ['In2.Cu'], TOP_ONLY, add_only=True)
```
That routes this fixture, but on `landscape-7bccb83` it costs neck +12 mm and bridge +7 mm (SA itself +3.4 mm),
so **do not adopt it as is**. Suggested instead: keep the single batch; if a net of a higher class than any routed
net is left open (or too long), rip up the lower-class L3 routes in its corridor, route the higher class first, then
put the others back. Both fixtures should then pass, with `landscape-7bccb83` no longer than today.

## 2. Silent router death
Three full runs at once on this machine: `py_router/route.py` died while "Building base obstacle map..." with no
traceback; the log only says "exited non-zero". Most likely out of memory. Please report the exit code/signal (and
say "killed, probably out of memory" for SIGKILL) so it is not mistaken for a placement failure.

## 3. A dangling stub got through
On this fixture 2f left a 0.55 mm `PB` stub on In2.Cu, (120.05, 106.9) to (119.5, 106.9) absolute, joined at one end
only. `check --final` passed; KiCad DRC reported `track_dangling`. The stub removal should catch it, and
`check --final` should fail on any track end that joins nothing.

## 4. "Too long" stops the run
Raising U3/U4 0.5 or 0.83 mm (otherwise this fixture) failed 2e with
`/Bridge/SB: 41 mm for a 19 mm tree, over the limit for a net off the top layer`. The verdict is probably right for a
P2 net, but a hard stop means no board to look at. Suggest: finish the run, write the board, and report it as
must-fix, so the placement can be judged.

## 5. Small
`stage_route.py check --final` only checks `R6_WORK`'s board; a `--board PATH` option would make checking a
hand-edited board easy.
