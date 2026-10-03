"""Test the installed-origin guard without recursively running package qualification."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


_spec=importlib.util.spec_from_file_location('package_smoke',Path(__file__).resolve().parents[1]/'tools/package_smoke.py')
smoke=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)


class InstalledOriginTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='shardcairn-origin-')
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name).resolve()
        self.environment=self.root/'environment'
        self.environment.mkdir()

    def package(self,directory):
        package=directory/'shardcairn'
        package.mkdir(parents=True)
        (package/'__init__.py').write_text('',encoding='ascii')
        return directory

    def alias(self,alias,target):
        if os.name=='nt':
            # Directory junctions do not require Windows symlink privileges.
            subprocess.run(['cmd','/c','mklink','/J',str(alias),str(target)],check=True,capture_output=True)
        else:
            alias.symlink_to(target,target_is_directory=True)
        return alias

    def check(self,environment,directory):
        environment_vars=dict(os.environ)
        environment_vars.pop('PYTHONHOME',None)
        environment_vars['PYTHONPATH']=str(directory)
        return subprocess.run([sys.executable,'-c',smoke.installed_origin_check(environment)],
                              cwd=self.root,env=environment_vars,text=True,capture_output=True)

    def assertAccepted(self,environment,directory):
        result=self.check(environment,directory)
        self.assertEqual(result.returncode,0,result.stderr)

    def assertRejected(self,environment,directory):
        result=self.check(environment,directory)
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn('AssertionError',result.stderr)

    def test_accepts_package_inside_environment(self):
        self.assertAccepted(self.environment,self.package(self.environment/'lib'))

    def test_accepts_canonical_import_for_aliased_environment(self):
        alias=self.alias(self.root/'alias',self.environment)
        self.assertAccepted(alias,self.package(self.environment/'lib'))

    def test_accepts_aliased_import_for_canonical_environment(self):
        self.package(self.environment/'lib')
        alias=self.alias(self.root/'alias',self.environment)
        self.assertAccepted(self.environment,alias/'lib')

    def test_rejects_environment_prefix_sibling(self):
        outside=self.package(self.root/'environment-sibling'/'lib')
        self.assertRejected(self.environment,outside)

    def test_rejects_source_import_outside_environment(self):
        outside=self.package(self.root/'source'/'src')
        self.assertRejected(self.environment,outside)

    def test_rejects_link_inside_environment_to_outside_package(self):
        outside=self.package(self.root/'source'/'src')
        alias=self.alias(self.environment/'lib',outside)
        self.assertRejected(self.environment,alias)
