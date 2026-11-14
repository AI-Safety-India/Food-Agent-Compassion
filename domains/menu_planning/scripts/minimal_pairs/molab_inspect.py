"""Read-only scratchpad inspection; no model loading, writes, or inference."""
import marimo._code_mode as cm
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

ctx = cm.get_context()
print('NOTEBOOK', json.dumps([{'id': c.id, 'name': c.name, 'status': str(c.status)} for c in ctx.cells]))
print('PYTHON', sys.executable, sys.version)
print('CWD', str(Path.cwd()))
versions = {}
for name in ('torch', 'transformers', 'numpy', 'accelerate', 'safetensors', 'marimo'):
    try:
        versions[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        versions[name] = None
print('VERSIONS', json.dumps(versions))
print('GPU', subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total,memory.used', '--format=csv,noheader'], capture_output=True, text=True).stdout)
print('GPU_PROCESSES', subprocess.run(['nvidia-smi', '--query-compute-apps=pid,process_name,used_memory', '--format=csv,noheader'], capture_output=True, text=True).stdout)
roots = {Path.home() / '.cache/huggingface/hub', Path('/home/marimo/.cache/huggingface/hub'), Path('/marimo/.cache/huggingface/hub')}
revision = 'c202236235762e1c871ad0ccb60c8ee5ba337b9a'
for cache in sorted(roots):
    snapshot = cache / 'models--Qwen--Qwen3.5-9B/snapshots' / revision
    if snapshot.is_dir():
        print('SNAPSHOT', str(snapshot))
        print('FILES', json.dumps([{'name': p.relative_to(snapshot).as_posix(), 'size': p.stat().st_size} for p in snapshot.rglob('*') if p.is_file()]))
        config = json.loads((snapshot / 'config.json').read_text())
        print('CONFIG', json.dumps(config))
print('NEW_OUTPUT_EXISTS', (Path.cwd() / 'results/rq2/minimal_pairs_v3').exists())
