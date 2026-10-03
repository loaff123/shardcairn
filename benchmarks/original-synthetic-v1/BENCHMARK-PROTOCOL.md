# ShardCairn frozen evaluation protocol

Protocol version: original-synthetic-v1. This specification is fixed before product optimization. Before tuning implementation heuristics, materialize the complete dataset exactly as specified, retain this protocol, and freeze a SHA-256 index. The index must include every manifest and this protocol. Do not tune by changing the dataset, omit losses, or overwrite its version. Corrections require a new protocol version with an explanation and both versions retained.

All costs are modeled integer milliseconds and all workloads are original synthetic examples. No observed test timing is embedded. Benchmark generation is a development asset, never inventory discovery or a runtime feature.

## Fixed examples

Include these named manifests in addition to the generated cases:

- setup-reuse-four: toy-manifest.json. Baseline 70/70, feasible improvement 50/60, optimum 60, analytic lower bound 55
- local-pair-trap: K=2, units in order with exclusive costs [20,14,12,10,6,6], no setups, one selector per unit. LPT assignment [0,1,1,0,1,0] has loads 36/32. Every single-unit move and pair swap has makespan >=36, while assignment [0,0,1,1,1,1] has 34/34. Both other documented seeds equal LPT without setups. Thus the documented heuristic portfolio cannot escape this case by strict-improvement moves/swaps; exact search can. Preserve it in all reports as a heuristic miss
- equal-load-not-equivalent: K=2, setup x=5, units (5,none),(0,x),(0,x). Optimum 5; unsafe load-only symmetry could miss it
- no-improvement-equal: K=4, eight units p=10, no setups. Baseline and optimum 20
- no-improvement-common: K=3, six units p=5, all require x=20. Every shard is nonempty and pays x; balanced baseline and optimum 30
- all-zero: K=4, seven units p=0, alternating require x=0 or no setup. Require nonempty output despite all zero costs
- one-shard: K=1, three units p=[0,5,9], requirements=[x],[x,y],[] with x=7,y=11. Optimum and analytic bound 32
- one-unit-per-shard: K=3 with the same units/setups. Optimum and analytic bound 23
- unused-registry: setup-reuse-four with unused setup never=9007199254740991. Same objective; unused cost never enters the aggregate charged-work bound
- integer-boundary: K=1, two units p=[9007199254740990,1], no setups. Total exactly safe maximum
- aggregate-overflow-negative-test: previous case with last p=2; must reject before optimization

The fixed examples use unit IDs U0000, U0001, ... except the named A/B/C/D toy, and selectors tests/test_synthetic.py::test_u0000, ... . Ordered grouping coverage is tested separately and must not modify the corresponding model costs.

## Portable generator

For each base seed in [0,1,2,3,5,8,13,21,34,55], initialize an unsigned 32-bit state separately for each case:

    state = (base_seed + 104729 * (case_index + 1) + family_offset) mod 2^32

family_offset=0 for tiny and 1000003 for medium. Each draw updates state=(1664525*state+1013904223) mod 2^32 and returns the new state. below(b) consumes one draw and returns state mod b for positive integer b. Modulo bias is acceptable for these defined synthetic fixtures; there is no probabilistic statistical claim.

Tiny case_index j runs 0..19 for each seed (200 total). N=4+(j mod 6), K=2+(j mod 3), so K<=4 and K^N<=262144. S=1+(j mod 6). Medium j runs 0..9 (100 total), with paired dimensions:

    N = [32,48,64,96,128,160,192,224,240,256][j]
    K = [2,3,4,6,8,10,12,14,16,16][j]
    S = 4 + 2*j

Setup IDs are s0000..s(S-1) and unit IDs u0000..u(N-1), in that order. Draw S setup costs first, each below(200). Then for each unit in index order, draw p=below(100), followed by its requirement-selection draws below. After all requirement draws for that unit, draw selector_count=1+below(3) and use exactly that many ordered selectors tests/test_generated.py::test_uIIII_mMMMM with zero-padded four-digit indices. Selector count does not alter p.

Each case uses mode=j mod 5:

- mode 0, no setup: declare zero setups and consume no setup-cost draws; every unit has no references and consumes no requirement draws
- mode 1, common hub: every unit requires s0000, plus s(1+below(S-1)) when S>1 and below(2)=1; when S=1 consume neither conditional draw
- mode 2, adjacent chain: consume r=below(S), require s(r) and s((r+1) mod S), deduplicated
- mode 3, clustered affinities: consume no requirement draws; require s(i mod S), and additionally s((i+1) mod S) iff i mod 5=0, deduplicated
- mode 4, overlapping random: consume t=below(min(4,S)+1); consume exactly t draws below(S), add those IDs to a set (duplicates simply collapse; do not redraw)

Requirement arrays are sorted by setup ID. For mode 0, S in the dimension formula is ignored and no setup declarations are emitted. For mode 1, evaluate the condition draw below(2) first and draw the secondary ID only when that condition succeeds. This order is normative. Every generated cost is exclusive and every setup declaration uses the stated model.

IDs of cases are tiny-seed-B-j-J and medium-seed-B-j-J with decimal base seed B and two-digit case index J. Store an exact generation ledger (case ID, initial state, N,K,S, mode, draw count, manifest SHA-256) alongside the frozen hash index. Test the generator against independently authored small golden draw/case records before freezing. The held-out family is mode 4 at seeds 34 and 55; do not use it to choose or tune heuristics. Still include every held-out outcome in the final report.

## Required recorded comparisons

For every fixed and generated valid case, retain baseline, heuristic-only, and auto output under the same declared default primitive/local/node limits. For tiny cases independently enumerate all Cartesian assignments; never call optimizer scoring/pruning helpers. If the oracle hits its own stated cap, label it unknown rather than keeping an alleged optimum. All 200 tiny case spaces fit the one-million tuple cap by construction.

Record modeled makespan, modeled total work, setup duplication, analytic lower bound and gap, oracle optimum when independently completed, heuristic/exact error relative to that optimum, operation counters, budget events, and final status. Report count of strict baseline improvements, equality/no-improvement, heuristic misses, arithmetic-bound proofs, completed exact searches, and budget exhaustion. Keep case-level data and seed membership. No-faster cases and misses are first-class rows.

Resource stress fixtures are separate from performance-comparison cases. Include byte cap and cap+1, maximum permitted unit/selector/setup/ref counts that fit the byte cap, 64 shards, deep lexical nesting, long escaped strings, plan/export byte limits, primitive/local/exact budget boundaries, and independently verified zero-work behavior. Record the actual input dimensions rather than calling an impossible combination maximal.

Changes to heuristic code may be tuned against only the non-held-out frozen cases. Resource implementation changes can use the separate stress suite. Neither observed pytest fixture timings nor external production CI timings enter this benchmark protocol. The owned pytest integration checks activation/coverage/order, and its timings are kept separate.
