"""Development-only independent direct-set oracle and mutation differential tests."""
import itertools
import random
import unittest

from shardcairn.budgets import Budget, BudgetStop
from shardcairn.optimization import Prepared, State, _mutate, _rollback, prefix_lower_bound, exact_search, local_improve
from shardcairn.planner import plan
from shardcairn.manifest import PlanOptions
from shardcairn.verifier import verify
from test_optimizer import manifest, score


class DifferentialTests(unittest.TestCase):
    def test_every_small_move_and_swap_against_sets(self):
        checked=0
        for scenario in range(12):
            m=manifest([scenario%3,(scenario//3)%3,1,0],k=2,
                       refs=[['a'],['a','b'],['b'] if scenario%2 else [],[]],setup={'a':scenario%4,'b':3})
            p=Prepared(m)
            for vector in itertools.product(range(2),repeat=4):
                if len(set(vector))!=2:continue
                for i in range(4):
                    choices=[((i,1-vector[i]),)]
                    choices += [((i,vector[j]),(j,vector[i])) for j in range(i+1,4) if vector[i]!=vector[j]]
                    for moves in choices:
                        candidate=list(vector)
                        for u,j in moves:candidate[u]=j
                        if len(set(candidate))!=2:continue
                        state=State.baseline(p,vector);before=(state.vector[:],state.exclusive[:],state.setup_cost[:],[dict(x) for x in state.counts],state.masks[:],state.sizes[:])
                        undo=[];b=Budget(10000,10000,10000)
                        _mutate(p,state,moves,b,'local',undo)
                        self.assertEqual(state.score(p,b,'local'),score(m,candidate))
                        _rollback(p,state,undo)
                        self.assertEqual((state.vector,state.exclusive,state.setup_cost,state.counts,state.masks,state.sizes),before)
                        checked+=1
        self.assertGreater(checked,1000)

    def test_prefix_bounds_against_every_completion(self):
        checked=0
        for scenario in range(24):
            for k in [2,3]:
                m=manifest([scenario%3,0,2,(scenario//3)%3],k,
                    [['a'],['a','b'],[],['b']],{'a':scenario%4,'b':(scenario//4)%4})
                p=Prepared(m)
                for depth in range(5):
                    for prefix in itertools.product(range(k),repeat=depth):
                        remaining=p.order[depth:]
                        candidates=[]
                        for labels in itertools.product(range(k),repeat=4-depth):
                            v=[None]*4
                            for i,j in zip(p.order[:depth],prefix):v[i]=j
                            for i,j in zip(remaining,labels):v[i]=j
                            objective=score(m,v)
                            if objective is not None:candidates.append(objective[0])
                        if not candidates:continue
                        state=State(p)
                        for i,j in zip(p.order[:depth],prefix):
                            state.vector[i]=j;state.exclusive[j]+=p.costs[i];state.sizes[j]+=1
                            for setup in p.refs[i]:
                                if setup not in state.counts[j]:
                                    state.setup_cost[j]+=p.setup_costs[setup];state.masks[j]|=1<<setup
                                state.counts[j][setup]=state.counts[j].get(setup,0)+1
                        remaining_mask=0
                        for i in remaining:
                            for setup in p.refs[i]:remaining_mask|=1<<setup
                        bound,_=prefix_lower_bound(p,state,sum(p.costs[i] for i in remaining),remaining_mask,Budget(10000,10000,10000))
                        self.assertLessEqual(bound,min(candidates),(scenario,k,depth,prefix))
                        checked+=1
        self.assertGreater(checked,2000)

    def test_two_thousand_exact_cases_independent_cartesian(self):
        r=random.Random(301027)
        for case in range(2000):
            n=3+case%3;k=1+case%min(n,3)
            costs=[r.randrange(8) for _ in range(n)]
            refs=[[s for s in ('a','b') if r.randrange(2)] for _ in range(n)]
            m=manifest(costs,k,refs,{'a':r.randrange(8),'b':r.randrange(8)})
            optimum=min(s[0] for v in itertools.product(range(k),repeat=n) if (s:=score(m,v)) is not None)
            p=Prepared(m);v,status=exact_search(p,p.baseline,Budget(500000,100000,100000))
            self.assertEqual(status,'completed');self.assertEqual(score(m,v)[0],optimum,(case,costs,k,refs))

    def test_exact_budget_boundary_equality_and_one_before(self):
        m=manifest([20,14,12,10,6,6]);p=Prepared(m);b=Budget(100000,10000,100000)
        _,status=exact_search(p,p.baseline,b);self.assertEqual(status,'completed')
        for work,nodes,want in [(b.used,b.nodes,'completed'),(b.used-1,b.nodes,'budget_exhausted'),(b.used,b.nodes-1,'budget_exhausted')]:
            p=Prepared(m);bounded=Budget(work,10000,nodes)
            v,status=exact_search(p,p.baseline,bounded);self.assertEqual(status,want)
            self.assertLessEqual(score(m,v)[0],36)
            self.assertEqual(bool(bounded.events),want=='budget_exhausted')

    def test_local_candidate_exact_scan_boundary(self):
        m=manifest([20,14,12,10,6,6])
        for limit,status in [(27,'fixed_point'),(26,'budget_exhausted')]:
            p=Prepared(m);b=Budget(100000,limit,100000)
            _,actual=local_improve(p,p.baseline,b)
            self.assertEqual(actual,status);self.assertEqual(b.local,limit)
            self.assertEqual(bool(b.events),limit==26)

    def test_metamorphic_model_and_result_validity(self):
        base=manifest([7,0,4,2],2,[['a'],['a','b'],['b'],[]],{'a':3,'b':8})
        for factor in [0,1,2,7]:
            changed=manifest([u.exclusive_cost_ms*factor for u in base.units],2,
                [list(u.setup_ids)+['zero'] for u in base.units],{'a':3*factor,'b':8*factor,'zero':0})
            for v in itertools.product(range(2),repeat=4):
                a=score(base,v);b=score(changed,v)
                if a is not None:self.assertEqual(b,(a[0]*factor,a[1]*factor))
            result=plan(changed);self.assertEqual(verify(changed,result).exit_code,0)
        renamed=manifest([7,0,4,2],2,[['z'],['z','y'],['y'],[]],{'z':3,'y':8})
        optimum=lambda m:min(s[0] for v in itertools.product(range(2),repeat=4) if (s:=score(m,v)) is not None)
        self.assertEqual(optimum(base),optimum(renamed))

if __name__=='__main__':unittest.main()
