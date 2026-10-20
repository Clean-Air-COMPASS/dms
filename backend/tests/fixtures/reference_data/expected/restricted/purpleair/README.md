# Restricted PurpleAir approved expectations

`phase2i5-approved.json` contains the restricted expectations approved by
Spheros Environmental at `2026-08-12T06:53:00-07:00`. The artifact inherits
the restricted/private handling of the PurpleAir source fixture and was
promoted only after source, worksheet, derivation, and frozen-measurement hashes
were verified. Current CompassAQ output is not stored in the expectation bundle.

The hash-bound source facts and worksheet are retained in
`backend/tests/fixtures/reference_data/provenance/phase2i5/` so the loader can
continue to validate the bundle without generated review output.
