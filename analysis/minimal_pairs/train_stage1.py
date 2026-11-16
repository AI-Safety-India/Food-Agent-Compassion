"""Prospective Stage1 TRAIN-ONLY fitting and freeze. Never reads mixed arrays.

Required archive: manifest.json, index.jsonl, and 140 separately hashed .npz
shards (activations[5,32,D], positions endA,endB,meanA,meanB,final). Index rows
contain exact frozen prompt metadata plus source_row, shard_file and shard_sha256. Only
welfare_train/none is accepted. All metadata are checked before any np.load.
Actual fitting requires the passed Stage0 result and explicit authorization.
"""
from __future__ import annotations
import os
for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_name] = "1"
import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import warnings

SEED = 20261114
PROMPTS_SHA = "dffff8f6a45f3abaf69c2b5f291952d940a3539debadd4e52108d9a923b3cd9b"
C_GRID = (1e-4, 1e-3, 1e-2, 1e-1, 1., 10.)
POSITIONS = ("endA", "endB", "meanA", "meanB", "final")
SPECIFICATION = {
    "stage": "1 train-only", "seed": SEED, "threads": 1,
    "input": "140 train-none prompt shards only;70 pairs;14 mechanisms;five pairs/mechanism;both orders",
    "positions": ["endA", "endB"], "layers": list(range(1, 33)),
    "primary": "unchanged audited fit_mass_mean; unscaled returned hidden states (entry32 normalized); better minus worse; unit direction",
    "secondary": "single-C sklearn StandardScaler+L2 LogisticRegression lbfgs,max_iter1000,seed20261114; C selected outside adapter",
    "C_grid": C_GRID, "folds": "leave-one-mechanism-out14; both orders of every pair stay in same fold",
    "scaling": "secondary scaler fitted only to training-fold line vectors; primary no scaling",
    "metric": "strict score(better)>score(worse) per prompt; ties count0; average equal-sized mechanism folds",
    "selection": "primary maximum LOMO accuracy then lower layer; secondary maximum LOMO accuracy then lower layer then lower C",
    "final_fit": "each selected method refit once on all train-none lines; no heldout/neutral access",
    "mean_position_robustness": "same frozen end-position direction applied to meanA/B; no refit or selection",
    "length_adjustment": "train-only per-feature OLS hidden~1+line token count at each method frozen layer; same method/C refit on residuals; report only",
    "bag_of_words": "original-order70 train pairs,140 line instances; binary CountVectorizer token_pattern[a-z]+,train-only vocabulary;L2 LogisticRegression C1,max_iter3000,lbfgs,seed20261114; correction from historical all-text vocabulary",
    "sign": "better positive by labels; never flip using evaluation data",
    "freeze": "directions, scaling, full CV, source hashes, actual code commit; expected external FROZEN SHA required by guard",
    "layer32": "post-final-normalization state; no downstream token mixing; no substitution if selected",
    "scope": "no evaluation, baselines, steering or activation-transfer implementation here",
}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_new(path, data):
    with Path(path).open("x", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")


def audited_module(helper):
    # Unchanged function import; suppress only historical import-time mkdirs.
    from unittest.mock import patch
    spec = importlib.util.spec_from_file_location("stage1_audited_helpers", helper)
    module = importlib.util.module_from_spec(spec)
    with patch("os.makedirs", lambda *args, **kwargs: None):
        spec.loader.exec_module(module)
    return module


def verify_code_commit(commit, files, repo):
    """Read-only Git verification, performed only at authorized fit/freeze time."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Actual full40-character code commit required")
    for path in files:
        path = Path(path).resolve()
        relative = path.relative_to(Path(repo).resolve()).as_posix()
        data = subprocess.check_output(["git", "show", f"{commit}:{relative}"], cwd=repo)
        if data != path.read_bytes():
            raise ValueError(f"Current code differs from committed bytes: {relative}")


def validate_training_index(root, prompts_path):
    """No activation open occurs until every row/hash/path/coverage passes."""
    root = Path(root).resolve()
    if sha(prompts_path) != PROMPTS_SHA:
        raise ValueError("Frozen prompts digest mismatch")
    canonical = [json.loads(s) for s in Path(prompts_path).read_text(encoding="utf-8").splitlines()]
    expected = [r for r in canonical if r["set"] == "welfare_train" and r["condition"] == "none"]
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("rows") != 140 or manifest.get("source_prompts_sha256") != PROMPTS_SHA:
        raise ValueError("Archive identity/row count differs from frozen train-none")
    if manifest.get("files", {}).get("index.jsonl") != sha(root / "index.jsonl"):
        raise ValueError("Index hash mismatch")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest.get("source_complete_sha256", "")):
        raise ValueError("Source extraction completion digest required")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest.get("extraction_script_sha256", "")):
        raise ValueError("Source extraction script digest required")
    rows = [json.loads(s) for s in (root / "index.jsonl").read_text().splitlines()]
    if len(rows) != 140 or len(expected) != 140:
        raise ValueError("Exactly140 train-none records required")
    paths = set()
    source_rows = {r["prompt_id"]: i for i, r in enumerate(canonical)}
    for row, original in zip(rows, expected):
        if any(row.get(k) != v for k, v in original.items()):
            raise ValueError("Train index identity/order differs from canonical prompt")
        if row.get("source_row") != source_rows[original["prompt_id"]]:
            raise ValueError("Source extraction row index differs")
        rel = Path(row["shard_file"])
        path = (root / rel).resolve()
        if (rel.is_absolute() or ".." in rel.parts or not path.is_relative_to(root)
                or path.suffix != ".npz" or path in paths):
            raise ValueError("Invalid/repeated train shard path")
        paths.add(path)
        if sha(path) != row["shard_sha256"] or manifest["files"].get(rel.as_posix()) != row["shard_sha256"]:
            raise ValueError("Training shard content hash mismatch")
    if {p.resolve() for p in root.rglob("*.npz")} != paths:
        raise ValueError("Archive includes extra or mixed activation files")
    allowed = {"index.jsonl", "manifest.json"} | {p.relative_to(root).as_posix() for p in paths}
    if {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} != allowed:
        raise ValueError("Archive contains unexpected files")
    if set(manifest["files"]) != allowed - {"manifest.json"}:
        raise ValueError("Manifest file inventory mismatch")
    return rows, manifest


def load_training_arrays(root, rows):
    import numpy as np
    arrays, dim = [], None
    for row in rows:
        if row["set"] != "welfare_train" or row["condition"] != "none":
            raise ValueError("Refusing non-training activation open")
        with np.load(Path(root)/row["shard_file"], allow_pickle=False) as z:
            a = z["activations"]
            if a.ndim != 3 or a.shape[:2] != (5, 32) or a.dtype != np.float16 or not np.isfinite(a).all():
                raise ValueError("Expected finite fp16[5,32,D] training shard")
            if dim is None:
                dim = a.shape[2]
            if dim != a.shape[2]:
                raise ValueError("Hidden dimensions differ")
            arrays.append(a[:2].astype(np.float32))
    return np.stack(arrays)


def line_data(activations, rows, selected, layer):
    import numpy as np
    x = activations[selected, :, layer, :].reshape(-1, activations.shape[-1])
    y = np.array([int(rows[i][f"{letter}_is"] == "better") for i in selected for letter in ("A", "B")])
    return x, y


def pairwise_count(scores, labels):
    import numpy as np
    scores, labels = np.asarray(scores).reshape(-1, 2), np.asarray(labels).reshape(-1, 2)
    if not np.all(labels.sum(axis=1) == 1):
        raise ValueError("Each prompt must have exactly one better line")
    better = (scores * labels).sum(axis=1)
    worse = (scores * (1-labels)).sum(axis=1)
    return {"correct": int((better > worse).sum()), "total": len(scores), "ties": int((better == worse).sum())}


def single_c_logistic(x, y, c):
    """Explicit adapter: audited helper internally selects by AUROC, so unsuitable.

    Retains its StandardScaler/L2/lbfgs recipe but fixes one C, uses the new seed,
    and returns training-fitted scaling for external pairwise LOMO selection.
    """
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.exceptions import ConvergenceWarning
    scaler = StandardScaler().fit(np.asarray(x, dtype=np.float64))
    clf = LogisticRegression(C=c, penalty="l2", solver="lbfgs", max_iter=1000, random_state=SEED)
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        clf.fit(scaler.transform(x), y)
    direction = clf.coef_[0] / scaler.scale_
    intercept = float(clf.intercept_[0] - (clf.coef_[0] * scaler.mean_ / scaler.scale_).sum())
    return {"direction": direction, "intercept": intercept, "mean": scaler.mean_, "scale": scaler.scale_,
            "coefficient_standardized": clf.coef_[0], "intercept_standardized": float(clf.intercept_[0]),
            "iterations": int(clf.n_iter_[0])}


def residualize_training(x, lengths):
    """Training-only nuisance regression; no evaluation-side coefficient fitting."""
    import numpy as np
    lengths = np.asarray(lengths, dtype=np.float64)
    if lengths.shape != (len(x),) or not np.isfinite(lengths).all() or (lengths <= 0).any():
        raise ValueError("Positive training line token lengths required")
    design = np.column_stack([np.ones(len(lengths)), lengths])
    coefficient, _, rank, _ = np.linalg.lstsq(design, np.asarray(x, dtype=np.float64), rcond=None)
    residual = np.asarray(x, dtype=np.float64) - design @ coefficient
    return residual, {"residual_intercept": coefficient[0], "residual_slope": coefficient[1], "design_rank": rank}


def length_adjusted_mass_mean(x, y, lengths, helper):
    import numpy as np
    residual, parameters = residualize_training(x, lengths)
    w, midpoint = helper.fit_mass_mean(residual, y)
    if np.linalg.norm(w) < 1e-12:
        raise ValueError("Degenerate length-adjusted training direction")
    return {**parameters, "direction": w, "midpoint": midpoint}


def fit_bow_training(rows):
    from sklearn.feature_extraction.text import CountVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.exceptions import ConvergenceWarning
    originals = [r for r in rows if not r["mirrored"]]
    if len(originals) != 70 or len({r["pair_id"] for r in originals}) != 70:
        raise ValueError("BOW needs exactly70 unique original-order training pairs")
    texts = [r["spans"][letter+"_line"]["text"] for r in originals for letter in ("A", "B")]
    labels = [int(r[letter+"_is"] == "better") for r in originals for letter in ("A", "B")]
    vectorizer = CountVectorizer(binary=True, token_pattern=r"[a-z]+")
    x = vectorizer.fit_transform(texts)
    clf = LogisticRegression(C=1., penalty="l2", max_iter=3000, solver="lbfgs", random_state=SEED)
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        clf.fit(x, labels)
    return {"vocabulary": {k: int(v) for k, v in vectorizer.vocabulary_.items()},
            "coefficient": clf.coef_[0].tolist(), "intercept": float(clf.intercept_[0]),
            "binary": True, "token_pattern": "[a-z]+", "lowercase": True,
            "C": 1., "max_iter": 3000, "seed": SEED, "training_line_instances": len(texts),
            "training_pair_ids": [r["pair_id"] for r in originals],
            "vocabulary_scope": "training only; corrected from historical all-text vocabulary"}


def select(curve, *, secondary=False):
    return min(curve, key=lambda r: (-Fraction(r["correct"], r["total"]), r["layer"], r["C"] if secondary else 0))


def cross_validate(activations, rows, helper, logistic=single_c_logistic):
    import numpy as np
    mechanisms = sorted({r["mechanism"] for r in rows})
    primary, secondary = [], []
    for layer in range(32):
        folds_primary, folds_secondary = [], {c: [] for c in C_GRID}
        for mechanism in mechanisms:
            train = [i for i, r in enumerate(rows) if r["mechanism"] != mechanism]
            val = [i for i, r in enumerate(rows) if r["mechanism"] == mechanism]
            x, y = line_data(activations, rows, train, layer)
            xv, yv = line_data(activations, rows, val, layer)
            w, midpoint = helper.fit_mass_mean(x, y)
            scores = helper.score_mass_mean(xv, w, midpoint)
            folds_primary.append({"mechanism": mechanism, **pairwise_count(scores, yv)})
            for c in C_GRID:
                fit = logistic(x, y, c)
                score = np.dot(xv, fit["direction"]) + fit["intercept"]
                folds_secondary[c].append({"mechanism": mechanism, **pairwise_count(score, yv)})
        def summary(folds):
            if len({f["total"] for f in folds}) != 1:
                raise ValueError("LOMO folds must have equal prompt counts")
            return {"accuracy": sum(f["correct"] for f in folds)/sum(f["total"] for f in folds), "folds": folds,
                    "correct": sum(f["correct"] for f in folds), "total": sum(f["total"] for f in folds),
                    "ties": sum(f["ties"] for f in folds)}
        primary.append({"layer": layer+1, **summary(folds_primary)})
        secondary.extend({"layer": layer+1, "C": c, **summary(folds_secondary[c])} for c in C_GRID)
    return {"primary": primary, "secondary": secondary, "selected_primary": select(primary),
            "selected_secondary": select(secondary, secondary=True)}


def fit_and_freeze(args):
    import numpy as np
    from threadpoolctl import threadpool_limits
    if not args.fit_authorized:
        raise ValueError("Explicit post-Stage0 fit authorization required")
    stage0 = json.loads(Path(args.stage0).read_text())
    gate = stage0["gate"]
    if gate["stop"] or gate["hard_target_denominator"] != 240 or gate["hard_target_numerator"]*5 < 240*3:
        raise ValueError("Stage0 deterministic gate not passed")
    repo = Path(__file__).resolve().parents[4]
    verify_code_commit(args.code_commit, [__file__, args.helper], repo)
    rows, manifest = validate_training_index(args.training, args.prompts)
    # Only after metadata coverage checks: open the140 individually train-only shards.
    a = load_training_arrays(args.training, rows)
    helper = audited_module(args.helper)
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    with threadpool_limits(limits=1):
        write_new(root/"bow.json", fit_bow_training(rows))
        cv = cross_validate(a, rows, helper)
        write_new(root/"cv.json", cv)
        all_rows = list(range(len(rows)))
        primary = cv["selected_primary"]
        x, y = line_data(a, rows, all_rows, primary["layer"]-1)
        w, midpoint = helper.fit_mass_mean(x, y)
        if np.linalg.norm(w) < 1e-12:
            raise ValueError("Degenerate primary direction; no frozen direction")
        with (root/"primary.npz").open("xb") as f:
            np.savez(f, direction=w, midpoint=midpoint)
        lengths = [len(r["spans"][letter+"_line"]["token_indices"]) for r in rows for letter in ("A", "B")]
        adjusted = length_adjusted_mass_mean(x, y, lengths, helper)
        with (root/"length_adjusted.npz").open("xb") as f:
            np.savez(f, **adjusted)
        secondary = cv["selected_secondary"]
        x, y = line_data(a, rows, all_rows, secondary["layer"]-1)
        lr = single_c_logistic(x, y, secondary["C"])
        norm = float(np.linalg.norm(lr["direction"]))
        if norm < 1e-12:
            raise ValueError("Degenerate secondary direction")
        lr["direction_unit"] = lr["direction"]/norm
        with (root/"secondary.npz").open("xb") as f:
            np.savez(f, **lr)
        residual, residual_parameters = residualize_training(x, lengths)
        adjusted_lr = single_c_logistic(residual, y, secondary["C"])
        adjusted_norm = float(np.linalg.norm(adjusted_lr["direction"]))
        if adjusted_norm < 1e-12:
            raise ValueError("Degenerate length-adjusted secondary direction")
        adjusted_lr["direction_unit"] = adjusted_lr["direction"]/adjusted_norm
        with (root/"length_adjusted_secondary.npz").open("xb") as f:
            np.savez(f, **residual_parameters, **adjusted_lr)
    source_paths = {"code": Path(__file__).resolve(), "helper": Path(args.helper).resolve(),
                    "train_manifest": Path(args.training).resolve()/"manifest.json", "train_index": Path(args.training).resolve()/"index.jsonl",
                    "prompts": Path(args.prompts).resolve(), "stage0": Path(args.stage0).resolve()}
    frozen = {"specification": SPECIFICATION, "code_commit": args.code_commit, "method": "mass_mean",
              "layer": primary["layer"], "sign": "better_positive", "scaling": "none",
              "primary_direction_sha256": hashlib.sha256(np.ascontiguousarray(w).tobytes()).hexdigest(),
              "primary_direction_dtype": str(w.dtype), "primary_direction_shape": list(w.shape),
              "secondary": {"layer": secondary["layer"], "C": secondary["C"], "scaling": "saved StandardScaler fitted on all training lines"},
              "length_adjustment": {"primary_layer": primary["layer"], "secondary_layer": secondary["layer"],
                                    "secondary_C": secondary["C"], "scope": "train-only OLS and same-method refit; no layer/C reselection", "report_only": True},
              "files": {p.name: sha(p) for p in (root/"primary.npz", root/"secondary.npz", root/"length_adjusted.npz",
                                                root/"length_adjusted_secondary.npz", root/"bow.json", root/"cv.json")},
              "sources": {k: {"path": str(p), "sha256": sha(p)} for k, p in source_paths.items()},
              "train_prompt_ids": [r["prompt_id"] for r in rows],
              "source_extraction_complete_sha256": manifest["source_complete_sha256"],
              "source_extraction_script_sha256": manifest["extraction_script_sha256"],
              "hidden_state_note": "entry32 is final-normalized; no downstream token mixing for earlier-position causal perturbation",
              "evaluation_requires": "commit this freeze before evaluation; supply externally recorded expected freeze SHA and code commit"}
    write_new(root/"FROZEN.json", frozen)
    print(json.dumps({"frozen_sha256": sha(root/"FROZEN.json"), "status": "TRAIN_ONLY_FREEZE_CREATED_NOT_EVALUATED"}))


def verify_frozen(root, expected_sha, expected_code_commit, expected_freeze_commit):
    """Mandatory gate for a future evaluation module; no activation evaluation."""
    root = Path(root)
    if sha(root/"FROZEN.json") != expected_sha:
        raise ValueError("Frozen manifest drift")
    frozen = json.loads((root/"FROZEN.json").read_text())
    if frozen["code_commit"] != expected_code_commit:
        raise ValueError("Frozen code commit differs")
    for name, expected in frozen["files"].items():
        path = (root/name).resolve()
        if not path.is_relative_to(root.resolve()) or sha(path) != expected:
            raise ValueError("Frozen direction/scaling/CV drift")
    for source in frozen["sources"].values():
        if sha(source["path"]) != source["sha256"]:
            raise ValueError("Frozen source drift")
    repo = Path(__file__).resolve().parents[4]
    verify_code_commit(expected_freeze_commit, [root/"FROZEN.json"] + [root/name for name in frozen["files"]], repo)
    return frozen


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("specification", "fit"))
    p.add_argument("--output", required=True)
    p.add_argument("--training")
    p.add_argument("--prompts")
    p.add_argument("--stage0")
    p.add_argument("--code-commit")
    p.add_argument("--helper", default=str(Path(__file__).resolve().parents[1]/"rq2/run_rq2_gpu_pipeline.py"))
    p.add_argument("--fit-authorized", action="store_true")
    args = p.parse_args()
    if args.mode == "specification":
        write_new(args.output, {**SPECIFICATION, "code_sha256": sha(__file__)})
    else:
        if not all((args.training, args.prompts, args.stage0, args.code_commit)):
            p.error("training, prompts, stage0 and code-commit required")
        fit_and_freeze(args)


if __name__ == "__main__":
    main()
