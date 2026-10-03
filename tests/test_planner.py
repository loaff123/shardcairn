import unittest
from shardcairn.planner import plan
from shardcairn.manifest import PlanOptions, VerifyOptions
from shardcairn.verifier import verify
from test_optimizer import manifest


class PlannerTests(unittest.TestCase):
    def test_toy_exact_and_independent_audit(self):
        m=manifest([10,10,30,30],refs=[['db'],['db'],[],[]],setup={'db':30})
        doc=plan(m);d=doc.to_dict()
        self.assertEqual(d['metrics']['makespan_ms'],60)
        self.assertEqual(d['bounds']['lower_bound_ms'],55)
        self.assertEqual(d['claim']['status'],'search_complete')
        v=verify(m,doc).to_dict();self.assertEqual(v['optimality'],'not_certified')
        v=verify(m,doc,VerifyOptions(audit_optimal=True)).to_dict();self.assertEqual(v['optimality'],'audit_proved')
    def test_zero_caps_phase_precedence(self):
        m=manifest([20,14,12,10,6,6])
        d=plan(m,PlanOptions(work_limit=0,local_candidates=0,exact_nodes=0)).to_dict()
        self.assertEqual(d['work']['budget_events'],[{'phase':'marginal_seed','budget':'primitive_work'},{'phase':'exact','budget':'exact_nodes'}])
        self.assertEqual(d['solver']['seeds'][2]['state'],'not_started')
        self.assertEqual(d['work']['local_state'],'not_started')
        self.assertEqual(d['solver']['exact']['state'],'budget_exhausted')
    def test_root_enters_before_first_denied_bound(self):
        m=manifest([20,14,12,10,6,6]);d=plan(m,PlanOptions(work_limit=0,exact_nodes=1)).to_dict()
        self.assertEqual(d['work']['exact_nodes_entered'],1)
        self.assertEqual(d['work']['budget_events'][-1],{'phase':'exact','budget':'primitive_work'})
    def test_heuristic_miss_retained(self):
        m=manifest([20,14,12,10,6,6]);d=plan(m,PlanOptions(mode='heuristic')).to_dict()
        self.assertEqual(d['metrics']['makespan_ms'],36)
        self.assertEqual(d['solver']['exact']['state'],'not_requested')
    def test_tight_zero_nonempty(self):
        m=manifest([0]*7,k=4);d=plan(m).to_dict()
        self.assertEqual(len(d['assignment']),4)
        self.assertEqual(d['claim']['status'],'bound_tight')
        self.assertEqual([s['state'] for s in d['solver']['seeds']], ['completed','not_started','not_started'])
        self.assertEqual(d['solver']['exact']['state'],'skipped_bound_tight')
        self.assertEqual(d['work']['local_state'],'not_started')
        self.assertEqual(d['bounds']['gap_fraction'],{'numerator':0,'denominator':1})
    def test_reproducible(self):
        m=manifest([10,10,30,30],refs=[['db'],['db'],[],[]],setup={'db':30})
        self.assertEqual(plan(m).to_bytes(),plan(m).to_bytes())
    def test_options_subclass_cannot_override_validation(self):
        class Unchecked(PlanOptions):
            def validate(self):return self
        with self.assertRaises(Exception) as e:plan(manifest([1,2]),Unchecked(work_limit=-1))
        self.assertEqual(e.exception.exit_code,2)
    def test_force_exact_size_rejected(self):
        m=manifest([1]*19)
        with self.assertRaises(Exception) as e:plan(m,PlanOptions(mode='exact'))
        self.assertEqual(e.exception.exit_code,2)

if __name__=='__main__':unittest.main()
