"""One durable Stage 3 subprocess; never retry model work automatically."""
import json, os, subprocess, sys, traceback
from pathlib import Path
ROOT=Path('/marimo/results/rq2/minimal_pairs_v3')
job=ROOT/'jobs/stage3'
try:
    result=subprocess.run([sys.executable,'-B','-u',str(Path(__file__).with_name('steer_minimal_pairs.py')),
        'worker','--root',str(ROOT),'--free-runtime-confirmed'],env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
    status={'returncode':result.returncode,'status':'complete' if result.returncode==0 else 'failed'}
except BaseException:
    status={'returncode':1,'status':'failed','traceback':traceback.format_exc()}
with (job/'exit.json').open('x') as f:
    json.dump(status,f,indent=2);f.flush();os.fsync(f.fileno())
sys.exit(status['returncode'])
