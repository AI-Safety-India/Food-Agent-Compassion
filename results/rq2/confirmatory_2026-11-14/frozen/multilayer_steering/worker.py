"""Exploratory (not pre-registered) multi-layer welfare steering, following Sofroniew et al. (2026):
steer the option's own tokens (the attribute line) across a band of middle layers, with small pushes.

To keep activations on-distribution, the hook HOLDS a fixed shift instead of adding pushes that pile up:
at every band layer, each steered line token's projection on that layer's unit vector u_l is set to
    (its unsteered projection) + k * natural_gap_l
where natural_gap_l is the mean better-minus-worse line projection on u_l in the training pairs (about 5-7% of the
token's activation norm). So the line never moves further than k typical better-vs-worse differences at any layer.
Random-direction controls use the identical procedure with random unit vectors and the same per-layer shift size.

Runs on molab with the audited loader and the frozen Stage 3 inputs. Condition "none" only. Writes result.json.
"""
import argparse
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path('/marimo/results/rq2/minimal_pairs_v3')
SCRIPTS = Path('/marimo/domains/menu_planning/scripts/minimal_pairs')
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

K_WELFARE = [-1.0, -0.5, -0.25, 0.25, 0.5, 1.0]
K_RANDOM = [-1.0, -0.5, 0.5, 1.0]
N_RANDOM = 5


def main():
    import importlib.util
    import random
    import numpy as np
    import torch

    band = np.load(OUT / 'band.npz')
    layers = [int(x) for x in band['layers']]           # hidden_states indexing; module = model.layers.{L-1}
    W = band['vectors'].astype(np.float32)               # (n_layers, 4096) unit welfare vectors, denoised
    gap = band['natural_gap'].astype(np.float32)          # (n_layers,)
    rng = np.random.default_rng(20261114)
    R = rng.standard_normal((N_RANDOM, len(layers), 4096)).astype(np.float32)
    R /= np.linalg.norm(R, axis=-1, keepdims=True)
    dirs = np.concatenate([W[None], R], 0)               # (1+N_RANDOM, n_layers, 4096); index 0 = welfare

    rows = json.loads((OUT / 'inputs.json').read_text(encoding='utf-8'))
    # Same settings as the audited extraction runtime: seeds, no TF32, bf16 via the unchanged audited helper,
    # pinned revision c202236235762e1c871ad0ccb60c8ee5ba337b9a downloaded to OUT/model. The worker checks that
    # unsteered logits reproduce the saved extraction logits.
    random.seed(20261114); np.random.seed(20261114); torch.manual_seed(20261114); torch.cuda.manual_seed_all(20261114)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    spec = importlib.util.spec_from_file_location('audited_helper', SCRIPTS / 'audited_helper.py')
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    model, tok = helper.load_qwen_model_and_tokenizer(str(OUT / 'model'))
    model.eval()
    import transformers
    env = dict(torch=torch.__version__, transformers=transformers.__version__, numpy=np.__version__,
               model_class=type(model).__name__, device=torch.cuda.get_device_name(),
               attention_implementation=getattr(model.config, '_attn_implementation', None))
    device = next(model.parameters()).device
    mods = {L: dict(model.named_modules())[f'model.layers.{L - 1}'] for L in layers}
    D = torch.tensor(dirs, device=device)                # float32
    G = torch.tensor(gap, device=device)

    def forward(ids, hooks):
        handles = [mods[L].register_forward_hook(h) for L, h in hooks.items()]
        try:
            with torch.no_grad():
                return model(input_ids=torch.tensor([ids], device=device), use_cache=False).logits[0, -1].float()
        finally:
            for h in handles:
                h.remove()

    results, t0 = [], time.time()
    for n, r in enumerate(rows):
        ids = r['input_ids']
        a_id, b_id = r['answer_token_ids']['A'], r['answer_token_ids']['B']
        toks = {t: r['spans'][f'{t}_line']['token_indices'] for t in ('A', 'B')}
        # 1) unsteered pass: record each line token's projection on every direction at every band layer
        base_proj = {}

        def capture(L, li):
            def hook(mod, inp, out):
                for t, ti in toks.items():
                    h = out[0, ti, :].float()                      # (tokens, 4096)
                    base_proj[(L, t)] = h @ D[:, li, :].T           # (tokens, n_dirs)
                return out
            return hook
        logits = forward(ids, {L: capture(L, li) for li, L in enumerate(layers)})
        saved = [r['candidate_logits'][str(a_id)], r['candidate_logits'][str(b_id)]]
        base_logits = [float(logits[a_id]), float(logits[b_id])]
        rec = dict(prompt_id=r['prompt_id'], pair_id=r['pair_id'], set=r['set'], mechanism=r['mechanism'],
                   mirrored=r['mirrored'], A_is=r['A_is'], B_is=r['B_is'], base_logits=base_logits,
                   matches_saved=[round(x, 4) for x in base_logits] == [round(x, 4) for x in saved], runs=[])

        # 2) steered passes: hold projection = unsteered + k * gap_l on the target line's tokens
        def hold(L, li, t, d, k):
            u = D[d, li, :]
            def hook(mod, inp, out):
                o = out.clone()
                ti = toks[t]
                h = o[0, ti, :].float()
                target = base_proj[(L, t)][:, d] + k * G[li]
                h = h + (target - h @ u)[:, None] * u[None, :]
                o[0, ti, :] = h.to(o.dtype)
                return o
            return hook
        configs = [(0, k) for k in K_WELFARE]
        if r['set'] == 'welfare_heldout':
            configs += [(d, k) for d in range(1, N_RANDOM + 1) for k in K_RANDOM]
        for d, k in configs:
            for t in ('A', 'B'):
                lg = forward(ids, {L: hold(L, li, t, d, k) for li, L in enumerate(layers)})
                rec['runs'].append(dict(direction=d, k=k, target=t, logits=[float(lg[a_id]), float(lg[b_id])]))
        results.append(rec)
        if n % 10 == 0:
            (OUT / 'progress.json').write_text(json.dumps(dict(done=n + 1, total=len(rows), seconds=round(time.time() - t0))))
            (OUT / 'partial.json').write_text(json.dumps(results))
    (OUT / 'result.json').write_text(json.dumps(dict(layers=layers, k_welfare=K_WELFARE, k_random=K_RANDOM,
                                                     n_random=N_RANDOM, env=env, results=results)))
    (OUT / 'progress.json').write_text(json.dumps(dict(done=len(rows), total=len(rows), seconds=round(time.time() - t0), complete=True)))
    print('DONE', len(results))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        (OUT / 'error.txt').write_text(traceback.format_exc())
        raise
