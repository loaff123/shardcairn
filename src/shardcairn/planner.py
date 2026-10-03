"""Public deterministic planner: complete verified incumbents only."""
from .manifest import Manifest, PlanDocument, PlanOptions, validate_manifest
from .canonical import canonical_bytes, manifest_sha256
from .errors import ShardCairnError
from .budgets import Budget, BudgetStop
from .optimization import Prepared, build_seed, local_improve, exact_search
from .verifier import evaluate_assignment, verify


def _checked(prepared, vector, score=None):
    result = evaluate_assignment(prepared.manifest, vector)
    actual = (result['metrics']['makespan_ms'], result['metrics']['total_work_ms'])
    if score is not None and actual != score:
        raise ShardCairnError('internal_invariant', 'Independent phase arithmetic disagrees', exit_code=70)
    return result


def _seed_better(candidate, current, candidate_score, current_score, budget, phase):
    if candidate_score != current_score:
        return candidate_score < current_score
    for a, b in zip(candidate, current):
        budget.tick(phase)
        budget.tick(phase)
        if a != b:
            return a < b
    return False


def plan(manifest: Manifest, options: PlanOptions | None = None) -> PlanDocument:
    """Return immutable canonical plan bytes; never collect or execute tests."""
    manifest = validate_manifest(manifest)
    options = PlanOptions() if options is None else options
    if type(options) is not PlanOptions:
        raise ShardCairnError('options', 'Expected PlanOptions', exit_code=2)
    options.validate()
    if options.mode == 'exact' and (len(manifest.units) > 18 or manifest.shards > 8):
        raise ShardCairnError('exact_size', 'Exact mode requires at most 18 units and 8 shards', exit_code=2)
    p = Prepared(manifest)
    budget = Budget(options.work_limit, options.local_candidates, options.exact_nodes)
    incumbent = p.baseline
    checked = _checked(p, incumbent, p.states[id(incumbent)].cached_score)
    incumbent_score = (checked['metrics']['makespan_ms'], checked['metrics']['total_work_ms'])
    baseline = {'algorithm_version':'exclusive-lpt-v1', 'metrics':checked['metrics'],
                'shards':[{key:record[key] for key in ('index','unit_ids','exclusive_cost_ms','setup_cost_ms','load_ms')}
                          for record in checked['assignment']]}
    seeds = [{'id':'lpt', 'state':'completed'}]
    initial_seed, source = 'lpt', 'seed'
    for kind in ('marginal', 'affinity'):
        if budget.primitive_denied or incumbent_score[0] == p.lower:
            seeds.append({'id':kind, 'state':'not_started'})
            continue
        try:
            candidate = build_seed(p, kind, budget)
            candidate_score = p.states[id(candidate)].cached_score
            better = _seed_better(candidate, incumbent, candidate_score,
                                  incumbent_score, budget, kind+'_seed')
            candidate_checked = _checked(p, candidate, candidate_score)
            seeds.append({'id':kind, 'state':'completed'})
            if better:
                incumbent, incumbent_score, checked = candidate, candidate_score, candidate_checked
                initial_seed = kind
        except BudgetStop:
            seeds.append({'id':kind, 'state':'budget_exhausted'})
    local_state = 'not_started'
    if not budget.primitive_denied and incumbent_score[0] != p.lower:
        before = incumbent
        incumbent, local_state = local_improve(p, incumbent, budget)
        checked = _checked(p, incumbent, p.current_state.cached_score)
        incumbent_score = (checked['metrics']['makespan_ms'], checked['metrics']['total_work_ms'])
        if incumbent is not before:
            source = 'local'
    if options.mode == 'heuristic':
        exact_state = 'not_requested'
    elif options.mode == 'auto' and (p.n > 18 or p.k > 8):
        exact_state = 'skipped_size'
    elif incumbent_score[0] == p.lower:
        exact_state = 'skipped_bound_tight'
    else:
        before = incumbent
        incumbent, exact_state = exact_search(p, incumbent, budget)
        checked = _checked(p, incumbent)
        if checked['metrics']['makespan_ms'] != p.exact_makespan:
            raise ShardCairnError('internal_invariant', 'Independent exact arithmetic disagrees', exit_code=70)
        incumbent_score = (checked['metrics']['makespan_ms'], checked['metrics']['total_work_ms'])
        if incumbent is not before:
            source = 'exact'
    status = ('bound_tight' if checked['bounds']['lower_bound_ms'] == incumbent_score[0]
              else 'search_complete' if exact_state == 'completed' else 'feasible')
    result = {'plan_version':1,
              'model_version':'exclusive-additive-once-per-shard-v1',
              'manifest_hash':{'algorithm':'sha256','normalization':'shardcairn-manifest-c14n-v1',
                               'digest':manifest_sha256(manifest)},
              'solver':{'algorithm_version':'shardcairn-portfolio-v1','requested_mode':options.mode,
                        'initial_seed':initial_seed,'incumbent_source':source,
                        'exact':{'state':exact_state},'seeds':seeds},
              'work':budget.document(local_state),
              'baseline':baseline,
              'assignment':checked['assignment'], 'metrics':checked['metrics'], 'bounds':checked['bounds'],
              'claim':{'status':status,'primary_objective':'makespan','secondary_optimal':False}}
    document = PlanDocument(canonical_bytes(result))
    verdict = verify(manifest, document)
    if verdict.exit_code != 0:
        raise ShardCairnError('internal_invariant', 'Final independent plan verification failed', exit_code=70)
    return document
