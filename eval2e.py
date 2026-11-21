import sys,math,os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # board.py and r6render.py sit beside this file
import board as bd, checks, mirror_route, r6render as R
import matplotlib.pyplot as plt
from shapely.geometry import LineString
from shapely.ops import unary_union
w=sys.argv[1]; B=bd.Board(f'{w}/board.kicad_pcb'); later=mirror_route.waits_for_copy(B)
sig=bd.is_signal
ln=lambda l,f=lambda n:True:round(sum(math.dist((s['x1'],s['y1']),(s['x2'],s['y2'])) for s in B.segs if s['layer']==l and f(s['net'])),1)
hz=unary_union([g for n_,g,k,o in B.copper('F.Cu') if bd.is_hz(n_)]).buffer(1.0)
for n in sorted({s['net'] for s in B.segs if sig(s['net'])}):
    gs=[(LineString([(s['x1'],s['y1']),(s['x2'],s['y2'])]),s['w']) for s in B.segs if s['net']==n and s['layer']=='F.Cu']
    if not gs: continue
    pinch=[(checks.label(p),round(min(g.distance(B.pad_geom(p))-w_/2 for g,w_ in gs),2)) for p in B.pads if p['net']!=n and 'F.Cu' in p['layers'] and min(g.distance(B.pad_geom(p))-w_/2 for g,w_ in gs)<0.25]
    nh=sum(g.intersection(hz).length for g,w_ in gs)
    if len(pinch)>=2 or nh>3: print(' ',n,'pinch',pinch,'hz-run',round(nh,1))
un=[u['net'] for u in checks.unconnected(B) if u['net'] not in later and not u['net'].startswith('/Bridge') and not all(checks.tp_only(g) for g in checks.pad_groups(B,u['net'])[1:])]
print('vias',len(B.vias),'signal',sum(1 for v in B.vias if sig(v['net'])),'| top sig',ln('F.Cu',sig),'L3 sig',ln('In2.Cu',sig),'| open beyond TPs',un,'clr',len(checks.clearances(B)),'hz',len(checks.hz_rule(B)))
fig=plt.figure(figsize=(19.5,8))
for i,(win,l,t) in enumerate([((0,22,0,25),'F.Cu','Top: servo block'),((0,22,21,46),'F.Cu','Top: Q103/Q104 block and U3'),((0,22,21,46),'In2.Cu','L3, same area')]):
    ax=R.panel(fig,[0.003+0.333*i,0.02,0.328,0.92],win); R.draw(ax,B,l,win,t,netlabels=True)
plt.savefig(f'{w}/2e_zoom2.png',dpi=75)
