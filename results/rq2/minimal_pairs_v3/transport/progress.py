from pathlib import Path
import json
root = Path('/marimo/results/rq2/minimal_pairs_v3')
for stage in ['prepare', 'extract']:
    job = root / 'jobs' / stage
    for name in ['pid.json', 'exit.json']:
        p = job / name
        if p.exists(): print(stage, name, p.read_text())
    log = job / 'worker.log'
    if log.exists():
        with log.open('rb') as f:
            f.seek(max(0, log.stat().st_size - 5000))
            print(stage, 'LOG_TAIL', f.read().decode(errors='replace'))
for name in ['preparation/snapshot_manifest.json', 'extraction/progress.json', 'extraction/environment.json', 'extraction/integrity.json']:
    p = root / name
    if p.exists(): print(name, p.read_text())
print('COMPLETE', (root / 'extraction/COMPLETE.json').exists())
