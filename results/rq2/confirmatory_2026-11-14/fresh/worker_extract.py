"""Confirmatory phase 1 (molab): tokenize confirm prompts with the audited template, verify rendering against three
saved v3 prompts, extract line-mean activations at layers 13-21, and write the RAW generally-good vector per layer
(good-line mean minus grand mean over gg_build pairs, condition none) exactly as build_vectors.py's concept_vector.
Denoising and orthogonalisation are done locally with the frozen v3 neutral lines (same code as build_vectors.py).
Also saves line-mean activations for every confirm prompt on the remote disk for later checks.
"""
import importlib.util
import json
import random
import sys
import traceback
from pathlib import Path

OUT = Path(__file__).resolve().parent
SCRIPTS = Path('/marimo/domains/menu_planning/scripts/minimal_pairs')
LAYERS = list(range(13, 22))


def spans_for(text, line, offs, after):
    start = text.index(line, after); end = start + len(line)
    idx = [i for i, (s, e) in enumerate(offs) if e > s and s < end and e > start]
    return idx, end


def main():
    import numpy as np
    import torch
    random.seed(20261114); np.random.seed(20261114); torch.manual_seed(20261114)
    torch.backends.cuda.matmul.allow_tf32 = False; torch.backends.cudnn.allow_tf32 = False
    spec = importlib.util.spec_from_file_location('audited_helper', SCRIPTS / 'audited_helper.py')
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    model, tok = helper.load_qwen_model_and_tokenizer('/marimo/multilayer_steering/model')
    model.eval(); dev = next(model.parameters()).device

    def render(prompt):
        text = tok.apply_chat_template([{'role': 'user', 'content': prompt}], add_generation_prompt=True, tokenize=False, enable_thinking=False)
        enc = tok(text, add_special_tokens=False, return_offsets_mapping=True)
        return text, list(enc['input_ids']), enc['offset_mapping']

    # rendering check against saved v3 inputs (exact token ids and line spans)
    checks = json.loads((OUT / 'v3_check.json').read_text())
    for c in checks:
        text, ids, offs = render(c['prompt'])
        assert ids == c['input_ids'], ('v3 token ids differ', c['prompt_id'])
        a, ea = spans_for(text, c['A_line'], offs, 0); b, _ = spans_for(text, c['B_line'], offs, ea)
        assert a == c['A_span'] and b == c['B_span'], ('v3 spans differ', c['prompt_id'], a, c['A_span'])
    print('RENDER_CHECK_OK', len(checks), flush=True)

    rows = json.loads((OUT / 'confirm_prompts.json').read_text())
    acts, meta = [], []
    for r in rows:
        text, ids, offs = render(r['prompt'])
        a, ea = spans_for(text, r['A_line'], offs, text.index('A) '))
        b, _ = spans_for(text, r['B_line'], offs, ea)
        with torch.no_grad():
            hs = model(input_ids=torch.tensor([ids], device=dev), output_hidden_states=True, use_cache=False).hidden_states
        acts.append(np.stack([[hs[L][0, a].float().mean(0).cpu().numpy(), hs[L][0, b].float().mean(0).cpu().numpy()] for L in LAYERS]))
        meta.append(dict(prompt_id=r['prompt_id'], input_ids=ids, A_span=a, B_span=b, final=len(ids) - 1))
    acts = np.array(acts, dtype=np.float32)  # (prompts, layers, 2[A,B], 4096)
    np.save(OUT / 'confirm_line_means.npy', acts.astype(np.float16))
    (OUT / 'confirm_tokens.json').write_text(json.dumps(meta))
    hi, lo = [], []
    for r, x in zip(rows, acts):
        if r['set'] != 'gg_build':
            continue
        good, plain = (x[:, 0], x[:, 1]) if r['A_is'] == 'good' else (x[:, 1], x[:, 0])
        hi.append(good); lo.append(plain)
    hi, lo = np.array(hi), np.array(lo)
    grand = np.concatenate([hi, lo]).mean(0)
    raw = hi.mean(0) - grand                      # (layers, 4096): same as concept_vector
    np.save(OUT / 'gg_raw.npy', raw.astype(np.float32))
    print('DONE gg_build prompts', len(hi), 'all prompts', len(rows), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        (OUT / 'error.txt').write_text(traceback.format_exc())
        raise
