# Feedback, 23 Nov 2026: the hop works; three loose ends

Reply to `REVIEW.md` at `0cd0754`. 59 tests pass here. Full run on `fixtures/landscape-83962f0` (supply on, 2h skips):
neck 408 mm / 17 vias, bridge 403 / 18, `[2f] unconnected nets 0`.

## KiCad DRC on that routed board (zones refilled)
**0 unconnected pads**: R110.1 is on V+ through the hop. Accepted.

But `check --final` still prints `second opinion: ... nets only it calls unconnected: ['V+']`. KiCad says joined, so the
second opinion is wrong here, most likely because it does not follow a track that lands on a via inside a zone (or does
not see the L3 hop at all). Please make it agree with KiCad, or at least not report V+/V- when every V+/V- pad reaches
its zone through copper; otherwise the warning will be ignored the day it is right.

KiCad also reports one item of ours:
- **`track_dangling` on `/Bridge/SB`**: F.Cu, 1.63 mm, unconnected end at (166.0, 100.8) absolute, board-relative
  (66.0, 20.8). This is probably your "`/Bridge/SB` track-track" unjustified item. A track end that joins nothing should
  be removed like the dangling vias (end of 2e and 2i), and `check --final` should fail on any left.

(The rest is the author's: silkscreen clearance and two silk-over-copper; the six "footprint library not in this
configuration" items come only from running DRC on a copy outside the project folder.)

## Unjustified vias
- **`/BAT-` J1.3 to Q302.2: excuse it.** Battery and supply nets (`/BAT-`, `/BAT+`, V+, V-, and the switch nets) are
  low-impedance; a via costs nothing there. Excuse by class (P7_Power / P8_GND and anything that is not P1-P6), not by
  name.
- **`/Bridge/OB` C207.2: keep flagging it.** It is P5 and harmless, but it is a real unneeded via; if the end-of-2i
  top-retry (via_justify) can take it back to top, do; if not, a warning is enough. Please make unjustified vias on P4/P5
  a warning rather than must-fix, and keep must-fix for P1-P3.
- **`/Bridge/SB`**: the dangling track above.

Result wanted: `check --final` passes on 83962f0 with only P5 warnings, and its second opinion agrees with KiCad.
