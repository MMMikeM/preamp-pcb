# route6
Step-by-step 6-layer routing helpers for the humbucker preamp board. Start with `REVIEW.md`.

    pip install -r requirements.txt
    python -m pytest -q tests                 # about 2 minutes
    python via_justify.py tests/board_4layer_rev1.kicad_pcb
    python stage_route.py setup --from ../../../humbucker-preamp.kicad_pcb
    python stage_route.py 2b                  # then 2c; steps 2a, 2p, 2d, 2e, 2i, 2f also need ROUTER_DIR
    python stage_route.py check --final       # also fails on unconnected nets, unjustified vias (P1-P3), copper that joins nothing
                                              # and nets too long off the top layer; --board PATH checks that board instead

    python score.py work/2i.kicad_pcb OTHER.kicad_pcb --classes work/net_classes.json   # weighted score, and what changed and why

Everything is written to `work/`. The project board is only read.

## Steps
`setup -> 2a -> 2p -> 2b -> 2c -> 2d -> 2e -> 2h -> 2i -> 2f -> check`. Each step saves `work/<step>.kicad_pcb` and
`work/<step>_checks.json`, and exits 1 if a script or the router it runs fails, or if a must-fix check is not empty.
A step that exits 1 puts `work/board.kicad_pcb` back to what it was before the step, so it can be rerun; the result that
failed stays in `work/<step>.kicad_pcb` to look at. A board with arc tracks is refused: straighten them in KiCad first.

- `setup` also sets the board's via defaults to filled and capped, because the drops put vias in pads, and saves the net
  classes from the `.kicad_pro` beside the board to `work/net_classes.json`. A ground pad set to no zone connection (J105,
  J205: no room for spokes) gets a top-layer link to the nearest ground pad, since the pours do not reach it.
- `2p` routes the front-end (P2_FrontEnd) and second-stage (P4_Stage2) nets on the top layer with no vias, before `2b`'s
  links can take their way: drains first, then the second stage, then the rest of the front end, a router call each. A net
  is kept only if it joins and passes 2e's pass-1 judging; the rest is left for `2e`.
- `2d` adds no top-layer supply links of its own: `2b` has already joined supply pads up to 4 mm apart. It drops the supply
  vias, then lays one V+ and one V- zone on L5 from the router's split plane (`route_planes.py`, the "spine split"): GND
  stays the layer's background, and each rail's zone is grown round its own pads and vias and joined by corridors laid so
  the two never cross. Nothing is placed by coordinates. The battery and bias nets are routed after the zones, and
  `zone_integrity` fails the step if one cuts a zone. A rail pad the zone misses gets an L3 hop to its own zone, and 2d
  fails if V+ or V- is still open. `R6_SKIP_SUPPLY=1` leaves the zones out, for comparing signal
  routing between placements. `via_justify.py` judges V+, V- and the bias nets by 2b's limits.
- `2a`, `2p`, `2b` and `2e` leave alone only the nets `2h` will copy, and route everything else on both channels. `2h` then
  copies those nets, skipping any whose copy would collide with copper that is staying, and `2i` routes whatever the copy
  did not cover. When no net has a twin (channels laid out by hand), `2h` copies nothing and passes.
- `2e` and `2i` fail on a net left open. A net off the top layer longer than max(1.8 x its tree, tree + 12 mm) (P4 and P5
  nets, being low-impedance, get 2.2 x) does not stop the run: `check --final` reports it (a warning on P4/P5), so the
  placement can be judged on a whole board. Both remove the vias and tracks that end up joining nothing (a pad via whose L3
  join was made another way, a track stub with a free end); `2d` does the same for the battery and bias vias. A V+ or V-
  via its zone misses is left for `check --final` to report. A pair the via check flags is routed again on top, with only
  the inner-layer track between the two pieces lifted; kept if the new top link is within the pair's own limit and not squeezed
  or beside high-impedance copper. A net still open, or a front-end net joined off the top layer at
  over 1.5 x its tree, with L3 track of a lower-priority signal or bias net in its way, is joined again with those tracks
  lifted and they are routed again round it: once lifting the bias alone, once every lower-priority net in the way. Of the
  results where it joins and nothing is left open, squeezed or cut, the one with the lowest routing score (`score.py`) is
  kept, if the net was open or the score drops.
- With the net classes from setup, an unjustified via is must-fix on P1-P3, a warning on P4-P6 and not reported on any
  other net (power, battery and ground are low-impedance, so a via costs nothing there).
- `2f` puts a via in each loose test point where one fits and has the router reach the rest by a track, then clears
  anything left joining nothing on every net but the rails and ground.

## The router (KiCadRoutingTools)
Set `ROUTER_DIR` to a checkout of https://github.com/drandyhaas/KiCadRoutingTools (MIT). It does two jobs here:

1. Steps 2a, 2p, 2d, 2e, 2i and 2f call its `py_router/route.py`, and 2d also its `py_router/route_planes.py`. That needs its compiled extension (`python build_router.py` there).
2. With `ROUTER_DIR` set, every step also gets a second opinion from its DRC and connectivity check (`krt_checks.py`).
   This part needs only `scipy` and `Pillow`, not the compiled extension. Its DRC items are must-fix. Nets that only it
   calls unconnected are listed as `krt_unconnected_extra` and are for a human to settle in KiCad after refilling zones.
   Without KiCad's own refill (`KICAD_PYTHON`) the router estimates a pour's fill, and that estimate misses vias on a zone's
   edge that KiCad's fill reaches; so a zoned net whose every pad reaches its zone through copper by route6's count is
   listed apart, as `krt_zone_fill_only`, and left to KiCad's DRC.

Without `ROUTER_DIR` the second opinion is skipped and the step says so.

What route6 keeps for itself, because the router has no equivalent: the unjustified-via check, short same-net links
before general routing (the router joins a net's short gaps last), via-in-pad drops by rule, copying one channel to the
other, and the 4-to-6-layer conversion. `board.py` stays because the router's writer cannot remove a track by uuid or
leave the rest of the file untouched.

## Known open items
- A full run on that placement ends with every step clean but 8 nets not fully connected and 4 unjustified vias, so
  `check --final` exits 1. `REVIEW.md` weak spot 1 lists them. A full run takes about ten minutes.
