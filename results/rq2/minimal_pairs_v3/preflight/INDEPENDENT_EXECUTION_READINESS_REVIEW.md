# Independent extraction execution review

14 November 2026, delegated reviewer `prefix_reviewer_b`. Parent reports the user explicitly confirmed the current runtime is free for this extraction. This reviewer performed local code/source inspection only, with no independent remote connection, model loading or inference.

## Minimum checks before main worker

1. Verify remote uploaded script, unchanged audited helper, prompts, pairs and snapshot-manifest hashes against the frozen local inputs. Use an isolated task directory, without uploading unrelated caches or secrets.
2. Check exact torch/transformers/numpy pins, import availability of `accelerate` required by `device_map='auto'`, CUDA BF16 capability, GPU model/free memory and whether an earlier worker/model process still occupies the device. Do not terminate another job without establishing its ownership/status.
3. Run snapshot inventory/hash verification and read pinned AutoConfig without weights. Confirm the conditional-generation architecture, text configuration of 32 layers and 4096 hidden dimensions, and absence of quantized weights/config. All model loading remains local/offline.
4. Check fast tokenizer, exact template hash and saved CPU preparation identity on the remote package version. Mapping/list chat-template returns are normalized without changing token IDs.
5. Confirm output directory is new, or explicitly inspect its immutable identity, lock/PID, completion marker and ledger. The worker rejects uncertain attempts before backend creation. A transport timeout is not evidence of process failure; inspect persistent status rather than launching again.
6. Launch one detached worker with redirected durable stdout/stderr and an external exit/status record that distinguishes success from exception. Retain PID and exact argument list. Poll saved state. Do not make network transport lifetime govern model-process lifetime.

## Loader and hidden-state compatibility

The named `Qwen3_5ForConditionalGeneration` adapter checks the pinned architecture, uses BF16 and local-only loading. The audited loader branch is only used when AutoModelForCausalLM supports the actual config. All floating parameters are checked for BF16; silent FP16 fallback is blocked. Version checks precede model creation.

Inspected pinned Transformers source: conditional-generation output forwards `outputs.hidden_states`, and default `logits_to_keep=0` preserves full sequence logits, compatible with the audited helper indexing `out.logits[0]`. The last hidden tuple entry is final-normalized, as established in LAYER_SOURCE_AUDIT.json. The first actual forward must still validate runtime shape and finiteness; source inspection does not replace that check.

`device_map='auto'` can place modules on CPU even when a CUDA BF16 device exists. At engineering startup, record/check `hf_device_map`, actual floating-parameter devices and available memory. The current environment's GPU name alone is not proof all computation resides there. If an incompatible package/kernel/model-load error occurs before the first intent, repair as engineering startup with provenance; after intent, preserve the attempt and do not rerun it.

## Durability and storage limits

Main extraction plus the sampled two-token continuation are one durable prompt attempt; integrity passes have separate intent/completion records. Crashes after intent preserve uncertainty. Existing partial consolidation deliberately blocks for manual bookkeeping rather than re-extracting. Keep per-prompt shards until consolidated layer/index hashes are verified. Arrays are FP16, with means accumulated in FP32 from the audited helper's FP16 vectors; do not describe these as BF16-preserved means.

A main forward failure currently propagates rather than recording a detailed per-prompt failure JSON. The intent and worker exception log therefore are the authoritative failure evidence, and the external launcher must persist nonzero exit/status. This is safe against duplicate execution but does not automatically finish missing rows.

Disposition: prior CPU review remains valid; remote inventory/launcher code must be checked against this checklist when available. Actual hardware startup and fidelity are still untested by this reviewer. No new model outcome or readiness claim is inferred from prior tasks' runs.
