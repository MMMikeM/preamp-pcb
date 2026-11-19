"""Run from the route6 folder:  python -m pytest -q tests      (about 4 minutes; needs shapely and numpy, not the router)"""
import os, sys, math, pytest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import board as bd, toplink as tl, via_justify, neighbour_links, drops, checks, setup6, mirror_route
OLD = os.path.join(HERE, 'board_4layer_rev1.kicad_pcb'); NEW = os.path.join(HERE, 'board_placed_19nov.kicad_pcb')

@pytest.fixture(scope='module')
def bare():
    B = bd.Board(NEW); B.text = setup6.convert(B.text); B._parse(); B.remove([s['uuid'] for s in B.segs] + [v['uuid'] for v in B.vias]); return B
@pytest.fixture(scope='module')
def linked(bare):
    neighbour_links.run.failed = set(); added = neighbour_links.run(bare, log=lambda *_: None); return bare, added

def test_reader_counts():
    B = bd.Board(OLD); assert len(B.vias) == 137 and len(B.fps) > 150 and B.copper_layers == ['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu']
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
    assert {f['net'] for f in failed} <= {'REF'} and all('U4.10' in f['pad'] for f in failed)
    assert checks.clearances(B) == [] and checks.holes(B) == [] and checks.no_via_pads(B) == []
    gnd = [p for p in B.pads if p['net'] == 'GND' and drops.smd_top(p) and p['ref'] not in bd.NO_VIA_REFS and not p['ref'].startswith('TP')]
    assert all(drops.has_via(B, p) for p in gnd)
    assert all((v['size'] - v['drill']) / 2 >= 0.1 - 1e-9 for v in B.vias)
    assert [u for u in checks.unconnected(B) if u['net'] == 'GND'] == []
def test_mirror_route_copies_connectivity(linked):
    B, _ = linked; todo, skipped = mirror_route.run(B)
    assert len(todo) >= 20 and checks.clearances(B) == []
    pc = lambda nets: {u['net']: u['pieces'] for u in checks.unconnected(B, nets)}
    a = pc([t['net'] for t in todo]); b = pc([t['twin'] for t in todo])
    assert all(a.get(t['net'], 1) == b.get(t['twin'], 1) for t in todo)
