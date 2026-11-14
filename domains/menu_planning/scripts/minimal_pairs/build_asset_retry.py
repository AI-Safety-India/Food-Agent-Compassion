"""Prepare a separately recorded startup fix; no model requests are repeated."""
from pathlib import Path
import base64, gzip, hashlib

code_dir = Path(__file__).resolve().parent
out = code_dir.parents[3] / 'results/rq2/minimal_pairs_v3/transport'
source = (code_dir / 'prepare_assets.py').read_text()
source = source.replace(", 'generation_config.json'", '')
(code_dir / 'prepare_assets_v2.py').write_text(source, encoding='utf-8', newline='\n')
source = (code_dir / 'job_supervisor.py').read_text().replace("['prepare', 'extract']", "['prepare2', 'extract']")
source = source.replace("args.stage == 'prepare'", "args.stage == 'prepare2'").replace("'prepare_assets.py'", "'prepare_assets_v2.py'")
(code_dir / 'job_supervisor_v2.py').write_text(source, encoding='utf-8', newline='\n')
for i, name in enumerate(['prepare_assets_v2.py', 'job_supervisor_v2.py']):
    data = (code_dir / name).read_bytes()
    payload = base64.b64encode(gzip.compress(data, mtime=0)).decode()
    sha = hashlib.sha256(data).hexdigest()
    script = f'''from pathlib import Path
import base64, gzip, hashlib, json
data = gzip.decompress(base64.b64decode({payload!r}))
p = Path('/marimo/domains/menu_planning/scripts/minimal_pairs/{name}')
assert hashlib.sha256(data).hexdigest() == {sha!r}
if p.exists():
    assert p.read_bytes() == data
else:
    with p.open('xb') as f: f.write(data)
print(json.dumps({{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}}))
'''
    (out / f'asset_retry_upload_{i}.py').write_text(script, encoding='utf-8', newline='\n')
launch = (out / 'prepare.py').read_text()
launch = launch.replace('minimal_pairs_prepare', 'minimal_pairs_prepare2')
launch = launch.replace("'prepare'", "'prepare2'").replace('job_supervisor.py', 'job_supervisor_v2.py')
(out / 'prepare2.py').write_text(launch, encoding='utf-8', newline='\n')
progress = (out / 'progress.py').read_text().replace("['prepare', 'extract']", "['prepare', 'prepare2', 'extract']")
(out / 'progress2.py').write_text(progress, encoding='utf-8', newline='\n')
print('Created versioned preparation fix and transports; no inference.')
