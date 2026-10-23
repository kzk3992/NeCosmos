"""Supported terrain/climate numerical audit; explicit checkpoints, no balance tuning."""
import sys,json,time,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'NeCosmos-Simulation'));sys.path.insert(0,str(ROOT/'public/engine'))
import bridge
bridge.FROZEN=str(ROOT/'NeCosmos-Simulation/configs/scenarios/frozen.json')
from src.coupling.simulation import SP
out=[]
for terrain in ('flat','hills','valley','depression','initial_river','mountain'):
 for climate in ('tundra','wet','dry','cold','moss'):
  for seed in (31001,31002):
   bridge.new_world(json.dumps(dict(terrain=terrain,climate=climate,composition='all8',seed=seed,weatherMode='normal')))
   sim=bridge.STATE['sim'];peak=len(sim.eco.pop);max_res={k:0 for k in ('water','soil','matter')};t=time.perf_counter();checkpoints=[]
   for day in range(1,1001):
    row=sim.step();peak=max(peak,len(sim.eco.pop))
    assert len(sim.eco.pop)<=200
    for k in max_res:
     v=abs(row['res_'+k+('_kg' if k=='matter' else '_m3')]);assert math.isfinite(v) and v<1e-8;max_res[k]=max(max_res[k],v)
    if day in (500,1000):checkpoints.append(dict(day=day,counts={sp:int((sim.eco.pop.sp==i).sum()) for i,sp in enumerate(SP)}))
   out.append(dict(terrain=terrain,climate=climate,seed=seed,peak=peak,checkpoints=checkpoints,residual=max_res,seconds=time.perf_counter()-t))
   Path('artifacts/oct23/matrix.json').write_text(json.dumps(out,indent=2));print(terrain,climate,seed,flush=True)
