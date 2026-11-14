from pathlib import Path
import base64,hashlib,json
repo=Path(__file__).resolve().parents[4];root=repo/'results/rq2/minimal_pairs_v3';out=root/'transport/stage3'
source=Path(__file__).with_name('stage3_supervisor_v2.py');data=source.read_bytes();digest=hashlib.sha256(data).hexdigest()
remote='/marimo/domains/menu_planning/scripts/minimal_pairs/stage3_supervisor_v2.py'
upload=f'''from pathlib import Path
import base64,hashlib,subprocess,sys,os
path=Path({remote!r});data=base64.b64decode({base64.b64encode(data).decode()!r})
assert hashlib.sha256(data).hexdigest()=={digest!r}
if path.exists():assert path.read_bytes()==data
else:
    with path.open('xb') as f:f.write(data)
check=subprocess.run([sys.executable,'-B','-c','import extract_minimal_pairs; print("IMPORT_PASS")'],env={{**os.environ,'PYTHONPATH':str(path.parent)+os.pathsep+os.environ.get('PYTHONPATH','')}},capture_output=True,text=True)
print(check.stdout,check.stderr);assert check.returncode==0
'''
(out/'retry_upload.py').write_text(upload,encoding='utf-8',newline='\n')
launch=(out/'launch.py').read_text()
launch=launch.replace('minimal_pairs_stage3','minimal_pairs_stage3_retry1').replace('jobs/stage3','jobs/stage3_retry1').replace('stage3_supervisor.py','stage3_supervisor_v2.py')
launch=launch.replace(hashlib.sha256(source.with_name('stage3_supervisor.py').read_bytes()).hexdigest(),digest)
# Verify the new supervisor both before queuing and inside the durable cell.
launch="from pathlib import Path\nimport hashlib\nassert hashlib.sha256(Path("+repr(remote)+").read_bytes()).hexdigest()=="+repr(digest)+"\n"+launch
(out/'retry_launch.py').write_text(launch,encoding='utf-8',newline='\n')
progress=(out/'progress.py').read_text().replace('jobs/stage3','jobs/stage3_retry1')
(out/'retry_progress.py').write_text(progress,encoding='utf-8',newline='\n')
print('Built startup-only retry; unchanged worker/plan')
