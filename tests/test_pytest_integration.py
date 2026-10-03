"""Development-only subprocess execution of this repository's owned fixture."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from shardcairn.manifest import load_manifest, PlanOptions
from shardcairn.planner import plan
from shardcairn.exporter import export, verify_directory


class OwnedPytestIntegration(unittest.TestCase):
    def test_owned_argfiles_coverage_order_and_setup_activation(self):
        if importlib.util.find_spec('pytest') is None:
            self.skipTest('development-only integration requires pytest>=8.2')
        import pytest
        if tuple(map(int,pytest.__version__.split('.')[:2])) < (8,2):
            self.skipTest('development-only integration requires pytest>=8.2')
        fixtures=Path(__file__).resolve().parents[1]/'integration'
        self.assertTrue((fixtures/'manifest.json').is_file(),'owned manifest fixture is required')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            repository=root/'repository'
            shutil.copytree(fixtures,repository,ignore=shutil.ignore_patterns('__pycache__','.pytest_cache'))
            manifest=load_manifest(repository/'manifest.json')
            document=plan(manifest,PlanOptions(mode='exact'))
            chosen=document.to_dict()['assignment']
            exports=root/'exports'
            export(manifest,document,exports,'pytest-argfile')
            verify_directory(exports)
            coverage=[]
            activation_count=0
            for shard in chosen:
                log=root/f"events-{shard['index']}.jsonl"
                env={'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1','PYTHONDONTWRITEBYTECODE':'1',
                     'PYTHONPATH':os.pathsep.join(sys.path),'SHARDCAIRN_OWNED_LOG':str(log)}
                if 'SYSTEMROOT' in os.environ:
                    env['SYSTEMROOT']=os.environ['SYSTEMROOT']
                command=[sys.executable,'-m','pytest','-c','pytest.ini','-p','no:cacheprovider',
                         '--confcutdir',str(repository),'-q','@'+str(exports/f"shard-{shard['index']:03d}.args")]
                run=subprocess.run(command,cwd=repository,env=env,text=True,capture_output=True,timeout=30)
                self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                events=[json.loads(line) for line in log.read_text().splitlines()]
                starts=[event['nodeid'] for event in events if event['kind']=='start']
                self.assertEqual(starts,shard['selectors'])
                coverage.extend(starts)
                setups=[event for event in events if event['kind']=='setup']
                teardowns=[event for event in events if event['kind']=='teardown']
                self.assertEqual(len(setups),len(shard['setup_ids']))
                self.assertEqual(len(teardowns),len(setups))
                self.assertEqual({event['setup'] for event in setups},set(shard['setup_ids']))
                activation_count+=len(setups)
                for unit in manifest.units:
                    if unit.id in shard['unit_ids']:
                        offset=starts.index(unit.selectors[0])
                        self.assertEqual(starts[offset:offset+len(unit.selectors)],list(unit.selectors))
            expected=[selector for unit in manifest.units for selector in unit.selectors]
            self.assertCountEqual(coverage,expected)
            self.assertEqual(len(coverage),len(set(coverage)))
            self.assertEqual(activation_count,document.to_dict()['metrics']['activated_setup_occurrences'])
