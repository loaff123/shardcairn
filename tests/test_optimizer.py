import itertools
import unittest

from shardcairn.budgets import Budget, BudgetStop
from shardcairn.baseline import baseline_vector
from shardcairn.optimization import Prepared, State, local_improve, exact_search, build_seed
from shardcairn.manifest import load_manifest


def manifest(p, k=2, refs=None, setup=None):
    import json
    refs = refs or [[] for _ in p]
    setup = setup or {}
    return load_manifest(json.dumps({'schema_version':1,'timing_basis':'exclusive-additive-once-per-shard-v1','shards':k,'setups':[{'id':s,'cost_ms':v} for s,v in setup.items()], 'units':[{'id':f'U{i}','selectors':[f'tests/test_x.py::test_u{i}'],'exclusive_cost_ms':v,'setup_ids':refs[i]} for i,v in enumerate(p)]}).encode())


def score(m, vector):
    c = {s.id:s.cost_ms for s in m.setups}
    loads=[]
    for j in range(m.shards):
        us=[u for i,u in enumerate(m.units) if vector[i]==j]
        if not us:return None
        union=set().union(*(set(u.setup_ids) for u in us))
        loads.append(sum(u.exclusive_cost_ms for u in us)+sum(c[s] for s in union))
    return max(loads),sum(loads)


class BudgetTests(unittest.TestCase):
    def test_denied_next_not_equality(self):
        b=Budget(1,1,1);b.tick('local')
        self.assertEqual(b.events,[])
        with self.assertRaises(BudgetStop):b.tick('local')
        self.assertEqual(b.events,[{'phase':'local','budget':'primitive_work'}])
    def test_local_precedence_atomic_start(self):
        b=Budget(0,0,0)
        with self.assertRaises(BudgetStop):b.local_start()
        self.assertEqual((b.used,b.local),(0,0))
        self.assertEqual(b.events,[{'phase':'local','budget':'local_candidates'}])
    def test_exact_entry_precedes_primitive(self):
        b=Budget(0,0,1);b.node_start();self.assertEqual(b.nodes,1)
        with self.assertRaises(BudgetStop):b.tick('exact')
        self.assertEqual(b.events,[{'phase':'exact','budget':'primitive_work'}])


class OptimizerTests(unittest.TestCase):
    def test_baseline_trap(self):
        m=manifest([20,14,12,10,6,6]);self.assertEqual(baseline_vector(m),(0,1,1,0,1,0))
    def test_zero_nonempty(self):
        m=manifest([0]*7,k=4);self.assertEqual(set(baseline_vector(m)),set(range(4)))
    def test_pair_trap_preserved_and_exact_escapes(self):
        m=manifest([20,14,12,10,6,6]);p=Prepared(m);v=p.baseline
        for kind in ['marginal','affinity']:
            self.assertEqual(build_seed(p,kind,Budget(100000,10000,10000)),v)
        v,state=local_improve(p,v,Budget(100000,10000,10000))
        self.assertEqual(state,'fixed_point');self.assertEqual(score(m,v)[0],36)
        v,state=exact_search(p,v,Budget(1000000,10000,100000))
        self.assertEqual(state,'completed');self.assertEqual(score(m,v)[0],34)
    def test_setup_reuse(self):
        m=manifest([10,10,30,30],refs=[['db'],['db'],[],[]],setup={'db':30})
        p=Prepared(m);v=p.baseline
        v,state=exact_search(p,v,Budget(100000,10000,10000))
        self.assertEqual(score(m,v),(60,110));self.assertEqual(state,'completed')
    def test_unsafe_load_symmetry_regression(self):
        m=manifest([5,0,0],refs=[[],['x'],['x']],setup={'x':5})
        p=Prepared(m);v,state=exact_search(p,p.baseline,Budget(100000,10000,10000))
        self.assertEqual(score(m,v)[0],5)
    def test_tiny_cartesian_differential(self):
        for bits in range(32):
            for k in [1,2,3]:
                p=[(bits>>i)&1 for i in range(4)]
                refs=[(['a'] if (bits>>(i+1))&1 else []) for i in range(4)]
                m=manifest(p,k,refs,{'a':3})
                optimum=min(s[0] for v in itertools.product(range(k),repeat=4) if (s:=score(m,v)) is not None)
                p=Prepared(m);v,state=exact_search(p,p.baseline,Budget(100000,10000,10000))
                self.assertEqual(score(m,v)[0],optimum,(bits,k))
                self.assertEqual(state,'completed')
    def test_local_budget_rollback_all_stops(self):
        m=manifest([10,10,30,30],refs=[['db'],['db'],[],[]],setup={'db':30});p=Prepared(m);base=p.baseline
        for limit in range(220):
            fresh=Prepared(m)
            v,status=local_improve(fresh,fresh.baseline,Budget(limit,1000,1000))
            self.assertEqual(len(v),4);self.assertEqual(set(v),{0,1})
            self.assertLessEqual(score(m,v),score(m,base))
    def test_exact_budget_rollback_all_stops(self):
        m=manifest([10,10,30,30],refs=[['db'],['db'],[],[]],setup={'db':30});p=Prepared(m);base=p.baseline
        for limit in range(220):
            v,status=exact_search(p,base,Budget(limit,1000,1000))
            self.assertEqual(set(v),{0,1});self.assertLessEqual(score(m,v)[0],score(m,base)[0])

if __name__=='__main__':unittest.main()
