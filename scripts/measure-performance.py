"""Native CPU stress probes; no production population cap changes."""
import sys,time,json,tracemalloc,statistics,argparse
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--root',default=str(Path(__file__).resolve().parents[1]));parser.add_argument('--out',default='artifacts/performance-native.json');args=parser.parse_args()
ROOT=Path(args.root);sys.path.insert(0,str(ROOT/'NeCosmos-Simulation'))
from src.coupling.simulation import Simulation,load_cfg
from src.ecosystem import behavior
from src.ecosystem.cats import Ecology
from src.ecosystem.spatial import SpatialIndex
ai=[];near=[];neighbors=[]
original=behavior.update;nearest=SpatialIndex.nearest;nearby=SpatialIndex.nearby
def timed_ai(*args):
 t=time.perf_counter();result=original(*args);ai.append(time.perf_counter()-t);return result
def timed_near(*args):
 t=time.perf_counter();result=nearest(*args);near.append(time.perf_counter()-t);return result
def timed_neighbors(*args,**kwargs):
 t=time.perf_counter();result=nearby(*args,**kwargs);neighbors.append(time.perf_counter()-t);return result
behavior.update=timed_ai;SpatialIndex.nearest=timed_near;SpatialIndex.nearby=timed_neighbors
kernel=[];eco_step=Ecology.step
def timed_ecology(*args,**kwargs):
 t=time.perf_counter();result=eco_step(*args,**kwargs);kernel.append(time.perf_counter()-t);return result
Ecology.step=timed_ecology
out=[]
for count,n in [(50,32),(200,32),(500,32),(500,64)]:
 cfg=load_cfg();cfg['terrain']['grid']['n']=n
 cfg['comps']['stress']={'grass':count//2,'fuwa':count//4,'kinoko':count-count//2-count//4}
 sc=dict(terrain='hills',climate='cold',composition='stress',seed=21001,days=100,weather_mode='normal',max_population=count,unlock='fixed')
 sim=Simulation(sc,cfg);ai.clear();near.clear();neighbors.clear();kernel.clear();samples=[];t=time.perf_counter()
 for _ in range(100):
  start=time.perf_counter();sim.step();samples.append(time.perf_counter()-start)
 elapsed=time.perf_counter()-t
 kernel_mean=statistics.mean(kernel)*1000
 ai_mean=statistics.mean(ai)*1000
 near_mean=statistics.mean(near)*1000 if near else None
 neighbor_mean=statistics.mean(neighbors)*1000
 # Memory probe separate from timings, since tracemalloc dramatically changes CPU cost.
 tracemalloc.start();sim2=Simulation(sc,cfg)
 for _ in range(5):sim2.step()
 current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
 out.append(dict(initial_population=count,grid=n,area_factor=(n/32)**2,days_per_second=100/elapsed,
   ecology_ms_mean=statistics.mean(samples)*1000,ecology_ms_max=max(samples)*1000,
   ecosystem_kernel_ms_mean=kernel_mean,ai_ms_mean=ai_mean,nearest_query_ms_mean=near_mean,
   neighbor_query_ms_mean=neighbor_mean, memory_python_peak_bytes=peak,final_population=len(sim.eco.pop)))
Path(args.out).write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
