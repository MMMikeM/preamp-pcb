# Feedback on the split-plane supply, 21 Nov 2026 (evening)

Reply to `REVIEW.md` at `45ef5e0`. All runs on this branch at `45ef5e0`, KiCadRoutingTools v0.24.1, `BIAS_L3_COST=1.0`,
setup to 2i, **supply on** unless stated.

## The split-plane supply: accepted
- It routes the author's current board completely with supply on: every step passes, no open nets, nothing must-fix.
  Taking it as the supply method.
- **Drop the "via within 1.5 mm of every supply pad" line** from `SUPPLY_RULE.md`. Agreed with your reasoning: those pads
  are joined on top to a pad that has the via, and 15 more vias in the busiest places is the wrong trade.

## New fixture: `fixtures/landscape-509fb5a`
The author's board as of kicad commit `509fb5a`, with its `.kicad_pro`. Since rev06 it has:
- the author's rework of the bridge strip, the bridge gate network (R201 to R204) and the middle (`8faafe2`);
- **R106/R206 (gain) now 5.6k 1206 hand-solder** (gain 1.86, on the existing 5.6k line), moved to the bottom edge at
  (22.75, 36.0) and (51.25, 36.0), so all four hand-swap parts pass `hand_access.py`;
- no tracks at all: the gates are no longer hand-routed, so the pipeline routes them (2a / 2i, P1 rules).

| Board | Neck | Bridge |
|---|---|---|
| `8faafe2` (author's rework, R106/R206 still 0805 in the Q block) | 427 mm, 14 vias | 432 mm, 14 vias |
| `509fb5a` (R106/R206 on the bottom edge) | 444 mm, 16 vias | 448 mm, 15 vias |

The difference is the price of the hand-swap rule, almost all on SA/SB (neck SB +12 mm / +2 vias, bridge SA +7, SB +9).
The author accepted it.

## Request: retry a failed gate net in the other order
On rev06 (before the author's rework) 2i left `/Bridge/GA` open. The cause:
- The pickup pads are not part of the strip copy: J201/J202 sit 50.0 mm from J101/J102, where every other bridge strip
  part sits 52.45 mm from its neck twin. That is deliberate (ground pads at the outer corners; a 2.45 mm shift would put
  J201 pin 4 on top of J204). So 2h cannot copy the gates, and 2i routes them from scratch.
- 2i routed `/Bridge/GB` first. It went round the outside of the strip (30-32 mm against the neck's 23 mm) and closed the
  only corridor GA had to U2 pin 8.
- The same happened in one of the author's R206 trial positions (`/Bridge/GA` open, everything else joined).

High-impedance nets are top-only with no vias, so a bad order is fatal for them. **Request:** when a P1 net is left open
in 2a or 2i, rip the other P1 nets of the same channel that were routed in that call, route the failed net first, then
the others, and keep the result if all of them join within their length limits. Otherwise restore the first attempt and
fail as now. A test: two top-only nets where the first-routed one, taking its shortest path, blocks the second, and the
reverse order joins both.

## Coming, so you are not surprised
- The author may rename the hand-swap parts to their own prefix (RS101/RS102, RS201/RS202) so they stand out. Your code
  finds them by description, so nothing should depend on it; the fixtures would keep the R names.
- `compare_channels.py` splitting by part name (your point D) is still on our side.
