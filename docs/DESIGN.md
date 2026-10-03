# ShardCairn implementation design

Public editorial adaptation of design-1, 2026-10-03.
Status: implemented contract for v0.1.0.

The original design-1 was a pre-implementation specification with SHA-256
`6295ebff7da064baaaad8a6d8d982f439b1a5a0014922d8baeb7a496de0c960b`.
This public adaptation is not byte-identical: it updates implementation layout,
links, status, and explanatory context while preserving the model, algorithm,
budget, and schema semantics. Its content has its own distinct file hash.

This public specification preserves the implemented model, algorithm, budget, and
protocol semantics. Local qualification and its limits are recorded in
[qualification](qualification/README.md). Implementation does not imply that every
supported platform has passed hosted CI or that a package has been published.
The [machine protocol](MACHINE-PROTOCOL.md) and [distributed schemas](../src/shardcairn/schemas/)
complete this contract; schema comments referring to DESIGN.md refer to this file.

## Decision and purpose

ShardCairn is a small offline Python library and CLI that assigns explicitly described indivisible test units to a fixed number of homogeneous serial CI shards. Its useful distinction is an explicit reusable-setup cost model, deterministic bounded optimization, and an independently checkable allocation artifact. No new scheduling algorithm, approximation ratio, measured CI speedup, or globally optimal secondary objective is claimed.

This design is intended for maintainers who already have a trustworthy inventory and exclusive cost estimates. The planner never discovers tests, imports a project, infers timing semantics, launches a runner, calls a CI API, or reads credentials. It is unsuitable when setup costs cannot be separated faithfully, workers differ, execution order has dependencies outside a unit, or scheduling must adapt while jobs run.

The implementation has three independently testable boundaries: strict manifest parsing, bounded assignment optimization, and a verifier/exporter that cannot call optimization helpers. Alternatives considered were ordinary duration splitting (already well served, insufficient distinction) and a general optimization framework (unnecessarily broad, better served by OR-Tools). Version 1 retains explicit setup modeling and narrow, reviewable behavior.

## Evidence and alternatives

The Gel/EdgeDB engineering account describes expensive database initialization, the need to avoid duplicating it across CI shards, and integrity checking for missing tests. Its custom setup-aware sharder is close prior art. ShardCairn does not present setup-aware sharding as novel. https://www.geldata.com/blog/how-we-sharded-our-test-suite-for-10x-faster-runs-on-github-actions

pytest-split issue 82 describes dependent test methods being divided and asks for class-level grouping. This supports explicit indivisible groups, not support for arbitrary test dependency graphs. https://github.com/jerry-git/pytest-split/issues/82

pytest-xdist already provides module/class grouping, explicit groups, and work stealing. It is usually a better choice for in-runner parallel execution. https://pytest-xdist.readthedocs.io/en/stable/distribution.html

Prefer pytest-split for ordinary duration-based pytest splitting; Buildkite Test Engine or CircleCI's integrated tools when their normal timing workflows fit; Knapsack Pro when dynamic queue behavior is required; and OR-Tools when richer scheduling constraints matter. No assertion is made that these products lack every comparable feature. References: https://github.com/jerry-git/pytest-split ; https://buildkite.com/docs/pipelines/configure/tests/bktec/installing-and-using-the-client ; https://circleci.com/docs/reference/configuration-reference/#parallelism ; https://docs.knapsackpro.com/ruby/queue-mode/ ; https://developers.google.com/optimization/scheduling

The optional pytest export relies on argument files introduced in pytest 8.2. https://docs.pytest.org/en/stable/how-to/usage.html#read-arguments-from-file

Implementation, fixtures, examples, and evaluation workloads are original. [Provenance](provenance.md) cites the related work; no production inventories, timings, or implementations are vendored. No registry reservation or trademark clearance is claimed.

## Mathematical contract

There are N >= 1 units, K shards with 1 <= K <= N, and a registry of zero or more setup IDs. Unit i has nonnegative integer exclusive cost p_i, an ordered nonempty selector array, and a set R_i of required setup IDs. Setup s has nonnegative integer cost c_s. Every selector is globally unique under exact Unicode scalar string equality.

A feasible assignment partitions the units into exactly K nonempty sets. Units remain indivisible. Each shard executes units serially; its modeled load is:

    load(j) = sum(p_i for assigned i) + sum(c_s for s in union(R_i for assigned i))

The primary objective is minimum max_j load(j). Every setup is charged once on every shard on which it is activated. A required setup with zero cost is still an activated setup. A declared setup unused by all units is not charged.

The caller promises that:

- p_i includes all work repeated for that unit and excludes separately modeled setup charges
- Setup costs are additive, exclusive, and nonoverlapping; nested fixtures have been flattened appropriately
- A setup ID denotes actually reusable state across all users assigned to a shard; separate lifetimes require separate IDs
- Startup, cleanup, and finalization costs are included in the applicable exclusive or reusable charge exactly once
- Workers are homogeneous and begin in the same assumed state
- The selected runner preserves each unit's member order and runs those members consecutively

The program can check structural consistency, but cannot establish these promises from a manifest. Timing provenance and actual wall time are outside the optimization input contract. Costs are estimates, not observations made by the product.

Unsupported: arbitrary precedence/dependency graphs, cross-shard synchronization, heterogeneous workers, capacities, resource conflicts, setup overlap, conditional tests, dynamic queues, test collection, timing auto-inference, remote state, and shell execution. Put an entire ordered dependency sequence inside one unit. A shared reusable setup does not itself impose execution order.

## Manifest format and validation

The normative declarative shape is the [manifest schema](../src/shardcairn/schemas/manifest.schema.json), supplemented by the semantic rules here. Every object has a closed set of fields. No version guessing, unknown-field tolerance, defaults for costs, coercion, aliases, or implicit singleton units.

Top-level fields, all required:

- schema_version: integer 1
- timing_basis: literal exclusive-additive-once-per-shard-v1
- shards: integer 1..64
- setups: array of objects with id and cost_ms, possibly empty
- units: nonempty array of objects with id, selectors, exclusive_cost_ms, and setup_ids

IDs are ASCII, 1..64 characters, matching [A-Za-z][A-Za-z0-9_.-]*. Setup IDs and unit IDs have separate namespaces; duplicates within either namespace are errors. Setup declaration order does not affect semantic identity. Unit array order and each selectors array order are meaningful. setup_ids contains no duplicate and must resolve to the registry. Unused declarations are allowed and reported as a count.

Selectors are opaque strings for the JSON interface: 1..4096 Unicode scalar values, without U+0000..001F or U+007F..009F. Reject unpaired surrogates and non-UTF-8 input. Do not normalize case, Unicode, slashes, paths, or whitespace. Other characters, including spaces and option-like text, are permitted only as inert JSON data and are not automatically suitable for pytest export. Selectors are never interpreted as filesystem paths by ShardCairn.

Every numeric model value is a JSON integer token in 0..9,007,199,254,740,991. Reject booleans, fractional syntax (including 1.0), exponents (including 1e0), strings, null, NaN, Infinity, negative costs, and negative-zero integer tokens. The JSON schema alone cannot enforce token syntax or Python's bool/int distinction; the parser must. Duplicate object keys are rejected at every depth before constructing the semantic object.

Before allocating incidence matrices or assignment structures, establish all counts and this safe aggregate bound using checked addition:

    standalone_sum = sum_i(p_i + sum_{s in R_i} c_s) <= 9,007,199,254,740,991

Every feasible total load is at most standalone_sum. Also validate each declared cost against the scalar limit even when unused. Use exact integer arithmetic throughout, including ceiling division. No float conversion is permitted in scoring, gaps, percentages, serialization, or equality decisions.

Hard input caps: 16 MiB UTF-8 manifest, 50,000 selectors, 10,000 units, 2,048 setup declarations, 64 shards, 64 setup references per unit, 64-character IDs, and 4096-scalar selectors. Reject K>N. Byte cap is checked while reading, not after an unbounded read. A lexical preflight rejects nesting depth above 16 and more than 2,000,000 JSON tokens before recursive decoding. String escaping is respected by this preflight; the standard JSON decoder remains responsible for grammar. Numeric callbacks reject tokens before large integer allocation. Errors use bounded JSON pointers, never echo a complete selector or source line, and total stderr is capped at 4096 UTF-8 bytes.

Plans and exports may contain private test identifiers, so documentation must warn users to review them before sharing; there is no automatic publication. No files are opened based on manifest content. Only explicitly named local input files and the explicitly named output directory are accessed. No glob expansion, default config discovery, home directory inspection, environment scraping, or network access.

## Canonical identity and ordering

Canonical JSON bytes use UTF-8, sorted ASCII object keys, no insignificant spaces, ensure_ascii=true escaping, and exactly one final LF. Integer spelling is base 10 without leading zeros. There are no floats. Escaping all non-ASCII scalar characters keeps serialized byte comparison portable without changing string values.

Before hashing, normalize the validated manifest as follows: setup registry sorted by setup ID, each unit's setup_ids sorted by setup ID, unit array order and selectors order preserved. The manifest fingerprint is SHA-256 of these canonical bytes. Raw whitespace and JSON key order therefore do not affect identity. Unit reorder, selector reorder, cost changes, shard count, IDs, or timing basis changes do. Hash scope and normalization have a fixed identifier, shardcairn-manifest-c14n-v1.

A returned assignment is normalized by sorting shards by their smallest original unit index, then numbering them 0..K-1. The canonical assignment vector contains one normalized shard index per unit, in original manifest unit order. Units inside a shard are emitted in original manifest order; selectors are the exact concatenation of their units in that order. This is a deterministic presentation rule, not a promise to preserve order across shards. Every unit remains consecutive and internally ordered.

Plan bytes include no time stamps, hostname, absolute paths, nondeterministic timings, random seeds, or environment details. Identical manifest, options, and solver version must produce identical bytes on supported platforms. Runtime version and benchmark timing can appear only in separate qualification evidence.

## Baseline and deterministic heuristic portfolio

The required baseline is exclusive-cost LPT, independently verified under the complete setup-aware model. Sort units by descending p_i, then original index. Assign the first K units to distinct shards 0..K-1. Assign each remaining unit to the shard with minimum exclusive work, tie by shard index. A min-heap is sufficient. This special initial fill guarantees nonempty shards even when costs are zero. The placement metric deliberately ignores setups, but its reported load includes them.

Construct this complete baseline before optional optimization. It cannot be invalidated by optimization budgets. A plan never returns a worse makespan than its independently reconstructed baseline. Also retain the baseline on an equal makespan if it has smaller total modeled work.

Additional seeds use deterministic online placement and preserve feasibility at every step: disallow any placement leaving more empty shards than remaining unplaced units.

1. Marginal setup seed. Order by descending stand-alone cost p_i+sum(R_i c), tie by original index. Choose the admissible shard minimizing (prospective global maximum, prospective chosen-shard load, newly activated setup cost, shard index).
2. Setup affinity seed. For each used setup calculate weight c_s*(number of requiring units-1). Give a unit its highest-weight setup as anchor, tie by descending setup cost then setup ID. Units without setups have a separate final anchor group. Order anchor groups by descending weight, descending setup cost, then setup ID; units within each group by descending stand-alone cost then original index. Choose admissible shard minimizing (new setup cost, prospective chosen-shard load, shard index). This intentionally favors reuse and can overconcentrate work; it is only a competing seed, never a claimed guarantee.

Compare complete seeds by (makespan, total modeled work, canonical assignment vector). A partial seed is never an incumbent. If a budget interrupts a seed, discard it and retain the best earlier complete verified candidate. The LPT baseline remains available.

Local improvement begins from the best completed seed. Maintain unit membership, exclusive loads, setup reference counts, and setup costs. A relocation moves one whole unit; a swap exchanges one whole unit from each of two different shards. Disallow relocations from singleton shards. For removals, charge removal of a setup only when its last referencing unit leaves; for additions, charge only first activation. Recompute affected loads exactly.

Enumerate relocations by original unit index then target shard index, followed by every unordered pair of units by increasing (first original index, second original index), charging consideration before rejecting same-shard pairs. Accept the first strict improvement in (makespan, total modeled work), normalize shard labels, then restart enumeration. Do not accept equal-objective rearrangements. A complete scan with no improvement is a local fixed point for these neighborhoods only. Interrupted scans never claim fixed-point status. Evaluate candidates lazily; never materialize an N-squared list. Cache only bounded per-shard and per-unit data.

At complete seed and phase boundaries and before output, the separate verifier reevaluates the candidate; this requires at most seven full independent passes (three seeds, local result, exact result, final result, and a final input/artifact check). Full verification is not repeated after every local move. Delta invariants are checked by exhaustive independent test rescoring. A verification mismatch is an internal error; do not quietly conceal it with a baseline fallback. Candidate mutation is transactional: if a budget is denied during scoring, copying, or normalization, restore the prior complete incumbent before returning. Maintain prevalidated undo records bounded by touched unit/setup entries; rollback and cleanup alone are uncharged and may run after exhaustion. Rollback cannot score candidates, improve the incumbent, expand a search node, allocate input-dependent new structures, or certify completion. Local rollback touches at most two units and their 128 reference entries; exact unwind touches at most 18 frames of 64 entries each. Exact search similarly unwinds every entered mutation on interruption. No partial candidate is committed. No local optimum implies a global optimum. Changing solver tie rules requires an algorithm version change.

## Exact search and proof boundaries

Exact search is optional, limited to N<=18 and K<=8. auto runs it only inside those limits after heuristic search, unless arithmetic bounds already meet. heuristic never runs it. exact rejects oversize input instead of silently downgrading. Node and primitive-work budgets apply in all cases.

Unit order is descending stand-alone cost then original index. Use depth-first branch-and-bound over a prefix of this order, with a complete verified incumbent. Branch over occupied shard labels ascending, followed by only the first empty label. This restricted-growth construction removes pure shard-label permutations and preserves a representative of every feasible unlabeled partition. Enforce nonempty final shards, and reject a prefix if remaining units are fewer than empty shards.

Additional interchangeable-shard pruning may retain only the lowest-label shard with each exactly equal (exclusive_load, setup-ID union, occupied_boolean) state. Equal total load alone is unsafe; equal setup cost without equal IDs is unsafe; an empty shard differs from an occupied zero-load shard. Do not add stronger symmetry rules without a separate proof and differential tests.

Pruning for strict makespan improvement is permitted only when one of the following holds:

- The nonempty completion condition fails
- A current shard load is >= incumbent makespan
- The safe prefix lower bound below is >= incumbent makespan

Costs are nonnegative, so partial loads cannot decrease. At a feasible leaf, replace the incumbent only if makespan strictly improves. Preserve the incumbent on equality. Exact completion proves primary makespan only; equality pruning can discard better secondary scores and lexicographic assignments.

A node is counted once upon entry, including root, internal nodes, and complete leaves, before pruning/terminal checks. Symmetry-skipped branches are not nodes. Check the node cap before entry. Reaching the cap numerically is not itself interruption: interrupted=true only if a required subsequent node entry is denied. If all work finishes exactly on the cap, completed=true is valid. Primitive-work interruption similarly cannot claim search completion. Zero caps are allowed and permit no corresponding charged operation; the baseline remains available. A positive node cap can still permit root entry before a zero primitive budget denies its first bound evaluation.

The exact search is an algorithmic claim, not a portable independent certificate. No pruning log or purported proof object is shipped in v1. A forged search_complete label does not establish optimality to the independent verifier.

## Genuine lower bounds

Let P be sum_i p_i, U the union of all required setups, and C=sum_{s in U} c_s. The public arithmetic lower bound is the maximum of:

- max_i(p_i+sum_{s in R_i}c_s): the unit and all its required setups must fit together
- ceil((P+C)/K): all exclusive work and each globally used setup must be paid at least once

The maximum of these bounds is a genuine global lower bound; report both components. Ignore unused registry setups. Report upper_bound_ms as the verified assignment makespan, absolute_gap_ms=upper-lower, and a dimensionless exact rational gap with numerator=upper-lower and denominator=upper. Define the zero-upper case as 0/1. Do not display this as a statistical confidence interval or a wall-time prediction.

At a partial exact node, current_total includes all irrevocable assigned exclusive work and setup activations. Let P_remaining be the remaining exclusive work, and F the setup IDs required by remaining units but active on no current shard. A safe conditional prefix bound is:

    max(global_lower_bound, current_max,
        ceil((current_total + P_remaining + sum_{s in F}c_s)/K))

The future setup term counts only setups definitely requiring at least one new activation, so it may be weak but cannot overstate unavoidable work. This conditional bound must never replace the reported global lower bound from a selected prefix. Only the two public global components are reported in v1.

A regression case against unsafe equal-load symmetry is: K=2, setup x costs 5, units (5,none), (0,x), (0,x). After splitting the first two, both loads equal 5, but only the x-bearing shard can accept the final unit without increasing the maximum.

## Plan protocol

The complete closed structural schema is the [plan schema](../src/shardcairn/schemas/plan.schema.json). The [machine protocol](MACHINE-PROTOCOL.md) and [other schemas](../src/shardcairn/schemas/) fix every machine-readable output shape and relational status rule. Additional relational constraints here are mandatory; schema validation alone is insufficient. Costs use the same safe integer range as the manifest.

Required top-level fields:

- plan_version=1; model_version=exclusive-additive-once-per-shard-v1
- manifest_hash with algorithm=sha256, normalization=shardcairn-manifest-c14n-v1, and 64 lowercase hexadecimal digest
- solver: fixed algorithm_version, requested mode, winning initial seed, final incumbent source, exact state
- work: configured limits, used counters, denied-budget categories, and local state
- baseline: baseline algorithm version, normalized shard unit-ID arrays, per-shard load summaries, and aggregate metrics
- assignment: normalized chosen shard records, including ordered unit IDs, exact concatenated selectors, sorted activated setup IDs, exclusive cost, setup cost, and load
- metrics: exclusive total, setup total, minimum unavoidable setup total, duplicated setup cost, activated setup occurrence count, makespan, and total modeled work
- bounds: both analytic components, lower bound, upper bound, absolute gap, and exact rational gap
- claim: feasible, bound_tight, or search_complete; primary_objective is makespan; secondary_optimal is always false

Every shard record has its contiguous index. Baseline records omit selector arrays and setup lists to avoid doubling large payloads; the verifier reconstructs those from unit IDs. Baseline per-shard arithmetic is nevertheless checked. Chosen assignment includes the ordered selector list and setup references for transparent export and review.

Definitions: setup_total_ms sums each active setup charge on each shard. minimum_setup_ms is sum of costs of globally used setups once. duplicated_setup_ms=setup_total_ms-minimum_setup_ms. activated_setup_occurrences is the count of (shard, setup-ID) activations, including zero-cost activations. These are different measures and must have distinct labels. total_work_ms=exclusive_total_ms+setup_total_ms=sum shard loads.

Optional phase order is baseline, marginal seed, affinity seed, local search, then exact search. Before each remaining seed or local phase, skip that phase if the current verified incumbent meets the arithmetic bound; skipped seeds are not_started and skipped local is not_started. At the exact stage decide state in order: heuristic mode not_requested; auto outside eligibility skipped_size; otherwise a tight bound skipped_bound_tight; otherwise attempt exact search. Forced exact oversize is rejected before optimization. Claim precedence: bound_tight if independently recomputed global lower bound equals verified upper; otherwise search_complete only if exact state is completed; otherwise feasible. Budget exhaustion is orthogonal and recorded by phase; it is never evidence for an optimality claim. An interrupted exact search remains incomplete even if separate arithmetic establishes bound_tight. There is no single ambiguous status named optimal.

exact.state enum: not_requested, skipped_size, skipped_bound_tight, completed, budget_exhausted. local.state enum: not_started, fixed_point, budget_exhausted. The plan's metadata describes what the producer says it did; most history counters cannot be proved by arithmetic validation. Report this distinction explicitly.

## Independent verification

verify accepts the original manifest and a plan. It reads both through strict byte, integer, duplicate-key, depth, and shape limits. It recomputes the manifest hash, checks supported versions, requires K normalized nonempty shards, exact unit coverage once, exact selector coverage once, original within-unit order and consecutive grouping, known IDs, all declared arithmetic, setup unions, baseline assignment, and both global lower-bound components. It also checks every relational status invariant and that chosen makespan does not exceed the reconstructed baseline. For equal makespan, chosen total work must not exceed the baseline total.

The verifier must not import or call scoring, delta, seed, local search, exact search, or pruning helpers. It may share only strict JSON reading, model constants, immutable parsed records, and canonical byte/hash helpers. Its cost calculation uses direct unit iteration and Python set unions. Its baseline reconstruction is separately implemented from the optimizer's baseline constructor and checked by independent hand cases. Add an import-boundary test so future refactors cannot collapse this independence.

Default verification reports feasibility and modeled arithmetic as verified, and optimality as:

- bound_proved when its own genuine global lower bound equals upper
- not_certified when arithmetic passes but bounds differ, including any producer search_complete claim

A false bound_tight claim is invalid. A structurally consistent search_complete claim without a matching bound is permitted as producer metadata but is explicitly not independently certified. Consistency of counters and labels does not authenticate historical execution.

Optional --audit-optimal performs a separate Cartesian assignment enumeration, no pruning, no symmetry, direct set-union scoring, filtering nonempty assignments. Enumerate label tuples lexicographically over original manifest unit order, with each label in 0..K-1. Count every visited tuple, including those rejected for empty shards, before checking it. Eligibility: N<=10, K<=6, and K^N<=1,000,000 using bounded multiplication. After mandatory input validation, check explicitly requested audit eligibility before considering a tight-bound skip; an oversize requested audit exits 2 even when arithmetic could prove the bound. Failed mandatory validation records audit not_run when the audit was requested, with zero visits, configured limit, and no witness. Its separate assignment-visit cap includes infeasible tuples. A completed enumeration proves optimum if its minimum equals the plan. On finding a better feasible witness, stop immediately: for a producer claim feasible, retain arithmetic validity and report optimality=not_optimal (exit 0 normally or 6 with --require-optimal); for a producer claim search_complete or bound_tight, report contradicted and exit 3. Include the canonical witness assignment vector and its independently calculated makespan. Exhausting the audit visit budget reports optimality=unknown and does not certify optimality; valid coverage/arithmetic remains valid. An audit finishing exactly on its final permitted tuple is complete; a denied next tuple alone signals exhaustion. If arithmetic already proves the bound tight, an explicitly requested audit is skipped with state=not_needed. The audit does not import optimizer modules. No automatic installation of external solvers.

--require-optimal succeeds only for an independent arithmetic or completed Cartesian audit proof. It cannot treat a producer label as evidence. Without this flag a valid heuristic plan verifies successfully; optimality is not_certified when no independent proof or refutation was obtained. The verifier does not certify supplied measurements, runner semantics, or actual elapsed time.

## CLI and output safety

Commands:

    shardcairn plan MANIFEST --out-dir DIR [--mode auto|heuristic|exact]
        [--work-limit INT] [--local-candidates INT] [--exact-nodes INT]

    shardcairn verify MANIFEST PLAN [--audit-optimal] [--audit-visits INT]
        [--require-optimal]
    shardcairn export MANIFEST PLAN --out-dir DIR [--format json|pytest-argfile]

plan creates only plan.json, report.txt, and complete.json under a previously nonexistent output directory. export creates only shard-000.json through shard-(K-1).json for JSON; or shard-000.args through the corresponding fixed numeric suffix for pytest; plus export.json and complete.json. Width is three digits. No selector or ID influences a filename. Export first verifies the input plan completely. report.txt is human-readable, UTF-8, at most 64 KiB, with counts plus the first 20 shard summaries and a clear truncation note. No untrusted terminal control sequences are emitted.

A preexisting target directory, symlink target, or existing output file is an error. Validate and size-check all input and output content before directory creation. Create the target directory exclusively and every output file exclusively; write complete.json last. Consumers require that completion marker and its SHA-256/byte-size list before treating a directory as complete. Files use LF, no BOM. If writing fails, best-effort remove only files created by this invocation and its newly created empty directory. Never remove an existing directory. A crash can leave an incomplete directory, which is reported and must not be reused automatically. Concurrent hostile replacement of parent directory components is outside the portable local CLI threat model; document that the destination must be in a trusted local directory. Reject symlink final targets and unexpected entries encountered during writing.

verify emits one canonical JSON result on stdout and bounded human diagnostics on stderr. It does not create a report directory. stdout of plan/export is one bounded JSON summary with status and fixed relative filenames; detailed data is in their artifacts. No ANSI color in v1.

Exit codes:

- 0: requested artifact was produced or input plan passed its requested verification level; ordinary success does not imply optimality
- 2: CLI syntax or incompatible options, including forced exact/audit size outside supported eligibility
- 3: malformed/invalid manifest or plan, unknown reference, numerical violation, inconsistent claim, or contradictory optimum witness
- 4: I/O error, unsafe or preexisting output destination
- 5: hard resource limit prevents a verified result, including input/output size limits
- 6: verify --require-optimal could not be satisfied; this does not invalidate otherwise verified coverage and arithmetic
- 70: internal invariant failure; no completion marker or successful artifact claim

Optimization budget exhaustion after a valid baseline gives a feasible result with exit 0. Only verify supports --require-optimal; use verify --audit-optimal --require-optimal for an eligible independent enumeration. Exact or audit interruption is visible in the result and never becomes completed. A failed optional seed cannot erase the baseline. A parser or verifier resource failure is unknown, not valid and not optimal.

## Restricted pytest export

The JSON exporter preserves opaque selectors. The pytest argument-file exporter is explicitly narrower and rejects the whole export if any selector falls outside this grammar:

    relative_path.py::test_name
    relative_path.py::ClassName::test_name

relative_path is one or more slash-separated ASCII components; each starts with [A-Za-z_], continues with [A-Za-z0-9_.-]*, and is not '.' or '..'; the final component ends in '.py'. ClassName and test_name match [A-Za-z_][A-Za-z0-9_]*. No parametrized bracket suffixes in v1. No file-only selector, absolute path, Windows drive prefix, backslash, '@', leading '-', whitespace, colon except the exact '::' separators, control characters, Unicode, quotes, wildcard, or shell syntax. Restriction is intentional; unsupported node IDs still work through JSON with a separately trusted adapter. There is no escaping mode.

The grammar is a syntactic restriction, not test discovery. A two-segment string can name a class in an actual repository even though it has the accepted shape; the exporter cannot detect that without importing or collecting tests. The caller must supply selectors that identify the intended individual tests, rather than class-only targets.

Emit exactly one syntactically validated selector plus LF per line. Export does not resolve, open, collect, or execute those paths. The docs show a user-run invocation of pytest>=8.2 with @shard-000.args; the product does not invoke it or generate a shell script. The user chooses repository root and isolated process environment. Ordering can be changed by plugins or runner configuration, which are outside the planner's guarantee.

Shipped integration fixture: one repository-owned module with tests representing units A (two ordered methods), B (one test), C, D, and an original session-scoped reusable fixture x used by A/B. Include explicit manifest selectors, no collection-based inventory generation. A development-only test launches one isolated pytest process for each exported shard, with owned configuration that disables unrelated plugin auto-loading and logs test start/order and x activation/teardown to a process-local file. Aggregate logs to prove exact intended coverage, unit consecutiveness/order, no cross-shard duplication, and observed activation counts equal the exported assignment's modeled activation counts. This validates the adapter and fixture contract, not the millisecond estimates. The product itself never receives permission to execute arbitrary user tests.

## Worked example

K=2; setup db costs 30 ms. Units A and B each have p=10 ms and require db; C and D each have p=30 ms and require no setup. A contains two distinct selectors in a fixed order. These tiny numbers illustrate arithmetic, not measured durations.

Exclusive LPT orders C,D,A,B and allocates C+A and D+B. After output normalization the loads are 70 and 70 ms, total 140, setup total 60, duplicated setup cost 30.

A setup-aware assignment A+B and C+D has loads 50 and 60 ms, total 110, setup total 30, duplicated setup cost 0. The global arithmetic lower bound is max(40,ceil(110/2))=55 ms; its gap is 5 ms, or 5/60 as the exact rational. Direct exhaustive enumeration proves makespan 60 is optimal. Thus exact completion can be true while the elementary lower bound remains loose. The default verifier certifies arithmetic, not this 60 ms optimum, unless it independently enumerates the tiny case.

This example is not evidence of a production speedup. Preserve cases where setup-aware heuristics do no better or miss the optimum.

## Deterministic work and memory bounds

There are separate optimization controls with fixed, versioned defaults:

- primitive work: default 5,000,000, hard maximum 50,000,000
- local candidate evaluations: default 100,000, hard maximum 2,000,000
- exact nodes: default 250,000, hard maximum 2,000,000
- independent audit assignment visits: default 1,000,000, hard maximum 1,000,000

A primitive optimization tick is charged before each setup-reference examination, shard-load examination, candidate placement/move/swap consideration, exact shard-state comparison, exact-node bound evaluation, or assignment-vector element examined during tie comparison/canonicalization. Count local candidate consideration before admissibility filtering, including same-shard swaps and disallowed singleton moves, so rejected candidates cannot hide an N-squared unbudgeted scan. local_candidates_started counts these considerations, including an interrupted consideration. Check both relevant caps before beginning a consideration; a denied start increments neither counter. Individual primitive ticks are counted only when permitted; denied work is not included in used counters. A complete neighborhood scan ending exactly at its cap is complete, and only a denied needed next consideration makes it exhausted. Any loop doing input-dependent optimization work must use these tick categories or a documented bounded preprocessing operation. Seed building, local search, and exact search share the primitive budget in that order. The only exempt preprocessing is strict parsing, canonical hashing, validated ID lookup/index creation, standalone cost calculation, setup incidence/degree/anchor calculation, fixed unit-order sorting, and mandatory baseline construction. These are bounded O(bytes + references + N log N + S log S) passes. Independent verification at the documented bounded phase boundaries is also exempt. All remaining input-dependent optimization iterations consume defined ticks. Setup unions used in exact-state keys may be bounded-width integer bitsets of at most 2,048 bits; each key comparison costs one tick, and no variable-sized unmetered combinatorial construction is allowed. Their operation/count summaries are separately recorded in qualification logs, not misrepresented as zero work. Do not claim the tick cap is a CPU-time limit.

Setup incidence storage is O(total references), not a unit-by-setup dense matrix. Per-shard setup counters are bounded by K*S<=131,072. Exact search mutates/reverts a depth<=18 state instead of retaining the entire search tree. Local candidates are generated lazily. Check dimensions before allocations; no N*K*S or N^2 structure is allowed.

Plan input/output cap is 64 MiB. Total export bytes, including export.json and complete.json, are capped at 64 MiB; report cap is 64 KiB; completion marker cap is 64 KiB; any command stdout record is capped at 16 KiB. Compute conservative output-size bounds before serialization and enforce actual byte limits while serializing. Bounds account for escaping expansion, unit IDs, selector duplication inside one chosen assignment, per-shard active setup IDs, baseline records, and fixed metadata. Refuse a too-large artifact explicitly; never truncate plan or selector data. Parse plan with the same depth limit and a 2,000,000-token cap, then check semantic counts before derived allocation. A malformed plan is not allowed to multiply the permitted selector count by repeating complete lists across shards.

Resource qualification measures actual CPU time, peak RSS, serialized bytes, and tick/candidate/node counts on defined fixtures. The local resource acceptance gate is: the maximal legal baseline/verify/export case completes within 60 seconds each and below 512 MiB peak RSS on the recorded Linux release machine; no claim of universal machine performance follows. Optional optimization must stop at its exact deterministic budgets. If this gate fails, optimize bounded data handling or lower documented hard limits before v1; do not waive the gate or publish unmeasured capacity. Hosted CI uses smaller stress cases and explicit timeouts; the local maximal case and environment are archived as release evidence.

## Library API and modules

Python 3.11 through 3.14, MIT, standard library only at runtime. Public API uses immutable dataclasses/tuples/frozensets and explicit options; no hidden module-global budgets. Public functions: load_manifest(path_or_bytes), plan(manifest, options), verify(manifest, plan_document, options), export(manifest, plan_document, destination, *, format), canonical_manifest_bytes(manifest). See [API documentation](api.md) for types, defaults, and examples. Return typed result records with separate feasibility, evidence, and resource statuses. Domain exceptions carry stable short codes and bounded pointers. Public APIs apply the same limits and cannot bypass checks by manually constructing records.

Modules: parsing.py (strict bytes/JSON), manifest.py (validated immutable model), canonical.py, baseline.py, optimization.py (seed, local, and exact search), budgets.py, planner.py, verifier.py, audit.py, exporter.py, cli.py, and version.py. verifier/audit cannot depend on baseline/optimization/planner/budgets. The dependency rule is enforced in tests. Product imports have no filesystem, subprocess, network, or environment discovery side effects.

Package data includes all seven JSON schemas. Documentation includes README, model contract, CLI/API, verification and assurance semantics, limitations, prior art/provenance, and the frozen evaluation protocol. Include MIT license, complete wheel and sdist metadata, __main__ entrypoint, typed API, and CI for supported Python minors and Linux/macOS/Windows. Release artifacts have no private paths, names, task history, credentials, generated environment inventories, or production datasets.

## Frozen original evaluation set

Freeze the workload generator specification, generated manifests, IDs, and SHA-256 index before tuning heuristics. Benchmark generation and oracle scripts are development assets only, not product functionality. Record the generator's explicit algorithm version; never silently regenerate a different workload under an existing ID. All cases are synthetic and original.

Fixed families:

1. No setups: equal work, highly skewed work, zero work, K=1, K=N
2. One common setup: cheap, dominant, zero-cost, and users with zero exclusive work
3. Disjoint affinities: balanced and imbalanced groups; more/fewer groups than shards
4. Overlapping setup sets: chains, hubs, cliques of small unit groups, and anchor conflicts
5. Mixed grouped units: varied selector counts with identical costs, ordered-member coverage
6. Known counterexamples: A/B/C/D and unsafe load-only symmetry; retain heuristic misses discovered during pre-freeze probing
7. Boundary cases: maximum counts, dense allowed references, huge safe integer totals, one-past-cap inputs
8. Reproducibility cases: reordered JSON keys, setup registry/references reordered, alternate Unicode encodings, canonical byte checks

For tiny cases use the independent Cartesian oracle. The [benchmark protocol](../benchmarks/BENCHMARK-PROTOCOL.md) specifies seed list [0,1,2,3,5,8,13,21,34,55], a portable LCG, exact generation rules for 200 tiny instances within the one-million Cartesian assignment bound, and 100 medium instances with N=32..256, K=2..16. Add explicit no-improvement cases and report them; do not filter the portfolio by positive outcome. Hold at least one fixed overlapping-setup family out of heuristic tuning. Freeze family membership before implementation performance tuning.

Report modeled baseline and returned makespan, total and duplicated setup work, analytic gap, exact/oracle result only where completed, budget consumption, and no-improvement/miss counts. Include all instances, not just averages or successful cases. No external CI speed claim is permitted from this dataset. A release benchmark is an inspectable evaluation of this model, not a production guarantee.

## Test and release gates

1. Strict parsing: every required/unknown field, duplicate JSON key, duplicate ID/member/reference, unknown setup, invalid UTF-8/surrogate/control, boolean/fraction/exponent/negative/overflow, caps and cap+1, empty units, empty selectors, and K>N. Source files unchanged.
2. Model arithmetic: zero costs, unused setups, shared setups, one activation per shard, final reference removal, overlapping requirements, all cost boundaries, aggregate overflow, ceiling division, and gap zero semantics.
3. Baseline: exact LPT tie order, mandatory nonempty initialization, hand-checked assignments, independent reconstruction, and chosen-result never worse.
4. Local deltas: every relocation and pair swap on exhaustive small feasible partitions checked against separate full set-union rescoring; singleton relocation refused; interrupted scans not fixed points.
5. Exact differential: independent tiny oracle over thousands of fixed/random cases, all allowed K, nonempty and zero cases, symmetry identities, bound validity on partial prefixes, cap exactly-on-completion, cap-one-before, zero budget, and no infeasible incumbent.
6. Verifier mutations: omitted/duplicated/unknown units and selectors; split/reordered/interleaved group; altered setup set/load/total/gap/baseline/hash; false bound_tight; unsupported versions/fields; forged search_complete remains uncertified; budget labels mutually inconsistent; oversized plan gives no successful certificate.
7. Metamorphic: cost scaling by positive integers within cap, setup-ID renaming, zero-cost setup insertion, JSON reformatting, setup declaration/ref reordering, and consistent recomputation of all reported metrics. Positive scaling must scale each fixed assignment load and the independently established optimum exactly. Do not require the arithmetic ceiling bound, search trace, or final assignment under a fixed budget to scale identically: ceiling rounding can change bound-tight skips and pruning. Zero scaling is tested for validity and nonempty coverage only.
8. Export safety: whole-export rejection for each unsupported pytest grammar form; exact JSON byte/string preservation; no selector-derived paths; preexisting directory/file/symlink refusal; crash/incomplete marker; output cap; source immutability; no partial export advertised complete.
9. Real owned pytest integration: isolated shard processes, exact coverage/order, observed session setup activations, restricted argfile invocation on pytest>=8.2, and explicit plugin configuration. No timing speed assertion.
10. Reproducibility: byte-identical canonical manifests/plans/exports across supported Python and OS jobs with identical version/options, fixed count budgets, Unicode and integer boundary fixtures.
11. Packaging: source tests, fresh offline wheel install, extracted-sdist build/install using locally available build tools, CLI smoke tests from an unrelated cwd, schema presence, MIT metadata, no dependency downloads during qualification, no import side effects, and no source-tree mutation. Installing development or build dependencies is a separate setup step; qualification records distinguish installed tooling from product runtime requirements.
12. Resource gates: boundary and malicious nesting/token inputs, worst dense references, maximal selectors, N-squared candidate avoidance, exact exponential exhaustion, bounded stderr/report, actual memory/time measurements, and post-interruption feasibility verification.
13. Independent review: optimization bounds/pruning/nonempty/ties reviewed before build; implementation reviewed independently afterward; verifier independence and export/publication safety receive separate review. Fix critical/important findings and rerun affected plus full checks.

An optional development-only OR-Tools CP-SAT audit can provide supplementary evidence. Assignment x_ij and setup activation y_sj must enforce each unit once, each shard nonempty, and exact activation equivalence, with load constraints. Treat only OPTIMAL status as an objective oracle. Its output is supplementary, never a runtime dependency or replacement for the independent tiny oracle.

## Release acceptance

This specification describes the contract, not proof that every release gate has
passed. The [qualification record](qualification/README.md) identifies executed
checks and remaining gates. Reviews and finite tests are evidence, not formal
proofs, authentication of solver history, or validation of supplied timings.

A usable first release must deliver the complete setup-aware model, independent verifier, deterministic heuristic portfolio, bounded exact mode, safe exports, real owned pytest integration, frozen complete evaluation set, cross-platform CI definition, documentation, and installable audited artifacts. Ordinary LPT plus formatting would not meet the purpose. Release qualification requires passing tests and resource gates; public release completion additionally requires publication and successful hosted CI for the exact published commit. These stages have different evidence and must be reported separately.
