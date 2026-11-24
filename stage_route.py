"""Runs the 6-layer routing one step at a time. Each step reads WORK, writes WORK, runs checks.py and (with --commit) commits.
    python stage_route.py setup  --from ../../../humbucker-preamp.kicad_pcb     # 1   6-layer conversion, rip-up
    python stage_route.py 2a     # high-impedance nets, top layer only, no vias          (router)
    python stage_route.py 2p     # front-end and second-stage nets, top only, no vias     (router, a call per group)
    python stage_route.py 2b     # neighbour links on top, every net class               (neighbour_links.py)
    python stage_route.py 2c     # a via in every ground pad                             (drops.py --ground)
    python stage_route.py 2d     # supply: drops, L5 zones, battery and bias nets         (drops.py --supply, the router's split plane, router on In4.Cu and In2.Cu)
    python stage_route.py 2e     # remaining signals: top first, L3 only when needed     (router twice + length test)
    python stage_route.py 2h     # copy the routing to the other channel                 (mirror_route.py)
    python stage_route.py 2i     # what the copy did not cover: links, then the router   (neighbour_links.py, router as in 2a and 2e)
    python stage_route.py 2f     # test points: via in pad                               (drops.py --testpoints, router)
    python stage_route.py check  # report only; add --final to also fail on unconnected nets, unjustified vias and nets too long
                                 # off the top layer; --board PATH checks that board instead of the work one
A step exits 1 if a script or the router it runs exits non-zero, or if a must-fix check is not empty. It then puts
work/board.kicad_pcb back to what it was before the step; the result that failed stays in work/<step>.kicad_pcb to look at.
Steps 2a, 2p, 2b and 2e leave alone the nets that 2h will make by copying; everything else on both channels is routed in
its class's step. 2i routes what the copy did not cover.
With ROUTER_DIR set, every step also gets a second opinion from the router's own DRC and connectivity check (krt_checks.py).
2g (tidy) is manual review for now. WORK defaults to ./work/board.kicad_pcb; every step keeps work/<step>.kicad_pcb as well.
The router is KiCadRoutingTools (not included): set ROUTER_DIR to its checkout. Steps 2b, 2c, 2h, check and setup do not need it."""
import sys, os, subprocess, shutil, argparse, json, math, time, re, contextlib, fnmatch, heapq, itertools, signal
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import board as bd, toplink as tl, checks, krt_checks, mirror_route, drops, via_justify, hand_access
from shapely.geometry import LineString, Point, Polygon, box
from shapely.strtree import STRtree
from shapely.ops import unary_union
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

# a process that dies without a traceback was killed from outside it; on Windows the exit code is the NTSTATUS of the crash
NTSTATUS = {0xC0000017: 'ran out of memory', 0xC0000005: 'crashed (access violation)', 0xC00000FD: 'crashed (stack overflow)', 0xC0000409: 'crashed (stack buffer overrun)'}
def how_it_ended(name, code):
    if code < 0:
        sig = signal.Signals(-code).name if -code in signal.valid_signals() else f'signal {-code}'
        return f"{name} was killed by {sig}" + (', probably out of memory' if sig == 'SIGKILL' else '') + ': not a routing result'
    if code & 0xFFFFFFFF in NTSTATUS: return f'{name} {NTSTATUS[code & 0xFFFFFFFF]}, exit {code & 0xFFFFFFFF:#x}: not a routing result'
    return f'{name} exited {code}'
def sh(cmd, check=True, ok=(0,), **kw):
    print('  $', ' '.join(str(c) for c in cmd))
    name = ' '.join(os.path.basename(str(c)) for c in cmd[:2])
    with timed(name, kind='script'): r = subprocess.run(cmd, **kw)
    if r.returncode not in ok and check: raise StepFailed(how_it_ended(name, r.returncode))
    return r
def router_dir():
    rd = os.environ.get('ROUTER_DIR')
    if not rd: raise StepFailed('set ROUTER_DIR to the KiCadRoutingTools checkout for this step')
    return rd
def split_supply(layer='In4.Cu'):
    """V+ and V- zones on L5 from the router's split plane (route_planes.py, the "spine split"): GND is the layer's background, and
    each rail gets one zone grown round its pads and vias and joined by corridors laid so the two rails never cross. Nothing is placed
    by coordinates, so the zones follow the placement. Only the two zones are kept: the tool's own GND pieces would replace setup's pour."""
    out = BOARD + '.tmp'; A = bd.Board(BOARD)
    sh([PY, 'py_router/route_planes.py', BOARD, out, '--nets', 'GND|' + '|'.join(sorted(bd.RAILS)), '--plane-layers', layer, '--skip-existing-zones',
        '--zone-clearance', str(bd.CLEAR), '--min-thickness', '0.25', '--no-thermal-vias', '--clearance', str(bd.CLEAR), '--board-edge-clearance', str(bd.EDGE),
        '--hole-to-hole-clearance', str(bd.HOLE_GAP), '--net-clearances', bd.NET_CLEARANCES], cwd=router_dir())
    guard(A, out, set())
    zones = bd.Board(out).zone_blocks(bd.RAILS); os.remove(out)
    made = {n for n in bd.RAILS if any(f'(net "{n}")' in z for z in zones)}
    if made != bd.RAILS: raise StepFailed(f'the split plane made no zone for {sorted(bd.RAILS - made)}')
    A.add(zones); A.save(BOARD); count('supply zones', len(zones))
HOP_WIDTH = 0.4
def hop_to_zone(layer='In2.Cu'):
    """Rule 6's L3 hop. A rail pad whose via the zone does not reach (its L5 stub would have to cross the other rail's zone) is joined by
    one track on L3, with no new via, from that via to the nearest via of its own net that the zone does reach."""
    B = bd.Board(BOARD); hops = []
    for net in sorted(bd.RAILS):
        zones = [Polygon(z['pts']) for z in B.zones if z['net'] == net and len(z['pts']) > 2]
        landed = [v for v in B.vias if v['net'] == net and any(z.intersects(B.via_geom(v)) for z in zones)]
        for g in checks.pad_groups(B, net):
            mine = [v for v in B.vias if v['net'] == net and any(B.pad_geom(p).intersects(B.via_geom(v)) for p in g)]
            if not mine or any(v in landed for v in mine): continue
            comps = tl.components(B, net, layer); src = next(c for c in comps if any(v in mine for v in c['vias']))
            homes = sorted((tl.gap(src, c)[0], i) for i, c in enumerate(comps) if any(v in landed for v in c['vias']))
            found = next((r for _, i in homes[:5] for r in [tl.top_path(B, net, src, comps[i], HOP_WIDTH, layer=layer)] if r), None)
            label = '+'.join(checks.label(p) for p in g)
            if not found: print(f'  {net} {label}: no L3 hop to its zone'); continue
            pts = found[1]; B.add([B.seg_text(*pts[k], *pts[k + 1], HOP_WIDTH, layer, net) for k in range(len(pts) - 1)]); B.save(BOARD)
            hops.append(label); count('rail pads joined by an L3 hop'); print(f'  {net} {label}: the zone misses its via; joined by an L3 hop of {found[0]:.1f} mm')
    return hops
def router(nets, layers, extra=(), clearances=None, add_only=False):
    """Returns the given nets the router left open"""
    if not nets: print('  nothing to route on', *layers); return []
    rd = router_dir()
    out = BOARD + '.tmp'
    cmd = [PY, '-u', 'py_router/route.py', BOARD, out, '--nets', *nets, '--layers', *layers, '--grid-step', '0.05', '--heuristic-weight', '1.0',
           '--same-net-pad-clearance', '0.15', '--fab-tier', 'standard', '--escalation', 'off',
           # stated, not left to the router: without a .kicad_pro beside the board it falls back to 0.25 / 0.2 / 0.2 mm, looser than rule 7 at the edge
           '--clearance', str(bd.CLEAR), '--board-edge-clearance', str(bd.EDGE), '--hole-to-hole-clearance', str(bd.HOLE_GAP),
           '--net-clearances', clearances or bd.NET_CLEARANCES, '--keep-input-copper', '--direction-preference-cost', '0', *extra]
    with timed('router ' + '+'.join(layers), kind='router', layers=list(layers), nets_given=len(nets)) as rec:
        release_held(); A = bd.Board(BOARD); print('  $', ' '.join(str(c) for c in cmd))
        if os.path.exists(out): os.remove(out)
        # the router never rips a net that has locked copper, whatever its rip switches say. A given net with locked copper is still routed, but the
        # router's rescue and rip passes leave it alone, so a given net is locked only where its copper is finished and it may only gain a link
        held = bd.Board(BOARD); ours = held.lock([x['uuid'] for x in held.segs + held.vias if add_only or x['net'] not in nets])
        json.dump(ours, open(held_file(), 'w')); held.save()
        try: rec.update(run_router(cmd, rd), earlier_pieces_locked=len(ours))
        finally: release_held()
        code = rec.pop('returncode')
        if code != 0: raise StepFailed(how_it_ended('py_router/route.py', code))
        if not os.path.exists(out): raise StepFailed('the router exited 0 but wrote no board')
        guard(A, out, set(nets)); os.replace(out, BOARD)
        B = bd.Board(BOARD); done = [n for n in nets if not checks.top_incomplete(B, n)]
        rec.update(nets_complete=len(done), tracks_added=len(B.segs) - len(A.segs), vias_added=len(B.vias) - len(A.vias))
    count('router calls'); count('nets given to the router', len(nets)); count('nets the router completed', len(done))
    return [n for n in nets if n not in done]
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
def classes_beside(board):
    """{class: [net patterns]} from the .kicad_pro beside the board, or None"""
    pro = os.path.splitext(board)[0] + '.kicad_pro'
    if not os.path.exists(pro): return None
    cl = {}
    for p in json.load(open(pro)).get('net_settings', {}).get('netclass_patterns') or []: cl.setdefault(p['netclass'], []).append(p['pattern'])
    return cl
def leaves_top(B, net): return any(v['net'] == net for v in B.vias) or any(s['net'] == net and s['layer'] != 'F.Cu' for s in B.segs)
def finish(step, commit, final=False, failed=None):
    saved = [os.path.join(WORK, f'{step}.kicad_pcb'), os.path.join(WORK, f'{step}_checks.json')]
    shutil.copy(BOARD, saved[0])
    with timed('load board', kind='check'): B = bd.Board(BOARD)
    per = {}
    cl = classes_beside(BOARD) or (json.load(open(os.path.join(WORK, 'net_classes.json'))) if os.path.exists(os.path.join(WORK, 'net_classes.json')) else None)
    with timed('own checks', kind='check') as rec: R = checks.report(B, justify=final or step not in ('setup', '2a'), timing=per, classes=cl); rec['per_check_s'] = per
    # a joined net over its off-top limit is reported, not a stop: the run goes on, so the placement can be judged on a whole board
    # on P4 and P5, low-impedance, it is a warning, as an unjustified via is there
    long = [dict(net=n, length=round(L, 1), tree=round(t, 1)) for n in B.nets if bd.is_signal(n) and leaves_top(B, n) and not checks.top_incomplete(B, n)
            for far, L, t in [too_long_to_pass(B, n, cl or {})] if far]
    low_z = lambda x: (checks.priority(x['net'], cl) or 0) in (4, 5)
    R['too_long'] = [x for x in long if not low_z(x)]; R['too_long_warnings'] = [x for x in long if low_z(x)]
    if krt_checks.configured():
        with timed("router's checker (second opinion)", kind='check'): R.update(krt_checks.report(BOARD))
        # without KiCad's own refill the router estimates a pour's fill, and that estimate misses vias on a zone's edge that KiCad's fill
        # reaches; a zoned net whose every pad reaches its zone through copper here is left to KiCad's DRC
        ours = {u['net'] for u in R['unconnected']}; zoned = {z['net'] for z in B.zones}; theirs = [n for n in R.pop('krt_unconnected') if n not in ours]
        R['krt_unconnected_extra'] = [n for n in theirs if n not in zoned]; R['krt_zone_fill_only'] = [n for n in theirs if n in zoned]
        print(f"  second opinion: {len(R['krt_drc'])} DRC items | nets only it calls unconnected: {R['krt_unconnected_extra'] or 'none'}"
              + (f" (and {R['krt_zone_fill_only']}, by its estimate of the pour only)" if R['krt_zone_fill_only'] else ''))
    else: print('  second opinion skipped: ROUTER_DIR is not set')
    json.dump(R, open(saved[1], 'w'), indent=1)
    bad = checks.must_fix(R, final)
    print(f'[{step}] tracks {R["stats"]["tracks"]} vias {R["stats"]["vias"]} unconnected nets {len(R["unconnected"])} unjustified {len(R.get("unjustified_vias", []))} (+{len(R.get("unjustified_warnings", []))} warnings) too long {len(R.get("too_long", []))} (+{len(R.get("too_long_warnings", []))} warnings) | must-fix: {bad or ("step failed: " + failed if failed else "none")}')
    # work/ is ignored, hence -f; the pathspec keeps anything else that happens to be staged out of the commit
    if commit and not bad and sh(['git', 'add', '-f', '--', *saved], check=False, cwd=HERE).returncode == 0:
        sh(['git', 'commit', '-q', '-m', f'route6 step {step}', '--', *saved], check=False, cwd=HERE)
    return 1 if bad else 0

def open_hz(B): return [n for n in B.nets if bd.is_hz(n) and checks.unconnected(B, [n])]
def open_signals(B): return [n for n in B.nets if bd.is_signal(n) and checks.top_incomplete(B, n)]
HZ_ARGS = ['--via-cost', '100000', '--track-width', '0.2']
def channel(net): return net.split('/')[1] if net.count('/') > 1 else None
def route_hz(nets):
    """Top only, no vias, so the order the router picks can be fatal: a net routed first along its shortest path may close the only
    corridor another one had. A net left open is routed again on its own before the others of its channel that the call routed, and that
    order is kept if every one of them joins within the top-layer length limit; otherwise the first attempt stands."""
    before = copper_ids(bd.Board(BOARD)); shut_out = router(nets, ['F.Cu'], HZ_ARGS)
    for n in shut_out:
        mates = [m for m in nets if m not in shut_out and channel(m) == channel(n)]
        if not mates: continue
        shutil.copy(BOARD, BOARD + '.hz'); drop_new(bd.Board(BOARD), mates + [n], before)
        try: router([n], ['F.Cu'], HZ_ARGS); router(mates, ['F.Cu'], HZ_ARGS); B = bd.Board(BOARD); worse = [m for m in [n] + mates if not joins_short(B, m)]
        except StepFailed: worse = [n] + mates
        if worse: shutil.copy(BOARD + '.hz', BOARD)
        count('high-impedance nets routed again first'); count('high-impedance reorders kept', int(not worse))
        print(f'  {n} was left open; routed first, then {mates}: ' + (f'kept, all joined' if not worse else f'not kept ({worse} open or too long), the first attempt stands'))
    if os.path.exists(BOARD + '.hz'): os.remove(BOARD + '.hz')
for _switch in ('KICAD_RIP_PREEXISTING', 'KICAD_FINALIZE_RIP', 'KICAD_RECONCILE_RIP_ESCALATION'): os.environ.setdefault(_switch, '0')   # the router must never rip copper an earlier step placed; each of the three grants that on its own
L3_RATIO = 1.8; L3_RATIO_LOW_Z = 2.2; L3_EXTRA = 12.0; PINCH = 0.25; HZ_NEAR = tl.HZ_KEEP; HZ_RUN = 3.0; OWN_PAD = 2.5     # a top route is rejected if it squeezes between two foreign pads, or runs more than HZ_RUN mm inside the soft keep-away of a high-impedance net
TOP_ONLY = ['--via-cost', '100000']; TOP_AND_L3 = ['--layer-costs', '1.0', '1.2', '--via-cost', '150']
def joins_short(B, net):
    L, t = length_and_tree(B, net); return not checks.top_incomplete(B, net) and L <= max(TOP_RATIO * t, t + TOP_EXTRA)
def copper_ids(B): return {x['uuid'] for x in B.segs + B.vias}
def drop_new(B, nets, since):
    """Removes the nets' tracks and vias that are not in `since` and saves the board"""
    gone = [x['uuid'] for x in B.segs + B.vias if x['net'] in nets and x['uuid'] not in since]
    if gone: B.remove(gone); B.save(BOARD)
def length_and_tree(B, net):
    """(track length, shortest tree through the pads) of a net, test points aside"""
    return (sum(math.dist((x['x1'], x['y1']), (x['x2'], x['y2'])) for x in B.segs if x['net'] == net),
            tree_len([(p['x'], p['y']) for p in B.pads if p['net'] == net and not checks.is_tp(p)]))
def per_board(B, key, make):
    """make(B), worked out once for each state of the board: every edit re-parses it into a new text"""
    memo = B.__dict__.setdefault('_memo', {}); hit = memo.get(key)
    if hit is None or hit[0] is not B.text: hit = memo[key] = (B.text, make(B))
    return hit[1]
def new_top_lines(B, net, since): return [LineString([(x['x1'], x['y1']), (x['x2'], x['y2'])]) for x in B.segs if x['net'] == net and x['uuid'] not in since and x['layer'] == 'F.Cu']
def hz_run(B, net, since):
    """mm of the net's top-layer track newer than `since` that lies within HZ_NEAR of high-impedance copper.
    The approach to its own pads does not count: a servo net has to end beside the servo inputs."""
    mine = new_top_lines(B, net, since)
    if not mine: return 0.0
    near = per_board(B, 'hz_near', lambda B: unary_union([g for n, g, k, o in B.copper('F.Cu') if bd.is_hz(n)]).buffer(HZ_NEAR))
    own = unary_union([Point(p['x'], p['y']).buffer(OWN_PAD) for p in B.pads if p['net'] == net])
    return sum(g.intersection(near).difference(own).length for g in mine)
def squeezed(B, net, since):
    """Foreign pads the net's top-layer track newer than `since` passes within PINCH mm of; two or more is a squeeze"""
    mine = new_top_lines(B, net, since)
    wid = max([x['w'] for x in B.segs if x['net'] == net and x['uuid'] not in since] or [0.2])
    own_refs = {p['ref'] for p in B.pads if p['net'] == net}                    # the other pad of a part the net ends on is not a squeeze
    pads, tree = per_board(B, 'top_pads', lambda B: (lambda P: (P, STRtree([B.pad_geom(p) for p in P])))([p for p in B.pads if 'F.Cu' in p['layers']]))
    close = {id(pads[int(i)]) for g in mine for i in tree.query(g, predicate='dwithin', distance=PINCH + wid / 2)}
    pinch = [checks.label(p) for p in B.pads if id(p) in close and p['net'] != net and p['ref'] not in own_refs and min(g.distance(B.pad_geom(p)) for g in mine) - wid / 2 < PINCH]
    under = {r for r in {x.split('.')[0] for x in pinch} if len(B.fps[r]['pads']) == 2 and sum(x.split('.')[0] == r for x in pinch) == 2}   # passing under a two-pad part between its pads is allowed
    return [x for x in pinch if x.split('.')[0] not in under]
def judge_top(B, net, since):
    """(kind, detail) of why the net's top-layer route newer than `since` is refused, or None"""
    L, t = length_and_tree(B, net)
    if L > max(TOP_RATIO * t, t + TOP_EXTRA): return 'too long on top', f'too long on top ({L:.0f} mm for a {t:.0f} mm tree)'
    pinch = squeezed(B, net, since)
    if len(pinch) >= 2: return 'squeezed', f'squeezed on top, under {PINCH} mm from {pinch}'
    near = hz_run(B, net, since)
    if near > HZ_RUN: return 'beside high-impedance copper', f'runs {near:.1f} mm within {HZ_NEAR} mm of high-impedance copper'
def refuse_top(B, net, since):
    """judge_top for a net that must also be joined"""
    return ('open', 'not joined on top') if checks.top_incomplete(B, net) else judge_top(B, net, since)
def net_classes():
    f = os.path.join(WORK, 'net_classes.json')
    if not os.path.exists(f): raise StepFailed('work/net_classes.json is missing: run setup with the .kicad_pro beside the board')
    return json.load(open(f))
def top_first(nets, label):
    """Top layer only, no vias. A net is kept only if it joins and passes the same judging as pass 1 of 2e; the rest is removed and left for later."""
    before = copper_ids(bd.Board(BOARD))
    router(nets, ['F.Cu'], TOP_ONLY)
    B = bd.Board(BOARD); later = []
    for n in nets:
        why = refuse_top(B, n, before)
        if why: later.append(n); count(f'{label} left for later: {why[0]}'); print(f'  {n}: {why[1]}, left for later')
    drop_new(B, later, before)
    count(f'{label} nets kept on top', len(nets) - len(later))
def in_class(net, cl, *classes): return any(fnmatch.fnmatchcase(net, p) for c in classes for p in cl.get(c, []))
def wanders(B, net, ratio=L3_RATIO):
    """(too long, length, shortest tree) of a net that was allowed off the top layer"""
    L, t = length_and_tree(B, net)
    return L > max(ratio * t, t + L3_EXTRA), L, t
def too_long_to_pass(B, net, cl):
    """wanders, at the limit a finished net must meet. Stage 2 and the outputs are low-impedance, so length costs them little"""
    return wanders(B, net, L3_RATIO_LOW_Z if in_class(net, cl, 'P4_Stage2', 'P5_AudioOut') else L3_RATIO)
def joined_off_top(B, net, ends_a, ends_b):
    """The net's inner-layer tracks on the shortest way from one of its vias at the points `ends_a` to one at `ends_b`, or None unless
    taking them out splits the net in two and no more: track on that way that also serves another pad must stay."""
    vias = [v for v in B.vias if v['net'] == net]
    def node(x, y):
        v = next((v for v in vias if math.dist((x, y), (v['x'], v['y'])) <= v['size'] / 2), None)
        return (round(v['x'], 2), round(v['y'], 2)) if v else (round(x, 3), round(y, 3))
    adj = {}
    for s in B.segs:
        if s['net'] == net and s['layer'] != 'F.Cu':
            a, b = node(s['x1'], s['y1']), node(s['x2'], s['y2']); d = math.dist((s['x1'], s['y1']), (s['x2'], s['y2']))
            adj.setdefault(a, []).append((b, d, s)); adj.setdefault(b, []).append((a, d, s))
    goal = {(round(x, 2), round(y, 2)) for x, y in ends_b}; done = set(); k = itertools.count()
    heap = [(0.0, next(k), (round(x, 2), round(y, 2)), []) for x, y in ends_a]
    while heap:
        d, _, at, way = heapq.heappop(heap)
        if at in done: continue
        if at in goal:
            if not way: return None
            ids = {s['uuid'] for s in way}
            return way if len(checks.pad_groups(B, net, ids)) == len(checks.pad_groups(B, net)) + 1 else None
        done.add(at)
        for to, step, s in adj.get(at, ()):
            if to not in done: heapq.heappush(heap, (d + step, next(k), to, way + [s]))
def top_again(nets, step):
    """A pair the via check flags has a legal top path within its limit, yet is joined through vias: the router took another
    way while other nets were in the way. Each such net is routed again on top alone and kept only if the whole net stays joined
    and passes the pass-1 judging; otherwise the board goes back."""
    for x in via_justify.check(bd.Board(BOARD), nets=[n for n in nets if bd.is_signal(n)]):
        B = bd.Board(BOARD); n = x['net']; off = joined_off_top(B, n, x['vias_a'], x['vias_b'])
        if not off or any(o['locked'] for o in off): continue
        shutil.copy(BOARD, BOARD + '.via'); before = copper_ids(B)
        B.remove([o['uuid'] for o in off]); B.save(BOARD)
        try: router([n], ['F.Cu'], TOP_ONLY, add_only=True); drop_dangling([n], step); why = refuse_top(bd.Board(BOARD), n, before)
        except StepFailed as e: why = ('router', f'the retry failed ({e})')      # an optional clean-up must not cost the step what it already routed
        if why: shutil.copy(BOARD + '.via', BOARD)
        count(f'{step} flagged vias retried on top'); count(f'{step} flagged vias replaced on top', int(not why))
        print(f"  {n} {x['a']} -> {x['b']}: " + (f'{why[1]}, vias kept' if why else f"now on top, {len(off)} inner-layer tracks removed"))
    if os.path.exists(BOARD + '.via'): os.remove(BOARD + '.via')
def drop_dangling(nets, step):
    """A via with copper on one layer only (a pad via whose inner-layer join was made another way, or what a top retry left) is removed,
    and so is a track with an end that meets nothing, then whatever that leaves loose. Track ends that met only through the via are
    first joined to its centre on their layer, so the net stays joined as it was; a via whose removal would still split the net is kept."""
    B = bd.Board(BOARD); gone = []; kept = set()
    while True:                                                               # one at a time: of two vias joining the same pieces, each is spare only while the other stays
        x = next((x for x in checks.dangling_vias(B, set(nets)) + checks.dangling_tracks(B, set(nets)) if not x['locked'] and x['uuid'] not in kept), None)
        if not x: break
        if 'size' in x:
            was = len(checks.pad_groups(B, x['net'])); keep = B.text; ends = checks.ends_in(B, x)
            if len(ends) > 1: B.add([B.seg_text(ex, ey, x['x'], x['y'], w, layer, x['net']) for (layer, ex, ey), w in ends.items() if math.dist((ex, ey), (x['x'], x['y'])) > 1e-4])
            B.remove([x['uuid']])
            if len(checks.pad_groups(B, x['net'])) > was: B.text = keep; B._parse(); kept.add(x['uuid']); continue
        else: B.remove([x['uuid']])
        gone.append(f"{x['net']} {'via' if 'size' in x else 'track'} ({x.get('x', x.get('x1')):.2f}, {x.get('y', x.get('y1')):.2f})")
    if gone: B.save(BOARD); count(f'{step} vias and tracks joining nothing removed', len(gone)); print(f'  vias and tracks joining nothing removed: {gone}')
def wide_then_standard(nets, step):
    """Pass 3: router vias allowed, with wider gaps so it cannot bring back the squeezes pass 1 was rejected for. A widened clearance also
    shuts a net out of its own pad when that pad sits inside it, so what stays open gets one try at the standard clearances; route_signals
    then holds those routes to the squeeze and high-impedance tests the wider gaps stood in for."""
    wide = bd.write_clearances(os.path.join(WORK, f'{step}_pass3_clearances.json'), {k: HZ_NEAR for k in bd.net_clearances() if bd.is_hz(k)})
    shut_out = router(nets, ['F.Cu', 'In2.Cu'], TOP_AND_L3 + ['--clearance', '0.3'], clearances=wide)
    if shut_out:
        print('  still open with the widened clearances, retried with the standard ones:', shut_out); count('nets retried at standard clearances', len(shut_out))
        router(shut_out, ['F.Cu', 'In2.Cu'], TOP_AND_L3)
def pad_vias_then_l3(nets, label):
    """A via IN a pad for each top-layer piece (the router only puts vias in open space), then those vias joined on L3 with no new vias.
    Returns the tracks there were before the L3 join."""
    with timed(f'{label} pad vias', vias=0) as rec:
        B = bd.Board(BOARD); added, failed = drops.run(B, signals=nets, log=lambda *a: None); B.save(BOARD); rec.update(vias=len(added), blocked=len(failed))
    count(f'{label} nets (pad vias + L3)', len(nets)); count(f'{label} pad vias', len(added)); count(f'{label} pieces with no legal pad via', len(failed))
    print(f'  {label} (pad vias + L3): {nets} | {len(added)} pad vias, {len(failed)} pieces with no legal pad via')
    mark = {x['uuid'] for x in B.segs}
    if nets: router(nets, ['In2.Cu'], TOP_ONLY, add_only=True)   # keep the pad vias just placed
    return mark
def route_signals(nets, step='2e'):
    """Returns (nets still open, nets routed too long): what the passes could not put right."""
    A = bd.Board(BOARD); before = {x['uuid'] for x in A.segs}; start = copper_ids(A); count(f'{step} pass 1 nets (top only)', len(nets))
    router(nets, ['F.Cu'], TOP_ONLY)                                         # pass 1: top only; nets that do not fit stay open
    with timed(f'{step} judge the top-only routes'):
        B = bd.Board(BOARD); again = []; redo = []
        for n in nets:
            why = judge_top(B, n, before)
            if why: again.append(n); redo.append(n); count(f'{step} rejected: {why[0]}'); print(f'  {n}: {why[1]}')
            elif checks.top_incomplete(B, n): again.append(n)                              # partly done on top: keep what connected, L3 only for the missing links
        if redo: B.remove([x['uuid'] for x in B.segs if x['net'] in redo and x['uuid'] not in before]); B.save(BOARD)
    mark = pad_vias_then_l3(again, f'{step} pass 2')
    B = bd.Board(BOARD); left = [n for n in again if checks.top_incomplete(B, n)]
    for n in again:                                                           # an L3-only join that had to wander round earlier nets is thrown away: pass 3 may cross with a via instead
        if n in left: continue
        far, L, t = wanders(B, n)
        if far:
            B.remove([x['uuid'] for x in B.segs if x['net'] == n and x['uuid'] not in mark]); left.append(n); count(f'{step} L3-only joins that wandered'); print(f'  {n}: L3-only join wandered ({L:.0f} mm for a {t:.0f} mm tree), redone in pass 3')
    B.save(BOARD)
    print('  pass 3 (router may add its own vias):', left)
    held = copper_ids(B)
    count(f'{step} pass 3 nets (router vias allowed)', len(left))
    if left: wide_then_standard(left, step)
    # in a shared call the router's own ordering decides who gets the ground; a net that came out open or wandering gets a call to itself
    def state(B, n):
        joined = not checks.top_incomplete(B, n); far, L, t = wanders(B, n)
        return (joined and not far, joined, -L), L, t
    def solo(n, route, since): drop_new(bd.Board(BOARD), [n], since); route([n]); return bd.Board(BOARD)
    B = bd.Board(BOARD)
    for n in sorted([n for n in left if not state(B, n)[0][0]], key=lambda n: wanders(B, n)[2]):
        was = state(bd.Board(BOARD), n)[0]; shutil.copy(BOARD, BOARD + '.shared')
        now, L, t = state(solo(n, lambda some: wide_then_standard(some, step), held), n)
        if now < was: shutil.copy(BOARD + '.shared', BOARD)
        count(f'{step} pass 3 nets routed again alone'); print(f"  {n} alone: {'joined' if now[1] else 'open'}, {L:.0f} mm for a {t:.0f} mm tree" + ('; worse than in the shared call, which is kept' if now < was else ''))
        if max(now, was)[0]: continue
        # the wider gap is only ever given up as a fallback, and the squeeze test it stood in for is applied instead; the net starts again from
        # nothing, as its earlier pieces and pad vias were placed for the wider gap and boxed it in at it
        shutil.copy(BOARD, BOARD + '.shared')
        B = solo(n, lambda some: router(some, ['F.Cu', 'In2.Cu'], TOP_AND_L3), start)
        (ok, joined, _), L, t = state(B, n); pinch = squeezed(B, n, start); kept = ok and len(pinch) < 2
        if not kept: shutil.copy(BOARD + '.shared', BOARD)
        count(f'{step} pass 3 nets routed alone at standard clearances'); count(f'{step} pass 3 standard-clearance routes kept', int(kept))
        print(f"  {n} alone at standard clearances: {'joined' if joined else 'open'}, {L:.0f} mm for a {t:.0f} mm tree"
              + ('' if kept else f"; not kept ({'squeezed, under ' + str(PINCH) + ' mm from ' + str(pinch) if ok else 'open or too long'})"))
    if os.path.exists(BOARD + '.shared'): os.remove(BOARD + '.shared')
    # the retries at standard clearances are free to squeeze between pads and hug high-impedance copper, so those routes answer to the same tests
    for kind, why, bad in (('squeezed', 'squeezed between foreign pads', lambda B, n: len(squeezed(B, n, held)) >= 2),
                           ('beside high-impedance copper', 'beside high-impedance copper', lambda B, n: hz_run(B, n, held) > HZ_RUN)):
        B = bd.Board(BOARD); dropped = [n for n in left if bad(B, n)]
        if dropped: drop_new(B, dropped, held); count(f'{step} pass 3 routes dropped: {kind}', len(dropped)); print(f'  pass 3 routes dropped, {why}: {dropped}')
    B = bd.Board(BOARD); left = [n for n in again if checks.top_incomplete(B, n)]         # pass 4: a pad that was blocked in pass 2 may be free now
    if left: pad_vias_then_l3(left, f'{step} pass 4')
    drop_dangling(nets, step)                                                 # first, so a stub left over does not change which vias the check flags
    top_again(nets, step)
    clear_the_way(nets, step)
    drop_dangling(nets, step)
    cl = net_classes() if os.path.exists(os.path.join(WORK, 'net_classes.json')) else {}
    B = bd.Board(BOARD); still_open = [n for n in nets if checks.top_incomplete(B, n)]; long = {n: w for n in nets if n not in still_open for w in [too_long_to_pass(B, n, cl)] if w[0]}
    for n in still_open: print(f'  {n}: still open')
    for n, (_, L, t) in long.items(): print(f'  {n}: {L:.0f} mm for a {t:.0f} mm tree, over the limit for a net off the top layer; check --final reports it')
    count(f'{step} nets left open', len(still_open)); count(f'{step} nets left too long', len(long)); return still_open, sorted(long)

def route_bias(nets):
    # L3 runs east-west, L5 north-south (the router alternates by position in --layers); BIAS_L3_COST trades L3 length against hop vias
    return router(nets, ['In2.Cu', 'In4.Cu'], ['--layer-costs', os.environ.get('BIAS_L3_COST', '2.0'), '1.0', '--via-cost', '40', '--track-width', '0.4',
                                               '--direction-preference-cost', '1000'])
FRONT_LONG = 1.5; BOX = 2.0
def rank(net, cl): return checks.priority(net, cl) or (6 if net in bd.BIAS else 99)
def clear_the_way(nets, step):
    """The router, not the net classes, decides the order of an L3 call, and 2d lays the bias on L3 before any signal. So a net still
    open, or a front-end net that joined off the top layer at over FRONT_LONG x its tree, may have been shut out or sent round by a
    lower-priority net's L3 track. If lower-priority signal or bias nets have L3 track in the box round its pads, those tracks are
    lifted, the net is joined first (pad vias and L3, then with router vias if it must), and the lifted nets are routed again round it.
    Two lifts are tried from the same board, the bias alone and every lower-priority net in the box. A result counts only if the net
    joins (and, if it was long, is shorter with no more vias), every lifted net that was joined still is, nothing new is squeezed or
    runs beside high-impedance copper, and no supply zone is cut. Of those, the one with the lowest routing score (score.py) is kept,
    if the net was open or that score is lower than before; otherwise the board goes back. A lifted net that comes out longer is
    weighed by the score, not refused: on one board refusing it kept a 57 mm route over a 25 mm one."""
    import score
    cl = net_classes() if os.path.exists(os.path.join(WORK, 'net_classes.json')) else {}
    vias = lambda B, m: sum(v['net'] == m for v in B.vias)
    def attempt(n, lift, shut, long):
        """Routes it from the board as it was; returns why the result does not count, or None"""
        B = bd.Board(BOARD); L = length_and_tree(B, n)[0]; start = copper_ids(B)
        was = dict(L=L, vias=vias(B, n), zones=len(checks.zone_integrity(B)), open={m for m in lift if checks.top_incomplete(B, m)})
        B.remove([s['uuid'] for s in B.segs if s['layer'] == 'In2.Cu' and s['net'] in [n] + lift]); B.save(BOARD)
        sig = [m for m in lift if m not in bd.BIAS]; bias = [m for m in lift if m in bd.BIAS]
        try:
            if shut:
                pad_vias_then_l3([n], f'{step} way cleared')
                if checks.top_incomplete(bd.Board(BOARD), n): wide_then_standard([n], step)
            else: router([n], ['In2.Cu'], TOP_ONLY, add_only=True)
            if sig:
                router(sig, ['In2.Cu'], TOP_ONLY, add_only=True)
                again = [m for m in sig if m not in was['open'] and checks.top_incomplete(bd.Board(BOARD), m)]
                if again: wide_then_standard(again, step)
            if bias: route_bias(bias)
            drop_dangling([n] + lift, step)
            B = bd.Board(BOARD); now = length_and_tree(B, n)[0]
            return next((w for bad, w in (
                (checks.top_incomplete(B, n), 'not joined'),
                (long and (now >= was['L'] or vias(B, n) > was['vias']), f'{now:.0f} mm, {vias(B, n)} vias'),
                (any(checks.top_incomplete(B, m) for m in lift if m not in was['open']), 'a lifted net left open'),
                (any(len(squeezed(B, m, start)) >= 2 or hz_run(B, m, start) > HZ_RUN for m in [n] + sig), 'squeezed or beside high-impedance copper'),
                (len(checks.zone_integrity(B)) > was['zones'], 'a supply zone cut')) if bad), None)
        except StepFailed as e: return f'the retry failed ({e})'
    for n in nets:
        B = bd.Board(BOARD); L, t = length_and_tree(B, n); shut = checks.top_incomplete(B, n)
        long = not shut and in_class(n, cl, 'P2_FrontEnd') and L > FRONT_LONG * t and any(s['net'] == n and s['layer'] == 'In2.Cu' for s in B.segs)
        if not (shut or long): continue
        xs, ys = zip(*[(p['x'], p['y']) for p in B.pads if p['net'] == n and not checks.is_tp(p)])
        area = box(min(xs) - BOX, min(ys) - BOX, max(xs) + BOX, max(ys) + BOX)
        lower = sorted({s['net'] for s in B.segs if s['layer'] == 'In2.Cu' and not s['locked'] and s['net'] != n and (bd.is_signal(s['net']) or s['net'] in bd.BIAS)
                        and rank(s['net'], cl) > rank(n, cl) and B.seg_geom(s).intersects(area)})
        bias = [m for m in lower if m in bd.BIAS]
        lifts = [x for x in (bias, lower) if x][:2 if bias != lower else 1]
        if not lifts: continue
        shutil.copy(BOARD, BOARD + '.clear'); before = None if shut else score.routing_total(BOARD, cl); found = []
        for k, lift in enumerate(lifts):
            shutil.copy(BOARD + '.clear', BOARD); why = attempt(n, lift, shut, long)
            got = None if why else score.routing_total(BOARD, cl)
            if not why: shutil.copy(BOARD, BOARD + f'.clear{k}'); found.append((got, k, lift))
            count(f'{step} nets routed again with lower-priority L3 lifted')
            print(f"  {n} ({'open' if shut else f'{L:.0f} mm'}) routed on L3 before {lift}: " + (f'does not count ({why})' if why else
                  f"{length_and_tree(bd.Board(BOARD), n)[0]:.0f} mm and {vias(bd.Board(BOARD), n)} vias, routing score {got:.0f}" + ('' if shut else f' (was {before:.0f})')))
        best = min(found, default=None)
        if best and (shut or best[0] < before):
            shutil.copy(BOARD + f'.clear{best[1]}', BOARD); count(f'{step} of those kept'); print(f'  kept: {n} with {best[2]} lifted')
        else: shutil.copy(BOARD + '.clear', BOARD)
        for f in [BOARD + '.clear'] + [BOARD + f'.clear{k}' for k in range(len(lifts))]:
            if os.path.exists(f): os.remove(f)
def link_unpoured_ground():
    """A ground pad set to no zone connection (a corner with no room for spokes) is not joined by the pours, and nothing routes ground:
    it gets a top-layer link to the nearest ground pad that can take one"""
    B = bd.Board(BOARD)
    for p in [p for p in B.pads if p['net'] in bd.GROUND and p['zone_none'] and 'F.Cu' in p['layers']]:
        comps = tl.components(B, p['net']); mine = next(c for c in comps if any(checks.label(q) == checks.label(p) for q in c['pads']))
        if len(mine['pads']) > 1 or mine['segs']: continue
        found = None
        for g, i in sorted((tl.gap(mine, c)[0], i) for i, c in enumerate(comps) if c is not mine)[:5]:
            lim = max(TOP_RATIO * g, g + TOP_EXTRA)
            for w in (0.4, 0.3, 0.2):
                found = tl.top_path(B, p['net'], mine, comps[i], w, max_len=lim)
                if found and found[0] <= lim: break
                found = None
            if found: break
        if not found: print(f'  WARNING: {checks.label(p)} has no zone connection and no legal top-layer link to another ground pad'); count('unpoured ground pads left open'); continue
        pts = found[1]; B.add([B.seg_text(*pts[k], *pts[k + 1], w, 'F.Cu', p['net']) for k in range(len(pts) - 1)]); B.save(BOARD)
        count('unpoured ground pads linked'); print(f'  {checks.label(p)} has no zone connection: linked on top, {found[0]:.1f} mm, {w} mm wide')
def run_step(s, src):
    links = [PY, os.path.join(HERE, 'neighbour_links.py'), BOARD, BOARD, '--json', os.path.join(WORK, f'{s}_links.json')]
    if s == 'setup':
        if not src: raise SystemExit('--from BOARD needed')
        sh([PY, os.path.join(HERE, 'setup6.py'), src, BOARD]); link_unpoured_ground()
        cl = classes_beside(src)
        if cl is None: print('  no .kicad_pro beside the board, so step 2p has no net classes')
        else: json.dump(cl, open(os.path.join(WORK, 'net_classes.json'), 'w'), indent=1)
        B = bd.Board(BOARD)                                                    # a warning, not a failure: the placement is the author's to fix, and routing can still run
        for r, v in hand_access.check(B, hand_access.hand_refs(B)).items():
            if not v['ok']: print(f"  WARNING: {r} is swapped by hand but hard to reach: nearest other pad {v['nearest_mm']} mm (needs {hand_access.SPACE_MM}), no clear board edge within {hand_access.EDGE_MM} mm"); count('hand-swap parts hard to reach')
    elif s == '2a':
        B = bd.Board(BOARD); later = mirror_route.waits_for_copy(B); route_hz([n for n in open_hz(B) if n not in later])
    elif s == '2p':
        # before 2b, so a neighbour link (a supply link above all) routes round these nets instead of through their way. The rest of the
        # front end goes last: the sources sit on a low-impedance resistor ladder and can take a via
        B = bd.Board(BOARD); cl = net_classes(); copies = mirror_route.waits_for_copy(B)
        of = lambda c: [n for n in B.nets if n not in copies and checks.top_incomplete(B, n) and in_class(n, cl, c)]
        drain = lambda n: n.split('/')[-1] in ('DA', 'DB')
        for label, group in (('2p drains', [n for n in of('P2_FrontEnd') if drain(n)]), ('2p stage 2', of('P4_Stage2')),
                             ('2p front end', [n for n in of('P2_FrontEnd') if not drain(n)])):
            if group: top_first(group, label)
    elif s == '2b':
        B = bd.Board(BOARD); later = mirror_route.waits_for_copy(B); sh(links + ['--nets', *[n for n in B.nets if n not in later]])
    elif s == '2c': sh([PY, os.path.join(HERE, 'drops.py'), BOARD, BOARD, '--ground', '--json', os.path.join(WORK, '2c_drops.json')])
    elif s == '2d':
        sh([PY, os.path.join(HERE, 'drops.py'), BOARD, BOARD, '--supply', '--json', os.path.join(WORK, '2d_drops.json')])
        if not os.environ.get('R6_SKIP_SUPPLY'):                                 # R6_SKIP_SUPPLY=1: no zones, for comparing signal routing between placements
            split_supply(); hop_to_zone()
            cut = checks.unconnected(bd.Board(BOARD), sorted(bd.RAILS))
            if cut: raise StepFailed(f"2d left {', '.join(u['net'] + ' open at ' + str(u['pads']) for u in cut)}")
        B = bd.Board(BOARD); bat = [n for n in B.nets if bd.is_battery(n)]; bias = [n for n in B.nets if n in bd.BIAS]
        router(bat, ['In4.Cu'], ['--via-cost', '100000', '--track-width', '0.5'])
        route_bias(bias)
        # a rail via the zone misses is a fault in the zone, not a spare: check --final reports it
        drop_dangling([n for n in B.nets if bd.is_supply(n) and n not in bd.RAILS], '2d')
    elif s == '2e':
        B = bd.Board(BOARD); later = mirror_route.waits_for_copy(B); still_open, long = route_signals([n for n in open_signals(B) if n not in later])
        # every one of these nets has now been attempted, so one left open is this step's failure, not something for the final check to find
        if still_open: raise StepFailed(f'2e left {len(still_open)} net(s) open {still_open}')
    elif s == '2h': sh([PY, os.path.join(HERE, 'mirror_route.py'), BOARD, BOARD, '--json', os.path.join(WORK, '2h_mirror.json')])
    elif s == '2i':
        sh(links); route_hz(open_hz(bd.Board(BOARD))); _, long = route_signals(open_signals(bd.Board(BOARD)), step='2i')
        # 2i is the last routing step for everything but the test points, which 2f joins
        B = bd.Board(BOARD); still_open = [n for n in B.nets if checks.top_incomplete(B, n)]
        if still_open: raise StepFailed(f'2i left {len(still_open)} net(s) open {still_open}')
    elif s == '2f':
        # a test point with no room for a via is not a failure here: the router reaches it by a track instead
        sh([PY, os.path.join(HERE, 'drops.py'), BOARD, BOARD, '--testpoints', '--json', os.path.join(WORK, '2f_drops.json')], ok=(0, drops.NO_ROOM))
        router(checks.loose_testpoint_nets(bd.Board(BOARD)), ['F.Cu', 'In2.Cu'], TOP_AND_L3, add_only=True)
        drop_dangling([n for n in bd.Board(BOARD).nets if n not in bd.RAILS | bd.GROUND], '2f')    # the last routing step: nothing loose may be left
    elif s != 'check': raise SystemExit('unknown step ' + s)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('step'); ap.add_argument('--from', dest='src'); ap.add_argument('--commit', action='store_true')
    ap.add_argument('--final', action='store_true'); ap.add_argument('--board', help='with check: check this board, not work/board.kicad_pcb')
    a = ap.parse_args(); global BOARD
    if a.board:
        if a.step != 'check': raise SystemExit('--board is for the check step only')
        BOARD = os.path.abspath(a.board)
    os.makedirs(WORK, exist_ok=True); failed = None; release_held()
    before = BOARD + '.before'; had_board = os.path.exists(BOARD) and a.step != 'check'             # check changes nothing, so it keeps no copy
    if had_board: shutil.copy(BOARD, before)
    t0 = time.perf_counter()
    try: run_step(a.step, a.src)
    except StepFailed as e: failed = str(e); print(f'[{a.step}] step failed: {e}')
    except BaseException:                                                     # a crash or Ctrl-C mid-step must not leave a half-routed board behind either
        if had_board: release_held(); os.replace(before, BOARD); print(f'[{a.step}] interrupted; the board is back to what it was before this step')
        raise
    if failed and not os.path.exists(BOARD): sys.exit(1)
    code = finish(a.step, a.commit and not failed, a.final, failed) or int(bool(failed))
    write_timing(a.step, time.perf_counter() - t0)
    if had_board:
        if code:
            os.replace(before, BOARD); print(f'[{a.step}] the board is back to what it was before this step; the result that failed is work/{a.step}.kicad_pcb')
        else: os.remove(before)
    sys.exit(code)
if __name__ == '__main__': main()
