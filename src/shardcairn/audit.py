"""Independent, unpruned Cartesian objective audit (never an optimizer dependency)."""
from itertools import product

from .errors import ShardCairnError
from .manifest import validate_manifest


def audit_size(manifest):
    """Return Cartesian size, rejecting unsupported requested audit dimensions."""
    n, k = len(manifest.units), manifest.shards
    if n > 10 or k > 6:
        raise ShardCairnError('usage', 'Requested audit exceeds supported dimensions', exit_code=2)
    size = 1
    for _ in range(n):
        if size > 1_000_000 // k:
            raise ShardCairnError('usage', 'Requested audit exceeds Cartesian assignment cap', exit_code=2)
        size *= k
    return size


def cartesian_audit(manifest, makespan_ms, assignment_limit=1_000_000):
    """Count every tuple, including empty-shard tuples; stop on the first witness.

    A denied next tuple, rather than equality with the limit, means exhaustion.
    This evaluator deliberately duplicates set-union arithmetic independently of
    both the production optimizer and the verifier's assignment evaluator.
    """
    manifest = validate_manifest(manifest)
    audit_size(manifest)
    if type(assignment_limit) is not int or not 0 <= assignment_limit <= 1_000_000:
        raise ShardCairnError('usage', 'Invalid audit assignment limit', exit_code=2)
    if type(makespan_ms) is not int or makespan_ms < 0:
        raise ShardCairnError('invalid_cost', 'Invalid audit comparison objective')
    k = manifest.shards
    costs = {s.id: s.cost_ms for s in manifest.setups}
    result = dict(state='completed', assignments_visited=0,
                  assignment_limit=assignment_limit, witness=None)
    for vector in product(range(k), repeat=len(manifest.units)):
        if result['assignments_visited'] == assignment_limit:
            result['state'] = 'budget_exhausted'
            return result
        result['assignments_visited'] += 1
        if len(set(vector)) != k:
            continue
        exclusive = [0] * k
        activated = [set() for _ in range(k)]
        for index, unit in enumerate(manifest.units):
            shard = vector[index]
            exclusive[shard] += unit.exclusive_cost_ms
            activated[shard].update(unit.setup_ids)
        maximum = max(exclusive[j] + sum(costs[s] for s in activated[j]) for j in range(k))
        if maximum < makespan_ms:
            labels = {}
            normalized = []
            for old_label in vector:
                if old_label not in labels:
                    labels[old_label] = len(labels)
                normalized.append(labels[old_label])
            result['state'] = 'counterexample'
            result['witness'] = dict(assignment_vector=normalized, makespan_ms=maximum)
            return result
    return result
