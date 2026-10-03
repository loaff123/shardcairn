"""Independent plan validation and explicit, bounded optimality evidence.

No optimizer scoring, baseline, search, or budget implementation is imported.
Search-completion metadata is checked for consistency, never used as proof.
"""
import heapq
import re

from . import audit
from .canonical import canonical_bytes, manifest_sha256, sha256_bytes
from .errors import ShardCairnError
from .manifest import (Manifest, PlanDocument, VerificationResult, VerifyOptions,
                       validate_manifest, validate_verify_options)
from .parsing import PLAN_MAX_BYTES, parse_json

_SCHEMA_NAMES = frozenset(('manifest', 'plan', 'verification', 'completion',
                           'export', 'shard-selectors', 'cli-result'))


def _fail(code, message, pointer=''):
    raise ShardCairnError(code, message, pointer)


def _child(pointer, key):
    return (pointer + '/' + str(key).replace('~', '~0').replace('/', '~1'))[:256]


def _same_scalar(a, b):
    return type(a) is type(b) and a == b


def validate_schema(data, schema_name):
    """Validate the complete bundled closed schema vocabulary without a dependency.

    Shapes are embedded from the reviewed package schemas: no implicit file
    reads are performed. Semantic relations remain caller-owned.
    """
    if schema_name not in _SCHEMA_NAMES:
        raise ValueError('Unknown built-in schema')
    root = _SCHEMAS[schema_name]

    def visit(value, rule, pointer):
        if '$ref' in rule:
            target = root
            for part in rule['$ref'].split('/')[1:]:
                target = target[part.replace('~1', '/').replace('~0', '~')]
            visit(value, target, pointer)
        for keyword in ('anyOf', 'oneOf'):
            if keyword in rule:
                matches = 0
                for candidate in rule[keyword]:
                    try:
                        visit(value, candidate, pointer)
                    except ShardCairnError:
                        continue
                    matches += 1
                if not matches or (keyword == 'oneOf' and matches != 1):
                    _fail('schema', 'Value does not match the required shape', pointer)
        if 'allOf' in rule:
            for candidate in rule['allOf']:
                visit(value, candidate, pointer)
        if 'const' in rule and not _same_scalar(value, rule['const']):
            _fail('schema', 'Unsupported fixed value or version', pointer)
        if 'enum' in rule and not any(_same_scalar(value, choice) for choice in rule['enum']):
            _fail('schema', 'Unsupported enumerated value', pointer)
        if 'type' in rule:
            types = rule['type'] if isinstance(rule['type'], list) else [rule['type']]
            actual = {dict:'object', list:'array', str:'string', int:'integer', bool:'boolean', type(None):'null'}.get(type(value))
            if actual not in types:
                _fail('schema', 'Incorrect JSON value type', pointer)
        if type(value) is dict:
            required = rule.get('required', ())
            for key in required:
                if key not in value:
                    _fail('schema', 'Required field is missing', _child(pointer, key))
            properties = rule.get('properties', {})
            if rule.get('additionalProperties') is False and set(value) - set(properties):
                _fail('schema', 'Unknown object field', pointer)
            for key, child in properties.items():
                if key in value:
                    visit(value[key], child, _child(pointer, key))
        elif type(value) is list:
            if len(value) < rule.get('minItems', 0) or len(value) > rule.get('maxItems', len(value)):
                _fail('schema', 'Array length exceeds the permitted shape', pointer)
            if rule.get('uniqueItems'):
                seen = set()
                for element in value:
                    if type(element) in (str, int, bool, type(None)):
                        key = (type(element).__name__, element)
                    else:
                        key = canonical_bytes(element)
                    if key in seen:
                        _fail('schema', 'Array contains duplicate values', pointer)
                    seen.add(key)
            if 'items' in rule:
                for index, child in enumerate(value):
                    visit(child, rule['items'], _child(pointer, index))
        elif type(value) is str:
            if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
                _fail('schema', 'String contains a non-scalar Unicode value', pointer)
            if len(value) < rule.get('minLength', 0) or len(value) > rule.get('maxLength', len(value)):
                _fail('schema', 'String length exceeds the permitted shape', pointer)
            if 'pattern' in rule and re.search(rule['pattern'], value) is None:
                _fail('schema', 'String does not match the required format', pointer)
        elif type(value) is int:
            if value < rule.get('minimum', value) or value > rule.get('maximum', value):
                _fail('schema', 'Integer is outside the permitted range', pointer)
    visit(data, root, '')
    return data


def _evaluate_validated(manifest, vector):
    k, n = manifest.shards, len(manifest.units)
    if type(vector) is not tuple or len(vector) != n:
        _fail('coverage', 'Assignment must have one integer label per unit', '/assignment')
    if any(type(label) is not int or not 0 <= label < k for label in vector):
        _fail('coverage', 'Assignment shard label is invalid', '/assignment')
    if len(set(vector)) != k:
        _fail('coverage', 'Assignment must contain every nonempty shard', '/assignment')
    costs = {s.id: s.cost_ms for s in manifest.setups}
    labels = {}
    members = []
    for index, label in enumerate(vector):
        if label not in labels:
            labels[label] = len(labels)
            members.append([])
        members[labels[label]].append(index)
    assignment = []
    globally_used = set()
    exclusive_total = setup_total = occurrences = standalone = 0
    for shard_index, indices in enumerate(members):
        exclusive = 0
        activated = set()
        unit_ids, selectors = [], []
        for index in indices:
            unit = manifest.units[index]
            exclusive += unit.exclusive_cost_ms
            activated.update(unit.setup_ids)
            unit_ids.append(unit.id)
            selectors.extend(unit.selectors)
            unit_cost = unit.exclusive_cost_ms + sum(costs[s] for s in unit.setup_ids)
            standalone = max(standalone, unit_cost)
        setup_cost = sum(costs[s] for s in activated)
        globally_used.update(activated)
        exclusive_total += exclusive
        setup_total += setup_cost
        occurrences += len(activated)
        assignment.append(dict(index=shard_index, unit_ids=unit_ids,
                               exclusive_cost_ms=exclusive, setup_cost_ms=setup_cost,
                               load_ms=exclusive + setup_cost, selectors=selectors,
                               setup_ids=sorted(activated)))
    minimum_setup = sum(costs[s] for s in globally_used)
    upper = max(shard['load_ms'] for shard in assignment)
    average = (exclusive_total + minimum_setup + k - 1) // k
    lower = max(standalone, average)
    metrics = dict(exclusive_total_ms=exclusive_total, setup_total_ms=setup_total,
                   minimum_setup_ms=minimum_setup, duplicated_setup_ms=setup_total-minimum_setup,
                   makespan_ms=upper, total_work_ms=exclusive_total+setup_total,
                   activated_setup_occurrences=occurrences)
    bounds = dict(standalone_lower_bound_ms=standalone, average_lower_bound_ms=average,
                  lower_bound_ms=lower, upper_bound_ms=upper, absolute_gap_ms=upper-lower,
                  gap_fraction=dict(numerator=upper-lower, denominator=upper or 1))
    return dict(assignment=assignment, metrics=metrics, bounds=bounds)


def evaluate_assignment(manifest: Manifest, vector: tuple[int, ...]) -> dict:
    """Independently score and normalize one complete, feasible assignment."""
    return _evaluate_validated(validate_manifest(manifest), vector)


def _baseline_validated(manifest):
    # Separate reconstruction: exclusive-only LPT with mandatory initial fill.
    units, k = manifest.units, manifest.shards
    order = sorted(range(len(units)), key=lambda index: (-units[index].exclusive_cost_ms, index))
    vector = [0] * len(units)
    heap = []
    for shard, index in enumerate(order[:k]):
        vector[index] = shard
        heap.append((units[index].exclusive_cost_ms, shard))
    heapq.heapify(heap)
    for index in order[k:]:
        load, shard = heapq.heappop(heap)
        vector[index] = shard
        heapq.heappush(heap, (load + units[index].exclusive_cost_ms, shard))
    evaluated = _evaluate_validated(manifest, tuple(vector))
    shards = [{key:value for key,value in shard.items() if key not in ('selectors', 'setup_ids')}
              for shard in evaluated['assignment']]
    return dict(algorithm_version='exclusive-lpt-v1', shards=shards, metrics=evaluated['metrics'])


def baseline_record(manifest: Manifest) -> dict:
    """Reconstruct the mandatory baseline independently of the optimizer."""
    return _baseline_validated(validate_manifest(manifest))


def _coverage_vector(manifest, records):
    if len(records) != manifest.shards:
        _fail('coverage', 'Shard count differs from manifest', '/assignment')
    if sum(len(shard['unit_ids']) for shard in records) != len(manifest.units):
        _fail('coverage', 'Unit coverage count differs from manifest', '/assignment')
    selector_count = sum(len(unit.selectors) for unit in manifest.units)
    if sum(len(shard['selectors']) for shard in records) != selector_count:
        _fail('coverage', 'Selector coverage count differs from manifest', '/assignment')
    lookup = {unit.id:index for index,unit in enumerate(manifest.units)}
    vector = [-1] * len(manifest.units)
    minima = []
    for expected_index, shard in enumerate(records):
        pointer = '/assignment/' + str(expected_index)
        if shard['index'] != expected_index:
            _fail('coverage', 'Shard indices are not contiguous', pointer + '/index')
        indices = []
        selectors = []
        for uid in shard['unit_ids']:
            if uid not in lookup:
                _fail('coverage', 'Unknown unit identifier', pointer + '/unit_ids')
            index = lookup[uid]
            if vector[index] != -1:
                _fail('coverage', 'Unit occurs on more than one shard', pointer + '/unit_ids')
            vector[index] = expected_index
            indices.append(index)
            selectors.extend(manifest.units[index].selectors)
        if indices != sorted(indices):
            _fail('coverage', 'Unit order differs from manifest order', pointer + '/unit_ids')
        if selectors != shard['selectors']:
            _fail('coverage', 'Selectors differ from exact ordered unit members', pointer + '/selectors')
        minima.append(indices[0])
    if minima != sorted(minima) or -1 in vector:
        _fail('coverage', 'Assignment is not a complete canonical partition', '/assignment')
    return tuple(vector)


def _relations(manifest, plan):
    solver, work = plan['solver'], plan['work']
    seeds = solver['seeds']
    if [seed['id'] for seed in seeds] != ['lpt', 'marginal', 'affinity'] or seeds[0]['state'] != 'completed':
        _fail('status', 'Seeds must follow the fixed completed-baseline order', '/solver/seeds')
    states = {seed['id']:seed['state'] for seed in seeds}
    if states[solver['initial_seed']] != 'completed':
        _fail('status', 'Initial seed did not complete', '/solver/initial_seed')
    counters = (('primitive_work_used','primitive_work_limit'),
                ('local_candidates_started','local_candidate_limit'),
                ('exact_nodes_entered','exact_node_limit'))
    for used, limit in counters:
        if work[used] > work[limit]:
            _fail('status', 'Work counter exceeds its configured limit', '/work/'+used)
    if work['primitive_work_used'] < work['local_candidates_started']:
        _fail('status', 'Local considerations lack their primitive ticks', '/work')
    budgets = ['primitive_work', 'local_candidates', 'exact_nodes']
    phases = ['marginal_seed', 'affinity_seed', 'local', 'exact']
    events = work['budget_events']
    event_phases = [event['phase'] for event in events]
    if len(set(event_phases)) != len(event_phases) or event_phases != sorted(event_phases, key=phases.index):
        _fail('status', 'Budget events violate phase order or one-denial-per-phase', '/work/budget_events')
    event_by_phase = {event['phase']:event['budget'] for event in events}
    if work['denied_budgets'] != [budget for budget in budgets if any(event['budget']==budget for event in events)]:
        _fail('status', 'Denied budget list differs from event projection', '/work/denied_budgets')
    exhausted_counters = dict(primitive_work=counters[0], local_candidates=counters[1], exact_nodes=counters[2])
    for phase, budget in event_by_phase.items():
        permitted = {'primitive_work'} | ({'local_candidates'} if phase=='local' else {'exact_nodes'} if phase=='exact' else set())
        if budget not in permitted:
            _fail('status', 'Budget is invalid for this phase', '/work/budget_events')
        used, limit = exhausted_counters[budget]
        if work[used] != work[limit]:
            _fail('status', 'Denied budget is not exhausted', '/work/budget_events')
    for seed, phase in [('marginal','marginal_seed'), ('affinity','affinity_seed')]:
        if (states[seed] == 'budget_exhausted') != (phase in event_by_phase):
            _fail('status', 'Seed state disagrees with its budget event', '/solver/seeds')
    completed_optional = sum(states[seed] == 'completed' for seed in ('marginal','affinity'))
    if work['primitive_work_used'] < work['local_candidates_started'] + completed_optional:
        _fail('status', 'Completed optional seeds lack disjoint primitive work', '/work/primitive_work_used')
    n = len(manifest.units)
    if work['local_state'] == 'fixed_point' and work['local_candidates_started'] < n * manifest.shards + n * (n - 1) // 2:
        _fail('status', 'Fixed-point claim lacks one complete neighborhood scan', '/work/local_candidates_started')
    tight = plan['bounds']['lower_bound_ms'] == plan['metrics']['makespan_ms']
    baseline_tight = plan['baseline']['metrics']['makespan_ms'] == plan['bounds']['lower_bound_ms']
    if (states['marginal'] == 'not_started') != baseline_tight:
        _fail('status', 'First optional seed skip disagrees with independently known baseline bound', '/solver/seeds/1')
    if baseline_tight and (work['primitive_work_used'] or work['local_candidates_started'] or work['exact_nodes_entered'] or events):
        _fail('status', 'Tight baseline must skip all charged optional work', '/work')
    marginal_denied = 'marginal_seed' in event_by_phase
    marginal_skipped = states['marginal'] == 'not_started'
    if (marginal_denied or marginal_skipped) and states['affinity'] != 'not_started':
        _fail('status', 'Later seed must stop after a primitive denial or bound skip', '/solver/seeds/2')
    if states['affinity'] == 'not_started' and not (marginal_denied or tight):
        _fail('status', 'Later seed skip lacks a matching bound or prior denial', '/solver/seeds/2')
    seed_denied = marginal_denied or 'affinity_seed' in event_by_phase
    local_state = work['local_state']
    if event_by_phase.get('local') == 'primitive_work' and work['local_candidate_limit'] == 0:
        _fail('status', 'Local candidate denial must precede primitive denial at zero candidate cap', '/work/budget_events')
    if (local_state == 'budget_exhausted') != ('local' in event_by_phase):
        _fail('status', 'Local state disagrees with its budget event', '/work/local_state')
    if local_state == 'not_started':
        if work['local_candidates_started'] or (not seed_denied and not tight):
            _fail('status', 'Skipped local phase has incompatible counters or reason', '/work/local_state')
    if seed_denied and local_state != 'not_started':
        _fail('status', 'Local phase cannot run after a denied seed', '/work/local_state')
    exact = solver['exact']['state']
    mode = solver['requested_mode']
    oversized = len(manifest.units)>18 or manifest.shards>8
    if mode=='exact' and oversized:
        _fail('status', 'Forced exact mode exceeds supported dimensions', '/solver/requested_mode')
    if mode=='heuristic':
        allowed = {'not_requested'}
    elif oversized:
        allowed = {'skipped_size'}
    else:
        allowed = {'skipped_bound_tight', 'completed', 'budget_exhausted'}
    if exact not in allowed:
        _fail('status', 'Exact state conflicts with mode or dimensions', '/solver/exact/state')
    if (exact=='budget_exhausted') != ('exact' in event_by_phase):
        _fail('status', 'Exact state disagrees with its budget event', '/solver/exact/state')
    if exact in ('not_requested','skipped_size','skipped_bound_tight') and work['exact_nodes_entered']:
        _fail('status', 'Skipped exact phase reports entered nodes', '/work/exact_nodes_entered')
    if exact=='skipped_bound_tight' and not tight:
        _fail('status', 'Exact bound-tight skip lacks matching arithmetic bound', '/solver/exact/state')
    if exact=='completed' and (not work['exact_nodes_entered'] or not work['primitive_work_used']):
        _fail('status', 'Completed exact phase lacks entered work', '/solver/exact/state')
    if event_by_phase.get('exact')=='primitive_work' and work['exact_nodes_entered']==0:
        _fail('status', 'Exact primitive denial requires root entry', '/work/exact_nodes_entered')
    earlier_primitive = any(event['budget']=='primitive_work' and event['phase']!='exact' for event in events)
    if earlier_primitive and exact in ('completed','budget_exhausted'):
        expected = 'exact_nodes' if work['exact_node_limit']==0 else 'primitive_work'
        expected_nodes = 0 if expected=='exact_nodes' else 1
        if event_by_phase.get('exact')!=expected or work['exact_nodes_entered']!=expected_nodes:
            _fail('status', 'Exact root-entry precedence after primitive denial is inconsistent', '/work')
    source = solver['incumbent_source']
    if states['affinity'] == 'not_started' and not marginal_denied and local_state != 'not_started':
        _fail('status', 'Affinity bound skip must also skip local work', '/work/local_state')
    chosen_objective = (plan['metrics']['makespan_ms'], plan['metrics']['total_work_ms'])
    baseline_objective = (plan['baseline']['metrics']['makespan_ms'], plan['baseline']['metrics']['total_work_ms'])
    if source == 'local' and chosen_objective >= baseline_objective:
        _fail('status', 'Local incumbent must strictly improve the baseline objective tuple', '/solver/incumbent_source')
    if source == 'exact' and chosen_objective[0] >= baseline_objective[0]:
        _fail('status', 'Exact incumbent must strictly improve baseline makespan', '/solver/incumbent_source')
    if tight and source == 'seed':
        if local_state != 'not_started':
            _fail('status', 'Tight seed incumbent must skip local work', '/work/local_state')
        if solver['initial_seed'] == 'marginal' and states['affinity'] != 'not_started':
            _fail('status', 'Tight marginal incumbent must skip the later seed', '/solver/seeds/2')
    pre_exact_tight = (tight and source != 'exact') or (local_state == 'not_started' and not seed_denied)
    if pre_exact_tight and mode != 'heuristic' and not oversized and exact != 'skipped_bound_tight':
        _fail('status', 'Known pre-exact tight bound must skip exact work', '/solver/exact/state')
    if source=='local' and (local_state=='not_started' or not work['local_candidates_started']):
        _fail('status', 'Local incumbent lacks a completed feasible local candidate', '/solver/incumbent_source')
    if source=='exact' and (exact not in ('completed','budget_exhausted') or work['exact_nodes_entered']<len(manifest.units)+1):
        _fail('status', 'Exact incumbent lacks a possible completed feasible leaf', '/solver/incumbent_source')
    if source=='seed' and solver['initial_seed']=='lpt':
        stripped = [{key:value for key,value in shard.items() if key not in ('selectors','setup_ids')} for shard in plan['assignment']]
        if stripped != plan['baseline']['shards']:
            _fail('status', 'Baseline-seed incumbent differs from reconstructed baseline', '/solver/incumbent_source')
    required_claim = 'bound_tight' if tight else 'search_complete' if exact=='completed' else 'feasible'
    if plan['claim']['status'] != required_claim:
        _fail('claim', 'Producer claim violates arithmetic and phase precedence', '/claim/status')


def _document(plan_document):
    if type(plan_document) is PlanDocument:
        raw = plan_document.to_bytes()
    elif type(plan_document) is bytes:
        raw = plan_document
    elif type(plan_document) is dict:
        raw = canonical_bytes(plan_document)
    else:
        _fail('schema', 'Plan must be a PlanDocument, bytes, or JSON object')
    value = parse_json(raw, max_bytes=PLAN_MAX_BYTES)
    validate_schema(value, 'plan')
    return value


def verify(manifest: Manifest, plan_document: PlanDocument | bytes | dict,
           options: VerifyOptions | None = None) -> VerificationResult:
    """Return mandatory validation plus separately stated independent evidence."""
    options = validate_verify_options(VerifyOptions() if options is None else options)
    report = dict(verification_version=1, result='invalid', manifest_sha256=None,
                  plan_sha256=None, checks=dict(coverage=None, arithmetic=None, baseline=None),
                  producer_claim=None, optimality='unknown',
                  audit=dict(state='not_run' if options.audit_optimal else 'not_requested',
                             assignments_visited=0, assignment_limit=options.audit_visits if options.audit_optimal else 0,
                             witness=None), errors=[])
    stage = None
    try:
        manifest = validate_manifest(manifest)
        report['manifest_sha256'] = manifest_sha256(manifest)
        document = _document(plan_document)
        report['plan_sha256'] = sha256_bytes(canonical_bytes(document))
        report['producer_claim'] = document['claim']['status']
        if document['manifest_hash']['digest'] != report['manifest_sha256']:
            _fail('manifest_hash', 'Plan fingerprint differs from normalized manifest', '/manifest_hash/digest')
        stage = 'coverage'
        vector = _coverage_vector(manifest, document['assignment'])
        report['checks'][stage] = True
        stage = 'arithmetic'
        evaluated = _evaluate_validated(manifest, vector)
        for key in ('assignment','metrics','bounds'):
            if document[key] != evaluated[key]:
                _fail('arithmetic', 'Reported value differs from independent set-union calculation', '/'+key)
        report['checks'][stage] = True
        stage = 'baseline'
        baseline = _baseline_validated(manifest)
        if document['baseline'] != baseline:
            _fail('baseline', 'Reported baseline differs from independent LPT reconstruction', '/baseline')
        chosen = document['metrics']
        b = baseline['metrics']
        if (chosen['makespan_ms'],chosen['total_work_ms']) > (b['makespan_ms'],b['total_work_ms']):
            _fail('baseline', 'Chosen assignment regresses against the required baseline', '/metrics')
        report['checks'][stage] = True
        stage = None
        _relations(manifest, document)
        # Eligibility is intentionally checked before the arithmetic-proof skip.
        if options.audit_optimal:
            audit.audit_size(manifest)
        tight = evaluated['bounds']['lower_bound_ms'] == evaluated['metrics']['makespan_ms']
        report['result'] = 'valid'
        report['optimality'] = 'bound_proved' if tight else 'not_certified'
        if options.audit_optimal:
            if tight:
                report['audit']['state'] = 'not_needed'
            else:
                report['audit'] = audit.cartesian_audit(manifest, chosen['makespan_ms'], options.audit_visits)
                state = report['audit']['state']
                if state=='completed':
                    report['optimality'] = 'audit_proved'
                elif state=='budget_exhausted':
                    report['optimality'] = 'unknown'
                elif state=='counterexample':
                    witness = report['audit']['witness']
                    independently_checked = _evaluate_validated(manifest, tuple(witness['assignment_vector']))
                    if independently_checked['metrics']['makespan_ms'] != witness['makespan_ms'] or witness['makespan_ms'] >= chosen['makespan_ms']:
                        raise ShardCairnError('internal', 'Independent audit witness failed re-evaluation', exit_code=70)
                    if report['producer_claim']=='feasible':
                        report['optimality'] = 'not_optimal'
                    else:
                        report['optimality'] = 'contradicted'
                        report['result'] = 'invalid'
                        report['errors'] = [dict(code='contradicted', pointer='/claim/status', message='Independent feasible witness contradicts the producer optimality claim')]
        exit_code = 3 if report['result']=='invalid' else 6 if options.require_optimal and report['optimality'] not in ('bound_proved','audit_proved') else 0
    except ShardCairnError as error:
        if error.exit_code in (2,70):
            raise
        if stage:
            report['checks'][stage] = False
        report['result'] = 'resource_limit' if error.exit_code==5 else 'invalid'
        report['errors'] = [dict(code=error.code, pointer=error.pointer[:256], message=error.message[:512])]
        exit_code = error.exit_code if error.exit_code in (3,4,5) else 3
    validate_schema(report, 'verification')
    return VerificationResult(canonical_bytes(report), exit_code)


def validate_plan(manifest: Manifest, plan_document: PlanDocument | bytes | dict) -> dict:
    """Raise on invalid mandatory validation; otherwise return a detached plan."""
    result = verify(manifest, plan_document)
    if result.exit_code:
        details = result.to_dict()['errors']
        first = details[0] if details else dict(code='invalid_plan', message='Plan failed verification', pointer='')
        raise ShardCairnError(first['code'], first['message'], first['pointer'], exit_code=result.exit_code)
    return _document(plan_document)


# Embedded approved schema snapshots. Keep byte-equivalent semantics to package data.
_SCHEMAS = {'cli-result': {'$comment': 'Structural shape only. DESIGN.md and MACHINE-PROTOCOL.md add '
                            'mandatory semantic, canonicalization, strict-token, aggregate-cap and '
                            'relational constraints.',
                '$id': 'urn:shardcairn:cli-result:1',
                '$schema': 'https://json-schema.org/draft/2020-12/schema',
                'oneOf': [{'additionalProperties': False,
                           'properties': {'budget_exhausted': {'type': 'boolean'},
                                          'claim_status': {'enum': ['feasible',
                                                                    'bound_tight',
                                                                    'search_complete']},
                                          'cli_result_version': {'const': 1},
                                          'command': {'const': 'plan'},
                                          'completion_file': {'const': 'complete.json'},
                                          'files': {'items': {'pattern': '^(complete\\.json|plan\\.json|report\\.txt|export\\.json|shard-[0-9]{3}\\.(json|args))(?![\\s\\S])',
                                                              'type': 'string'},
                                                    'maxItems': 66,
                                                    'minItems': 3,
                                                    'type': 'array',
                                                    'uniqueItems': True},
                                          'result': {'const': 'created'}},
                           'required': ['cli_result_version',
                                        'result',
                                        'completion_file',
                                        'files',
                                        'command',
                                        'claim_status',
                                        'budget_exhausted'],
                           'type': 'object'},
                          {'additionalProperties': False,
                           'properties': {'cli_result_version': {'const': 1},
                                          'command': {'const': 'export'},
                                          'completion_file': {'const': 'complete.json'},
                                          'files': {'items': {'pattern': '^(complete\\.json|plan\\.json|report\\.txt|export\\.json|shard-[0-9]{3}\\.(json|args))(?![\\s\\S])',
                                                              'type': 'string'},
                                                    'maxItems': 66,
                                                    'minItems': 3,
                                                    'type': 'array',
                                                    'uniqueItems': True},
                                          'format': {'enum': ['json', 'pytest-argfile']},
                                          'result': {'const': 'created'},
                                          'shard_count': {'maximum': 64,
                                                          'minimum': 1,
                                                          'type': 'integer'}},
                           'required': ['cli_result_version',
                                        'result',
                                        'completion_file',
                                        'files',
                                        'command',
                                        'format',
                                        'shard_count'],
                           'type': 'object'}],
                'title': 'ShardCairn command success summary version 1'},
 'completion': {'$comment': 'Structural shape only. DESIGN.md and MACHINE-PROTOCOL.md add '
                            'mandatory semantic, canonicalization, strict-token, aggregate-cap and '
                            'relational constraints.',
                '$id': 'urn:shardcairn:completion:1',
                '$schema': 'https://json-schema.org/draft/2020-12/schema',
                'additionalProperties': False,
                'properties': {'completion_version': {'const': 1},
                               'files': {'items': {'additionalProperties': False,
                                                   'properties': {'name': {'pattern': '^(plan\\.json|report\\.txt|export\\.json|shard-[0-9]{3}\\.(json|args))(?![\\s\\S])',
                                                                           'type': 'string'},
                                                                  'sha256': {'pattern': '^[0-9a-f]{64}(?![\\s\\S])',
                                                                             'type': 'string'},
                                                                  'size_bytes': {'maximum': 67108864,
                                                                                 'minimum': 1,
                                                                                 'type': 'integer'}},
                                                   'required': ['name', 'size_bytes', 'sha256'],
                                                   'type': 'object'},
                                         'maxItems': 65,
                                         'minItems': 2,
                                         'type': 'array'},
                               'kind': {'enum': ['plan', 'export']},
                               'manifest_sha256': {'pattern': '^[0-9a-f]{64}(?![\\s\\S])',
                                                   'type': 'string'},
                               'plan_sha256': {'pattern': '^[0-9a-f]{64}(?![\\s\\S])',
                                               'type': 'string'}},
                'required': ['completion_version',
                             'kind',
                             'manifest_sha256',
                             'plan_sha256',
                             'files'],
                'title': 'ShardCairn completion marker version 1',
                'type': 'object'},
 'export': {'$comment': 'Structural shape only. DESIGN.md and MACHINE-PROTOCOL.md add mandatory '
                        'semantic, canonicalization, strict-token, aggregate-cap and relational '
                        'constraints.',
            '$id': 'urn:shardcairn:export:1',
            '$schema': 'https://json-schema.org/draft/2020-12/schema',
            'additionalProperties': False,
            'properties': {'export_version': {'const': 1},
                           'format': {'enum': ['json', 'pytest-argfile']},
                           'manifest_sha256': {'pattern': '^[0-9a-f]{64}(?![\\s\\S])',
                                               'type': 'string'},
                           'plan_sha256': {'pattern': '^[0-9a-f]{64}(?![\\s\\S])',
                                           'type': 'string'},
                           'shards': {'items': {'additionalProperties': False,
                                                'properties': {'active_setup_count': {'maximum': 2048,
                                                                                      'minimum': 0,
                                                                                      'type': 'integer'},
                                                               'filename': {'pattern': '^shard-[0-9]{3}\\.(json|args)(?![\\s\\S])',
                                                                            'type': 'string'},
                                                               'index': {'maximum': 63,
                                                                         'minimum': 0,
                                                                         'type': 'integer'},
                                                               'load_ms': {'maximum': 9007199254740991,
                                                                           'minimum': 0,
                                                                           'type': 'integer'},
                                                               'selector_count': {'maximum': 50000,
                                                                                  'minimum': 1,
                                                                                  'type': 'integer'},
                                                               'unit_count': {'maximum': 10000,
                                                                              'minimum': 1,
                                                                              'type': 'integer'}},
                                                'required': ['index',
                                                             'filename',
                                                             'unit_count',
                                                             'selector_count',
                                                             'active_setup_count',
                                                             'load_ms'],
                                                'type': 'object'},
                                      'maxItems': 64,
                                      'minItems': 1,
                                      'type': 'array'}},
            'required': ['export_version', 'format', 'manifest_sha256', 'plan_sha256', 'shards'],
            'title': 'ShardCairn export index version 1',
            'type': 'object'},
 'manifest': {'$comment': 'Structural schema only. The specification additionally requires exact '
                          'JSON integer tokens (no fractions/exponents/booleans), duplicate-key '
                          'rejection, Unicode scalar validation, aggregate count/cost caps, unique '
                          'IDs/selectors, reference integrity, K<=N, lexical depth/token limits, '
                          'and canonicalization.',
              '$defs': {'cost': {'maximum': 9007199254740991, 'minimum': 0, 'type': 'integer'},
                        'id': {'maxLength': 64,
                               'minLength': 1,
                               'pattern': '^[A-Za-z][A-Za-z0-9_.-]{0,63}(?![\\s\\S])',
                               'type': 'string'},
                        'selector': {'maxLength': 4096,
                                     'minLength': 1,
                                     'pattern': '^[^\\u0000-\\u001f\\u007f-\\u009f]+(?![\\s\\S])',
                                     'type': 'string'},
                        'setup': {'additionalProperties': False,
                                  'properties': {'cost_ms': {'$ref': '#/$defs/cost'},
                                                 'id': {'$ref': '#/$defs/id'}},
                                  'required': ['id', 'cost_ms'],
                                  'type': 'object'},
                        'unit': {'additionalProperties': False,
                                 'properties': {'exclusive_cost_ms': {'$ref': '#/$defs/cost'},
                                                'id': {'$ref': '#/$defs/id'},
                                                'selectors': {'items': {'$ref': '#/$defs/selector'},
                                                              'maxItems': 50000,
                                                              'minItems': 1,
                                                              'type': 'array',
                                                              'uniqueItems': True},
                                                'setup_ids': {'items': {'$ref': '#/$defs/id'},
                                                              'maxItems': 64,
                                                              'minItems': 0,
                                                              'type': 'array',
                                                              'uniqueItems': True}},
                                 'required': ['id', 'selectors', 'exclusive_cost_ms', 'setup_ids'],
                                 'type': 'object'}},
              '$id': 'urn:shardcairn:manifest:1',
              '$schema': 'https://json-schema.org/draft/2020-12/schema',
              'additionalProperties': False,
              'properties': {'schema_version': {'const': 1},
                             'setups': {'items': {'$ref': '#/$defs/setup'},
                                        'maxItems': 2048,
                                        'minItems': 0,
                                        'type': 'array'},
                             'shards': {'maximum': 64, 'minimum': 1, 'type': 'integer'},
                             'timing_basis': {'const': 'exclusive-additive-once-per-shard-v1'},
                             'units': {'items': {'$ref': '#/$defs/unit'},
                                       'maxItems': 10000,
                                       'minItems': 1,
                                       'type': 'array'}},
              'required': ['schema_version', 'timing_basis', 'shards', 'setups', 'units'],
              'title': 'ShardCairn manifest version 1',
              'type': 'object'},
 'plan': {'$comment': 'Closed structural shape only. All relational, arithmetic, original-manifest '
                      'coverage/order, baseline non-regression, status/counter, byte/token, cost, '
                      'and canonicalization constraints in DESIGN.md are normative. '
                      'Search-completion labels are producer assertions, not independent '
                      'certificates.',
          '$defs': {'baseline_shard': {'additionalProperties': False,
                                       'properties': {'exclusive_cost_ms': {'$ref': '#/$defs/cost'},
                                                      'index': {'maximum': 63,
                                                                'minimum': 0,
                                                                'type': 'integer'},
                                                      'load_ms': {'$ref': '#/$defs/cost'},
                                                      'setup_cost_ms': {'$ref': '#/$defs/cost'},
                                                      'unit_ids': {'items': {'$ref': '#/$defs/id'},
                                                                   'maxItems': 10000,
                                                                   'minItems': 1,
                                                                   'type': 'array',
                                                                   'uniqueItems': True}},
                                       'required': ['index',
                                                    'unit_ids',
                                                    'exclusive_cost_ms',
                                                    'setup_cost_ms',
                                                    'load_ms'],
                                       'type': 'object'},
                    'chosen_shard': {'additionalProperties': False,
                                     'properties': {'exclusive_cost_ms': {'$ref': '#/$defs/cost'},
                                                    'index': {'maximum': 63,
                                                              'minimum': 0,
                                                              'type': 'integer'},
                                                    'load_ms': {'$ref': '#/$defs/cost'},
                                                    'selectors': {'items': {'$ref': '#/$defs/selector'},
                                                                  'maxItems': 50000,
                                                                  'minItems': 1,
                                                                  'type': 'array',
                                                                  'uniqueItems': True},
                                                    'setup_cost_ms': {'$ref': '#/$defs/cost'},
                                                    'setup_ids': {'items': {'$ref': '#/$defs/id'},
                                                                  'maxItems': 2048,
                                                                  'minItems': 0,
                                                                  'type': 'array',
                                                                  'uniqueItems': True},
                                                    'unit_ids': {'items': {'$ref': '#/$defs/id'},
                                                                 'maxItems': 10000,
                                                                 'minItems': 1,
                                                                 'type': 'array',
                                                                 'uniqueItems': True}},
                                     'required': ['index',
                                                  'unit_ids',
                                                  'exclusive_cost_ms',
                                                  'setup_cost_ms',
                                                  'load_ms',
                                                  'selectors',
                                                  'setup_ids'],
                                     'type': 'object'},
                    'cost': {'maximum': 9007199254740991, 'minimum': 0, 'type': 'integer'},
                    'id': {'maxLength': 64,
                           'minLength': 1,
                           'pattern': '^[A-Za-z][A-Za-z0-9_.-]{0,63}(?![\\s\\S])',
                           'type': 'string'},
                    'metrics': {'additionalProperties': False,
                                'properties': {'activated_setup_occurrences': {'maximum': 131072,
                                                                               'minimum': 0,
                                                                               'type': 'integer'},
                                               'duplicated_setup_ms': {'maximum': 9007199254740991,
                                                                       'minimum': 0,
                                                                       'type': 'integer'},
                                               'exclusive_total_ms': {'maximum': 9007199254740991,
                                                                      'minimum': 0,
                                                                      'type': 'integer'},
                                               'makespan_ms': {'maximum': 9007199254740991,
                                                               'minimum': 0,
                                                               'type': 'integer'},
                                               'minimum_setup_ms': {'maximum': 9007199254740991,
                                                                    'minimum': 0,
                                                                    'type': 'integer'},
                                               'setup_total_ms': {'maximum': 9007199254740991,
                                                                  'minimum': 0,
                                                                  'type': 'integer'},
                                               'total_work_ms': {'maximum': 9007199254740991,
                                                                 'minimum': 0,
                                                                 'type': 'integer'}},
                                'required': ['exclusive_total_ms',
                                             'setup_total_ms',
                                             'minimum_setup_ms',
                                             'duplicated_setup_ms',
                                             'makespan_ms',
                                             'total_work_ms',
                                             'activated_setup_occurrences'],
                                'type': 'object'},
                    'selector': {'maxLength': 4096,
                                 'minLength': 1,
                                 'pattern': '^[^\\u0000-\\u001f\\u007f-\\u009f]+(?![\\s\\S])',
                                 'type': 'string'}},
          '$id': 'urn:shardcairn:plan:1',
          '$schema': 'https://json-schema.org/draft/2020-12/schema',
          'additionalProperties': False,
          'properties': {'assignment': {'items': {'$ref': '#/$defs/chosen_shard'},
                                        'maxItems': 64,
                                        'minItems': 1,
                                        'type': 'array'},
                         'baseline': {'additionalProperties': False,
                                      'properties': {'algorithm_version': {'const': 'exclusive-lpt-v1'},
                                                     'metrics': {'$ref': '#/$defs/metrics'},
                                                     'shards': {'items': {'$ref': '#/$defs/baseline_shard'},
                                                                'maxItems': 64,
                                                                'minItems': 1,
                                                                'type': 'array'}},
                                      'required': ['algorithm_version', 'shards', 'metrics'],
                                      'type': 'object'},
                         'bounds': {'additionalProperties': False,
                                    'properties': {'absolute_gap_ms': {'$ref': '#/$defs/cost'},
                                                   'average_lower_bound_ms': {'$ref': '#/$defs/cost'},
                                                   'gap_fraction': {'additionalProperties': False,
                                                                    'properties': {'denominator': {'maximum': 9007199254740991,
                                                                                                   'minimum': 1,
                                                                                                   'type': 'integer'},
                                                                                   'numerator': {'$ref': '#/$defs/cost'}},
                                                                    'required': ['numerator',
                                                                                 'denominator'],
                                                                    'type': 'object'},
                                                   'lower_bound_ms': {'$ref': '#/$defs/cost'},
                                                   'standalone_lower_bound_ms': {'$ref': '#/$defs/cost'},
                                                   'upper_bound_ms': {'$ref': '#/$defs/cost'}},
                                    'required': ['standalone_lower_bound_ms',
                                                 'average_lower_bound_ms',
                                                 'lower_bound_ms',
                                                 'upper_bound_ms',
                                                 'absolute_gap_ms',
                                                 'gap_fraction'],
                                    'type': 'object'},
                         'claim': {'additionalProperties': False,
                                   'properties': {'primary_objective': {'const': 'makespan'},
                                                  'secondary_optimal': {'const': False},
                                                  'status': {'enum': ['feasible',
                                                                      'bound_tight',
                                                                      'search_complete']}},
                                   'required': ['status', 'primary_objective', 'secondary_optimal'],
                                   'type': 'object'},
                         'manifest_hash': {'additionalProperties': False,
                                           'properties': {'algorithm': {'const': 'sha256'},
                                                          'digest': {'pattern': '^[0-9a-f]{64}(?![\\s\\S])',
                                                                     'type': 'string'},
                                                          'normalization': {'const': 'shardcairn-manifest-c14n-v1'}},
                                           'required': ['algorithm', 'normalization', 'digest'],
                                           'type': 'object'},
                         'metrics': {'$ref': '#/$defs/metrics'},
                         'model_version': {'const': 'exclusive-additive-once-per-shard-v1'},
                         'plan_version': {'const': 1},
                         'solver': {'additionalProperties': False,
                                    'properties': {'algorithm_version': {'const': 'shardcairn-portfolio-v1'},
                                                   'exact': {'additionalProperties': False,
                                                             'properties': {'state': {'enum': ['not_requested',
                                                                                               'skipped_size',
                                                                                               'skipped_bound_tight',
                                                                                               'completed',
                                                                                               'budget_exhausted']}},
                                                             'required': ['state'],
                                                             'type': 'object'},
                                                   'incumbent_source': {'enum': ['seed',
                                                                                 'local',
                                                                                 'exact']},
                                                   'initial_seed': {'enum': ['lpt',
                                                                             'marginal',
                                                                             'affinity']},
                                                   'requested_mode': {'enum': ['auto',
                                                                               'heuristic',
                                                                               'exact']},
                                                   'seeds': {'items': {'additionalProperties': False,
                                                                       'properties': {'id': {'enum': ['lpt',
                                                                                                      'marginal',
                                                                                                      'affinity']},
                                                                                      'state': {'enum': ['completed',
                                                                                                         'budget_exhausted',
                                                                                                         'not_started']}},
                                                                       'required': ['id', 'state'],
                                                                       'type': 'object'},
                                                             'maxItems': 3,
                                                             'minItems': 3,
                                                             'type': 'array'}},
                                    'required': ['algorithm_version',
                                                 'requested_mode',
                                                 'initial_seed',
                                                 'incumbent_source',
                                                 'exact',
                                                 'seeds'],
                                    'type': 'object'},
                         'work': {'additionalProperties': False,
                                  'properties': {'budget_events': {'items': {'additionalProperties': False,
                                                                             'properties': {'budget': {'enum': ['primitive_work',
                                                                                                                'local_candidates',
                                                                                                                'exact_nodes']},
                                                                                            'phase': {'enum': ['marginal_seed',
                                                                                                               'affinity_seed',
                                                                                                               'local',
                                                                                                               'exact']}},
                                                                             'required': ['phase',
                                                                                          'budget'],
                                                                             'type': 'object'},
                                                                   'maxItems': 4,
                                                                   'minItems': 0,
                                                                   'type': 'array',
                                                                   'uniqueItems': True},
                                                 'denied_budgets': {'items': {'enum': ['primitive_work',
                                                                                       'local_candidates',
                                                                                       'exact_nodes']},
                                                                    'maxItems': 3,
                                                                    'minItems': 0,
                                                                    'type': 'array',
                                                                    'uniqueItems': True},
                                                 'exact_node_limit': {'maximum': 2000000,
                                                                      'minimum': 0,
                                                                      'type': 'integer'},
                                                 'exact_nodes_entered': {'maximum': 2000000,
                                                                         'minimum': 0,
                                                                         'type': 'integer'},
                                                 'local_candidate_limit': {'maximum': 2000000,
                                                                           'minimum': 0,
                                                                           'type': 'integer'},
                                                 'local_candidates_started': {'maximum': 2000000,
                                                                              'minimum': 0,
                                                                              'type': 'integer'},
                                                 'local_state': {'enum': ['not_started',
                                                                          'fixed_point',
                                                                          'budget_exhausted']},
                                                 'primitive_work_limit': {'maximum': 50000000,
                                                                          'minimum': 0,
                                                                          'type': 'integer'},
                                                 'primitive_work_used': {'maximum': 50000000,
                                                                         'minimum': 0,
                                                                         'type': 'integer'}},
                                  'required': ['primitive_work_limit',
                                               'local_candidate_limit',
                                               'exact_node_limit',
                                               'primitive_work_used',
                                               'local_candidates_started',
                                               'exact_nodes_entered',
                                               'denied_budgets',
                                               'local_state',
                                               'budget_events'],
                                  'type': 'object'}},
          'required': ['plan_version',
                       'model_version',
                       'manifest_hash',
                       'solver',
                       'work',
                       'baseline',
                       'assignment',
                       'metrics',
                       'bounds',
                       'claim'],
          'title': 'ShardCairn plan version 1',
          'type': 'object'},
 'shard-selectors': {'$comment': 'Structural shape only. DESIGN.md and MACHINE-PROTOCOL.md add '
                                 'mandatory semantic, canonicalization, strict-token, '
                                 'aggregate-cap and relational constraints.',
                     '$id': 'urn:shardcairn:shard-selectors:1',
                     '$schema': 'https://json-schema.org/draft/2020-12/schema',
                     'items': {'maxLength': 4096,
                               'minLength': 1,
                               'pattern': '^[^\\u0000-\\u001f\\u007f-\\u009f]+(?![\\s\\S])',
                               'type': 'string'},
                     'maxItems': 50000,
                     'minItems': 1,
                     'title': 'ShardCairn shard selector array version 1',
                     'type': 'array',
                     'uniqueItems': True},
 'verification': {'$comment': 'Structural shape only. DESIGN.md and MACHINE-PROTOCOL.md add '
                              'mandatory semantic, canonicalization, strict-token, aggregate-cap '
                              'and relational constraints.',
                  '$id': 'urn:shardcairn:verification:1',
                  '$schema': 'https://json-schema.org/draft/2020-12/schema',
                  'additionalProperties': False,
                  'properties': {'audit': {'additionalProperties': False,
                                           'properties': {'assignment_limit': {'maximum': 1000000,
                                                                               'minimum': 0,
                                                                               'type': 'integer'},
                                                          'assignments_visited': {'maximum': 1000000,
                                                                                  'minimum': 0,
                                                                                  'type': 'integer'},
                                                          'state': {'enum': ['not_requested',
                                                                             'not_run',
                                                                             'not_needed',
                                                                             'completed',
                                                                             'budget_exhausted',
                                                                             'counterexample']},
                                                          'witness': {'anyOf': [{'additionalProperties': False,
                                                                                 'properties': {'assignment_vector': {'items': {'maximum': 5,
                                                                                                                                'minimum': 0,
                                                                                                                                'type': 'integer'},
                                                                                                                      'maxItems': 10,
                                                                                                                      'minItems': 1,
                                                                                                                      'type': 'array'},
                                                                                                'makespan_ms': {'maximum': 9007199254740991,
                                                                                                                'minimum': 0,
                                                                                                                'type': 'integer'}},
                                                                                 'required': ['assignment_vector',
                                                                                              'makespan_ms'],
                                                                                 'type': 'object'},
                                                                                {'type': 'null'}]}},
                                           'required': ['state',
                                                        'assignments_visited',
                                                        'assignment_limit',
                                                        'witness'],
                                           'type': 'object'},
                                 'checks': {'additionalProperties': False,
                                            'properties': {'arithmetic': {'type': ['boolean',
                                                                                   'null']},
                                                           'baseline': {'type': ['boolean',
                                                                                 'null']},
                                                           'coverage': {'type': ['boolean',
                                                                                 'null']}},
                                            'required': ['coverage', 'arithmetic', 'baseline'],
                                            'type': 'object'},
                                 'errors': {'items': {'additionalProperties': False,
                                                      'properties': {'code': {'pattern': '^[a-z][a-z0-9_]{0,63}(?![\\s\\S])',
                                                                              'type': 'string'},
                                                                     'message': {'maxLength': 512,
                                                                                 'type': 'string'},
                                                                     'pointer': {'maxLength': 256,
                                                                                 'type': 'string'}},
                                                      'required': ['code', 'pointer', 'message'],
                                                      'type': 'object'},
                                            'maxItems': 10,
                                            'minItems': 0,
                                            'type': 'array'},
                                 'manifest_sha256': {'anyOf': [{'pattern': '^[0-9a-f]{64}(?![\\s\\S])',
                                                                'type': 'string'},
                                                               {'type': 'null'}]},
                                 'optimality': {'enum': ['bound_proved',
                                                         'audit_proved',
                                                         'not_certified',
                                                         'not_optimal',
                                                         'contradicted',
                                                         'unknown']},
                                 'plan_sha256': {'anyOf': [{'pattern': '^[0-9a-f]{64}(?![\\s\\S])',
                                                            'type': 'string'},
                                                           {'type': 'null'}]},
                                 'producer_claim': {'anyOf': [{'enum': ['feasible',
                                                                        'bound_tight',
                                                                        'search_complete']},
                                                              {'type': 'null'}]},
                                 'result': {'enum': ['valid', 'invalid', 'resource_limit']},
                                 'verification_version': {'const': 1}},
                  'required': ['verification_version',
                               'result',
                               'manifest_sha256',
                               'plan_sha256',
                               'checks',
                               'producer_claim',
                               'optimality',
                               'audit',
                               'errors'],
                  'title': 'ShardCairn verification result version 1',
                  'type': 'object'}}
