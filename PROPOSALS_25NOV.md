# route6: proposals (25 Nov 2026)

Three changes from KiCadRoutingTools, for your call. Nothing below is built yet. Please answer each one with yes, no or
changed, plus anything we should know.

## 1. Router v0.24.2 (from v0.24.1): adopt
Tried on shift127 and 83962f0, from setup to `check --final`.

| | v0.24.1 | v0.24.2 |
|---|---|---|
| Tests | 75 pass | 75 pass |
| shift127 2e | 114 s | 92 s |
| 83962f0 2e | 105 s | 80 s |
| shift127 final | 525 tracks, 113 vias, `/Bridge/SB` too long | same |
| 83962f0 final | 472 tracks, 118 vias, passes | same |

Counts are identical; the copper was not compared track by track. The release also fixes:
- KRT's own net propagation now treats a track end on a via's rim as joined (#1989). That is the case our `ends_in` got
  wrong.
- Stripping an unlocked twin no longer removes locked copper (#1960).

The Rust core is unchanged between the two tags. **Ask:** may `REVIEW.md`'s basis move to v0.24.2?

## 2. Guide corridors for the long bridge joins
The open must-fix items are long joins:
- `/Bridge/SB` on shift127 (34.3 mm against a 19.0 mm tree) and on aligned (34.5 mm);
- `/Bridge/SA` on 7bccb83 (46.6 mm).

On shift127 and aligned both L3 lifts give SB the same 30 mm and 4 vias, so lifting other nets doesn't help. The router
takes the detour because nothing tells it the short way is wanted.

`route.py --guide-corridor` reads a polyline on a User layer (`--guide-corridor-layer`, default `User.1`) and routes the
selected nets through its vertices as waypoints. The router's documentation says:
- it never makes a route fail: a waypoint it can't reach is dropped;
- it keeps a route on one layer where it can, so it adds no vias the direct route wouldn't need;
- endpoints and the net's topology are untouched;
- with the flag off, routing is byte-for-byte unchanged.

It steers every net in the call, so the call must route the guided net alone.

Plan: when a signal comes back over its limit in 2e, draw a corridor along its shortest legal path (the same search
`toplink` already does, run across layers), then reroute that net alone with `--guide-corridor`. The corridor is erased
before the board is saved. Keep the result only if it scores better by `score.py`'s tie rule.

**Ask:**
- Should corridors be generated like this, or should they be fixture data you draw per board? Generated ones follow the
  landscape when parts move; drawn ones encode your intent exactly.
- Is a too-long P2 signal the only trigger, or should any net over its limit be retried?

## 3. `check_weird.py` as a third opinion
The SB gap reached `krt_drc` because our own copper cleanup (`drop_dangling`, `checks.ends_in`) misjudged a joint. KRT's
`py_tools/check_weird.py` is a read-only copper hygiene scan. Its categories include:
- `dangling-end` and `kicad-dangling`, which match KiCad's `track_dangling`;
- `soft-joint`, the near-open joint behind the SB failure;
- `off-centre-via-end`;
- `orphan-island`, `unsupported-via` and `dangling-via`.

Proposal: run it after every step beside `krt_drc`. Report everything; make `soft-joint`, `dangling-end`,
`kicad-dangling` and `orphan-island` must-fix. I haven't run it on our boards, so the first step is a run over the five
fixtures to see what it reports today.

**Ask:** which categories should be must-fix, and which only warnings?

## Not proposed
- The router's other features don't apply to this board: differential pairs, length and time matching, BGA fanout and
  placement.
- `--ordering original` (rank order instead of MPS) and `--quick 1` on top-only multi-net calls are still on our list. Both
  change routing: `--quick 1` changes roughly one router call in 12 and would cut about two thirds of 2e's router time.
  Tell us if you want either tried.
