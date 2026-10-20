# Offline reference fixtures

`synthetic/purpleair_2m` is repository-owned synthetic data. Its identifiers
cannot be confused with provider IDs. Compact JSONL records with `repeat_count`
expand into regular observations during validation and loading.

`restricted/purpleair` contains the approved Phase 2I.4C one-shot PurpleAir
capture. It is private, is not approved for public redistribution, and must not
be refreshed automatically. The capture used exactly three history requests,
zero retries, and no metadata or discovery requests. Sensor 198733 returned no
observations in the original capture; the approved Phase 2I.4C.2 replacement
sensor 159361 later supplied all 2,160 expected provider rows. The current
fixture contains 12,938 pollutant measurements across active sensors 159361,
175407, and 99177. The original sensor 198733 attempt and complete original
fixture remain archived under `capture_history/phase_2i4c`. Restricted fixtures
are optional unless `REQUIRE_RESTRICTED_REFERENCE_DATA=true`.

`public/openaq` contains the bounded Phase 2I.3 location-discovery evidence and
the Phase 2I.4A frozen historical fixture. The history capture is limited to the
13 sensor IDs in `selected_reference_manifest.json`, the half-open UTC window
`[2026-08-01T00:00:00Z, 2026-08-08T00:00:00Z)`, one OpenAQ v3 sensor
measurements endpoint per selected sensor, zero retries, at most 11 pages per
sensor, and an absolute ceiling of 143 requests. The completed capture used 13
requests and no direct PurpleAir or AirGradient request.

`history_capture_plan.json` and `capture_report.json` preserve the approved and
actual request budgets. `manifest.json` and `measurements.jsonl` are the
loader-compatible frozen fixture. Values, provider units, flags, provider
periods, and attribution metadata are preserved without gas conversion or
AQI-driven manipulation. The OpenAQ period metadata documents a one-hour
reporting interval for 12 sensors; sensor 1099 returned no observations, so its
temporal metadata remains unknown rather than inferred. Observed timestamp gaps
are recorded separately from provider-documented interval metadata.

Neither frozen provider fixture has an `expected_results.json`; Phase 2I.5 owns
expected-result derivation and fixture-facing development views. Do not refresh,
overwrite, or extend either capture automatically. A future capture requires a
new reviewed selection, an explicit request ceiling, a zero-network dry run, and
separate approval. Origin license terms vary and are preserved per device; the
fixtures do not infer redistribution rights from repository storage or transport.

Phase 2I.5 source facts, analyst worksheets, implementation-observation reports,
and promotion rules are documented in
`backend/docs/offline_real_data_conformance.md`. Approved public and restricted
expectations have separate roots beneath `expected/`; no expectation is present
until an analyst-approved, hash-matching candidate is promoted.
