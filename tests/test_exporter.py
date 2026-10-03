"""Export safety regressions; fixtures are original and contain no project tests."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shardcairn.exporter import export, write_plan, verify_directory
from shardcairn.manifest import load_manifest, PlanDocument
from shardcairn.canonical import canonical_bytes, manifest_sha256
from shardcairn.errors import ShardCairnError
from shardcairn.verifier import evaluate_assignment, baseline_record


def sample(selectors=None, shards=2):
    names = selectors or ['owned/test_owned.py::TestA::test_first', 'owned/test_owned.py::TestA::test_second', 'owned/test_owned.py::test_b', 'owned/test_owned.py::test_c', 'owned/test_owned.py::test_d']
    units = [dict(id='A', selectors=names[:2], exclusive_cost_ms=10, setup_ids=['x']), dict(id='B', selectors=[names[2]], exclusive_cost_ms=10, setup_ids=['x']), dict(id='C', selectors=[names[3]], exclusive_cost_ms=30, setup_ids=[]), dict(id='D', selectors=[names[4]], exclusive_cost_ms=30, setup_ids=[])]
    manifest = load_manifest(canonical_bytes(dict(schema_version=1, timing_basis='exclusive-additive-once-per-shard-v1', shards=shards, setups=[dict(id='x',cost_ms=30)], units=units)))
    evaluated = evaluate_assignment(manifest, (0,0,1,1) if shards == 2 else (0,0,0,0))
    plan = dict(plan_version=1, model_version=manifest.timing_basis, manifest_hash=dict(algorithm='sha256',normalization='shardcairn-manifest-c14n-v1',digest=manifest_sha256(manifest)), solver=dict(algorithm_version='shardcairn-portfolio-v1',requested_mode='heuristic',initial_seed='marginal',incumbent_source='seed',exact=dict(state='not_requested'),seeds=[dict(id=x,state='completed') for x in ('lpt','marginal','affinity')]),work=dict(primitive_work_limit=1000,local_candidate_limit=100,exact_node_limit=0,primitive_work_used=100,local_candidates_started=20 if shards == 2 else 0,exact_nodes_entered=0,denied_budgets=[],budget_events=[],local_state='fixed_point' if shards == 2 else 'not_started'), baseline=baseline_record(manifest),**evaluated, claim=dict(status='bound_tight' if shards == 1 else 'feasible',primary_objective='makespan',secondary_optimal=False))
    return manifest, PlanDocument(canonical_bytes(plan))


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest, self.plan = sample()

    def test_json_export_exact_bytes_and_complete_marker(self):
        target = self.root / 'result'
        result = export(self.manifest, self.plan, target).to_dict()
        self.assertEqual(result['files'], ['complete.json','export.json','shard-000.json','shard-001.json'])
        self.assertEqual(json.loads((target/'shard-000.json').read_bytes()), list(self.manifest.units[0].selectors+self.manifest.units[1].selectors))
        marker = verify_directory(target)
        self.assertEqual(marker['kind'], 'export')
        for record in marker['files']:
            data = (target/record['name']).read_bytes()
            self.assertEqual(record['size_bytes'], len(data))
            self.assertEqual(record['sha256'], hashlib.sha256(data).hexdigest())

    def test_json_selectors_are_inert_and_exact(self):
        names = ['../../victim','--flag',' café \\ @☃','C:/odd::name','literal[params]']
        manifest, plan = sample(names)
        export(manifest, plan, self.root/'result')
        got = json.loads((self.root/'result'/'shard-000.json').read_bytes())
        self.assertEqual(got, names[:3])
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['result'])

    def test_pytest_valid_grammar_and_lf(self):
        export(self.manifest,self.plan,self.root/'result','pytest-argfile')
        expected = '\n'.join(self.manifest.units[0].selectors+self.manifest.units[1].selectors)+'\n'
        self.assertEqual((self.root/'result'/'shard-000.args').read_bytes(),expected.encode())

    def test_pytest_rejects_whole_export_before_creation(self):
        invalid = ['test.py','test.py::test_a[x]','../test.py::test_a','/test.py::test_a','C:/test.py::test_a','test\\x.py::test_a','@test.py::test_a','-test.py::test_a','test a.py::test_a','té.py::test_a','test.py::test_a;id','test.py::test_*','test.py:::test_a','test.py::test_a::x::y','test.py::test_a\n--help']
        for i, selector in enumerate(invalid):
            with self.subTest(selector=selector):
                names = [selector,'owned/test_owned.py::TestA::test_second','owned/test_owned.py::test_b','owned/test_owned.py::test_c','owned/test_owned.py::test_d']
                if '\n' in selector:
                    with self.assertRaises(ShardCairnError): sample(names)
                    continue  # The manifest parser rejects this before export.
                manifest,plan=sample(names)
                target=self.root/f'bad{i}'
                with self.assertRaises(ShardCairnError): export(manifest,plan,target,'pytest-argfile')
                self.assertFalse(target.exists())

    def test_existing_destinations_are_untouched(self):
        directory=self.root/'dir'; directory.mkdir(); (directory/'keep').write_text('keep')
        regular=self.root/'file'; regular.write_text('keep')
        link=self.root/'link'; link.symlink_to(directory,target_is_directory=True)
        dangling=self.root/'dangling'; dangling.symlink_to(self.root/'absent')
        for target in (directory,regular,link,dangling):
            with self.subTest(target=target.name):
                with self.assertRaises(ShardCairnError) as raised: export(self.manifest,self.plan,target)
                self.assertEqual(raised.exception.exit_code,4)
        self.assertEqual((directory/'keep').read_text(),'keep')
        self.assertEqual(regular.read_text(),'keep')
        self.assertTrue(dangling.is_symlink())

    def test_invalid_plan_and_size_fail_before_creation(self):
        damaged=self.plan.to_dict(); damaged['metrics']['makespan_ms']+=1
        target=self.root/'invalid'
        with self.assertRaises(ShardCairnError): export(self.manifest,damaged,target)
        self.assertFalse(target.exists())
        with patch('shardcairn.exporter.OUTPUT_MAX_BYTES', 50):
            with self.assertRaises(ShardCairnError) as raised: export(self.manifest,self.plan,self.root/'huge')
        self.assertEqual(raised.exception.exit_code,5)
        self.assertFalse((self.root/'huge').exists())

    def test_write_plan_report_and_integrity(self):
        target=self.root/'plan'
        result=write_plan(self.manifest,self.plan,target).to_dict()
        self.assertEqual(result['command'],'plan')
        self.assertEqual((target/'plan.json').read_bytes(),self.plan.to_bytes())
        self.assertLessEqual((target/'report.txt').stat().st_size,65536)
        self.assertEqual(verify_directory(target)['kind'],'plan')

    def test_integrity_rejects_extra_missing_modified_and_symlink_files(self):
        for corruption in ('extra','missing','modified','link','marker'):
            with self.subTest(corruption=corruption):
                target=self.root/corruption; export(self.manifest,self.plan,target)
                shard=target/'shard-000.json'
                if corruption=='extra': (target/'unexpected').write_text('x')
                elif corruption=='missing': shard.unlink()
                elif corruption=='modified': shard.write_text('[]\n')
                elif corruption=='link':
                    payload=shard.read_bytes(); shard.unlink(); outside=self.root/'outside'; outside.write_bytes(payload); shard.symlink_to(outside)
                else: (target/'complete.json').unlink()
                with self.assertRaises(ShardCairnError): verify_directory(target)

    def test_failure_cleans_only_invocation_files_and_never_marks_complete(self):
        import shardcairn.exporter as module
        original=module._write_file
        def fail(path,data):
            if path.name == 'shard-000.json': raise OSError('injected write failure')
            return original(path,data)
        with patch.object(module,'_write_file',side_effect=fail):
            with self.assertRaises(ShardCairnError): export(self.manifest,self.plan,self.root/'failure')
        self.assertFalse((self.root/'failure').exists())

    def test_marker_last_and_unexpected_entry_is_preserved_on_failure(self):
        import shardcairn.exporter as module
        original=module._write_file; writes=[]
        def record(path,data):
            writes.append(path.name)
            return original(path,data)
        with patch.object(module,'_write_file',side_effect=record): export(self.manifest,self.plan,self.root/'ok')
        self.assertEqual(writes[-1],'complete.json')
        def inject(path,data):
            result=original(path,data)
            if path.name=='export.json': (path.parent/'intruder').write_text('do not remove')
            return result
        with patch.object(module,'_write_file',side_effect=inject):
            with self.assertRaises(ShardCairnError): export(self.manifest,self.plan,self.root/'injected')
        self.assertEqual((self.root/'injected'/'intruder').read_text(),'do not remove')
        self.assertFalse((self.root/'injected'/'complete.json').exists())

    def test_invalid_destination_type_is_a_domain_error(self):
        with self.assertRaises(ShardCairnError) as raised:
            export(self.manifest,self.plan,None)
        self.assertEqual(raised.exception.exit_code,4)

    def test_resealed_index_count_and_mixed_filenames_are_rejected(self):
        from shardcairn.exporter import _marker
        for mutation in ('count','index','mixed','duplicate'):
            with self.subTest(mutation=mutation):
                target=self.root/mutation
                export(self.manifest,self.plan,target)
                index=json.loads((target/'export.json').read_bytes())
                if mutation=='count': index['shards'][0]['selector_count']+=1
                if mutation=='index': index['shards'][0]['index']=1
                if mutation=='mixed':
                    (target/'shard-000.json').rename(target/'shard-000.args')
                    index['shards'][0]['filename']='shard-000.args'
                if mutation=='duplicate':
                    data=json.loads((target/'shard-001.json').read_bytes())
                    data[0]=self.manifest.units[0].selectors[0]
                    (target/'shard-001.json').write_bytes(canonical_bytes(data))
                (target/'export.json').write_bytes(canonical_bytes(index))
                contents={path.name:path.read_bytes() for path in target.iterdir() if path.name!='complete.json'}
                marker=_marker('export',index['manifest_sha256'],index['plan_sha256'],contents)
                (target/'complete.json').write_bytes(canonical_bytes(marker))
                with self.assertRaises(ShardCairnError): verify_directory(target)

    def test_report_truncates_after_twenty_shards_without_echoing_selectors(self):
        from shardcairn.planner import plan
        from shardcairn.manifest import PlanOptions
        document=dict(schema_version=1,timing_basis='exclusive-additive-once-per-shard-v1',shards=21,setups=[],units=[dict(id=f'U{i}',selectors=[f'private-secret-{i}'],exclusive_cost_ms=0,setup_ids=[]) for i in range(21)])
        manifest=load_manifest(canonical_bytes(document))
        write_plan(manifest,plan(manifest,PlanOptions(mode='heuristic',work_limit=0)),self.root/'many')
        report=(self.root/'many'/'report.txt').read_text()
        self.assertIn('019:',report); self.assertNotIn('020:',report)
        self.assertIn('Truncated: 1',report); self.assertNotIn('private-secret',report)

    def test_module_is_offline_and_never_imports_execution_tools(self):
        import ast
        import shardcairn.exporter as module
        tree=ast.parse(Path(module.__file__).read_text())
        imports={alias.name.split('.')[0] for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names}
        imports|={node.module.split('.')[0] for node in ast.walk(tree) if isinstance(node,ast.ImportFrom) and node.module and not node.level}
        self.assertFalse(imports & {'subprocess','socket','requests','urllib','pytest'})
