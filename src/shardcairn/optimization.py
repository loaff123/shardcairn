"""Deterministic portfolio internals, with transactional bounded neighborhoods.

Preprocessing is limited to validated sparse incidence, standalone/anchor order,
fixed sorting, and mandatory baseline construction. State normalization and every
optional reference/load/vector examination consume the shared primitive budget.
"""
from .baseline import baseline_vector
from .budgets import BudgetStop


class State:
    def __init__(self, p):
        self.vector = [-1] * p.n
        self.exclusive = [0] * p.k
        self.setup_cost = [0] * p.k
        self.counts = [{} for _ in range(p.k)]
        self.masks = [0] * p.k
        self.sizes = [0] * p.k

    @classmethod
    def baseline(cls, p, vector):
        state = cls(p)
        state.vector = list(vector)
        for i, j in enumerate(vector):
            state.sizes[j] += 1
            state.exclusive[j] += p.costs[i]
            for s in p.refs[i]:
                old = state.counts[j].get(s, 0)
                state.counts[j][s] = old + 1
                if old == 0:
                    state.setup_cost[j] += p.setup_costs[s]
                    state.masks[j] |= 1 << s
        state.cached_score = (max(a+b for a,b in zip(state.exclusive,state.setup_cost)), sum(state.exclusive)+sum(state.setup_cost))
        return state

    def score(self, p, budget, phase):
        high = total = 0
        for j in range(p.k):
            budget.tick(phase)
            load = self.exclusive[j] + self.setup_cost[j]
            high = max(high, load)
            total += load
        return high, total

    def normalized(self, p, budget, phase):
        labels = {}
        vector = []
        for j in self.vector:
            budget.tick(phase)
            vector.append(labels.setdefault(j, len(labels)))
        old_order = [None] * p.k
        for old, new in labels.items():
            budget.tick(phase)
            old_order[new] = old
        # All source elements have been examined and charged above. These fixed
        # field gathers do not inspect any additional unit/setup/shard state.
        fields = tuple([getattr(self, name)[j] for j in old_order]
                       for name in ('exclusive', 'setup_cost', 'counts', 'masks', 'sizes'))
        return tuple(vector), fields

    def commit_normalization(self, vector, fields):
        self.vector = list(vector)
        self.exclusive, self.setup_cost, self.counts, self.masks, self.sizes = fields


class Prepared:
    def __init__(self, manifest):
        self.manifest = manifest
        self.n, self.k = len(manifest.units), manifest.shards
        ids = {s.id: i for i, s in enumerate(manifest.setups)}
        self.setup_ids = tuple(s.id for s in manifest.setups)
        self.setup_costs = tuple(s.cost_ms for s in manifest.setups)
        self.costs = tuple(u.exclusive_cost_ms for u in manifest.units)
        self.exclusive_total = sum(self.costs)
        self.refs = tuple(tuple(ids[s] for s in u.setup_ids) for u in manifest.units)
        self.standalone = tuple(self.costs[i] + sum(self.setup_costs[s] for s in self.refs[i])
                                for i in range(self.n))
        self.order = tuple(sorted(range(self.n), key=lambda i: (-self.standalone[i], i)))
        degree = [0] * len(ids)
        for refs in self.refs:
            for s in refs:
                degree[s] += 1
        self.used = tuple(s for s, d in enumerate(degree) if d)
        self.lower = max(max(self.standalone),
                         (sum(self.costs) + sum(self.setup_costs[s] for s in self.used) + self.k - 1) // self.k)
        weights = tuple(self.setup_costs[s] * (degree[s] - 1) for s in range(len(ids)))
        def anchor_key(s):
            return (-weights[s], -self.setup_costs[s], self.setup_ids[s])
        anchors = [min(refs, key=anchor_key) if refs else None for refs in self.refs]
        self.affinity_order = tuple(sorted(range(self.n), key=lambda i:
            ((1, 0, 0, '') if anchors[i] is None else (0,) + anchor_key(anchors[i]))
            + (-self.standalone[i], i)))
        self.baseline = baseline_vector(manifest)
        self.states = {id(self.baseline): State.baseline(self, self.baseline)}


def build_seed(p, kind, budget):
    phase = kind + '_seed'
    state = State(p)
    order = p.order if kind == 'marginal' else p.affinity_order
    empty = p.k
    for pos, i in enumerate(order):
        current_max = 0
        for j in range(p.k):
            budget.tick(phase)
            current_max = max(current_max, state.exclusive[j] + state.setup_cost[j])
        best = None
        chosen = None
        for j in range(p.k):
            budget.tick(phase)  # placement consideration, even if inadmissible
            new_empty = empty - (state.sizes[j] == 0)
            if new_empty > p.n - pos - 1:
                continue
            new_setup = 0
            for s in p.refs[i]:
                budget.tick(phase)
                if s not in state.counts[j]:
                    new_setup += p.setup_costs[s]
            budget.tick(phase)
            load = state.exclusive[j] + state.setup_cost[j] + p.costs[i] + new_setup
            key = ((max(current_max, load), load, new_setup, j)
                   if kind == 'marginal' else (new_setup, load, j))
            if best is None or key < best:
                best, chosen = key, j
        j = chosen
        if state.sizes[j] == 0:
            empty -= 1
        state.sizes[j] += 1
        state.exclusive[j] += p.costs[i]
        state.vector[i] = j
        for s in p.refs[i]:
            budget.tick(phase)
            old = state.counts[j].get(s, 0)
            state.counts[j][s] = old + 1
            if old == 0:
                state.setup_cost[j] += p.setup_costs[s]
                state.masks[j] |= 1 << s
    state.cached_score = state.score(p, budget, phase)
    vector, fields = state.normalized(p, budget, phase)
    state.commit_normalization(vector, fields)
    state.canonical_vector = vector
    p.states[id(vector)] = state
    return vector


def _mutate(p, state, moves, budget, phase, undo):
    """Each undo slot exists before its corresponding state mutation."""
    for i, target in moves:
        source = state.vector[i]
        undo.append(('unit', i, source, target))
        state.vector[i] = target
        state.sizes[source] -= 1
        state.sizes[target] += 1
        state.exclusive[source] -= p.costs[i]
        state.exclusive[target] += p.costs[i]
        for s in p.refs[i]:
            budget.tick(phase)
            old = state.counts[source][s]
            undo.append(('ref', source, s, old, True))
            if old == 1:
                # Keep the existing table slot: rollback must never allocate
                # or rehash untouched setup entries after budget exhaustion.
                state.counts[source][s] = 0
                state.setup_cost[source] -= p.setup_costs[s]
                state.masks[source] &= ~(1 << s)
            else:
                state.counts[source][s] = old - 1
            budget.tick(phase)
            old = state.counts[target].get(s, 0)
            undo.append(('ref', target, s, old, s in state.counts[target]))
            state.counts[target][s] = old + 1
            if old == 0:
                state.setup_cost[target] += p.setup_costs[s]
                state.masks[target] |= 1 << s


def _rollback(p, state, undo):
    for item in reversed(undo):
        if item[0] == 'unit':
            _, i, source, target = item
            state.vector[i] = source
            state.sizes[source] += 1
            state.sizes[target] -= 1
            state.exclusive[source] += p.costs[i]
            state.exclusive[target] -= p.costs[i]
        else:
            _, j, s, old, was_present = item
            now = state.counts[j].get(s, 0)
            if not old:
                if was_present:
                    state.counts[j][s] = 0
                else:
                    state.counts[j].pop(s, None)
                if now:
                    state.setup_cost[j] -= p.setup_costs[s]
                    state.masks[j] &= ~(1 << s)
            else:
                state.counts[j][s] = old
                if not now:
                    state.setup_cost[j] += p.setup_costs[s]
                    state.masks[j] |= 1 << s


def local_improve(p, vector, budget):
    state = p.states[id(vector)]
    incumbent = vector
    # Independent phase-boundary scores are reused as an initialization, while
    # all optional candidate scores below explicitly meter each shard read.
    old_score = state.cached_score
    p.current_state = state
    try:
        while True:
            improved = False
            def considerations():
                for i in range(p.n):
                    for target in range(p.k):
                        yield i, target, None
                for i in range(p.n):
                    for other in range(i+1, p.n):
                        yield i, None, other
            for i, target, other in considerations():
                budget.local_start()
                source = state.vector[i]
                if other is None:
                    if source == target or state.sizes[source] == 1:
                        continue
                    moves = ((i, target),)
                else:
                    target = state.vector[other]
                    if source == target:
                        continue
                    moves = ((i, target), (other, source))
                undo = []
                committed = False
                try:
                    _mutate(p, state, moves, budget, 'local', undo)
                    candidate_score = state.score(p, budget, 'local')
                    if candidate_score < old_score:
                        candidate, fields = state.normalized(p, budget, 'local')
                        state.commit_normalization(candidate, fields)
                        committed = True
                        incumbent, old_score = candidate, candidate_score
                        state.cached_score = candidate_score
                        improved = True
                finally:
                    if not committed:
                        _rollback(p, state, undo)
                if improved:
                    break
            if not improved:
                return incumbent, 'fixed_point'
    except BudgetStop:
        return incumbent, 'budget_exhausted'


def prefix_lower_bound(p, state, remaining_p, remaining_mask, budget):
    """Conditional search bound; never used as a public global lower bound."""
    high = total = 0
    active_mask = 0
    for j in range(p.k):
        budget.tick('exact')
        load = state.exclusive[j] + state.setup_cost[j]
        high = max(high, load)
        total += load
        active_mask |= state.masks[j]
    missing = remaining_mask & ~active_mask
    future = 0
    while missing:
        budget.tick('exact')
        bit = missing & -missing
        future += p.setup_costs[bit.bit_length()-1]
        missing -= bit
    return max(p.lower, high, (total+remaining_p+future+p.k-1)//p.k), high


def exact_search(p, vector, budget):
    """Restricted-growth DFS, safe prefix bounds, no load-only symmetry."""
    state = State(p)
    incumbent = vector
    # The initial score is independently verified at the caller's phase boundary.
    verified = p.states.get(id(vector))
    if verified is None:
        # Local state can be found without traversing input-dependent collections:
        # callers retain the State under its latest canonical vector.
        verified = p.current_state
    best = verified.cached_score[0]
    remaining = p.exclusive_total
    suffix_mask = [0] * (p.n + 1)
    # At most 18*64 setup references; this is search work, not preprocessing.
    initialized = False

    def dfs(depth, occupied, remaining_p):
        nonlocal incumbent, best, initialized
        budget.node_start()
        budget.tick('exact')  # node-bound evaluation, including root/leaf
        if not initialized:
            for d in range(p.n-1, -1, -1):
                mask = suffix_mask[d+1]
                for s in p.refs[p.order[d]]:
                    budget.tick('exact')
                    mask |= 1 << s
                suffix_mask[d] = mask
            initialized = True
        bound, high = prefix_lower_bound(p, state, remaining_p, suffix_mask[depth], budget)
        if p.n - depth < p.k - occupied or high >= best:
            return
        if bound >= best:
            return
        if depth == p.n:
            candidate, _ = state.normalized(p, budget, 'exact')
            incumbent, best = candidate, high
            return
        i = p.order[depth]
        seen = set()
        for j in range(min(occupied+1, p.k)):
            budget.tick('exact')  # candidate placement
            budget.tick('exact')  # exact state equivalence comparison
            key = (state.exclusive[j], state.masks[j], state.sizes[j] != 0)
            if key in seen:
                continue
            seen.add(key)
            old_exclusive = state.exclusive[j]
            old_setup = state.setup_cost[j]
            old_mask = state.masks[j]
            old_size = state.sizes[j]
            undo = []
            state.vector[i] = j
            state.exclusive[j] += p.costs[i]
            state.sizes[j] += 1
            try:
                for s in p.refs[i]:
                    budget.tick('exact')
                    old = state.counts[j].get(s, 0)
                    undo.append((s, old))
                    state.counts[j][s] = old+1
                    if old == 0:
                        state.setup_cost[j] += p.setup_costs[s]
                        state.masks[j] |= 1 << s
                dfs(depth+1, max(occupied,j+1), remaining_p-p.costs[i])
            finally:
                for s, old in reversed(undo):
                    if old:
                        state.counts[j][s] = old
                    else:
                        state.counts[j].pop(s, None)
                state.exclusive[j],state.setup_cost[j],state.masks[j],state.sizes[j] = old_exclusive,old_setup,old_mask,old_size
                state.vector[i] = -1
    try:
        dfs(0, 0, remaining)
        p.exact_makespan = best
        return incumbent, 'completed'
    except BudgetStop:
        p.exact_makespan = best
        return incumbent, 'budget_exhausted'
