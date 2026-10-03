# Prior art and original assets

All implementation, manifests, test fixtures, and benchmarks in this project are
original. Synthetic millisecond costs are not copied production timings and do not
establish real CI speedup. Setup-aware sharding itself is not new.

The closely related Gel/EdgeDB engineering account discusses expensive database
setups, avoiding repeated initialization, and missing-test integrity checks:
https://www.geldata.com/blog/how-we-sharded-our-test-suite-for-10x-faster-runs-on-github-actions

Existing tools are often the right choice:

- pytest-split for ordinary duration-based splitting: https://github.com/jerry-git/pytest-split
- Its grouping/dependent-method discussion: https://github.com/jerry-git/pytest-split/issues/82
- pytest-xdist for module/class/group distribution and work stealing: https://pytest-xdist.readthedocs.io/en/stable/distribution.html
- Buildkite Test Engine for integrated timing workflows: https://buildkite.com/docs/pipelines/configure/tests/bktec/installing-and-using-the-client
- CircleCI integrated timing/configuration: https://circleci.com/docs/reference/configuration-reference/#parallelism
- Knapsack Pro dynamic queues: https://docs.knapsackpro.com/ruby/queue-mode/
- OR-Tools for richer scheduling constraints: https://developers.google.com/optimization/scheduling

No assertion is made that these tools lack every similar feature. ShardCairn's
scope is an explicit reusable-setup model, fixed deterministic planning budgets,
and independently checkable offline artifacts for maintainers who already have a
trustworthy inventory.

The optional adapter uses pytest argument files introduced in version 8.2:
https://docs.pytest.org/en/stable/how-to/usage.html#read-arguments-from-file

Runtime code uses only Python's standard library. Development integration uses
pytest (MIT); build tooling uses setuptools (MIT) and wheel (MIT). No prior-art code
or production dataset is vendored. The project is distributed under MIT.
