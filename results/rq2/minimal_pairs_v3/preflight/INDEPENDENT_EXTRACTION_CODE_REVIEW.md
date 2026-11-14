# Independent extraction code review, first pass

Reviewer: `prefix_reviewer_b`, delegated model agent, 14 November 2026. Reviewed the complete extraction script and eight synthetic tests. No inference or model weights loaded. Implementer A received findings directly; this records the pre-fix assessment, not final approval.

The exact canonical prompt reconstruction, paired-order mapping, character-offset span selection, template/token-ID equality check, endA/endB/final ordering, one audited extraction forward, and FP32 accumulation of helper-returned FP16 token states are coherent. The clarified boundary rule is implemented: exact span text or exactly one leading ASCII separator space, never arbitrary trimming or trailing punctuation. Real pinned-tokenizer verification remains necessary.

## Required corrections before execution

1. `calibrated_family` currently rejects mixed families. Implement the parent's prospective frequency rule across eligible symmetric single-token A/B families with fixed tie order, and retain family counts/ambiguity. No label/outcome optimization. Store multi-token variants descriptively; do not mistake their first token for an independently valid label token.
2. `COMPLETE.json` currently calls any first token outside the selected family off-format. Count true off-format against the union of recognized single-token A/B variants; separately report valid variants outside the chosen family.
3. `load_runtime` records package versions but does not enforce the prescribed pins. Check torch 2.11.0 (allow a documented local CUDA build suffix), transformers 5.14.1 and numpy 2.4.6 before model creation.
4. Resume checks occur after model loading. Validate existing intents, marker hashes, array hashes, row identities and ledger events under the exclusive lock before backend creation. A marker currently only checks prompt_id and array hash, while its input identity and metadata hash are not checked against the intent/completion ledger. A crash after marker write but before completion ledger must be explicitly recovered without inference, not silently skipped. An uncertain intent without a complete result blocks dispatch before expensive startup. Add synthetic pending-intent, tampered metadata, tampered array, missing completion and duplicate event tests.
5. Record exact hidden-state/module semantics, including whether final tuple entry is post-final normalization; shape `(positions, 32, hidden)` cannot establish raw residual identity. Preserve explicit 1-based layer to module/output mapping for later hooks. This must not be guessed from old helper comments.
6. Snapshot verification resolves each symlink and requires it inside the snapshot. Normal Hugging Face cache snapshots can link to sibling blob storage. Either use an explicitly materialized copied snapshot or allow hash-verified file links within an explicitly declared cache root; never skip hash checking. Freeze this operational choice before remote upload.

## Secondary robustness issues

- Integrity records and calibration records on resume should be checked against their saved IDs/input hashes and existing aggregate records, not simply trusted because marker paths exist. This extends the main-run identity principle.
- Consolidation is described as restartable but deliberately rejects any existing layer file. That safely avoids overwrite but is not automatic restart; report the recovery procedure as blocked/manual bookkeeping. An interrupted `.npz` write should not be treated as a completed layer. Do not redo study forwards to repair consolidation.
- `greedy_tail` intentionally uses two extra forward passes after the main argmax. It does not stop at EOS; record that these are fixed three-token diagnostics, including any post-EOS continuation, rather than ordinary EOS-terminated generation. Prefer an explicit early-stop policy if the parent requires normal generation semantics, frozen before diagnostic outputs.
- Existing synthetic tests validate spans, labels, template hash rejection, samples, lock/exclusive write and one-forward means. They do not substitute for the required 30 real tokenizer demonstrations, all-prompt preflight, or actual Qwen architecture inspection.

## Parent clarifications received

Length is report-only under the binding plan; no invented length-contamination threshold. Boundary decoding permits exactly the line or exactly one leading separator space with the exact character span retained. Calibration family selection is deterministic by frequency with fixed family-order ties and reported ambiguity. These supersede the first-pass design note's unresolved alternatives; original notes remain preserved.
