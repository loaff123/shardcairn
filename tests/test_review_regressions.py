"""Regressions from fresh independent implementation review."""
import copy
import unittest
from shardcairn.canonical import manifest_sha256,canonical_bytes
from shardcairn.verifier import verify,evaluate_assignment,baseline_record
from test_optimizer import manifest


def tight_marginal_record():
    m=manifest([2,2,2,3,3]);body=evaluate_assignment(m,(0,0,0,1,1))
    body.update(plan_version=1,model_version='exclusive-additive-once-per-shard-v1',
        manifest_hash=dict(algorithm='sha256',normalization='shardcairn-manifest-c14n-v1',digest=manifest_sha256(m)),
        solver=dict(algorithm_version='shardcairn-portfolio-v1',requested_mode='auto',initial_seed='marginal',incumbent_source='seed',exact=dict(state='skipped_bound_tight'),seeds=[dict(id='lpt',state='completed'),dict(id='marginal',state='completed'),dict(id='affinity',state='not_started')]),
        work=dict(primitive_work_limit=1000,local_candidate_limit=100,exact_node_limit=100,primitive_work_used=100,local_candidates_started=0,exact_nodes_entered=0,denied_budgets=[],budget_events=[],local_state='not_started'),
        baseline=baseline_record(m),claim=dict(status='bound_tight',primary_objective='makespan',secondary_optimal=False))
    return m,body


class ReviewedStatusRegressions(unittest.TestCase):
    def test_impossible_phases_after_seed_bound_tight(self):
        m,valid=tight_marginal_record();self.assertEqual(verify(m,valid).exit_code,0)
        cases=[]
        a=copy.deepcopy(valid);a['solver']['seeds'][2]['state']='completed';cases.append(a)
        a=copy.deepcopy(valid);a['work'].update(local_state='fixed_point',local_candidates_started=30);cases.append(a)
        a=copy.deepcopy(valid);a['solver']['exact']['state']='completed';a['work']['exact_nodes_entered']=1;cases.append(a)
        a=copy.deepcopy(valid);a['solver'].update(incumbent_source='exact',exact={'state':'completed'});a['work']['exact_nodes_entered']=6;cases.append(a)
        for index,candidate in enumerate(cases):
            with self.subTest(index=index):
                result=verify(m,canonical_bytes(candidate))
                self.assertEqual(result.exit_code,3)
                self.assertEqual(result.to_dict()['result'],'invalid')

class ReviewedRollbackRegressions(unittest.TestCase):
    def test_denied_removal_rollback_never_inserts_missing_dict_key(self):
        from shardcairn.budgets import Budget,BudgetStop
        from shardcairn.optimization import Prepared,State,_mutate,_rollback
        class NoNewKeysDuringRollback(dict):
            guarded=False
            def __setitem__(self,key,value):
                if self.guarded and key not in self:
                    raise AssertionError('Rollback attempted a new dictionary insertion')
                super().__setitem__(key,value)
        m=manifest([1,1,1],2,[['a'],[],[]],{'a':7})
        p=Prepared(m);state=State.baseline(p,(0,0,1));state.counts[0]=NoNewKeysDuringRollback(state.counts[0])
        undo=[]
        with self.assertRaises(BudgetStop):_mutate(p,state,((0,1),),Budget(1,100,100),'local',undo)
        state.counts[0].guarded=True
        _rollback(p,state,undo)
        self.assertEqual(state.counts[0],{0:1})
        self.assertEqual(state.vector,[0,0,1])

class ReviewedOriginRegressions(unittest.TestCase):
    def test_affinity_bound_skip_cannot_be_followed_by_local_source(self):
        m,doc=tight_marginal_record()
        doc['solver']['incumbent_source']='local'
        doc['work'].update(local_state='fixed_point',local_candidates_started=30)
        self.assertEqual(verify(m,canonical_bytes(doc)).exit_code,3)
    def test_local_and_exact_origins_require_strict_baseline_improvement(self):
        m=manifest([10,10,30,30],2,[['db'],['db'],[],[]],{'db':30})
        _,template=tight_marginal_record()
        template.update(evaluate_assignment(m,(0,1,0,1)))
        template['manifest_hash']['digest']=manifest_sha256(m)
        template['baseline']=baseline_record(m)
        template['solver']['initial_seed']='lpt'
        template['solver']['seeds'][2]['state']='completed'
        template['work'].update(local_state='fixed_point',local_candidates_started=30)
        for source in ['local','exact']:
            doc=copy.deepcopy(template)
            doc['solver']['incumbent_source']=source
            doc['solver']['requested_mode']='heuristic' if source=='local' else 'auto'
            doc['solver']['exact']['state']='not_requested' if source=='local' else 'completed'
            doc['work']['exact_nodes_entered']=0 if source=='local' else 5
            doc['claim']['status']='feasible' if source=='local' else 'search_complete'
            with self.subTest(source=source):self.assertEqual(verify(m,canonical_bytes(doc)).exit_code,3)

class ReviewedWorkMinimumRegressions(unittest.TestCase):
    def test_completed_phases_require_conservative_counter_minima(self):
        from test_verifier import model,hand_plan
        m=model();valid=hand_plan(m);self.assertEqual(verify(m,valid).exit_code,0)
        cases=[]
        a=copy.deepcopy(valid);a['work']['local_candidates_started']=13;cases.append(a)
        a=copy.deepcopy(valid);a['work']['primitive_work_used']=20;cases.append(a)
        a=copy.deepcopy(valid);a['work'].update(primitive_work_used=0,local_candidates_started=0,local_candidate_limit=0,local_state='budget_exhausted',denied_budgets=['local_candidates'],budget_events=[{'phase':'local','budget':'local_candidates'}]);cases.append(a)
        for index,candidate in enumerate(cases):
            with self.subTest(index=index):self.assertEqual(verify(m,canonical_bytes(candidate)).exit_code,3)
