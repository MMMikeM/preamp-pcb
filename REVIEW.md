# route6: reviewer feedback (21 Nov 2026)

Reply to `FEEDBACK_21NOV.md`. Earlier rounds are in git (`0eced4c` and before). How to run the pipeline is in `README.md`.

## Basis
- Router: KiCadRoutingTools v0.24.1 (`31049fd`).
- Board: `fixtures/landscape-74f5949`, run setup to 2i with `R6_SKIP_SUPPLY=1` and `BIAS_L3_COST=1.0`. 2i fails only on V+
  and V-, as expected with supply skipped.
- 46 tests pass with `ROUTER_DIR` set.

## The U3/U4 unit swap: nothing maps it wrongly
Checked every place that pairs one channel with the other, by running it on the fixture:
- `mirror_route.plan` (2h's copy) pairs pads by position and copies a net only if every pad lands on one twin net. The four
  nets on the swapped pins (`Net-(Q103-C)`, `/Neck/BO`, `/Neck/OBN`, `Net-(U3B--)`) are refused both ways. With the bridge
  made an exact shifted copy of the neck in memory they are still refused, because each lands on two nets, while
  `/Neck/OA`, `DA`, `DB` and `OB` copy as they should.
- `other_side` (the "already routed on the other channel" report) maps by pad number, but only between `X1nn` and `X2nn`
  parts. U3 and U4 never match, and the passives kept their pins. It gives the function twin for all 39 nets, both ways.
- `waits_for_copy`, `checks.symmetry` and `board.channel_shift` don't look at nets on U3/U4.

Mapping by net name would be wrong here: a copy of Q103-C onto Q203-C would end on U4.6, which is `Net-(U4B--)`. The real
cost of the swap is that the four bridge nets always wait for 2i. Two tests pin this on the fixture.

Seen in passing: `channel_shift` gives 52.44 on this placement (10 parts against 9 for 52.45), inside the copy's 0.03 mm
tolerance.

## P2/P4 before supply links: built as step 2p
`setup -> 2a -> 2p -> 2b -> ...`. 2p routes the P2_FrontEnd and P4_Stage2 nets on the top layer with no vias, in three
router calls: drains, then the second stage, then the rest of the front end. Copy targets are left to 2h; the bridge's
untwinned nets are routed here. A net is kept only if it joins and passes the same judging as 2e's pass 1 (length,
squeeze, high-impedance keep-away, now one function, `judge_top`); the rest is removed and left for 2e. The classes come
from the `.kicad_pro` beside the source board, which setup saves to `work/net_classes.json`.

Rule 2 (keep supply links 0.4 mm from P2/P4 copper) is not built. With P2/P4 down first, a 2b link can only route round
them; rule 2 would only widen the gap from 0.2 to 0.4 mm, which a decoupled rail doesn't need, and `via_justify` would then
flag the vias of every link it refused unless it learned the same rule. A test covers "a link goes round a track placed
before it".

### On the fixture, against the same pipeline without 2p
| | Without 2p | With 2p |
|---|---|---|
| Neck signal track / vias | 427 mm / 16 | 425 mm / 15 |
| Bridge signal track / vias | 436 mm / 19 | 428 mm / 14 |
| `/Neck/DB` | 18 mm, 2 vias | 12.2 mm, 0 vias |
| `Net-(Q203-C)` | 14.7 mm, 0 vias | 12.4 mm, 0 vias |
| Nets copied in 2h | 19 | 19 |

Costs: `/Bridge/OBN` +6 mm (one via fewer), `/Neck/OB` one via more. Left for 2e by 2p: `Net-(Q103-B)` (41 mm on top for a
9 mm tree), `Net-(Q103-E)`, `/Bridge/SA` and `/Neck/SB` (too long on top), `/Bridge/SB` (squeezed at Q202).

### Your acceptance check
R127 and C112 each moved 0.1 mm, setup to 2i: only the nets on those two parts changed (`/OUT_NK`, `/Neck/BO`, a GND
via). Q203-C and every other net were identical.

## Why Q203-C moved between your runs D and E: not found
The router is deterministic, so I tested whether one channel's routing can reorder the other's inside a shared router
call. Three tests say no on this fixture: the R127 nudge without 2p changed only R127's nets; re-routing two neck nets
inside the shared 2i call changed no bridge net; and 2p with a call per region gave the same board as one call. So I did
not split calls by region. R127 and C112 are 38 to 41 mm from Q203-C and their nets are not copied, so the copy can't carry
a change across either. Whatever moved it in E, it is not on this fixture.

## Your branch's code changes
- Pass 2's L3 join with `add_only=True`: agreed and kept; no completion was lost in any run here.
- `R6_SKIP_SUPPLY` and `compare_channels.py`: kept, and used for every comparison above.

## Not done
- Partial copy: still the largest gain.
- Bias tracks blocking the copy.
- Supply shapes from pad positions.
- `/Neck/CLD` and the five loose test points from the last round are with you.
