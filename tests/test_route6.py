"""Run from the route6 folder:  python -m pytest -q tests      (about 4 minutes; needs shapely and numpy, not the router)"""
import os, sys, math, re, copy, subprocess, pytest
from shapely.geometry import Point, box
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import board as bd, toplink as tl, via_justify, neighbour_links, drops, checks, setup6, mirror_route, stage_route, krt_checks
OLD = os.path.join(HERE, 'board_4layer_rev1.kicad_pcb'); NEW = os.path.join(HERE, 'board_placed_19nov.kicad_pcb')

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
    gnd = [p for p in B.pads if p['net'] == 'GND' and drops.smd_top(p) and p['ref'] not in bd.NO_VIA_REFS and not p['ref'].startswith('TP')]
    assert all(drops.has_via(B, p) for p in gnd)
    assert all((v['size'] - v['drill']) / 2 >= 0.1 - 1e-9 for v in B.vias)
    assert [u for u in checks.unconnected(B) if u['net'] == 'GND'] == []
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
def test_only_final_fails_on_unconnected_nets(bare, tmp_path, monkeypatch):
    monkeypatch.setattr(stage_route, 'WORK', str(tmp_path)); monkeypatch.setattr(stage_route, 'BOARD', str(tmp_path / 'board.kicad_pcb')); bare.save(stage_route.BOARD)
    unfinished = dict({k: [] for k in checks.FAIL + checks.FINAL}, unconnected=[dict(net='X')], stats=dict(tracks=0, vias=0))
    monkeypatch.setattr(checks, 'report', lambda B, justify=True, timing=None: unfinished)
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
def test_a_failed_step_puts_the_board_back(bare, tmp_path, monkeypatch):
    monkeypatch.setattr(stage_route, 'WORK', str(tmp_path)); monkeypatch.setattr(stage_route, 'BOARD', str(tmp_path / 'board.kicad_pcb')); bare.save(stage_route.BOARD)
    good = open(stage_route.BOARD, 'rb').read()
    def step_that_breaks(step, src):
        B = bd.Board(stage_route.BOARD); track(B, 'X', [(110, 100), (111, 100)]); B.save(); raise stage_route.StepFailed('broke')
    monkeypatch.setattr(stage_route, 'run_step', step_that_breaks); monkeypatch.setattr(krt_checks, 'configured', lambda: False)
    monkeypatch.setattr(checks, 'report', lambda B, justify=True, timing=None: dict({k: [] for k in checks.FAIL + checks.FINAL}, stats=dict(tracks=0, vias=0)))
    monkeypatch.setattr(sys, 'argv', ['stage_route.py', '2b'])
    with pytest.raises(SystemExit) as e: stage_route.main()
    assert e.value.code == 1 and open(stage_route.BOARD, 'rb').read() == good
    assert open(tmp_path / '2b.kicad_pcb', 'rb').read() != good
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
def _supply_zone(B, net='V+'):
    import supply5; x0, y0 = 105.0, 100.0
    B.add([supply5.zone_text(net, box(5, 20, 8, 40), f'{net}_test')])       # zone_text takes mm from the board corner
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
def test_supply_track_is_refused_where_it_would_crowd_other_copper(bare):
    import supply5; path = [(5, 20), (9, 20)]                                           # mm from the board corner
    assert supply5.track_fits(bare, 'V+', 'In2.Cu', path)
    bare.add([bare.via_text(107, 100.5, 0.6, 0.3, 'GND')]); assert not supply5.track_fits(bare, 'V+', 'In2.Cu', path)
def test_channel_shift_is_read_from_the_placement(bare):
    assert bd.channel_shift(bare) == 19.45
def test_a_killed_router_call_leaves_no_locks(linked, tmp_path, monkeypatch):
    B, _ = linked; monkeypatch.setattr(stage_route, 'WORK', str(tmp_path)); monkeypatch.setattr(stage_route, 'BOARD', str(tmp_path / 'board.kicad_pcb'))
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
