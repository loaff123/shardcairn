"""Independent verifier hand cases and adversarially re-sealed mutations."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import unittest


def model():
    from shardcairn.manifest import load_manifest
    return load_manifest(json.dumps({
        'schema_version': 1, 'timing_basis': 'exclusive-additive-once-per-shard-v1',
        'shards': 2, 'setups': [{'id': 'db', 'cost_ms': 30}, {'id': 'unused', 'cost_ms': 99}],
        'units': [
            {'id':'A','selectors':['a1','a2'],'exclusive_cost_ms':10,'setup_ids':['db']},
            {'id':'B','selectors':['b'],'exclusive_cost_ms':10,'setup_ids':['db']},
            {'id':'C','selectors':['c'],'exclusive_cost_ms':30,'setup_ids':[]},
            {'id':'D','selectors':['d'],'exclusive_cost_ms':30,'setup_ids':[]},
        ]}).encode())


def hand_plan(m, *, baseline=False, claim='feasible'):
    from shardcairn.canonical import manifest_sha256
    baseline_metrics = dict(exclusive_total_ms=80, setup_total_ms=60, minimum_setup_ms=30,
                            duplicated_setup_ms=30, makespan_ms=70, total_work_ms=140,
                            activated_setup_occurrences=2)
    chosen_metrics = dict(exclusive_total_ms=80, setup_total_ms=30, minimum_setup_ms=30,
                          duplicated_setup_ms=0, makespan_ms=60, total_work_ms=110,
                          activated_setup_occurrences=1)
    bs = [dict(index=0, unit_ids=['A','C'], exclusive_cost_ms=40, setup_cost_ms=30, load_ms=70),
          dict(index=1, unit_ids=['B','D'], exclusive_cost_ms=40, setup_cost_ms=30, load_ms=70)]
    chosen = [dict(index=0,unit_ids=['A','B'],selectors=['a1','a2','b'],setup_ids=['db'],exclusive_cost_ms=20,setup_cost_ms=30,load_ms=50),
              dict(index=1,unit_ids=['C','D'],selectors=['c','d'],setup_ids=[],exclusive_cost_ms=60,setup_cost_ms=0,load_ms=60)]
    if baseline:
        chosen = [dict(bs[0], selectors=['a1','a2','c'], setup_ids=['db']),
                  dict(bs[1], selectors=['b','d'], setup_ids=['db'])]
    upper = 70 if baseline else 60
    return {
        'plan_version':1, 'model_version':'exclusive-additive-once-per-shard-v1',
        'manifest_hash':{'algorithm':'sha256','normalization':'shardcairn-manifest-c14n-v1','digest':manifest_sha256(m)},
        'solver':{'algorithm_version':'shardcairn-portfolio-v1','requested_mode':'auto' if claim=='search_complete' else 'heuristic',
                  'initial_seed':'lpt' if baseline else 'marginal','incumbent_source':'seed',
                  'exact':{'state':'completed' if claim=='search_complete' else 'not_requested'},
                  'seeds':[{'id':x,'state':'completed'} for x in ['lpt','marginal','affinity']]},
        'work':{'primitive_work_limit':1000,'local_candidate_limit':100,'exact_node_limit':100,
                'primitive_work_used':100,'local_candidates_started':20,
                'exact_nodes_entered':1 if claim=='search_complete' else 0,'denied_budgets':[],
                'budget_events':[],'local_state':'fixed_point'},
        'baseline':{'algorithm_version':'exclusive-lpt-v1','shards':bs,'metrics':baseline_metrics},
        'assignment':chosen,'metrics':baseline_metrics.copy() if baseline else chosen_metrics,
        'bounds':{'standalone_lower_bound_ms':40,'average_lower_bound_ms':55,'lower_bound_ms':55,
                  'upper_bound_ms':upper,'absolute_gap_ms':upper-55,
                  'gap_fraction':{'numerator':upper-55,'denominator':upper}},
        'claim':{'status':claim,'primary_objective':'makespan','secondary_optimal':False},
    }


class VerifierTests(unittest.TestCase):
    def setUp(self):
        # The initial test-first run witnesses the missing module as an assertion.
        self.assertIsNotNone(importlib.util.find_spec('shardcairn.verifier'))
        from shardcairn.verifier import verify
        self.verify = verify
        self.m = model()

    def result(self, p, **options):
        from shardcairn.manifest import VerifyOptions
        return self.verify(self.m, p, VerifyOptions(**options))

    def test_hand_assignment_baseline_bounds(self):
        from shardcairn.verifier import evaluate_assignment, baseline_record
        p = hand_plan(self.m)
        from shardcairn.errors import ShardCairnError
        with self.assertRaises(ShardCairnError):
            evaluate_assignment(self.m, (8,8,9,9))

    def test_independent_arithmetic(self):
        from shardcairn.verifier import evaluate_assignment, baseline_record
        p = hand_plan(self.m)
        result = evaluate_assignment(self.m, (1,1,0,0))
        self.assertEqual(result, {x:p[x] for x in ['assignment','metrics','bounds']})
        self.assertEqual(baseline_record(self.m), p['baseline'])
        r = self.result(p)
        self.assertEqual(r.exit_code,0)
        self.assertEqual(r.to_dict()['optimality'],'not_certified')
        self.assertEqual(r.to_dict()['checks'],dict(coverage=True,arithmetic=True,baseline=True))

    def test_search_claim_not_trusted(self):
        r = self.result(hand_plan(self.m, claim='search_complete'),require_optimal=True)
        self.assertEqual(r.exit_code,6)
        self.assertEqual(r.to_dict()['optimality'],'not_certified')

    def test_optional_audit_exact_final_cap(self):
        for limit,state,code,opt in [(16,'completed',0,'audit_proved'),(15,'budget_exhausted',6,'unknown'),(0,'budget_exhausted',6,'unknown')]:
            with self.subTest(limit=limit):
                r=self.result(hand_plan(self.m),audit_optimal=True,audit_visits=limit,require_optimal=True)
                self.assertEqual(r.exit_code,code)
                self.assertEqual(r.to_dict()['audit']['state'],state)
                self.assertEqual(r.to_dict()['audit']['assignments_visited'],limit)
                self.assertEqual(r.to_dict()['optimality'],opt)

    def test_counterexample_and_forged_claim(self):
        for claim,code,opt in [('feasible',0,'not_optimal'),('search_complete',3,'contradicted')]:
            with self.subTest(claim=claim):
                r=self.result(hand_plan(self.m,baseline=True,claim=claim),audit_optimal=True)
                d=r.to_dict()
                self.assertEqual(r.exit_code,code)
                self.assertEqual(d['optimality'],opt)
                self.assertEqual(d['audit']['state'],'counterexample')
                self.assertEqual(d['audit']['assignments_visited'],4)
                self.assertEqual(d['audit']['witness'],dict(assignment_vector=[0,0,1,1],makespan_ms=60))

    def test_resealed_mutations_rejected(self):
        from shardcairn.canonical import canonical_bytes
        mutations = [
            lambda p:p['assignment'][0]['unit_ids'].append('C'),
            lambda p:p['assignment'][0]['unit_ids'].__setitem__(0,'unknown'),
            lambda p:p['assignment'][0]['unit_ids'].reverse(),
            lambda p:p['assignment'][0]['selectors'].reverse(),
            lambda p:p['assignment'][0]['selectors'].append('c'),
            lambda p:p['assignment'][0]['setup_ids'].clear(),
            lambda p:p['assignment'][0].__setitem__('load_ms',51),
            lambda p:p['metrics'].__setitem__('activated_setup_occurrences',2),
            lambda p:p['bounds']['gap_fraction'].__setitem__('denominator',12),
            lambda p:p['bounds'].__setitem__('average_lower_bound_ms',54),
            lambda p:p['baseline']['shards'][0]['unit_ids'].reverse(),
            lambda p:p['baseline']['metrics'].__setitem__('total_work_ms',141),
            lambda p:p['manifest_hash'].__setitem__('digest','0'*64),
            lambda p:p['claim'].__setitem__('status','bound_tight'),
            lambda p:p['claim'].__setitem__('secondary_optimal',True),
            lambda p:p['solver']['exact'].__setitem__('state','completed'),
            lambda p:p['solver'].__setitem__('incumbent_source','exact'),
            lambda p:p['solver']['seeds'][0].__setitem__('state','not_started'),
            lambda p:p['solver']['seeds'].reverse(),
            lambda p:p['work'].__setitem__('primitive_work_used',1001),
            lambda p:p['work'].__setitem__('local_state','budget_exhausted'),
            lambda p:p['work'].__setitem__('denied_budgets',['primitive_work']),
            lambda p:p['work']['budget_events'].append({'phase':'local','budget':'exact_nodes'}),
        ]
        for index,change in enumerate(mutations):
            with self.subTest(index=index):
                p=hand_plan(self.m); change(p)
                # Re-serialization deliberately removes any integrity shortcut.
                r=self.result(canonical_bytes(p),audit_optimal=True)
                self.assertEqual(r.exit_code,3)
                self.assertEqual(r.to_dict()['result'],'invalid')
                self.assertEqual(r.to_dict()['audit']['state'],'not_run')

    def test_all_objects_closed_and_required(self):
        def objects(value,path=()):
            if isinstance(value,dict):
                yield path,value
                for key,v in value.items():yield from objects(v,path+(key,))
            elif isinstance(value,list):
                for index,v in enumerate(value):yield from objects(v,path+(index,))
        original=hand_plan(self.m)
        for path,node in objects(original):
            for key in list(node)+['unknown_field']:
                with self.subTest(path=path,key=key):
                    p=copy.deepcopy(original); at=p
                    for step in path:at=at[step]
                    if key=='unknown_field':at[key]=None
                    else:del at[key]
                    self.assertEqual(self.result(p).exit_code,3)

    def test_schema_integer_is_not_bool(self):
        p=hand_plan(self.m);p['plan_version']=True
        self.assertEqual(self.result(p).exit_code,3)
        p=hand_plan(self.m);p['claim']['secondary_optimal']=0
        self.assertEqual(self.result(p).exit_code,3)

    def test_malformed_json_and_null_checks(self):
        r=self.result(b'{"assignment":[],"assignment":[]}',audit_optimal=True)
        self.assertEqual(r.exit_code,3)
        self.assertEqual(r.to_dict()['checks'],dict(coverage=None,arithmetic=None,baseline=None))
        self.assertEqual(r.to_dict()['audit']['state'],'not_run')

    def test_import_boundary(self):
        import shardcairn.verifier as verifier
        import shardcairn.audit as audit
        allowlists={verifier:{'audit','canonical','errors','manifest','parsing'},
                    audit:{'errors','manifest'}}
        for module,allowed in allowlists.items():
            tree=ast.parse(Path(module.__file__).read_text(encoding='utf8'))
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom) and node.level:
                    self.assertEqual(node.level,1)
                    names=[node.module.split('.')[0]] if node.module else [alias.name for alias in node.names]
                    self.assertTrue(set(names)<=allowed,(module.__name__,names))
                elif isinstance(node,(ast.Import,ast.ImportFrom)):
                    names=([node.module] if isinstance(node,ast.ImportFrom) else [alias.name for alias in node.names])
                    for name in names:
                        self.assertNotIn('shardcairn',(name or '').split('.'))





def zero_case(n=3, k=2):
    from shardcairn.manifest import load_manifest
    from shardcairn.canonical import manifest_sha256
    from shardcairn.verifier import evaluate_assignment, baseline_record
    m=load_manifest(json.dumps({'schema_version':1,'timing_basis':'exclusive-additive-once-per-shard-v1','shards':k,
        'setups':[{'id':'free','cost_ms':0},{'id':'unused','cost_ms':9007199254740991}],
        'units':[{'id':'U'+str(i),'selectors':['selector'+str(i)],'exclusive_cost_ms':0,'setup_ids':['free']} for i in range(n)]}).encode())
    vector=tuple(list(range(k))+[0]*(n-k))
    p=hand_plan(model())
    p['manifest_hash']['digest']=manifest_sha256(m)
    p.update(evaluate_assignment(m,vector))
    p['baseline']=baseline_record(m)
    p['solver'].update(requested_mode='auto',initial_seed='lpt',incumbent_source='seed',
        exact={'state':'skipped_bound_tight'},seeds=[{'id':'lpt','state':'completed'},{'id':'marginal','state':'not_started'},{'id':'affinity','state':'not_started'}])
    p['work'].update(primitive_work_used=0,local_candidates_started=0,exact_nodes_entered=0,local_state='not_started')
    p['claim']['status']='bound_tight'
    return m,p


class VerifierBoundaryTests(unittest.TestCase):
    def test_zero_activations_bound_skip_and_gap(self):
        from shardcairn.verifier import verify
        from shardcairn.manifest import VerifyOptions
        m,p=zero_case()
        self.assertEqual(p['metrics']['activated_setup_occurrences'],2)
        self.assertEqual(p['metrics']['setup_total_ms'],0)
        self.assertEqual(p['bounds']['gap_fraction'],{'numerator':0,'denominator':1})
        self.assertTrue(all(row['unit_ids'] for row in p['assignment']))
        r=verify(m,p,VerifyOptions(audit_optimal=True,audit_visits=0,require_optimal=True))
        self.assertEqual(r.exit_code,0)
        self.assertEqual(r.to_dict()['optimality'],'bound_proved')
        self.assertEqual(r.to_dict()['audit']['state'],'not_needed')
        self.assertEqual(r.to_dict()['audit']['assignments_visited'],0)

    def test_audit_eligibility_before_bound_skip(self):
        from shardcairn.verifier import verify
        from shardcairn.manifest import VerifyOptions
        from shardcairn.errors import ShardCairnError
        for n,k in [(11,1),(7,7),(10,6)]:
            with self.subTest(n=n,k=k):
                m,p=zero_case(n,k)
                with self.assertRaises(ShardCairnError) as ctx:
                    verify(m,p,VerifyOptions(audit_optimal=True))
                self.assertEqual(ctx.exception.exit_code,2)

    def test_embedded_schemas_match_distributed_approved_shapes(self):
        from shardcairn.verifier import _SCHEMAS
        directory=Path(__file__).parents[1]/'src'/'shardcairn'/'schemas'
        self.assertEqual(set(_SCHEMAS),{p.name.removesuffix('.schema.json') for p in directory.glob('*.schema.json')})
        for name,shape in _SCHEMAS.items():
            self.assertEqual(shape,json.loads((directory/(name+'.schema.json')).read_text()),name)

    def test_mandatory_resource_failure_never_valid(self):
        from shardcairn.verifier import verify
        from shardcairn.manifest import VerifyOptions
        from unittest.mock import patch
        with patch('shardcairn.verifier.PLAN_MAX_BYTES',32):
            r=verify(model(),hand_plan(model()),VerifyOptions(audit_optimal=True))
        self.assertEqual(r.exit_code,5)
        self.assertEqual(r.to_dict()['result'],'resource_limit')
        self.assertEqual(r.to_dict()['optimality'],'unknown')
        self.assertEqual(r.to_dict()['audit']['state'],'not_run')

    def test_tight_baseline_forbids_attempted_optional_phases(self):
        from shardcairn.verifier import verify
        m,p=zero_case()
        p['solver']['seeds'][1]['state']='completed'
        self.assertEqual(verify(m,p).exit_code,3)

    def test_not_started_marginal_requires_baseline_bound_tight(self):
        from shardcairn.verifier import verify
        m,p=zero_case()
        # Any genuine first-seed skip is justified by the independently known
        # baseline, not by an unrelated final bound-tight result.
        p['solver']['seeds'][1]['state']='budget_exhausted'
        p['work'].update(primitive_work_limit=0,denied_budgets=['primitive_work'],budget_events=[{'phase':'marginal_seed','budget':'primitive_work'}])
        self.assertEqual(verify(m,p).exit_code,3)

    def test_canonical_assignment_bool_and_non_surjection_rejected(self):
        from shardcairn.verifier import evaluate_assignment
        from shardcairn.errors import ShardCairnError
        for vector in [(False,False,1,1),(0,0,0,0),(0,1),(0,1,2,1),[0,0,1,1]]:
            with self.subTest(vector=vector),self.assertRaises(ShardCairnError):
                evaluate_assignment(model(),vector)

    def test_root_precedence_after_denied_seed(self):
        from shardcairn.verifier import verify
        m=model()
        for cap in [0,2]:
            with self.subTest(cap=cap):
                p=hand_plan(m,baseline=True)
                p['solver'].update(requested_mode='auto',exact={'state':'budget_exhausted'})
                p['solver']['seeds'][1]['state']='budget_exhausted'
                p['solver']['seeds'][2]['state']='not_started'
                budget='exact_nodes' if cap==0 else 'primitive_work'
                p['work'].update(primitive_work_limit=0,primitive_work_used=0,local_candidates_started=0,
                    exact_node_limit=cap,exact_nodes_entered=0 if cap==0 else 1,local_state='not_started',
                    denied_budgets=['primitive_work']+(['exact_nodes'] if cap==0 else []),
                    budget_events=[{'phase':'marginal_seed','budget':'primitive_work'},{'phase':'exact','budget':budget}])
                self.assertEqual(verify(m,p).exit_code,0)
                p['work']['budget_events'].reverse()
                self.assertEqual(verify(m,p).exit_code,3)

    def test_local_atomic_denial_precedence(self):
        from shardcairn.verifier import verify
        m=model();p=hand_plan(m)
        p['work'].update(primitive_work_limit=100,primitive_work_used=100,local_candidate_limit=0,
            local_candidates_started=0,local_state='budget_exhausted',denied_budgets=['primitive_work'],
            budget_events=[{'phase':'local','budget':'primitive_work'}])
        self.assertEqual(verify(m,p).exit_code,3)
        p['work']['denied_budgets']=['local_candidates']
        p['work']['budget_events'][0]['budget']='local_candidates'
        self.assertEqual(verify(m,p).exit_code,0)

    def test_bounded_error_report_does_not_echo_source(self):
        from shardcairn.verifier import verify
        p=hand_plan(model());p['assignment'][0]['unit_ids'][0]='x'*64
        d=verify(model(),p).to_dict()
        self.assertNotIn('x'*64,json.dumps(d['errors']))
        self.assertLessEqual(len(json.dumps(d['errors']).encode()),4096)


class VerifierHostileRecordTests(unittest.TestCase):
    def test_plan_document_subclass_cannot_override_bytes(self):
        from shardcairn.manifest import PlanDocument
        from shardcairn.verifier import verify, validate_plan
        from shardcairn.canonical import canonical_bytes
        from shardcairn.errors import ShardCairnError
        m=model();raw=canonical_bytes(hand_plan(m))
        class HostileDocument(PlanDocument):
            def to_bytes(self):return raw
        hostile=HostileDocument(b'{}')
        self.assertEqual(verify(m,hostile).exit_code,3)
        with self.assertRaises(ShardCairnError):validate_plan(m,hostile)


if __name__=='__main__':unittest.main()
