"""Durable subprocess exit evidence. Launch exactly once through the notebook."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path('/marimo/results/rq2/minimal_pairs_v3')
CODE = Path('/marimo/domains/menu_planning/scripts/minimal_pairs')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['prepare2', 'extract'])
    args = parser.parse_args()
    job = ROOT / 'jobs' / args.stage
    target = job / 'exit.json'
    if target.exists():
        raise RuntimeError('Job already finished; no duplicate launch')
    try:
        if args.stage == 'prepare2':
            command = [sys.executable, '-B', '-u', str(CODE / 'prepare_assets_v2.py')]
        else:
            manifest = ROOT / 'preparation/snapshot_manifest.json'
            snapshot = json.loads(manifest.read_text())['snapshot']
            command = [sys.executable, '-B', '-u', str(CODE / 'extract_minimal_pairs.py'), 'worker',
                       '--prompts', str(ROOT / 'inputs/prompts.jsonl'), '--pairs', str(ROOT / 'inputs/pairs.json'),
                       '--snapshot', snapshot, '--snapshot-manifest', str(manifest),
                       '--helper', str(CODE / 'audited_helper.py'), '--output', str(ROOT / 'extraction'),
                       '--whitespace-boundary', '--free-runtime-confirmed']
        result = subprocess.run(command, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        status = {'stage': args.stage, 'returncode': result.returncode, 'status': 'complete' if result.returncode == 0 else 'failed'}
    except BaseException:
        status = {'stage': args.stage, 'returncode': 1, 'status': 'failed', 'traceback': traceback.format_exc()}
    with target.open('x') as f:
        json.dump(status, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    sys.exit(status['returncode'])


if __name__ == '__main__':
    main()
