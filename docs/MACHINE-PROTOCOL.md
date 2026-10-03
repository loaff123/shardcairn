# ShardCairn machine protocol

All objects are closed and versioned. [distributed schemas](../src/shardcairn/schemas/) specify structural shapes; this document and [DESIGN.md](DESIGN.md) add mandatory relations. Every JSON file is serialized with the canonical byte rules in DESIGN.md. A JSON Schema implementation is not required at runtime; hand-written validation must implement the stricter contract.

## Plan relations

The solver seeds array has exactly three entries in the order lpt, marginal, affinity. lpt is always completed. initial_seed identifies a completed seed. incumbent_source is seed, local, or exact. Local and exact sources require a completed feasible result from that phase, though the phase can subsequently exhaust its budget. Exact source is permitted with exact state budget_exhausted: a better feasible leaf may have been found before the denied node.

work counters never exceed their configured limits. denied_budgets is sorted in the fixed order primitive_work, local_candidates, exact_nodes with each present at most once. It records an actually denied operation, not merely equality between a used counter and its limit. A denied exact-node entry requires exact.state=budget_exhausted. local.state=budget_exhausted requires denial of primitive work or local candidates. exact.state=completed cannot coexist with a primitive/exact denial during that phase; prior local candidate denial alone does not prevent exact completion. Because one global denied list cannot identify phase, every denial also appears in budget_events, an ordered array of closed objects {phase, budget}; phase is marginal_seed, affinity_seed, local, or exact. Repeated identical phase/budget events are prohibited. The global list is the deduplicated fixed-order projection of budget_events. A phase stops at its first denied budget, so it has at most one event. At a local consideration start, check local-candidate availability first, then primitive availability. If both are permitted, increment the local count and the primitive consideration tick together; otherwise increment neither. At an exact node entry, check node availability first; if permitted, increment the node counter before terminal/pruning work. Entry itself is not a primitive tick; the next bound evaluation or other primitive operation is charged separately and can be denied after entry. Denial precedence is therefore local_candidates before primitive_work for a local start, and exact_nodes before primitive_work for a node whose entry is denied. Intermediate primitive denial remains primitive_work. An entered node may remain incomplete if its first or later primitive operation is denied. No synthetic events are added for phases skipped after a prior global primitive denial.

The seeds after a primitive-denied seed are not_started, as is local. For the exact stage, apply the documented mode, size, and tight-bound skip rules first even after prior primitive exhaustion. If exact work is still required, apply normal root-entry precedence: a zero node cap denies root entry with an exact/exact_nodes event and zero entered nodes; a positive node cap enters the root, then an exhausted primitive budget denies its first bound evaluation with an exact/primitive_work event and one entered node. In either denied case exact.state=budget_exhausted. local not_started denotes a phase skipped rather than attempted; local budget_exhausted denotes attempted optional work that was denied. A local phase skipped because the incumbent has a matching arithmetic bound is not_started. Exact phases skipped for such a bound are skipped_bound_tight, never completed.

Mode/state compatibility:

- heuristic: exact.state=not_requested; exact_nodes_entered=0
- auto above N=18 or K=8: exact.state=skipped_size; exact_nodes_entered=0
- auto within limits or exact: exact.state is skipped_bound_tight, completed, or budget_exhausted
- exact outside limits: reject command before producing output

Claim precedence is bound_tight when the independently recomputed global arithmetic bound meets the verified chosen makespan, otherwise search_complete if exact.state=completed, otherwise feasible. secondary_optimal is always false. Equal makespan chosen total work cannot exceed baseline total work. A strict makespan improvement can increase total work or duplicated setups.

Shard records are indexed 0..K-1, sorted by smallest original unit index. Unit IDs are in increasing original index order; each occurs exactly once. Chosen selectors equal exact concatenations, and setup_ids are the exact sorted union. Baseline assignment is reconstructed independently from the manifest and its fixed algorithm. Scalars and metrics are then recomputed independently. The bounds upper equals chosen makespan; the absolute gap equals upper-lower; gap numerator equals gap and denominator equals upper unless upper=0, where the pair must be 0/1. Fractions are deliberately unreduced so there is only one permitted representation.

## Completion marker

complete.json conforms to schemas/completion.schema.json. Fields are completion_version=1, kind (plan or export), manifest_sha256, plan_sha256, and files. Each file record has name, size_bytes, and sha256. File records are lexicographically sorted by fixed relative filename, have no duplicates, and exclude complete.json itself. SHA-256 covers the exact complete raw bytes of that file, including final LF. A zero-length expected artifact is invalid.

For plan, the exact file list is plan.json and report.txt. For export, it is export.json and exactly K contiguous shard-NNN.json files or shard-NNN.args files, never mixed. Digests are lowercase 64-character hexadecimal. manifest_sha256 is the normalized-manifest hash. plan_sha256 is SHA-256 of canonical validated plan JSON bytes (the same as generated plan.json bytes). The completion marker must match its index/plan counts and format. Extra files invalidate the directory-level completion contract. Marker content itself is not a security signature.

Consumers accepting a whole output directory must require the marker, exact file set, byte counts, and hashes before considering it complete. The commands verify MANIFEST PLAN and export MANIFEST PLAN intentionally accept individually supplied plan files, including copies outside their original directory: they validate the plan itself and do not read or trust sibling markers or files. This avoids implicit filesystem reads and allows independent artifact transfer. A marker never substitutes for manifest/plan verification.

## JSON shard arrays and export index

Each shard-NNN.json is a top-level JSON array of nonempty selector strings. It contains exactly the selectors in assignment shard NNN, in the same order, with no wrapper object. Global count and all string rules remain enforced. The schema is schemas/shard-selectors.schema.json. The restricted pytest variant is a text file specified in DESIGN.md.

export.json conforms to schemas/export.schema.json and contains export_version=1, format (json or pytest-argfile), manifest_sha256, plan_sha256, and shards. Each shard record contains index, filename, unit_count, selector_count, active_setup_count, and load_ms. The contiguous indices, deterministic names/extensions, counts, and modeled loads must match the verified plan. No arbitrary URLs or paths are accepted.

## Verification report

verify stdout conforms to schemas/verification.schema.json. It has verification_version=1, result, manifest_sha256, plan_sha256, checks, producer_claim, optimality, audit, and errors. Hashes and producer_claim are null if not yet established. checks has coverage, arithmetic, and baseline values of true, false, or null (not reached). It never treats absence as true. errors is an ordered bounded array of code, pointer, and message, capped at 10 entries and 4096 UTF-8 bytes in aggregate; values are sanitized and may be abbreviated. No full input text is echoed.

result is valid, invalid, or resource_limit. resource_limit is for inability to finish feasibility/arithmetic validation, not for an optional audit alone. valid requires all checks true and no contradictory producer claim. A parsing or relational failure is invalid even if another independent check already passed.

optimality enum:

- bound_proved: verifier's own arithmetic lower=upper
- audit_proved: independent Cartesian audit completed, minimum=plan makespan
- not_certified: valid arithmetic, no proof and no witness, audit not requested
- not_optimal: a better feasible witness exists and producer_claim=feasible
- contradicted: a better witness contradicts a producer claim of search_complete or bound_tight
- unknown: optional audit exhausted, or feasibility/arithmetic could not be established

Audit has state (not_requested, not_run, not_needed, completed, budget_exhausted, counterexample), assignments_visited, assignment_limit, and witness. not_requested has visited=0 and limit=0. not_run means an audit was requested but mandatory input validation or I/O failed before it could run; it has visited=0, the configured limit, and no witness. A requested eligible audit uses the configured limit; requested audit eligibility is checked after mandatory validation but before a bound-tight skip. not_needed has visited=0 and no witness. completed means every required Cartesian tuple was visited. budget_exhausted means a required next tuple was denied, not merely visited=limit. counterexample terminates on the first better feasible tuple in fixed enumeration order. A witness is null or {assignment_vector, makespan_ms}; vector labels are normalized and ordered by original unit index. It is re-evaluated independently before being reported. Budget-exhausted audit is result=valid with optimality=unknown if the preceding mandatory checks passed.

Without --require-optimal, result=valid returns 0 even if optimality is not_certified, not_optimal, or unknown. With --require-optimal, only bound_proved and audit_proved return 0; other otherwise valid results return 6. Contradicted returns 3. Invalid input returns 3; mandatory resource_limit returns 5. --audit-visits without --audit-optimal is an incompatible option. Oversize explicitly requested audit returns 2 even if arithmetic is tight. CLI usage problems return 2 and need not emit a verification JSON object because no command execution began. I/O failures return 4 with result=invalid, a stable io error code, and null unreached checks. Internal faults return 70 with no claim of valid results.

## Command success summaries

plan/export stdout is a single closed object conforming to schemas/cli-result.schema.json with cli_result_version=1, command, result=created, completion_file=complete.json, and files. files lists every produced artifact including complete.json, in lexicographic order. plan additionally gives claim_status and budget_exhausted (true iff budget_events is nonempty); export additionally gives format and shard_count. Relative names only, no output directory or input path. Failed commands emit bounded diagnostics to stderr and do not emit a successful summary. A successful stdout record is written only after complete.json has been closed successfully.

## Format maintenance

Changing field names, serialization, cost semantics, or validation promises requires the corresponding format/model version change. Changing seed order, branch order, tie rules, budget charge boundaries, or heuristic choices requires an algorithm version change. A schema's semantic comment does not relax closed-object validation. A producer must not write fields unsupported by its declared version. Unknown future versions are explicit errors, not forward-compatible guesses.
