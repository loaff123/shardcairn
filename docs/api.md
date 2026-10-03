# CLI and Python API

```console
shardcairn plan MANIFEST --out-dir DIR [--mode auto|heuristic|exact]
  [--work-limit INT] [--local-candidates INT] [--exact-nodes INT]
shardcairn verify MANIFEST PLAN [--audit-optimal] [--audit-visits INT]
  [--require-optimal]
shardcairn export MANIFEST PLAN --out-dir DIR [--format json|pytest-argfile]
```

A command emits one canonical JSON result on stdout. Failed plan/export commands
never emit a created summary. Verification emits a structured report when command
execution begins; incompatible options may instead emit a bounded usage diagnostic.
Diagnostics are bounded, contain no ANSI color, and avoid reflecting full input.

Exit codes: 0 requested success; 2 syntax/incompatible options; 3 invalid input or
contradicted claim; 4 I/O or unsafe output destination; 5 hard resource limit;
6 requested independent optimality not established; 70 internal invariant failure.
Optimization budget exhaustion after a valid baseline is a successful feasible
plan (exit 0), with explicit phase events rather than a false completion label.

```python
from shardcairn import load_manifest, plan, verify, export, PlanOptions, VerifyOptions

manifest = load_manifest("manifest.json")
result = plan(manifest, PlanOptions(mode="auto"))
report = verify(manifest, result, VerifyOptions(audit_optimal=True))
if report.exit_code == 0:
    export(manifest, result, "new-shards", format="json")
```

`load_manifest` accepts bytes or an explicit string/Path filesystem path.
`Manifest`, `Unit`, `Setup`, options, and returned document/result records are
immutable. Manually constructed objects are revalidated at public API boundaries.
`PlanDocument.to_bytes()` provides canonical JSON; `.to_dict()` returns a detached
mutable copy, never a view into internal state. Verification and export accept a
PlanDocument, plan bytes, or a detached plan dictionary. No API receives a runner
or automatically imports user code. Domain exceptions expose bounded `code`,
`message`, `pointer`, and `exit_code` fields.

## Pytest adapter

JSON preserves selectors as opaque data. The opt-in pytest argument-file format
accepts only relative ASCII `.py` paths followed by `::test_name` or
`::ClassName::test_name`. Path components begin with ASCII letter/underscore and
continue with letters, digits, underscore, dot, or hyphen. Member names contain
letters/digits/underscore and begin with letter/underscore.

No spaces, Unicode, parametrized brackets, quotes, backslashes, absolute paths,
parent traversal, option prefixes, `@`, wildcard, or shell syntax are accepted.
Unsupported selectors can still be exported as JSON for a separately trusted
adapter. There is no escaping mode.

The user may run pytest≥8.2 from their chosen repository root:

```console
python -m pytest @shards/shard-000.args
```

ShardCairn never runs that command. Runner/plugins can alter order. The owned
integration fixture tests the narrow adapter's coverage, order, and session-setup
activations in isolated processes; it does not validate millisecond estimates.
