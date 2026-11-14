from pathlib import Path
import json, hashlib
root = Path('/marimo/results/rq2/minimal_pairs_v3')
assert hashlib.sha256((root/'preparation/snapshot_manifest.json').read_bytes()).hexdigest() == '28e2c8eb290647b2965af1e0a3c01f1518eb1e922ccbd1ae8740e6e68af40a28'
assert hashlib.sha256(Path('/marimo/domains/menu_planning/scripts/minimal_pairs/extract_minimal_pairs.py').read_bytes()).hexdigest() == '44d173288932160d44e5bf7e99e53887b364e64b62e9d1b01978787f0a7c36fc'
record = {'preflight_commit': '1bd5463', 'user_free_confirmation': 'Yes, this Molab runtime is explicitly free.', 'paid_authorized': False, 'model_revision': 'c202236235762e1c871ad0ccb60c8ee5ba337b9a', 'snapshot_manifest_sha256': '28e2c8eb290647b2965af1e0a3c01f1518eb1e922ccbd1ae8740e6e68af40a28', 'extraction_code_sha256': '44d173288932160d44e5bf7e99e53887b364e64b62e9d1b01978787f0a7c36fc', 'main_forwards': 1002, 'calibration_extra_forwards': 60, 'integrity_forwards': 20, 'original_results_untouched': True, 'reuse_original_audited_extractor': True}
approval = root/'preparation/EXTRACTION_APPROVAL.json'
if approval.exists():
    assert json.loads(approval.read_text()) == record
else:
    with approval.open('x') as f: json.dump(record,f,indent=2)
import marimo._code_mode as cm
async with cm.get_context() as ctx:
    assert not any(c.name == 'minimal_pairs_extract' for c in ctx.cells), 'Cell exists; inspect instead of duplicating'
    cid = ctx.create_cell("def launch_minimal_pairs_extract():\n    import hashlib, json, os, subprocess, sys\n    from pathlib import Path\n    root = Path('/marimo/results/rq2/minimal_pairs_v3')\n    job = root / 'jobs' / 'extract'\n    job.mkdir(parents=True, exist_ok=True)\n    if (job / 'exit.json').exists():\n        print('Job already finished:', (job / 'exit.json').read_text())\n        return\n    if (job / 'launch_intent.json').exists():\n        print('Launch already recorded. Inspect saved PID/log; do not launch again.')\n        return\n    with (job / 'launch_intent.json').open('x') as f:\n        json.dump({'stage': 'extract', 'user_confirmed_free': True, 'paid_authorized': False}, f)\n        f.flush()\n        os.fsync(f.fileno())\n    with (job / 'worker.log').open('ab') as log:\n        process = subprocess.Popen([sys.executable, '-B', '-u', '/marimo/domains/menu_planning/scripts/minimal_pairs/job_supervisor.py', 'extract'], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)\n    with (job / 'pid.json').open('x') as f:\n        json.dump({'pid': process.pid}, f)\n    print('Started minimal-pairs extract, PID', process.pid, 'on the confirmed free runtime. Progress is saved on disk.')\nlaunch_minimal_pairs_extract()\n", name='minimal_pairs_extract', hide_code=False)
    print('Created cell', cid)
    ctx.run_cell(cid)
