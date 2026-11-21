"""Runs the 6-layer routing one step at a time. Each step reads WORK, writes WORK, runs checks.py and (with --commit) commits.
    python stage_route.py setup  --from ../../../humbucker-preamp.kicad_pcb     # 1   6-layer conversion, rip-up
    python stage_route.py 2a     # high-impedance nets, top layer only, no vias          (router)
    python stage_route.py 2b     # neighbour links on top, every net class               (neighbour_links.py)
    python stage_route.py 2c     # a via in every ground pad                             (drops.py --ground)
    python stage_route.py 2d     # supply: drops, L5 zones, battery and bias nets         (drops.py --supply, supply5.py, router on In4.Cu and In2.Cu)
    python stage_route.py 2e     # remaining signals: top first, L3 only when needed     (router twice + length test)
    python stage_route.py 2h     # copy the routing to the other channel                 (mirror_route.py)
    python stage_route.py 2i     # what the copy did not cover: links, then the router   (neighbour_links.py, router as in 2a and 2e)
    python stage_route.py 2f     # test points: via in pad                               (drops.py --testpoints, router)
    python stage_route.py check  # report only; add --final to also fail on unconnected nets and unjustified vias
A step exits 1 if a script or the router it runs exits non-zero, or if a must-fix check is not empty. It then puts
work/board.kicad_pcb back to what it was before the step; the result that failed stays in work/<step>.kicad_pcb to look at.
Steps 2a, 2b and 2e leave alone the nets that 2h will make by copying, and the other channel's own nets: routed first they
are only in the copy's way. 2i routes them afterwards.
With ROUTER_DIR set, every step also gets a second opinion from the router's own DRC and connectivity check (krt_checks.py).
2g (tidy) is manual review for now. WORK defaults to ./work/board.kicad_pcb; every step keeps work/<step>.kicad_pcb as well.
The router is KiCadRoutingTools (not included): set ROUTER_DIR to its checkout. Steps 2b, 2c, 2h, check and setup do not need it."""
import sys, os, subprocess, shutil, argparse, json, math, time, re, contextlib
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import board as bd, checks, krt_checks, mirror_route, drops
WORK = os.environ.get('R6_WORK') or os.path.join(HERE, 'work'); BOARD = os.path.join(WORK, 'board.kicad_pcb')
PY = sys.executable
TOP_RATIO = 1.5; TOP_EXTRA = 3.0          # a net may leave the top layer only if its top-only route is longer than max(ratio*tree, tree+extra)

class StepFailed(Exception): pass
def held_file(): return os.path.join(WORK, 'locked_for_router.json')
def release_held():
    """Unlocks what a router call locked. The list is on disk, so a run that was killed mid-call is cleaned up by the next one."""
    if not os.path.exists(held_file()): return
    ours = json.load(open(held_file()))
    for f in (BOARD, BOARD + '.tmp'):
        if os.path.exists(f): U = bd.Board(f); U.unlock(ours); U.save()
    os.remove(held_file())

# ---- timing and counters: written to <step>_timing.json and summarised in one line per step; never changes what is routed ----
TIMING = dict(parts=[], counts={})
@contextlib.contextmanager
def timed(label, kind='own', **info):
    """Times one sub-step. kind: 'router' (a router call, start to finish), 'script' (another script as a subprocess),
    'check' (the checks at the end of a step) or 'own' (work done inside stage_route). The caller may add fields to the yielded dict."""
    rec = dict(label=label, kind=kind, **info); t0 = time.perf_counter()
    try: yield rec
    finally: rec['seconds'] = round(time.perf_counter() - t0, 3); TIMING['parts'].append(rec)
def count(key, n=1): TIMING['counts'][key] = TIMING['counts'].get(key, 0) + n
def timing_summary(step, total):
    by = {}
    for p in TIMING['parts']: by[p['kind']] = by.get(p['kind'], 0) + p['seconds']
    calls = [p for p in TIMING['parts'] if p['kind'] == 'router']; search = sum(p.get('router_search_s') or 0 for p in calls)
    rest = total - sum(by.values())
    return (f"[{step}] time {total:.0f} s: router {len(calls)} call(s) {by.get('router', 0):.0f} s (path search {search:.1f} s) | "
            f"other scripts {by.get('script', 0):.0f} s | own work {by.get('own', 0):.0f} s | checks {by.get('check', 0):.0f} s | untimed {rest:.0f} s")
def write_timing(step, total):
    out = dict(step=step, total_seconds=round(total, 3), summary=timing_summary(step, total), counts=TIMING['counts'], parts=TIMING['parts'])
    json.dump(out, open(os.path.join(WORK, f'{step}_timing.json'), 'w'), indent=1); print(out['summary'])
    if TIMING['counts']: print(f'[{step}] counts:', ', '.join(f'{k} {v}' for k, v in TIMING['counts'].items()))

def sh(cmd, check=True, ok=(0,), **kw):
    print('  $', ' '.join(str(c) for c in cmd))
    with timed(' '.join(os.path.basename(str(c)) for c in cmd[:2]), kind='script'): r = subprocess.run(cmd, **kw)
    if r.returncode not in ok and check: raise StepFailed(f"{' '.join(os.path.basename(str(c)) for c in cmd[:2])} exited {r.returncode}")
    return r
def router(nets, layers, extra=(), clearances=None, add_only=False):
    if not nets: print('  nothing to route on', *layers); return
    rd = os.environ.get('ROUTER_DIR')
    if not rd: raise StepFailed('set ROUTER_DIR to the KiCadRoutingTools checkout for this step')
    out = BOARD + '.tmp'
    cmd = [PY, '-u', 'py_router/route.py', BOARD, out, '--nets', *nets, '--layers', *layers, '--grid-step', '0.05', '--heuristic-weight', '1.0',
           '--same-net-pad-clearance', '0.15', '--fab-tier', 'standard', '--escalation', 'off',
           # stated, not left to the router: without a .kicad_pro beside the board it falls back to 0.25 / 0.2 / 0.2 mm, looser than rule 7 at the edge
           '--clearance', str(bd.CLEAR), '--board-edge-clearance', str(bd.EDGE), '--hole-to-hole-clearance', str(bd.HOLE_GAP),
           '--net-clearances', clearances or os.path.join(HERE, 'net_clearances.json'), '--keep-input-copper']
    cmd += ([] if '--direction-preference-cost' in extra else ['--direction-preference-cost', '0']) + list(extra)
    with timed('router ' + '+'.join(layers), kind='router', layers=list(layers), nets_given=len(nets)) as rec:
        release_held(); A = bd.Board(BOARD); print('  $', ' '.join(str(c) for c in cmd))
        if os.path.exists(out): os.remove(out)
        # the router never rips a net that has locked copper, whatever its rip switches say. A given net with locked copper is still routed, but the
        # router's rescue and rip passes leave it alone, so a given net is locked only where its copper is finished and it may only gain a link
        held = bd.Board(BOARD); ours = held.lock([x['uuid'] for x in held.segs + held.vias if add_only or x['net'] not in nets])
        json.dump(ours, open(held_file(), 'w')); held.save()
        try: rec.update(run_router(cmd, rd), earlier_pieces_locked=len(ours))
        finally: release_held()
        if rec.pop('returncode') != 0: raise StepFailed('py_router/route.py exited non-zero')
        if not os.path.exists(out): raise StepFailed('the router exited 0 but wrote no board')
        guard(A, out, set(nets)); os.replace(out, BOARD)
        B = bd.Board(BOARD); done = [n for n in nets if not checks.top_incomplete(B, n)]
        rec.update(nets_complete=len(done), tracks_added=len(B.segs) - len(A.segs), vias_added=len(B.vias) - len(A.vias))
    count('router calls'); count('nets given to the router', len(nets)); count('nets the router completed', len(done))
    shut_out = [n for n in nets if n not in done]
    if clearances and shut_out:       # a widened clearance also shuts a net out of its own pad when that pad sits inside it, so what stayed open gets one try without
        print('  still open with the widened clearances, retried with the standard ones:', shut_out); count('nets retried at standard clearances', len(shut_out))
        at = list(extra).index('--clearance') if '--clearance' in extra else None
        router(shut_out, layers, list(extra) if at is None else list(extra[:at]) + list(extra[at + 2:]), add_only=add_only)
ROUTER_LOG = (('router_wall_s', r'Wall time:\s*([0-9.]+)s', float, max), ('router_search_s', r'Search time:\s*([0-9.]+)s', float, max),
              ('iterations', r'Net total time: [0-9.]+s, (\d+) iterations', int, sum), ('main_loop_s', r'"main_loop_time_s": ([0-9.]+)', float, max))
ROUTER_COUNT = (('preexisting_rips', 'PRE-EXISTING rip'), ('ripup_retries_failed', 'Retry FAILED'), ('nets_ripped', 'Ripping '), ('not_connected_notes', 'NOT CONNECTED'))
def run_router(cmd, cwd):
    """Runs the router, passes its log through unchanged, and returns its own timing and rip-up numbers scraped from that log."""
    found = {k: [] for k, *_ in ROUTER_LOG}; n = {k: 0 for k, _ in ROUTER_COUNT}; lines = 0
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace')
    for line in p.stdout:
        sys.stdout.write(line); sys.stdout.flush(); lines += 1
        for k, pat, cast, _ in ROUTER_LOG:
            m = re.search(pat, line)
            if m: found[k].append(cast(m.group(1)))
        for k, needle in ROUTER_COUNT:
            if needle in line: n[k] += 1
    p.wait()
    out = {k: (agg(found[k]) if found[k] else None) for k, _, _, agg in ROUTER_LOG}; out.update(n); out.update(log_lines=lines, returncode=p.returncode)
    return out
def guard(A, out, routed):
    """The router may only add copper, and only for the nets it was given. Anything else fails the step; nothing is repaired."""
    B = bd.Board(out); now = {x['uuid']: x for x in B.segs + B.vias}; old = {x['uuid'] for x in A.segs + A.vias}
    gone = sorted({x['net'] for x in A.segs + A.vias if x['uuid'] not in now})
    changed = sorted({x['net'] for x in A.segs + A.vias if x['uuid'] in now and now[x['uuid']] != x})
    stray = sorted({x['net'] for x in B.segs + B.vias if x['uuid'] not in old and x['net'] not in routed})
    said = [f'{what} {nets}' for what, nets in (('removed earlier copper of', gone), ('changed earlier copper of', changed), ('added copper for nets it was not given:', stray)) if nets]
    if said: raise StepFailed(f"the router {'; '.join(said)}. Its board is kept as {out}")
def tree_len(pts):
    if len(pts) < 2: return 0.0
    inn = {0}; L = 0.0
    while len(inn) < len(pts):
        d, j = min((math.dist(pts[i], pts[j]), j) for i in inn for j in range(len(pts)) if j not in inn); inn.add(j); L += d
    return L
def finish(step, commit, final=False, failed=None):
    saved = [os.path.join(WORK, f'{step}.kicad_pcb'), os.path.join(WORK, f'{step}_checks.json')]
    shutil.copy(BOARD, saved[0])
    with timed('load board', kind='check'): B = bd.Board(BOARD)
    per = {}
    with timed('own checks', kind='check') as rec: R = checks.report(B, justify=final or step not in ('setup', '2a'), timing=per); rec['per_check_s'] = per
    if krt_checks.configured():
        with timed("router's checker (second opinion)", kind='check'): R.update(krt_checks.report(BOARD))
        ours = {u['net'] for u in R['unconnected']}
        R['krt_unconnected_extra'] = [n for n in R.pop('krt_unconnected') if n not in ours]
        print(f"  second opinion: {len(R['krt_drc'])} DRC items | nets only it calls unconnected: {R['krt_unconnected_extra'] or 'none'}")
    else: print('  second opinion skipped: ROUTER_DIR is not set')
    json.dump(R, open(saved[1], 'w'), indent=1)
    bad = checks.must_fix(R, final)
    print(f'[{step}] tracks {R["stats"]["tracks"]} vias {R["stats"]["vias"]} unconnected nets {len(R["unconnected"])} unjustified {len(R.get("unjustified_vias", []))} | must-fix: {bad or ("step failed: " + failed if failed else "none")}')
    # work/ is ignored, hence -f; the pathspec keeps anything else that happens to be staged out of the commit
    if commit and not bad and sh(['git', 'add', '-f', '--', *saved], check=False, cwd=HERE).returncode == 0:
        sh(['git', 'commit', '-q', '-m', f'route6 step {step}', '--', *saved], check=False, cwd=HERE)
    return 1 if bad else 0

def open_hz(B): return [n for n in B.nets if bd.is_hz(n) and checks.unconnected(B, [n])]
def open_signals(B): return [n for n in B.nets if n not in bd.GROUND and not bd.is_supply(n) and not bd.is_hz(n) and checks.top_incomplete(B, n)]
def route_hz(nets): router(nets, ['F.Cu'], ['--via-cost', '100000', '--track-width', '0.2'])
for _switch in ('KICAD_RIP_PREEXISTING', 'KICAD_FINALIZE_RIP', 'KICAD_RECONCILE_RIP_ESCALATION'): os.environ.setdefault(_switch, '0')   # the router must never rip copper an earlier step placed; each of the three grants that on its own
L3_RATIO = 1.8; L3_EXTRA = 12.0; PINCH = 0.25; HZ_NEAR = 1.0; HZ_RUN = 3.0; OWN_PAD = 2.5     # a top route is rejected if it squeezes between two foreign pads, or runs more than HZ_RUN mm inside the soft keep-away of a high-impedance net
def hz_run(B, net, since):
    """mm of the net's top-layer track newer than `since` that lies within HZ_NEAR of high-impedance copper.
    The approach to its own pads does not count: a servo net has to end beside the servo inputs."""
    from shapely.geometry import LineString, Point; from shapely.ops import unary_union
    mine = [LineString([(x['x1'], x['y1']), (x['x2'], x['y2'])]) for x in B.segs if x['net'] == net and x['uuid'] not in since and x['layer'] == 'F.Cu']
    if not mine: return 0.0
    near = unary_union([g for n, g, k, o in B.copper('F.Cu') if bd.is_hz(n)]).buffer(HZ_NEAR)
    own = unary_union([Point(p['x'], p['y']).buffer(OWN_PAD) for p in B.pads if p['net'] == net])
    return sum(g.intersection(near).difference(own).length for g in mine)
def squeezed(B, net, since):
    """Foreign pads the net's top-layer track newer than `since` passes within PINCH mm of; two or more is a squeeze"""
    from shapely.geometry import LineString
    mine = [LineString([(x['x1'], x['y1']), (x['x2'], x['y2'])]) for x in B.segs if x['net'] == net and x['uuid'] not in since and x['layer'] == 'F.Cu']
    wid = max([x['w'] for x in B.segs if x['net'] == net and x['uuid'] not in since] or [0.2])
    own_refs = {p['ref'] for p in B.pads if p['net'] == net}                    # the other pad of a part the net ends on is not a squeeze
    pinch = [checks.label(p) for p in B.pads if p['net'] != net and p['ref'] not in own_refs and 'F.Cu' in p['layers'] and mine and min(g.distance(B.pad_geom(p)) for g in mine) - wid / 2 < PINCH]
    under = {r for r in {x.split('.')[0] for x in pinch} if len(B.fps[r]['pads']) == 2 and sum(x.split('.')[0] == r for x in pinch) == 2}   # passing under a two-pad part between its pads is allowed
    return [x for x in pinch if x.split('.')[0] not in under]
def wanders(B, net):
    """(too long, length, shortest tree) of a net that was allowed off the top layer"""
    t = tree_len([(p['x'], p['y']) for p in B.pads if p['net'] == net and not checks.is_tp(p)])
    L = sum(math.dist((x['x1'], x['y1']), (x['x2'], x['y2'])) for x in B.segs if x['net'] == net)
    return L > max(L3_RATIO * t, t + L3_EXTRA), L, t
def route_signals(nets, step='2e'):
    """Returns (nets still open, nets routed too long): what the passes could not put right."""
    A = bd.Board(BOARD); before = {x['uuid'] for x in A.segs}; start = before | {x['uuid'] for x in A.vias}; count(f'{step} pass 1 nets (top only)', len(nets))
    router(nets, ['F.Cu'], ['--via-cost', '100000'])                       # pass 1: top only; nets that do not fit stay open
    t_judge = time.perf_counter()
    B = bd.Board(BOARD); again = []; redo = []
    for n in nets:
        pts = [(p['x'], p['y']) for p in B.pads if p['net'] == n and not checks.is_tp(p)]; t = tree_len(pts)
        L = sum(math.dist((x['x1'], x['y1']), (x['x2'], x['y2'])) for x in B.segs if x['net'] == n)
        pinch = squeezed(B, n, before)
        near_hz = hz_run(B, n, before)
        if L > max(TOP_RATIO * t, t + TOP_EXTRA): again.append(n); redo.append(n); count(f'{step} rejected: too long on top'); print(f'  {n}: too long on top ({L:.0f} mm for a {t:.0f} mm tree)')
        elif len(pinch) >= 2: again.append(n); redo.append(n); count(f'{step} rejected: squeezed'); print(f'  {n}: squeezed on top, under {PINCH} mm from {pinch}')
        elif near_hz > HZ_RUN: again.append(n); redo.append(n); count(f'{step} rejected: beside high-impedance copper'); print(f'  {n}: runs {near_hz:.1f} mm within {HZ_NEAR} mm of high-impedance copper')
        elif checks.top_incomplete(B, n): again.append(n)                                  # partly done on top: keep what connected, L3 only for the missing links
    B.remove([x['uuid'] for x in B.segs if x['net'] in redo and x['uuid'] not in before])
    # pass 2: a via IN a pad for each top-layer piece (the router only puts vias in open space), then join those vias on L3 with no new vias
    TIMING['parts'].append(dict(label=f'{step} judge the top-only routes', kind='own', seconds=round(time.perf_counter() - t_judge, 3)))
    with timed(f'{step} pass 2 pad vias', vias=0) as rec: added, failed = drops.run(B, signals=again, log=lambda *a: None); B.save(BOARD); rec.update(vias=len(added), blocked=len(failed))
    count(f'{step} pass 2 nets (pad vias + L3)', len(again)); count(f'{step} pad vias', len(added)); count(f'{step} pieces with no legal pad via', len(failed))
    print(f'  pass 2 (pad vias + L3): {again} | {len(added)} pad vias, {len(failed)} pieces with no legal pad via')
    mark = {x['uuid'] for x in B.segs}
    if again: router(again, ['In2.Cu'], ['--via-cost', '100000'], add_only=True)   # keep the pad vias this pass just placed
    B = bd.Board(BOARD); left = [n for n in again if checks.top_incomplete(B, n)]
    for n in again:                                                           # an L3-only join that had to wander round earlier nets is thrown away: pass 3 may cross with a via instead
        if n in left: continue
        far, L, t = wanders(B, n)
        if far:
            B.remove([x['uuid'] for x in B.segs if x['net'] == n and x['uuid'] not in mark]); left.append(n); count(f'{step} L3-only joins that wandered'); print(f'  {n}: L3-only join wandered ({L:.0f} mm for a {t:.0f} mm tree), redone in pass 3')
    B.save(BOARD)
    print('  pass 3 (router may add its own vias):', left)
    held = {x['uuid'] for x in B.segs + B.vias}
    count(f'{step} pass 3 nets (router vias allowed)', len(left))
    def pass3(some):                                                          # pass 3 keeps wider gaps so it cannot bring back the squeezes pass 1 was rejected for
        nc = json.load(open(os.path.join(HERE, 'net_clearances.json'))); wide = os.path.join(WORK, f'{step}_pass3_clearances.json')
        json.dump({k: (HZ_NEAR if bd.is_hz(k) else v) for k, v in nc.items()}, open(wide, 'w'))
        router(some, ['F.Cu', 'In2.Cu'], ['--layer-costs', '1.0', '1.2', '--via-cost', '150', '--clearance', '0.3'], clearances=wide)
    if left: pass3(left)
    # in a shared call the router's own ordering decides who gets the ground; a net that came out open or wandering gets a call to itself
    B = bd.Board(BOARD); state = lambda B, n: (not checks.top_incomplete(B, n) and not wanders(B, n)[0], not checks.top_incomplete(B, n), -wanders(B, n)[1])
    alone = sorted([n for n in left if not state(B, n)[0]], key=lambda n: wanders(B, n)[2])
    def solo(n, route, since):
        B = bd.Board(BOARD); B.remove([x['uuid'] for x in B.segs + B.vias if x['net'] == n and x['uuid'] not in since]); B.save(BOARD); route([n]); return bd.Board(BOARD)
    for n in alone:
        B = bd.Board(BOARD); was = state(B, n); shutil.copy(BOARD, BOARD + '.shared')
        B = solo(n, pass3, held); now = state(B, n); far, L, t = wanders(B, n)
        if now < was: shutil.copy(BOARD + '.shared', BOARD)
        count(f'{step} pass 3 nets routed again alone'); print(f"  {n} alone: {'joined' if now[1] else 'open'}, {L:.0f} mm for a {t:.0f} mm tree" + ('; worse than in the shared call, which is kept' if now < was else ''))
        if max(now, was)[0]: continue
        # the wider gap is only ever given up as a fallback, and the squeeze test it stood in for is applied instead; the net starts again from
        # nothing, as its earlier pieces and pad vias were placed for the wider gap and boxed it in at it
        shutil.copy(BOARD, BOARD + '.shared')
        B = solo(n, lambda some: router(some, ['F.Cu', 'In2.Cu'], ['--layer-costs', '1.0', '1.2', '--via-cost', '150']), start)
        ok, (far, L, t), pinch = state(B, n)[0], wanders(B, n), squeezed(B, n, start)
        if not ok or len(pinch) >= 2: shutil.copy(BOARD + '.shared', BOARD)
        count(f'{step} pass 3 nets routed alone at standard clearances'); count(f'{step} pass 3 standard-clearance routes kept', int(ok and len(pinch) < 2))
        print(f"  {n} alone at standard clearances: {'joined' if state(B, n)[1] else 'open'}, {L:.0f} mm for a {t:.0f} mm tree"
              + ('' if ok and len(pinch) < 2 else f"; not kept ({'squeezed, under ' + str(PINCH) + ' mm from ' + str(pinch) if ok else 'open or too long'})"))
    if os.path.exists(BOARD + '.shared'): os.remove(BOARD + '.shared')
    B = bd.Board(BOARD); tight = [n for n in left if len(squeezed(B, n, held)) >= 2]      # the shared call's own retry at standard clearances answers to the same test
    if tight:
        B.remove([x['uuid'] for x in B.segs + B.vias if x['net'] in tight and x['uuid'] not in held]); B.save(BOARD)
        count(f'{step} pass 3 routes dropped: squeezed', len(tight)); print(f'  pass 3 routes dropped, squeezed between foreign pads: {tight}')
    B = bd.Board(BOARD); crept = [n for n in left if hz_run(B, n, held) > HZ_RUN]         # the retry at standard clearances is free to hug high-impedance copper
    if crept:
        B.remove([x['uuid'] for x in B.segs + B.vias if x['net'] in crept and x['uuid'] not in held]); B.save(BOARD)
        count(f'{step} pass 3 routes dropped: beside high-impedance copper', len(crept)); print(f'  pass 3 routes dropped, beside high-impedance copper: {crept}')
    B = bd.Board(BOARD); left = [n for n in again if checks.top_incomplete(B, n)]         # pass 4: a pad that was blocked in pass 2 may be free now
    if left:
        with timed(f'{step} pass 4 pad vias') as rec: added, failed = drops.run(B, signals=left, log=lambda *a: None); B.save(BOARD); rec.update(vias=len(added), blocked=len(failed))
        count(f'{step} pass 4 nets', len(left)); count(f'{step} pad vias', len(added))
        print(f'  pass 4 (pad vias again + L3): {left} | {len(added)} pad vias, {len(failed)} still blocked')
        router(left, ['In2.Cu'], ['--via-cost', '100000'])
    B = bd.Board(BOARD); still_open = [n for n in nets if checks.top_incomplete(B, n)]; long = {n: wanders(B, n) for n in nets if n not in still_open and wanders(B, n)[0]}
    for n in still_open: print(f'  {n}: still open')
    for n, (_, L, t) in long.items(): print(f'  {n}: {L:.0f} mm for a {t:.0f} mm tree, over the limit for a net off the top layer')
    count(f'{step} nets left open', len(still_open)); count(f'{step} nets left too long', len(long)); return still_open, sorted(long)

def run_step(s, src):
    links = [PY, os.path.join(HERE, 'neighbour_links.py'), BOARD, BOARD, '--json', os.path.join(WORK, f'{s}_links.json')]
    if s == 'setup':
        if not src: raise SystemExit('--from BOARD needed')
        sh([PY, os.path.join(HERE, 'setup6.py'), src, BOARD])
    elif s == '2a':
        B = bd.Board(BOARD); later = mirror_route.waits_for_copy(B); route_hz([n for n in open_hz(B) if n not in later])
    elif s == '2b':
        B = bd.Board(BOARD); later = mirror_route.waits_for_copy(B); sh(links + ['--nets', *[n for n in B.nets if n not in later]])
    elif s == '2c': sh([PY, os.path.join(HERE, 'drops.py'), BOARD, BOARD, '--ground', '--json', os.path.join(WORK, '2c_drops.json')])
    elif s == '2d':
        sh([PY, os.path.join(HERE, 'drops.py'), BOARD, BOARD, '--supply', '--json', os.path.join(WORK, '2d_drops.json')])
        nc = os.path.join(WORK, '2d_net_clearances.json')
        sh([PY, os.path.join(HERE, 'supply5.py'), BOARD, BOARD, '--nc', nc])       # V+/V- fingers (zones + centre tracks), stubs, the one L3 crossing
        B = bd.Board(BOARD); bat = [n for n in B.nets if 'BAT' in n]; bias = [n for n in B.nets if n in bd.BIAS]
        router(bat, ['In4.Cu'], ['--via-cost', '100000', '--track-width', '0.5'])
        # bias nets: L3 runs east-west, L5 north-south (the router alternates by position in --layers); BIAS_L3_COST trades L3 length against hop vias
        router(bias, ['In2.Cu', 'In4.Cu'], ['--layer-costs', os.environ.get('BIAS_L3_COST', '2.0'), '1.0', '--via-cost', '40', '--track-width', '0.4',
                                            '--direction-preference-cost', '1000'], clearances=nc)
    elif s == '2e':
        B = bd.Board(BOARD); later = mirror_route.waits_for_copy(B); still_open, long = route_signals([n for n in open_signals(B) if n not in later])
        # every one of these nets has now been attempted, so one left open or wandering is this step's failure, not something for the final check to find
        if still_open or long: raise StepFailed(f'2e left {len(still_open)} net(s) open {still_open} and {len(long)} too long {long}')
    elif s == '2h': sh([PY, os.path.join(HERE, 'mirror_route.py'), BOARD, BOARD, '--json', os.path.join(WORK, '2h_mirror.json')])
    elif s == '2i':
        sh(links); route_hz(open_hz(bd.Board(BOARD))); _, long = route_signals(open_signals(bd.Board(BOARD)), step='2i')
        # 2i is the last routing step for everything but the test points, which 2f joins
        B = bd.Board(BOARD); still_open = [n for n in B.nets if checks.top_incomplete(B, n)]
        if still_open or long: raise StepFailed(f'2i left {len(still_open)} net(s) open {still_open} and {len(long)} too long {long}')
    elif s == '2f':
        # a test point with no room for a via is not a failure here: the router reaches it by a track instead
        sh([PY, os.path.join(HERE, 'drops.py'), BOARD, BOARD, '--testpoints', '--json', os.path.join(WORK, '2f_drops.json')], ok=(0, drops.NO_ROOM))
        router(checks.loose_testpoint_nets(bd.Board(BOARD)), ['F.Cu', 'In2.Cu'], ['--layer-costs', '1.0', '1.2', '--via-cost', '150'], add_only=True)
    elif s != 'check': raise SystemExit('unknown step ' + s)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('step'); ap.add_argument('--from', dest='src'); ap.add_argument('--commit', action='store_true')
    ap.add_argument('--final', action='store_true'); a = ap.parse_args()
    os.makedirs(WORK, exist_ok=True); failed = None; release_held()
    before = BOARD + '.before'; had_board = os.path.exists(BOARD)
    if had_board: shutil.copy(BOARD, before)
    t0 = time.perf_counter()
    try: run_step(a.step, a.src)
    except StepFailed as e: failed = str(e); print(f'[{a.step}] step failed: {e}')
    if failed and not os.path.exists(BOARD): sys.exit(1)
    code = finish(a.step, a.commit and not failed, a.final, failed) or int(bool(failed))
    write_timing(a.step, time.perf_counter() - t0)
    if had_board:
        if code and a.step != 'check':
            os.replace(before, BOARD); print(f'[{a.step}] the board is back to what it was before this step; the result that failed is work/{a.step}.kicad_pcb')
        else: os.remove(before)
    sys.exit(code)
if __name__ == '__main__': main()
