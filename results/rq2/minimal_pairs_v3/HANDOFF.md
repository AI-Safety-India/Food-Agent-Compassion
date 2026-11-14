# Minimal-pairs handoff — 14 November 2026

## Current authorization and boundary

User explicitly confirmed this Molab runtime is free for Stage 3 and authorized the reduced steering design. Never start paid resources. Preserve all original results. Local commits only; no push. No patching, figures, Stage 5, or sub-agent code review for this run. Use the four-prompt engineering check instead and record review skipped.

## Completed

- Extraction: 1002 main forwards, cached logits and 32 layers downloaded and hash verified; 20 integrity checks passed. No extraction worker remains running.
- Stage 0: welfare-condition choices 234/240; no excluded mechanisms.
- Stage 1 frozen primary layer 21: held-out 81/100, mechanism CI [0.67,0.93]; neutral ratio 0.1974; neutral-choice AUROC 0.4749. All predeclared representation gates pass. Independent comparison: 182 fields exact.
- Stage 2: held-out welfare-minus-brand-control gap +0.8212, pair-bootstrap CI [0.4164,1.2261]. Independent comparison: 315 fields exact. This is descriptive instruction amplification, not proof of causal use or of moral evaluation beyond content.

## Existing commit identities

- Extraction and Stage 0/training design: 6d432d568df7690117254bf65c573ebd04779b1a.
- Training/evaluation code freeze: 149bfcb1ad783ebd58243917d14a60284ff148a6.
- Primary probe freeze and Stage 2 code: 6b4ca1cde12af72e987b45db98975c02d729020b.
- Stage 1/2 output commit: pending immediately after writing this file; record below after commit.

Canonical freeze: `stage1/frozen/FROZEN.json`, SHA256 `780e326a329d04531b186b2825f5f3e6dd695fe1f3dc68be207df983cc28ead7`. Use its primary.npz; never select a new layer/direction. Stage 1 results SHA256 `802bde9445f2ee875b93913f6eca5b34e0bc5ad5edf142f41f82690b8b33d873`; Stage 2 results SHA256 `e5801134b97078b2629ebe637c0e75f09643efd5b7d6d3af16be75dec736f89a`.

## Stage 3 next steps

Follow STEERING_PREREG.md once committed. It supersedes preflight/STEERING_PREREG_DRAFT.md, whose full controls, patching and held-out-primary design are NOT authorized for this run.

Reduced design: 9208 nonzero study forwards; reuse alpha-zero cached logits after engineering equivalence passes. Four prompts, two forwards each for zero-hook equivalence and nonzero position isolation: 8 engineering forwards, total 9216. Primary population is all 120 welfare pairs; report 50 held-out pairs separately. Ten random directions only on held-out prompts at +/-4; neutral-fitted direction on held-out prompts at six nonzero doses; primary direction also on 94 neutral prompts. No model calls have been made for Stage 3.

1. Save Stage 1/2 outputs and this handoff locally.
2. Commit STEERING_PREREG.md before any model call.
3. Implement and freeze steer_minimal_pairs.py, exact execution manifest, sigma/control vectors and four sanity prompt IDs. Reuse extraction rendering, span finder and candidate token readout. No sub-agent review.
4. Reconnect via existing pairing bridge, inspect runtime read-only, upload new task files, run one durable batched job. Stop on sanity failure or uncertain job intent; no automatic repeat of model calls.
5. Download raw outputs and verify remote SHA256 hashes. Analyse pair-cluster bootstrap and independently recompute only combined/held-out +/-4 and random 90th percentiles with separate code.
6. Commit locally with message `minimal pairs: Stage 3 steering`, update this handoff and report PASS/FAIL per criterion; stop.

## Paths and exact existing connection command

Repository: `C:\Users\Person1\OneDrive\Desktop\sfn\Sentient-Futures-Project-git`.
Local Python: `results/rq2/minimal_pairs_v3/preflight/.venv/Scripts/python.exe`.
Remote Python: `/tmp/uv-venv/bin/python`.
Remote root: `/marimo/results/rq2/minimal_pairs_v3`.
Remote extraction: `/marimo/results/rq2/minimal_pairs_v3/extraction`.
Remote model snapshot: `/marimo/results/rq2/minimal_pairs_v3/model_cache/hub/models--Qwen--Qwen3.5-9B/snapshots/c202236235762e1c871ad0ccb60c8ee5ba337b9a`.
Endpoint: `https://sb-8e189fdea7da37de.sb.molab.run/`.

From workspace root, existing transport command (CODE_FILE must be prepared; do not run a nonexistent placeholder):

```powershell
python rq2_repair/connect_molab.py --url https://sb-8e189fdea7da37de.sb.molab.run/ --code-file CODE_FILE --output OUTPUT_LOG
```

Read marimo-pair skill first. First kernel command of a new session must be only `import marimo._code_mode as cm; help(cm)`. Persist notebook changes through cm. Never inspect, print, commit, or upload the protected pairing/token file. Existing bridge consumes it internally. No new dependency installation is currently required.

Exact worker/analyser commands will be recorded when those CLIs exist; they are not implemented yet. Do not mistake a planning command for a ready worker.
