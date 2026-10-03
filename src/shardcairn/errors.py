"""Small, bounded domain errors without raw input or source-line disclosure."""
from __future__ import annotations

import unicodedata


def _bounded_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return 'Invalid value'
    pieces: list[str] = []
    used = 0
    for character in value:
        if unicodedata.category(character).startswith('C') or character in '\u2028\u2029':
            character = '?'
        width = len(character.encode('utf-8'))
        if used + width > limit:
            break
        pieces.append(character)
        used += width
    return ''.join(pieces)


class ShardCairnError(Exception):
    """A stable short code, sanitized message/pointer, and CLI exit category."""

    def __init__(self, code: str, message: str, pointer: str = '', exit_code: int = 3):
        self.code = _bounded_text(code, 64)
        self.message = _bounded_text(message, 2048)
        self.pointer = _bounded_text(pointer, 512)
        self.exit_code = exit_code if type(exit_code) is int and exit_code in (2, 3, 4, 5, 6, 70) else 70
        location = f' at {self.pointer}' if self.pointer else ''
        super().__init__(f'{self.code}{location}: {self.message}')
