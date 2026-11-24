# route6: reviewer feedback (24 Nov 2026, fourth): tie rule, U3C--, a correction

- **Tie rule.** Routing scores within 1 mm of the net's own weight of the lowest are a tie; of those, fewest vias, then
  least track. The board before the lift is a candidate too when the net is already joined. A 1 % band was too wide (about
  14 points) and threw away real gains on 7bccb83 and aligned.
- **`Net-(U3C--)` is P4** in seven fixtures' `.kicad_pro`. 74f5949 and eacfa31 really have `Net-(U3B--)` and are unchanged.
- **Correction:** "each passes `check --final`" in the third reply was wrong. Those runs started at 2d on older boards.
  From setup, HEAD fails 2e on shift127 and aligned with a KRT end gap on `/Bridge/SB`: the router joined a track whose round
  end only reaches a via's edge, and `checks.ends_in` ignored the track's width, so `drop_dangling` cut it. Fixed.
- **Speed:** shift127 from setup to 2f takes 194 s instead of 681 s with identical copper. The suite takes 50 s.

### `check --final` from setup
| Board | Result |
|---|---|
| 83962f0, 509fb5a | pass |
| shift127 | `/Bridge/SB` too long, 34.3 mm against a 19.0 mm tree |
| aligned | `/Bridge/SB` too long (34.5 mm), and one unjustified SB via |
| 7bccb83 | `/Bridge/SA` too long (46.6 mm), the same at HEAD |

On shift127 and aligned both SB lifts come back at 30 mm and 4 vias, no better than before, so neither is kept. The long
bridge SA/SB joins are next on our side.

---

# route6: reviewer feedback (24 Nov 2026, third): your score answers, applied

`score.py` now uses your answers; the proposal section further down describes the earlier placeholders.
- **Weights:** gates and LINK 100; servo inputs 10; DA/DB 10; VB 3; other P2, P4, P6 3; P5 1; power 0.3; GND 0. Vias 2 mm.
- **Victims:** P1, DA/DB and the servo nodes only; a kilohm node is no longer charged for coupling.
- **Coupling curve:** in full within 2h, then 5/(1+(s/h)^2), so it is continuous at 2h (1/(1+(s/h)^2) alone drops from 1 to
  0.2 there). h from setup6's stackup: 0.0994 mm for the top layer (to L2). L3 is 0.1164 mm above L4 but 0.55 mm below L2, so
  its field is looser than the top's; it uses 0.1164, the nearer plane. Counted out to 16h, beyond which the share is under
  2 %. On the top layer that is 0.29 at 0.4 mm, 0.14 at 0.6 mm and 0.05 at 1 mm. Please confirm your order uses this stackup.
- **Aggressors:** P5 only. No P4 net is driven by an op-amp output: every output pin of U3/U4 is on a P5 net, and U6's are
  servo and bias nets. If you meant the second stage's swinging nodes (`Net-(Q103-C)`, the collector to U3.6), name them and
  they go in at half strength. `/TIP`, `/OUT_NK`, `/OUT_BR` and `Net-(J2-Pin_2)` are P5 already.
- `Net-(U3C--)` still has no class here; it waits for your `.kicad_pro`.

Re-run of the five boards: every result is identical to the one before, and each passes `check --final`. The verdicts of
the six comparisons in these replies hold with any one weight or constant multiplied or divided by 3, except that mirrorB's
"OB moved on top" now scores slightly worse (+21; its gain was on P2 source nodes, no longer victims). On 83962f0 the score
still calls lifting the bias for `/Neck/SA` even (1058 against 1056), as your weights for SA and PB (3 each) imply.

---

# route6: reviewer feedback (24 Nov 2026, second)

## `landscape-shift127`: `/Neck/SA` now joins
Reproduced your failure at `bf12262` (2e leaves SA open). The retry that lifts lower-priority L3 now tries both lifts from
the same board and keeps the one with the lower routing score (`score.py`), instead of refusing any result where a lifted
net ends over its limit:

| shift127, SA | SA | Neck | Routing score |
|---|---|---|---|
| bias lifted alone | 57 mm, 3 vias, 18 mm beside OBN | 499 mm / 18 vias | 2297 |
| every lower net lifted (kept) | **24.7 mm**, 3 vias | **465 mm / 18 vias** | **2086** |

The second was refused before because `/Neck/OA` came back 1.3 mm over its 24.6 mm limit. A net too long off the top layer
is now a warning on P4/P5 (as an unjustified via is), must-fix elsewhere.

That left one must-fix, an unjustified via on `/Bridge/SB` (U2.5's piece, joined through two vias though a 7.0 mm top path
fits its 7.8 mm limit). The top retry found that path but judged it by the top-only limit for a whole net, and SB, already
25 mm through its L3 link to RS201, fails that with any link. It now judges the new link: within the pair's own limit, not
squeezed, not beside high-impedance copper. **shift127 to 2f: every step passes, `check --final` passes with no must-fix**
(one P5 warning each for an unjustified via and a long net); neck 465 mm / 18 vias, bridge 456 / 15 (SB 31.5 mm / 2 vias,
was 30.4 / 4). The other four boards come out identical. Judging that retry by the routing score as well was tried and
dropped: mid-step, nets routed later are not there yet, and it refused a `/Bridge/DB` move the finished board was better for.

7bccb83, 509fb5a and aligned come out identical. **83962f0 changes:** lifting the bias shortens `/Neck/SA` 9.6 mm but costs
PB 6.3 mm and 2 vias; with SA (P2, not a drain) and PB (P6) both weighted 3 the score calls it even (3549 against 3548), so
SA stays at 34.3 mm, where the old rule (a P2 mm worth 3 of any other) took it. Your 22 Nov answer said a P2 millimetre is
worth more than a P6 one; with your weight answers in, please say whether the sources (SA, SB) should weigh more than bias.

---

# route6: proposal, 24 Nov 2026: a score weighted by node

Total millimetres and vias treat 20 mm of V+ like 20 mm of GA. `score.py` (read-only, not wired into any step) weighs each net
by how much it cares, so a change can be judged by what it does electrically. **The weights and two constants are yours to
set; the numbers below are placeholders from the parts list.**

## What it scores
Per net, weight x:
- **placement**: its shortest pad-to-pad tree (only moving parts changes it; reported apart, not part of the routing score);
- **excess**: length over that tree;
- **vias**: `VIA_MM` (2) mm per via;
- **coupling**: `COUPLE_MM` (5) x its length beside an output (P5) on the same layer, by edge-to-edge gap: within 0.3 mm in
  full, 0.6 half, 1.0 a quarter; round the gates 1, 2 and 3 mm (the pipeline already keeps outputs 1 mm off them). L2 and
  L4 are ground, so top and L3 do not see each other. Victims are P1-P3.
- **Not charged:** two nets the circuit joins through one or two 2-pad parts with R <= 10k or C >= 100p, not by way of
  ground, a rail or bias (stray capacitance there sits beside a far lower path). It prints the pairs; on 7bccb83: DA-OA
  (1k, 270p), DB-OB, SA-OA (2k), SB-OA, SB-OB (1k), SA-OB and SB-CLD through the other source, the C104/C105 nodes to
  DRVA/DRVB (100n), the C106/C107 nodes to OA/OB (270p), and the bridge twins. GA to CLD (330k) is charged.

| Weight | Nets | Why |
|---|---|---|
| 100 | GA, GB, LINK | the pickup node: only 47M and 220p on it |
| 30 | SVN, SVP, SVN_I, SVP_I | 10M and 47M nodes |
| 10 | DA, DB | op-amp inputs: stray capacitance touches loop stability |
| 10 | VB | gate bias, decoupled by C103 (100n to GND) |
| 3 | other P2 (SA, SB, emitter and coupling-cap nodes), P4, P6 | kilohm nodes |
| 1 | P5 | low-impedance outputs |
| 0.3 / 0 | P7 / GND | |

`Net-(U3C--)` has no class in the `.kicad_pro` (`Net-(U3B--)`, `Net-(U4B--)`, `Net-(U6C--)` do); it gets 3.

## What it says about changes made here
| Change | mm / vias | Routing score | Driven by |
|---|---|---|---|
| mirrorB: SB routed round the bias | bridge 456 -> 426 mm, 23 -> 22 vias | -95 bridge, +22 bias | SB's excess -12 mm; an output no longer beside `Net-(Q201-E)` |
| 7bccb83: lifting every lower net, not bias first | neck 453 -> 462 mm | +93 neck | SA +10 mm, 9 mm more beside CLD |
| mirrorB: OB moved on top (`345d035`) | bridge 426 -> 445 mm, 22 -> 19 vias | -30 bridge | OBN no longer beside two P2 nodes; OA's +15 mm is P5 |
| 83962f0: OB moved on top (`345d035`) | bridge 403 -> 401 mm, 18 -> 16 vias | -22 bridge | SB 3 mm shorter, one via fewer, less beside OBN |

Each verdict holds with any one weight, `VIA_MM` or `COUPLE_MM` multiplied or divided by 3, so none hangs on a guess.

## Output, for your reports too
One board: per channel the routing score split into excess, vias and coupling, each with its raw value (mm, count, coupled
mm), subtotals by class, and the nets that cost most with their coupling per output net. Two boards: per channel the change
in each term and which one drove it, and per net the change with its excess, vias and coupling per output net. `--json`
writes the weights and constants, both boards and the change. Please include the two-board summary when you report a
placement or routing change, alongside mm and vias.

## Questions
1. The weights: right order of magnitude, per node?
2. `COUPLE_MM` (how much worse a millimetre beside an output is than a millimetre of length) and the bands: no derivation
   here; your call.
3. Aggressors: only P5 now. Should the drains, or anything else that swings, count too?

---

# route6: reviewer feedback (24 Nov 2026)

Reply to `FEEDBACK_23NOV_LATE.md` and the 7bccb83 note. KiCadRoutingTools v0.24.1, `BIAS_L3_COST=1.0`, supply on.

## `landscape-aligned` routes here, at your commit
Setup to 2f at `bf12262`'s code: every step passes, neck 480 mm / 17 vias, bridge 454 / 16, `check --final` passes (one
P5 warning), and 2f leaves no `PB` stub. `/Neck/SA` joins at 31.8 mm / 3 vias. The router is deterministic here: 2e
under `PYTHONHASHSEED` 0 and 1 gives the same board. So your failing run differs by platform, or by the router dying
mid-run (point 2). **Please push the `work/2e.kicad_pcb` and log of a run where SA is left open**, so I can check the
fix below on the real case.

`landscape-7bccb83` reproduces your numbers exactly: neck 453 / 14, bridge 444 / 17.

## 1. Lower-priority L3 out of the way (generalises the bias retry)
At the end of 2e and 2i, for a net still open, or a P2 net joined off the top layer at over 1.5 x its tree: if signal
nets of a lower class, or bias nets, have L3 track in the box round its pads, those tracks are lifted, the net is joined
first (pad vias and L3, then with router vias if it must), and the lifted nets are routed again round it. The bias alone
is tried first, then every lower-priority net in the box. Kept only if the net now joins (or, if it was long, is
shorter with no more vias and the class-weighted total drops), every lifted net that was joined still is and is not
newly over its length limit, nothing new is squeezed or runs beside high-impedance copper, and no supply zone is cut.
One batch L3 call stays as before; this runs only after it.

| Board | Before | Now | `check --final` |
|---|---|---|---|
| 7bccb83 | neck 453 / 14, bridge 444 / 17 | identical | passes |
| aligned | neck 480 / 17, bridge 454 / 16 | identical | passes, 1 P5 warning |
| 83962f0 | neck 408 / 17, bridge 401 / 16 | identical | passes |
| 509fb5a | neck 409 / 15, bridge 415 / 11 | identical | passes |

Lifting every lower net at once first cost `/Neck/SA` 10 mm on 7bccb83 (a lifted net came back over its limit, so the old
bias-only result was lost); hence bias first. A stand-in-router test covers the open case: a P2 net shut out by a P5 L3
track joins first and the P5 track is routed again.

## 2. Router death
A script or router that ends by a signal is reported as such: "killed by SIGKILL, probably out of memory: not a routing
result". On Windows, the NTSTATUS codes for out of memory, access violation and stack overflow are named the same way.

## 3. Dangling stubs
Our track-end test used the track's round end, so a stub lying alongside a track counted as joined; KiCad uses the end
point. It now does too, and 2f clears loose copper on every net but the rails and ground (it had no clean-up before).
I could not reproduce your `PB` stub, as 2f leaves none here; none of our routed boards has a loose end by the new test.

## 4. "Too long" no longer stops the run
2e and 2i stop only for a net left open. A net over its off-top limit is listed as `too_long` in every step's checks and
fails `check --final`.

## 5. `check --board PATH`
`stage_route.py check --final --board PATH` checks that board, taking the net classes from the `.kicad_pro` beside it if
there is one; it writes nothing beside the board.

---

# route6: reviewer feedback (23 Nov 2026)

Reply to `FEEDBACK_23NOV.md`. KiCadRoutingTools v0.24.1, `BIAS_L3_COST=1.0`, supply on, 2d to 2i from each board's 2c.

## `check --final` passes on 83962f0, with no warnings at all
| Board | Before (`0cd0754`) | Now | `check --final` |
|---|---|---|---|
| 83962f0 | neck 408 mm / 17 vias, bridge 403 / 18 | neck 408 / 17, **bridge 401 / 17** | passes, 0 warnings |
| 509fb5a | neck 409 / 15, bridge 415 / 11 | identical copper | passes |
| mirrorB | neck 418 / 14, bridge 426 / 22 | neck 418 / 14, bridge 445 / 20 | passes |

- **The dangling `/Bridge/SB` track** (your 166.0, 100.8) and the piece it led from are removed. A track with an end that
  meets no copper of its net on its layer is removed at the end of 2e and 2i, repeated back along a stub, as long as the
  net stays joined the same way; `check --final` fails on any left (`dangling_tracks`).
- **That stub was hiding a real `/Bridge/SB` flag** (a 6.65 mm top path to R208.2), which the end-of-step top retry used to
  skip because SB's L3 track also serves R207.1. The retry now lifts only the inner-layer track between the two flagged
  pieces, if that splits the net in two and no more, routes them on top, and clears the vias left spare. On 83962f0 SB
  goes to 25.1 mm / 2 vias (was 28.3 / 3) and `/Bridge/OB`'s C207.2 link goes on top as well (29.1 mm, was 27.6, same 3
  vias), so no P5 warning is left either.
- **Unjustified vias by class**, from `work/net_classes.json`: must-fix on P1-P3, a warning on P4-P6 (bias included, being
  low-impedance like P4/P5), not reported on anything else, so `/BAT-` is gone. `checks.py --classes` does the same by hand.
- **The second opinion on V+.** Its complaint was not R110 but U2/R209 and C307/U6: their vias sit on the V+ zone's edge
  (C307.1's centre 0.15 mm outside it). With no KiCad here the router estimates the pour's fill, and that estimate stops
  short of them; KiCad's fill does not. A zoned net whose every pad reaches its zone through copper by our count is now
  listed apart ("by its estimate of the pour only", `krt_zone_fill_only`) instead of as unconnected. Setting
  `KICAD_PYTHON` to KiCad's Python should make the router's own check agree outright; not tried, KiCad is not installed here.
- **A via where two tracks end at different points, away from a pad, is kept.** Without it the ends would be 0.07 mm
  apart and the router's DRC flags the gap; that happened once while building this.

mirrorB's bridge is 19 mm longer: `/Bridge/OB` now goes on top in 2e (one via fewer), and `/Bridge/OA`, routed after it
in 2i, comes out 15 mm longer. mirrorB is the old placement; 83962f0 and 509fb5a show nothing like it.

## Addendum: the `/Bridge/OB` via at (171.35, 94.85)
It was not a via with one stub: two F.Cu tracks ended in it 0.07 mm apart (one at its centre, the one to RS202.1 at
171.4, 94.9), and I had kept it on purpose, since removing it alone left the router's DRC an endpoint gap. Now:
- `check --final` fails on any via with copper on one layer only, whatever touches it there (KiCad's test).
- The clean-up removes such a via, first joining the track ends that met in it to its centre on their layer (here a
  0.07 mm piece), and keeps it only if the net would still split; then removes any stub left loose, repeating back along
  it. It runs before and after the top retry and the bias retry at the end of 2e and 2i.
- On 83962f0 the via is gone: bridge 401 mm / **16** vias, neck 408 / 17, `check --final` passes with no warnings and the
  router's DRC has nothing. `509fb5a` is identical; mirrorB moves under 1 mm.
- Tests: two top tracks meeting only through a via lose the via and stay joined; a pad with a track to a via and nothing
  else on the via loses both.

---

# route6: reviewer feedback (22 Nov 2026, fifth)

Reply to `FEEDBACK_22NOV_LATE.md`. KiCadRoutingTools v0.24.1, `BIAS_L3_COST=1.0`, supply on.

## Rule 6's L3 hop: in 2d
Done in 2d, right after the split plane and before the battery and bias, so every later step routes round it. For each
V+ or V- pad whose via its zone does not reach, `hop_to_zone` lays one 0.4 mm track on L3 from that via to the nearest
via of its own net that the zone does reach, with no new via: the far end lands on a via already in the zone, so the
hop is the pad via, the track and that via. Our own path search (`toplink`), not the router: one track, deterministic,
and it keeps the high-impedance clearance. 2d then fails if V+ or V- is still open, which enforces "no V+ or V- open after
2d".

On 83962f0: R110.1 is joined in 8.5 mm (6.78, 27.58 board-relative) -> (11.78, 27.58) -> (14.27, 25.06), landing on the
via of the V+ column. The first leg is horizontal, at right angles under the V- column (4.2 mm under the V- zone), then
45 degrees for 1.1 mm more under it, then a 0.08 mm snap onto the via centre.

| 83962f0, from 2d | Neck | Bridge |
|---|---|---|
| Without the hop (`6f474ff`) | 408 mm, 17 vias; 2i stops, V+ open | 403 mm, 18 vias |
| With the hop | 408 mm, 17 vias; every net joined | 403 mm, 18 vias |

`/Neck/SA` comes out 24.7 mm instead of 24.0. `509fb5a` gives identical copper (no pad is cut off there).

- **`check --final` still fails on 83962f0, on unjustified vias**, as it did on your run and every run here before the
  hop: `/BAT-` J1.3-Q302.2 (by design), `/Bridge/OB` C207.2-via and `/Bridge/SB` track-track. `/BAT-` alone keeps it from
  ever passing on this placement; say if it should be excused rather than flagged.
- Not enforced: 0.4 mm from P2 copper on L3. At 2d there is none on L3, and later P2 routes keep the standard 0.2 mm from
  the hop; making them keep 0.4 needs a per-net-pair rule the router does not take.
- Test: a V+ pad beyond a V- zone, with its own zone round a far via, joins through one L3 hop and two vias, with no new
  copper on L5 and no clearance errors.

---

# route6: reviewer feedback (22 Nov 2026, fourth)

Reply to `FEEDBACK_22NOV.md` (with its answers) and the late-evening addendum to `FEEDBACK_21NOV_EVE.md`.
KiCadRoutingTools v0.24.1, `BIAS_L3_COST=1.0`, supply on, setup to 2i.

## 83962f0: R110 gets no V+ (please look first)
The split plane's V+ zone misses R110.1's via by 3.7 mm in our run, and by 2.2 mm in the zone already on your board.
Nothing else joins R110.1 to V+, so the pad is cut off. The old connectivity check counted any via on a zone's layer as
in the pour and passed it; the router's own checker has called V+ unconnected from 2d onward all along, but only as a
note. With the check fixed (below), 2i now stops on 83962f0 with V+ open. Everything else on the board joins.

## Bias retry: built
When a front-end (P2) net has joined off the top layer at more than 1.5 x its tree, and a bias net has L3 track in the
box round its pads (2 mm margin), the L3 tracks of both are lifted, the P2 net is joined on L3 again with no new vias,
and the bias is routed again as in 2d. It is kept only if the P2 net is shorter with no more vias, every bias net that
was joined still is and stays within its length limit, `zone_integrity` gets no worse, and the class-weighted total
drops (a P2 mm weighs 3, any other 1, a via counts as 3 mm of its net). Otherwise the board goes back. It runs at the
end of 2e and 2i.

| Board | Before | After |
|---|---|---|
| 83962f0 | neck 416 mm / 17 vias, bridge 403 / 18 | **neck 408 / 17**, bridge 403 / 18 |
| mirrorB | neck 418 / 14, bridge 456 / 21 | neck 418 / 14, **bridge 426 / 22** |
| 509fb5a | | identical copper (nothing qualifies) |

- 83962f0: `/Neck/SA` 32.5 -> 24.0 mm, same 3 vias; PB +6.3 mm and 2 vias. `/Bridge/SB` (28 mm for an 18 mm tree) was
  tried and not kept: no lower weighted total. Before is your run's figure exactly (2h skipped, `L3_RATIO` 1.9).
- mirrorB: `/Bridge/SB` 46.4 -> 34.4 mm, same 2 vias; `/Bridge/OA` (routed later, in 2i) 51.7 -> 35.0 mm and one more
  via; PB +2.7 mm and 2 vias, REF +0.7 mm. `/Bridge/DB` was tried and not kept.

How SB was found: alone on L3 with its own and OB's L3 tracks removed it stayed at 46.4 mm, so order among the signals
was not it; the only L3 copper on its straight line was PB. Of the 34.4 mm left, 12 are on top from U2.5 to the pad via
in R208.2; SB's tree is 28.4 mm, so 30 mm would also need that via nearer R207. `BIAS_L3_COST=2.0` does not help.

## `Net-(C205-Pad1)`: a gate net in its way, not L3
Routed alone on top, the 330k node joins in 7.9 mm on the setup board but needs 20 mm (over the limit) on the 2a board,
and more after 2p. The only 2a copper on its straight line is `/Bridge/GB`: 16.0 mm for a 16.4 mm tree, while
`/Neck/GB` goes round at 20.8 mm and leaves C105's way open. So it is P1 against P2: a bridge GB routed the neck's way
(about 5 mm longer) would let the node join on top with no vias. That trade is the author's to make.

## The rest: done
- **2h with nothing to copy** logs "nothing to copy" and passes.
- **P4/P5 off-top limit:** 2.2 x the tree for P4_Stage2 and P5_AudioOut, 1.8 for the rest, at the pass/fail test only;
  the pass-2 "wandered, redo in pass 3" threshold stays 1.8, so routing is unchanged. 83962f0 passes 2e at these limits.
- **Vias that join nothing** are removed at the end of 2e and 2i (signals) and 2d (battery and bias), and
  `check --final` fails on any left, a V+ or V- via its zone misses included. "Joins nothing": copper of its net on
  fewer than two layers, and the net's pads stay joined without it. It was a pass-2 pad via whose L3 join was later
  made another way: on `509fb5a` it removes your `/Neck/CLD` via, on mirrorB four. None on 83962f0.
- **J105/J205:** `board.py` reads zone connection "none"; setup links such a ground pad on top to the nearest ground
  pad. On 83962f0 its links are exactly yours (setup rips tracks, then lays the same two).
- **The connectivity check counted any copper on a zone's layer as in the pour.** It now needs to touch the zone
  outline. That is what finds R110 above. On rev06 it also shows U3.4's via 0.39 mm outside the V+ zone when 2b's links
  are left out; the split-plane test now runs on `509fb5a`.
- **Setup takes a board that already has the V+ and V- zones** (83962f0 does, unnamed): it drops them and 2d lays them
  again. Before, setup crashed on the unnamed zones.

Not done: refusing a 2e pad via that splits a supply zone. It has not come back, and `zone_integrity` still catches it.

---

# route6: reviewer feedback (22 Nov 2026, third)

Follows `a81a437`; the earlier parts of this file are unchanged below.

## The bridge is no longer a copy of the neck, so nothing waits for one
On `509fb5a` only 7 of 52 neck/bridge part pairs sit at a shifted or mirrored position (rev06 had 38, eacfa31 45), and
there is no common offset for the rest: your rework moved the bridge strip on its own. 2h copies 1 net of 33. So:
- **Partial copy, and moving bias tracks out of a copy's way, are dropped.** Both would gain almost nothing on this board.
- **2a, 2p, 2b and 2e now hold back only the nets 2h will actually copy.** Before, every bridge net with no neck twin also
  waited, so on `509fb5a` almost the whole bridge was routed last, in 2i.

| Supply on | Neck | Bridge | 2h copies |
|---|---|---|---|
| `509fb5a`, before | 444 mm, 16 vias | 448 mm, 15 vias | 1 |
| `509fb5a`, now | 444 mm, 16 vias | **435 mm, 11 vias** | 1 |
| rev06, before | 428 mm, 13 vias | 410 mm, 16 vias | 14 |
| rev06, now | 428 mm, 13 vias | 410 mm, 16 vias | 13 |

On `509fb5a`, `/Bridge/GB` drops from 30.3 to 21 mm, back inside the top-layer limit. On rev06, where the strips still line
up, the bridge's own nets now go in before the copy and cost it one net: `/Bridge/DB` was copied (12 mm, no vias) and is now
routed in 2i (17 mm, 3 vias), while `/Bridge/OBN` loses 3 vias. If you ever make the strips copies again, that trade is
worth a second look.

## Smaller items
- **Bias cost.** `BIAS_L3_COST=2.0` on `509fb5a` moves 14 mm of bias from L3 to L5 for 3 more bias vias; signals barely
  move (neck 444 -> 447 mm, one via fewer; bridge 448 -> 447). Nothing to gain; keep 1.0.
- **Speed.** The via check is cached per net and board, so 2e and 2i stop checking the same board twice; `toplink` skips
  its second search when the first proved the target unreachable; the high-impedance keep-away and the pad index used by
  the squeeze test are built once per board state. Same boards at every step; a `509fb5a` run goes from 133 to 120 s.
- **Flagged vias.** On `509fb5a` only `/BAT-` is left, by design. The rev06 and eacfa31 ones are gone with the boards.

## Left
- 2f, once the test points are back.
- Yours: board origin from the outline in `r6render.py`; the test points.
- Done on the author's side (21 Nov, evening): `compare_channels.py` now splits by part name (X1nn/U1/U3 neck, X2nn/U2/U4
  bridge, the rest 'Shared'; net names /Neck/ and /Bridge/ win), so it no longer depends on x < 137. `Net-(Q103-B)` is
  fixed by the author's rework: 8.0 mm, no vias, joined in 2p (`Net-(Q203-B)` 7.7 mm, no vias) on `509fb5a` at `1f3afca`.

---

# route6: reviewer feedback (22 Nov 2026, second)

Reply to `FEEDBACK_21NOV_EVE.md`. The earlier part of this file (the split-plane supply) is unchanged below.

## Gate nets: a net left open is routed again first
`route_hz` (2a and 2i) now does what you asked: when a high-impedance net is left open, the other high-impedance nets of
its channel that the call routed are ripped, the open net is routed alone, then the others, and that order is kept if all
of them join within the top-layer length limit (`TOP_RATIO`, `TOP_EXTRA`). Otherwise the first attempt stands and the step
goes on as before. A router failure inside the retry also restores the first attempt. Channel is read from the net name
(`/Neck/...`, `/Bridge/...`). Two tests with a stand-in router: the blocked order is fixed by the retry, and a retry that
does not help leaves the first attempt.

I could not reproduce your rev06 case: my supply-on rev06 run from `45ef5e0` joins `/Bridge/GA`, so the retry has not
fired on a real board yet.

## `509fb5a`: your numbers, exactly
Supply on, setup to 2i: neck 444 mm / 16 vias, bridge 448 mm / 15 vias. Every step passes, no open nets, `zone_integrity`
clean, only `/BAT-` flagged. All six gate nets join on top with no vias. One to look at: `/Bridge/GB` is 30.3 mm for a
19.1 mm tree (neck GB 22.7 for 20.9); that is over the top-layer limit (28.7 mm) and 2a has no length test, so nothing
flags it.

## `SUPPLY_RULE.md` rewritten
It now describes the split plane as built, with the 1.5 mm line gone and the acceptance checks kept. The comb and trunk
text is in git (`ecb0475`).

## Next on our side
Partial copy together with bias tracks blocking the copy, since both change 2h.

---

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
