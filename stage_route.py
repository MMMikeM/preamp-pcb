"""Runs the 6-layer routing one step at a time. Each step reads WORK, writes WORK, runs checks.py and (with --commit) commits.
    python stage_route.py setup  --from ../../../humbucker-preamp.kicad_pcb     # 1   6-layer conversion, rip-up
    python stage_route.py 2a     # high-impedance nets, top layer only, no vias          (router)
    python stage_route.py 2b     # neighbour links on top, every net class               (neighbour_links.py)
    python stage_route.py 2c     # a via in every ground pad                             (drops.py --ground)
    python stage_route.py 2d     # supply top links, drops, then trunks on L5            (neighbour_links.py --rule3, drops.py --supply, router on In4.Cu)
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
import sys, os, subprocess, shutil, argparse, json, math
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import board as bd, checks, krt_checks, mirror_route, drops
WORK = os.path.join(HERE, 'work'); BOARD = os.path.join(WORK, 'board.kicad_pcb')
PY = sys.executable
TOP_RATIO = 1.5; TOP_EXTRA = 3.0          # a net may leave the top layer only if its top-only route is longer than max(ratio*tree, tree+extra)

class StepFailed(Exception): pass
def sh(cmd, check=True, ok=(0,), **kw):
    print('  $', ' '.join(str(c) for c in cmd)); r = subprocess.run(cmd, **kw)
    if r.returncode not in ok and check: raise StepFailed(f"{' '.join(os.path.basename(str(c)) for c in cmd[:2])} exited {r.returncode}")
    return r
def router(nets, layers, extra=(), out=None):
    if not nets: print('  nothing to route on', *layers); return
    rd = os.environ.get('ROUTER_DIR')
    if not rd: raise StepFailed('set ROUTER_DIR to the KiCadRoutingTools checkout for this step')
    out = out or BOARD + '.tmp'
    cmd = [PY, 'py_router/route.py', BOARD, out, '--nets', *nets, '--layers', *layers, '--grid-step', '0.05', '--heuristic-weight', '1.0',
           '--direction-preference-cost', '0', '--same-net-pad-clearance', '0.15', '--fab-tier', 'standard', '--escalation', 'off',
           # stated, not left to the router: without a .kicad_pro beside the board it falls back to 0.25 / 0.2 / 0.2 mm, looser than rule 7 at the edge
           '--clearance', str(bd.CLEAR), '--board-edge-clearance', str(bd.EDGE), '--hole-to-hole-clearance', str(bd.HOLE_GAP),
           '--net-clearances', os.path.join(HERE, 'net_clearances.json'), '--keep-input-copper', *extra]
    sh(cmd, cwd=rd)
    if not os.path.exists(out): raise StepFailed('the router exited 0 but wrote no board')
    os.replace(out, BOARD)
def tree_len(pts):
    if len(pts) < 2: return 0.0
    inn = {0}; L = 0.0
    while len(inn) < len(pts):
        d, j = min((math.dist(pts[i], pts[j]), j) for i in inn for j in range(len(pts)) if j not in inn); inn.add(j); L += d
    return L
def finish(step, commit, final=False):
    saved = [os.path.join(WORK, f'{step}.kicad_pcb'), os.path.join(WORK, f'{step}_checks.json')]
    shutil.copy(BOARD, saved[0])
    B = bd.Board(BOARD); R = checks.report(B, justify=final or step not in ('setup', '2a'))
    if krt_checks.configured():
        R.update(krt_checks.report(BOARD)); ours = {u['net'] for u in R['unconnected']}
        R['krt_unconnected_extra'] = [n for n in R.pop('krt_unconnected') if n not in ours]
        print(f"  second opinion: {len(R['krt_drc'])} DRC items | nets only it calls unconnected: {R['krt_unconnected_extra'] or 'none'}")
    else: print('  second opinion skipped: ROUTER_DIR is not set')
    json.dump(R, open(saved[1], 'w'), indent=1)
    bad = checks.must_fix(R, final)
    print(f'[{step}] tracks {R["stats"]["tracks"]} vias {R["stats"]["vias"]} unconnected nets {len(R["unconnected"])} unjustified {len(R.get("unjustified_vias", []))} | must-fix: {bad or "none"}')
    # work/ is ignored, hence -f; the pathspec keeps anything else that happens to be staged out of the commit
    if commit and not bad and sh(['git', 'add', '-f', '--', *saved], check=False, cwd=HERE).returncode == 0:
        sh(['git', 'commit', '-q', '-m', f'route6 step {step}', '--', *saved], check=False, cwd=HERE)
    return 1 if bad else 0

def open_hz(B): return [n for n in B.nets if bd.is_hz(n) and checks.unconnected(B, [n])]
def open_signals(B): return [n for n in B.nets if n not in bd.GROUND and not bd.is_supply(n) and not bd.is_hz(n) and checks.top_incomplete(B, n)]
def route_hz(nets): router(nets, ['F.Cu'], ['--via-cost', '100000', '--track-width', '0.2'])
def route_signals(nets):
    before = {x['uuid'] for x in bd.Board(BOARD).segs}
    router(nets, ['F.Cu'], ['--via-cost', '100000'])                       # pass 1: top only; nets that do not fit stay open
    B = bd.Board(BOARD); again = []
    for n in nets:
        pts = [(p['x'], p['y']) for p in B.pads if p['net'] == n and not checks.is_tp(p)]; t = tree_len(pts)
        L = sum(math.dist((x['x1'], x['y1']), (x['x2'], x['y2'])) for x in B.segs if x['net'] == n)
        if checks.top_incomplete(B, n) or L > max(TOP_RATIO * t, t + TOP_EXTRA): again.append(n)
    B.remove([x['uuid'] for x in B.segs if x['net'] in again and x['uuid'] not in before]); B.save(BOARD)
    print('  pass 2 (top + L3):', again)
    router(again, ['F.Cu', 'In2.Cu'], ['--layer-costs', '1.0', '1.2', '--via-cost', '150'])

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
        supply = [n for n in bd.Board(BOARD).nets if bd.is_supply(n)]
        sh(links + ['--rule3', '--nets', *supply])
        sh([PY, os.path.join(HERE, 'drops.py'), BOARD, BOARD, '--supply', '--json', os.path.join(WORK, '2d_drops.json')])
        B = bd.Board(BOARD); rails = [n for n in B.nets if n in bd.RAILS or 'BAT' in n]; bias = [n for n in B.nets if n in bd.BIAS]
        router(rails, ['In4.Cu'], ['--via-cost', '100000', '--track-width', '0.5'])
        router(bias, ['In4.Cu'], ['--via-cost', '100000', '--track-width', '0.25'])
    elif s == '2e':
        B = bd.Board(BOARD); later = mirror_route.waits_for_copy(B); route_signals([n for n in open_signals(B) if n not in later])
    elif s == '2h': sh([PY, os.path.join(HERE, 'mirror_route.py'), BOARD, BOARD, '--json', os.path.join(WORK, '2h_mirror.json')])
    elif s == '2i':
        sh(links); route_hz(open_hz(bd.Board(BOARD))); route_signals(open_signals(bd.Board(BOARD)))
    elif s == '2f':
        # a test point with no room for a via is not a failure here: the router reaches it by a track instead
        sh([PY, os.path.join(HERE, 'drops.py'), BOARD, BOARD, '--testpoints', '--json', os.path.join(WORK, '2f_drops.json')], ok=(0, drops.NO_ROOM))
        router(checks.loose_testpoint_nets(bd.Board(BOARD)), ['F.Cu', 'In2.Cu'], ['--layer-costs', '1.0', '1.2', '--via-cost', '150'])
    elif s != 'check': raise SystemExit('unknown step ' + s)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('step'); ap.add_argument('--from', dest='src'); ap.add_argument('--commit', action='store_true')
    ap.add_argument('--final', action='store_true'); a = ap.parse_args()
    os.makedirs(WORK, exist_ok=True); failed = False
    before = BOARD + '.before'; had_board = os.path.exists(BOARD)
    if had_board: shutil.copy(BOARD, before)
    try: run_step(a.step, a.src)
    except StepFailed as e: failed = True; print(f'[{a.step}] step failed: {e}')
    if failed and not os.path.exists(BOARD): sys.exit(1)
    code = finish(a.step, a.commit and not failed, a.final) or int(failed)
    if had_board:
        if code and a.step != 'check':
            os.replace(before, BOARD); print(f'[{a.step}] the board is back to what it was before this step; the result that failed is work/{a.step}.kicad_pcb')
        else: os.remove(before)
    sys.exit(code)
if __name__ == '__main__': main()
