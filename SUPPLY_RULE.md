# Supply on L5: the rule (rewritten 22 Nov 2026)

What step 2d builds, as accepted in `FEEDBACK_21NOV_EVE.md`. The comb and trunk shapes this file used to describe were never
built; the router's split plane replaced them. Their text is in git (`ecb0475`).

## Layers
- **L5 (In4.Cu):** one V+ zone and one V- zone, on top of the GND pour that `setup` lays on the whole layer. REF, PB and
  /VR as tracks, on L5 or L3.
- L2, L4 and L6 stay ground. L5 sits between L4 and L6, so nothing on L5 couples to the top layer.

## How the zones are made
1. `drops.py --supply` puts one via in a pad of each top-layer piece of V+ and V-; decoupling caps always get their own.
2. The router's split plane (`py_router/route_planes.py`, the "spine split") is run for `GND|V+|V-` on L5, on a copy of
   the board. GND is the layer's background. Each rail gets one region grown round its own pads and vias, joined by
   corridors on the layer, and the regions are laid out so the two rails never cross.
3. Only its V+ and V- zones are kept, at the fill priorities it assigns. Its own GND pieces are dropped, so the GND pour
   stays as `setup` made it, and `guard` confirms it placed no tracks or vias.
4. A rail pad whose via the zone does not reach (its L5 stub would cross the other rail's zone) gets rule 6's L3 hop: one
   0.4 mm track on L3, no new via, from its pad via to the nearest via of its own net that the zone does reach. 2d fails
   if V+ or V- is still open after that.
5. The battery nets, then REF, PB and /VR, are routed by the router at the standard clearances.

No board coordinates, no part names. A placement change moves the zones with it.

## What must hold after 2d
- `zone_integrity` clean: each rail's zone is one piece that holds all of its vias, with no foreign track cutting it.
- No V+, V- or bias net open.
- No supply via outside its own rail's zone, except a pad via joined to the zone by its L3 hop.

## Acceptance for a change to this step
- On the current fixture, supply on against `R6_SKIP_SUPPLY=1` from the same commit: per channel, signal track within
  10 mm and vias within 2, and no P1, P2 or P4 net changes layer or gains a via.
- Robustness: the same run with one strip's op-amp block moved 1 mm down, and with C301 moved 1 mm left, still builds valid
  zones without any code change.

## Not covered
- Test points: off for now; when they return, a supply test point is one more pad joined through its via.
