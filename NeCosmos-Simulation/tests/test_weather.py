import sys,json,copy,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.weather.generator import WeatherGenerator
from src.coupling.simulation import Simulation,load_cfg
from src.hydrology import water
from src.ecosystem import cats as C
from test_numerics import bare_world,tcfg,storage
from test_requirements import eco_world,make_eco
CFG=load_cfg()
def gen(mode='normal',seed=21001):return WeatherGenerator(seed,CFG['climates']['climates']['wet'],CFG['weather'],mode)
def scenario(mode='normal'):
 return dict(terrain='hills',climate='wet',composition='all8',seed=21001,days=1200,max_population=200,weather_mode=mode,extreme_start_day=150)
class TestWeather(unittest.TestCase):
 def test_seed_reproducible_and_different_seed(self):
  a,b,c=gen(),gen(),gen(seed=21002)
  aa=[a.next(d) for d in range(1,721)];bb=[b.next(d) for d in range(1,721)];cc=[c.next(d) for d in range(1,721)]
  self.assertEqual(aa,bb);self.assertNotEqual(aa,cc)
 def test_season_and_previous_day_probabilities(self):
  g=gen()
  self.assertGreater(g.probabilities(1,2,0),g.probabilities(181,2,0))
  self.assertGreater(g.probabilities(1,2,0),g.probabilities(1,0,0))
  self.assertLess(g.probabilities(1,0,2),g.probabilities(1,0,0))
 def test_state_roundtrip_and_cache(self):
  a=gen()
  for d in range(1,91):a.next(d)
  state=a.export_state();b=gen();b.restore_state(state)
  self.assertEqual(a.next(90),b.next(90));self.assertEqual(a.export_state(),state)
  self.assertEqual([a.next(d) for d in range(91,361)],[b.next(d) for d in range(91,361)])
  with self.assertRaises(ValueError):a.next(400)
 def test_bounds_and_long_dry_spell(self):
  g=gen('dry');dry=longest=0
  for d in range(1,3601):
   w=g.next(d);self.assertTrue(np.isfinite([w.temperature_C,w.precipitation_mm,w.sunlight,w.relative_humidity]).all())
   self.assertGreaterEqual(w.precipitation_mm,0);self.assertTrue(0<=w.relative_humidity<=1)
   dry=dry+1 if w.precipitation_mm==0 else 0;longest=max(longest,dry)
  self.assertGreaterEqual(longest,30)
 def test_fixed_no_season_or_randomness(self):
  a,b=gen('fixed'),gen('fixed',21002)
  seq=[a.next(d) for d in range(1,721)]
  self.assertEqual([x.precipitation_mm for x in seq],[b.next(d).precipitation_mm for d in range(1,721)])
  self.assertEqual(len({x.temperature_C for x in seq}),1)
 def test_extreme_switch(self):
  a=gen('normal');b=gen('extreme');b.extreme_start_day=601
  for d in range(1,601):self.assertEqual(a.next(d),b.next(d))
  seq=[b.next(d) for d in range(601,1201)]
  self.assertTrue(any(x.extreme for x in seq))
  self.assertTrue(all(x.precipitation_mm>=25 for x in seq if x.extreme))
 def test_deferred_hydrology_then_terrain_conservation(self):
  w=bare_world(n=16,z=np.tile(np.linspace(1,0,16),(16,1)));cfg=tcfg();w['h'][:]=.2
  oldsoil=w['soil'].copy();oldsed=w['sed'].copy();before=storage(w)
  hyd=water.daily(w,cfg,.25,.001,defer_sediment=True)
  np.testing.assert_array_equal(w['soil'],oldsoil);np.testing.assert_array_equal(w['sed'],oldsed)
  water.sediment_from_trace(w,cfg,hyd)
  after=storage(w);led=hyd['ledger']
  self.assertAlmostEqual(after[0]-before[0],led['rain']-led['outflow']-led['evap_surface']-led['evap_soil'],delta=1e-10)
  self.assertAlmostEqual(after[1]-before[1],-led['sed_export'],delta=1e-10)
  self.assertLessEqual(float(w['dz_used'].max()),.02+1e-12)
 def test_receipts_unavailable_until_cycle(self):
  w=eco_world();w['_ecology_pending']={k:np.zeros_like(w[k]) for k in ('N','O','G')}
  before=w['G'].copy();C._credit(w,'G',(4,4),.1)
  np.testing.assert_array_equal(w['G'],before);self.assertEqual(w['_ecology_pending']['G'][4,4],.1)
 def test_coupled_ledgers_attribution_and_altitude(self):
  s=Simulation(scenario('extreme'))
  for d in range(330):
   r=s.step()
   self.assertLess(max(abs(r[k]) for k in ('res_water_m3','res_soil_m3','res_matter_kg')),1e-8)
   self.assertLess(r['dz_attribution_error_m'],1e-12)
   self.assertLessEqual(r['max_dz_used_m'],.02+1e-12);self.assertLessEqual(r['pop_total'],200)
  expected=CFG['weather']['lapse_C_per_m']*(s.w['z']-s.zmean0)
  np.testing.assert_allclose(s.w['T_air']-s.weather_driver.current.temperature_C,expected,atol=1e-12)
  np.testing.assert_allclose(sum(s.terrain_attribution.values()),s.w['z']-s.z0,atol=1e-12)
 def test_coupled_observer_and_population_order(self):
  a,b=Simulation(scenario()),Simulation(scenario())
  for d in range(330):
   if len(b.eco.pop)>1:b.eco.pop.permute(np.arange(len(b.eco.pop))[::-1])
   a.step();b.step()
   if d%7==0:b.snapshot();b.weather(b.day)
  self.assertEqual(a.state_hash(),b.state_hash())
