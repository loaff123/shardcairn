"""Actual byte-cap sentinels, without creating enormous semantic objects."""
from pathlib import Path
import tempfile
import unittest
from shardcairn.parsing import MANIFEST_MAX_BYTES, PLAN_MAX_BYTES, read_bytes
from shardcairn.errors import ShardCairnError

class ActualByteCapTests(unittest.TestCase):
    def test_actual_manifest_cap_and_one_past(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'explicit-input'
            with path.open('wb') as stream:
                stream.write(b'{}');stream.write(b' '*(MANIFEST_MAX_BYTES-2))
            self.assertEqual(len(read_bytes(path,MANIFEST_MAX_BYTES)),MANIFEST_MAX_BYTES)
            with path.open('ab') as stream:stream.write(b' ')
            with self.assertRaises(ShardCairnError) as caught:read_bytes(path,MANIFEST_MAX_BYTES)
            self.assertEqual(caught.exception.exit_code,5)
            self.assertEqual(path.stat().st_size,MANIFEST_MAX_BYTES+1)
    def test_actual_plan_cap_and_one_past(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'explicit-plan'
            with path.open('wb') as stream:
                stream.write(b'{}');stream.seek(PLAN_MAX_BYTES-1);stream.write(b' ')
            self.assertEqual(len(read_bytes(path,PLAN_MAX_BYTES)),PLAN_MAX_BYTES)
            with path.open('ab') as stream:stream.write(b' ')
            with self.assertRaises(ShardCairnError) as caught:read_bytes(path,PLAN_MAX_BYTES)
            self.assertEqual(caught.exception.exit_code,5)
