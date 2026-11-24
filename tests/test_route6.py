"""Run from the route6 folder:  python -m pytest -q tests      (about 4 minutes; needs shapely and numpy, not the router)"""
import os, sys, math, re, json, copy, itertools, subprocess, pytest
from shapely.geometry import Point, box
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import board as bd, toplink as tl, via_justify, neighbour_links, drops, checks, setup6, mirror_route, stage_route, krt_checks
OLD = os.path.join(HERE, 'board_4layer_rev1.kicad_pcb'); NEW = os.path.join(HERE, 'board_placed_19nov.kicad_pcb')
LAND = os.path.join(os.path.dirname(HERE), 'fixtures', 'landscape-74f5949', 'humbucker-preamp.kicad_pcb')

@pytest.fixture(scope='module')
def _bare():
    B = bd.Board(NEW); B.text = setup6.convert(B.text); B._parse(); B.remove([s['uuid'] for s in B.segs] + [v['uuid'] for v in B.vias]); return B
@pytest.fixture(scope='module')
def _linked(_bare):
    B = copy.deepcopy(_bare); return B, neighbour_links.run(B, log=lambda *_: None)
# The tests add tracks and vias, so each gets its own copy; the slow steps still run once.
@pytest.fixture
def bare(_bare): return copy.deepcopy(_bare)
@pytest.fixture
def linked(_linked): return copy.deepcopy(_linked)
def track(B, net, pts, w=0.2, layer='F.Cu'): B.add([B.seg_text(*pts[k], *pts[k + 1], w, layer, net) for k in range(len(pts) - 1)])
def spot(x, y, r=0.1): return dict(geom=Point(x, y).buffer(r), anchors=[(x, y, 'spot')])
@pytest.fixture
def work(tmp_path, monkeypatch):
    """stage_route pointed at a scratch work folder"""
    monkeypatch.setattr(stage_route, 'WORK', str(tmp_path)); monkeypatch.setattr(stage_route, 'BOARD', str(tmp_path / 'board.kicad_pcb')); return tmp_path
def ends(B, n): return [p for p in B.pads if p['net'] == n and not checks.is_tp(p)]
def straight(B, n): a, b = ends(B, n); track(B, n, [(a['x'], a['y']), (b['x'], b['y'])])
def close_pairs(B):
    """signal nets of two top-layer pads under 5 mm apart whose straight top track passes the pass-1 judging"""
    def fits(n): C = copy.deepcopy(B); straight(C, n); return stage_route.judge_top(C, n, {x['uuid'] for x in B.segs}) is None
    return [n for n in B.nets if bd.is_signal(n) and len(ends(B, n)) == 2 and all('F.Cu' in p['layers'] for p in ends(B, n))
            and math.dist(*[(p['x'], p['y']) for p in ends(B, n)]) < 5 and fits(n)]

def test_reader_counts():
    B = bd.Board(OLD); assert len(B.vias) == 137 and len(B.fps) > 150 and B.copper_layers == ['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu']
def test_a_script_keeps_the_source_line_endings(tmp_path):
    src = tmp_path / 'crlf.kicad_pcb'; out = tmp_path / 'out.kicad_pcb'
    src.write_bytes(open(NEW, 'rb').read().replace(b'\n', b'\r\n'))
    subprocess.run([sys.executable, os.path.join(os.path.dirname(HERE), 'drops.py'), str(src), str(out)], check=True)   # no flags: adds nothing
    assert out.read_bytes() == src.read_bytes()
def test_old_board_is_clean_by_our_own_checks():
    B = bd.Board(OLD)      # KiCad DRC passed this board: our checks must agree, or they are wrong
    assert checks.clearances(B) == [] and checks.hz_rule(B) == [] and checks.edge(B) == []
    assert [u for u in checks.unconnected(B) if u['net'] != 'GND'] == []
def test_via_check_flags_the_bat_minus_hop_on_the_old_board():
    fl = via_justify.check(bd.Board(OLD), nets=['/BAT-'])
    assert any(x['b'] == 'R304.2' and x['gap'] < 3 for x in fl)        # Q302.2 - R304.2: 2.8 mm apart, joined through two vias
def test_setup6_layers_and_zones(bare):
    assert bare.copper_layers == bd.LAYERS6
    assert sorted(z['name'] for z in bare.zones) == ['GND_B', 'GND_In1', 'GND_In3', 'GND_In4']
    assert '(capping yes)' in bare.text and '(filling yes)' in bare.text      # vias go in pads, so the fab must fill and cap them
def test_neighbour_links_make_the_image_case_direct(linked):
    B, added = linked
    hit = [x for x in added if x['net'] == '/BAT-' and {x['a'], x['b']} == {'Q303.2', 'R306.2'}]
    assert hit and hit[0]['length'] < 3.0 and hit[0]['width'] == 0.4
def test_neighbour_links_are_legal_and_loop_free(linked):
    B, added = linked
    assert checks.clearances(B) == [] and checks.edge(B) == [] and not B.vias
    assert all(x['length'] <= max(1.5 * x['gap'], x['gap'] + 1.0) + 1e-6 for x in added)
    assert not any(bd.is_hz(x['net']) or x['net'] == 'GND' for x in added)
def test_drops(linked):
    B, _ = linked; added, failed = drops.run(B, ground=True, supply=True, log=lambda *_: None)
    # known, real conflict on this placement: test point TP205 (BO, bottom side) sits right under U4 pin 10 (REF)
    assert {f['net'] for f in failed} <= {'REF'} and all('U4.10' in f['pad'] for f in failed) and len(failed) <= 1
    assert checks.clearances(B) == [] and checks.holes(B) == [] and checks.no_via_pads(B) == []
    gnd = [p for p in B.pads if p['net'] == 'GND' and drops.smd_top(p) and not B.fps[p['ref']]['hand'] and not p['ref'].startswith('TP')]
    assert all(drops.has_via(B, p) for p in gnd)
    assert all((v['size'] - v['drill']) / 2 >= 0.1 - 1e-9 for v in B.vias)
    cut = {checks.label(p) for p in B.pads if p['zone_none']}                          # setup links those on top; the drops cannot reach them
    assert {x for u in checks.unconnected(B) if u['net'] == 'GND' for g in u['pads'] for x in g} <= cut
def test_mirror_route_copies_connectivity(linked):
    B, _ = linked; planned = len(mirror_route.plan(B)[0]); todo, skipped = mirror_route.run(B)
    assert planned >= 20 and todo and checks.clearances(B) == []
    pc = lambda nets: {u['net']: u['pieces'] for u in checks.unconnected(B, nets)}
    a = pc([t['net'] for t in todo]); b = pc([t['twin'] for t in todo])
    assert all(a.get(t['net'], 1) == b.get(t['twin'], 1) for t in todo)

def test_pad_without_an_angle_is_read_unrotated():
    B = bd.Board(NEW); ref, pad = next((r, p) for r, f in B.fps.items() if f['r'] == 90 for p in f['pads'] if p['w'] != p['h'])
    i = B.text.index(f'(property "Reference" "{ref}"'); s = B.text.rindex('\n\t(footprint', 0, i) + 2; e = setup6.block(B.text, s)
    own_at = B.text.index('(at ', s) + 4
    B.text = B.text[:own_at] + re.sub(r'\(at (\S+) (\S+) 90\)', r'(at \1 \2)', B.text[own_at:e]) + B.text[e:]; B._parse()
    q = next(q for q in B.fps[ref]['pads'] if q['num'] == pad['num'])
    assert (q['w'], q['h']) == (pad['h'], pad['w'])
def test_link_from_a_track_end_keeps_clearance(bare):
    # an own 0.2 mm track running at exactly 0.2 mm from another net: a wider link starting on its end would stick out towards it
    x, y = 103.0, 91.0
    track(bare, 'V+', [(x, y), (x + 1, y)]); track(bare, 'OTHER', [(x - 1, y - 0.4), (x + 2, y - 0.4)])
    A = next(c for c in tl.components(bare, 'V+') if c['segs'] and c['segs'][0]['x1'] == x)
    wide, narrow = [tl.top_path(bare, 'V+', A, spot(x + 0.5, y + 1.5, 0.3), w, margin=2.0) for w in (0.4, 0.2)]
    assert narrow is not None
    if wide: track(bare, 'V+', wide[1], 0.4)
    track(bare, 'V+', narrow[1], 0.2)
    assert checks.clearances(bare) == []
def test_link_keeps_the_edge_distance_the_edge_check_wants(bare):
    r = tl.top_path(bare, 'X', spot(100.45, 88.5), spot(100.45, 91.5), 0.2)
    if r: track(bare, 'X', r[1])
    assert checks.edge(bare) == []
def test_a_join_within_the_limit_is_found_even_inside_the_keep_away(bare, monkeypatch):
    # a 2.5 mm corridor between a high-impedance track and another net: the only path is straight and wholly inside the keep-away
    track(bare, '/Neck/GA', [(101.5, 91.8), (105.0, 91.8)]); track(bare, 'OTHER', [(101.5, 90.5), (105.0, 90.5)])
    join = lambda: tl.top_path(bare, 'X', spot(102.0, 91.0), spot(104.5, 91.0), 0.2, max_len=3.75)
    assert join()[0] == pytest.approx(2.5)
    monkeypatch.setattr(tl, 'LIMIT_BEATS_KEEP_AWAY', False)
    assert join() is None
def test_bottom_test_point_does_not_make_a_top_route_incomplete(bare):
    net = '/Neck/SO'; top = [p for p in bare.pads if p['net'] == net and not checks.is_tp(p)]
    assert checks.top_incomplete(bare, net) and net in checks.loose_testpoint_nets(bare)
    track(bare, net, [(p['x'], p['y']) for p in top])
    assert checks.unconnected(bare, [net])[0]['pads'] == [['TP106.1']]
    assert not checks.top_incomplete(bare, net) and net in checks.loose_testpoint_nets(bare)
def test_testpoint_already_joined_gets_no_second_via(bare):
    tp = next(p for p in bare.pads if p['ref'] == 'TP106'); q = next(p for p in bare.pads if p['net'] == tp['net'] and not checks.is_tp(p))
    bare.add([bare.via_text(q['x'], q['y'], 0.5, 0.3, tp['net'])]); track(bare, tp['net'], [(q['x'], q['y']), (tp['x'], tp['y'])], layer='B.Cu')
    added, failed = drops.run(bare, testpoints=True, log=lambda *_: None)
    assert 'TP106.1' not in [x['pad'] for x in added + failed] and 'TP206.1' in [x['pad'] for x in added]
def test_supply_vias_placed_after_step_2b_are_all_justified(linked):
    B, _ = linked; supply = [n for n in B.nets if bd.is_supply(n)]
    drops.run(B, ground=True, supply=True, log=lambda *_: None)
    assert via_justify.check(B, nets=supply) == [] and checks.clearances(B) == []
def test_via_check_judges_a_rail_by_step_2b_limits(bare):
    bare.add([bare.via_text(p['x'], p['y'], 0.5, 0.3, 'V+') for p in bare.pads if p['net'] == 'V+' and p['kind'] == 'smd'])
    seen = []; real = tl.top_path
    def spy(B, net, A, C, width, max_len): seen.append((tl.gap(A, C)[0], max_len)); return real(B, net, A, C, width, max_len=max_len)
    try: tl.top_path = spy; via_justify.check(bare, nets=['V+'])
    finally: tl.top_path = real
    assert seen and all(g <= neighbour_links.MAX_GAP and lim == pytest.approx(max(neighbour_links.RATIO * g, g + neighbour_links.EXTRA)) for g, lim in seen)
def test_mirror_keeps_the_twin_when_the_source_has_no_routing(bare):
    t = mirror_route.plan(bare)[0][0]; a, b = [p for p in bare.pads if p['net'] == t['twin'] and not checks.is_tp(p)][:2]
    track(bare, t['twin'], [(a['x'], a['y']), (b['x'], b['y'])])
    mirror_route.run(bare)
    assert len([s for s in bare.segs if s['net'] == t['twin']]) == 1
def test_stage_fails_when_a_script_it_runs_fails():
    with pytest.raises(stage_route.StepFailed): stage_route.sh([sys.executable, '-c', 'import sys; sys.exit(3)'])
def test_only_final_fails_on_unconnected_nets(bare, work, monkeypatch):
    bare.save(stage_route.BOARD)
    unfinished = dict({k: [] for k in checks.FAIL + checks.FINAL}, unconnected=[dict(net='X')], stats=dict(tracks=0, vias=0))
    monkeypatch.setattr(checks, 'report', lambda B, justify=True, timing=None, classes=None: unfinished)
    assert stage_route.finish('check', False) == 0 and stage_route.finish('check', False, final=True) == 1
@pytest.mark.skipif(not krt_checks.configured(), reason='needs ROUTER_DIR (KiCadRoutingTools checkout)')
def test_the_router_drc_agrees_that_links_and_drops_are_clean(linked, tmp_path):
    B, _ = linked; drops.run(B, ground=True, supply=True, log=lambda *_: None); path = str(tmp_path / 'board.kicad_pcb'); B.save(path)
    assert krt_checks.report(path)['krt_drc'] == []
def test_a_board_with_arc_tracks_is_refused(tmp_path):
    text = open(NEW, encoding='utf-8').read().rstrip(); path = tmp_path / 'arcs.kicad_pcb'
    arc = '\t(arc\n\t\t(start 110 100)\n\t\t(mid 110.3 100.1)\n\t\t(end 110.4 100.4)\n\t\t(width 0.2)\n\t\t(layer "F.Cu")\n\t\t(net "GND")\n\t\t(uuid "0")\n\t)\n'
    path.write_text(text[:-1] + arc + ')\n', encoding='utf-8')
    with pytest.raises(ValueError, match='arc tracks'): bd.Board(str(path))
def test_a_via_in_a_through_hole_pad_is_a_hole_error(bare):
    p = next(p for p in bare.pads if p['drill'] and p['net'])
    assert checks.holes(bare) == []
    bare.add([bare.via_text(p['x'], p['y'], 0.6, 0.3, p['net'])])
    assert len(checks.holes(bare)) == 1
def test_a_failed_step_puts_the_board_back(bare, work, monkeypatch):
    bare.save(stage_route.BOARD)
    good = open(stage_route.BOARD, 'rb').read()
    def step_that_breaks(step, src):
        B = bd.Board(stage_route.BOARD); track(B, 'X', [(110, 100), (111, 100)]); B.save(); raise stage_route.StepFailed('broke')
    monkeypatch.setattr(stage_route, 'run_step', step_that_breaks); monkeypatch.setattr(krt_checks, 'configured', lambda: False)
    monkeypatch.setattr(checks, 'report', lambda B, justify=True, timing=None, classes=None: dict({k: [] for k in checks.FAIL + checks.FINAL}, stats=dict(tracks=0, vias=0)))
    monkeypatch.setattr(sys, 'argv', ['stage_route.py', '2b'])
    with pytest.raises(SystemExit) as e: stage_route.main()
    assert e.value.code == 1 and open(stage_route.BOARD, 'rb').read() == good
    assert open(work / '2b.kicad_pcb', 'rb').read() != good
def test_a_copy_that_would_collide_is_skipped_and_its_twin_kept(bare):
    pad = lambda ref, num: next(p for p in bare.pads if p['ref'] == ref and p['num'] == num)
    a, b = pad('Q101', '3'), pad('U1', '2'); shift = bd.channel_shift(bare)                # /Neck/DA, whose twin is /Bridge/DA shifted
    track(bare, '/Neck/DA', [(a['x'], a['y']), (b['x'], b['y'])])
    clear = copy.deepcopy(bare); assert '/Neck/DA' in [t['net'] for t in mirror_route.run(clear)[0]] and checks.clearances(clear) == []
    mid = ((a['x'] + b['x']) / 2 + shift, (a['y'] + b['y']) / 2)
    track(bare, 'STAYING', [(mid[0] - 0.05, mid[1]), (mid[0] + 0.05, mid[1])])          # sits where the copy would land
    crowded = checks.clearances(bare); todo, skipped = mirror_route.run(bare)                # the stub itself may crowd a pad
    assert '/Neck/DA' not in [t['net'] for t in todo] and any(s['net'] == '/Neck/DA' and 'STAYING' in s['why'] for s in skipped)
    assert not [s for s in bare.segs if s['net'] == '/Bridge/DA'] and checks.clearances(bare) == crowded
def test_a_track_marked_locked_no_is_locked_for_the_router(linked):
    B, _ = linked; u = B.segs[0]['uuid']; B.text = B.text.replace(f'(uuid "{u}")', f'(locked no)\n\t\t(uuid "{u}")', 1); B._parse()
    assert not B.segs[0]['locked'] and B.lock([u]) == [u] and B.segs[0]['locked']
def test_lock_and_unlock_leave_the_file_as_it_was(linked):
    B, _ = linked; before = B.text; mine = B.lock([s['uuid'] for s in B.segs])
    assert mine and all(s['locked'] for s in B.segs)
    again = B.lock([s['uuid'] for s in B.segs]); assert again == []                    # already locked: not ours to unlock later
    B.unlock(mine); assert B.text == before and not any(s['locked'] for s in B.segs)
def _router_result(linked, tmp_path, edit):
    A, _ = linked; out = str(tmp_path / 'out.kicad_pcb'); B = copy.deepcopy(A); edit(B); B.save(out); return A, out
def test_guard_passes_copper_added_for_a_given_net(linked, tmp_path):
    A, out = _router_result(linked, tmp_path, lambda B: track(B, '/Neck/DA', [(110, 100), (111, 100)]))
    stage_route.guard(A, out, {'/Neck/DA'})
def test_guard_fails_when_earlier_copper_is_gone(linked, tmp_path):
    A, out = _router_result(linked, tmp_path, lambda B: B.remove([B.segs[0]['uuid']]))
    with pytest.raises(stage_route.StepFailed, match='removed earlier copper of .*' + re.escape(linked[0].segs[0]['net'])): stage_route.guard(A, out, {'/Neck/DA'})
def test_guard_fails_on_copper_for_a_net_it_was_not_given(linked, tmp_path):
    A, out = _router_result(linked, tmp_path, lambda B: track(B, '/Neck/DB', [(110, 100), (111, 100)]))
    with pytest.raises(stage_route.StepFailed, match='not given'): stage_route.guard(A, out, {'/Neck/DA'})
def test_guard_fails_on_a_lock_left_behind(linked, tmp_path):
    A, out = _router_result(linked, tmp_path, lambda B: B.lock([B.segs[0]['uuid']]))
    with pytest.raises(stage_route.StepFailed, match='changed earlier copper'): stage_route.guard(A, out, {'/Neck/DA'})
def zone_text(net, poly, layer='In4.Cu'):
    pts = ' '.join(f'(xy {x:.3f} {y:.3f})' for x, y in list(poly.exterior.coords)[:-1])
    return (f'\n\t(zone\n\t\t(net "{net}")\n\t\t(layer "{layer}")\n\t\t(uuid "{net}-test")\n\t\t(name "{net}_test")\n\t\t(hatch edge 0.5)\n\t\t(priority 2)\n'
            f'\t\t(connect_pads yes\n\t\t\t(clearance 0.2)\n\t\t)\n\t\t(min_thickness 0.25)\n\t\t(fill yes)\n\t\t(polygon\n\t\t\t(pts\n\t\t\t\t{pts}\n\t\t\t)\n\t\t)\n\t)\n')
def _supply_zone(B, net='V+'):
    x0, y0 = 105.0, 100.0
    B.add([zone_text(net, box(x0, y0, x0 + 3, y0 + 20))])
    B.add([B.via_text(x0 + 1.5, y0 + 2, 0.6, 0.3, net), B.via_text(x0 + 1.5, y0 + 18, 0.6, 0.3, net)])
def test_zone_check_passes_a_whole_finger_and_flags_a_cut_one(bare):
    _supply_zone(bare); assert checks.zone_integrity(bare) == []
    track(bare, '/BAT+', [(104, 110), (109, 110)], w=0.5, layer='In4.Cu')                 # a foreign track straight across the finger
    bad = checks.zone_integrity(bare); assert len(bad) == 1 and bad[0]['net'] == 'V+' and bad[0]['pieces'] == 2 and len(bad[0]['cut_off']) == 1
def test_zone_check_lets_a_via_sit_inside_a_finger(bare):
    _supply_zone(bare); bare.add([bare.via_text(106.5, 110, 0.6, 0.3, '/Neck/DA')]); assert checks.zone_integrity(bare) == []
def test_via_check_ignores_pieces_that_never_leave_the_top_layer(bare):
    pair = {'Q303.2', 'R306.2'}; flagged = lambda: [x for x in via_justify.check(bare, nets=['/BAT-']) if {x['a'], x['b']} == pair]
    assert flagged() == []                                                              # two bare pads: unfinished, not unjustified
    q = next(p for p in bare.pads if checks.label(p) == 'Q303.2'); bare.add([bare.via_text(q['x'], q['y'], 0.5, 0.3, '/BAT-')])
    assert len(flagged()) == 1
def test_channel_shift_is_read_from_the_placement(bare):
    assert bd.channel_shift(bare) == 19.45
def test_a_killed_router_call_leaves_no_locks(linked, work):
    B, _ = linked
    clean = B.text; ours = B.lock([s['uuid'] for s in B.segs]); B.save(stage_route.BOARD)
    import json; json.dump(ours, open(stage_route.held_file(), 'w'))                     # the state a killed call leaves behind
    stage_route.release_held()
    assert bd.Board(stage_route.BOARD).text == clean and not os.path.exists(stage_route.held_file())
def test_mirror_leaves_a_twin_with_locked_copper_alone(linked):
    B, _ = linked; t = next(t for t in mirror_route.plan(B)[0] if any(s['net'] == t['net'] for s in B.segs))
    a, b = [p for p in B.pads if p['net'] == t['twin'] and not checks.is_tp(p)][:2]; track(B, t['twin'], [(a['x'], a['y']), (b['x'], b['y'])])
    mine = [s['uuid'] for s in B.segs if s['net'] == t['twin']]; B.lock(mine)
    todo, skipped = mirror_route.run(B)
    assert t['net'] not in [x['net'] for x in todo] and any(s['net'] == t['net'] and 'locked' in s['why'] for s in skipped)
    assert sorted(s['uuid'] for s in B.segs if s['net'] == t['twin']) == sorted(mine)
def test_hz_run_measures_new_track_beside_high_impedance_copper(bare):
    hz = next(p for p in bare.pads if bd.is_hz(p['net']) and p['kind'] == 'smd'); y = hz['y'] - hz['h'] / 2 - 0.6
    track(bare, '/Neck/DA', [(hz['x'] - 3, y), (hz['x'] + 3, y)])
    assert stage_route.hz_run(bare, '/Neck/DA', set()) > stage_route.HZ_RUN
    assert stage_route.hz_run(bare, '/Neck/DA', {s['uuid'] for s in bare.segs}) == 0
def test_a_net_off_the_top_layer_is_judged_by_its_length(bare):
    a, b = [p for p in bare.pads if p['net'] == '/Neck/DA' and not checks.is_tp(p)][:2]; d = math.dist((a['x'], a['y']), (b['x'], b['y']))
    track(bare, '/Neck/DA', [(a['x'], a['y']), (b['x'], b['y'])], layer='In2.Cu'); far, L, t = stage_route.wanders(bare, '/Neck/DA')
    assert not far and L == pytest.approx(d)
    track(bare, '/Neck/DA', [(a['x'], a['y']), (a['x'], a['y'] + 2 * t + stage_route.L3_EXTRA)], layer='In2.Cu'); assert stage_route.wanders(bare, '/Neck/DA')[0]
def test_copy_report_marks_a_net_the_other_channel_already_has(bare):
    assert mirror_route.other_side(bare, '/Neck/GA') == {'/Bridge/GA'}
    a, b = [p for p in bare.pads if p['net'] == '/Bridge/SB' and not checks.is_tp(p)][:2]; track(bare, '/Bridge/SB', [(a['x'], a['y']), (b['x'], b['y'])])
    done = len([p for p in bare.pads if p['net'] == '/Bridge/SB' and not checks.is_tp(p)]) == 2
    s = next(s for s in mirror_route.run(bare, dry=True)[1] if s['net'] == '/Neck/SB')
    assert ('already_routed_as' in s) == done
# On the landscape fixture the neck's U3 uses op-amp units B and C swapped: on pins 5 to 10, U3 pin n carries what U4 pin 15 - n does
SWAPPED = {'Net-(Q103-C)': 'Net-(Q203-C)', '/Neck/BO': '/Bridge/BO', '/Neck/OBN': '/Bridge/OBN', 'Net-(U3B--)': 'Net-(U4B--)'}
def test_a_net_on_the_swapped_op_amp_pins_is_never_copied():
    B = bd.Board(LAND); net = lambda ref, num: next(p['net'] for p in B.pads if p['ref'] == ref and p['num'] == num)
    assert [net('U3', n) for n in '6789'] == list(SWAPPED) and [net('U4', n) for n in '9876'] == list(SWAPPED.values())
    copied = lambda src='1': {x for t in mirror_route.plan(B, src)[0] for x in (t['net'], t['twin'])}
    assert not (copied('1') | copied('2')) & (set(SWAPPED) | set(SWAPPED.values()))
    shift = bd.channel_shift(B); at = {(p['ref'], p['num']): p for p in B.pads}
    for p in B.pads:                                                                    # the bridge as an exact shifted copy of the neck: only the swap can stop a copy now
        m = re.match(r'([A-Z]+)2(\d\d)$', p['ref']); q = at.get((f'{m[1]}1{m[2]}', p['num'])) if m else None
        if q: p['x'], p['y'] = q['x'] + shift, q['y']
    todo = {t['net']: t['twin'] for t in mirror_route.plan(B)[0]}
    assert not set(todo) & set(SWAPPED) and all(todo.get(n) == n.replace('/Neck/', '/Bridge/') for n in ('/Neck/OA', '/Neck/DA', '/Neck/DB', '/Neck/OB'))
def test_copy_report_pairs_the_swapped_op_amp_nets_by_function_not_by_pin():
    B = bd.Board(LAND)
    assert all(mirror_route.other_side(B, a) == {b} and mirror_route.other_side(B, b, '2') == {a} for a, b in SWAPPED.items())
    def join(net): track(B, net, [(p['x'], p['y']) for p in B.pads if p['net'] == net])
    report = lambda: {s['net']: s.get('already_routed_as') for s in mirror_route.run(B, dry=True)[1] if s['net'] in SWAPPED}
    join('/Bridge/OBN')                                                                 # on U4.7, the pin /Neck/BO's U3.7 matches by number
    assert report() == {'Net-(Q103-C)': None, '/Neck/BO': None, '/Neck/OBN': ['/Bridge/OBN'], 'Net-(U3B--)': None}
    for n in SWAPPED.values(): join(n)
    assert report() == {a: [b] for a, b in SWAPPED.items()}
def _fake_router(B, work, monkeypatch):
    monkeypatch.setenv('ROUTER_DIR', str(work)); B.save(stage_route.BOARD); calls = []
    def run(cmd, cwd):                                                                  # adds nothing, so every open net stays open
        A = bd.Board(stage_route.BOARD); calls.append((cmd, {x['net'] for x in A.segs + A.vias if x['locked']}))
        import shutil; shutil.copy(stage_route.BOARD, stage_route.BOARD + '.tmp'); return dict(returncode=0)
    monkeypatch.setattr(stage_route, 'run_router', run); return calls
def test_the_retry_after_widened_clearances_drops_the_wider_default_too(linked, work, monkeypatch):
    B, _ = linked; calls = _fake_router(B, work, monkeypatch); n = next(n for n in B.nets if n.startswith('/Neck/') and checks.top_incomplete(B, n))
    assert stage_route.router([n], ['F.Cu'], ['--clearance', '0.3'], clearances=str(work / 'wide.json')) == [n]
    assert len(calls) == 1                                                              # 2d's bias call: the widened clearance is what keeps it out of the fingers
    calls.clear(); stage_route.wide_then_standard([n], 'test')
    assert len(calls) == 2 and '--clearance' in calls[0][0][calls[0][0].index('--via-cost'):]
    assert calls[1][0][calls[1][0].index('--clearance') + 1] == str(bd.CLEAR) and '0.3' not in calls[1][0]
def test_add_only_locks_the_given_nets_own_copper_for_the_call(linked, work, monkeypatch):
    B, _ = linked; calls = _fake_router(B, work, monkeypatch); n = B.segs[0]['net']
    stage_route.router([n], ['F.Cu']); assert n not in calls[0][1]
    stage_route.router([n], ['F.Cu'], add_only=True); assert n in calls[1][1]
    assert not any(x['locked'] for x in bd.Board(stage_route.BOARD).segs if x['net'] == n)
def test_top_first_keeps_only_nets_that_join_within_the_rules(bare, work, monkeypatch):
    monkeypatch.setenv('ROUTER_DIR', str(work)); good, detour, still = close_pairs(bare)[:3]
    bare.save(stage_route.BOARD)
    def run(cmd, cwd):                                                                  # joins one net straight, one by a long detour, and leaves one open
        B = bd.Board(stage_route.BOARD); straight(B, good)
        a, b = ends(B, detour); track(B, detour, [(a['x'], a['y']), (a['x'], a['y'] - 15), (b['x'], b['y'])]); B.save(stage_route.BOARD + '.tmp'); return dict(returncode=0)
    monkeypatch.setattr(stage_route, 'run_router', run)
    stage_route.top_first([good, detour, still], 'test')
    B = bd.Board(stage_route.BOARD); routed = {s['net'] for s in B.segs}
    assert good in routed and detour not in routed and still not in routed
def test_a_neighbour_link_goes_round_a_track_placed_before_it(bare, linked):
    _, added = linked; x = next(x for x in added if x['net'] == 'V+')
    a, b = [next(p for p in bare.pads if checks.label(p) == k) for k in (x['a'], x['b'])]
    mx, my = (a['x'] + b['x']) / 2, (a['y'] + b['y']) / 2; dx, dy = b['x'] - a['x'], b['y'] - a['y']; d = math.hypot(dx, dy)
    track(bare, 'Net-(Q103-C)', [(mx - 3 * dy / d, my + 3 * dx / d), (mx + 3 * dy / d, my - 3 * dx / d)])   # straight across the direct link
    crowded = checks.clearances(bare); again = neighbour_links.run(bare, nets=['V+'], log=lambda *_: None)
    assert checks.clearances(bare) == crowded
    assert all(y['length'] > x['length'] + 0.5 for y in again if {y['a'], y['b']} == {x['a'], x['b']})
def test_a_pair_joined_through_vias_with_a_free_top_path_is_routed_on_top_again(bare, work, monkeypatch):
    monkeypatch.setenv('ROUTER_DIR', str(work)); good, bad = close_pairs(bare)[:2]
    for n in (good, bad):                                                               # each joined by a via in both pads and a track on L3
        a, b = ends(bare, n); bare.add([bare.via_text(p['x'], p['y'], 0.45, 0.2, n) for p in (a, b)]); track(bare, n, [(a['x'], a['y']), (b['x'], b['y'])], layer='In2.Cu')
    bare.save(stage_route.BOARD); assert {x['net'] for x in via_justify.check(bare, nets=[good, bad])} == {good, bad}
    def run(cmd, cwd):                                                                  # the top route is found for one net only
        B = bd.Board(stage_route.BOARD); n = cmd[cmd.index('--nets') + 1]
        if n == good: straight(B, good)
        B.save(stage_route.BOARD + '.tmp'); return dict(returncode=0)
    monkeypatch.setattr(stage_route, 'run_router', run)
    stage_route.top_again([good, bad], 'test')
    B = bd.Board(stage_route.BOARD)
    assert not [v for v in B.vias if v['net'] == good] and {s['layer'] for s in B.segs if s['net'] == good} == {'F.Cu'}
    assert len([v for v in B.vias if v['net'] == bad]) == 2 and not checks.top_incomplete(B, bad)
REV06 = os.path.join(os.path.dirname(HERE), 'fixtures', 'landscape-rev06', 'humbucker-preamp.kicad_pcb')
LAND509 = os.path.join(os.path.dirname(HERE), 'fixtures', 'landscape-509fb5a', 'humbucker-preamp.kicad_pcb')
def test_hand_swapped_parts_are_read_from_the_footprint_description():
    import hand_access; B = bd.Board(REV06)                                             # rev 0.6 renumbered them: R109 and R117 are other parts now
    assert hand_access.hand_refs(B) == {'R106', 'R114', 'R206', 'R214'}
    assert {r for r, v in hand_access.check(B, hand_access.hand_refs(B)).items() if not v['ok']} == {'R106', 'R206'}
def test_a_signal_pad_via_goes_in_the_pad_nearest_the_rest_of_the_net(bare):
    P = drops.Placer(bare)
    def cases():
        for n in bare.nets:
            if not bd.is_signal(n): continue
            ps = [p for p in ends(bare, n) if p['ref'][0] not in 'UQ' and drops.smd_top(p) and not bare.fps[p['ref']]['hand']]
            for a, b in itertools.combinations(ps, 2):
                for c in ends(bare, n):
                    if c not in (a, b) and abs(min(a['w'], a['h']) - min(b['w'], b['h'])) < 1e-9 and P.spot(a) and P.spot(b):
                        da, db = math.dist((a['x'], a['y']), (c['x'], c['y'])), math.dist((b['x'], b['y']), (c['x'], c['y']))
                        near, far = (a, b) if da < db else (b, a)
                        if abs(da - db) > 1 and len(ends(bare, n)) == 3 and bare.pads.index(far) < bare.pads.index(near): yield n, (near, far)   # file order alone would pick the far one
    n, (near, far) = next(cases())
    track(bare, n, [(far['x'], far['y']), (near['x'], near['y'])])                     # the two equal pads as one top-layer piece, the third pad on its own
    drops.run(bare, signals=[n], log=lambda *_: None)
    inside = lambda p: any(bare.pad_geom(p).contains(Point(v['x'], v['y'])) for v in bare.vias if v['net'] == n)
    assert inside(near) and not inside(far)
@pytest.mark.skipif(not os.environ.get('ROUTER_DIR'), reason='needs ROUTER_DIR (KiCadRoutingTools checkout)')
def test_the_split_plane_gives_each_rail_one_whole_zone_holding_all_its_vias(work):
    B = bd.Board(LAND509); B.text = setup6.convert(B.text); B._parse(); B.remove([x['uuid'] for x in B.segs + B.vias])   # on rev06 it left U3.4's via 0.39 mm outside the V+ zone
    drops.run(B, supply=True, log=lambda *_: None); B.save(stage_route.BOARD); stage_route.split_supply()
    B = bd.Board(stage_route.BOARD)
    assert sorted(z['net'] for z in B.zones if z['net'] in bd.RAILS) == ['V+', 'V-'] and checks.zone_integrity(B) == []
    assert all(len(checks.pad_groups(B, n)) == 1 for n in bd.RAILS)
def _order_sensitive_router(B, work, monkeypatch, blocker, blocked, always=False):
    """A stand-in router that joins each given net in the order given, straight through its pads, except that `blocked` cannot join
    once `blocker` has copper (or never, with always=True)"""
    monkeypatch.setenv('ROUTER_DIR', str(work)); B.save(stage_route.BOARD)
    def run(cmd, cwd):
        C = bd.Board(stage_route.BOARD)
        for n in cmd[cmd.index('--nets') + 1:cmd.index('--layers')]:
            if n == blocked and (always or any(s['net'] == blocker for s in C.segs)): continue
            ps = ends(C, n); track(C, n, [(p['x'], p['y']) for p in ps])
        C.save(stage_route.BOARD + '.tmp'); return dict(returncode=0)
    monkeypatch.setattr(stage_route, 'run_router', run)
def _same_channel_pair(B):
    """two short two-pad nets of one channel; the stand-in router decides which blocks which"""
    ns = close_pairs(B); return next((a, b) for a, b in itertools.combinations(ns, 2) if stage_route.channel(a) == stage_route.channel(b))
def test_a_gate_net_left_open_is_routed_first_and_both_join(bare, work, monkeypatch):
    a, b = _same_channel_pair(bare)
    _order_sensitive_router(bare, work, monkeypatch, blocker=a, blocked=b)
    stage_route.route_hz([a, b])
    B = bd.Board(stage_route.BOARD); assert not checks.top_incomplete(B, a) and not checks.top_incomplete(B, b)
def test_a_gate_reorder_that_does_not_help_leaves_the_first_attempt(bare, work, monkeypatch):
    a, b = _same_channel_pair(bare)
    _order_sensitive_router(bare, work, monkeypatch, blocker=a, blocked=b, always=True)
    stage_route.route_hz([a, b])
    B = bd.Board(stage_route.BOARD); assert not checks.top_incomplete(B, a) and checks.top_incomplete(B, b)
def test_only_the_nets_the_copy_will_fill_wait_for_it(bare):
    wait = mirror_route.waits_for_copy(bare); twins = {t['twin'] for t in mirror_route.plan(bare)[0]}
    own = [n for n in bare.nets if bd.is_signal(n) and ends(bare, n) and all(mirror_route.is_dst(p['ref'], '1') for p in ends(bare, n)) and n not in twins]
    assert wait == twins and own and not set(own) & wait                                 # the bridge's own nets are routed with the neck's, not left to 2i
def test_a_ground_pad_with_no_zone_connection_is_linked_on_top(bare, work):
    cut = [p for p in bare.pads if p['net'] in bd.GROUND and p['zone_none']]
    loose = lambda B: {x for u in checks.unconnected(B, ['GND']) for g in u['pads'] for x in g}
    assert cut and {checks.label(p) for p in cut} <= loose(bare)                          # the pours do not reach them, so the check must not count them joined
    bare.save(stage_route.BOARD); stage_route.link_unpoured_ground(); B = bd.Board(stage_route.BOARD)
    assert not {checks.label(p) for p in cut} & loose(B) and checks.clearances(B) == [] and {s['layer'] for s in B.segs} == {'F.Cu'}
def test_a_via_on_one_layer_is_removed_and_track_ends_that_met_through_it_are_joined(bare, work):
    n, m = close_pairs(bare)[:2]
    straight(bare, n); a, b = ends(bare, n); bare.add([bare.via_text(a['x'], a['y'], 0.45, 0.2, n)])          # a pad via whose L3 join was never made
    a, b = ends(bare, m); x, y = (a['x'] + b['x']) / 2, (a['y'] + b['y']) / 2; d = math.dist((a['x'], a['y']), (b['x'], b['y'])); ux, uy = (b['x'] - a['x']) / d, (b['y'] - a['y']) / d
    track(bare, m, [(a['x'], a['y']), (x - 0.2 * ux, y - 0.2 * uy)]); track(bare, m, [(x + 0.2 * ux, y + 0.2 * uy), (b['x'], b['y'])])
    bare.add([bare.via_text(x, y, 0.45, 0.2, m)])                                         # two top tracks that meet only through this via
    assert {v['net'] for v in checks.dangling_vias(bare)} == {n, m}                        # KiCad's test: copper on one layer only, whatever it joins there
    bare.save(stage_route.BOARD); stage_route.drop_dangling([n, m], 'test'); B = bd.Board(stage_route.BOARD)
    assert not B.vias and not checks.top_incomplete(B, m) and not checks.top_incomplete(B, n) and checks.dangling_tracks(B) == []
def test_a_via_with_only_a_track_from_a_pad_goes_with_that_track(bare, work):
    n = close_pairs(bare)[0]; straight(bare, n); a, b = ends(bare, n)
    track(bare, n, [(a['x'], a['y']), (a['x'] + 1.5, a['y'] + 1.5)]); bare.add([bare.via_text(a['x'] + 1.5, a['y'] + 1.5, 0.45, 0.2, n)])
    bare.save(stage_route.BOARD); stage_route.drop_dangling([n], 'test'); B = bd.Board(stage_route.BOARD)
    assert not B.vias and len(B.segs) == 1 and not checks.top_incomplete(B, n)
def test_stage_2_and_the_outputs_may_run_longer_off_the_top_layer(bare):
    n = next(n for n in bare.nets if bd.is_signal(n) and stage_route.length_and_tree(bare, n)[1] > 16)
    t = stage_route.length_and_tree(bare, n)[1]; p = ends(bare, n)[0]; track(bare, n, [(p['x'], p['y']), (p['x'], p['y'] + 2 * t)], layer='In2.Cu')
    assert stage_route.too_long_to_pass(bare, n, {})[0] and stage_route.too_long_to_pass(bare, n, {'P5_AudioOut': [n]})[0] is False
def test_the_copy_step_passes_when_no_net_has_a_twin(bare, tmp_path):
    text = bare.text
    for k, r in enumerate(r for r in bare.fps if mirror_route.is_dst(r, '1')):          # each part of the other channel moved by its own amount, as when laid out by hand
        i = text.index(f'(property "Reference" "{r}"'); s = text.rindex('\n\t(footprint', 0, i) + 2; a = text.index('(at ', s) + 4; x = text[a:text.index(' ', a)]
        text = text[:a] + f'{float(x) + 0.3 * (k + 1):.4f}' + text[a + len(x):]
    src = tmp_path / 'in.kicad_pcb'; out = tmp_path / 'out.kicad_pcb'; src.write_text(text)
    assert not mirror_route.plan(bd.Board(str(src)))[0]
    r = subprocess.run([sys.executable, os.path.join(os.path.dirname(HERE), 'mirror_route.py'), str(src), str(out)], capture_output=True, text=True)
    assert r.returncode == 0 and 'nothing to copy' in r.stdout and out.read_text() == text
def _front_end_round_bias(bare, work, monkeypatch, long=True, bias_back=6.0):
    """A front-end net joined on L3 between its two pad vias, with a bias track across its way on L3. The stand-in router joins the
    net straight on L3 and lays the bias again `bias_back` mm long, away from the net."""
    monkeypatch.setenv('ROUTER_DIR', str(work)); n = close_pairs(bare)[0]; a, b = ends(bare, n)
    (work / 'net_classes.json').write_text(json.dumps({'P2_FrontEnd': [n]}))
    bare.add([bare.via_text(p['x'], p['y'], 0.45, 0.2, n) for p in (a, b)])
    track(bare, n, [(a['x'], a['y']), (a['x'], a['y'] + 12), (b['x'], b['y'] + 12), (b['x'], b['y'])] if long else [(a['x'], a['y']), (b['x'], b['y'])], layer='In2.Cu')
    mx, my = (a['x'] + b['x']) / 2, (a['y'] + b['y']) / 2; track(bare, 'PB', [(mx, my - 3), (mx, my + 3)], w=0.4, layer='In2.Cu')
    bare.save(stage_route.BOARD); calls = []
    def run(cmd, cwd):
        C = bd.Board(stage_route.BOARD); nets = cmd[cmd.index('--nets') + 1:cmd.index('--layers')]; calls.append(nets)
        if n in nets: track(C, n, [(a['x'], a['y']), (b['x'], b['y'])], layer='In2.Cu')
        if 'PB' in nets: track(C, 'PB', [(mx + 20, my), (mx + 20, my + bias_back)], w=0.4, layer='In2.Cu')
        C.save(stage_route.BOARD + '.tmp'); return dict(returncode=0)
    monkeypatch.setattr(stage_route, 'run_router', run)
    monkeypatch.setattr(checks, 'dangling_tracks', lambda B, nets=None: [])           # the stand-in's bias tracks lead nowhere; only the decision is tested
    return n, calls
def l3(B, n): return sum(math.dist((s['x1'], s['y1']), (s['x2'], s['y2'])) for s in B.segs if s['net'] == n and s['layer'] == 'In2.Cu')
def test_a_long_front_end_net_is_routed_again_with_the_bias_moved_out_of_its_way(bare, work, monkeypatch):
    n, calls = _front_end_round_bias(bare, work, monkeypatch); before = l3(bd.Board(stage_route.BOARD), n)
    stage_route.clear_the_way([n], 'test'); B = bd.Board(stage_route.BOARD)
    assert calls == [[n], ['PB']] and l3(B, n) < before - 20 and l3(B, 'PB') == pytest.approx(6.0) and not checks.top_incomplete(B, n)
def test_a_reroute_that_costs_the_bias_more_than_the_front_end_gains_is_not_kept(bare, work, monkeypatch):
    n, calls = _front_end_round_bias(bare, work, monkeypatch, bias_back=100.0); was = open(stage_route.BOARD).read()
    stage_route.clear_the_way([n], 'test')
    assert calls == [[n], ['PB']] and open(stage_route.BOARD).read() == was                      # within PB's own limit, but a P2 mm weighs 3 bias mm: 24 mm saved does not pay for 94
def test_a_front_end_net_within_its_length_is_left_alone(bare, work, monkeypatch):
    n, calls = _front_end_round_bias(bare, work, monkeypatch, long=False); was = open(stage_route.BOARD).read()
    stage_route.clear_the_way([n], 'test')
    assert calls == [] and open(stage_route.BOARD).read() == was
def test_a_rail_pad_beyond_the_other_rails_zone_joins_its_own_through_one_l3_hop(bare, work):
    P = drops.Placer(bare); ok = [p for p in bare.pads if p['net'] == 'V+' and drops.smd_top(p) and not bare.fps[p['ref']]['hand'] and P.spot(p)]
    a, c = next((a, c) for a, c in itertools.combinations(ok, 2) if 5 < math.dist((a['x'], a['y']), (c['x'], c['y'])) < 12)
    va, vc = P.spot(a), P.spot(c); bare.add([bare.via_text(*va, 'V+'), bare.via_text(*vc, 'V+')])
    mx, my = (va[0] + vc[0]) / 2, (va[1] + vc[1]) / 2
    bare.add([zone_text('V+', Point(vc[0], vc[1]).buffer(1.5)), zone_text('V-', Point(mx, my).buffer(1.2))])   # its zone round the far via, the other rail's between
    joined = lambda B: any({checks.label(a), checks.label(c)} <= {checks.label(p) for p in g} for g in checks.pad_groups(B, 'V+'))
    assert not joined(bare)
    bare.save(stage_route.BOARD); assert stage_route.hop_to_zone() == [checks.label(a)]; B = bd.Board(stage_route.BOARD)
    hop = [s for s in B.segs if s['net'] == 'V+']
    assert joined(B) and len(B.vias) == 2 and hop and {s['layer'] for s in hop} == {'In2.Cu'} and checks.clearances(B) == []
def test_unjustified_vias_are_must_fix_on_p1_to_p3_a_warning_on_p4_to_p6_and_not_reported_elsewhere():
    R = checks.report(bd.Board(OLD), classes={'P2_FrontEnd': ['V+'], 'P5_AudioOut': ['V-'], 'P7_Power': ['/BAT*']})   # the old board flags V+, V-, /BAT+ and /BAT-
    assert {x['net'] for x in R['unjustified_vias']} == {'V+'} and {x['net'] for x in R['unjustified_warnings']} == {'V-'}
    assert 'unjustified_warnings' not in checks.must_fix(R, final=True) and 'unjustified_vias' in checks.must_fix(R, final=True)
def test_a_track_stub_is_removed_back_to_where_it_joins(bare, work):
    n = close_pairs(bare)[0]; straight(bare, n); a, b = ends(bare, n)
    track(bare, n, [(a['x'], a['y']), (a['x'], a['y'] - 2), (a['x'] + 2, a['y'] - 2)])                    # two pieces leading nowhere
    assert [s['net'] for s in checks.dangling_tracks(bare)] == [n]
    bare.save(stage_route.BOARD); stage_route.drop_dangling([n], 'test'); B = bd.Board(stage_route.BOARD)
    assert len(B.segs) == 1 and not checks.top_incomplete(B, n) and checks.dangling_tracks(B) == []
def test_a_flagged_pair_on_a_shared_inner_track_moves_to_top_and_the_third_pad_stays_joined(bare, work, monkeypatch):
    monkeypatch.setenv('ROUTER_DIR', str(work)); P = drops.Placer(bare)
    def three(n):
        ps = [p for p in ends(bare, n) if drops.smd_top(p) and P.spot(p)]
        for a, b, c in itertools.permutations(ps, 3):
            if math.dist((a['x'], a['y']), (b['x'], b['y'])) < 4 and min(math.dist((c['x'], c['y']), (q['x'], q['y'])) for q in (a, b)) > 9: return a, b, c
    n, (a, b, c) = next((n, t) for n in bare.nets if bd.is_signal(n) and len(ends(bare, n)) == 3 for t in [three(n)] if t)
    va, vb, vc = (P.spot(p)[:2] for p in (a, b, c)); bare.add([bare.via_text(*v, 0.5, 0.3, n) for v in (va, vb, vc)])
    track(bare, n, [vc, va], layer='In2.Cu'); track(bare, n, [va, vb], layer='In2.Cu')                    # one inner track serving all three pads
    assert any({x['a'], x['b']} == {checks.label(a), checks.label(b)} for x in via_justify.check(bare, nets=[n]))
    bare.save(stage_route.BOARD)
    def run(cmd, cwd):
        C = bd.Board(stage_route.BOARD); track(C, n, [(a['x'], a['y']), (b['x'], b['y'])]); C.save(stage_route.BOARD + '.tmp'); return dict(returncode=0)
    monkeypatch.setattr(stage_route, 'run_router', run)
    stage_route.top_again([n], 'test'); B = bd.Board(stage_route.BOARD)
    inner = [s for s in B.segs if s['net'] == n and s['layer'] == 'In2.Cu']
    assert not checks.top_incomplete(B, n) and len(inner) == 1 and len([v for v in B.vias if v['net'] == n]) == 2
def test_a_net_shut_out_by_a_lower_priority_l3_track_is_joined_first_and_that_track_routed_again(bare, work, monkeypatch):
    monkeypatch.setenv('ROUTER_DIR', str(work)); n, m = close_pairs(bare)[:2]; a, b = ends(bare, n)
    (work / 'net_classes.json').write_text(json.dumps({'P2_FrontEnd': [n], 'P5_AudioOut': [m]}))
    mx, my = (a['x'] + b['x']) / 2, (a['y'] + b['y']) / 2; track(bare, m, [(mx, my - 3), (mx, my + 3)], layer='In2.Cu')   # m's L3 track across n's way
    bare.save(stage_route.BOARD); calls = []
    def run(cmd, cwd):                                                                  # n joins on L3 between its pad vias only while m's track is gone
        C = bd.Board(stage_route.BOARD); nets = cmd[cmd.index('--nets') + 1:cmd.index('--layers')]; calls.append(nets)
        if n in nets and not any(s['net'] == m and s['layer'] == 'In2.Cu' for s in C.segs): track(C, n, [(v['x'], v['y']) for v in C.vias if v['net'] == n][:2], layer='In2.Cu')
        if m in nets: track(C, m, [(mx + 20, my), (mx + 20, my + 6)], layer='In2.Cu')
        C.save(stage_route.BOARD + '.tmp'); return dict(returncode=0)
    monkeypatch.setattr(stage_route, 'run_router', run); monkeypatch.setattr(checks, 'dangling_tracks', lambda B, nets=None: [])
    stage_route.clear_the_way([n], 'test'); B = bd.Board(stage_route.BOARD)
    assert calls[0] == [n] and [m] in calls and not checks.top_incomplete(B, n) and l3(B, m) == pytest.approx(6.0)
def test_a_net_too_long_off_the_top_layer_fails_only_the_final_check(bare, work, monkeypatch):
    monkeypatch.delenv('ROUTER_DIR', raising=False); n = close_pairs(bare)[0]; a, b = ends(bare, n)
    bare.add([bare.via_text(p['x'], p['y'], 0.45, 0.2, n) for p in (a, b)]); track(bare, n, [(a['x'], a['y']), (a['x'], a['y'] + 20), (b['x'], b['y'])], layer='In2.Cu')
    bare.save(stage_route.BOARD); stage_route.finish('check', False, final=False)
    R = json.load(open(work / 'check_checks.json')); assert [x['net'] for x in R['too_long']] == [n]
    assert 'too_long' in checks.must_fix(R, final=True) and 'too_long' not in checks.must_fix(R)
def test_a_router_killed_from_outside_is_not_reported_as_a_routing_result():
    assert 'probably out of memory' in stage_route.how_it_ended('route.py', -9) and 'out of memory' in stage_route.how_it_ended('route.py', 0xC0000017)
    assert stage_route.how_it_ended('route.py', 1) == 'route.py exited 1'
def test_a_stub_lying_alongside_a_track_is_still_loose(bare):
    n = close_pairs(bare)[0]; straight(bare, n); a, b = ends(bare, n); d = math.dist((a['x'], a['y']), (b['x'], b['y']))
    nx, ny = -(b['y'] - a['y']) / d, (b['x'] - a['x']) / d; mx, my = (a['x'] + b['x']) / 2 + 0.15 * nx, (a['y'] + b['y']) / 2 + 0.15 * ny
    track(bare, n, [(mx, my), (mx + 0.6 * nx, my + 0.6 * ny)])                          # its round end overlaps the track, its end point does not
    assert [s['net'] for s in checks.dangling_tracks(bare)] == [n]
def test_check_takes_a_board_by_path_and_leaves_it_alone(bare, tmp_path):
    src = tmp_path / 'mine.kicad_pcb'; bare.save(str(src)); was = src.read_text(); env = dict(os.environ, R6_WORK=str(tmp_path / 'w')); env.pop('ROUTER_DIR', None)
    r = subprocess.run([sys.executable, os.path.join(os.path.dirname(HERE), 'stage_route.py'), 'check', '--board', str(src)], env=env, capture_output=True, text=True)
    assert r.returncode == 0 and '[check] tracks 0' in r.stdout and src.read_text() == was and sorted(os.listdir(tmp_path)) == ['mine.kicad_pcb', 'w']
SEVEN = os.path.join(os.path.dirname(HERE), 'fixtures', 'landscape-7bccb83', 'humbucker-preamp.kicad_pcb')
def test_the_score_charges_a_front_end_track_beside_an_output_by_the_gap(bare, tmp_path):
    import score
    n, m = close_pairs(bare)[:2]; a, b = ends(bare, n); straight(bare, n); d = math.dist((a['x'], a['y']), (b['x'], b['y']))
    nx, ny = -(b['y'] - a['y']) / d, (b['x'] - a['x']) / d; off = 0.2 + 0.2                       # 0.2 mm edge to edge for two 0.2 mm tracks
    track(bare, m, [(a['x'] + off * nx, a['y'] + off * ny), (b['x'] + off * nx, b['y'] + off * ny)])
    f = tmp_path / 'b.kicad_pcb'; bare.save(str(f)); cl = tmp_path / 'cl.json'; cl.write_text(json.dumps({'P2_FrontEnd': [n], 'P5_AudioOut': [m]}))
    r = score.score(str(f), str(cl))['rows'][n]
    assert r['coupled_by_aggressor'][m][0] >= d - 0.5 and r['p_coupling'] == pytest.approx(r['weight'] * score.COUPLE_MM * r['coupled'], abs=0.2)
def test_the_score_does_not_charge_nets_the_circuit_joins_through_a_small_impedance():
    import score
    S = score.score(SEVEN); pairs = {(n, m) for n, m, _ in S['exempt']}
    assert ('/Neck/DB', '/Neck/OB') in pairs and ('/Neck/SA', '/Neck/OA') in pairs                 # 1k and 270p; 2k
    assert not any(n == '/Neck/GA' for n, _ in pairs)                                               # the gate reaches the cold-load drive only through 330k
