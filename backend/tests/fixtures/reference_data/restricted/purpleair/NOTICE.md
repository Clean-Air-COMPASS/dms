# Restricted PurpleAir reference data

This directory contains the approved Phase 2I.4C frozen PurpleAir capture. It is
classified `restricted_private_not_approved_for_public_redistribution` and must
remain private. Repository storage does not grant public redistribution rights.

Before a public release, remove or relocate every restricted fixture, its
derived database, and any copied CI artifact. Confirm attribution and licensing
with the data owner. Do not automatically refresh or recapture this data.

Private CI may point `COMPASSAQ_RESTRICTED_REFERENCE_DATA_ROOT` at an approved
external directory. Set `REQUIRE_RESTRICTED_REFERENCE_DATA=true` only when that
private data is expected; otherwise absence is an explicit skip.

`capture_manifest.json` is the immutable Phase 2I.4B paid-capture authorization
record. It contains no measurements or API key and cannot perform a provider
request. The New York and Rio sensor selections use existing non-paid evidence.
Metro Manila sensor
`99177` was manually supplied and approved by the user; its unsupplied name and
coordinates remain unknown rather than being retrieved with a metadata request.
The exact prices and verification timestamp used for approval are frozen in the
manifest; they do not authorize a later capture.

The fixed proposed window is
`[2026-08-08T00:00:00Z, 2026-08-11T00:00:00Z)`. PurpleAir's public guidance
allows up to 30 days of real-time history in one request, so the intended
72-hour capture is one history request per sensor and three requests total.
The completed one-shot capture made three history requests and no metadata,
discovery, OpenAQ, or AirGradient requests. It used no retries.
`capture_report.json` records returned rows and point accounting,
`capture_staging/` preserves each raw response, and `manifest.json` plus
`measurements.jsonl` form the validated fixture.
Sensor 198733 returned no observations in the approved window; that absence is
preserved explicitly. Do not refresh, overwrite, or recapture this dataset.

`new_york_replacement_capture_manifest.json` is a zero-network preflight for
New York replacement sensor 159361. Its separately approved one-request capture
returned 2,160 usable provider rows. Sensor 159361 is now the active New York
reference sensor in `manifest.json`; the original empty sensor 198733 response
and the complete pre-replacement fixture remain in `capture_staging/` and
`capture_history/phase_2i4c/`. Rio and Metro Manila measurement lines were
preserved byte-for-byte. Do not rerun the replacement capture or contact another
candidate without new explicit approval.
