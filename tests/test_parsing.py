"""Strict lexical and bounded local-read regression tests."""
import json
from pathlib import Path
import tempfile
import unittest

from shardcairn.errors import ShardCairnError
from shardcairn.parsing import MAX_SAFE_INTEGER, parse_json, read_bytes


class ParsingTests(unittest.TestCase):
    def parse(self, data):
        return parse_json(data, 16 * 1024 * 1024)

    def rejected(self, data, exit_code=3):
        with self.assertRaises(ShardCairnError) as caught:
            self.parse(data)
        self.assertEqual(caught.exception.exit_code, exit_code)
        self.assertLessEqual(len(str(caught.exception).encode('utf-8')), 4096)

    def test_unicode_scalar_and_integer_boundaries(self):
        self.assertEqual(self.parse(b'[0,9007199254740991,"\\ud83d\\ude00"]'), [0, MAX_SAFE_INTEGER, '\U0001f600'])
        self.assertEqual(self.parse('"é"'.encode()), 'é')

    def test_no_floating_numeric_or_negative_tokens(self):
        for token in [b'1.0', b'1e0', b'1E+1', b'-0', b'-1', b'NaN', b'Infinity', b'-Infinity', b'9007199254740992', b'9' * 10000]:
            with self.subTest(token=token[:20]):
                self.rejected(token)

    def test_boolean_null_remain_json_values_for_plan_flags(self):
        self.assertEqual(self.parse(b'[true,false,null]'), [True, False, None])

    def test_duplicate_keys_at_any_depth(self):
        for raw in [b'{"x":1,"x":2}', b'{"x":{"a":1,"a":2}}', b'{"\\u0061":1,"a":2}']:
            self.rejected(raw)

    def test_rejects_invalid_encoding_and_surrogates(self):
        for raw in [b'"\xff"', b'"\xed\xa0\x80"', b'"\\ud800"', b'{"\\udfff":1}', b'"\\ud800x\\udc00"']:
            self.rejected(raw)

    def test_strict_json_grammar(self):
        for raw in [b'', b'{} {}', b'[1,]', b'{"x":01}', b'{"x":1 /*comment*/}', b'\xef\xbb\xbf{}', b'"x\n"']:
            self.rejected(raw)

    def test_nesting_boundary_ignores_escaped_structure(self):
        self.assertEqual(self.parse(b'[' * 16 + b'0' + b']' * 16), [[[[[[[[[[[[[[[[0]]]]]]]]]]]]]]]])
        self.rejected(b'[' * 17 + b'0' + b']' * 17, 5)
        self.assertEqual(self.parse(b'"[[[\\\"{{{"'), '[[["{{{')

    def test_token_boundary(self):
        # [ plus 999,999 numbers plus 999,998 commas plus ] = 1,999,999.
        self.assertEqual(len(self.parse(b'[' + b'0,' * 999998 + b'0]')), 999999)
        self.rejected(b'[' + b'0,' * 999999 + b'0]', 5)

    def test_byte_limit_checked_for_input_and_file(self):
        self.assertEqual(read_bytes(b'1234', 4), b'1234')
        with self.assertRaises(ShardCairnError) as caught:
            read_bytes(b'12345', 4)
        self.assertEqual(caught.exception.exit_code, 5)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input'
            path.write_bytes(b'12345')
            with self.assertRaises(ShardCairnError) as caught:
                read_bytes(path, 4)
            self.assertEqual(caught.exception.exit_code, 5)
            self.assertEqual(path.read_bytes(), b'12345')
            self.assertEqual(read_bytes(str(path), 5), b'12345')

    def test_io_error_does_not_reveal_path(self):
        path = '/nonexistent/private-secret-selector'
        with self.assertRaises(ShardCairnError) as caught:
            read_bytes(path, 99)
        self.assertEqual(caught.exception.exit_code, 4)
        self.assertNotIn(path, str(caught.exception))

    def test_errors_are_sanitized_and_bounded(self):
        error = ShardCairnError('bad\x1bcode', 'é\n\x1b\ud800' * 10000, '/' + 'é\x00' * 10000)
        rendered = str(error)
        self.assertLessEqual(len(rendered.encode()), 4096)
        self.assertNotIn('\x1b', rendered)
        self.assertNotIn('\n', rendered)
        self.assertLessEqual(len(error.pointer.encode()), 512)


if __name__ == '__main__':
    unittest.main()
