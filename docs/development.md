# Development and qualification

Core tests use Python's standard-library unittest:

```console
PYTHONPATH=src python -m unittest discover -s tests -v
```

On Windows set PYTHONPATH using the shell's normal environment assignment syntax.
The separately identified owned integration test requires pytest≥8.2. It launches
only repository-owned fixture code with unrelated plugin autoloading disabled.
The product itself never imports or launches pytest.

The original-synthetic-v1 fixture generator is portable and versioned. Its complete
200 tiny + 100 medium + 11 fixed manifests were materialized and hash-frozen before
heuristic tuning. One fixed manifest intentionally exceeds the safe aggregate and
must be rejected. Literal independent golden draws/cases qualify the generator.
The mode-4 overlap family at seeds 34 and 55 is held out from tuning. No results are
removed for lack of benefit, budget exhaustion, or a heuristic miss.

Evaluation uses a separate direct-set Cartesian oracle for all tiny cases. Reported
millisecond costs are caller-supplied synthetic model values. Resource/integration
elapsed times are stored separately and never fed back into those values.

`tools/resource_qualification.py` generates a stress fixture simultaneously reaching
10,000 units, 50,000 selectors, 2,048 setup declarations, 64 references per unit,
and 64 shards while fitting the 16 MiB manifest limit. Separate fresh processes
measure baseline planning, independent verification, and export. The release gate
is under 60 seconds per operation and below 512 MiB peak RSS on the recorded Linux
qualification machine. Hosted CI uses smaller bounded tests and explicit timeouts.

Release qualification includes source tests; independent optimizer, verifier, and
export reviews; source/wheel/extracted-sdist installs; CLI/API checks from unrelated
working directories; packaged schema presence; source immutability; deterministic
outputs; and output completion-marker checks. Cross-platform CI definitions cover
Linux, macOS, and Windows with Python 3.11–3.14. A definition alone is not evidence
that hosted jobs passed: only observed jobs for the exact public commit count.

No project completion/publication claim follows from local qualification alone.

Workflow action usage follows the official [checkout](https://github.com/actions/checkout)
and [setup-python](https://github.com/actions/setup-python) documentation. Repository
credentials are not persisted by checkout. Artifact reproducibility is checked with
versioned golden hashes, including opaque Unicode and safe-integer boundaries;
`.gitattributes` keeps frozen text fixtures LF-only on every platform.
