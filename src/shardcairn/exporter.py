"""Offline artifact writing. Selectors never become filesystem paths.

Use a trusted local destination parent. Concurrent hostile replacement of parent
components is outside the portable threat model; final targets are checked.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
from typing import Any

from .canonical import canonical_bytes, manifest_sha256, sha256_bytes
from .errors import ShardCairnError
from .manifest import Manifest, PlanDocument, ArtifactResult, validate_manifest
from .parsing import parse_json, read_bytes
from .verifier import validate_plan, validate_schema

OUTPUT_MAX_BYTES = 64 * 1024 * 1024
MARKER_MAX_BYTES = 64 * 1024
REPORT_MAX_BYTES = 64 * 1024
STDOUT_MAX_BYTES = 16 * 1024
_COMPONENT = r'[A-Za-z_][A-Za-z0-9_.-]*'
_NAME = r'[A-Za-z_][A-Za-z0-9_]*'
_PYTEST_SELECTOR = re.compile(rf'(?:{_COMPONENT}/)*{_COMPONENT}\.py::{_NAME}(?:::{_NAME})?', re.ASCII)


def _error(code: str, message: str, exit_code: int = 4) -> ShardCairnError:
    return ShardCairnError(code, message, exit_code=exit_code)


def _json_size(value: Any) -> int:
    """Exact canonical size without allocating encoded copies of input strings."""
    if value is None:
        return 4
    if type(value) is bool:
        return 4 if value else 5
    if type(value) is int:
        return len(str(value))
    if type(value) is str:
        size = 2
        for char in value:
            point = ord(char)
            if char in '"\\' or char in '\b\f\n\r\t':
                size += 2
            elif point < 32 or point > 126:
                size += 12 if point > 65535 else 6
            else:
                size += 1
        return size
    if type(value) is list or type(value) is tuple:
        return 2 + max(0, len(value) - 1) + sum(_json_size(item) for item in value)
    if type(value) is dict:
        return 2 + max(0, len(value) - 1) + sum(_json_size(key) + 1 + _json_size(item) for key, item in value.items())
    raise _error('internal_error', 'Unsupported canonical artifact value', 70)


def _bounded_json(value: Any, limit: int) -> bytes:
    if _json_size(value) + 1 > limit:
        raise _error('output_size_limit', 'Artifact exceeds output byte limit', 5)
    data = canonical_bytes(value)
    if len(data) > limit:
        raise _error('output_size_limit', 'Artifact exceeds output byte limit', 5)
    return data


def _summary(command: str, names: list[str], **fields: Any) -> ArtifactResult:
    data = {'cli_result_version': 1, 'command': command, 'result': 'created',
            'completion_file': 'complete.json', 'files': sorted(names), **fields}
    return ArtifactResult(_bounded_json(data, STDOUT_MAX_BYTES))


def _identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise _error('unsafe_destination', 'Output destination is not a regular directory')
    return info.st_dev, info.st_ino


def _check_entries(path: Path, identity: tuple[int, int], expected: set[str]) -> None:
    if _identity(path) != identity:
        raise _error('unsafe_destination', 'Output destination changed during writing')
    if set(os.listdir(path)) != expected:
        raise _error('unexpected_output_entry', 'Output directory contains unexpected entries')
    for name in expected:
        if not stat.S_ISREG((path / name).lstat().st_mode):
            raise _error('unsafe_destination', 'Output file is not a regular file')


def _write_file(path: Path, data: bytes) -> tuple[int, int]:
    """Exclusive create; remove our own partial file if write or close fails."""
    identity = None
    try:
        with path.open('xb') as stream:
            info = os.fstat(stream.fileno())
            identity = (info.st_dev, info.st_ino)
            written = stream.write(data)
            if written != len(data):
                raise OSError('short artifact write')
            stream.flush()
        return identity
    except BaseException:
        if identity is not None:
            try:
                current = path.lstat()
                if stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == identity:
                    path.unlink()
            except OSError:
                pass
        raise


def _cleanup(path: Path, identity: tuple[int, int], created: dict[str, tuple[int, int]]) -> None:
    try:
        if _identity(path) != identity:
            return
        for name, file_identity in created.items():
            try:
                file = path / name
                info = file.lstat()
                if stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == file_identity:
                    file.unlink()
            except OSError:
                pass
        path.rmdir()  # Fails safely if another actor added an entry.
    except (OSError, ShardCairnError):
        pass


def _write_directory(destination: str | Path, contents: dict[str, bytes], marker: dict) -> None:
    marker_bytes = _bounded_json(marker, MARKER_MAX_BYTES)
    if any(not data for data in contents.values()) or sum(map(len, contents.values())) + len(marker_bytes) > OUTPUT_MAX_BYTES:
        raise _error('output_size_limit', 'Artifacts exceed total output byte limit', 5)
    try:
        path = Path(destination)
    except (TypeError, ValueError) as exc:
        raise _error('unsafe_destination', 'Expected a local output directory path') from exc
    created: dict[str, tuple[int, int]] = {}
    identity = None
    try:
        # mkdir is exclusive even for an existing empty directory or symlink.
        path.mkdir(mode=0o700)
        identity = _identity(path)
        for name in sorted(contents):
            _check_entries(path, identity, set(created))
            created[name] = _write_file(path / name, contents[name])
        _check_entries(path, identity, set(created))
        created['complete.json'] = _write_file(path / 'complete.json', marker_bytes)
        _check_entries(path, identity, set(created))
        verify_directory(path)
    except BaseException as exc:
        if identity is not None:
            _cleanup(path, identity, created)
        if isinstance(exc, ShardCairnError):
            raise
        if isinstance(exc, (OSError, ValueError, TypeError)):
            raise _error('output_io', 'Cannot safely create output directory') from exc
        raise


def _marker(kind: str, manifest_hash: str, plan_hash: str, contents: dict[str, bytes]) -> dict:
    return {'completion_version': 1, 'kind': kind, 'manifest_sha256': manifest_hash,
            'plan_sha256': plan_hash, 'files': [
                {'name': name, 'size_bytes': len(contents[name]), 'sha256': sha256_bytes(contents[name])}
                for name in sorted(contents)]}


def export(manifest: Manifest, plan_document: PlanDocument | bytes | dict,
           destination: str | Path, format: str = 'json') -> ArtifactResult:
    """Verify and export a plan to a new directory, without running tests."""
    manifest = validate_manifest(manifest)
    if format not in ('json', 'pytest-argfile'):
        raise _error('usage', 'Unsupported export format', 2)
    plan = validate_plan(manifest, plan_document)
    plan_bytes = _bounded_json(plan, OUTPUT_MAX_BYTES)
    plan_hash = sha256_bytes(plan_bytes)
    manifest_hash = manifest_sha256(manifest)
    contents: dict[str, bytes] = {}
    records = []
    total = 0
    for shard in plan['assignment']:
        name = f"shard-{shard['index']:03d}.{'json' if format == 'json' else 'args'}"
        selectors = shard['selectors']
        if format == 'json':
            data = _bounded_json(selectors, OUTPUT_MAX_BYTES - total)
        else:
            if any(_PYTEST_SELECTOR.fullmatch(selector) is None for selector in selectors):
                raise _error('unsupported_pytest_selector', 'Selector is outside the restricted pytest grammar', 3)
            size = sum(len(selector) + 1 for selector in selectors)
            if total + size > OUTPUT_MAX_BYTES:
                raise _error('output_size_limit', 'Artifacts exceed total output byte limit', 5)
            data = ''.join(selector + '\n' for selector in selectors).encode('ascii')
        contents[name] = data
        total += len(data)
        records.append({'index': shard['index'], 'filename': name, 'unit_count': len(shard['unit_ids']),
                        'selector_count': len(selectors), 'active_setup_count': len(shard['setup_ids']),
                        'load_ms': shard['load_ms']})
    index = {'export_version': 1, 'format': format, 'manifest_sha256': manifest_hash,
             'plan_sha256': plan_hash, 'shards': records}
    contents['export.json'] = _bounded_json(index, OUTPUT_MAX_BYTES - total)
    marker = _marker('export', manifest_hash, plan_hash, contents)
    result = _summary('export', list(contents) + ['complete.json'], format=format, shard_count=manifest.shards)
    _write_directory(destination, contents, marker)
    return result


def _report(manifest, plan: dict) -> bytes:
    lines = ['ShardCairn allocation report', '',
             'Model estimates only; this is not a measured wall-time prediction.',
             'Review private test identifiers before sharing plan or export files.',
             f"Units: {len(manifest.units)}", f"Selectors: {sum(len(unit.selectors) for unit in manifest.units)}",
             f"Shards: {manifest.shards}", f"Unused setup declarations: {len(manifest.setups) - len({sid for unit in manifest.units for sid in unit.setup_ids})}",
             f"Modeled makespan (ms): {plan['metrics']['makespan_ms']}",
             f"Baseline makespan (ms): {plan['baseline']['metrics']['makespan_ms']}",
             f"Arithmetic lower bound (ms): {plan['bounds']['lower_bound_ms']}",
             f"Absolute gap (ms): {plan['bounds']['absolute_gap_ms']}",
             f"Gap fraction: {plan['bounds']['gap_fraction']['numerator']}/{plan['bounds']['gap_fraction']['denominator']}",
             f"Producer claim: {plan['claim']['status']}",
             'Search-completion labels are not independent optimality certificates.', '', 'Shard summaries:']
    for shard in plan['assignment'][:20]:
        lines.append(f"{shard['index']:03d}: units={len(shard['unit_ids'])}, selectors={len(shard['selectors'])}, setups={len(shard['setup_ids'])}, load_ms={shard['load_ms']}")
    if len(plan['assignment']) > 20:
        lines.append(f"Truncated: {len(plan['assignment']) - 20} additional shard summaries omitted; see plan.json.")
    data = ('\n'.join(lines) + '\n').encode('utf-8')
    if len(data) > REPORT_MAX_BYTES:
        raise _error('output_size_limit', 'Report exceeds byte limit', 5)
    return data


def write_plan(manifest: Manifest, plan_document: PlanDocument | bytes | dict,
               destination: str | Path) -> ArtifactResult:
    """Write a verified canonical plan and bounded report; marker is last."""
    manifest = validate_manifest(manifest)
    plan = validate_plan(manifest, plan_document)
    contents = {'plan.json': _bounded_json(plan, OUTPUT_MAX_BYTES), 'report.txt': _report(manifest, plan)}
    marker = _marker('plan', manifest_sha256(manifest), sha256_bytes(contents['plan.json']), contents)
    result = _summary('plan', list(contents) + ['complete.json'], claim_status=plan['claim']['status'],
                      budget_exhausted=bool(plan['work']['budget_events']))
    _write_directory(destination, contents, marker)
    return result


def _read_regular(path: Path, limit: int) -> bytes:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise _error('unsafe_artifact', 'Artifact is not a regular file')
    return read_bytes(path, limit)


def verify_directory(path: str | Path) -> dict:
    """Check directory completion integrity, not semantic plan optimality.

    An export carries no manifest or plan; its marker is not a signature. Use
    verify(manifest, plan) for independent coverage and arithmetic assurance.
    """
    path = Path(path)
    try:
        identity = _identity(path)
        marker_bytes = _read_regular(path / 'complete.json', MARKER_MAX_BYTES)
        marker = parse_json(marker_bytes, MARKER_MAX_BYTES)
        validate_schema(marker, 'completion')
        if canonical_bytes(marker) != marker_bytes:
            raise _error('invalid_completion', 'Completion marker is not canonical')
        records = marker['files']
        names = [record['name'] for record in records]
        if names != sorted(set(names)):
            raise _error('invalid_completion', 'Completion file list is not sorted and unique')
        _check_entries(path, identity, set(names) | {'complete.json'})
        contents = {}
        total = len(marker_bytes)
        for record in records:
            if total + record['size_bytes'] > OUTPUT_MAX_BYTES:
                raise _error('output_size_limit', 'Directory exceeds total byte limit', 5)
            data = _read_regular(path / record['name'], min(record['size_bytes'], OUTPUT_MAX_BYTES - total))
            if not data or len(data) != record['size_bytes'] or sha256_bytes(data) != record['sha256']:
                raise _error('artifact_integrity', 'Artifact size or digest differs from completion marker')
            total += len(data)
            contents[record['name']] = data
        if marker['kind'] == 'plan':
            if names != ['plan.json', 'report.txt'] or len(contents['report.txt']) > REPORT_MAX_BYTES:
                raise _error('invalid_completion', 'Plan completion file set is invalid')
            plan = parse_json(contents['plan.json'], OUTPUT_MAX_BYTES)
            validate_schema(plan, 'plan')
            if canonical_bytes(plan) != contents['plan.json'] or marker['plan_sha256'] != sha256_bytes(contents['plan.json']) or marker['manifest_sha256'] != plan['manifest_hash']['digest']:
                raise _error('artifact_integrity', 'Plan completion identity mismatch')
            contents['report.txt'].decode('utf-8', 'strict')
        else:
            if 'export.json' not in contents:
                raise _error('invalid_completion', 'Export index is missing')
            index = parse_json(contents['export.json'], OUTPUT_MAX_BYTES)
            validate_schema(index, 'export')
            if canonical_bytes(index) != contents['export.json'] or any(index[key] != marker[key] for key in ('manifest_sha256','plan_sha256')):
                raise _error('artifact_integrity', 'Export completion identity mismatch')
            extension = 'json' if index['format'] == 'json' else 'args'
            expected = ['export.json'] + [f'shard-{i:03d}.{extension}' for i in range(len(index['shards']))]
            if names != expected:
                raise _error('invalid_completion', 'Export completion file set is invalid')
            seen = set()
            total_units = 0
            for i, shard in enumerate(index['shards']):
                filename = f'shard-{i:03d}.{extension}'
                if shard['index'] != i or shard['filename'] != filename:
                    raise _error('invalid_export', 'Export shard names or indices are not contiguous')
                data = contents[filename]
                if extension == 'json':
                    selectors = parse_json(data, OUTPUT_MAX_BYTES)
                    validate_schema(selectors, 'shard-selectors')
                    if canonical_bytes(selectors) != data:
                        raise _error('invalid_export', 'Shard array is not canonical')
                else:
                    text = data.decode('ascii', 'strict')
                    if not text.endswith('\n'):
                        raise _error('invalid_export', 'Argument file is missing final LF')
                    selectors = text[:-1].split('\n')
                    if any(_PYTEST_SELECTOR.fullmatch(selector) is None for selector in selectors):
                        raise _error('invalid_export', 'Argument file contains unsupported selectors')
                total_units += shard['unit_count']
                if len(selectors) != shard['selector_count'] or shard['unit_count'] > len(selectors):
                    raise _error('invalid_export', 'Export selector counts differ from index')
                for selector in selectors:
                    if selector in seen:
                        raise _error('invalid_export', 'Duplicate exported selector')
                    seen.add(selector)
                if len(seen) > 50000 or total_units > 10000:
                    raise _error('invalid_export', 'Export semantic count exceeds limit')
        _check_entries(path, identity, set(names) | {'complete.json'})
        return marker
    except ShardCairnError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise _error('artifact_io', 'Cannot validate completed artifact directory') from exc
