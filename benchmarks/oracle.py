"""Independent benchmark oracle: Cartesian tuples, no optimizer imports or pruning.

All tuples, including infeasible empty-shard assignments, count against the cap.
The direct set-union arithmetic deliberately does not reuse product code.
"""
from __future__ import annotations

from itertools import product

CAP = 1_000_000


def score_assignment(manifest: dict, vector) -> dict:
    units, k = manifest["units"], manifest["shards"]
    if len(vector) != len(units) or any(type(x) is not int or not 0 <= x < k for x in vector):
        raise ValueError("invalid assignment vector")
    if len(set(vector)) != k:
        raise ValueError("every shard must be nonempty")
    registry = {s["id"]: s["cost_ms"] for s in manifest["setups"]}
    exclusive = [0] * k
    setups = [set() for _ in range(k)]
    for unit, shard in zip(units, vector):
        exclusive[shard] += unit["exclusive_cost_ms"]
        setups[shard].update(unit["setup_ids"])
    setup_costs = [sum(registry[s] for s in ids) for ids in setups]
    used = set().union(*setups)
    minimum = sum(registry[s] for s in used)
    setup_total = sum(setup_costs)
    loads = [p + c for p, c in zip(exclusive, setup_costs)]
    return {"exclusive_total_ms": sum(exclusive), "setup_total_ms": setup_total,
            "minimum_setup_ms": minimum, "duplicated_setup_ms": setup_total - minimum,
            "activated_setup_occurrences": sum(map(len, setups)),
            "makespan_ms": max(loads), "total_work_ms": sum(loads)}


def arithmetic_bounds(manifest: dict, upper: int) -> dict:
    registry = {s["id"]: s["cost_ms"] for s in manifest["setups"]}
    units = manifest["units"]
    used = set().union(*(set(u["setup_ids"]) for u in units))
    standalone = max(u["exclusive_cost_ms"] + sum(registry[s] for s in u["setup_ids"]) for u in units)
    necessary = sum(u["exclusive_cost_ms"] for u in units) + sum(registry[s] for s in used)
    average = (necessary + manifest["shards"] - 1) // manifest["shards"]
    lower = max(standalone, average)
    return {"unit_bound_ms": standalone, "average_bound_ms": average, "lower_bound_ms": lower,
            "upper_bound_ms": upper, "absolute_gap_ms": upper - lower,
            "gap": {"numerator": upper - lower, "denominator": upper} if upper else {"numerator": 0, "denominator": 1}}


def enumerate_optimum(manifest: dict, assignment_limit: int = CAP) -> dict:
    if type(assignment_limit) is not int or not 0 <= assignment_limit <= CAP:
        raise ValueError("assignment cap must be in 0..1000000")
    n, k = len(manifest["units"]), manifest["shards"]
    if n > 10 or k > 6 or k ** n > CAP:
        return {"state": "ineligible", "assignment_limit": assignment_limit,
                "assignments_visited": 0, "feasible_assignments": 0, "optimum_ms": None,
                "assignment_vector": None, "best_observed_ms": None}
    # Prepared immutable scalar lists are not product state; every tuple below is
    # scored by rebuilding each shard's set union. No symmetry or bound pruning.
    costs = tuple(u["exclusive_cost_ms"] for u in manifest["units"])
    refs = tuple(tuple(u["setup_ids"]) for u in manifest["units"])
    registry = {s["id"]: s["cost_ms"] for s in manifest["setups"]}
    visited, feasible, best, winner = 0, 0, None, None
    state = "completed"
    for vector in product(range(k), repeat=n):
        if visited == assignment_limit:
            state = "budget_exhausted"
            break
        visited += 1
        if len(set(vector)) != k:
            continue
        feasible += 1
        loads, active = [0] * k, [set() for _ in range(k)]
        for i, shard in enumerate(vector):
            loads[shard] += costs[i]
            active[shard].update(refs[i])
        for shard in range(k):
            loads[shard] += sum(registry[s] for s in active[shard])
        makespan = max(loads)
        if best is None or makespan < best:
            best, winner = makespan, vector
    return {"state": state, "assignment_limit": assignment_limit,
            "assignments_visited": visited, "feasible_assignments": feasible,
            "optimum_ms": best if state == "completed" else None,
            "assignment_vector": list(winner) if winner is not None else None,
            "best_observed_ms": best}
