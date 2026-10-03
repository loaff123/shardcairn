"""Run the frozen original synthetic comparison using only ShardCairn's public API.

No observed timings enter deterministic case records. The oracle is independent
and its complete Cartesian enumeration is cached by raw manifest SHA-256.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from oracle import arithmetic_bounds, enumerate_optimum, score_assignment

HERE = Path(__file__).resolve().parent
DEFAULTS = {"primitive_work_limit": 5_000_000, "local_candidate_limit": 100_000, "exact_node_limit": 250_000}


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_frozen(folder: Path) -> list[dict]:
    indexed = set()
    for line in (folder / "SHA256SUMS").read_text().splitlines():
        expected, relative = line.split("  ", 1)
        if relative in indexed or digest(folder / relative) != expected:
            raise ValueError(f"frozen index mismatch: {relative}")
        indexed.add(relative)
    members = json.loads((folder / "membership.json").read_bytes())["cases"]
    if len(members) != 311 or sum(x["family"] == "tiny" for x in members) != 200 or sum(x["family"] == "medium" for x in members) != 100:
        raise ValueError("frozen benchmark membership changed")
    for member in members:
        if member["path"] not in indexed or digest(folder / member["path"]) != member["manifest_sha256"]:
            raise ValueError("manifest is not pinned by both ledger and frozen index")
    if sum(x["held_out"] for x in members) != 12:
        raise ValueError("held-out membership changed")
    return members


def oracle_rows(folder: Path, members: list[dict]):
    for member in members:
        if not member["expected_valid"]:
            continue
        manifest = json.loads((folder / member["path"]).read_bytes())
        result = enumerate_optimum(manifest)
        if member["family"] == "tiny" and result["state"] != "completed":
            raise AssertionError("every frozen tiny oracle must complete")
        yield {"case_id": member["case_id"], "manifest_sha256": member["manifest_sha256"],
               "family": member["family"], "base_seed": member["base_seed"],
               "case_index": member["case_index"], "held_out": member["held_out"], **result}


def read_oracles(path: Path, members: list[dict]) -> dict[str, dict]:
    records = [json.loads(line) for line in path.read_text().splitlines()]
    result = {r["case_id"]: r for r in records}
    expected = {m["case_id"] for m in members if m["expected_valid"]}
    if len(result) != len(records) or set(result) != expected:
        raise ValueError("oracle cache must contain every valid frozen case exactly once")
    for m in members:
        if not m["expected_valid"]:
            continue
        r = result[m["case_id"]]
        if r["manifest_sha256"] != m["manifest_sha256"] or (m["family"] == "tiny" and r["state"] != "completed"):
            raise ValueError("oracle cache does not match frozen case")
    return result


def vector_for(manifest: dict, shards: list[dict]) -> list[int]:
    positions = {u["id"]: i for i, u in enumerate(manifest["units"])}
    result = [-1] * len(positions)
    for shard in shards:
        for unit_id in shard["unit_ids"]:
            index = positions[unit_id]
            if result[index] != -1:
                raise AssertionError("duplicate unit in output")
            result[index] = shard["index"]
    if -1 in result:
        raise AssertionError("missing unit in output")
    return result


def bounds_for(manifest: dict, upper: int) -> dict:
    direct = arithmetic_bounds(manifest, upper)
    return {"standalone_lower_bound_ms": direct["unit_bound_ms"],
            "average_lower_bound_ms": direct["average_bound_ms"],
            "lower_bound_ms": direct["lower_bound_ms"], "upper_bound_ms": upper,
            "absolute_gap_ms": direct["absolute_gap_ms"], "gap_fraction": direct["gap"]}


def fingerprint_product() -> dict[str, str]:
    root = HERE.parent
    files = sorted(p for p in (root / "src" / "shardcairn").rglob("*") if p.suffix in (".py", ".json"))
    return {p.relative_to(root).as_posix(): digest(p) for p in files}



def relative_error(upper: int, optimum: int | None):
    if optimum is None:
        return None
    return {"numerator": upper - optimum, "denominator": optimum or 1}


def write_report(output: Path, rows: list[dict], summary: dict) -> None:
    lines = ["# Frozen original synthetic evaluation", "",
             "All costs below are modeled integer milliseconds, not measured CI speedups. "
             "The same default limits apply throughout: 5,000,000 primitive ticks, 100,000 local candidates, and 250,000 exact nodes.", "",
             "## Complete comparison", "",
             "| Method | Strict baseline improvements | Equal makespan | Oracle misses / 210 eligible | Arithmetic bound proofs | Completed exact searches | Budget-exhausted cases |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for method, values in summary["methods"].items():
        names = ("strict_baseline_improvements", "equal_makespan_no_improvement", "oracle_misses", "arithmetic_bound_proofs", "completed_exact_searches", "budget_exhausted_cases")
        lines.append("| " + method + " | " + " | ".join(str(values[n]) for n in names) + " |")
    lines += ["", "Every one of the 200 tiny Cartesian spaces completed independently under the one-million tuple cap. "
              "All 100 medium cases are recorded with unknown oracle optimum; no global-optimum claim follows from heuristic results. "
              "The 10 valid fixed cases also have completed independent oracles. The aggregate-overflow negative fixture was rejected before optimization.", "",
              "Equal makespan is retained as no-faster even if total modeled work improves. "
              "A producer search_complete label is distinct from independent certification; case records retain both.", "",
              "## Fixed cases", "",
              "| Case | Baseline | Heuristic | Auto | Oracle |", "|---|---:|---:|---:|---:|"]
    grouped = {}
    for row in rows:
        grouped.setdefault(row["case_id"], {})[row["method"]] = row
    for case_id, methods in grouped.items():
        if methods["baseline"]["family"] == "fixed":
            values = [methods[m]["metrics"]["makespan_ms"] for m in ("baseline", "heuristic", "auto")]
            lines.append(f"| {case_id} | " + " | ".join(map(str, values)) + f" | {methods['auto']['oracle']['optimum_ms']} |")
    lines += ["", "The local-pair-trap's 36 versus 34 is an intentional, retained heuristic miss. "
              "The documented strict-improvement relocation/swap portfolio cannot escape it. "
              "The no-improvement fixtures and zero-work nonempty assignments are retained without filtering.", "",
              "## All held-out overlapping cases", "",
              "Mode 4 at base seeds 34 and 55 was frozen as held out before implementation tuning. "
              "All 12 cases (36 method rows) are included below and in held-out.jsonl.", "",
              "| Case | Baseline | Heuristic | Auto | Oracle |", "|---|---:|---:|---:|---:|"]
    for case_id, methods in grouped.items():
        if methods["baseline"]["held_out"]:
            values = [methods[m]["metrics"]["makespan_ms"] for m in ("baseline", "heuristic", "auto")]
            optimum = methods["auto"]["oracle"]["optimum_ms"]
            lines.append(f"| {case_id} | " + " | ".join(map(str, values)) + f" | {optimum if optimum is not None else 'unknown'} |")
    lines += ["", "## Every heuristic miss against a completed oracle", "",
              "| Case | Heuristic | Oracle | Error | Held out |", "|---|---:|---:|---:|---|"]
    for row in rows:
        if row["method"] == "heuristic" and row["error_vs_oracle_ms"] not in (None, 0):
            lines.append(f"| {row['case_id']} | {row['metrics']['makespan_ms']} | {row['oracle']['optimum_ms']} | {row['error_vs_oracle_ms']} | {str(row['held_out']).lower()} |")
    lines += ["", "## Inspectable evidence", "",
              "- cases.jsonl: all 930 case/method rows, seed membership, modeled makespan/work/setup duplication, bounds/gaps, oracle errors, counters, events, statuses and verification results",
              "- plans/: all baseline records and complete heuristic/auto producer plans",
              "- summary.json: complete method totals plus every no-improvement and oracle-miss case ID",
              "- held-out.jsonl: every held-out outcome",
              "- rejections.jsonl: required invalid overflow rejection",
              "- run.json: exact defaults, source hashes and unchanged-source check",
              "- SHA256SUMS: exact output bytes", "",
              "This synthetic, deterministic comparison does not measure wall time, production workload representativeness, "
              "statistical confidence, or a globally optimal secondary objective. Resource qualification is separate.", ""]
    (output / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")


def run_evaluation(folder: Path, output: Path, cache: Path) -> None:
    # Imports deliberately restricted to the supported public facade. The oracle
    # above has no imports from the product at all.
    from shardcairn import PlanOptions, ShardCairnError, load_manifest, plan, verify
    members = load_frozen(folder)
    oracles = read_oracles(cache, members)
    output.mkdir(parents=True, exist_ok=False)
    (output / "plans").mkdir()
    fingerprint = fingerprint_product()
    run = {"evaluation_version": "original-synthetic-comparison-v1",
           "protocol_version": "original-synthetic-v1", "default_limits": DEFAULTS,
           "frozen_index_sha256": digest(folder / "SHA256SUMS"),
           "oracle_results_sha256": digest(cache), "oracle_source_sha256": digest(HERE / "oracle.py"),
           "evaluator_source_sha256": digest(Path(__file__)), "product_sources": fingerprint,
           "all_cases_required": True,
           "cost_unit": "modeled integer milliseconds; not elapsed measurements",
           "baseline_work_note": "Mandatory baseline preprocessing is exempt from optional-work ticks; zero ticks do not imply zero CPU work.",
           "held_out_note": "All mode-4 cases at seeds 34 and 55 were excluded from heuristic tuning and are retained without filtering."}
    (output / "run.json").write_bytes(encoded(run))
    rows = []
    with (output / "cases.jsonl").open("wb") as case_file, (output / "rejections.jsonl").open("wb") as rejected_file:
        for member in members:
            raw = (folder / member["path"]).read_bytes()
            manifest = json.loads(raw)
            if not member["expected_valid"]:
                try:
                    load_manifest(raw)
                except ShardCairnError as error:
                    if error.exit_code != 3:
                        raise AssertionError("overflow did not receive invalid-input status") from error
                    rejected_file.write(encoded({"case_id": member["case_id"], "manifest_sha256": member["manifest_sha256"],
                                                 "expected_valid": False, "rejected_before_optimization": True,
                                                 "code": error.code, "exit_code": error.exit_code}))
                else:
                    raise AssertionError("required aggregate-overflow negative case was accepted")
                continue
            parsed = load_manifest(raw)
            oracle = oracles[member["case_id"]]
            common = {key: member.get(key) for key in ("case_id", "family", "base_seed", "case_index", "mode", "held_out", "N", "K", "S", "manifest_sha256")}
            common["oracle"] = oracle
            baseline = None
            for method in ("heuristic", "auto"):
                document = plan(parsed, PlanOptions(mode=method))
                value = document.to_dict()
                verdict = verify(parsed, document)
                if verdict.exit_code != 0:
                    raise AssertionError("public independent verification failed")
                if {key: value["work"][key] for key in DEFAULTS} != DEFAULTS:
                    raise AssertionError("comparison changed the declared default limits")
                vector = vector_for(manifest, value["assignment"])
                direct = score_assignment(manifest, vector)
                if direct != value["metrics"] or bounds_for(manifest, direct["makespan_ms"]) != value["bounds"]:
                    raise AssertionError("benchmark's independent output arithmetic disagrees")
                (output / "plans" / f"{member['case_id']}.{method}.json").write_bytes(document.to_bytes())
                if baseline is None:
                    baseline = value["baseline"]
                    baseline_vector = vector_for(manifest, baseline["shards"])
                    baseline_metrics = score_assignment(manifest, baseline_vector)
                    if baseline_metrics != baseline["metrics"]:
                        raise AssertionError("baseline arithmetic disagrees")
                    baseline_bounds = bounds_for(manifest, baseline_metrics["makespan_ms"])
                    base = {**common, "method": "baseline", "exit_code": 0, "assignment_vector": baseline_vector,
                            "metrics": baseline_metrics, "bounds": baseline_bounds,
                            "work": {**DEFAULTS, "primitive_work_used": 0, "local_candidates_started": 0,
                                     "exact_nodes_entered": 0, "denied_budgets": [], "local_state": "not_started", "budget_events": []},
                            "solver": {"algorithm_version": baseline["algorithm_version"], "exact": {"state": "not_requested"}},
                            "status": "bound_tight" if baseline_bounds["absolute_gap_ms"] == 0 else "feasible",
                            "error_vs_oracle_ms": None if oracle["optimum_ms"] is None else baseline_metrics["makespan_ms"] - oracle["optimum_ms"],
                            "error_vs_oracle_fraction": relative_error(baseline_metrics["makespan_ms"], oracle["optimum_ms"]),
                            "strict_baseline_improvement": False}
                    rows.append(base)
                    case_file.write(encoded(base))
                    (output / "plans" / f"{member['case_id']}.baseline.json").write_bytes(encoded(baseline))
                elif baseline != value["baseline"]:
                    raise AssertionError("the comparison baselines differ")
                row = {**common, "method": method, "exit_code": 0, "assignment_vector": vector,
                       "metrics": value["metrics"], "bounds": value["bounds"], "work": value["work"],
                       "solver": value["solver"], "status": value["claim"]["status"],
                       "verification": verdict.to_dict(),
                       "error_vs_oracle_ms": None if oracle["optimum_ms"] is None else direct["makespan_ms"] - oracle["optimum_ms"],
                       "error_vs_oracle_fraction": relative_error(direct["makespan_ms"], oracle["optimum_ms"]),
                       "strict_baseline_improvement": direct["makespan_ms"] < baseline["metrics"]["makespan_ms"]}
                if row["error_vs_oracle_ms"] is not None and row["error_vs_oracle_ms"] < 0:
                    raise AssertionError("planner beat independently enumerated optimum")
                rows.append(row)
                case_file.write(encoded(row))
                case_file.flush()
            print(member["case_id"], flush=True)
    if len(rows) != 930:
        raise AssertionError("missing baseline/heuristic/auto case records")
    summary = {"valid_cases": 310, "invalid_cases_rejected": 1, "method_rows": len(rows),
               "tiny_oracles_completed": sum(r["state"] == "completed" and r["family"] == "tiny" for r in oracles.values()),
               "held_out_cases": 12, "methods": {}}
    for method in ("baseline", "heuristic", "auto"):
        selected = [r for r in rows if r["method"] == method]
        summary["methods"][method] = {
            "strict_baseline_improvements": sum(r["strict_baseline_improvement"] for r in selected),
            "equal_makespan_no_improvement": sum(not r["strict_baseline_improvement"] for r in selected),
            "oracle_comparisons": sum(r["error_vs_oracle_ms"] is not None for r in selected),
            "oracle_misses": sum(r["error_vs_oracle_ms"] not in (None, 0) for r in selected),
            "arithmetic_bound_proofs": sum(r["status"] == "bound_tight" for r in selected),
            "completed_exact_searches": sum(r["solver"]["exact"]["state"] == "completed" for r in selected),
            "budget_exhausted_cases": sum(bool(r["work"]["budget_events"]) for r in selected),
            "status_counts": dict(Counter(r["status"] for r in selected)),
            "no_improvement_case_ids": [r["case_id"] for r in selected if not r["strict_baseline_improvement"]],
            "oracle_miss_case_ids": [r["case_id"] for r in selected if r["error_vs_oracle_ms"] not in (None, 0)]}
    run["product_sources_unchanged_during_run"] = fingerprint == fingerprint_product()
    if not run["product_sources_unchanged_during_run"]:
        raise RuntimeError("product sources changed during evaluation; preserve this run and repeat in a new directory")
    (output / "run.json").write_bytes(encoded(run))
    (output / "summary.json").write_bytes(encoded(summary))
    (output / "held-out.jsonl").write_bytes(b"".join(encoded(r) for r in rows if r["held_out"]))
    write_report(output, rows, summary)
    index = [(p.relative_to(output).as_posix(), digest(p)) for p in sorted(output.rglob("*")) if p.is_file()]
    (output / "SHA256SUMS").write_text("".join(f"{h}  {name}\n" for name, h in index), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", type=Path, default=HERE / "original-synthetic-v1")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--oracle-only", action="store_true")
    parser.add_argument("--oracles", type=Path)
    args = parser.parse_args()
    if args.oracle_only:
        members = load_frozen(args.frozen)
        args.output.mkdir(parents=True, exist_ok=False)
        with (args.output / "oracle-results.jsonl").open("wb") as target:
            for row in oracle_rows(args.frozen, members):
                target.write(encoded(row))
                target.flush()
                print(row["case_id"], row["state"], row["optimum_ms"], flush=True)
    elif args.oracles is None:
        parser.error("full evaluation requires --oracles from the independent --oracle-only run")
    else:
        run_evaluation(args.frozen, args.output, args.oracles)


if __name__ == "__main__":
    main()
