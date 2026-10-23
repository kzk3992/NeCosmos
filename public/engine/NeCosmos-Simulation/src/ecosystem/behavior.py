"""Persistent utility/FSM observer over committed ecology actions.

Daily budgets remain in Ecology.step; this controller labels their decisions without
replacing species equations. Goals persist until arrival, completion or danger.
No additional random draws and no dependency on cameras or real time.
"""
STATES = ('idle','seekFood','move','eat','rest','explore','socialize','avoidDanger','interact')


def update(eco, w, day):
    p=eco.pop
    previous=getattr(eco,'behavior',{})
    from .spatial import SpatialIndex
    index=None
    result={}
    for k in range(len(p)):
        cid=int(p.id[k]);sp=int(p.sp[k]);j=int(p.j[k]);i=int(p.i[k])
        hunger=max(0.,1.-float(p.energy[k]));stress=float(p.stress[k])
        old=previous.get(cid)
        fatigue=min(1.,max(0.,(old or {}).get('fatigue',0.) + (.15 if (old or {}).get('travelled',False) else -.1)))
        if old and day < old['until'] and stress < .004 and hunger < .7 and int(p.action[k]) == 0:
            # Continue a safe commitment without rebuilding/evaluating utility
            # scores. Movement still uses the unchanged species opportunity.
            result[cid]={'state':old['state'],'goal':[j,i],'since':old['since'],
                         'fatigue':fatigue,'until':old['until']}
            continue
        if index is None:index=SpatialIndex(p.j,p.i,p.id)
        nearby=len(index.nearby(j,i,cross=True))-1
        resource=float(w['G'][j,i] if sp in (1,5,6) else w['O'][j,i]+w['R'][j,i])
        scores={'idle':.1,'seekFood':hunger*(1+min(resource,1)), 'rest':.15+fatigue*.6,
                'explore':.2+(cid%17)/100, 'socialize':min(nearby,5)*(.15 if sp in (3,7) else .03),
                'avoidDanger':stress*100, 'interact':.7 if sp==4 and day%300==0 else 0}
        state=max(scores,key=scores.get);a=int(p.action[k]);old=previous.get(cid)
        # Confirmed actions win over intentions. A minimum two-day commitment avoids
        # needless re-evaluation churn; danger and hunger may interrupt immediately.
        if a in (1,6):state='move'
        elif a in (3,4):state='eat'
        elif a==2:state='rest'  # stationary photosynthesis remains species-specific
        elif a==5:state='interact'
        elif old and day < old['until'] and stress < .004 and hunger < .7:state=old['state']
        result[cid]={'state':state,'goal':[j,i], 'since':old['since'] if old and old['state']==state else day,
                     'fatigue':fatigue, 'until':old['until'] if old and old['state']==state else day+2}
    eco.behavior=result
    return result
