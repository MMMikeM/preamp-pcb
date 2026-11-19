"""Second opinion on a saved board from KiCadRoutingTools' own DRC and connectivity check (needs ROUTER_DIR, scipy, Pillow).
It grades against the real board outline and pad shapes and knows checks route6 has no model for (a via in a paste opening
that the file does not mark filled and capped). route6's own checks stay the inner loop: these need a file, not a Board.
usage: krt_checks.py BOARD"""
import os, sys, json, io, contextlib
import board as bd
HERE = os.path.dirname(os.path.abspath(__file__))

def configured(): return bool(os.environ.get('ROUTER_DIR'))

def _load():
    # appended, not inserted: route6's modules must win any name clash with py_router's 180 scripts
    path = os.path.join(os.environ['ROUTER_DIR'], 'py_router')
    if path not in sys.path: sys.path.append(path)
    import check_drc, check_connected
    return check_drc, check_connected

def _plain(v):
    if isinstance(v, float): return round(v, 4)
    if isinstance(v, (list, tuple)): return [_plain(x) for x in v]
    return v if isinstance(v, (str, int, bool, type(None))) else str(v)

def report(path):
    """{'krt_drc': violations it does not itself accept, 'krt_unconnected': net names}"""
    check_drc, check_connected = _load()
    clear = json.load(open(os.path.join(HERE, 'net_clearances.json')))
    with contextlib.redirect_stdout(io.StringIO()):
        found = check_drc.run_drc(path, clearance=bd.CLEAR, hole_to_hole_clearance=bd.HOLE_GAP, board_edge_clearance=bd.EDGE, net_clearances=clear,
                                  clearance_margin_mm=bd.TOL, quiet=True, print_summary=False)
        open_nets = check_connected.run_connectivity_check(path, None, quiet=True)
    keep = ('type', 'net1', 'net2', 'layer', 'overlap_mm', 'required_mm', 'loc1', 'loc2')
    return dict(krt_drc=[{k: _plain(x[k]) for k in keep if k in x} for x in found if not x.get('accepted')],
                krt_unconnected=sorted(str(x.get('net_name')) for x in open_nets))

if __name__ == '__main__':
    if not configured(): raise SystemExit('set ROUTER_DIR to the KiCadRoutingTools checkout')
    R = report(sys.argv[1])
    for k, v in R.items():
        print(f"{'FAIL' if v and k == 'krt_drc' else 'note' if v else 'ok  '} {k:<17} {len(v)}")
        for x in v[:6]: print('       ', x)
    sys.exit(1 if R['krt_drc'] else 0)
