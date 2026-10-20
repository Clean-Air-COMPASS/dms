# Offline real-data conformance

Phase 2I.5 keeps three artifact classes separate:

1. `independently_extracted_source_facts` contains only frozen provider evidence,
   clock-position assignment, and explicit `Decimal` arithmetic.
2. `analyst_derivation_worksheet` is a review candidate. Its independently
   derived expected fields cannot be used as conformance expectations before
   explicit human approval and promotion.
3. `implementation_observations` records what CompassAQ currently returns from
   an Alembic-created temporary SQLite database. It is diagnostic output only.

Only `analyst_approved_expectations` can be loaded by conformance tests. The
promotion command checks the current frozen measurement file checksum, the entire source-fact
file hash, the entire worksheet file hash, each derivation hash, reviewer
identity, timestamp, comments, and approval decision. Any source, methodology,
derivation, or expected-result change therefore requires a new review.

All repository reference artifacts are UTF-8 JSON or JSONL text. File
fingerprints normalize CRLF checkout line endings to LF before calculating
SHA-256 so Windows, Linux, and existing checkouts verify the same reviewed
content. Encoding, JSON formatting, spaces, and all other bytes remain
hash-significant. `.gitattributes` also requests LF working-tree files, but the
fingerprint rule is authoritative because adding that attribute does not rewrite
files already present in an existing checkout.

## Offline workflow

Run commands from the repository root. These commands read local frozen files;
they do not call providers or read credentials. Generated command output under
`tmp/` is local-only and ignored by Git.

```powershell
python backend/tests/reference_data_tools/source_facts.py `
  --output tmp/phase-2i5/source-facts.json

python backend/tests/reference_data_tools/worksheet.py `
  tmp/phase-2i5/source-facts.json `
  --dataset openaq `
  --json-output tmp/phase-2i5/openaq-worksheet.json `
  --markdown-output tmp/phase-2i5/openaq-worksheet.md
```

The extractor resolves restricted data from
`COMPASSAQ_RESTRICTED_REFERENCE_DATA_ROOT` first and then the checked-in
restricted fixture. It skips the restricted dataset when neither exists unless
`REQUIRE_RESTRICTED_REFERENCE_DATA=true`.

The current-output reporter requires the backend dependencies, including
Alembic. The production migration chain begins with PostgreSQL-only extension
and enum operations, so the SQLite reporter asks Alembic to generate the current
ORM schema into a new temporary database and stamps it at the production head.
It does not bypass or rewrite a migration. The reporter refuses to write beneath
the expected-results tree:

```powershell
python backend/tests/reference_data_tools/current_observations.py `
  --output tmp/phase-2i5/current-observations.json

python backend/tests/reference_data_tools/discrepancy_report.py `
  tmp/phase-2i5/openaq-worksheet.json `
  tmp/phase-2i5/current-observations.json `
  --output tmp/phase-2i5/openaq-discrepancies.json
```

An analyst completes the derivation steps and expected fields without copying
current CompassAQ output, records a decision and comments, and supplies the
canonical derivation hash. The approved-candidate tool mechanically adds the
explicit review record without deriving or changing expected values:

```powershell
python backend/tests/reference_data_tools/approved_bundle.py `
  --worksheet tmp/phase-2i5/openaq-worksheet.json `
  --source-facts tmp/phase-2i5/source-facts.json `
  --artifact-root tmp/phase-2i5 `
  --reviewer "Named analyst or organization" `
  --reviewed-at "2026-08-12T06:53:00-07:00" `
  --comments "Meaningful analyst review comments" `
  --output tmp/phase-2i5/openaq-approved-candidate.json
```

Promotion is then explicit:

```powershell
python backend/tests/reference_data_tools/promotion.py `
  tmp/phase-2i5/openaq-approved-candidate.json `
  backend/tests/fixtures/reference_data/expected/public/openaq/approved.json `
  --artifact-root tmp/phase-2i5 `
  --expected-root backend/tests/fixtures/reference_data/expected
```

Promotion never overwrites an existing expectation and rejects any candidate
that contains current implementation observations. Conformance tests load only
`analyst_approved_expectations`; candidates, worksheets, implementation output,
stale hashes, tampered derivations or expected results, and changed frozen
measurements fail closed.

## Philippine DENR-EMB candidate version

The Philippine AQI work adds an independent, standard-library-only derivation in
`backend/tests/reference_data_tools/philippines_denr_independent.py`. It reads the
existing frozen OpenAQ and PurpleAir measurement files, verifies their hashes,
uses zero provider calls, and produces three candidate completed-Manila-day
cases: OpenAQ PM2.5, PurpleAir PM2.5, and PurpleAir PM10. It does not import the
production Philippine calculation or service modules.

This candidate is deliberately marked `candidate_awaiting_analyst_approval`.
It must receive a named analyst review, discrepancy review, and promotion into a
new immutable bundle version before it can become a release conformance
expectation. Existing `phase2i5-approved.json` bundles remain immutable and must
not be reused or rewritten for the Philippine methodology.

The pre-approval review run also creates an independent synthetic matrix for
regulatory boundaries and policy cases. The synthetic derivation does not
import application, database, provider, or network modules. Candidate and
production observations remain separate, and discrepancy tooling never changes
either side automatically.

```powershell
python backend/tests/reference_data_tools/philippines_denr_synthetic_independent.py `
  --output tmp/philippines-aqi-review/synthetic-candidates.json

python backend/tests/reference_data_tools/philippines_denr_current_observations.py `
  --synthetic-candidates tmp/philippines-aqi-review/synthetic-candidates.json `
  --output tmp/philippines-aqi-review/implementation-observations.json

python backend/tests/reference_data_tools/philippines_denr_discrepancy_report.py `
  backend/tests/fixtures/reference_data/provenance/philippines_denr/candidate.json `
  tmp/philippines-aqi-review/implementation-observations.json `
  --output tmp/philippines-aqi-review/discrepancy-report.json

python backend/tests/reference_data_tools/philippines_denr_synthetic_discrepancy.py `
  tmp/philippines-aqi-review/synthetic-candidates.json `
  tmp/philippines-aqi-review/implementation-observations.json `
  --output tmp/philippines-aqi-review/synthetic-discrepancy-report.json
```

The reviewer-facing JSON and Markdown package is generated outside the expected
results tree with `promotion_allowed=false` and null approval fields:

```powershell
python backend/tests/reference_data_tools/philippines_denr_review_package.py `
  --candidate backend/tests/fixtures/reference_data/provenance/philippines_denr/candidate.json `
  --synthetic-candidates backend/tests/fixtures/reference_data/provenance/philippines_denr/synthetic-candidates.json `
  --implementation tmp/philippines-aqi-review/implementation-observations.json `
  --discrepancy tmp/philippines-aqi-review/discrepancy-report.json `
  --synthetic-discrepancy tmp/philippines-aqi-review/synthetic-discrepancy-report.json `
  --integrity tmp/philippines-aqi-review/integrity-verification.json `
  --output-json tmp/philippines-aqi-review/analyst-review-package.json `
  --output-markdown tmp/philippines-aqi-review/analyst-review-package.md
```

Promotion must stop until a human supplies reviewer identity, a timezone-aware
timestamp, an `approved` or `rejected` decision, meaningful comments, and any
explicit exceptions. Those values must be recorded verbatim. They must never be
inferred from the implementation result or invented by an agent. A new
Philippine approved bundle may be created only after approval; the existing
Phase 2I bundles and frozen measurement files remain unchanged.

## Philippine DENR-EMB approved bundle

Spheros Environmental approved all 106 reviewed Philippine cases on
`2026-08-12T12:15:00-07:00`, with no exceptions. The exact approval text is
retained in the hash-bound provenance file
`backend/tests/fixtures/reference_data/provenance/philippines_denr/approval-record.json`
and copied verbatim into every promoted case review.

The approved bundle is:

`backend/tests/fixtures/reference_data/expected/philippines_denr/denr-emb-aqi-2021-approved-v1.json`

Its SHA-256 is
`57dd36c08c1475f2889d69ce4cb91b7025795f01041b42f3d61611e3c51b08f0`.
It uses the versioned multi-source branch of the existing Phase 2I promotion,
validation, and loader code. The earlier single-provider schema and approved
OpenAQ/PurpleAir bundles remain unchanged. The Philippine bundle adds stronger
bindings needed for this standard: both frozen measurement hashes, both
production-code-free candidate artifacts, the approved review package, each
source-case hash, each derivation hash, and the approval record.

`backend/tests/test_philippines_denr_approved_conformance.py` loads only this
promoted artifact as the oracle. It reconstructs the frozen Manila database and
runs production qualification, calculation, service selection, and API
serialization before comparing results. Synthetic edge cases are passed through
the production domain and completeness paths without duplicating the Philippine
formula in the assertion. The loader reads only the small hash-bound provenance
set under `backend/tests/fixtures/reference_data/provenance/`; generated review
reports and visual evidence are not required.
