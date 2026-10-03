"""Build and qualify wheel + extracted-sdist installs, offline and outside source cwd."""
from pathlib import Path
import hashlib
import json
import re
import os
import subprocess
import shutil
import sys
import tarfile
import tempfile
import venv

ROOT=Path(__file__).resolve().parents[1]


def run(command,cwd,env=None,capture_all=False):
    clean=dict(os.environ)
    clean.pop('PYTHONPATH',None)
    clean.pop('PYTHONHOME',None)
    clean['SOURCE_DATE_EPOCH']='315532800'
    if env:clean.update(env)
    completed=subprocess.run(command,cwd=cwd,env=clean,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    if completed.returncode:
        raise RuntimeError(f'Command failed ({completed.returncode}): {completed.stdout[-4000:]} {completed.stderr[-4000:]}')
    return completed.stdout + completed.stderr if capture_all else completed.stdout


def build(source,destination,kind):
    run([sys.executable,'-c',f'from setuptools.build_meta import build_{kind}; build_{kind}({str(destination)!r})'],source)
    return next(destination.glob('*.whl' if kind=='wheel' else '*.tar.gz'))


def qualify(wheel,work,fixture,test_tools):
    env=work/'environment'
    venv.EnvBuilder(with_pip=True).create(env)
    python=env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    unrelated=work/'unrelated';unrelated.mkdir()
    run([str(python),'-m','pip','install','--no-index','--no-deps',str(wheel)],unrelated)
    result=run([str(python),'-c',"import importlib.resources as r, shardcairn; from shardcairn import load_manifest, plan, verify; assert len(list(r.files('shardcairn').joinpath('schemas').iterdir()))==7; assert r.files('shardcairn').joinpath('py.typed').is_file(); print(shardcairn.__version__)"],unrelated)
    output=unrelated/'plan'
    run([str(python),'-m','shardcairn','plan',str(fixture),'--out-dir',str(output)],unrelated)
    verified=json.loads(run([str(python),'-m','shardcairn','verify',str(fixture),str(output/'plan.json'),'--audit-optimal','--require-optimal'],unrelated))
    assert verified['optimality']=='audit_proved'
    run([str(python),'-m','shardcairn','export',str(fixture),str(output/'plan.json'),'--out-dir',str(unrelated/'export')],unrelated)
    entry=env/('Scripts/shardcairn.exe' if os.name=='nt' else 'bin/shardcairn')
    run([str(entry),'--help'],unrelated)
    test_environment={'PYTHONDONTWRITEBYTECODE':'1'}
    if test_tools is not None:test_environment['PYTHONPATH']=str(test_tools)
    check='import shardcairn; assert shardcairn.__file__.startswith('+repr(str(env))+')'
    run([str(python),'-c',check],unrelated,env=test_environment)
    suite=run([str(python),'-m','unittest','discover','-s',str(fixture.parents[1]/'tests'),'-v'],unrelated,env=test_environment,capture_all=True)
    match=re.search(r'Ran (\d+) tests?',suite)
    if match is None:raise RuntimeError('Installed suite count missing')
    if test_tools is not None and 'skipped=' in suite:raise RuntimeError('Installed qualification unexpectedly skipped tests')
    run([str(python),str(fixture.parents[1]/'tools/check_reproducibility.py')],unrelated,env=test_environment)
    return {'version':result.strip(),'installed_tests':int(match.group(1)),'owned_pytest_available':test_tools is not None,'wheel_sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),'optimality':verified['optimality']}


def source_inventory(root):
    """Hash the original tree without following links or entering Git internals."""
    return {str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file() and '.git' not in path.relative_to(root).parts}


def main():
    try:
        import pytest
        test_tools=Path(pytest.__file__).resolve().parent.parent
    except ImportError:
        test_tools=None
    with tempfile.TemporaryDirectory(prefix='shardcairn-packaging-') as td:
        work=Path(td)
        before=source_inventory(ROOT)
        staging=work/'source'
        shutil.copytree(ROOT,staging,ignore=shutil.ignore_patterns('.git','__pycache__','*.pyc','*.egg-info','build','dist','.pytest_cache'))
        artifacts=work/'artifacts';artifacts.mkdir()
        wheel=build(staging,artifacts,'wheel')
        sdist=build(staging,artifacts,'sdist')
        first=work/'first';first.mkdir()
        wheel_result=qualify(wheel,first,staging/'examples/setup-reuse.json',test_tools)
        extracted=work/'extracted';extracted.mkdir()
        with tarfile.open(sdist) as archive:
            # Only our freshly generated sdist is extracted; still constrain names.
            for item in archive.getmembers():
                if item.name.startswith('/') or '..' in Path(item.name).parts or item.issym() or item.islnk():
                    raise RuntimeError('Unsafe generated sdist member')
            if hasattr(tarfile,'data_filter'):
                archive.extractall(extracted,filter='data')
            else:
                archive.extractall(extracted)
        source=next(extracted.iterdir())
        rebuilt=work/'rebuilt';rebuilt.mkdir()
        second_wheel=build(source,rebuilt,'wheel')
        second=work/'second';second.mkdir()
        sdist_result=qualify(second_wheel,second,source/'examples/setup-reuse.json',test_tools)
        if source_inventory(ROOT)!=before:raise RuntimeError('Original source tree changed during packaging')
        print(json.dumps({'original_source_unchanged':True,'wheel':wheel_result,'extracted_sdist':sdist_result,'sdist_sha256':hashlib.sha256(sdist.read_bytes()).hexdigest()},sort_keys=True))

if __name__=='__main__':main()
