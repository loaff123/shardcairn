# Local release-candidate qualification

Date: 2026-10-03. This is local qualification of version 0.1.0. No public repository,
package publication, or hosted CI result is implied. Python 3.11/3.14 and native
Windows/macOS remain hosted-matrix verification gates.

## Executed checks

- CPython 3.12.14, Linux: 118 unittest tests passed, no skips
- CPython 3.13, Linux: 118 unittest tests passed, no skips
- Owned pytest 8.4.2 integration: isolated shard processes checked exact coverage,
  consecutive ordered unit members, and session setup/teardown activations
- Cross-interpreter golden bytes match for canonical manifests, plans, reports,
  JSON exports, and completion markers, including Unicode and integer boundaries
- Source tests include 2,000 independent tiny Cartesian optimizer comparisons,
  exhaustive small move/swap rescoring, feasible prefix-bound checks, budget
  equality/one-before cases, resealed mutations, strict parsing, caps, immutable
  public records, and fault-injected output/marker handling
- Independent fresh reviews separately covered optimizer, verifier/audit, and
  export/CLI/parser/API safety; important findings were repaired and reprobed

## Frozen model evaluation

All 200 tiny, 100 medium, and 11 fixed manifests were frozen before heuristic
workload tuning. One fixed case intentionally rejects safe-aggregate overflow.
The 310 valid cases retain 930 method rows and full outputs. Every held-out case,
no-improvement case, and heuristic miss remains visible.

- Heuristic: 189 strict baseline makespan improvements; 121 equal makespans;
  13 misses among 210 independently enumerable cases
- Auto: 195 strict improvements; 115 equal makespans; zero oracle misses
- Auto exact search completed in 151 cases; 148 retain `search_complete` status,
  while three have the higher-precedence `bound_tight` status
- Both optional methods exhausted a deterministic budget in 17 cases
- All 200 tiny and 10 valid fixed cases were independently enumerated across
  8,281,012 Cartesian tuples, with at most 262,144 tuples for any one case
- The local-pair trap remains baseline 36, heuristic 36, auto/oracle 34

These are original synthetic integer-cost models, not measured CI speedups.
Full inspectable results: [benchmark report](../../benchmarks/evaluation-v1/RESULTS.md).
The evaluator fingerprints every product module/schema before and after the run.

## Resource gates

[resources.json](resources.json) retains actual CPU/elapsed time, peak RSS, bytes,
input SHA-256, dimensions, and product-source identities. Fresh processes on the
recorded Linux environment passed the 60-second and 512-MiB gates; hard limits did
not need to be lowered.

| Fixture | Operation | Elapsed seconds | Peak RSS bytes |
|---|---|---:|---:|
| All count caps | Baseline | 20.172 | 230559744 |
| All count caps | Verify | 10.493 | 215306240 |
| All count caps | Export | 21.608 | 254517248 |
| Exact 16-MiB Unicode input | Baseline | 15.144 | 195817472 |
| Exact 16-MiB Unicode input | Verify | 6.997 | 195330048 |
| Exact 16-MiB Unicode input | Export | 17.340 | 262135808 |

The count fixture simultaneously has 10,000 units, 50,000 selectors, 2,048 declared
setups, 640,000 references (64/unit), and 64 shards; its input is 13,436,313 bytes.
The escaped fixture has 1,000 selectors of 4,096 Unicode scalars, 64 shards, and
exactly 16,777,216 input bytes; its export is 49,126,706 bytes. Baseline runs disable
optional work explicitly. Zero optional ticks do not mean zero preprocessing work.
Recreate either input with tools/resource_qualification.py.

## Independent review outcomes

Optimizer review found a bounded-rollback defect: restoring a deleted dictionary
key could resize a shard counter table after work exhaustion. Tentative removals
now retain zero slots; rollback never inserts a missing prior slot. Independent
resize-threshold and 1,000 zero-slot cutpoint probes confirmed the repair. Further
review probes passed 1,200 seed comparisons, 600 ordered local-reference
comparisons, 720 independent exact-oracle comparisons, 2,080 budget/rollback
cutpoints, 300 byte-identity checks, and six manually corrupted record rejections.

Verifier review found logically impossible phase/origin/counter metadata accepted
alongside correct arithmetic. Nine reproduced contradictions now reject: known
bound-tight phases must skip, local/exact sources must have strict baseline
improvement, completed seeds need primitive work, and fixed-point claims need a
complete neighborhood scan. Fresh checks passed 2,020 assignment evaluations,
120 independent baselines, 420 audit checks, 80 exit/state combinations, and 19
additional malicious mutations. All schemas and import boundaries matched.

Export review found Windows text stdout could change LF to CRLF. Machine records
now use binary stdout, confirmed with a Windows-translation wrapper. Packaging
qualification now builds in copied staging rather than mutating the original
source tree. The safety review passed 54 scoped tests, 13 additional probes,
2,000 randomized canonical-size comparisons, and real short-write/flush/close
fault injection. Native Windows execution remains a separate CI gate.

Reviews are finite evidence, not formal proofs or authentication of producer
history. The verifier never certifies supplied duration estimates or trusts a
search-completion label as independent optimum proof.

## Packaging and remaining release gates

The packaging smoke tool builds from a clean temporary copy, installs a wheel into
a fresh offline environment, rebuilds from the extracted sdist, and checks both
CLI entry points, API/schema availability, and independent audit from an unrelated
working directory. It verifies original-source byte inventory is unchanged. Its
full installed-suite and reproducibility checks use only already available tooling.
Final package hashes are supplied in the release bundle's qualification record.

The repository includes Linux/macOS/Windows × Python 3.11–3.14 CI definitions, but
these have not run on a public commit. Public review/approval, remote publication,
and successful exact-head hosted CI are still required before counting this as a
usable publicly released project. No registry-name reservation is claimed.
