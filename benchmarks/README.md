# Original synthetic benchmarks

ShardCairn's frozen workload version is `original-synthetic-v1`. These are original synthetic costs, never observed production timings. The fixture version was frozen before optimizer tuning. Its directory must not be modified; corrections require a new version and an explanation retaining both versions.

## Evidence layout

- `original-synthetic-v1/`: exactly 200 tiny, 100 medium, and 11 fixed manifest files; the complete exact protocol, generation ledger, membership, golden records, and SHA-256 index
- `golden-records.json`: literal independent LCG and seven complete case records covering all five modes, no-setup draws, and the single-setup conditional case
- `generate.py`: portable LCG generator; refuses an existing destination
- `oracle.py`: independent unpruned Cartesian tuple enumeration with direct set-union scoring and a one-million assignment cap; no product imports
- `oracles-v1/`: all 310 valid-case oracle eligibility/results, including 200 completed tiny and 10 completed fixed cases
- `evaluate.py`: public-API-only baseline/heuristic/auto evaluation; independently reconstructs all output metrics and bounds
- `evaluation-v1/`: complete stable-source comparison, full outputs, machine-readable rows, and `RESULTS.md`; only the large row file is losslessly gzip-compressed for distribution (see [storage notes](evaluation-v1/STORAGE.md))

The ledger's `S` is the normative dimensional formula even in mode 0; `declared_setup_count` is zero for that mode. `draw_count` includes setup, exclusive cost, requirement, and selector-count draws. The initial and final 32-bit states are recorded. Each raw manifest digest covers sorted-key, two-space-indented UTF-8 JSON with a final LF. This frozen raw-file identity differs intentionally from the product's canonical semantic manifest hash.

Mode 4 at seeds 34 and 55 is explicitly held out: eight tiny and four medium cases. No held-out result was used to choose or tune heuristics. Every held-out result, no-improvement result, and heuristic miss is retained. The required overflow-negative case remains in the frozen membership and is rejected before optimization.

## Reproduce without dependencies

From the repository root, using an available supported Python interpreter:

```sh
python -m unittest discover -s tests -p test_benchmark_generator.py -v
(cd benchmarks/original-synthetic-v1 && sha256sum -c SHA256SUMS)
python benchmarks/generate.py /tmp/shardcairn-fixtures-reproduction
python benchmarks/evaluate.py --oracle-only --output /tmp/shardcairn-oracle-reproduction
PYTHONPATH=src python benchmarks/evaluate.py \
  --oracles /tmp/shardcairn-oracle-reproduction/oracle-results.jsonl \
  --output /tmp/shardcairn-evaluation-reproduction
```

Choose nonexistent output destinations. Scripts do not install anything, discover tests, or launch runners. The comparison uses declared default limits of 5,000,000 primitive ticks, 100,000 local candidates, and 250,000 exact nodes. The baseline is the mandatory baseline emitted and verified in each default-limit plan; its zero optional-work counters do not mean zero CPU work. Full runs reject a changed product-source fingerprint. No wall-clock observation is embedded in deterministic comparison rows.

Resource-capacity and runner integration evidence are separate. These synthetic results establish modeled arithmetic and search behavior, not a production speedup, approximation ratio, or wall-time bound.
