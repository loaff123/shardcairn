# Frozen original synthetic evaluation

All costs below are modeled integer milliseconds, not measured CI speedups. The same default limits apply throughout: 5,000,000 primitive ticks, 100,000 local candidates, and 250,000 exact nodes.

## Complete comparison

| Method | Strict baseline improvements | Equal makespan | Oracle misses / 210 eligible | Arithmetic bound proofs | Completed exact searches | Budget-exhausted cases |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 0 | 310 | 106 | 38 | 0 | 0 |
| heuristic | 189 | 121 | 13 | 70 | 0 | 17 |
| auto | 195 | 115 | 0 | 73 | 151 | 17 |

Every one of the 200 tiny Cartesian spaces completed independently under the one-million tuple cap. All 100 medium cases are recorded with unknown oracle optimum; no global-optimum claim follows from heuristic results. The 10 valid fixed cases also have completed independent oracles. The aggregate-overflow negative fixture was rejected before optimization.

Equal makespan is retained as no-faster even if total modeled work improves. A producer search_complete label is distinct from independent certification; case records retain both.

## Fixed cases

| Case | Baseline | Heuristic | Auto | Oracle |
|---|---:|---:|---:|---:|
| setup-reuse-four | 70 | 60 | 60 | 60 |
| local-pair-trap | 36 | 36 | 34 | 34 |
| equal-load-not-equivalent | 5 | 5 | 5 | 5 |
| no-improvement-equal | 20 | 20 | 20 | 20 |
| no-improvement-common | 30 | 30 | 30 | 30 |
| all-zero | 0 | 0 | 0 | 0 |
| one-shard | 32 | 32 | 32 | 32 |
| one-unit-per-shard | 23 | 23 | 23 | 23 |
| unused-registry | 70 | 60 | 60 | 60 |
| integer-boundary | 9007199254740991 | 9007199254740991 | 9007199254740991 | 9007199254740991 |

The local-pair-trap's 36 versus 34 is an intentional, retained heuristic miss. The documented strict-improvement relocation/swap portfolio cannot escape it. The no-improvement fixtures and zero-work nonempty assignments are retained without filtering.

## All held-out overlapping cases

Mode 4 at base seeds 34 and 55 was frozen as held out before implementation tuning. All 12 cases (36 method rows) are included below and in held-out.jsonl.

| Case | Baseline | Heuristic | Auto | Oracle |
|---|---:|---:|---:|---:|
| tiny-seed-34-j-04 | 412 | 365 | 365 | 365 |
| tiny-seed-34-j-09 | 574 | 497 | 497 | 497 |
| tiny-seed-34-j-14 | 343 | 303 | 267 | 267 |
| tiny-seed-34-j-19 | 135 | 135 | 135 | 135 |
| tiny-seed-55-j-04 | 755 | 534 | 534 | 534 |
| tiny-seed-55-j-09 | 715 | 695 | 695 | 695 |
| tiny-seed-55-j-14 | 301 | 195 | 195 | 195 |
| tiny-seed-55-j-19 | 227 | 195 | 195 | 195 |
| medium-seed-34-j-04 | 1578 | 1292 | 1292 | unknown |
| medium-seed-34-j-09 | 2534 | 1616 | 1616 | unknown |
| medium-seed-55-j-04 | 1901 | 1502 | 1502 | unknown |
| medium-seed-55-j-09 | 2940 | 1786 | 1786 | unknown |

## Every heuristic miss against a completed oracle

| Case | Heuristic | Oracle | Error | Held out |
|---|---:|---:|---:|---|
| tiny-seed-0-j-02 | 330 | 326 | 4 | false |
| tiny-seed-0-j-15 | 185 | 184 | 1 | false |
| tiny-seed-1-j-11 | 418 | 400 | 18 | false |
| tiny-seed-2-j-03 | 386 | 358 | 28 | false |
| tiny-seed-3-j-15 | 186 | 182 | 4 | false |
| tiny-seed-3-j-16 | 327 | 321 | 6 | false |
| tiny-seed-5-j-02 | 364 | 346 | 18 | false |
| tiny-seed-5-j-09 | 640 | 636 | 4 | false |
| tiny-seed-5-j-10 | 105 | 104 | 1 | false |
| tiny-seed-21-j-15 | 130 | 128 | 2 | false |
| tiny-seed-34-j-14 | 303 | 267 | 36 | true |
| tiny-seed-34-j-16 | 413 | 403 | 10 | false |
| local-pair-trap | 36 | 34 | 2 | false |

## Inspectable evidence

- [cases.jsonl.gz](cases.jsonl.gz) (lossless gzip; see [storage notes](STORAGE.md)): all 930 case/method rows, seed membership, modeled makespan/work/setup duplication, bounds/gaps, oracle errors, counters, events, statuses and verification results
- plans/: all baseline records and complete heuristic/auto producer plans
- summary.json: complete method totals plus every no-improvement and oracle-miss case ID
- held-out.jsonl: every held-out outcome
- rejections.jsonl: required invalid overflow rejection
- run.json: exact defaults, source hashes and unchanged-source check
- SHA256SUMS: exact output bytes

This synthetic, deterministic comparison does not measure wall time, production workload representativeness, statistical confidence, or a globally optimal secondary objective. Resource qualification is separate.
