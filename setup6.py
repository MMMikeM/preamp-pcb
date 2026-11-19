"""Step 1: turn the 4-layer board into the 6-layer starting point.
 - adds In3.Cu / In4.Cu, sets JLC's default 6-layer 1.6 mm stackup
 - ground zones on In1 (L2), In3 (L4), In4 (L5, lowest priority under the power copper) and B.Cu (L6); the old In2 zone goes (L3 = hops)
 - rips all tracks and vias, except top-only routing of the nets named in --keep that is still fully connected and legal
usage: setup6.py IN OUT [--keep GA GB GA_M GB_M VB]"""
import sys, re, argparse, uuid
import board as bd

STACK = '''		(stackup
			(layer "F.SilkS" (type "Top Silk Screen"))
			(layer "F.Paste" (type "Top Solder Paste"))
			(layer "F.Mask" (type "Top Solder Mask") (thickness 0.01))
			(layer "F.Cu" (type "copper") (thickness 0.035))
			(layer "dielectric 1" (type "prepreg") (thickness 0.0994) (material "FR4") (epsilon_r 4.1) (loss_tangent 0.02))
			(layer "In1.Cu" (type "copper") (thickness 0.0152))
			(layer "dielectric 2" (type "core") (thickness 0.55) (material "FR4") (epsilon_r 4.6) (loss_tangent 0.02))
			(layer "In2.Cu" (type "copper") (thickness 0.0152))
			(layer "dielectric 3" (type "prepreg") (thickness 0.1164) (material "FR4") (epsilon_r 4.16) (loss_tangent 0.02))
			(layer "In3.Cu" (type "copper") (thickness 0.0152))
			(layer "dielectric 4" (type "core") (thickness 0.55) (material "FR4") (epsilon_r 4.6) (loss_tangent 0.02))
			(layer "In4.Cu" (type "copper") (thickness 0.0152))
			(layer "dielectric 5" (type "prepreg") (thickness 0.0994) (material "FR4") (epsilon_r 4.1) (loss_tangent 0.02))
			(layer "B.Cu" (type "copper") (thickness 0.035))
			(layer "B.Mask" (type "Bottom Solder Mask") (thickness 0.01))
			(layer "B.Paste" (type "Bottom Solder Paste"))
			(layer "B.SilkS" (type "Bottom Silk Screen"))
			(copper_finish "None")
			(dielectric_constraints no)
		)
'''
def block(text, start):
    depth = 0; j = start
    while True:
        c = text[j]
        if c == '"':
            j += 1
            while text[j] != '"': j += 2 if text[j] == '\\' else 1
        elif c == '(': depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0: return j + 1
        j += 1

def convert(text):
    if '"In3.Cu"' not in text.split('(setup')[0]:
        text = text.replace('\t\t(6 "In2.Cu" signal)\n', '\t\t(6 "In2.Cu" signal)\n\t\t(8 "In3.Cu" signal)\n\t\t(10 "In4.Cu" signal)\n', 1)
    s = text.index('\t\t(stackup'); e = block(text, s + 2)
    text = text[:s] + STACK + text[e + 1:]
    zones = {}
    for m in list(re.finditer(r'\n\t\(zone\n', text))[::-1]:                 # back to front so offsets stay valid
        s = m.start() + 1; e = block(text, s); z = text[s:e]
        name = re.search(r'\(name "([^"]*)"\)', z).group(1)
        z2 = z
        while True:                                                          # drop stale fills
            i = z2.find('\n\t\t(filled_polygon')
            if i < 0: break
            z2 = z2[:i] + z2[block(z2, i + 3):]
        zones[name] = z2
        text = text[:s] + (z2 + '\n' if name != 'GND_In2' else '') + text[e + 1:]
    src = zones.get('GND_In1')
    if src is None: raise SystemExit('no GND_In1 zone to copy')
    new = ''
    for lay, nm in (('In3.Cu', 'GND_In3'), ('In4.Cu', 'GND_In4')):
        if nm in zones: continue
        z = src.replace('(layer "In1.Cu")', f'(layer "{lay}")').replace('(name "GND_In1")', f'(name "{nm}")')
        z = re.sub(r'\(uuid "[^"]+"\)', lambda _: f'(uuid "{uuid.uuid4()}")', z)
        new += z + '\n'
    i = text.rstrip().rfind(')'); return text[:i] + new + ')\n'

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('inp'); ap.add_argument('out'); ap.add_argument('--keep', nargs='*', default=['GA', 'GB', 'GA_M', 'GB_M', 'VB'])
    a = ap.parse_args(); B = bd.Board(a.inp); B.text = convert(B.text); B._parse()
    import checks
    keep = set()
    for net in B.nets:
        if net.split('/')[-1] not in a.keep: continue
        if any(v['net'] == net for v in B.vias) or any(s['net'] == net and s['layer'] != 'F.Cu' for s in B.segs): continue
        keep.add(net)
    B.remove([s['uuid'] for s in B.segs if s['net'] not in keep] + [v['uuid'] for v in B.vias])
    bad = {u['net'] for u in checks.unconnected(B, keep)} | {c['a_net'] for c in checks.clearances(B) if c['a_net'] in keep} | {c['b_net'] for c in checks.clearances(B) if c['b_net'] in keep}
    if bad: B.remove([s['uuid'] for s in B.segs if s['net'] in bad])
    print('layers', B.copper_layers, '| zones', [(z['name'], z['layers']) for z in B.zones])
    print('kept routing:', sorted(keep - bad), '| ripped because broken or illegal:', sorted(bad & keep), '| tracks left', len(B.segs))
    B.save(a.out, crlf=False)
