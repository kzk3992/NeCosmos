"""Isolated spatial index vs vector-reference costs, deterministic ties included."""
import sys,time,json
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'NeCosmos-Simulation'))
from src.ecosystem.spatial import SpatialIndex
out=[]
for n in (50,200,500):
 rng=np.random.default_rng(100);j=rng.integers(0,32,n);i=rng.integers(0,32,n);idx=SpatialIndex(j,i)
 a=[idx.nearest(int(j[k]),int(i[k]),k) for k in range(n)];b=[idx.nearest_reference(int(j[k]),int(i[k]),k) for k in range(n)];assert a==b
 times={}
 for name in ('nearest','nearest_reference'):
  start=time.perf_counter()
  for _ in range(10):
   for k in range(n):getattr(idx,name)(int(j[k]),int(i[k]),k)
  times[name+'_us']=(time.perf_counter()-start)*1e6/(10*n)
 out.append(dict(population=n,equivalent=True,**times))
Path('artifacts/phase234/spatial.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
