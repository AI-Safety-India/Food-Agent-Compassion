"""Exploratory (not pre-registered): per-layer welfare vectors following Sofroniew et al. (2026), 'Emotion Concepts and
their Function in a Large Language Model', adapted to the minimal-pair dataset.

Their recipe -> ours:
  average activations over the concept's tokens         -> mean over each option line's tokens (saved meanA/meanB)
  emotion mean minus mean across emotions               -> better-line mean minus grand mean of all train lines
  project out top PCs of neutral text (50% of variance) -> PCs of neutral-pair line means (no welfare content)
  strength relative to the layer's mean residual norm   -> per-layer median per-token residual norm (endA/endB)
Vectors use only welfare_train / condition none. Held-out and neutral evaluations below are DESCRIPTIVE: those
activations were already opened in Stage 1, so nothing here is a confirmatory test.

Inputs: Sentient-Futures-Project-git/results/rq2/minimal_pairs_v3/extraction/layer_XX.npz + index.jsonl
Outputs (this folder): vectors.npz, layer_curves.json
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
EXT = HERE.parents[1] / "Sentient-Futures-Project-git/results/rq2/minimal_pairs_v3/extraction"

idx = [json.loads(l) for l in open(EXT / "index.jsonl", encoding="utf-8")]
none = [i for i, r in enumerate(idx) if r["condition"] == "none"]
by_set = {s: [i for i in none if idx[i]["set"] == s] for s in ("welfare_train", "welfare_heldout", "neutral_control")}
mechs = sorted({idx[i]["mechanism"] for i in by_set["welfare_train"]})


def unit(v):
    return v / np.linalg.norm(v)


def better_worse(X, ids, iA, iB):
    """Return (better, worse) line vectors for welfare prompts, or (line_1, line_2) for neutral."""
    hi, lo = [], []
    for i in ids:
        a_top = idx[i]["A_is"] in ("better", "line_1")
        hi.append(X[i, iA] if a_top else X[i, iB])
        lo.append(X[i, iB] if a_top else X[i, iA])
    return np.array(hi), np.array(lo)


def denoise(v, neutral_lines):
    """Project out the top principal components of neutral lines explaining 50% of variance."""
    C = neutral_lines - neutral_lines.mean(0)
    _, s, vt = np.linalg.svd(C, full_matrices=False)
    var = s ** 2 / (s ** 2).sum()
    k = int(np.searchsorted(np.cumsum(var), 0.5) + 1)
    P = vt[:k]
    return v - P.T @ (P @ v), k


def concept_vector(X, ids, iA, iB):
    hi, lo = better_worse(X, ids, iA, iB)
    grand = np.concatenate([hi, lo]).mean(0)
    return hi.mean(0) - grand  # = (mean better - mean worse) / 2


def pairwise_acc(X, ids, iA, iB, v):
    hi, lo = better_worse(X, ids, iA, iB)
    return float(np.mean(hi @ v > lo @ v))


curves, raw_vecs, den_vecs, norms, ks = [], [], [], [], []
for L in range(1, 33):
    z = np.load(EXT / f"layer_{L:02d}.npz")
    X = z["activations"].astype(np.float32)
    pos = list(z["positions"])
    iA, iB = pos.index("meanA"), pos.index("meanB")
    eA, eB = pos.index("endA"), pos.index("endB")
    tr, ho, ne = by_set["welfare_train"], by_set["welfare_heldout"], by_set["neutral_control"]
    neutral_lines = np.concatenate([X[ne, iA], X[ne, iB]])
    v_raw = concept_vector(X, tr, iA, iB)
    v_den, k = denoise(v_raw, neutral_lines)
    # train-only leave-one-mechanism-out accuracy (the only selection signal used)
    lomo = []
    for m in mechs:
        fit = [i for i in tr if idx[i]["mechanism"] != m]
        test = [i for i in tr if idx[i]["mechanism"] == m]
        v, _ = denoise(concept_vector(X, fit, iA, iB), neutral_lines)
        lomo.append(pairwise_acc(X, test, iA, iB, v))
    hi_n, lo_n = better_worse(X, ne, iA, iB)
    hi_h, lo_h = better_worse(X, ho, iA, iB)
    ud = unit(v_den)
    gap_ho = float(np.mean(hi_h @ ud - lo_h @ ud))
    gap_ne = float(np.mean(np.abs(hi_n @ ud - lo_n @ ud)))
    tok_norm = float(np.median(np.linalg.norm(np.concatenate([X[none, eA], X[none, eB]]), axis=1)))
    curves.append(dict(layer=L, train_lomo_acc=float(np.mean(lomo)), heldout_acc_raw=pairwise_acc(X, ho, iA, iB, unit(v_raw)),
                       heldout_acc_denoised=pairwise_acc(X, ho, iA, iB, ud), neutral_abs_gap_over_heldout_gap=gap_ne / gap_ho if gap_ho else None,
                       pcs_removed=k, residual_norm=tok_norm, cos_raw_denoised=float(unit(v_raw) @ ud)))
    raw_vecs.append(unit(v_raw)); den_vecs.append(ud); norms.append(tok_norm); ks.append(k)
    c = curves[-1]
    print(f"L{L:02d} lomo {c['train_lomo_acc']:.2f} | held-out raw {c['heldout_acc_raw']:.2f} denoised {c['heldout_acc_denoised']:.2f} "
          f"| neutral/held-out gap {c['neutral_abs_gap_over_heldout_gap']:.2f} | PCs {k} | norm {tok_norm:.1f}", flush=True)
    del X, z

np.savez(HERE / "vectors.npz", denoised=np.array(den_vecs, dtype=np.float32), raw=np.array(raw_vecs, dtype=np.float32),
         residual_norm=np.array(norms, dtype=np.float32), layers=np.arange(1, 33))
json.dump(curves, open(HERE / "layer_curves.json", "w"), indent=1)
print("saved vectors.npz and layer_curves.json")
