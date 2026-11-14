# Independent preparation retry review

Reviewer: prefix_reviewer_b. Local source inspection only; no remote connection, downloads, model load, or inference performed by this reviewer.

Disposition: acceptable pre-inference engineering retry. `prepare_assets_v2.py` removes the optional, unavailable `generation_config.json` request. The public pinned revision, `token=False`, task-local cache, index-derived shard inventory, full snapshot hashing, architecture/template checks, and exclusive manifest creation remain intact. No study input or extraction behavior changes.

`job_supervisor_v2.py` maps `prepare2` to `prepare_assets_v2.py`; its job evidence is separate under `jobs/prepare2`. The generated launch cell uses a distinct name and durable exclusive launch intent before subprocess creation, and refuses repeat launch after intent or exit evidence. The extraction branch remains unchanged. Remote upload scripts permit only new files or byte-identical existing files.

Reviewed SHA256 values:

- Preparation v2: `19236732753035d6f792e0a72c6e25fc47af3fcadcb2f161c1437bbc5938d90e`.
- Supervisor v2: `1b9f48a7fea2474a13e5e0ae6bdc6b6ad82775207ece568d2fca8ca8defcc13b`.
- Unchanged extractor: `44d173288932160d44e5bf7e99e53887b364e64b62e9d1b01978787f0a7c36fc`.

Preservation caveat: the local retry builder uses `write_text` for its new versioned outputs. Preserve this first generated version; do not rerun a changed builder over those evidence files. The original preparation and supervisor files are read, not rewritten.

Pending: independently compare the completed snapshot manifest's four weight hashes against the prior pinned-model manifest before extraction. This review does not establish download completion, GPU compatibility, or hardware inference success.
