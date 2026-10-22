"""Rebuild report charts from the cited frozen study and explicit case workflow.

No model training, new benchmark or human-rating generation is performed.
"""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/figures'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11, 'axes.spines.top':False,'axes.spines.right':False})

def event_chart():
    # docs/事件时序模型v2评估.md, section 4; 600 events per cohort.
    series=[('Frozen v1',[.6125,.6111,.5880,.5126,.5068],'#8e9cae'),
            ('Mixed aggregate',[.6689,.6263,.5997,.6221,.5686],'#52979a'),
            ('Mixed temporal v2',[.7668,.7619,.7228,.7528,.6505],'#223e5a'),
            ('Shuffled labels',[.2010,.1962,.1956,.2098,.1692],'#cfac7e')]
    fig,ax=plt.subplots(figsize=(10,4.2),layout='constrained')
    x=np.arange(5);width=.19
    for j,(name,values,color) in enumerate(series):
        ax.bar(x+(j-1.5)*width,values,width,label=name,color=color)
    ax.set_xticks(x,['Nominal\nnew assets','Other\nnew assets','Unseen\nexcitation','Covered\nstress','Extreme\nstress'])
    ax.set_ylim(0,1);ax.set_ylabel('Macro-F1 over 11 labels');ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    ax.legend(ncols=2,loc='upper center',frameon=False,fontsize=10)
    fig.savefig(OUT/'final-event-comparison.png',dpi=220);plt.close(fig)

def case_flow():
    fig,ax=plt.subplots(figsize=(10,3.8));ax.set_xlim(0,10);ax.set_ylim(0,3.8);ax.axis('off')
    boxes=[(.05,2.05,'1  Observe','20 C for 90 min\nMKT 19 C; intact packaging'),
           (3.4,2.05,'2  Preserve rule result','Rule 3: scrap\nOriginal assessment retained'),
           (6.75,2.05,'3  Exercise review gate','Pending: preview blocked\nScripted review: scrap retained'),
           (6.75,.15,'4  Adopt replacement','V02 spare vehicle selected\n23.22 km; ETA 556.14 min'),
           (3.4,.15,'5  Record execution','Replacement delivered\nOriginal order stays scrapped'),
           (.05,.15,'6  Close and retain audit','Case closed after delivery\nGraph not verified in this run')]
    for x,y,title,body in boxes:
        ax.add_patch(FancyBboxPatch((x,y),3.15,1.4,boxstyle='round,pad=0.02,rounding_size=0.06',facecolor='#f0f4f7',edgecolor='#a1adba',linewidth=1))
        ax.text(x+.16,y+1.04,title,fontsize=11.5,fontweight='bold',color='#142b45')
        ax.text(x+.16,y+.55,body,fontsize=10.5,linespacing=1.5,va='center',color='#243444')
    for a,b in [((3.21,2.75),(3.36,2.75)),((6.56,2.75),(6.71,2.75)),((8.32,2.02),(8.32,1.6)),((6.71,.85),(6.57,.85)),((3.36,.85),(3.22,.85))]:
        ax.annotate('',xy=b,xytext=a,arrowprops={'arrowstyle':'-|>','color':'#45566c','lw':1.7})
    fig.subplots_adjust(left=.005,right=.995,bottom=.01,top=.99)
    fig.savefig(OUT/'final-case-flow.png',dpi=220);plt.close(fig)

def architecture():
    fig,ax=plt.subplots(figsize=(9.6,4.5))
    ax.set_xlim(0,9.6);ax.set_ylim(0,4.5);ax.axis('off')
    boxes=[(.2,3.15,'M1  Inputs','Orders, assets and scenarios'),
           (3.65,3.15,'M2  Exposure','Intervals, excursions and MKT'),
           (7.1,3.15,'M3  Decisions','Rules and human review'),
           (.2,1.05,'M4  Models','Risk and cause candidates'),
           (3.65,1.05,'M6  Evidence','Graph queries and bounded QA'),
           (7.1,1.05,'M5  Dispatch','Plans, replacement and delivery')]
    for x,y,title,body in boxes:
        ax.add_patch(FancyBboxPatch((x,y),2.3,.92,boxstyle='round,pad=0.02,rounding_size=0.05',facecolor='#f0f4f7',edgecolor='#9aaaba'))
        ax.text(x+1.15,y+.63,title,ha='center',va='center',fontsize=11.5,fontweight='bold',color='#142b45')
        ax.text(x+1.15,y+.27,body,ha='center',va='center',fontsize=8.2,color='#243444')
    def arrow(points,dashed=False):
        xs,ys=zip(*points)
        ax.plot(xs[:-1],ys[:-1],color='#53677e',lw=1.2,ls='--' if dashed else '-')
        ax.annotate('',xy=points[-1],xytext=points[-2],arrowprops={'arrowstyle':'-|>','color':'#53677e','lw':1.2,'linestyle':'--' if dashed else '-'})
    for a,b in [((2.53,3.61),(3.6,3.61)),((5.98,3.61),(7.05,3.61)),((1.35,3.12),(1.35,2.02)),((8.25,3.12),(8.25,2.02))]:
        arrow([a,b])
    arrow([(2.53,1.51),(2.95,1.51),(2.95,2.75),(7.35,2.75),(7.35,3.12)],True)
    ax.text(5.1,2.84,'Advisory candidates; no automatic disposition',ha='center',fontsize=8.5,color='#53677e')
    arrow([(7.65,3.12),(7.65,2.35),(4.8,2.35),(4.8,2.02)])
    ax.text(6.05,2.44,'Recorded case and evidence',ha='center',fontsize=8.5,color='#53677e')
    arrow([(7.05,1.51),(6,1.51)])
    ax.text(6.52,1.7,'Delivery state',ha='center',fontsize=8,color='#53677e')
    ax.add_patch(FancyBboxPatch((.2,.15),9.2,.48,boxstyle='round,pad=0.02,rounding_size=0.05',facecolor='#233f56',edgecolor='#233f56'))
    ax.text(4.8,.39,'M7  API, operator interface, persistent storage, audit and deployment',ha='center',va='center',fontsize=10.5,color='white')
    fig.subplots_adjust(left=.005,right=.995,bottom=.01,top=.99)
    fig.savefig(OUT/'final-architecture-clean.png',dpi=220);plt.close(fig)

if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    event_chart();case_flow();architecture()
