"""Read-only multi-seed audit; run against either checkout via --root."""
import sys,json,time,argparse,collections,statistics
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',default=str(Path(__file__).resolve().parents[1]));p.add_argument('--out',required=True);p.add_argument('--days',type=int,default=10000);a=p.parse_args()
root=Path(a.root);sys.path.insert(0,str(root/'NeCosmos-Simulation'))
from src.coupling.simulation import Simulation,SP
ov=json.loads((root/'NeCosmos-Simulation/configs/scenarios/frozen.json').read_text())['overrides']
results=[]
for seed in (21001,21002,21003):
 s=Simulation(dict(terrain='hills',climate='wet',composition='all8',seed=seed,days=a.days,weather_mode='normal',max_population=200,overrides=ov,unlock='fixed'))
 births=collections.Counter(); checkpoints=[];peak=len(s.eco.pop);t=time.perf_counter()
 for day in range(1,a.days+1):
  row=s.step();peak=max(peak,len(s.eco.pop))
  for sp in SP:births[sp]+=row.get('births_'+sp,0)
  if day in (500,1000,3000,10000):
   checkpoints.append(dict(day=day,counts={sp:int((s.eco.pop.sp==i).sum()) for i,sp in enumerate(SP)},resources={k:float(s.w[k].sum()) for k in ('G','O','R','N','Ws','h')},energy=float(s.eco.pop.energy.sum()),temperature=float(s.w['T'].mean()),moisture=float(s.w['moist'].mean()),mass=float(s.eco.pop.mass.sum()),hash=s.state_hash()))
 deaths=s.eco.deaths
 results.append(dict(seed=seed,seconds=time.perf_counter()-t,peak=peak,births=dict(births),deaths_by_species=dict(collections.Counter(d['species'] for d in deaths)),causes=dict(collections.Counter(d['cause'] for d in deaths)),death_age_days=[d['age'] for d in deaths],checkpoints=checkpoints,extinct=s.extinct))
 Path(a.out).write_text(json.dumps(results,indent=2));print(seed,results[-1]['seconds'],flush=True)
