# Supply on L5: the rule (21 Nov 2026)

What step 2d should build, written from what `supply5.py`'s constants do on `eacfa31`, with no coordinates. Everything
below is derived from pad positions after 2c, so a placement change moves the shapes with it.

## Layers
- **L5 (In4.Cu):** V+ and V- as zones, each with a 0.6 mm scaffold track along its middle. REF, PB and /VR as tracks in the
  gaps between the zones.
- **L3 (In2.Cu):** the one V+ crossing (below), and bias tracks that cannot find a gap on L5.
- L2, L4 and L6 stay ground. L5 sits between L4 ground and L6 ground, so nothing on L5 couples to the top layer.

## Where the pads are (eacfa31)
| Group | V+ | V- |
|---|---|---|
| Neck strip | inner side: U3.4, U1.3, C309, R113, R114 | outer side: U3.11, U1.7, C310 |
| Bridge strip | outer side: U4.4, U2.3, C311, R213, R214 | inner side: U4.11, U2.7, C312 |
| Middle | left of centre: U6.4, C307, C306, C305, R307 | right of centre: U6.11, U5.3, C303, C304, C308, R312 |
| Q blocks | R124, R224 (top of each Q block) | none |
| Sources | Q301.3 / C301.1, top of the middle, right | Q303.3 / C302.2, top of the middle, left |

The strips are shifted copies, not mirrors, so the V+ column is on the inner side of the neck and the outer side of the
bridge. The rule must not assume the two strips mirror each other.

## The shape: two interleaved combs
1. **V- hangs from a top bar.** One horizontal bar just below the supply row (below the sources and J1 to J3) runs from the
   neck's V- column to the bridge's V- column. One finger drops from it down each strip's V- column, and one down the
   middle's V- side.
2. **V+ rises from a bottom bar, in the middle section only.** The bar runs along the bottom of the middle between the two
   strips. One finger rises from it down the middle's V+ side. Each strip's V+ finger joins the bottom bar by a horizontal
   link placed below the strip's lowest supply pad and above the input wire pads.
3. **Never under the input wire pads.** J101/J102 and J201/J202 pierce every layer. No zone and no scaffold within 1 mm of
   their row; the gate area stays solid ground on every inner layer.
4. **The V+ crossing on L3.** The V+ source is at the top, above the V- bar, so it needs exactly one crossing; two combs
   fed from the same edge cannot avoid it. Rule:
   - from the source's pad via, one L3 track to a new 0.6/0.3 mm via on the V+ finger nearest the source in x;
   - land at the first point below the V- bar where the via is legal and the L3 track keeps its clearances;
   - straight down, or one 45 degree jog then down; nothing longer;
   - laid in 2d, before 2e, so signals route round it; 0.4 mm from any P2 or P4 copper already on L3 from 2p.
   If a placement ever puts the V+ source below the V- bar, there is no crossing.
5. **Finger position.** Centre each finger on the median x of its column's supply pads. Width 3.0 mm (scaffold 0.6 mm plus
   1.2 mm of zone each side), clipped where it would come within 0.5 mm of the other rail's zone. Vertical extent: from the
   bar to 1 mm past the furthest pad in the column.
6. **Under parts: yes.** L5 is buried; a part on F.Cu does not care what is on L5. What a finger must avoid is foreign holes:
   - a foreign via: the zone flows round it, and `trim_centres` cuts the scaffold back (as now);
   - a through-hole pad of another net (J103/J203, the battery and output wire pads, and the hand-fit resistor holes still
     to come): the scaffold must not touch it (fatal, as now); the zone flows round it.
   If a finger's scaffold cannot run straight past a through-hole pad, shift the whole finger sideways in 0.1 mm steps up
   to 1 mm; beyond that, fail and say which pad.

## Joining the pads
- Each supply pad gets its own via in or beside the pad (2c, as now).
- A via inside its own zone needs nothing more.
- A via outside its zone gets one straight stub on L5 to the nearest point of its scaffold, at most 3 mm long, crossing
  no foreign copper and keeping 0.5 mm from the other rail's zone. No straight stub: move the via along the pad (2c's
  `spot`), and if that fails, fail the step and name the pad. Do not bend the stub or route it.
- R124/R224 (V+ at the top of each Q block) are the likeliest to need a stub; they sit between the V- bar and the middle.

## Bias: REF, PB, /VR
- Routed after the zones, on L5 in the gaps between fingers, keeping the widened clearance from the zones (as now).
- A bias track never crosses a finger. If the only path on L5 crosses one, that bias link goes to L3 instead.
- REF and PB pads sit inside both strips (U3/U4 REF pins, the Q101/Q102/Q201/Q202 PB bases), so each strip needs one gap
  wide enough for a bias track between its V+ and V- fingers. With the fingers on opposite sides of each strip, that gap
  is the strip's middle, under the op-amp and JFET, and it is about 5 mm wide on `eacfa31`.

## Checks
- `zone_integrity` clean; every zone piece holds at least one same-net via; no V+ or V- open after 2d.
- On `eacfa31`, supply on against supply skipped, from the same commit: per channel, signal track within 5 mm and vias
  within 2; no P1, P2 or P4 net changes layer or gains a via.
- Robustness: the same run with one strip's op-amp block moved 1 mm down, and with C301 moved 1 mm left, still builds valid
  shapes without any code change.
- No board coordinates in the code, only margins and widths.

## Not covered
- Test points: off for now; when they return, a supply test point is one more pad joined as above.
- Battery (BAT+, BAT-) stays as it is.
