"""Per-channel comparison of two routed boards: signal track on top / L3 and vias for each channel, then the
nets that changed most. Supply, GND, REF, PB and VR are left out. Usage: python3 compare_channels.py A.kicad_pcb B.kicad_pcb"""
import sys,math; sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
import board as bd
def stats(f):
    B=bd.Board(f); r={}
    sig=lambda n: n and n!='GND' and not bd.is_supply(n) and n not in('REF','PB','/VR')
    ch={}
    for p in B.pads:
        if sig(p['net']): ch.setdefault(p['net'],[]).append(p['x'])
    side=lambda n:'Neck' if sum(ch[n])/len(ch[n])<137 else 'Bridge'
    for s in B.segs:
        if s['net'] in ch: d=r.setdefault(s['net'],[0,0,0]); L=math.dist((s['x1'],s['y1']),(s['x2'],s['y2'])); d[0 if s['layer']=='F.Cu' else 1]+=L
    for v in B.vias:
        if v['net'] in ch: r.setdefault(v['net'],[0,0,0])[2]+=1
    return {n:(side(n),*v) for n,v in r.items()}
a=stats(sys.argv[1]); b=stats(sys.argv[2])
for c in('Neck','Bridge'):
    A=[v for v in a.values() if v[0]==c]; Bv=[v for v in b.values() if v[0]==c]
    f=lambda S:(sum(x[1] for x in S),sum(x[2] for x in S),sum(x[3] for x in S))
    print('%-6s %s: top %.0f L3 %.0f total %.0f vias %d   ->  %s: top %.0f L3 %.0f total %.0f vias %d'%(c,'A',*f(A)[:2],sum(f(A)[:2]),f(A)[2],'B',*f(Bv)[:2],sum(f(Bv)[:2]),f(Bv)[2]))
    ch=sorted(((b.get(n,(c,0,0,0))[1]+b.get(n,(c,0,0,0))[2]-a[n][1]-a[n][2],b.get(n,(c,0,0,0))[3]-a[n][3],n) for n in a if a[n][0]==c),key=lambda t:-abs(t[0])-3*abs(t[1]))[:12]
    for d,dv,n in ch: print('      %-22s %+6.1f mm %+d vias   (%.0f/%d -> %.0f/%d)'%(n,d,dv,a[n][1]+a[n][2],a[n][3],b.get(n,(c,0,0,0))[1]+b.get(n,(c,0,0,0))[2],b.get(n,(c,0,0,0))[3]))
