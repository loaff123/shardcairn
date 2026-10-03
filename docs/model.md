# Model contract

For shard j, load is the sum of exclusive unit costs assigned to j plus the cost
of each distinct required setup ID activated on j. A zero-cost setup is still an
activation. An unused registry entry is never charged. A feasible assignment places
every indivisible unit exactly once into exactly K nonempty shards.

The caller, not this software, establishes that:

- Exclusive unit cost includes all work repeated for that unit and excludes setup
- Setup costs are additive and nonoverlapping; nested fixtures are flattened
- A setup ID describes genuinely reusable state with the assumed shard lifetime
- Startup, finalization, and cleanup are included exactly once where applicable
- Workers are homogeneous and begin in the same assumed state
- The trusted runner preserves the ordered consecutive members of each unit

Separate lifetimes need separate setup IDs. Arbitrary dependencies, conditional
execution, shared capacities, synchronization, cross-shard resource conflicts,
heterogeneous workers, and changing work queues are unsupported. A shared setup
is not an execution-order dependency.

## Lower bounds

Let P be total exclusive work and C the cost of the union of globally used setups.
The reported arithmetic lower bound is the larger of:

1. The largest unit standalone cost (exclusive plus all its required setups)
2. ceil((P+C)/K)

The gap is chosen makespan minus this lower bound. Its fraction is intentionally
unreduced: gap/makespan, or 0/1 when makespan is zero. This is a deterministic model
bound, not a confidence interval or a prediction of elapsed time.

Exact search also uses a conditional prefix bound: current charged work plus
remaining exclusive work plus each remaining-needed setup active on no current
shard, divided upward by K. It never reports that prefix-dependent bound as a global
lower bound. Equal loads alone cannot justify symmetry pruning; setup identity,
exclusive load, and occupied status must also match.

## Ordering and identity

Setup declarations and each setup reference set are sorted for hashing. Original
unit order and member order remain unchanged. UTF-8 input is decoded strictly;
strings are not case-folded or Unicode-normalized. Canonical JSON uses sorted keys,
ASCII escapes, no insignificant whitespace, and one final LF. Manifest identity is
SHA-256 under shardcairn-manifest-c14n-v1.

Shards are presented in order of their earliest original unit. Units in each shard
are in original manifest order, with their selectors concatenated unchanged. There
is no cross-shard ordering guarantee. Plugins or runner configuration can change
actual execution order and are outside the planner's control.
