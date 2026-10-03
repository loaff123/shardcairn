"""Closed manifest, immutable public records, and canonical identity tests."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from shardcairn.errors import ShardCairnError
from shardcairn.manifest import (ArtifactResult, Manifest, PlanDocument, PlanOptions,
    Setup, Unit, VerificationResult, VerifyOptions, load_manifest,
    manifest_to_dict, validate_manifest)
from shardcairn.canonical import canonical_bytes, canonical_manifest_bytes, manifest_sha256, sha256_bytes
from shardcairn.parsing import MAX_SAFE_INTEGER


def source():
    return {'schema_version': 1, 'timing_basis': 'exclusive-additive-once-per-shard-v1',
            'shards': 1, 'setups': [{'id': 'z', 'cost_ms': 2}, {'id': 'a', 'cost_ms': 0}],
            'units': [{'id': 'A', 'selectors': [' x\\y::é', '-opaque'],
                       'exclusive_cost_ms': 3, 'setup_ids': ['z', 'a']}]}


def encoded(value):
    return json.dumps(value, ensure_ascii=True).encode()


class ManifestTests(unittest.TestCase):
    def reject(self, value, exit_code=3):
        with self.assertRaises(ShardCairnError) as caught:
            load_manifest(encoded(value))
        self.assertEqual(caught.exception.exit_code, exit_code)

    def test_load_and_roundtrip_preserve_opaque_string_order(self):
        data = source()
        manifest = load_manifest(encoded(data))
        self.assertIsInstance(manifest, Manifest)
        self.assertEqual(manifest.units[0].selectors, tuple(data['units'][0]['selectors']))
        self.assertEqual(manifest_to_dict(manifest), data)
        self.assertIs(validate_manifest(manifest), manifest)

    def test_all_closed_objects_required_and_unknown_fields(self):
        for path in [(), ('setups', 0), ('units', 0)]:
            original = source()
            record = original
            for key in path:
                record = record[key]
            for field in list(record):
                candidate = deepcopy(original)
                target = candidate
                for key in path:
                    target = target[key]
                del target[field]
                with self.subTest(path=path, missing=field):
                    self.reject(candidate)
            record['unknown-private-input'] = 1
            self.reject(original)

    def test_wrong_container_shapes(self):
        for field in ['setups', 'units']:
            for value in [None, {}, 'x', 1]:
                candidate = source(); candidate[field] = value
                self.reject(candidate)
        for field in ['selectors', 'setup_ids']:
            for value in [None, {}, 'x', 1]:
                candidate = source(); candidate['units'][0][field] = value
                self.reject(candidate)
        self.reject([])

    def test_versions_basis_shard_range_and_nonempty_arrays(self):
        for field, values in [('schema_version', [True, 2, '1', None]), ('timing_basis', [None, 'wrong']),
                              ('shards', [True, 0, 2, '1', None])]:
            for value in values:
                candidate = source(); candidate[field] = value
                self.reject(candidate)
        candidate = source(); candidate['units'] = []; self.reject(candidate)
        candidate = source(); candidate['units'][0]['selectors'] = []; self.reject(candidate)

    def test_ids_are_exact_ascii_closed_grammar(self):
        for value in ['', 'a' * 65, '_a', '1a', 'é', 'a\n', 'a b', 1, None]:
            for namespace in ['setups', 'units']:
                candidate = source(); candidate[namespace][0]['id'] = value
                self.reject(candidate)
        candidate = source(); candidate['units'][0]['id'] = 'A' + '_.-9' * 15 + '123'
        self.assertEqual(len(load_manifest(encoded(candidate)).units[0].id), 64)

    def test_costs_reject_bool_null_strings_negative_overflow(self):
        for field, namespace in [('exclusive_cost_ms', 'units'), ('cost_ms', 'setups')]:
            for value in [True, None, '1', -1, MAX_SAFE_INTEGER + 1, 1.0]:
                candidate = source(); candidate[namespace][0][field] = value
                self.reject(candidate)

    def test_duplicate_namespaces_members_and_references(self):
        candidate = source(); candidate['setups'].append(deepcopy(candidate['setups'][0])); self.reject(candidate)
        candidate = source(); candidate['units'].append(deepcopy(candidate['units'][0])); self.reject(candidate)
        candidate = source(); candidate['units'][0]['selectors'] *= 2; self.reject(candidate)
        candidate = source(); candidate['units'][0]['setup_ids'] *= 2; self.reject(candidate)
        candidate = source(); candidate['units'].append({'id': 'B', 'selectors': ['-opaque'], 'exclusive_cost_ms': 0, 'setup_ids': []}); self.reject(candidate)
        candidate = source(); candidate['units'][0]['setup_ids'] = ['missing']; self.reject(candidate)
        candidate = source(); candidate['units'][0]['id'] = 'a'
        self.assertEqual(load_manifest(encoded(candidate)).units[0].id, 'a')

    def test_selector_scalar_control_and_size_rules(self):
        for value in ['', '\x00', '\x1f', '\x7f', '\x9f', '\ud800', 'x' * 4097, 1, None]:
            candidate = source(); candidate['units'][0]['selectors'] = [value]; self.reject(candidate)
        candidate = source(); candidate['units'][0]['selectors'] = ['\U0001f600' * 4096]
        self.assertEqual(len(load_manifest(encoded(candidate)).units[0].selectors[0]), 4096)
        candidate['units'][0]['selectors'] = ['é', 'e\u0301']
        self.assertEqual(len(load_manifest(encoded(candidate)).units[0].selectors), 2)

    def test_aggregate_bound_charges_each_unit_reference(self):
        candidate = source(); candidate['setups'] = [{'id': 'z', 'cost_ms': MAX_SAFE_INTEGER}]
        candidate['units'][0].update(exclusive_cost_ms=0, setup_ids=['z'])
        self.assertEqual(load_manifest(encoded(candidate)).setups[0].cost_ms, MAX_SAFE_INTEGER)
        candidate['units'].append({'id':'B','selectors':['b'],'exclusive_cost_ms':0,'setup_ids':['z']})
        self.reject(candidate)
        candidate['units'].pop(); candidate['units'][0]['setup_ids'] = []
        candidate['units'][0]['exclusive_cost_ms'] = MAX_SAFE_INTEGER
        self.assertEqual(load_manifest(encoded(candidate)).units[0].exclusive_cost_ms, MAX_SAFE_INTEGER)

    def test_collection_count_caps(self):
        candidate = source(); candidate['setups'] = [{'id': f's{i}', 'cost_ms': 0} for i in range(2048)]
        candidate['units'][0]['setup_ids'] = [f's{i}' for i in range(64)]
        load_manifest(encoded(candidate))
        candidate['units'][0]['setup_ids'].append('s64'); self.reject(candidate, 5)
        candidate['units'][0]['setup_ids'].pop(); candidate['setups'].append({'id':'extra','cost_ms':0}); self.reject(candidate, 5)
        candidate = source(); candidate['units'] = [{'id':f'u{i}', 'selectors':[f't{i}'], 'exclusive_cost_ms':0, 'setup_ids':[]} for i in range(10000)]
        load_manifest(encoded(candidate))
        candidate['units'].append({'id':'extra','selectors':['extra'],'exclusive_cost_ms':0,'setup_ids':[]}); self.reject(candidate, 5)
        candidate = source(); candidate['units'][0]['selectors'] = [f't{i}' for i in range(50000)]
        load_manifest(encoded(candidate))
        candidate['units'].append({'id':'extra','selectors':['extra'],'exclusive_cost_ms':0,'setup_ids':[]}); self.reject(candidate, 5)

    def test_manual_records_are_immutable_and_revalidated(self):
        manifest = load_manifest(encoded(source()))
        with self.assertRaises(FrozenInstanceError):
            manifest.shards = 2
        with self.assertRaises(ShardCairnError):
            Unit('A', ['a'], 0, ())
        with self.assertRaises(ShardCairnError):
            Manifest(1, manifest.timing_basis, 1, [], manifest.units)
        object.__setattr__(manifest.units[0], 'exclusive_cost_ms', True)
        with self.assertRaises(ShardCairnError):
            validate_manifest(manifest)
        with self.assertRaises(ShardCairnError):
            manifest_to_dict(manifest)

    def test_manual_manifest_cannot_bypass_input_byte_cap(self):
        # Each individual unit is legal; their aggregate minimal UTF-8 form is not.
        units = tuple(Unit(f'U{i}', (f'{i:04}' + 'x' * 4092,), 0, ()) for i in range(4100))
        with self.assertRaises(ShardCairnError) as caught:
            Manifest(1, 'exclusive-additive-once-per-shard-v1', 1, (), units)
        self.assertEqual(caught.exception.exit_code, 5)

    def test_local_path_loading_does_not_modify_source(self):
        raw = encoded(source())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'manifest.json'; path.write_bytes(raw)
            self.assertEqual(load_manifest(path), load_manifest(str(path)))
            self.assertEqual(path.read_bytes(), raw)


class CanonicalTests(unittest.TestCase):
    def test_json_golden_safe_values_and_ascii_escaping(self):
        self.assertEqual(canonical_bytes({'z': 'é\U0001f600', 'a': [0,MAX_SAFE_INTEGER,True,None]}),
                         b'{"a":[0,9007199254740991,true,null],"z":"\\u00e9\\ud83d\\ude00"}\n')
        for value in [1.0, -1, MAX_SAFE_INTEGER+1, '\ud800', {'é': 1}, {1:2}, set(), b'bytes']:
            with self.subTest(value=type(value)):
                with self.assertRaises(ShardCairnError): canonical_bytes(value)

    def test_ascii_escape_size_bound_matches_every_ascii_character(self):
        value = ''.join(chr(point) for point in range(128))
        self.assertEqual(canonical_bytes(value), (json.dumps(value, ensure_ascii=True) + '\n').encode())

    def test_normalization_preserves_semantic_identity_only(self):
        a = source(); b = deepcopy(a)
        b['setups'].reverse(); b['units'][0]['setup_ids'].reverse()
        self.assertEqual(canonical_manifest_bytes(load_manifest(encoded(a))), canonical_manifest_bytes(load_manifest(encoded(b))))
        self.assertEqual(manifest_sha256(load_manifest(encoded(a))), manifest_sha256(load_manifest(encoded(b))))
        b['units'][0]['selectors'].reverse()
        self.assertNotEqual(manifest_sha256(load_manifest(encoded(a))), manifest_sha256(load_manifest(encoded(b))))
        canonical = canonical_manifest_bytes(load_manifest(encoded(a)))
        self.assertEqual(manifest_sha256(load_manifest(encoded(a))), hashlib.sha256(canonical).hexdigest())
        self.assertEqual(sha256_bytes(b'abc'), hashlib.sha256(b'abc').hexdigest())

    def test_returned_dictionary_is_detached(self):
        manifest = load_manifest(encoded(source()))
        detached = manifest_to_dict(manifest); detached['units'][0]['selectors'].append('changed')
        self.assertEqual(len(manifest.units[0].selectors), 2)

    def test_manual_depth_and_output_caps(self):
        value = 0
        for _ in range(17): value = [value]
        with self.assertRaises(ShardCairnError) as caught: canonical_bytes(value)
        self.assertEqual(caught.exception.exit_code, 5)
        with self.assertRaises(ShardCairnError) as caught: canonical_bytes('\U0001f600' * 5600000)
        self.assertEqual(caught.exception.exit_code, 5)


class PublicRecordTests(unittest.TestCase):
    def test_options_exact_types_ranges_and_defaults(self):
        self.assertEqual(PlanOptions().work_limit, 5000000)
        self.assertIsInstance(PlanOptions().validate(), PlanOptions)
        PlanOptions(mode='exact', work_limit=0, local_candidates=0, exact_nodes=0)
        PlanOptions(work_limit=50000000, local_candidates=2000000, exact_nodes=2000000)
        VerifyOptions(audit_visits=0).validate()
        for kwargs in [{'mode':'other'}, {'work_limit':True}, {'work_limit':50000001}, {'local_candidates':2000001}, {'exact_nodes':-1}]:
            with self.assertRaises(ShardCairnError) as caught: PlanOptions(**kwargs)
            self.assertEqual(caught.exception.exit_code, 2)
        for kwargs in [{'audit_optimal':1}, {'require_optimal':None}, {'audit_visits':1000001}, {'audit_visits':True}]:
            with self.assertRaises(ShardCairnError) as caught: VerifyOptions(**kwargs)
            self.assertEqual(caught.exception.exit_code, 2)

    def test_plan_document_and_results_are_immutable_detached_canonical(self):
        for result in [PlanDocument(b'{ "x": [1] }'), ArtifactResult(b'{ "x": [1] }'), VerificationResult(b'{ "x": [1] }', 0)]:
            self.assertEqual(result.to_bytes(), b'{"x":[1]}\n')
            detached = result.to_dict(); detached['x'].append(2)
            self.assertEqual(result.to_dict(), {'x':[1]})
            with self.assertRaises(FrozenInstanceError): result.data = b'{}'
        for raw in [b'[]', b'{"x":1,"x":2}', b'{"x":1.0}', '{}']:
            with self.assertRaises(ShardCairnError): PlanDocument(raw)
        with self.assertRaises(ShardCairnError): VerificationResult(b'{}', True)


if __name__ == '__main__': unittest.main()
