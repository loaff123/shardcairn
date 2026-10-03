# Verification and claims

`verify` has separate structural/arithmetic validity and optimality results.
Successful ordinary verification means coverage, grouping/order, modeled costs,
baseline, bounds, identity, and protocol relations checked out. It does not mean
supplied durations are measured or runner semantics were validated.

- `bound_proved`: verifier independently obtained matching arithmetic bounds
- `audit_proved`: its independent Cartesian enumeration finished and matched
- `not_certified`: valid arithmetic without an independent optimum proof
- `not_optimal`: a better witness exists for a producer claiming only feasibility
- `contradicted`: a better witness disproves the producer's optimum claim
- `unknown`: optional audit ran out of visits, or mandatory checking could not finish

Producer claims are `feasible`, `bound_tight`, or `search_complete`. Counters and
labels can be internally consistent without authenticating a search history.
A forged `search_complete` label remains uncertified by default.

The optional audit visits all Cartesian label tuples in original unit order,
including infeasible tuples with empty shards. It uses no optimizer pruning or
symmetry. Eligibility is N≤10, K≤6, and K^N≤1,000,000. Explicitly requesting an
oversize audit is a usage error even when an arithmetic bound happens to be tight.
Its default/hard visit cap is 1,000,000. Reaching a cap is not exhaustion unless a
needed next tuple is denied. A found witness is independently evaluated and
normalized before reporting.

`--require-optimal` returns 6 when otherwise valid input lacks an independent
proof; no optional audit is implicitly requested. An exhausted optional audit does
not invalidate established coverage and arithmetic. A mandatory resource limit
cannot yield a valid certificate.

The verifier and audit import no optimizer, seed, local-search, exact-search,
baseline, or scoring helpers. Shared code is limited to strict JSON, immutable
models, constants, canonical serialization, and errors. The baseline reconstruction
and set-union arithmetic are independently implemented.
