"""Bounded local reads and strict integer-only JSON decoding."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import ShardCairnError

MAX_SAFE_INTEGER = 9_007_199_254_740_991
MANIFEST_MAX_BYTES = 16 * 1024 * 1024
PLAN_MAX_BYTES = 64 * 1024 * 1024
MAX_JSON_DEPTH = 16
MAX_JSON_TOKENS = 2_000_000
_SAFE_TOKEN = str(MAX_SAFE_INTEGER)


def _limit(value: int) -> None:
    if type(value) is not int or not 0 <= value <= PLAN_MAX_BYTES:
        raise ShardCairnError('invalid_limit', 'Byte limit is outside the supported range.')


def read_bytes(source: bytes | str | Path, max_bytes: int) -> bytes:
    """Read no more than the cap plus one sentinel byte; strings denote paths."""
    _limit(max_bytes)
    if type(source) is bytes:
        if len(source) > max_bytes:
            raise ShardCairnError('input_size', 'Input exceeds the byte limit.', exit_code=5)
        return source
    if type(source) is not str and not isinstance(source, Path):
        raise ShardCairnError('input_type', 'Input must be bytes or an explicit local path.')
    chunks: list[bytes] = []
    size = 0
    try:
        with open(source, 'rb') as stream:
            while True:
                chunk = stream.read(min(65536, max_bytes - size + 1))
                size += len(chunk)
                if size > max_bytes:
                    raise ShardCairnError('input_size', 'Input exceeds the byte limit.', exit_code=5)
                if not chunk:
                    break
                chunks.append(chunk)
    except (OSError, ValueError):
        raise ShardCairnError('io', 'Cannot read the explicitly named input file.', exit_code=4) from None
    return b''.join(chunks)


def _preflight(text: str) -> None:
    """Count structural/punctuation, string, and primitive tokens before decoding."""
    index = 0
    depth = 0
    tokens = 0
    length = len(text)
    while index < length:
        character = text[index]
        if character in ' \t\r\n':
            index += 1
            continue
        tokens += 1
        if tokens > MAX_JSON_TOKENS:
            raise ShardCairnError('json_tokens', 'JSON exceeds the token limit.', exit_code=5)
        if character == '"':
            index += 1
            while index < length:
                if text[index] == '\\':
                    index += 2
                elif text[index] == '"':
                    index += 1
                    break
                else:
                    index += 1
        elif character in '[{':
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ShardCairnError('json_depth', 'JSON exceeds the nesting limit.', exit_code=5)
            index += 1
        elif character in ']}':
            depth -= 1
            index += 1
        elif character in ',:':
            index += 1
        else:
            index += 1
            while index < length and text[index] not in ' \t\r\n{}[],:"':
                index += 1


def _integer(token: str) -> int:
    # Check spelling/length before constructing any potentially large integer.
    if token.startswith('-') or len(token) > len(_SAFE_TOKEN) or (len(token) == len(_SAFE_TOKEN) and token > _SAFE_TOKEN):
        raise ShardCairnError('integer_range', 'Integer token is outside the nonnegative safe range.')
    return int(token)


def _noninteger(token: str) -> Any:
    raise ShardCairnError('integer_token', 'Only nonnegative integer number tokens are supported.')


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ShardCairnError('duplicate_key', 'Duplicate JSON object key.')
        result[key] = value
    return result


def _unicode_scalars(value: Any) -> None:
    if type(value) is str:
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ShardCairnError('unicode_scalar', 'JSON strings must contain Unicode scalar values.')
    elif type(value) is dict:
        for key, item in value.items():
            _unicode_scalars(key)
            _unicode_scalars(item)
    elif type(value) is list:
        for item in value:
            _unicode_scalars(item)


def parse_json(data: bytes, max_bytes: int) -> Any:
    """Decode strict UTF-8 JSON without floats, duplicate keys, or surrogates."""
    _limit(max_bytes)
    if type(data) is not bytes:
        raise ShardCairnError('input_type', 'JSON input must be immutable bytes.')
    if len(data) > max_bytes:
        raise ShardCairnError('input_size', 'Input exceeds the byte limit.', exit_code=5)
    try:
        text = data.decode('utf-8', errors='strict')
    except UnicodeDecodeError:
        raise ShardCairnError('invalid_utf8', 'JSON input must be valid UTF-8.') from None
    _preflight(text)
    try:
        value = json.loads(text, parse_int=_integer, parse_float=_noninteger,
                           parse_constant=_noninteger, object_pairs_hook=_object)
    except (json.JSONDecodeError, RecursionError):
        raise ShardCairnError('json_syntax', 'Input is not valid JSON.') from None
    _unicode_scalars(value)
    return value
