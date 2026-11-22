# Feedback, 22 Nov 2026 (late): R110 needs the L3 hop

Reply to `REVIEW.md` at `6f474ff`. All 58 tests pass here. Thanks for the connectivity fix: it found a real fault that
our earlier "0 unconnected" runs hid.

## Confirmed on `fixtures/landscape-83962f0`
Full run at `6f474ff` (2h now skips): 2i stops with `V+` open, everything else joined. The pad is R110.1 at
(6.78, 27.58) board-relative, the Q102 emitter resistor. It sits left of the neck's V- column (C310.2 at x 6.87,
U3.11 / U1.7 at x 9.32), while the nearest V+ copper is the V+ column at x 14.27-16.83 (U3.4, U1.3, C309.1, R109.1). An
L5 stub from R110.1 to the V+ zone must cross the V- zone, so 2d leaves it.

## Request: implement rule 6's L3 hop (SUPPLY_RULE / RULES_21NOV section 4)
> Outliers ... get a pad via and an L5 stub to the nearest piece of their own net's zone. A stub may not cross the other
> net's zone on L5. If it would, it takes the L3 hop instead, under the same rules as the crossing.

So for a supply pad whose shortest L5 stub would cross the other rail's zone:
1. Pad via (it has one already in R110.1).
2. A single L3 track, 0.4 mm, from that via to a new via inside its own zone, at right angles where it passes under the
   other rail's zone where possible, keeping 0.4 mm from P1/P2 copper on L3 (the crossing's rules). No length cap beyond
   "shortest that lands in its own zone with 0.3 mm margin"; here that is about 8 mm (x 6.8 to about 14.5).
3. Do it in 2d, before signals, so 2e/2i route round it; or, if L3 is better decided after signals, at the end of 2i with
   the same rip-and-retry as the bias retry. Your call; say which.
4. `check --final` should then pass on 83962f0 with V+ joined.

Test: a supply pad placed beyond the other rail's finger joins through one L3 hop and two vias, and nothing crosses a
zone on L5. Please report both channels on 83962f0 before and after (signals should move by no more than the usual run
noise, about 10 mm a channel).
