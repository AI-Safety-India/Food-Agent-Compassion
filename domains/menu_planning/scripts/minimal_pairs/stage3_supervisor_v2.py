"""Preserved startup retry: explicitly add task imports under Molab safe_path."""
import json,os,subprocess,sys,traceback
from pathlib import Path
ROOT=Path('/marimo/results/rq2/minimal_pairs_v3');CODE=Path(__file__).parent
job=ROOT/'jobs/stage3_retry1'
assert json.loads((ROOT/'jobs/stage3/exit.json').read_text())['returncode']==1
assert not (ROOT/'stage3/run').exists(),'Existing model work: never retry'
try:
    result=subprocess.run([sys.executable,'-B','-u',str(CODE/'steer_minimal_pairs.py'),
        'worker','--root',str(ROOT),'--free-runtime-confirmed'],
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(CODE)+os.pathsep+os.environ.get('PYTHONPATH','')})
    status={'returncode':result.returncode,'status':'complete' if result.returncode==0 else 'failed'}
except BaseException:
    status={'returncode':1,'status':'failed','traceback':traceback.format_exc()}
with (job/'exit.json').open('x') as f:
    json.dump(status,f,indent=2);f.flush();os.fsync(f.fileno())
sys.exit(status['returncode'])
