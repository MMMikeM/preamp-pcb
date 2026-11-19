"""Runs the 6-layer routing one step at a time. Each step reads WORK, writes WORK, runs checks.py and (with --commit) commits.
    python stage_route.py setup  --from ../../../humbucker-preamp.kicad_pcb     # 1   6-layer conversion, rip-up
    python stage_route.py 2a     # high-impedance nets, top layer only, no vias          (router)
    python stage_route.py 2b     # neighbour links on top, every net class               (neighbour_links.py)
    python stage_route.py 2c     # a via in every ground pad                             (drops.py --ground)
    python stage_route.py 2d     # supply drops, then supply and bias trunks on L5       (drops.py --supply, router on In4.Cu)
    python stage_route.py 2e     # remaining signals: top first, L3 only when needed     (router twice + length test)
    python stage_route.py 2h     # copy the routing to the other channel                 (mirror_route.py)
    python stage_route.py 2f     # test points: via in pad                               (drops.py --testpoints, router)
    python stage_route.py check  # report only
2g (tidy) is manual review for now. WORK defaults to ./work/board.kicad_pcb; every step keeps work/<step>.kicad_pcb as well.
The router is KiCadRoutingTools (not included): set ROUTER_DIR to its checkout. Steps 2b, 2c, 2h, check and setup do not need it."""
import sys, os, subprocess, shutil, argparse, json, math
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import board as bd, checks
WORK = os.path.join(HERE, 'work'); BOARD = os.path.join(WORK, 'board.kicad_pcb')
PY = sys.executable
TOP_RATIO = 1.5; TOP_EXTRA = 3.0          # a net may leave the top layer only if its top-only route is longer than max(ratio*tree, tree+extra)

def sh(cmd, **kw):
    print('  $', ' '.join(str(c) for c in cmd)); r = subprocess.run(cmd, **kw)
    if r.returncode not in (0,): print('  exit', r.returncode)
    return r
def router(nets, layers, extra=(), out=None):
    rd = os.environ.get('ROUTER_DIR')
    if not rd: raise SystemExit('set ROUTER_DIR to the KiCadRoutingTools checkout for this step')
    out = out or BOARD + '.tmp'
    cmd = [PY, 'py_router/route.py', BOARD, out, '--nets', *nets, '--layers', *layers, '--grid-step', '0.05', '--heuristic-weight', '1.0',
           '--direction-preference-cost', '0', '--same-net-pad-clearance', '0.15', '--fab-tier', 'standard', '--escalation', 'off',
           '--net-clearances', os.path.join(HERE, 'net_clearances.json'), '--keep-input-copper', *extra]
    r = sh(cmd, cwd=rd)
    if r.returncode == 0 and os.path.exists(out): os.replace(out, BOARD)
    return r.returncode
def tree_len(pts):
    if len(pts) < 2: return 0.0
    inn = {0}; L = 0.0
    while len(inn) < len(pts):
        d, j = min((math.dist(pts[i], pts[j]), j) for i in inn for j in range(len(pts)) if j not in inn); inn.add(j); L += d
    return L
def finish(step, commit):
    shutil.copy(BOARD, os.path.join(WORK, f'{step}.kicad_pcb'))
    B = bd.Board(BOARD); R = checks.report(B, justify=step not in ('setup', '2a'))
    json.dump(R, open(os.path.join(WORK, f'{step}_checks.json'), 'w'), indent=1)
    bad = {k: len(R[k]) for k in checks.FAIL if R[k]}
    print(f'[{step}] tracks {R["stats"]["tracks"]} vias {R["stats"]["vias"]} unconnected nets {len(R["unconnected"])} unjustified {len(R.get("unjustified_vias", []))} | must-fix: {bad or "none"}')
    if commit and not bad: sh(['git', 'add', '-A', WORK], cwd=HERE); sh(['git', 'commit', '-q', '-m', f'route6 step {step}'], cwd=HERE)
    return 1 if bad else 0

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('step'); ap.add_argument('--from', dest='src'); ap.add_argument('--commit', action='store_true'); a = ap.parse_args()
    os.makedirs(WORK, exist_ok=True); s = a.step
    if s == 'setup':
        if not a.src: raise SystemExit('--from BOARD needed')
        sh([PY, os.path.join(HERE, 'setup6.py'), a.src, BOARD])
    elif s == '2a':
        B = bd.Board(BOARD); nets = [n for n in B.nets if bd.is_hz(n) and checks.unconnected(B, [n])]
        router(nets, ['F.Cu'], ['--via-cost', '100000', '--track-width', '0.2'])
    elif s == '2b': sh([PY, os.path.join(HERE, 'neighbour_links.py'), BOARD, BOARD, '--json', os.path.join(WORK, '2b_links.json')])
    elif s == '2c': sh([PY, os.path.join(HERE, 'drops.py'), BOARD, BOARD, '--ground', '--json', os.path.join(WORK, '2c_drops.json')])
    elif s == '2d':
        sh([PY, os.path.join(HERE, 'drops.py'), BOARD, BOARD, '--supply', '--json', os.path.join(WORK, '2d_drops.json')])
        B = bd.Board(BOARD); rails = [n for n in B.nets if n in bd.RAILS or 'BAT' in n]; bias = [n for n in B.nets if n in bd.BIAS]
        router(rails, ['In4.Cu'], ['--via-cost', '100000', '--track-width', '0.5'])
        router(bias, ['In4.Cu'], ['--via-cost', '100000', '--track-width', '0.25'])
    elif s == '2e':
        B = bd.Board(BOARD); nets = [n for n in B.nets if n not in bd.GROUND and not bd.is_supply(n) and not bd.is_hz(n) and checks.unconnected(B, [n])]
        before = {x['uuid'] for x in B.segs}
        router(nets, ['F.Cu'], ['--via-cost', '100000'])                       # pass 1: top only; nets that do not fit stay open
        B = bd.Board(BOARD); again = []
        for n in nets:
            pts = [(p['x'], p['y']) for p in B.pads if p['net'] == n and not p['ref'].startswith('TP')]; t = tree_len(pts)
            L = sum(math.dist((x['x1'], x['y1']), (x['x2'], x['y2'])) for x in B.segs if x['net'] == n)
            if checks.unconnected(B, [n]) or L > max(TOP_RATIO * t, t + TOP_EXTRA): again.append(n)
        B.remove([x['uuid'] for x in B.segs if x['net'] in again and x['uuid'] not in before]); B.save(BOARD)
        print('  pass 2 (top + L3):', again)
        if again: router(again, ['F.Cu', 'In2.Cu'], ['--layer-costs', '1.0', '1.2', '--via-cost', '150'])
    elif s == '2h': sh([PY, os.path.join(HERE, 'mirror_route.py'), BOARD, BOARD, '--json', os.path.join(WORK, '2h_mirror.json')])
    elif s == '2f':
        sh([PY, os.path.join(HERE, 'drops.py'), BOARD, BOARD, '--testpoints', '--json', os.path.join(WORK, '2f_drops.json')])
        B = bd.Board(BOARD); nets = [u['net'] for u in checks.unconnected(B) if any(p[0].startswith('TP') for g in u['pads'] for p in [g])]
        if nets: router(nets, ['F.Cu', 'In2.Cu'], ['--layer-costs', '1.0', '1.2', '--via-cost', '150'])
    elif s != 'check': raise SystemExit('unknown step ' + s)
    sys.exit(finish(s, a.commit))
if __name__ == '__main__': main()
