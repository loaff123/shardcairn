"""CLI boundaries and bounded diagnostics; no subprocess in product code."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shardcairn.cli import main
from shardcairn.canonical import canonical_bytes
from shardcairn.manifest import manifest_to_dict
from test_exporter import sample


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.manifest,self.plan=sample()
        self.manifest_path=self.root/'manifest.json'; self.manifest_path.write_bytes(canonical_bytes(manifest_to_dict(self.manifest)))
        self.plan_path=self.root/'input-plan.json'; self.plan_path.write_bytes(self.plan.to_bytes())

    def run_cli(self,*args):
        output=io.StringIO(); error=io.StringIO()
        with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error): code=main(list(map(str,args)))
        return code,output.getvalue(),error.getvalue()

    def test_plan_and_export_success_summaries(self):
        with patch('shardcairn.cli.plan',return_value=self.plan):
            code,out,err=self.run_cli('plan',self.manifest_path,'--out-dir',self.root/'planned')
        self.assertEqual((code,err),(0,'')); self.assertEqual(json.loads(out)['command'],'plan')
        code,out,err=self.run_cli('export',self.manifest_path,self.plan_path,'--out-dir',self.root/'exported')
        self.assertEqual((code,err),(0,'')); self.assertEqual(json.loads(out)['format'],'json')
        self.assertLessEqual(len(out.encode()),16384)

    def test_verification_reports_valid_and_required_unproved(self):
        code,out,err=self.run_cli('verify',self.manifest_path,self.plan_path)
        self.assertEqual(code,0); self.assertEqual(json.loads(out)['result'],'valid')
        code,out,err=self.run_cli('verify',self.manifest_path,self.plan_path,'--require-optimal')
        self.assertEqual(code,6); self.assertEqual(json.loads(out)['result'],'valid')

    def test_verify_missing_and_invalid_input_emit_closed_reports(self):
        for source in (self.root/'missing',self.root/'bad'):
            if source.name=='bad': source.write_text('{"bad":true}')
            code,out,err=self.run_cli('verify',source,self.plan_path)
            self.assertEqual(code,4 if source.name=='missing' else 3)
            report=json.loads(out); self.assertEqual(report['result'],'invalid')
            self.assertEqual(report['checks'],dict(coverage=None,arithmetic=None,baseline=None))
            self.assertLessEqual(len(err.encode()),4096)

    def test_usage_is_bounded_sanitized_and_no_output_created(self):
        cases=[[],['--surprise'],['plan',str(self.manifest_path),'--out-dir',str(self.root/'bad'),'--work-limit','1e2'],['plan',str(self.manifest_path),'--out-dir',str(self.root/'bad'),'--work-limit','-0'],['verify',str(self.manifest_path),str(self.plan_path),'--audit-visits','1'],['export',str(self.manifest_path),str(self.plan_path),'--out-dir',str(self.root/'bad'),'--format','no'],['--'+ '\x1b'+ 'x'*10000]]
        for args in cases:
            with self.subTest(args=args[:1]):
                code,out,err=self.run_cli(*args)
                self.assertEqual(code,2); self.assertEqual(out,''); self.assertLessEqual(len(err.encode()),4096); self.assertNotIn('\x1b',err)
        self.assertFalse((self.root/'bad').exists())

    def test_output_failure_never_emits_success(self):
        code,out,err=self.run_cli('export',self.manifest_path,self.plan_path,'--out-dir',self.root)
        self.assertEqual(code,4); self.assertEqual(out,'')

    def test_internal_failure_is_bounded_and_has_no_valid_claim(self):
        with patch('shardcairn.cli.plan',side_effect=RuntimeError('private details')):
            code,out,err=self.run_cli('plan',self.manifest_path,'--out-dir',self.root/'bad')
        self.assertEqual(code,70); self.assertEqual(out,''); self.assertNotIn('private details',err)

    def test_help_and_version(self):
        for flag in ('--help','--version'):
            code,out,err=self.run_cli(flag)
            self.assertEqual((code,err),(0,'')); self.assertTrue(out); self.assertLessEqual(len(out.encode()),16384)

class CanonicalStdoutTests(unittest.TestCase):
    def test_windows_text_translation_cannot_change_canonical_bytes(self):
        from shardcairn.cli import _output
        raw=io.BytesIO()
        text=io.TextIOWrapper(raw,encoding='ascii',newline='\r\n')
        with patch('shardcairn.cli.sys.stdout',text):
            _output(b'{"x":1}\n')
        self.assertEqual(raw.getvalue(),b'{"x":1}\n')
        text.detach()
