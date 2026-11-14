# Actual tokenizer evidence disposition

Delegated reviewer `prefix_reviewer_b`, 14 November 2026. Extraction SHA256 `44d173288932160d44e5bf7e99e53887b364e64b62e9d1b01978787f0a7c36fc`.

Reviewed the compatibility correction: `Mapping` results from `apply_chat_template(tokenize=True)` are normalized through `['input_ids']`; list results remain supported. The actual token-ID equality assertion is retained. This fixes comparing BatchEncoding keys rather than token IDs; it does not change prompts or tokenization. Independently reran eleven synthetic tests, including the new mapping-return regression: all passed.

Independently inspected saved `tokenizer_test_01/preflight.json` and all 1,002 `rendered.jsonl` records. Verified current script and original prompt/pair source hashes against recorded hashes, rendered artifact hash, unique prompt coverage, every saved span's character substring and allowed decoded boundary, and endA < endB < final = last token. Verified the 30-example sample covers all nine set/condition cells, a maximum-length brand, five-word and ten-word lines. The separate clearly labelled synthetic CPU fixture covers numeric endings and is not a study input.

Observed candidate evidence: raw A/B IDs 32/33, space-prefixed A/B IDs 357/417; newline variants are two-token sequences beginning with 198, not independent single-token answer candidates. Saved template hash matches the prescribed value. This audit checks saved real-tokenizer evidence; it did not repeat model inference or load weights.

**Disposition: Step A CPU extraction/tokenizer review passed.** The previous API mismatch is resolved with regression coverage. Hardware/model-loading smoke, actual runtime hidden-state and logit fidelity checks remain for Step B after the explicit task-specific free-runtime confirmation. No claim of GPU execution or model results is made.
