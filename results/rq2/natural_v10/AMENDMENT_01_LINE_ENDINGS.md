# Stage A amendment 01: exact audited line-ending equivalence

13 November 2026. Prospective implementation repair after the first registered
Stage A invocation stopped at the original-position identity check. No normalized
records, eligibility counts, prefix-review decisions, fitted scores or feature
results were produced or inspected. The diagnosis inspected only source bytes
and the saved audit's input-hash metadata.

The local original position file has 1,200 CRLF line endings. Its raw SHA256 is
`07591930f7401daa0005f47841204238c3a2fda392248318dc19d72fd19dbd93`.
Replacing only the two-byte CRLF sequence with LF produces exactly the saved
audit digest `e1ef14d550bcccfce32ce30cd9c3741aed2b411e0f6fe504258c97562c51f30b`.

The local replay helper has 86 CRLF line endings. Its raw SHA256 is
`94854a69a81729b67710c41fa5a66c959d90c0911f267d8c142e46f1a9f8c498`.
The same byte-only conversion produces exactly its saved audit digest
`dd4a11a7d8376c46959f79fc1d2d003873820bb22e2830ee2b36f0b8f16436cc`.

The adapter now accepts these two audited text inputs if either their raw bytes
or their CRLF-to-LF bytes match the expected audit hash exactly. It records the
raw digest, converted digest, expected audit digest and matching method in the
source ledger. No decoding, BOM stripping, whitespace trimming, lone-CR handling
or other normalization is allowed. Any other byte/content drift fails closed.

Original source files and the frozen raw INPUT_HASHES.json remain unchanged.
The ordinary raw-file freeze checks still run before the adapter. The amendment
does not change matching, exclusions, labels, positions, sample-size gates or
scientific pass criteria. Synthetic tests cover exact conversion, raw identity,
source preservation and rejection of substantive edits or other normalizations.
Commit the amended code/hash manifest before another real-data invocation.
