"""Versioned, integer-only deterministic JSON and normalized manifest identity."""
from __future__ import annotations

import hashlib
import json
from typing import Any, TYPE_CHECKING

from .errors import ShardCairnError
from .parsing import MAX_JSON_DEPTH, MAX_JSON_TOKENS, MAX_SAFE_INTEGER, PLAN_MAX_BYTES

if TYPE_CHECKING:
    from .manifest import Manifest


def _measure(value: Any) -> int:
    """Check supported values and bound bytes/tokens before encoder allocation."""
    size = 1  # The canonical final LF.
    tokens = 0

    def add(byte_count: int, token_count: int = 0) -> None:
        nonlocal size, tokens
        size += byte_count
        tokens += token_count
        if size > PLAN_MAX_BYTES:
            raise ShardCairnError('output_size', 'Canonical JSON exceeds the byte limit.', exit_code=5)
        if tokens > MAX_JSON_TOKENS:
            raise ShardCairnError('json_tokens', 'JSON exceeds the token limit.', exit_code=5)

    def string(text: str, key: bool = False) -> None:
        add(2, 1)
        if key and not text.isascii():
            raise ShardCairnError('object_key', 'Canonical object keys must be ASCII strings.')
        # This cheap lower bound rejects huge strings before a character scan.
        if len(text) > PLAN_MAX_BYTES - size:
            raise ShardCairnError('output_size', 'Canonical JSON exceeds the byte limit.', exit_code=5)
        for character in text:
            point = ord(character)
            if 0xD800 <= point <= 0xDFFF:
                raise ShardCairnError('unicode_scalar', 'JSON strings must contain Unicode scalar values.')
            if character in '"\\\b\f\n\r\t':
                add(2)
            elif point < 32 or 127 <= point <= 0xFFFF:
                add(6)
            elif point > 0xFFFF:
                add(12)
            else:
                add(1)

    def walk(item: Any, depth: int) -> None:
        kind = type(item)
        if kind is dict or kind is list or kind is tuple:
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ShardCairnError('json_depth', 'JSON exceeds the nesting limit.', exit_code=5)
            add(2, 2)
            for index, entry in enumerate(item):
                if index:
                    add(1, 1)
                if kind is dict:
                    if type(entry) is not str:
                        raise ShardCairnError('object_key', 'Canonical object keys must be ASCII strings.')
                    string(entry, key=True)
                    add(1, 1)
                    walk(item[entry], depth)
                else:
                    walk(entry, depth)
        elif kind is str:
            string(item)
        elif kind is bool:
            add(4 if item else 5, 1)
        elif item is None:
            add(4, 1)
        elif kind is int:
            if not 0 <= item <= MAX_SAFE_INTEGER:
                raise ShardCairnError('integer_range', 'Integer is outside the nonnegative safe range.')
            add(len(str(item)), 1)
        else:
            raise ShardCairnError('json_type', 'Value is not a supported JSON type.')

    walk(value, 0)
    return size


def canonical_bytes(value: Any) -> bytes:
    """Serialize validated JSON as sorted ASCII-key UTF-8 bytes and one LF."""
    expected = _measure(value)
    encoder = json.JSONEncoder(ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(',', ':'))
    chunks: list[bytes] = []
    size = 1
    for chunk in encoder.iterencode(value):
        raw = chunk.encode('ascii')
        size += len(raw)
        if size > PLAN_MAX_BYTES:
            raise ShardCairnError('output_size', 'Canonical JSON exceeds the byte limit.', exit_code=5)
        chunks.append(raw)
    if size != expected:
        raise ShardCairnError('internal', 'Canonical byte-size invariant failed.', exit_code=70)
    chunks.append(b'\n')
    return b''.join(chunks)


def canonical_manifest_bytes(manifest: Manifest) -> bytes:
    from .manifest import manifest_to_dict
    data = manifest_to_dict(manifest)
    data['setups'].sort(key=lambda setup: setup['id'])
    for unit in data['units']:
        unit['setup_ids'].sort()
    return canonical_bytes(data)


def sha256_bytes(data: bytes) -> str:
    if type(data) is not bytes:
        raise ShardCairnError('input_type', 'Hash input must be immutable bytes.')
    return hashlib.sha256(data).hexdigest()


def manifest_sha256(manifest: Manifest) -> str:
    return sha256_bytes(canonical_manifest_bytes(manifest))
