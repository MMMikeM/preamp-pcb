# Answers to PROPOSALS_25NOV.md (25 Nov 2026)

## 0. Before anything else: zone check now counts the net's own tracks (committed here)
`checks.zone_integrity` judged a plane only by its fill pieces. KiCad joins fill pieces through the net's own tracks, so
a split rejoined by one short track still failed the check (every later step stayed blocked). This commit adds the
net's own segments on that layer to the fill before counting pieces (`checks.py`, 2 lines). Tests: 73 pass, 2 skipped.
- `run_sh2` 2h board (1.27 mm shift): V- in 2 pieces -> still reported (no joining track yet).
- Same board with one 0.25 mm V- track on L5 joining the pieces: was reported, now passes. KiCad: 0 unconnected.

Known gap, not fixed: a supply via that is outside every zone outline of its net is not judged at all. On the tightened
block board (`a0727dd` placement) the bridge V+ via at R210 (165.95, 107.58) sat outside the V+ outline; `check --final`
passed and KiCad reported it unconnected. Suggest: any via or pad of a plane net that is neither in a fill piece nor joined
by its own copper to one is must-fix.

## 1. Router v0.24.2: yes
Our run on the newest placement (jumpers across the top corners): every net's length and via count identical to
v0.24.1; 343 s against 413 s. Move `REVIEW.md`'s basis.

## 2. Guide corridors: yes, generated
- Generated from the shortest legal path, not drawn: the author moves parts often, drawn corridors would go stale.
- Trigger: any P1-P3 net over its limit (P1/P3 too, not only P2). Today's largest detour is `/Neck/SA` at 42.7 mm and
  3 vias on the newest placement (bridge SA 23.0).
- Keep or drop by `score.py` with the run's `net_classes.json`. (Our scores before 25 Nov afternoon used the
  `.kicad_pro` for `--classes` by mistake; the help text could say it wants `net_classes.json`, and fail on a `.kicad_pro`.)

## 3. `check_weird.py`: yes
Must-fix: `soft-joint`, `dangling-end`, `kicad-dangling` (the PB stubs on 23 and 24 Nov were these). Warnings:
`orphan-island` (fill fragments can be legitimate), `off-centre-via-end`, `unsupported-via`, `dangling-via`.

## 4. Copy step (2h) and a one-sided change
Rotating only Q101 (neck) moved the bridge result too (+15 on the bridge score, no bridge part moved), because 2h
mirrors the neck routing onto a bridge that no longer mirrors it there. Worth a line in the 2h report: which nets were
copied and which fell back to routing.

## Not proposed: `--ordering original` and `--quick 1`
Not now.
