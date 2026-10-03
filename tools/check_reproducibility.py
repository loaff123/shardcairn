"""Cross-platform canonical fixture check. --write is a maintainer-only refresh."""
from pathlib import Path
import argparse
import hashlib
import json
import tempfile

from shardcairn import load_manifest,plan,export
from shardcairn.exporter import write_plan
ROOT=Path(__file__).resolve().parents[1]
GOLDEN=ROOT/'tests/reproducibility-golden.json'


def snapshot():
    from shardcairn import canonical_manifest_bytes
    result={}
    fixtures=['setup-reuse-four','local-pair-trap','all-zero','integer-boundary','unused-registry','opaque-unicode']
    for name in fixtures:
        source=ROOT/'benchmarks/original-synthetic-v1/manifests'/f'{name}.json'
        # Fixture hierarchy is part of the frozen development dataset.
        if name=='opaque-unicode':source=ROOT/'examples/opaque-unicode.json'
        if not source.exists():
            matches=list((ROOT/'benchmarks/original-synthetic-v1').rglob(name+'.json'))
            if len(matches)!=1:raise RuntimeError('Frozen fixture missing')
            source=matches[0]
        m=load_manifest(source);p=plan(m)
        records={'manifest':hashlib.sha256(canonical_manifest_bytes(m)).hexdigest(),'plan':hashlib.sha256(p.to_bytes()).hexdigest()}
        with tempfile.TemporaryDirectory(prefix='shardcairn-repro-') as td:
            root=Path(td)
            write_plan(m,p,root/'plan')
            export(m,p,root/'export')
            for kind in ['plan','export']:
                for path in sorted((root/kind).iterdir()):
                    records[kind+'/'+path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
        result[name]=records
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--write',action='store_true');args=parser.parse_args()
    actual=snapshot()
    if args.write:
        GOLDEN.write_text(json.dumps(actual,sort_keys=True,indent=2)+'\n',encoding='ascii')
    else:
        expected=json.loads(GOLDEN.read_text(encoding='ascii'))
        if actual!=expected:raise SystemExit('Canonical fixture bytes differ from the versioned golden records')
    print('Canonical manifests, plans, reports, JSON exports, and markers match')

if __name__=='__main__':main()
