"""Build secret-free marimo scratchpad commands from an explicit input allowlist."""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
CODE = REPO / 'domains/menu_planning/scripts/minimal_pairs'
OUT = REPO / 'results/rq2/minimal_pairs_v3/transport'
REMOTE = '/marimo/results/rq2/minimal_pairs_v3'
REMOTE_CODE = '/marimo/domains/menu_planning/scripts/minimal_pairs'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['upload', 'prepare', 'extract', 'progress'])
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    if args.mode == 'upload':
        sources = [(REPO.parent / 'welfare_minimal_pairs/v3/prompts.jsonl', REMOTE + '/inputs/prompts.jsonl'),
                   (REPO.parent / 'welfare_minimal_pairs/v3/pairs.json', REMOTE + '/inputs/pairs.json'),
                   (CODE.parent / 'rq2/run_rq2_gpu_pipeline.py', REMOTE_CODE + '/audited_helper.py')]
        sources += [(CODE / name, REMOTE_CODE + '/' + name) for name in ['extract_minimal_pairs.py', 'prepare_assets.py', 'job_supervisor.py']]
        payload, manifest = [], []
        for source, target in sources:
            data = source.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            payload.append({'path': target, 'sha256': sha, 'data': base64.b64encode(gzip.compress(data, mtime=0)).decode()})
            manifest.append({'source': str(source), 'target': target, 'sha256': sha, 'bytes': len(data)})
        code = f'''from pathlib import Path
import base64, gzip, hashlib, json
for item in {payload!r}:
    path = Path(item['path'])
    data = gzip.decompress(base64.b64decode(item['data']))
    assert hashlib.sha256(data).hexdigest() == item['sha256']
    if path.exists():
        assert path.read_bytes() == data, 'Existing destination differs; never overwrite'
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as f: f.write(data)
    print(json.dumps({{'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': len(data)}}))
'''
        manifest_path = OUT / 'UPLOAD_MANIFEST.json'
        manifest_text = json.dumps(manifest, indent=2)
        if manifest_path.exists():
            if manifest_path.read_text(encoding='utf-8') != manifest_text:
                raise RuntimeError('Existing upload manifest differs; preserve it')
        else:
            manifest_path.write_text(manifest_text, encoding='utf-8')
        # Keep every shell-transport argument below Windows/MSYS limits.
        for number, item in enumerate(payload):
            if len(item['data']) > 16000:
                chunks = [item['data'][i:i+16000] for i in range(0, len(item['data']), 16000)]
                for part, chunk in enumerate(chunks):
                    fragment = f'''from pathlib import Path
import base64, gzip, hashlib, json
root = Path({REMOTE + '/transport_parts/' + item['sha256']!r})
root.mkdir(parents=True, exist_ok=True)
p = root / {str(part)!r}
data = {chunk!r}
if p.exists():
    assert p.read_text() == data
else:
    with p.open('x') as f: f.write(data)
print('Verified upload fragment', {number}, {part})
if all((root / str(i)).exists() for i in range({len(chunks)})):
    complete = gzip.decompress(base64.b64decode(''.join((root / str(i)).read_text() for i in range({len(chunks)}))))
    assert hashlib.sha256(complete).hexdigest() == {item['sha256']!r}
    target = Path({item['path']!r})
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert target.read_bytes() == complete
    else:
        with target.open('xb') as f: f.write(complete)
    print(json.dumps({{'path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'bytes': len(complete)}}))
'''
                    destination = OUT / f'fragment_{number:02d}_{part:02d}.py'
                    if destination.exists() and destination.read_text(encoding='utf-8') != fragment:
                        raise RuntimeError('Existing upload fragment differs')
                    destination.write_text(fragment, encoding='utf-8', newline='\n')
            single = code.replace(repr(payload), repr([item]))
            single_path = OUT / f'upload_{number:02d}.py'
            if single_path.exists() and single_path.read_text(encoding='utf-8') != single:
                raise RuntimeError('Existing split upload differs')
            single_path.write_text(single, encoding='utf-8', newline='\n')
    elif args.mode in ('prepare', 'extract'):
        stage = args.mode
        cell = f'''def launch_minimal_pairs_{stage}():
    import hashlib, json, os, subprocess, sys
    from pathlib import Path
    root = Path({REMOTE!r})
    job = root / 'jobs' / {stage!r}
    job.mkdir(parents=True, exist_ok=True)
    if (job / 'exit.json').exists():
        print('Job already finished:', (job / 'exit.json').read_text())
        return
    if (job / 'launch_intent.json').exists():
        print('Launch already recorded. Inspect saved PID/log; do not launch again.')
        return
    with (job / 'launch_intent.json').open('x') as f:
        json.dump({{'stage': {stage!r}, 'user_confirmed_free': True, 'paid_authorized': False}}, f)
        f.flush()
        os.fsync(f.fileno())
    with (job / 'worker.log').open('ab') as log:
        process = subprocess.Popen([sys.executable, '-B', '-u', {REMOTE_CODE + '/job_supervisor.py'!r}, {stage!r}], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    with (job / 'pid.json').open('x') as f:
        json.dump({{'pid': process.pid}}, f)
    print('Started minimal-pairs {stage}, PID', process.pid, 'on the confirmed free runtime. Progress is saved on disk.')
launch_minimal_pairs_{stage}()
'''
        code = f'''import marimo._code_mode as cm
async with cm.get_context() as ctx:
    assert not any(c.name == 'minimal_pairs_{stage}' for c in ctx.cells), 'Cell exists; inspect instead of duplicating'
    cid = ctx.create_cell({cell!r}, name='minimal_pairs_{stage}', hide_code=False)
    print('Created cell', cid)
    ctx.run_cell(cid)
'''
    else:
        code = f'''from pathlib import Path
import json
root = Path({REMOTE!r})
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
'''
    target = OUT / (args.mode + '.py')
    if target.exists() and target.read_text(encoding='utf-8') != code:
        raise RuntimeError('Existing transport differs; preserve and use a new version')
    target.write_text(code, encoding='utf-8', newline='\n')
    print(target)


if __name__ == '__main__':
    main()
