"""Prepare non-inference runtime validation against previously verified hashes."""
import json
from pathlib import Path

repo = Path(__file__).resolve().parents[4]
root = repo / 'results/rq2/minimal_pairs_v3'
old = json.loads((repo / 'results/rq2/askmodel_v11/execution_freeze_2026_11_14/runtime_preparation.json').read_text())
uploads = json.loads((root / 'transport/UPLOAD_MANIFEST.json').read_text())
source = f'''from pathlib import Path
import json, hashlib, importlib.metadata, subprocess, sys
import torch
root = Path('/marimo/results/rq2/minimal_pairs_v3')
manifest_path = root / 'preparation/snapshot_manifest.json'
manifest = json.loads(manifest_path.read_text())
prior = {old['model_files']!r}
assert all(prior[k] == v for k,v in manifest['files'].items()), 'Pinned assets differ from earlier verified hashes'
for item in {uploads!r}:
    assert hashlib.sha256(Path(item['target']).read_bytes()).hexdigest() == item['sha256'], 'Upload hash mismatch'
versions = {{name: importlib.metadata.version(name) for name in ['torch','transformers','numpy','accelerate']}}
assert versions['torch'].split('+')[0] == '2.11.0' and versions['transformers'] == '5.14.1' and versions['numpy'] == '2.4.6'
assert torch.cuda.is_available() and torch.cuda.is_bf16_supported()
assert torch.cuda.device_count() == 1
target = root / 'preparation/remote_tokenizer_check'
if not target.exists():
    result = subprocess.run([sys.executable,'-B','/marimo/domains/menu_planning/scripts/minimal_pairs/extract_minimal_pairs.py','preflight',
        '--prompts',str(root/'inputs/prompts.jsonl'),'--pairs',str(root/'inputs/pairs.json'),
        '--tokenizer',manifest['snapshot'],'--output',str(target),'--whitespace-boundary'],capture_output=True,text=True)
    with (root/'preparation/tokenizer_stdout.log').open('x') as f: f.write(result.stdout+'\\n'+result.stderr)
    assert result.returncode == 0, result.stderr[-2000:]
check = json.loads((target/'preflight.json').read_text())
assert check['prompts'] == 1002 and len(check['sample']) == 30
readiness = {{'versions': versions, 'gpu': torch.cuda.get_device_name(), 'bf16_supported': True,
    'assets_match_prior': len(manifest['files']), 'snapshot_manifest': manifest,
    'snapshot_manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    'tokenizer_check': {{'prompts':check['prompts'],'sample':len(check['sample']),'template':check['template_sha256']}},
    'extraction_core_sha256':check['sources']['script'],'weights_loaded': False,'model_passes':0,
    'free_confirmed_by_user':True,'paid_resources_authorized':False}}
destination = root/'preparation/RUNTIME_READY.json'
if destination.exists():
    assert json.loads(destination.read_text()) == readiness
else:
    with destination.open('x') as f: json.dump(readiness,f,indent=2)
print('READINESS_JSON',json.dumps(readiness))
'''
target = root / 'transport/readiness.py'
with target.open('x', encoding='utf-8', newline='\n') as f:
    f.write(source)
