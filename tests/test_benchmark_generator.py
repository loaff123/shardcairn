"""Literal, independently authored generator records precede implementation."""
import hashlib
import gzip
import importlib.util
import json
from pathlib import Path

import unittest

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmarks"
GOLDEN = json.loads((BENCH / "golden-records.json").read_text())


def generator():
    path = BENCH / "generate.py"
    assert path.is_file(), "The portable generator is not implemented yet"
    spec = importlib.util.spec_from_file_location("benchmark_generator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BenchmarkGeneratorTests(unittest.TestCase):
    def test_independent_golden_unsigned_lcg_draws(self):
        rng = generator().LCG(GOLDEN["initial_state"])
        assert [rng.draw() for _ in GOLDEN["draws"]] == GOLDEN["draws"]
        assert rng.draw_count == len(GOLDEN["draws"])


    def test_independent_golden_complete_cases(self):
        for record in GOLDEN["cases"]:
            with self.subTest(case_index=record["case_index"]):
                manifest, ledger = generator().generate_case(record["base_seed"], record["case_index"], record["family"])
                assert manifest["shards"] == record["K"]
                assert len(manifest["units"]) == record["N"]
                assert len(manifest["setups"]) == record["S"]
                assert [s["cost_ms"] for s in manifest["setups"]] == record["setup_costs"]
                observed = [[u["exclusive_cost_ms"], [int(s[1:]) for s in u["setup_ids"]], len(u["selectors"])] for u in manifest["units"]]
                assert observed == record["units"]
                for i, unit in enumerate(manifest["units"]):
                    assert unit["id"] == f"u{i:04d}"
                    assert unit["selectors"] == [f"tests/test_generated.py::test_u{i:04d}_m{m:04d}" for m in range(len(unit["selectors"]))]
                for key in ("initial_state", "draw_count", "final_state", "mode"):
                    assert ledger[key] == record[key]
                assert ledger["manifest_sha256"] == hashlib.sha256(generator().manifest_bytes(manifest)).hexdigest()


    def test_complete_membership_and_separate_initial_states(self):
        module = generator()
        records = list(module.generated_cases())
        assert len(records) == 300
        assert sum(r[1]["family"] == "tiny" for r in records) == 200
        assert sum(r[1]["family"] == "medium" for r in records) == 100
        assert len({r[1]["case_id"] for r in records}) == 300
        heldout = [r[1] for r in records if r[1]["held_out"]]
        assert len(heldout) == 12
        assert all(r["mode"] == 4 and r["base_seed"] in (34, 55) for r in heldout)
        assert max(r[1]["K"] ** r[1]["N"] for r in records if r[1]["family"] == "tiny") <= 1_000_000
        medium, ledger = module.generate_case(0, 0, "medium")
        assert ledger["initial_state"] == 1104732
        assert (ledger["N"], ledger["K"], ledger["S"], ledger["declared_setup_count"]) == (32, 2, 4, 0)
        assert ledger["draw_count"] == 64


    def test_required_fixed_cases_preserve_invalid_overflow_and_toy(self):
        cases = generator().fixed_cases(BENCH / "toy-manifest.json")
        assert len(cases) == 11
        assert cases["setup-reuse-four"] == json.loads((BENCH / "toy-manifest.json").read_bytes())
        assert [u["exclusive_cost_ms"] for u in cases["local-pair-trap"]["units"]] == [20, 14, 12, 10, 6, 6]
        assert sum(u["exclusive_cost_ms"] for u in cases["integer-boundary"]["units"]) == 9007199254740991
        assert sum(u["exclusive_cost_ms"] for u in cases["aggregate-overflow-negative-test"]["units"]) == 9007199254740992
        assert cases["unused-registry"]["setups"][-1] == {"id": "never", "cost_ms": 9007199254740991}


class BenchmarkOracleTests(unittest.TestCase):
    def oracle(self):
        path = BENCH / "oracle.py"
        self.assertTrue(path.is_file(), "Independent Cartesian oracle is not implemented yet")
        spec = importlib.util.spec_from_file_location("benchmark_oracle", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_fixed_oracle_minima_and_tuple_counts(self):
        oracle = self.oracle()
        expected = {"setup-reuse-four": 60, "local-pair-trap": 34,
                    "equal-load-not-equivalent": 5, "no-improvement-equal": 20,
                    "no-improvement-common": 30, "all-zero": 0,
                    "one-shard": 32, "one-unit-per-shard": 23,
                    "unused-registry": 60, "integer-boundary": 9007199254740991}
        for name, optimum in expected.items():
            with self.subTest(case_id=name):
                manifest = generator().fixed_cases()[name]
                result = oracle.enumerate_optimum(manifest)
                self.assertEqual(result["state"], "completed")
                self.assertEqual(result["optimum_ms"], optimum)
                self.assertEqual(result["assignments_visited"], manifest["shards"] ** len(manifest["units"]))
                self.assertEqual(oracle.score_assignment(manifest, result["assignment_vector"])["makespan_ms"], optimum)

    def test_oracle_denied_next_tuple_not_cap_equality(self):
        oracle = self.oracle()
        manifest = generator().fixed_cases()["setup-reuse-four"]
        self.assertEqual(oracle.enumerate_optimum(manifest, 16)["state"], "completed")
        stopped = oracle.enumerate_optimum(manifest, 15)
        self.assertEqual(stopped["state"], "budget_exhausted")
        self.assertIsNone(stopped["optimum_ms"])
        self.assertEqual(stopped["assignments_visited"], 15)
        self.assertEqual(oracle.enumerate_optimum(manifest, 0)["assignments_visited"], 0)

    def test_oracle_independent_imports_and_zero_activation_metrics(self):
        oracle = self.oracle()
        import ast
        tree = ast.parse((BENCH / "oracle.py").read_text())
        modules = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        modules += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        self.assertFalse(any(m and m.startswith("shardcairn") for m in modules))
        manifest = generator().fixed_cases()["all-zero"]
        metrics = oracle.score_assignment(manifest, [0, 1, 2, 3, 0, 0, 0])
        self.assertEqual(metrics["activated_setup_occurrences"], 2)
        self.assertEqual(metrics["total_work_ms"], 0)
        self.assertEqual(oracle.arithmetic_bounds(manifest, 0)["gap"], {"numerator": 0, "denominator": 1})
        with self.assertRaises(ValueError):
            oracle.score_assignment(manifest, [0] * 7)


class FrozenDatasetTests(unittest.TestCase):
    def test_frozen_index_and_regeneration(self):
        folder = BENCH / "original-synthetic-v1"
        self.assertEqual(hashlib.sha256((folder / "SHA256SUMS").read_bytes()).hexdigest(), "5cc744a2d8ea20b16b0147208355a74e441f447836731033f12afe0905cbe1be")
        lines = (folder / "SHA256SUMS").read_text().splitlines()
        self.assertEqual(len(lines), 315)
        for line in lines:
            digest, path = line.split("  ", 1)
            self.assertEqual(hashlib.sha256((folder / path).read_bytes()).hexdigest(), digest, path)
        self.assertEqual((folder / "BENCHMARK-PROTOCOL.md").read_bytes(), (BENCH / "BENCHMARK-PROTOCOL.md").read_bytes())
        ledger = [json.loads(line) for line in (folder / "ledger.jsonl").read_text().splitlines()]
        for manifest, record in generator().generated_cases():
            self.assertIn(record, ledger)
            frozen = folder / record["family"] / (record["case_id"] + ".json")
            self.assertEqual(frozen.read_bytes(), generator().manifest_bytes(manifest))

        for name, manifest in generator().fixed_cases().items():
            self.assertEqual((folder / "fixed" / (name + ".json")).read_bytes(), generator().manifest_bytes(manifest))

    def test_evaluation_loader_checks_frozen_index(self):
        path = BENCH / "evaluate.py"
        self.assertTrue(path.is_file(), "Public-API benchmark evaluation is not implemented yet")
        import sys
        sys.path.insert(0, str(BENCH))
        try:
            spec = importlib.util.spec_from_file_location("benchmark_evaluate", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            members = module.load_frozen(BENCH / "original-synthetic-v1")
        finally:
            sys.path.pop(0)
        self.assertEqual(len(members), 311)
        self.assertEqual(sum(m["expected_valid"] for m in members), 310)
        self.assertEqual(sum(m["held_out"] for m in members), 12)


class CompletedEvaluationTests(unittest.TestCase):
    def test_complete_frozen_oracle_records(self):
        rows = [json.loads(x) for x in (BENCH / "oracles-v1" / "oracle-results.jsonl").read_text().splitlines()]
        tiny = [r for r in rows if r["family"] == "tiny"]
        self.assertEqual(len(tiny), 200)
        self.assertTrue(all(r["state"] == "completed" and r["optimum_ms"] is not None for r in tiny))
        self.assertTrue(all(r["assignments_visited"] <= 1_000_000 for r in tiny))
        self.assertEqual(len({r["case_id"] for r in rows}), 310)
        self.assertEqual(sum(r["held_out"] for r in rows), 12)

    def test_complete_evaluation_keeps_misses_and_held_outs(self):
        folder = BENCH / "evaluation-v1"
        self.assertTrue((folder / "summary.json").is_file(), "Stable complete benchmark evaluation is not recorded yet")
        raw_path = folder / "cases.jsonl"
        raw = raw_path.read_bytes() if raw_path.exists() else gzip.decompress((folder / "cases.jsonl.gz").read_bytes())
        self.assertEqual(len(raw), 1857958)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), "18ab43daa943c7fdb37fa7b2b31a06303220ba9bc385f1b347a17ec4d6cffb55")
        rows = [json.loads(x) for x in raw.splitlines()]
        self.assertEqual(len(rows), 930)
        self.assertEqual(len({(r["case_id"], r["method"]) for r in rows}), 930)
        self.assertEqual(sum(r["held_out"] for r in rows), 36)
        trap = {r["method"]: r for r in rows if r["case_id"] == "local-pair-trap"}
        self.assertEqual([trap[m]["metrics"]["makespan_ms"] for m in ("baseline", "heuristic", "auto")], [36, 36, 34])
        self.assertEqual(trap["heuristic"]["error_vs_oracle_ms"], 2)
        self.assertEqual(trap["heuristic"]["error_vs_oracle_fraction"], {"numerator": 2, "denominator": 34})
        self.assertTrue(all(r["exit_code"] == 0 for r in rows))
        self.assertTrue((folder / "RESULTS.md").is_file())
        self.assertTrue(any(r["method"] == "heuristic" and not r["strict_baseline_improvement"] for r in rows))
        tiny_auto = [r for r in rows if r["family"] == "tiny" and r["method"] == "auto"]
        self.assertEqual(len(tiny_auto), 200)
        self.assertTrue(all(r["error_vs_oracle_ms"] == 0 for r in tiny_auto))
        self.assertTrue(json.loads((folder / "run.json").read_bytes())["product_sources_unchanged_during_run"])
        rejects = [json.loads(x) for x in (folder / "rejections.jsonl").read_text().splitlines()]
        self.assertEqual([r["case_id"] for r in rejects], ["aggregate-overflow-negative-test"])
        self.assertTrue(rejects[0]["rejected_before_optimization"])
        for line in (folder / "SHA256SUMS").read_text().splitlines():
            digest, path = line.split("  ", 1)
            self.assertEqual(hashlib.sha256((folder / path).read_bytes()).hexdigest(), digest, path)

if __name__ == "__main__":
    unittest.main()
