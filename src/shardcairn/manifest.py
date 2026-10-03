"""Immutable public records and closed manifest semantics."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from .errors import ShardCairnError
from .parsing import MANIFEST_MAX_BYTES, PLAN_MAX_BYTES, MAX_SAFE_INTEGER, parse_json, read_bytes

TIMING_BASIS = 'exclusive-additive-once-per-shard-v1'
SCHEMA_VERSION = 1
MAX_UNITS = 10_000
MAX_SELECTORS = 50_000
MAX_SETUPS = 2_048
MAX_SHARDS = 64
MAX_SETUP_REFERENCES = 64
MAX_SELECTOR_SCALARS = 4_096
MAX_ID_LENGTH = 64
STDOUT_MAX_BYTES = 16 * 1024
_ID = re.compile(r'[A-Za-z][A-Za-z0-9_.-]{0,63}\Z', flags=re.ASCII)


@dataclass(frozen=True, slots=True)
class Setup:
    id: str
    cost_ms: int

    def __post_init__(self) -> None:
        _setup(self, '')


@dataclass(frozen=True, slots=True)
class Unit:
    id: str
    selectors: tuple[str, ...]
    exclusive_cost_ms: int
    setup_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _unit(self, '')


@dataclass(frozen=True, slots=True)
class Manifest:
    schema_version: int
    timing_basis: str
    shards: int
    setups: tuple[Setup, ...]
    units: tuple[Unit, ...]

    def __post_init__(self) -> None:
        validate_manifest(self)


def _error(code: str, message: str, pointer: str, resource: bool = False) -> None:
    raise ShardCairnError(code, message, pointer, 5 if resource else 3)


def _integer(value: Any, pointer: str, minimum: int = 0, maximum: int = MAX_SAFE_INTEGER) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        _error('integer_range', 'Expected an integer in the permitted range.', pointer)


def _id(value: Any, pointer: str) -> None:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _error('id', 'Expected a valid ASCII identifier of 1 to 64 characters.', pointer)


def _selector(value: Any, pointer: str) -> None:
    if type(value) is not str or not 1 <= len(value) <= MAX_SELECTOR_SCALARS:
        _error('selector', 'Expected a selector of 1 to 4096 Unicode scalar values.', pointer)
    for character in value:
        point = ord(character)
        if point < 32 or 127 <= point <= 159 or 0xD800 <= point <= 0xDFFF:
            _error('selector', 'Selector contains a forbidden control or non-scalar value.', pointer)


def _tuple(value: Any, pointer: str, maximum: int, nonempty: bool = False) -> None:
    if type(value) is not tuple:
        _error('immutable_type', 'Model collections must be immutable tuples.', pointer)
    if nonempty and not value:
        _error('empty', 'Collection must not be empty.', pointer)
    if len(value) > maximum:
        _error('count_limit', 'Collection exceeds the permitted count.', pointer, True)


def _setup(value: Setup, pointer: str) -> None:
    if type(value) is not Setup:
        _error('model_type', 'Expected an immutable Setup record.', pointer)
    _id(value.id, pointer + '/id')
    _integer(value.cost_ms, pointer + '/cost_ms')


def _unit(value: Unit, pointer: str) -> int:
    if type(value) is not Unit:
        _error('model_type', 'Expected an immutable Unit record.', pointer)
    _id(value.id, pointer + '/id')
    _integer(value.exclusive_cost_ms, pointer + '/exclusive_cost_ms')
    _tuple(value.selectors, pointer + '/selectors', MAX_SELECTORS, True)
    _tuple(value.setup_ids, pointer + '/setup_ids', MAX_SETUP_REFERENCES)
    record_bytes = (len('{"id":"","selectors":[],"exclusive_cost_ms":,"setup_ids":[]}')
                    + len(value.id) + len(str(value.exclusive_cost_ms))
                    + max(0, len(value.selectors) - 1) + max(0, len(value.setup_ids) - 1))
    seen: set[str] = set()
    for index, selector in enumerate(value.selectors):
        location = pointer + f'/selectors/{index}'
        _selector(selector, location)
        if selector in seen:
            _error('duplicate_selector', 'Selector occurs more than once.', location)
        seen.add(selector)
        record_bytes += 2 + len(selector.encode('utf-8')) + selector.count('\\') + selector.count('"')
        if record_bytes > MANIFEST_MAX_BYTES:
            _error('input_size', 'Model exceeds the manifest byte limit.', pointer, True)
    seen.clear()
    for index, setup_id in enumerate(value.setup_ids):
        location = pointer + f'/setup_ids/{index}'
        _id(setup_id, location)
        if setup_id in seen:
            _error('duplicate_reference', 'Setup reference occurs more than once.', location)
        seen.add(setup_id)
        record_bytes += 2 + len(setup_id)
    return record_bytes


def validate_manifest(manifest: Manifest) -> Manifest:
    """Revalidate all manual records before any algorithm/API consumes them."""
    if type(manifest) is not Manifest:
        _error('model_type', 'Expected an immutable Manifest record.', '')
    _integer(manifest.schema_version, '/schema_version', 1, 1)
    if type(manifest.timing_basis) is not str or manifest.timing_basis != TIMING_BASIS:
        _error('timing_basis', 'Unsupported timing basis.', '/timing_basis')
    _integer(manifest.shards, '/shards', 1)
    if manifest.shards > MAX_SHARDS:
        _error('count_limit', 'Shard count exceeds the permitted limit.', '/shards', True)
    _tuple(manifest.setups, '/setups', MAX_SETUPS)
    _tuple(manifest.units, '/units', MAX_UNITS, True)
    if manifest.shards > len(manifest.units):
        _error('shard_count', 'Shard count cannot exceed unit count.', '/shards')
    # The smallest compact UTF-8 representation bounds manually built inputs too.
    manifest_bytes = (len('{"schema_version":1,"timing_basis":"","shards":,"setups":[],"units":[]}')
                      + len(TIMING_BASIS) + len(str(manifest.shards))
                      + max(0, len(manifest.setups) - 1) + len(manifest.units) - 1)
    registry: dict[str, int] = {}
    for index, setup in enumerate(manifest.setups):
        location = f'/setups/{index}'
        _setup(setup, location)
        if setup.id in registry:
            _error('duplicate_id', 'Setup identifier occurs more than once.', location + '/id')
        registry[setup.id] = setup.cost_ms
        manifest_bytes += len('{"id":"","cost_ms":}') + len(setup.id) + len(str(setup.cost_ms))
    unit_ids: set[str] = set()
    selectors: set[str] = set()
    selector_count = 0
    standalone_sum = 0
    for index, unit in enumerate(manifest.units):
        location = f'/units/{index}'
        manifest_bytes += _unit(unit, location)
        if manifest_bytes > MANIFEST_MAX_BYTES:
            _error('input_size', 'Model exceeds the manifest byte limit.', '/units', True)
        if unit.id in unit_ids:
            _error('duplicate_id', 'Unit identifier occurs more than once.', location + '/id')
        unit_ids.add(unit.id)
        selector_count += len(unit.selectors)
        if selector_count > MAX_SELECTORS:
            _error('count_limit', 'Global selector count exceeds the permitted limit.', '/units', True)
        for selector_index, selector in enumerate(unit.selectors):
            if selector in selectors:
                _error('duplicate_selector', 'Selector occurs in more than one unit.', location + f'/selectors/{selector_index}')
            selectors.add(selector)
        charge = unit.exclusive_cost_ms
        for reference_index, setup_id in enumerate(unit.setup_ids):
            if setup_id not in registry:
                _error('unknown_setup', 'Setup reference is not declared.', location + f'/setup_ids/{reference_index}')
            cost = registry[setup_id]
            if cost > MAX_SAFE_INTEGER - charge:
                _error('aggregate_range', 'Stand-alone aggregate exceeds the safe integer range.', location)
            charge += cost
        if charge > MAX_SAFE_INTEGER - standalone_sum:
            _error('aggregate_range', 'Stand-alone aggregate exceeds the safe integer range.', location)
        standalone_sum += charge
    return manifest


def _closed(value: Any, fields: set[str], pointer: str) -> dict:
    if type(value) is not dict:
        _error('object_type', 'Expected an object.', pointer)
    if set(value) != fields:
        _error('object_fields', 'Object must contain exactly the required fields.', pointer)
    return value


def _array(value: Any, pointer: str, maximum: int, nonempty: bool = False) -> list:
    if type(value) is not list:
        _error('array_type', 'Expected an array.', pointer)
    if nonempty and not value:
        _error('empty', 'Array must not be empty.', pointer)
    if len(value) > maximum:
        _error('count_limit', 'Array exceeds the permitted count.', pointer, True)
    return value


def load_manifest(source: bytes | str | Path) -> Manifest:
    data = parse_json(read_bytes(source, MANIFEST_MAX_BYTES), MANIFEST_MAX_BYTES)
    _closed(data, {'schema_version', 'timing_basis', 'shards', 'setups', 'units'}, '')
    raw_setups = _array(data['setups'], '/setups', MAX_SETUPS)
    raw_units = _array(data['units'], '/units', MAX_UNITS, True)
    # Establish every array count before constructing immutable model records.
    selector_count = 0
    for index, value in enumerate(raw_units):
        location = f'/units/{index}'
        _closed(value, {'id', 'selectors', 'exclusive_cost_ms', 'setup_ids'}, location)
        _array(value['selectors'], location + '/selectors', MAX_SELECTORS, True)
        _array(value['setup_ids'], location + '/setup_ids', MAX_SETUP_REFERENCES)
        selector_count += len(value['selectors'])
        if selector_count > MAX_SELECTORS:
            _error('count_limit', 'Global selector count exceeds the permitted limit.', '/units', True)
    setups: list[Setup] = []
    for index, value in enumerate(raw_setups):
        location = f'/setups/{index}'
        _closed(value, {'id', 'cost_ms'}, location)
        _id(value['id'], location + '/id')
        _integer(value['cost_ms'], location + '/cost_ms')
        setups.append(Setup(value['id'], value['cost_ms']))
    units: list[Unit] = []
    for index, value in enumerate(raw_units):
        # Preserve a stable numeric pointer when record-local validation fails.
        try:
            units.append(Unit(value['id'], tuple(value['selectors']), value['exclusive_cost_ms'], tuple(value['setup_ids'])))
        except ShardCairnError as error:
            raise ShardCairnError(error.code, error.message, f'/units/{index}' + error.pointer, error.exit_code) from None
    return Manifest(data['schema_version'], data['timing_basis'], data['shards'], tuple(setups), tuple(units))


def manifest_to_dict(manifest: Manifest) -> dict:
    validate_manifest(manifest)
    return {'schema_version': manifest.schema_version, 'timing_basis': manifest.timing_basis,
            'shards': manifest.shards,
            'setups': [{'id': setup.id, 'cost_ms': setup.cost_ms} for setup in manifest.setups],
            'units': [{'id': unit.id, 'selectors': list(unit.selectors),
                       'exclusive_cost_ms': unit.exclusive_cost_ms, 'setup_ids': list(unit.setup_ids)}
                      for unit in manifest.units]}


@dataclass(frozen=True, slots=True)
class PlanOptions:
    mode: str = 'auto'
    work_limit: int = 5_000_000
    local_candidates: int = 100_000
    exact_nodes: int = 250_000

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> PlanOptions:
        return validate_plan_options(self)


def _option_integer(value: Any, maximum: int, name: str) -> None:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ShardCairnError('usage', 'Option must be an integer in the supported range.', '/' + name, 2)


def validate_plan_options(options: PlanOptions) -> PlanOptions:
    if type(options) is not PlanOptions:
        raise ShardCairnError('usage', 'Expected PlanOptions.', exit_code=2)
    if type(options.mode) is not str or options.mode not in ('auto', 'heuristic', 'exact'):
        raise ShardCairnError('usage', 'Unsupported planning mode.', '/mode', 2)
    _option_integer(options.work_limit, 50_000_000, 'work_limit')
    _option_integer(options.local_candidates, 2_000_000, 'local_candidates')
    _option_integer(options.exact_nodes, 2_000_000, 'exact_nodes')
    return options


@dataclass(frozen=True, slots=True)
class VerifyOptions:
    audit_optimal: bool = False
    audit_visits: int = 1_000_000
    require_optimal: bool = False

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> VerifyOptions:
        return validate_verify_options(self)


def validate_verify_options(options: VerifyOptions) -> VerifyOptions:
    if type(options) is not VerifyOptions:
        raise ShardCairnError('usage', 'Expected VerifyOptions.', exit_code=2)
    if type(options.audit_optimal) is not bool or type(options.require_optimal) is not bool:
        raise ShardCairnError('usage', 'Verification flags must be booleans.', exit_code=2)
    _option_integer(options.audit_visits, 1_000_000, 'audit_visits')
    return options


def _document(data: bytes, maximum: int) -> bytes:
    from .canonical import canonical_bytes
    value = parse_json(data, maximum)
    if type(value) is not dict:
        raise ShardCairnError('object_type', 'Document must be a JSON object.')
    canonical = canonical_bytes(value)
    if len(canonical) > maximum:
        raise ShardCairnError('output_size', 'Document exceeds the byte limit.', exit_code=5)
    return canonical


class _JSONMethods:
    __slots__ = ()
    data: bytes

    def to_dict(self) -> dict:
        return parse_json(self.data, PLAN_MAX_BYTES)

    def to_bytes(self) -> bytes:
        return self.data


@dataclass(frozen=True, slots=True)
class PlanDocument(_JSONMethods):
    data: bytes

    def __post_init__(self) -> None:
        object.__setattr__(self, 'data', _document(self.data, PLAN_MAX_BYTES))


@dataclass(frozen=True, slots=True)
class VerificationResult(_JSONMethods):
    data: bytes
    exit_code: int

    def __post_init__(self) -> None:
        if type(self.exit_code) is not int or self.exit_code not in (0, 2, 3, 4, 5, 6, 70):
            raise ShardCairnError('result_exit', 'Unsupported result exit code.')
        object.__setattr__(self, 'data', _document(self.data, STDOUT_MAX_BYTES))


@dataclass(frozen=True, slots=True)
class ArtifactResult(_JSONMethods):
    data: bytes

    def __post_init__(self) -> None:
        object.__setattr__(self, 'data', _document(self.data, STDOUT_MAX_BYTES))
