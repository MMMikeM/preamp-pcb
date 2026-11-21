# Feedback on step 2p, 21 Nov 2026 (afternoon)

Reply to `REVIEW.md` at `6c27adb`. All runs: this branch at `6c27adb`, KiCadRoutingTools v0.24.1, `R6_SKIP_SUPPLY=1`,
`BIAS_L3_COST=1.0`, setup to 2i.

## 2p: confirmed, and the board is now routed with it
On `fixtures/landscape-74f5949` I get your numbers exactly: neck 425 mm / 15 vias, bridge 428 mm / 14. That result is now on
the author's board, unedited, so it can be reproduced from the code. Agreed on leaving rule 2 out, and on the U3/U4 mapping:
by position is right, by net name would have been wrong.

## New fixture: `fixtures/landscape-eacfa31`
The author's placement after a tidy pass: 45 parts snapped to shared rows and columns, none moved more than 0.23 mm, and
nothing on the hand-routed gate nets touched. Same `.kicad_pro`. The existing fixture is unchanged, so your tests still
pin `74f5949`.

| | `74f5949` | `eacfa31` |
|---|---|---|
| Neck | 425 mm / 15 vias | 429 mm / 14 vias |
| Bridge | 428 mm / 14 vias | 432 mm / 16 vias |

Two other variants of the tidy (different choice of column for the U4 inner parts, R125/R225 left in place) give the same
bridge result, so it is not one part's fault.

## Request: use the unjustified-via list to retry a top route at the end of 2i
On `eacfa31`, `/Bridge/BO` ends with 2 vias and 19 mm. `via_justify` already says why that is wrong:

    /Bridge/BO  U4.8 -> C212.1  gap 7.06  top_path 7.06  limit 10.59  vias (153.29, 91.09), (160.84, 82.93)

The top-layer corridor from U4.8 straight up to C212.1 is empty on the finished board; on `74f5949` the same net took it
(15 mm, no vias). In the 2i log the shared call routes BO first, then its slot-0 guard rips BO to retry it alone, and the reroute
then leaves C212.1 unconnected; pass 2 joins it on L3. Final reconciliation retries BO but by then it has its L3 link, so
nothing changes.

Suggested, at the end of 2i (and 2e):
1. For each unjustified pair where `top_path` is within the limit, remove that net's vias and L3 copper between the two
   pads, route the pair alone on F.Cu with no vias, and keep it only if it joins and passes `judge_top`.
2. Otherwise put the removed copper back.

The same check flags `/Bridge/SB` (two vias 2.5 mm apart, top path 2.98 mm) and `/BAT-` (J1.3 to Q302.2), so it would be
tried three times on this board. A test: a net joined through L3 where a top path within the limit exists comes out on top.

## Smaller things
- 2p left `Net-(Q103-B)` for 2e (41 mm on top for a 9 mm tree). That one is placement, on the author's side.
- `/Neck/SB` came out 5 mm longer on `eacfa31` with no part on it moved. Not asking for anything; noting it as another case
  of order sensitivity, now much smaller than before 2p.
- The D/E question (Q203-C) can be closed. With 2p it has stayed on top with no vias in every run since.
- The supply shapes are still constants for an older placement; that remains the next thing that blocks a full run.
