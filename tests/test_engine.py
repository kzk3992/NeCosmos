import sys,json,unittest,importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'NeCosmos-Simulation'))
spec=importlib.util.spec_from_file_location('bridge',ROOT/'public/engine/bridge.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
b.FROZEN=str(ROOT/'NeCosmos-Simulation/configs/scenarios/frozen.json')
PARAMS=json.dumps(dict(terrain='hills',climate='wet',composition='all8',seed=21001,weatherMode='normal'))
def full():
 return json.dumps(b._enc(b.STATE['sim']),sort_keys=True)
class EngineTests(unittest.TestCase):
 def test_prepare_does_not_mutate_committed_world_or_rng(self):
  b.new_world(PARAMS);before=full();plan=b.prepare();self.assertEqual(before,full());self.assertEqual(plan,b.prepare())
 def test_headless_and_prepared_transactions_identical(self):
  b.new_world(PARAMS)
  for _ in range(30):b.step(1)
  expected=full()
  b.new_world(PARAMS)
  for _ in range(30):b.prepare();b.step(1)
  self.assertEqual(expected,full())
 def test_batch_speeds_have_identical_full_world(self):
  expected=None
  for batch in (1,5,10,20,100):
   b.new_world(PARAMS)
   left=120
   while left:
    n=min(batch,left);b.step(n);left-=n
   if expected is None:expected=full()
   else:self.assertEqual(expected,full())
 def test_save_restore_pending_events_and_future(self):
  b.new_world(PARAMS);b.step(20);b.prepare();saved=b.save();events=b.STATE['behavior_events'];b.step(30);expected=full()
  b.load(saved);self.assertEqual(events,b.STATE['behavior_events']);b.step(30);self.assertEqual(expected,full())
 def test_legacy_save_without_behavior(self):
  b.new_world(PARAMS);b.step(3);del b.STATE['sim'].eco.behavior;saved=b.save();b.load(saved);b.step(1)
  self.assertEqual(b.STATE['sim'].day,4)
 def test_biological_age_and_balance_are_distinct(self):
  b.new_world(PARAMS);before=b.STATE['sim'].eco.r_min.copy();s=json.loads(b.step(48));self.assertEqual(s['biologicalYearDays'],48)
  self.assertEqual(s['cats']['biologicalAgeYears'],[a/48 for a in s['cats']['age']]);self.assertTrue((before==b.STATE['sim'].eco.r_min).all())
 def test_events_and_behavior_states(self):
  b.new_world(PARAMS);s=json.loads(b.step(100));self.assertTrue(s['behaviorEvents'])
  for e in s['behaviorEvents']:self.assertIn('id',e);self.assertIn('planetTime',e)
  from src.ecosystem.behavior import STATES
  self.assertTrue(set(s['cats']['behavior']).issubset(STATES))
 def test_invalid_steps(self):
  b.new_world(PARAMS)
  for n in (0,-1,1.5,301):
   with self.assertRaises(ValueError):b.step(n)
if __name__=='__main__':unittest.main()

class SpatialTests(unittest.TestCase):
 def test_grid_matches_brute_force_including_ties(self):
  import numpy as np
  from src.ecosystem.spatial import SpatialIndex
  r=np.random.default_rng(10);j=r.integers(0,32,200);i=r.integers(0,32,200);index=SpatialIndex(j,i)
  for k in range(200):
   expected=min((n for n in range(200) if n!=k),key=lambda n:((int(j[n])-int(j[k]))**2+(int(i[n])-int(i[k]))**2,n))
   self.assertEqual(index.nearest(int(j[k]),int(i[k]),k),expected)

class TimelineTests(unittest.TestCase):
 def test_authoritative_subday_position_and_no_world_mutation(self):
  b.new_world(PARAMS);plan=json.loads(b.prepare());before=full()
  positions=json.loads(b.observe(1/300))['positions']
  by_id={m['id']:m for m in plan['moves']}
  for pos in positions:
   m=by_id[pos['id']];j,i=m['origin'];distance=((pos['x']-(i+.5)*.5)**2+(pos['y']-(j+.5)*.5)**2)**.5
   self.assertLessEqual(distance,.25000001)
  self.assertEqual(before,full())
 def test_all_modes_same_trajectory_at_same_planet_time(self):
  from src.ecosystem.timeline import sample
  m=[dict(id=1,origin=[0,0],position=[0,1])]
  expected=sample(m,.5,.003)
  for _ in [0.05,1,5,10,20,100]:self.assertEqual(expected,sample(m,.5,.003))

class LegacyFixtureTests(unittest.TestCase):
 def test_actual_v0101_save_retains_exact_state(self):
  fixture=json.loads((ROOT/'tests/fixtures/v0101-save.json').read_text());s=json.loads(b.load(fixture['save']))
  self.assertEqual(s['day'],fixture['day']);self.assertEqual(b.state_hash(),fixture['hash'])
  b.prepare();b.step(1);self.assertEqual(b.STATE['sim'].day,61)

class PlayerOperationTests(unittest.TestCase):
 def test_same_planet_time_operations_at_all_modes(self):
  expected=None
  for mode,batch in [(0.05,1),(1,1),(5,5),(10,10),(20,20),(100,100)]:
   b.new_world(PARAMS)
   for checkpoint,level in [(100,2),(200,3),(360,None)]:
    while b.STATE['sim'].day<checkpoint:
     n=min(batch,checkpoint-b.STATE['sim'].day)
     if mode==.05:b.prepare()
     b.step(n)
    if level:b.unlock(level)
   # Includes all population arrays, birth/death ledgers, resources, weather RNG,
   # event history, persistent FSM, and wisdom's day-300 state.
   if expected is None:expected=full()
   else:self.assertEqual(expected,full(),str(mode))
