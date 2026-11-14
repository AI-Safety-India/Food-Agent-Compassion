"""Cache pinned public model assets on the confirmed free runtime; no inference."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import sys

ROOT = Path('/marimo/results/rq2/minimal_pairs_v3')
REVISION = 'c202236235762e1c871ad0ccb60c8ee5ba337b9a'
MODEL = 'Qwen/Qwen3.5-9B'
os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['HF_HOME'] = str(ROOT / 'model_cache')
from huggingface_hub import hf_hub_download


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024**2), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    prep = ROOT / 'preparation'
    prep.mkdir(parents=True, exist_ok=True)
    target = prep / 'snapshot_manifest.json'
    if target.exists():
        raise RuntimeError('Preparation manifest exists; verify it rather than duplicate preparation')
    cache = ROOT / 'model_cache/hub'
    def get(name):
        return Path(hf_hub_download(MODEL, name, revision=REVISION, cache_dir=cache, token=False))
    index = get('model.safetensors.index.json')
    snapshot = index.parent
    meta = json.loads(index.read_text())
    needed = meta['metadata']['total_size']
    if shutil.disk_usage(ROOT).free < needed + 6 * 1024**3:
        raise RuntimeError('Insufficient free disk; no paid storage fallback')
    names = ['config.json', 'tokenizer.json', 'tokenizer_config.json', 'chat_template.jinja']
    names += sorted(set(meta['weight_map'].values()))
    for i, name in enumerate(names):
        path = get(name)
        print(json.dumps({'asset': name, 'bytes': path.stat().st_size, 'completed': i + 1, 'total': len(names)}), flush=True)
    files = {p.relative_to(snapshot).as_posix(): digest(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}
    config = json.loads((snapshot / 'config.json').read_text())
    text = config.get('text_config', config)
    assert text['num_hidden_layers'] == 32 and text['hidden_size'] == 4096
    assert config['architectures'] == ['Qwen3_5ForConditionalGeneration']
    assert not config.get('quantization_config')
    expected_template = 'a4aee8afcf2e0711942cf848899be66016f8d14a889ff9ede07bca099c28f715'
    assert files['chat_template.jinja'] == expected_template, 'Template SHA differs: STOP'
    manifest = {'model_id': MODEL, 'revision': REVISION, 'snapshot': str(snapshot), 'files': files,
                'python': sys.executable, 'model_passes': 0, 'weights_loaded': False}
    with target.open('x') as f:
        json.dump(manifest, f, indent=2)
    print(json.dumps({'status': 'assets_ready', 'snapshot': str(snapshot), 'manifest_sha256': digest(target),
                      'model_passes': 0}), flush=True)


if __name__ == '__main__':
    main()
