# ShardCairn

Offline, setup-aware CI shard planning, with deterministic work budgets and an
independent allocation verifier. Python 3.11–3.14; MIT; no runtime dependencies.

ShardCairn is useful when you already have an explicit test inventory and can
separate each unit's repeated work from reusable setup costs. It plans exactly K
nonempty homogeneous, serial shards. It neither collects nor executes tests.

A setup is charged once on each shard using it. An indivisible unit may contain
several ordered test selectors. This narrow model can expose unnecessary setup
duplication that balancing exclusive test durations alone misses. There is no
approximation-ratio, new-algorithm, or measured CI wall-time speedup claim.

## Quick start

Clone and install the source with Python 3.11 or newer:

```console
git clone https://github.com/loaff123/shardcairn.git
cd shardcairn
python -m pip install --no-deps .
shardcairn plan examples/setup-reuse.json --out-dir plan-output
shardcairn verify examples/setup-reuse.json plan-output/plan.json --audit-optimal --require-optimal
shardcairn export examples/setup-reuse.json plan-output/plan.json --out-dir shards
```

This installs from the checkout; there is no PyPI release. For an isolated install,
create and activate a Python virtual environment first.

Output directories must not already exist. Each successful output has a
`complete.json` marker containing exact byte sizes and SHA-256 digests. Consumers
accepting a directory must validate that marker and its exact file set. Individually
supplied plan files are verified independently without reading their siblings.

The included synthetic example compares exclusive-cost LPT loads of 70/70 with a
setup-aware assignment of 50/60 modeled milliseconds. Its true model optimum is
60 and its arithmetic lower bound is 55. These are illustrative estimates, not
observed runner timings. The benchmark also preserves a heuristic miss (36 versus
an independently enumerated optimum of 34) and cases with no improvement.

## Input contract

```json
{
  "schema_version": 1,
  "timing_basis": "exclusive-additive-once-per-shard-v1",
  "shards": 2,
  "setups": [{"id": "db", "cost_ms": 30}],
  "units": [
    {"id": "A", "selectors": ["tests/test_a.py::test_one", "tests/test_a.py::test_two"], "exclusive_cost_ms": 10, "setup_ids": ["db"]},
    {"id": "B", "selectors": ["tests/test_b.py::test_one"], "exclusive_cost_ms": 10, "setup_ids": ["db"]},
    {"id": "C", "selectors": ["tests/test_c.py::test_one"], "exclusive_cost_ms": 30, "setup_ids": []},
    {"id": "D", "selectors": ["tests/test_d.py::test_one"], "exclusive_cost_ms": 30, "setup_ids": []}
  ]
}
```

All fields are required and objects are closed. Selectors must be globally unique.
Costs must be nonnegative integer tokens; booleans, floats, exponents, `-0`, and
aggregate overflow are rejected. Unit/member order is meaningful. Setup registry
and reference order do not affect canonical identity. JSON selectors are inert
opaque strings; the restricted pytest adapter accepts a much narrower grammar.

The caller must ensure reusable setup charges really are additive and exclusive,
workers are homogeneous, and the runner preserves each unit's member order and
consecutiveness. Structural verification cannot prove these assumptions. Read the
[model contract](docs/model.md) before using output to configure CI.

## Optimization and assurance

The portfolio compares exclusive-cost LPT, marginal-load, and setup-affinity seeds,
then tries whole-unit relocations and pair swaps. It never returns a worse modeled
makespan than its independently reconstructed baseline; equal-makespan results
cannot increase total modeled work. It keeps the last complete feasible result if
a budget stops a phase.

`auto` additionally uses bounded exact branch-and-bound when N≤18 and K≤8.
`heuristic` omits exact search; `exact` rejects larger inputs. Exact search proves
only the primary makespan when completed. No globally optimal secondary objective
is claimed. All limits are deterministic operation counts, not CPU-time limits.

The independent verifier reconstructs coverage, order, setup unions, cost arithmetic,
baseline, lower bounds, and protocol consistency without importing optimizer helpers.
A producer `search_complete` label alone is **not an independent certificate**.
`--audit-optimal` enumerates Cartesian assignments for eligible tiny inputs
(N≤10, K≤6, K^N≤1,000,000). `--require-optimal` requires an independently matching
arithmetic bound or completed audit. See [verification](docs/verification.md).

## Boundaries and alternatives

There is no dependency graph, heterogeneous worker model, capacity constraint,
resource-conflict model, dynamic queue, remote API, inventory discovery, credential
handling, timing inference, telemetry, or shell/test execution. Put a complete
ordered dependency sequence inside one unit; cross-unit dependencies are unsupported.

For ordinary duration-based pytest splitting, consider pytest-split. For in-runner
parallelism/grouping/work stealing, consider pytest-xdist. Existing Buildkite or
CircleCI users should first evaluate their integrated timing tools. Knapsack Pro
supports dynamic queues; OR-Tools is better for richer scheduling constraints.
[Prior art and provenance](docs/provenance.md) documents these alternatives and the
closely related Gel/EdgeDB setup-aware approach.

## More

- [CLI and immutable Python API](docs/api.md)
- [Safety, output contract, and resource limits](docs/safety.md)
- [Normative design contract](docs/DESIGN.md)
- [Machine protocol](docs/MACHINE-PROTOCOL.md)
- [Frozen original synthetic benchmark protocol](benchmarks/BENCHMARK-PROTOCOL.md)
- [Development and qualification](docs/development.md)

Plans and exports contain test identifiers and may reveal private project details.
Review them before sharing. ShardCairn never publishes them automatically.
