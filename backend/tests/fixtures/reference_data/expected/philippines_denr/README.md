# Philippines DENR-EMB approved conformance expectations

`denr-emb-aqi-2021-approved-v1.json` is an immutable analyst-approved oracle.
It was promoted through `reference_data_tools/promotion.py`; it must never be
edited or overwritten in place. A methodology, source, derivation, expected
result, or review change requires a new bundle filename and a new approval.

The bundle binds both frozen Manila measurement hashes, the production-code-free
real and synthetic candidate artifacts, the approved review package, every
source-case and derivation hash, and the verbatim analyst approval record. The
hash-bound review provenance is retained under
`backend/tests/fixtures/reference_data/provenance/philippines_denr/`; it does
not contain production implementation observations.

The existing OpenAQ and PurpleAir `phase2i5-approved.json` bundles remain
separate and unchanged.
