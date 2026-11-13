# Capacity runner preparation

No generation has been performed by this preparation. Importing capacity_runner
uses only the standard library. Ten synthetic tests exercise durability,
one-attempt semantics, hashes, output preservation, truncation and locking.

After parent verification/freezing, a durable notebook cell can call:

```python
from capacity_runner import run_prepared
results = run_prepared(manifest_path, frozen_manifest_sha256,
                       pinned_local_snapshot_path, output_directory)
```

There is no notebook API dependency, chat rerender, network action or tool
execution. The caller must supply the already-approved
free runtime; this module is not an authorization mechanism.

## Required manifest (capacity_runner_v1)

The manifest itself is authenticated by a separately supplied SHA256. Required
keys are:

- `schema`: `capacity_runner_v1`.
- `model_revision`: `c202236235762e1c871ad0ccb60c8ee5ba337b9a`.
- `engine`, `sampling`: exact copies of the module's ENGINE and SAMPLING dicts.
- `prepared_file`: relative gzip filename beneath the manifest directory.
- `prepared_sha256`: SHA256 of compressed bytes.
- `job_count`: 1066 for the complete study; tests use smaller synthetic bundles.
- `jobs`: map from each job_id to canonical JSON SHA256 of that complete
  prepared record, using jsha from this module/capacity_input.py.
- `model_files`: map of relative snapshot filenames to SHA256 of their bytes;
  parent must cover weights/index, model config and tokenizer assets. Symlinks
  to Hugging Face cache blobs are allowed and their target bytes are hashed.
- `stop_token_ids`: sorted unique tokenizer eos_token_id and `<|im_end|>` ID,
  derived locally before freeze and rechecked locally on execution.
- `sampler`: `{"name":"pytorch_native","VLLM_USE_FLASHINFER_SAMPLER":"0"}`.

The gzip contains the JSON list returned by prepare_capacity_input, including
input_ids and integrity/retention fields. Its historical not_ready status is not
treated as the execution gate: the parent-approved frozen manifest is the gate.
Parent reports the remote compressed bundle SHA256 as
06a25a391c30944a7fece2ce75aad932386f1dda34fc10e2bb8719f5265dc5f7;
this preparation did not retrieve or independently inspect those remote bytes.

The engine is vLLM 0.24.0, bf16, eager, prefix caching off, model length 6710,
max_num_seqs 1, GPU memory utilization 0.5, tensor parallel 1, seed 20261114,
generation_config='vllm'. Greedy sampling uses max 256 new tokens. Native sampler
selection follows parent-provided prior fidelity retry provenance:
rq2_repair/remote_retry_vllm_sampler.py set VLLM_USE_FLASHINFER_SAMPLER=0 before
vLLM import. No custom sampler implementation was guessed.

## Durable behavior

The exclusive lock and complete ledger recovery precede backend initialization.
Dependency checks, tokenizer loading, vLLM startup and environment recording all
finish before the first new intent. Engineering startup failure consumes zero
study attempts. Exact pinned versions are vLLM 0.24.0, torch 2.11.0,
transformers 5.14.1 and numpy 2.4.6, from the prior fidelity artifact.
Before dispatch, environment.json records GPU names/capabilities/memory, CUDA,
Python, package versions and resolved engine/sampling parameters. summary.json
is atomically updated after each response; compact stdout progress appears
every 25 responses and at completion.

An exclusive lock prevents concurrent dispatch. Each job has a fsynced intent
before generate, then an atomic fsynced response, then a fsynced completion
event. Exact backend prompt_token_ids are compared with supplied IDs; raw output
text, token IDs, finish/stop reasons and backend ID are retained. Exceptions are
saved as generation failures and stop the loop. A subsequent resume skips that
failed job rather than trying it again.

A ledger intent lacking a response blocks all further dispatch as uncertain.
An atomic response without a completion event is recovered without generation.
Malformed ledger JSON, changed completed responses, orphan responses, identity
changes or stale locks require manual audit. Never delete an intent to retry.
After hard process death a stale lock is intentionally left for the parent to
inspect and remove only after verifying no live process remains; this does not
authorize retry of any uncertain job.

Only genuinely unsubmitted jobs can be generated on resume. Input mismatches
stop immediately after preserving the result. Length finishes remain truncated
even if text looks complete. Unexpected think/tool markup is flagged, never
executed. Semantic scoring and broad-vs-target welfare interpretation remain
separate from this transport/completion layer.

Run synthetic tests with `python -m unittest test_capacity_runner -v` from this
directory. No vLLM/tokenizer/model is imported by those tests.

## Spawn-safe durable cell

Prefer the standalone guarded worker from a durable notebook cell so vLLM's
spawn method has a safe main module. Use the persistent study directory and
write stdout/stderr there; do not import notebook-control APIs in the worker.

```python
import subprocess, sys
from pathlib import Path
study = Path('/marimo/sf_capacity_v11_preparation_2026_11_14')
with (study / 'generation_worker.log').open('a') as log:
    subprocess.run([
        sys.executable, '-u', str(study / 'capacity_runner.py'),
        '--manifest', str(study / 'execution_manifest.json'),
        '--manifest-sha256', FROZEN_MANIFEST_SHA256,
        '--model-path', PINNED_LOCAL_SNAPSHOT_PATH,
        '--output-dir', str(study / 'generation_results'),
    ], cwd=study, stdout=log, stderr=subprocess.STDOUT, check=True)
```

This is a prospective invocation example, not an executed cell. The parent
must supply the frozen paths/hash and approved free runtime.
