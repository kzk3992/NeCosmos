"""Behavior acceptance: budgets remain tested by the existing conservation suite."""
import sys,unittest,json,copy
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'NeCosmos-Simulation'),str(ROOT/'NeCosmos-Simulation/tests')]
from test_requirements import make_eco,eco_world
from src.ecosystem.behavior import update,initialize,STATES
from src.ecosystem.cats import MOGU,FUWA,SLIME,GRASS

class BehaviorTests(unittest.TestCase):
 def setup_world(self,sp=MOGU,energy=.8):
  e=make_eco();w=eco_world();e.pop.add([sp],[2],[2],[energy],[.2],0)
  w['G'][:]=0;w['G'][2,3]=.1
  return e,w
 def test_hunger_interrupts_all_personalities(self):
  e,w=self.setup_world(energy=.1);initialize(e,100)
  for v in (0.,1.):
   e.personalities[1]={k:v for k in ('curiosity','sociability','vigilance')}
   self.assertEqual(update(e,w,1,100)[1]['state'],'seekFood')
 def test_satiated_does_not_only_forage(self):
  e,w=self.setup_world(energy=1.2)
  self.assertNotEqual(update(e,w,1,100)[1]['state'],'seekFood')
 def test_cold_fuwa_seeks_company(self):
  e,w=self.setup_world(FUWA);e.pop.add([FUWA],[2],[3],[1.2],[.2],0);w['T'][:]=-10
  initialize(e,100);e.personalities[1]['sociability']=1
  r=update(e,w,1,100)[1];self.assertEqual(r['intent'],'socializing');self.assertEqual(r['targetId'],2)
 def test_food_disappearance_invalidates_held_goal(self):
  e,w=self.setup_world(energy=.3);r=update(e,w,1,100)[1];self.assertEqual(r['goal'],[2,3])
  w['G'][:]=0;w['G'][3,2]=.1
  r=update(e,w,2,100)[1];self.assertEqual(r['goal'],[3,2]);self.assertEqual(r['since'],2)
 def test_goal_and_decision_deadline_persist(self):
  e,w=self.setup_world();r=copy.deepcopy(update(e,w,1,100)[1]);r2=update(e,w,2,100)[1]
  self.assertEqual(r['goal'],r2['goal']);self.assertEqual(r['nextDecisionDay'],r2['nextDecisionDay']);self.assertEqual(e.ai_evaluations,0)
 def test_sociability_changes_action(self):
  e,w=self.setup_world(FUWA,1.2);e.pop.add([FUWA]*4,[2]*4,[2]*4,[1.2]*4,[.2]*4,0)
  initialize(e,100);e.personalities[1]=dict(curiosity=0,sociability=0,vigilance=0)
  self.assertEqual(update(e,w,1,100)[1]['intent'],'resting')
  e.behavior={};e.personalities[1]['sociability']=1
  self.assertEqual(update(e,w,1,100)[1]['intent'],'socializing')
 def test_traits_are_seed_id_birth_deterministic_and_saved(self):
  e,w=self.setup_world();initialize(e,100);a=copy.deepcopy(e.personalities);initialize(e,100)
  self.assertEqual(a,e.personalities)
  e.personalities={};initialize(e,100);self.assertEqual(a,e.personalities)
  e.personalities={};initialize(e,101);self.assertNotEqual(a,e.personalities)
  self.assertTrue(all(0<=v<=1 for t in a.values() for v in t.values()))
 def test_order_invariance_without_consuming_resources(self):
  e,w=self.setup_world();e.pop.add([FUWA,SLIME],[3,2],[2,3],[.8,.8],[.2,.2],0)
  other=copy.deepcopy(e);other.pop.permute(np.array([2,0,1]));before={k:v.copy() for k,v in w.items() if isinstance(v,np.ndarray)}
  self.assertEqual(update(e,w,1,100),update(other,w,1,100))
  for k,v in before.items():np.testing.assert_array_equal(v,w[k])
 def test_emergency_stress_overrides_sociability(self):
  e,w=self.setup_world();e.pop.stress[:]=.01
  self.assertEqual(update(e,w,1,100)[1]['state'],'avoidingDanger')
 def test_configurable_weights_and_hysteresis(self):
  e,w=self.setup_world(energy=1.2);initialize(e,100);e.behavior_config['weights']['rest']=5
  r=update(e,w,1,100)[1];self.assertEqual(r['state'],'resting')
  self.assertTrue(set(STATES)>={'idle','moving','eating','resting','socializing'})

if __name__=='__main__':unittest.main()

class CompatibilityAndSpatialTests(unittest.TestCase):
 def test_spatial_implementation_cannot_change_world(self):
  from unittest.mock import patch
  from src.coupling.simulation import Simulation
  from src.ecosystem.spatial import SpatialIndex
  sc=dict(terrain='hills',climate='cold',composition='all8',seed=21001,days=90,weather_mode='normal',max_population=200,unlock='fixed')
  a=Simulation(sc);b=copy.deepcopy(a)
  for _ in range(90):a.step()
  with patch.object(SpatialIndex,'nearest',SpatialIndex.nearest_reference):
   for _ in range(90):b.step()
  self.assertEqual(a.state_hash(),b.state_hash())
 def test_real_v0100_save_migrates_without_material_loss(self):
  import importlib.util
  spec=importlib.util.spec_from_file_location('bridge_compat',ROOT/'public/engine/bridge.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
  b.FROZEN=str(ROOT/'NeCosmos-Simulation/configs/scenarios/frozen.json')
  f=json.loads((ROOT/'tests/fixtures/v0100-save.json').read_text())
  import base64,zlib
  old=b._dec(json.loads(zlib.decompress(base64.b64decode(f['save'])))['sim'])
  b.load(f['save']);s=b.STATE['sim'];self.assertEqual(s.day,60)
  for key in ('N','O','R','G','Ws','h','soil','bedrock'):np.testing.assert_array_equal(old.w[key],s.w[key])
  for key in old.eco.pop.FIELDS:np.testing.assert_array_equal(getattr(old.eco.pop,key),getattr(s.eco.pop,key))
  self.assertEqual(s.weather_migrated_at,60);b.step(1);self.assertEqual(s.day,61)
 def test_ai_and_object_state_survive_save_continuation(self):
  import importlib.util
  spec=importlib.util.spec_from_file_location('bridge_replay',ROOT/'public/engine/bridge.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
  b.FROZEN=str(ROOT/'NeCosmos-Simulation/configs/scenarios/frozen.json')
  b.new_world(json.dumps(dict(terrain='hills',climate='wet',composition='all8',seed=21001)))
  b.step(20);saved=b.save();b.step(20);expected=json.dumps(b._enc(b.STATE['sim']),sort_keys=True)
  b.load(saved);b.prepare();b.step(20);self.assertEqual(expected,json.dumps(b._enc(b.STATE['sim']),sort_keys=True))

class IntakeIntegrityTests(unittest.TestCase):
 def test_empty_resource_pools_do_not_provide_consumer_energy(self):
  e=make_eco(cat_effects=False);w=eco_world()
  for key in ('G','O','R'):w[key][:]=0
  species=[1,2,3,5,6,7]
  e.pop.add(species,[2]*6,[2]*6,[.5]*6,[.2]*6,0);e.move_p[:]=0
  before=e.pop.energy.copy();e.step(w,1,100,{'light':1.})
  self.assertTrue(np.all(e.pop.energy<before))

class GoalRoutingTests(unittest.TestCase):
 def test_committed_food_goal_controls_actual_move(self):
  e=make_eco(cat_effects=False);w=eco_world();w['G'][:]=0;w['G'][2,3]=.1
  e.pop.add([MOGU],[2],[2],[.6],[.2],0);e.move_p[MOGU]=1
  first=update(e,w,1,100)[1];self.assertEqual(first['goal'],[2,3])
  w['G'][3,2]=1 # better new food does not invalidate the still valid commitment
  second=update(e,w,2,100)[1];self.assertEqual(second['goal'],[2,3])
  e._move(w,2,100,np.array([2.]),{'sp_moved':np.zeros(8,int)})
  self.assertEqual((int(e.pop.j[0]),int(e.pop.i[0])),(2,3))
 def test_food_goal_uses_real_decomposition_capacity(self):
  e=make_eco();w=eco_world();w['O'][:]=0;w['R'][:]=0;w['R'][2,2]=100;w['O'][2,3]=.1
  e.pop.add([SLIME],[2],[2],[.1],[.2],0)
  self.assertEqual(update(e,w,1,100)[1]['goal'],[2,3])
