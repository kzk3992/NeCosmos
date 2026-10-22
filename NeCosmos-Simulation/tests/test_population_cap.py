import unittest
import numpy as np
from test_requirements import eco_world, make_eco
from src.coupling.simulation import Simulation
from src.ecosystem import cats as C

class TestPopulationCap(unittest.TestCase):
    def test_scenario_cap_and_invalid_inputs(self):
        sc=dict(terrain='valley',climate='wet',composition='all8',seed=110011,days=10,max_population=200)
        self.assertEqual(Simulation(sc).eco.max_population,200)
        for limit in (-1,True,1.5,0):
            with self.assertRaises(ValueError): Simulation(dict(sc,max_population=limit))
    def test_births_rejected_without_debit(self):
        e=make_eco(); w=eco_world(); e.max_population=200; e.K=1000; e.base[:]=100
        e.pop.add(np.full(200,C.GRASS),np.full(200,4),np.full(200,4),np.ones(200),np.full(200,.3),0)
        e.pop.age[:]=100
        energy=e.pop.energy.copy(); mass=e.pop.mass.copy()
        stats={'births':0,'births_by_sp':np.zeros(8,int)}
        e._reproduce(w,200,3,e.pop.age.astype(float),stats)
        self.assertEqual(len(e.pop),200);self.assertEqual(stats['births'],0)
        np.testing.assert_array_equal(e.pop.energy,energy);np.testing.assert_array_equal(e.pop.mass,mass)
    def test_competing_births_do_not_exceed_slots(self):
        e=make_eco();w=eco_world();e.max_population=200;e.K=1000;e.base[:]=100
        e.pop.add(np.full(199,C.GRASS),np.full(199,4),np.full(199,4),np.ones(199),np.full(199,.3),0)
        e.pop.age[:]=100
        stats={'births':0,'births_by_sp':np.zeros(8,int)}
        e._reproduce(w,200,3,e.pop.age.astype(float),stats)
        self.assertEqual(len(e.pop),200);self.assertEqual(stats['births'],1)

    def test_special_spawn_paths_at_cap_preserve_nutrients(self):
        e=make_eco(grass_spawn=True);w=eco_world();e.max_population=200
        e.pop.add(np.full(200,C.MOGU),np.full(200,4),np.full(200,4),np.ones(200),np.full(200,.3),0)
        before=w['N'].copy();st={'spawned':0,'wisdom_event':''}
        e._spawn_grass(w,300,110011,st,{})
        e._wisdom(w,300,110011,st)
        self.assertEqual(len(e.pop),200)
        np.testing.assert_array_equal(before,w['N'])
        self.assertEqual(st['spawned'],0);self.assertEqual(st['wisdom_event'],'')

    def test_cap_birth_selection_independent_of_storage_order(self):
        worlds=[];ecologies=[]
        for reverse in (False,True):
            e=make_eco();w=eco_world();e.max_population=200;e.K=1000;e.base[:]=100
            e.pop.add(np.full(199,C.GRASS),np.full(199,4),np.full(199,4),np.ones(199),np.full(199,.3),0)
            e.pop.age[:]=100
            if reverse:e.pop.permute(np.arange(199)[::-1])
            e._reproduce(w,200,3,e.pop.age.astype(float),{'births':0,'births_by_sp':np.zeros(8,int)})
            ecologies.append(e);worlds.append(w)
        for field in ecologies[0].pop.FIELDS:
            a,b=ecologies
            np.testing.assert_array_equal(getattr(a.pop,field)[np.argsort(a.pop.id)],getattr(b.pop,field)[np.argsort(b.pop.id)])
        np.testing.assert_array_equal(worlds[0]['N'],worlds[1]['N'])
