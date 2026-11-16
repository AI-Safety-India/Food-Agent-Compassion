"""Build explicit hash-checked secret-free uploads and cm durable launch."""
import base64,gzip,hashlib,json
from pathlib import Path
repo=Path(__file__).resolve().parents[4]
root=repo/'results/rq2/minimal_pairs_v3';code=Path(__file__).parent
remote='/marimo/results/rq2/minimal_pairs_v3';rc='/marimo/domains/menu_planning/scripts/minimal_pairs'
out=root/'transport/stage3';out.mkdir(parents=True,exist_ok=True)
sources=[(code/n,rc+'/'+n) for n in ['steer_minimal_pairs.py','stage3_supervisor.py']]
sources += [(root/n,remote+'/'+n) for n in ['STEERING_PREREG.md','stage3/plan/PLAN.json','stage3/plan/directions.npz','stage3/plan/inputs.json','stage3/plan/jobs.json']]
manifest=[];commands=[]
for source,target in sources:
    data=source.read_bytes();digest=hashlib.sha256(data).hexdigest()
    manifest.append(dict(source=str(source),target=target,sha256=digest,bytes=len(data)))
    encoded=base64.b64encode(gzip.compress(data,mtime=0)).decode()
    chunks=[encoded[i:i+14000] for i in range(0,len(encoded),14000)]
    for part,chunk in enumerate(chunks):
        script=f'''from pathlib import Path
import base64,gzip,hashlib,json
folder=Path({remote!r})/'stage3/upload_parts'/{digest!r}
folder.mkdir(parents=True,exist_ok=True)
p=folder/{str(part)!r}
if p.exists(): assert p.read_text()=={chunk!r}
else:
    with p.open('x') as f:f.write({chunk!r})
if all((folder/str(i)).exists() for i in range({len(chunks)})):
    data=gzip.decompress(base64.b64decode(''.join((folder/str(i)).read_text() for i in range({len(chunks)}))))
    assert hashlib.sha256(data).hexdigest()=={digest!r}
    target=Path({target!r});target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists(): assert target.read_bytes()==data
    else:
        with target.open('xb') as f:f.write(data)
    print('VERIFIED',{target!r},{digest!r})
else: print('FRAGMENT',{target!r},{part})
'''
        dest=out/f'upload_{len(commands):03d}.py';dest.write_text(script,encoding='utf-8',newline='\n');commands.append(str(dest))
(out/'UPLOAD_MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
(out/'commands.json').write_text(json.dumps(commands),encoding='utf-8')
checks={m['target']:m['sha256'] for m in manifest}
cell=f'''def launch_minimal_pairs_stage3():
    import hashlib,json,os,subprocess,sys
    from pathlib import Path
    root=Path({remote!r});job=root/'jobs/stage3'
    for path,digest in {checks!r}.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest
    assert not (root/'stage3/run').exists(),'Existing run: inspect; never relaunch'
    job.mkdir(parents=True,exist_ok=True)
    if (job/'launch_intent.json').exists():
        print('Already submitted; inspect PID/log; no duplicate launch');return
    with (job/'launch_intent.json').open('x') as f:
        json.dump({{'free_confirmed':True,'paid_authorized':False,'prereg_commit':'61577bd','plan_commit':'011b487'}},f)
        f.flush();os.fsync(f.fileno())
    with (job/'worker.log').open('ab') as log:
        proc=subprocess.Popen([sys.executable,'-B','-u',{rc+'/stage3_supervisor.py'!r}],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    with (job/'pid.json').open('x') as f:json.dump({{'pid':proc.pid}},f)
    print('STAGE3_STARTED',proc.pid)
launch_minimal_pairs_stage3()
'''
(out/'launch.py').write_text(f'''import marimo._code_mode as cm
async with cm.get_context() as ctx:
    assert not any(c.name=='minimal_pairs_stage3' for c in ctx.cells),'Inspect existing cell; no duplicate'
    cid=ctx.create_cell({cell!r},name='minimal_pairs_stage3',hide_code=False)
    print('Created cell',cid)
    ctx.run_cell(cid)
''',encoding='utf-8',newline='\n')
(out/'progress.py').write_text(f'''from pathlib import Path
root=Path({remote!r})
for name in ['jobs/stage3/pid.json','jobs/stage3/exit.json','stage3/run/SANITY.json','stage3/run/progress.json','stage3/WORKER_FAILED.json','stage3/run/COMPLETE.json']:
    p=root/name
    if p.exists(): print(name,p.read_text())
p=root/'jobs/stage3/worker.log'
if p.exists():
    with p.open('rb') as f:
        f.seek(max(0,p.stat().st_size-3000));print(f.read().decode(errors='replace'))
''',encoding='utf-8',newline='\n')
print('Built',len(commands),'upload fragments and durable launch/progress commands')
