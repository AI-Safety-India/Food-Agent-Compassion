"""Run read-only through paired scratchpad after the durable job exits."""
from pathlib import Path
import hashlib,json,urllib.parse
root=Path('/marimo/results/rq2/minimal_pairs_v3')
assert (root/'jobs/stage3_retry1/exit.json').exists(),'Worker not yet finished'
names=['stage3/run/raw.jsonl','stage3/run/ledger.jsonl','stage3/run/SANITY.json','stage3/run/environment.json',
       'stage3/run/COMPLETE.json','stage3/run/progress.json','stage3/WORKER_FAILED.json',
       'jobs/stage3/worker.log','jobs/stage3/launch_intent.json','jobs/stage3/pid.json','jobs/stage3/exit.json']
names += ['jobs/stage3_retry1/'+n for n in ['worker.log','launch_intent.json','pid.json','exit.json']]
manifest=[]
for name in names:
    p=root/name
    if p.exists():
        manifest.append(dict(target=name,bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
            url='/api/files/download?'+urllib.parse.urlencode({'path':str(p)})))
print('STAGE3_TRANSFER_MANIFEST '+json.dumps(manifest))
