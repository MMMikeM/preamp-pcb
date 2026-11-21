import sys
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # board.py sits beside this file
import board as bd
import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
COL={'hz':'#c0392b','supply':'#e67e22','signal':'#2471a3','gnd':'#7f8c8d'}
def cls(n): return 'gnd' if n=='GND' else 'hz' if bd.is_hz(n) else 'supply' if bd.is_supply(n) else 'signal'
def draw(ax,B,layer,win,title,labels=True,netlabels=False):
    for r,f in B.fps.items():
        for p in f['pads']:
            if layer not in p['layers']: continue
            if not (win[0]-2<p['x']-100<win[1]+2 and win[2]-2<p['y']-80<win[3]+2): continue
            g=B.pad_geom(p); xs,ys=g.exterior.xy
            ax.fill([x-100 for x in xs],[y-80 for y in ys],fc='#d5d8dc' if layer=='F.Cu' or p['drill'] else '#e8e8e8',ec='#888',lw=0.3,zorder=2)
            if netlabels and layer=='F.Cu': ax.text(p['x']-100,p['y']-80,p['net'].split('/')[-1].replace('Net-(','')[:6],fontsize=5,ha='center',va='center',zorder=7)
        if labels and layer=='F.Cu' and f['layer']=='F.Cu' and not r.startswith('TP') and win[0]<f['x']-100<win[1] and win[2]<f['y']-80<win[3] and not netlabels:
            ax.text(f['x']-100,f['y']-80,r,fontsize=4.5,ha='center',va='center',zorder=7,color='#333')
        if netlabels and layer=='F.Cu' and f['layer']=='F.Cu' and win[0]<f['x']-100<win[1] and win[2]<f['y']-80<win[3]:
            ax.text(f['x']-100,f['y']-80,r,fontsize=6.5,ha='center',va='center',zorder=8,weight='bold',color='#111',bbox=dict(fc='w',ec='none',alpha=0.6,pad=0.3))
    for s in B.segs:
        if s['layer']!=layer: continue
        c=COL[cls(s['net'])]
        ax.plot([s['x1']-100,s['x2']-100],[s['y1']-80,s['y2']-80],color=c,lw=max(s['w']*ax._mmpt,0.6),solid_capstyle='round',zorder=4)
    for v in B.vias:
        ax.add_patch(plt.Circle((v['x']-100,v['y']-80),v['size']/2,fc=COL[cls(v['net'])],ec='k',lw=0.3,zorder=5)); ax.add_patch(plt.Circle((v['x']-100,v['y']-80),v['drill']/2,fc='w',ec='none',zorder=6))
    ax.set_xlim(win[0],win[1]);ax.set_ylim(win[3],win[2]);ax.set_aspect('equal');ax.set_xticks([]);ax.set_yticks([]);ax.set_title(title,fontsize=10)
def panel(fig,rect,win):
    ax=fig.add_axes(rect); w_in=rect[2]*fig.get_figwidth(); ax._mmpt=w_in*72/(win[1]-win[0]); return ax
