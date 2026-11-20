"""Minimal KiCad .kicad_pcb reader/writer for the route6 scripts. Coordinates are KiCad's own (mm, y down).
Only what the routing steps need: pads, tracks, vias, zones (names only) and text-level insert/remove of tracks and vias."""
import re, math, uuid as _uuid
import numpy as np
from shapely.geometry import Point, LineString, box
from shapely import affinity

TOK = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+')
def parse(text):
    stack = [[]]
    for m in TOK.finditer(text):
        t = m.group(0)
        if t == '(': stack.append([])
        elif t == ')': x = stack.pop(); stack[-1].append(x)
        else: stack[-1].append(t[1:-1] if t[0] == '"' else t)
    return stack[0][0]
def find(node, key): return [c for c in node if isinstance(c, list) and c and c[0] == key]
def first(node, key):
    r = find(node, key); return r[0] if r else None
def is_locked(node):
    l = first(node, 'locked'); return 'locked' in node or (l is not None and (len(l) == 1 or l[1] in ('yes', 'true')))

# ---------------------------------------------------------------- project rules
HZ_SUFFIX = ('GA', 'GB', 'GA_M', 'GB_M', 'VB', 'SVN', 'SVP', 'SVN_I', 'SVP_I', 'SVN_R', 'SVP_R')
def is_hz(net): return net.split('/')[-1] in HZ_SUFFIX
GROUND = {'GND'}
RAILS = {'V+', 'V-'}
BIAS = {'REF', 'PB', 'VR'}
def is_supply(net): return net in RAILS or net in BIAS or 'BAT' in net
NO_VIA_REFS = {'R109', 'R117', 'R209', 'R217'}          # hand-swapped parts: no via in their pads
LAYERS6 = ['F.Cu', 'In1.Cu', 'In2.Cu', 'In3.Cu', 'In4.Cu', 'B.Cu']   # L1..L6
CLEAR = 0.2; CLEAR_HZ = 0.4
EDGE = 0.5                                              # copper to board edge
HOLE_GAP = 0.25                                         # drill edge to drill edge
TOL = 1e-3                                              # the checks report a breach only beyond this
def edge_room(outline, x, y, half):
    """distance from the board edge to copper of half-width `half` centred on x, y (numbers or arrays)"""
    x0, y0, x1, y1 = outline; return np.minimum.reduce([x - x0, x1 - x, y - y0, y1 - y]) - half
def clearance(a, b): return CLEAR_HZ if (is_hz(a) or is_hz(b)) else CLEAR

def channel_shift(B, tol=0.02):
    """How far the second channel's parts (X2nn) sit to the right of their first-channel twins (X1nn), read from the placement:
    the commonest offset among twins that are level with each other and not mirrored about the board centre. None if there is none."""
    x0, _, x1, _ = B.outline(); cx = (x0 + x1) / 2; seen = {}
    for r, f in B.fps.items():
        m = re.match(r'([A-Z]+)1(\d\d)$', r); t = B.fps.get(f'{m.group(1)}2{m.group(2)}') if m and not r.startswith('TP') else None
        if not t or abs(f['y'] - t['y']) > tol or abs(2 * cx - f['x'] - t['x']) < tol: continue
        d = round(t['x'] - f['x'], 2); seen[d] = seen.get(d, 0) + 1
    return max(seen, key=seen.get) if seen else None

def rot(x, y, r):
    t = math.radians(r); c, s = math.cos(t), math.sin(t)
    return x * c + y * s, -x * s + y * c

class Board:
    def __init__(self, path):
        raw = open(path, encoding='utf-8', newline='').read()
        self.path = path; self.crlf = '\r\n' in raw; self.text = raw.replace('\r', '')
        self._parse()
    def _parse(self):
        B = parse(self.text); self.pads = []; self.fps = {}; self.segs = []; self.vias = []; self.zones = []
        self._outline = None; self._copper = {}
        arcs = len(find(B, 'arc'))
        if arcs: raise ValueError(f'{self.path}: {arcs} arc tracks. route6 reads straight tracks only, so it could neither check nor rip them; straighten them in KiCad first.')
        for fp in find(B, 'footprint'):
            at = first(fp, 'at'); fx, fy = float(at[1]), float(at[2]); fr = float(at[3]) if len(at) > 3 else 0.0
            ref = next(p[2] for p in find(fp, 'property') if p[1] == 'Reference')
            val = next(p[2] for p in find(fp, 'property') if p[1] == 'Value')
            self.fps[ref] = dict(ref=ref, val=val, x=fx, y=fy, r=fr, layer=first(fp, 'layer')[1], pads=[])
            for p in find(fp, 'pad'):
                pa = first(p, 'at'); dx, dy = rot(float(pa[1]), float(pa[2]), fr)
                # the file stores a pad's angle as absolute (footprint rotation included), so a missing angle means 0
                sz = first(p, 'size'); n = first(p, 'net'); pr = float(pa[3]) if len(pa) > 3 else 0.0
                w, h = float(sz[1]), float(sz[2])
                if round(pr / 90) % 2: w, h = h, w
                d = first(p, 'drill'); lay = first(p, 'layers')[1:]
                cu = set(LAYERS6) if any(l == '*.Cu' for l in lay) else {l for l in lay if l.endswith('.Cu')}
                if any(l == 'F&B.Cu' for l in lay): cu |= {'F.Cu', 'B.Cu'}
                pad = dict(ref=ref, num=p[1], x=fx + dx, y=fy + dy, w=w, h=h, net=(n[-1] if n else ''), kind=p[2], shape=p[3],
                           drill=(float(d[-1]) if d and len(d) > 1 else 0.0), layers=cu,
                           rr=(float(first(p, 'roundrect_rratio')[1]) if first(p, 'roundrect_rratio') else 0.0))
                if pad['kind'] == 'np_thru_hole': pad['net'] = ''
                self.pads.append(pad); self.fps[ref]['pads'].append(pad)
        for s in find(B, 'segment'):
            a, b = first(s, 'start'), first(s, 'end')
            self.segs.append(dict(x1=float(a[1]), y1=float(a[2]), x2=float(b[1]), y2=float(b[2]), w=float(first(s, 'width')[1]),
                                  layer=first(s, 'layer')[1], net=first(s, 'net')[-1], uuid=first(s, 'uuid')[1], locked=is_locked(s)))
        for v in find(B, 'via'):
            a = first(v, 'at')
            self.vias.append(dict(x=float(a[1]), y=float(a[2]), size=float(first(v, 'size')[1]), drill=float(first(v, 'drill')[1]),
                                  net=first(v, 'net')[-1], uuid=first(v, 'uuid')[1], locked=is_locked(v)))
        for z in find(B, 'zone'):
            nm = first(z, 'name'); l = first(z, 'layer') or first(z, 'layers')
            poly = first(z, 'polygon'); cp = first(z, 'connect_pads'); cl = first(cp, 'clearance') if cp else None; mt = first(z, 'min_thickness')
            self.zones.append(dict(net=first(z, 'net')[-1], name=nm[1] if nm else '', layers=l[1:],
                                   pts=[(float(q[1]), float(q[2])) for q in find(first(poly, 'pts'), 'xy')] if poly else [],
                                   clearance=float(cl[1]) if cl else 0.0, min_thickness=float(mt[1]) if mt else 0.0))
        self.copper_layers = [l[1] for l in first(B, 'layers')[1:] if l[1].endswith('.Cu')]
        self.nets = sorted({p['net'] for p in self.pads if p['net']})
    # ---- geometry
    @staticmethod
    def pad_geom(p):
        if p['shape'] == 'circle': return Point(p['x'], p['y']).buffer(p['w'] / 2, 16)
        if p['shape'] == 'oval':
            r = min(p['w'], p['h']) / 2; dx, dy = max(p['w'] / 2 - r, 0), max(p['h'] / 2 - r, 0)
            return LineString([(p['x'] - dx, p['y'] - dy), (p['x'] + dx, p['y'] + dy)]).buffer(r, 8) if dx or dy else Point(p['x'], p['y']).buffer(r, 16)
        r = p.get('rr', 0) * min(p['w'], p['h']) if p['shape'] == 'roundrect' else 0
        if r > 1e-6: return box(p['x'] - p['w'] / 2 + r, p['y'] - p['h'] / 2 + r, p['x'] + p['w'] / 2 - r, p['y'] + p['h'] / 2 - r).buffer(r, 8)
        return box(p['x'] - p['w'] / 2, p['y'] - p['h'] / 2, p['x'] + p['w'] / 2, p['y'] + p['h'] / 2)
    @staticmethod
    def seg_geom(s): return LineString([(s['x1'], s['y1']), (s['x2'], s['y2'])]).buffer(s['w'] / 2, 8)
    @staticmethod
    def via_geom(v): return Point(v['x'], v['y']).buffer(v['size'] / 2, 16)
    def copper(self, layer):
        """[(net, geom, kind, obj)] of all copper on one layer (zones excluded). Shared until the next edit: do not change the list."""
        if layer in self._copper: return self._copper[layer]
        out = [(p['net'], self.pad_geom(p), 'pad', p) for p in self.pads if layer in p['layers']]
        out += [(s['net'], self.seg_geom(s), 'seg', s) for s in self.segs if s['layer'] == layer]
        out += [(v['net'], self.via_geom(v), 'via', v) for v in self.vias]
        self._copper[layer] = out; return out
    def outline(self):
        if self._outline: return self._outline
        xs = []; ys = []
        for m in re.finditer(r'\(gr_(?:line|arc|rect)[^()]*(?:\([^()]*\)[^()]*)*?\(layer "Edge.Cuts"\)', self.text): pass
        B = parse(self.text)
        for k in ('gr_line', 'gr_arc', 'gr_rect'):
            for g in find(B, k):
                if first(g, 'layer')[1] != 'Edge.Cuts': continue
                for q in ('start', 'end', 'mid'):
                    a = first(g, q)
                    if a: xs.append(float(a[1])); ys.append(float(a[2]))
        self._outline = (min(xs), min(ys), max(xs), max(ys)); return self._outline
    # ---- text-level edits (keeps everything else in the file byte-identical)
    @staticmethod
    def _f(v): return ('%.4f' % v).rstrip('0').rstrip('.')
    def seg_text(self, x1, y1, x2, y2, w, layer, net, uuid=None):
        f = self._f
        return (f'\t(segment\n\t\t(start {f(x1)} {f(y1)})\n\t\t(end {f(x2)} {f(y2)})\n\t\t(width {f(w)})\n\t\t(layer "{layer}")\n'
                f'\t\t(net "{net}")\n\t\t(uuid "{uuid or _uuid.uuid4()}")\n\t)\n')
    def via_text(self, x, y, size, drill, net, layers=('F.Cu', 'B.Cu'), uuid=None):
        f = self._f
        return (f'\t(via\n\t\t(at {f(x)} {f(y)})\n\t\t(size {f(size)})\n\t\t(drill {f(drill)})\n\t\t(layers "{layers[0]}" "{layers[1]}")\n'
                f'\t\t(net "{net}")\n\t\t(uuid "{uuid or _uuid.uuid4()}")\n\t)\n')
    def add(self, chunks):
        i = self.text.rstrip().rfind(')'); self.text = self.text[:i] + ''.join(chunks) + ')\n'; self._parse()
    def _track_blocks(self):
        """(start, last character, uuid) of every track and via block in the text"""
        for m in re.finditer(r'\n\t\((segment|via)\b', self.text):
            s = m.start() + 1; depth = 0; j = s
            while True:
                c = self.text[j]
                if c == '(': depth += 1
                elif c == ')':
                    depth -= 1
                    if depth == 0: break
                j += 1
            u = re.search(r'\(uuid "([^"]+)"\)', self.text[s:j + 1])
            yield s, j, u.group(1) if u else None
    def remove(self, uuids):
        uuids = set(uuids); out = []; pos = 0; n = 0
        for s, j, u in self._track_blocks():
            if u in uuids:
                out.append(self.text[pos:s]); pos = j + 2; n += 1
        out.append(self.text[pos:]); self.text = ''.join(out); self._parse(); return n
    def _rewrite(self, uuids, edit):
        uuids = set(uuids); out = []; pos = 0; done = []
        for s, j, u in self._track_blocks():
            if u not in uuids: continue
            old = self.text[s:j + 1]; new = edit(old)
            if new != old: out += [self.text[pos:s], new]; pos = j + 1; done.append(u)
        out.append(self.text[pos:]); self.text = ''.join(out); self._parse(); return done
    def lock(self, uuids):
        """Marks these tracks and vias as locked, the way KiCad does. Returns the ones it locked: a piece that was locked already is
        not in the list, so handing the list to unlock() leaves the user's own locks alone."""
        return self._rewrite(uuids, lambda blk: blk if re.search(r'\blocked\b', blk) else re.sub(r'(\n\t\t)(\(layers? )', r'\1(locked yes)\1\2', blk, count=1))
    def unlock(self, uuids):
        return self._rewrite(uuids, lambda blk: blk.replace('\n\t\t(locked yes)', '', 1))
    def save(self, path=None, crlf=None):
        path = path or self.path
        if crlf is None: crlf = self.crlf
        with open(path, 'w', encoding='utf-8', newline='') as fh: fh.write(self.text.replace('\n', '\r\n') if crlf else self.text)
