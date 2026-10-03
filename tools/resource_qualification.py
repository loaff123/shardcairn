"""Development-only resource measurement. Never measures scheduling estimates.

Run fixture/create followed by one separate process per baseline/verify/export.
Results go to caller-chosen paths; no host paths or identities enter report JSON.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time


def fixture(path):
    # Simultaneously reaches every count cap while fitting the 16 MiB byte cap.
    setups = [{'id':f's{s:04d}','cost_ms':s%7} for s in range(2048)]
    units = []
    for i in range(10000):
        selectors = [f'tests/test_resource_{i:05d}_{m}.py::test_' + 'a'*112 for m in range(5)]
        refs = [f's{(i*17+r)%2048:04d}' for r in range(64)]
        units.append({'id':f'u{i:05d}', 'selectors':selectors, 'exclusive_cost_ms':i%11, 'setup_ids':refs})
    doc = {'schema_version':1, 'timing_basis':'exclusive-additive-once-per-shard-v1',
           'shards':64,'setups':setups,'units':units}
    data = json.dumps(doc,separators=(',',':'),sort_keys=True).encode()+b'\n'
    if len(data)>16*1024*1024:raise RuntimeError('Stress fixture exceeds input cap')
    Path(path).write_bytes(data)
    return {'units':10000,'selectors':50000,'setups':2048,'references_per_unit':64,
            'total_references':640000,'shards':64,'manifest_bytes':len(data)}


def fixture_unicode(path):
    units=[{'id':f'U{i:04d}','selectors':[f'{i:04d}'+chr(0x1f600)*4092],
            'exclusive_cost_ms':1,'setup_ids':[]} for i in range(1000)]
    doc={'schema_version':1,'timing_basis':'exclusive-additive-once-per-shard-v1',
         'shards':64,'setups':[],'units':units}
    raw=json.dumps(doc,ensure_ascii=False,separators=(',',':')).encode()
    cap=16*1024*1024
    data=raw+b' '*(cap-len(raw)-1)+b'\n'
    if len(data)!=cap:raise RuntimeError('Unicode fixture dimensions exceed cap')
    Path(path).write_bytes(data)
    return {'units':1000,'selectors':1000,'setups':0,'references_per_unit':0,
            'shards':64,'selector_scalars':4096,'manifest_bytes':len(data)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',choices=['fixture','fixture-unicode','baseline','verify','export'])
    parser.add_argument('manifest')
    parser.add_argument('--plan')
    parser.add_argument('--out')
    args=parser.parse_args()
    wall=time.perf_counter();cpu=time.process_time()
    if args.operation=='fixture':
        result=fixture(args.manifest)
    elif args.operation=='fixture-unicode':
        result=fixture_unicode(args.manifest)
    else:
        from shardcairn import load_manifest,plan,verify,export,PlanOptions
        manifest=load_manifest(args.manifest)
        if args.operation=='baseline':
            output=plan(manifest,PlanOptions(work_limit=0,local_candidates=0,exact_nodes=0))
            Path(args.out).write_bytes(output.to_bytes())
            doc=output.to_dict()
            result={'plan_bytes':len(output.to_bytes()),'work':doc['work'],'claim':doc['claim']['status']}
        elif args.operation=='verify':
            result=verify(manifest,Path(args.plan).read_bytes()).to_dict()
            if result['result']!='valid':raise RuntimeError(result)
        else:
            export(manifest,Path(args.plan).read_bytes(),args.out)
            result={'export_bytes':sum(p.stat().st_size for p in Path(args.out).iterdir())}
    elapsed=time.perf_counter()-wall;cpu=time.process_time()-cpu
    try:
        import resource
        peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak_bytes=peak if sys.platform=='darwin' else peak*1024
    except ImportError:
        peak_bytes=None
    print(json.dumps({'operation':args.operation,'elapsed_seconds':elapsed,'cpu_seconds':cpu,
                      'peak_rss_bytes':peak_bytes,'python':sys.version.split()[0],
                      'platform':sys.platform,'result':result},sort_keys=True))

if __name__=='__main__':main()
