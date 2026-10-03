# Safety and resource contract

Only explicitly named local input files and output destinations are accessed.
No selector or unit/setup ID is ever used as a filename. There is no default config,
glob expansion, home-directory inspection, environment scraping, network access,
telemetry, shell interpolation, test collection, or test execution in product code.

An output destination must be a nonexistent directory in a trusted local parent.
Final-component symlinks and existing targets are rejected. All inputs and artifact
sizes are validated before exclusive directory creation. Files are exclusively
created under fixed names; complete.json is written last. On failure, cleanup only
removes files created by that invocation and its newly created empty directory.
A crash may leave an incomplete directory, which must not be silently reused.
Concurrent hostile replacement of parent-directory components is outside the
portable threat model; use a trusted local destination.

Completion markers are integrity indexes, not security signatures. Directory
consumers require exact filenames, byte counts, and digests, with no extra entries.
A valid marker never substitutes for original-manifest plan verification.

## Hard limits

- Manifest: 16 MiB UTF-8
- Units: 10,000; globally unique selectors: 50,000
- Setup registry: 2,048; references per unit: 64; shards: 64
- IDs: 64 ASCII characters; selectors: 4,096 Unicode scalar values
- JSON nesting: 16; lexical JSON tokens: 2,000,000
- Every cost and sum of all unit standalone costs: at most 9,007,199,254,740,991
- Plan bytes: 64 MiB; all export artifacts combined: 64 MiB
- Human report and completion marker: 64 KiB each; command stdout: 16 KiB
- Exact search: at most 18 units and 8 shards

The cap is checked while reading, before unbounded allocation. Duplicate object
keys, unsafe integer token spellings, invalid UTF-8, unpaired surrogates, control
characters in selectors, unknown fields, and malformed versions fail explicitly.
No partial/truncated plan is presented as valid.

Default deterministic work limits: 5,000,000 primitive ticks, 100,000 local candidate
starts, 250,000 exact-node entries. Hard maxima: 50,000,000 ticks and 2,000,000 each
for local/node counts. Audit visits default to/hard cap at 1,000,000.

A tick precedes a setup-reference, shard-load, candidate, exact-state-comparison,
node-bound, or canonical/tie vector-element examination. Sparse input indexing,
standalone/anchor calculations, fixed sorting, and mandatory baseline construction
are bounded exempt preprocessing. Independent checking occurs only at bounded
complete phase boundaries. Local candidates are lazy; no N² candidate list or
N×K×S matrix exists. Exact search retains at most 18 mutation frames.

Budgets are deterministic work counts, not CPU-time limits. Equality with a cap is
not exhaustion: a needed next operation must actually be denied. Local starts check
candidate then primitive availability atomically; exact entries check node budget
before primitive work. Interrupted mutation is rolled back before a result is used.

Limits are qualified on a recorded release machine, not guaranteed on every device.
See qualification evidence for dimensions, elapsed/CPU time, peak RSS, and artifact
sizes. Measurements are separate from the scheduling model.
