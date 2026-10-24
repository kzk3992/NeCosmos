"""Utility decisions over a start-of-day snapshot; never mutates resource pools.

Actions select destinations, not intake: Ecology owns all proportional allocations.
Counter stream 12 is reserved for immutable personality; stream 13 for exploration.
Commitments expire, arrive, lose a target/resource, or yield to survival interrupts.
"""
import json
from pathlib import Path
import numpy as np
from ..coupling import rng

STATES = ('idle','seekFood','moving','eating','resting','exploring','socializing','avoidingDanger','interacting')
ALIASES = dict(move='moving',eat='eating',rest='resting',explore='exploring',socialize='socializing',avoidDanger='avoidingDanger',interact='interacting')
DEFAULTS = json.loads((Path(__file__).resolve().parents[2]/'configs/species/behavior.json').read_text())


def initialize(eco, seed):
    """Lazy migration also covers children, without consuming any sequential RNG."""
    traits = getattr(eco, 'personalities', {})
    p=eco.pop
    missing=[k for k,cid in enumerate(p.id) if int(cid) not in traits]
    if missing:
        ids=p.id[missing]; born=p.born[missing]
        values=rng.u01(seed,12,born[:,None],ids[:,None]*3+np.arange(3)).reshape(-1,3)
        for k,v in zip(missing,values):
            traits[int(p.id[k])]=dict(zip(('curiosity','sociability','vigilance'),map(float,v)))
    # Only living personalities are needed; the birth ledger preserves identity.
    living=set(map(int,p.id))
    eco.personalities={cid:v for cid,v in traits.items() if cid in living}
    if not hasattr(eco,'behavior_config'):eco.behavior_config=json.loads(json.dumps(DEFAULTS))


def resource(eco,w,sp):
    d=w.get('_decision_resources',w)
    if sp==1:return d['G']
    if sp==5:return d['G']*(w['moist']<.72)
    if sp==6:
        v=lambda x:x[0] if isinstance(x,list) else x
        hab=(w['h']>=v(eco.S['sakana']['habitat_depth_m']))|(w['theta']>=v(eco.S['sakana']['habitat_sat']))
        return d['G']*hab
    if sp==3:return d['O']
    if sp in (2,7):
        v=lambda x:x[0] if isinstance(x,list) else x
        cfg=eco.S['kinoko' if sp==2 else 'slime'];m=w['moist']
        fast=v(cfg['fast_rate'])*((.45+m) if sp==2 else (.5+m)*(.65+v(cfg['decomposer'])*.7))
        slow=v(cfg['slow_rate'])*((.45+m) if sp==2 else (.5+m))*v(cfg['decomposer'])
        return np.minimum(d['O'],fast)+np.minimum(d['R'],slow)
    return w['N']



def update(eco, w, day, seed=0):
    initialize(eco,seed)
    p=eco.pop;previous=getattr(eco,'behavior',{});cfg=eco.behavior_config;weights=cfg['weights']
    from .spatial import SpatialIndex
    index=None;result={};evaluated=0;foods={sp:resource(eco,w,sp) for sp in set(map(int,p.sp))};id_to_k={int(cid):k for k,cid in enumerate(p.id)}
    for k in range(len(p)):
        cid=int(p.id[k]);sp=int(p.sp[k]);j=int(p.j[k]);i=int(p.i[k]);traits=eco.personalities[cid]
        old=dict(previous.get(cid,{}));old['state']=ALIASES.get(old.get('state'),old.get('state','idle'))
        hunger=max(0.,1.-float(p.energy[k]));stress=float(p.stress[k]);temp=float(w['T'][j,i])
        fatigue=min(1.,max(0.,old.get('fatigue',0.)+(.15 if old.get('travelled',False) else -.1)))
        food=foods[sp];goal=list(old.get('goal',[j,i]));gj,gi=goal
        valid=(0<=gj<food.shape[0] and 0<=gi<food.shape[1] and bool(w['unlocked'][gj,gi]))
        if valid and w.get('obstacles') is not None:valid=not w['obstacles'][gj,gi] or sp==5
        if old.get('targetId') is not None and old['targetId'] not in id_to_k:valid=False
        if old.get('intent',old['state'])=='seekFood' and valid:valid=float(food[gj,gi])>0
        emergency=stress>=cfg['emergency_stress'] or hunger>=cfg['emergency_hunger']
        # Arrival completes travel, but the activity remains committed until its
        # deadline. Invalid food/terrain and sudden thermal danger interrupt early.
        signature=(temp<10,temp>31,float(w['moist'][j,i])<.3,float(w['h'][j,i])>eco.wade)
        changed='environment' in old and tuple(old['environment'])!=signature
        if old and day<old.get('nextDecisionDay',old.get('until',day)) and valid and not emergency and not changed:
            old.update(state=old.get('intent',old['state']),fatigue=fatigue,duration=day-old.get('since',day),travelled=False)
            result[cid]=old;continue
        evaluated+=1
        if index is None:index=SpatialIndex(p.j,p.i,p.id)
        neighbors=index.nearby(j,i,cross=True);nearby=max(0,len(neighbors)-1)
        cold=max(0.,15-temp)/15
        species=weights['species']
        scores={'idle':weights['idle'],
                'seekFood':weights['food']*hunger*(1+min(float(food[j,i]),1.)),
                'resting':weights['rest']+weights['fatigue']*fatigue,
                'exploring':weights['explore']+weights['curiosity']*traits['curiosity'],
                'socializing':weights['social']*traits['sociability']*min(nearby,4)/4+(cold*species if sp==3 and nearby else 0),
                'avoidingDanger':weights['danger']*stress+weights['vigilance']*traits['vigilance']*max(0.,abs(temp-22)-12)/12,
                'interacting':species if sp==0 or (sp==4 and day%300==0) else (species*min(float(food[j,i]),1.) if sp in (2,7) else 0)}
        intent=max(scores,key=scores.get)
        prior=old.get('intent',old['state'])
        if prior in scores and valid and not emergency and scores[intent]<scores[prior]+cfg['hysteresis']:intent=prior
        if stress>=cfg['emergency_stress']:intent='avoidingDanger'
        elif hunger>=cfg['emergency_hunger'] and sp not in (0,4):intent='seekFood'
        goal=[j,i];target_id=None
        # Local destinations are retained until completion; movement still obeys
        # the original species opportunity, slope, obstacles and water checks.
        candidates=[]
        offsets=[(0,0),(0,1),(0,-1),(1,0),(-1,0)] if sp!=5 else [(dj,di) for dj in range(-eco.flight,eco.flight+1) for di in range(-eco.flight,eco.flight+1)]
        for dj,di in offsets:
            a,b=j+dj,i+di
            if not(0<=a<food.shape[0] and 0<=b<food.shape[1] and w['unlocked'][a,b]):continue
            if sp!=5 and w.get('obstacles') is not None and w['obstacles'][a,b]:continue
            if sp!=6 and w['h'][a,b]>eco.wade:continue
            if sp!=5 and abs(w['z'][a,b]-w['z'][j,i])/w['dx']>eco.walk:continue
            candidates.append((a,b))
        if intent=='socializing' and nearby:
            target_id=int(index.nearest(j,i,cid))
            nk=id_to_k[target_id];goal=[int(p.j[nk]),int(p.i[nk])]
        elif candidates:
            if intent=='seekFood':
                goal=list(max(candidates,key=lambda q:float(food[q])))
                if food[tuple(goal)]<=0:
                    goal=(list(max(candidates,key=lambda q:float(w['h'][q])+.05*float(w['theta'][q]))) if sp==6 else list(candidates[int(rng.u01(seed,13,day,cid)[0]*len(candidates))%len(candidates)]))
            elif intent=='avoidingDanger':goal=list(min(candidates,key=lambda q:max(0.,13-float(w['T'][q]))+max(0.,float(w['T'][q])-31)))
            elif intent=='exploring':goal=list(candidates[int(rng.u01(seed,13,day,cid)[0]*len(candidates))%len(candidates)])
            elif sp==6:goal=list(max(candidates,key=lambda q:float(w['h'][q])+.05*float(w['theta'][q])))
        same=old.get('intent')==intent and old.get('goal')==goal
        since=old.get('since',day) if same else day
        deadline=day+cfg['hold_days']+(cid%2) # deterministic staggering
        result[cid]=dict(state=intent,intent=intent,goal=goal,targetId=target_id,since=since,
                         duration=day-since,nextDecisionDay=deadline,until=deadline,fatigue=fatigue,
                         environment=list(signature),scores=scores,activity=cfg['species_activity'][sp],travelled=False)
    eco.behavior=result;eco.ai_evaluations=evaluated
    return result
