"""Exploratory: read the minimal-pair welfare vectors inside the 1,200 saved FAC agent runs (Qwen3.5-9B).

Remote pipeline (molab), each step verified before the next:
 1. sparse-clone the public project repo; check git blob hashes of the two .eval logs, the positions file and
    replay_rebuild.py against the local copies;
 2. a separate venv with inspect_ai==0.3.283 rebuilds each run's teacher-forced messages (same code as the audited
    RQ2 pipeline); the decompressed bytes must match the local rebuild's SHA256;
 3. the model venv renders each run, requires the audited token count, finds each read listing's content span,
    runs ONE forward pass, and at layers 13-21 projects (a) the listing's last content token and (b) the mean over
    the listing's content tokens onto the denoised minimal-pair welfare vectors, plus 5 random unit directions;
    plus the frozen Stage 1 vector (layer 21, end token). Band activations for each read are also kept on the
    remote disk (not downloaded) for later analyses.
Outputs in OUT: scores.json(.gz) and log/progress files.
"""
import gzip
import hashlib
import importlib.util
import json
import os
import random
import subprocess
import sys
import time
import traceback
from pathlib import Path

OUT = Path(__file__).resolve().parent
REPO = OUT / 'repo'
SCRIPTS = Path('/marimo/domains/menu_planning/scripts/minimal_pairs')
EXPECTED = json.loads((OUT / 'expected.json').read_text())


def sh(cmd, **kw):
    print('$', ' '.join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def step_inputs():
    if not (REPO / '.git').exists():
        sh(['git', 'clone', '--depth', '1', '--filter=blob:none', '--sparse',
            'https://github.com/AI-Safety-India/Sentient-Futures-Project.git', str(REPO)])
        sh(['git', '-C', str(REPO), 'sparse-checkout', 'set', '--no-cone',
            '/results/logs/full/qwen3.5-9b/', '/results/rq2/t2/qwen35_positions_1200.jsonl',
            '/domains/menu_planning/scripts/rq2/replay_rebuild.py'])
    for rel, blob in EXPECTED['blobs'].items():
        got = subprocess.run(['git', 'hash-object', str(REPO / rel)], capture_output=True, text=True, check=True).stdout.strip()
        assert got == blob, (rel, got, blob)
    print('BLOBS_OK', flush=True)
    env_py = OUT / 'inspect_env/bin/python'
    if not env_py.exists():
        sh([sys.executable, '-m', 'venv', str(OUT / 'inspect_env')])
        sh([str(env_py), '-m', 'pip', 'install', '-q', 'inspect-ai==0.3.283'])
    msg = OUT / 'messages.jsonl.gz'
    if not msg.exists():
        sh([str(env_py), str(OUT / 'prep_a_messages.py')], cwd=str(OUT))
    raw = gzip.open(msg, 'rb').read()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED['messages_sha256'], 'rebuilt messages differ from local'
    print('MESSAGES_OK', flush=True)
    return raw


def main():
    raw = step_inputs()
    import numpy as np
    import torch
    random.seed(20261114); np.random.seed(20261114); torch.manual_seed(20261114)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    band = np.load('/marimo/multilayer_steering/band.npz')
    layers = [int(x) for x in band['layers']]
    W = band['vectors'].astype(np.float32)
    frozen = np.load(OUT / 'frozen_d.npy').astype(np.float32); frozen /= np.linalg.norm(frozen)
    rng = np.random.default_rng(20261114)
    R = rng.standard_normal((5, len(layers), 4096)).astype(np.float32); R /= np.linalg.norm(R, axis=-1, keepdims=True)
    spec = importlib.util.spec_from_file_location('audited_helper', SCRIPTS / 'audited_helper.py')
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    model, tok = helper.load_qwen_model_and_tokenizer('/marimo/multilayer_steering/model')
    model.eval()
    dev = next(model.parameters()).device
    Wt = torch.tensor(np.concatenate([W[:, None], R.transpose(1, 0, 2)], 1), device=dev)  # (layers, 6, 4096)
    Ft = torch.tensor(frozen, device=dev)
    positions = {json.loads(l)['run_id']: json.loads(l) for l in open(REPO / 'results/rq2/t2/qwen35_positions_1200.jsonl') if l.strip()}
    acts_dir = OUT / 'acts'; acts_dir.mkdir(exist_ok=True)
    scores, skipped, t0 = [], [], time.time()
    lines = raw.decode('utf-8').splitlines()
    for n, line in enumerate(lines):
        m = json.loads(line); rec = positions[m['run_id']]
        text = tok.apply_chat_template(m['msgs'], tools=m['tools'], add_generation_prompt=False, tokenize=False)
        enc = tok(text, add_special_tokens=False, return_offsets_mapping=True)
        ids = list(enc['input_ids'])
        if len(ids) != rec['total_teacher_forced_tokens']:
            skipped.append(m['run_id']); continue
        offs = enc['offset_mapping']
        reads = []
        for a in rec['pos_a']:
            close = a['char_close_tag']; start = text.rfind('<tool_response>', 0, close) + len('<tool_response>')
            span = [i for i, (s, e) in enumerate(offs) if s >= start and e <= close and e > s]
            reads.append((a, span))
        with torch.no_grad():
            hs = model(input_ids=torch.tensor([ids], device=dev), output_hidden_states=True, use_cache=False).hidden_states
        rec_out = dict(run_id=m['run_id'], reads=[])
        keep = []
        for a, span in reads:
            entry = dict(option_id=a['option_id'], label=a['option_label'], end=a['tok_idx_content_last'], n_tokens=len(span),
                         end_proj=[], mean_proj=[])
            for li, L in enumerate(layers):
                h = hs[L][0].float()
                he, hm = h[a['tok_idx_content_last']], h[span].mean(0)
                entry['end_proj'].append((Wt[li] @ he).tolist())
                entry['mean_proj'].append((Wt[li] @ hm).tolist())
                keep.append(torch.stack([he, hm]).half().cpu().numpy())
                if L == 21:
                    entry['frozen_end'] = float(Ft @ he)
            rec_out['reads'].append(entry)
        np.save(acts_dir / f"{n:04d}.npy", np.array(keep).reshape(len(reads), len(layers), 2, 4096))
        scores.append(rec_out)
        del hs
        if n % 25 == 0:
            (OUT / 'progress.json').write_text(json.dumps(dict(done=n + 1, total=len(lines), skipped=len(skipped), seconds=round(time.time() - t0))))
    blob = json.dumps(dict(layers=layers, skipped=skipped, scores=scores)).encode()
    (OUT / 'scores.json.gz').write_bytes(gzip.compress(blob, mtime=0))
    (OUT / 'progress.json').write_text(json.dumps(dict(done=len(lines), total=len(lines), skipped=len(skipped), seconds=round(time.time() - t0), complete=True)))
    print('DONE', len(scores), 'skipped', len(skipped))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        (OUT / 'error.txt').write_text(traceback.format_exc())
        raise
