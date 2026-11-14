# Independent extraction re-review

14 November 2026, delegated reviewer `prefix_reviewer_b`. Independently ran `python -B -m unittest discover -s domains/menu_planning/scripts/minimal_pairs/tests -v`: all ten synthetic tests passed. No real tokenizer, model weights or GPU used in this check.

Verified corrections: version pins checked before model creation; valid alternative A/B token families separated from off-format output; modal-family rule and fixed tie order recorded; verified HF cache blob symlinks supported; main completed shards bind canonical input digest, row metadata, marker-byte hash and activation-array hash; uncertain main/integrity attempts are checked before backend load. Existing incomplete durable records block conservatively without repeating inference. Source/module provenance and final-layer caveat added.

Remaining issues sent to implementer and parent:

- Filter to symmetric single-token A/B families **before** choosing the modal family. Current implementation counts asymmetric families then fails if one wins, even if a usable symmetric family exists. Preserve all-family diagnostic counts separately.
- Reject duplicate/unknown/out-of-range main ledger events rather than collapsing completion events into a dictionary. Check intent/completion order and identity. Existing integrity result markers should bind row, original input identity and original candidate logits; do not trust an arbitrary existing marker merely by filename.
- Exact final hidden-state normalization is still described as “may be” rather than established from the pinned implementation. Source inspection is pending the parent's dependency installation; do not approve raw-residual or hook-coordinate claims until established. Extraction of literal `hidden_states[1:]` is explicitly documented meanwhile.

Import assessment: the new script has no import-time model load. Audited module import suppresses its directory creation; its original `sys.path`, stdout encoding and bytecode settings still change process state. These do not modify original datasets or results, but the import shim description should not imply every side effect is suppressed.

Disposition: synthetic behavior passed; **conditional, not final GPU-ready approval**. Remaining implementation fixes and actual pinned-tokenizer/source checks are required. This note makes no claim that the thirty real-tokenizer examples have run.
