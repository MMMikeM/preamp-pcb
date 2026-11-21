# Rules from the author, 21 Nov 2026 (evening)

Three parts: the schematic changed under you (read first), the hand-swap rule, and the supply rule you asked for.
Fixture for all of it: `fixtures/landscape-rev06/` (board and `.kicad_pro`), the author's tidied placement updated to the
new schematic.

## 1. The schematic changed: rev 0.6
Kicad repo commit `faa39e0`. Per channel (the bridge mirrors in 2xx):

- **20M pairs are single parts.** Gate bias R101/R102 47M (were R101+R102 and R103+R104, two 20M each). Servo inputs
  R125/R127 10M (were two 20M in parallel). Servo feedback R126/R128 47M (were two 20M in series). Simulated: same DC,
  noise, hum, response, headroom and overload recovery; the servo settles 0.3 s slower.
- **The gain resistor is one part.** R108 (1k) is gone; R106 (was R109) is 2k, 0805 hand-solder, between SA and SB.
- **Channel resistors renumbered** R101 to R129 with no gaps, order kept. Map in the kicad repo,
  `check/renumber_rev0.6.json`. Examples: R109 -> R106, R117 -> R114, R125 -> R122, R136 -> R129.
- **Nets gone:** GA_M, GB_M, SVN_R, SVP_R (each channel), `Net-(R108-Pad2)`. **Renamed:** `Net-(R125-Pad2)` ->
  `Net-(R122-Pad2)` (P4). The `.kicad_pro` netclass patterns and `netclasses-priority.json` are updated; the fixture's
  `.kicad_pro` has them.
- 14 fewer footprints (157 -> 143 on the board). The hand-routed gate tracks lost their midpoint pieces: VB is
  unconnected on both channels until the author re-routes the gates. Treat VB as not hand-routed on this fixture.

### What this breaks in the pipeline
- `board.NO_VIA_REFS = {'R109', 'R117', 'R209', 'R217'}` now names the wrong parts (R109 is an op-amp feedback resistor
  now). **Request:** stop listing references. Treat a footprint as hand-swapped when its Description contains
  "Swap by hand" (case-insensitive); `hand_access.hand_refs()` does that. Today it finds R106, R114, R206, R214.
- Anything else that names a reference or an auto net name: please grep for `R1[0-3][0-9]`, `R2[0-3][0-9]` and
  `Net-(R` in code and tests. The fixtures `landscape-74f5949` and `landscape-eacfa31` keep the old numbering, so tests
  pinned to them stay valid; new tests should use `landscape-rev06`.

## 2. Hand-swap parts must be reachable (new rule)
A part that is meant to be swapped by hand passes if **either**:
1. **edge:** its pads are within 3 mm of a board edge, and no other part's pad lies in the strip between it and that
   edge; **or**
2. **space:** no other part's pad is within 2 mm of its pads.

Plus the existing rule: no via in its pads.

`hand_access.py` in this branch implements the check (exit 1 on a failure). Please make it part of `setup`'s checks, as a
**warning** that names the parts, not a failure: the placement is the author's to fix, and routing should still run. On
`landscape-rev06`: R114/R214 pass on the edge rule; **R106/R206 fail** (0.76 mm from their nearest neighbour). The author
will move them.

## 3. Pad-via tie-break (request, small)
In `drops.run`, when a piece leaves the top layer, the via goes in the first pad of a sort by (IC/transistor last, bigger
pad first). Ties are broken by file order. On `eacfa31`, `/Bridge/SA`'s piece had four pads of the same size and the via
went on R233.1, 20.7 mm from the U2 pin it had to reach, while R210.2 was 15.9 mm away: about 5 mm of extra L3.

**Request:** sort by (IC/transistor last, distance to the nearest pad of the other pieces of the same net, bigger pad
first). Test: a piece with two equal pads gets its via on the one nearer the other piece.

## 4. The supply rule (you asked for it before any code)
Applies to step 2d (`supply5`). Coordinates are board-relative on `landscape-rev06` (origin top-left, x right, y down).
Everything below should be derived from pad positions, so it survives placement changes.

### Where the supply pads are
| Group | V+ pads | V- pads |
|---|---|---|
| Neck strip | column at x 13.2-15.8: U3.4, C309, U1.3, R110 | column at x 6.4-8.4: U3.11, C310, U1.7 |
| Bridge strip | column at x 65.7-68.3: U4.4, C311, U2.3, R210 | column at x 58.8-60.8: U4.11, C312, U2.7 |
| Middle | U6.4 (34.5, 32.7), C307, C305, C306, R307 | U6.11 (39.5, 32.7), C308, R312, U5.3, C303, C304 |
| Outliers | R111 (5.5, 25.3) in the neck's V- side; R211 (58.0, 25.3) in the bridge's V- side; R121/R221 (22.5 / 51.5, 9.1) in the Q blocks | - |
| Sources (power switch) | Q301.3 and C301 at the top right, (50.0, 5.6) | Q303.3 and C302 at the top left, (24.0, 5.6) |

Because the strips are copies, not mirrors, each strip has V- on its left and V+ on its right. So V+ and V- each have to
span the whole board, and they must cross once.

### The rule
1. **Layer:** V+ and V- are zones on L5 (In4.Cu). REF, PB and VR are tracks on L5 or L3 (2d as now).
2. **Fingers.** One V+ and one V- finger per strip, each a vertical bar under its supply column: x centred on the
   column's pads, from 1.5 mm above the top supply pad of the column to 1.5 mm below the bottom one, 2.4 mm wide. Derive
   each column by clustering that strip's supply pads by x (they fall into two clean groups today).
3. **Middle.** U6/U5 and their decoupling are fed by short stubs from the nearest trunk, never by a separate island.
4. **Trunks.** V- runs from its source (top left) along the top of the board, across to the bridge's V- finger, joining
   the neck's V- finger and the middle V- pads on the way. V+ runs from its source (top right) to the bridge's V+ finger,
   and to the neck's V+ finger and the middle V+ pads. Trunk width 1.5 mm or more. The trunks may run under parts: L5
   sits between the L4 and L6 ground planes, so nothing on top sees it.
5. **The one crossing.** V+ and V- cross exactly once, on L3, as a single track 0.4 mm wide, at most 4 mm long and at
   right angles to the other trunk. Put it in the middle third of the board (x 25-49), at the point where L3 has the most
   room once 2e/2i have routed; if that has to be decided before signals, pick the point with fewest signal pads within
   2 mm on L1. It keeps 0.4 mm from P1 and P2 copper on L3.
6. **Outliers** (R111, R211, R121, R221, and any future pad more than 3 mm from its finger or trunk) get a pad via and an
   L5 stub to the nearest piece of their own net's zone. A stub may not cross the other net's zone on L5. If it would, it
   takes the L3 hop instead, under the same rules as the crossing.
7. **Gaps.** At least 0.6 mm between a V+ zone and a V- zone on L5 (copper to copper), and the fingers keep 0.3 mm from
   every foreign via and through-hole pad. A finger may be cut back locally around a foreign via, but no zone may be split
   into two pieces by that (zone_integrity already checks this).
8. **Bias.** REF and PB keep using L5 between the fingers, and L3. A bias track may not cross a supply zone on L5; it
   hops on L3 instead.
9. **Every supply pad** (including decoupling caps) has one via within 1.5 mm that lands in its own net's zone or stub.

### Checks
- `zone_integrity` clean: each supply zone one piece, no bias track cutting a zone.
- Every V+/V- pad joined, no over-length supply link.
- **Signals do not move:** a full run on `landscape-rev06` with supply on, against the same run with `R6_SKIP_SUPPLY=1`.
  Per channel (`compare_channels.py`), signal track within 10 mm and vias within 2. If it costs more, the shapes are in
  the wrong place.
- Then remove `supply5.BOX` and `LINES`, together with points A and B from your list.

### Open to you
- Where exactly the trunks run (top edge, between the op-amp rows, or under the middle), provided points 4 to 8 hold.
- Whether the fingers are separate zones or one zone per net with a computed outline.
