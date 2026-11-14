from pathlib import Path
import json, os, shutil
for base in [Path('/marimo'), Path('/home/marimo'), Path.home()]:
    if base.is_dir():
        print('DIRECTORY', str(base), json.dumps([p.name for p in base.iterdir() if not p.name.startswith('.')]))
for key in ['HF_HOME', 'HF_HUB_CACHE', 'TRANSFORMERS_CACHE']:
    value = os.environ.get(key)
    print('CACHE_SETTING', key, value)
    if value and Path(value).is_dir():
        print('CACHE_ENTRIES', json.dumps([p.name for p in Path(value).iterdir()]))
print('DISK', shutil.disk_usage('/marimo')._asdict())
old = Path('/marimo/sf_capacity_v11_preparation_2026_11_14/runtime_preparation.json')
if old.is_file():
    record = json.loads(old.read_text())
    print('PRIOR_MODEL_PATH', record.get('local_model_path'))
