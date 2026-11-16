"""Record successful non-inference readiness and build a hash-checked launch."""
from pathlib import Path
import hashlib, json, subprocess, sys

repo = Path(__file__).resolve().parents[4]
root = repo / 'results/rq2/minimal_pairs_v3'
lines = (root / 'preflight/MOLAB_READINESS.txt').read_text(encoding='utf-8').splitlines()
ready = json.loads(next(line.removeprefix('READINESS_JSON ') for line in lines if line.startswith('READINESS_JSON ')))
assert ready['assets_match_prior'] == 9 and ready['tokenizer_check']['prompts'] == 1002
with (root / 'preflight/RUNTIME_READY.json').open('x', encoding='utf-8') as f:
    json.dump(ready, f, indent=2)
record = {'preflight_commit': '1bd5463', 'user_free_confirmation': 'Yes, this Molab runtime is explicitly free.',
          'paid_authorized': False, 'model_revision': ready['snapshot_manifest']['revision'],
          'snapshot_manifest_sha256': ready['snapshot_manifest_sha256'],
          'extraction_code_sha256': ready['extraction_core_sha256'],
          'main_forwards': 1002, 'calibration_extra_forwards': 60, 'integrity_forwards': 20,
          'original_results_untouched': True, 'reuse_original_audited_extractor': True}
with (root / 'preflight/EXTRACTION_APPROVAL.json').open('x', encoding='utf-8') as f:
    json.dump(record, f, indent=2)
subprocess.run([sys.executable, str(Path(__file__).with_name('build_transport.py')), 'extract'], check=True)
prefix = f'''from pathlib import Path
import json, hashlib
root = Path('/marimo/results/rq2/minimal_pairs_v3')
assert hashlib.sha256((root/'preparation/snapshot_manifest.json').read_bytes()).hexdigest() == {ready['snapshot_manifest_sha256']!r}
assert hashlib.sha256(Path('/marimo/domains/menu_planning/scripts/minimal_pairs/extract_minimal_pairs.py').read_bytes()).hexdigest() == {ready['extraction_core_sha256']!r}
record = {record!r}
approval = root/'preparation/EXTRACTION_APPROVAL.json'
if approval.exists():
    assert json.loads(approval.read_text()) == record
else:
    with approval.open('x') as f: json.dump(record,f,indent=2)
'''
with (root / 'transport/extract_frozen.py').open('x', encoding='utf-8', newline='\n') as f:
    f.write(prefix + (root / 'transport/extract.py').read_text(encoding='utf-8'))
print('Saved launch freeze; no model started.')
