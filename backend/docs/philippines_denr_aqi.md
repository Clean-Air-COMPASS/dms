# Philippines Air Quality Index methodology

Research checked: 12 August 2026. National calculation timezone: `Asia/Manila`.

## Methodology decision and sources

CompassAQ identifies this standard as `philippines_denr`, with methodology
`philippines_denr_aqi` version `denr_emb_aqi_2021`. It is a pollutant-specific
implementation; it does not claim an official site-wide or overall index.

The consolidated methodology uses:

1. DENR Administrative Order 2000-81, *Implementing Rules and Regulations for
   Republic Act No. 8749*, 7 November 2000, Annex A. It supplies the categories,
   PM10, SO2, ozone, CO and NO2 tables, special ozone/NO2 rules, and cautionary
   statements: <https://air.emb.gov.ph/wp-content/uploads/2016/04/DAO-2000-81.pdf>.
2. DENR Administrative Order 2020-14, *Establishing the Breakpoints for
   Particulate Matter 2.5 Air Quality Index*, approved 21 October 2020. It
   supplies the PM2.5 table and statements:
   <https://air.emb.gov.ph/wp-content/uploads/2021/01/DAO-2020-14-PM-2.5-Signed.pdf>.
3. EMB Memorandum Circular 2021-07 and the attached *Procedural Manual on Data
   Handling Conventions for Criteria Air Pollutants*, 3 May 2021. Chapter 2
   supplies data-capture rules; chapter 5 supplies interpolation, consolidated
   tables, and worked examples:
   <https://www.emb.gov.ph/wp-content/uploads/2022/11/EMB-MC-2021-07_FINAL-MANUAL-ON-DATA-HANDLING.pdf>.
4. DENR Memorandum Circular 2005-013, the earlier representative-day source:
   <https://air.emb.gov.ph/wp-content/uploads/2019/08/DMC-2005-013.pdf>.

The current EMB policy register was rechecked on 12 August 2026. It still lists
DAO 2020-14 and MC 2021-07 and did not list a later superseding national AQI
methodology: <https://air.emb.gov.ph/laws-policies-for-air-quality-management/>.

## Categories and breakpoints

| AQI | Code and label | Color |
|---|---|---|
| 0–50 | `good` — Good | `#00E400` |
| 51–100 | `fair` — Fair | `#FFFF00` |
| 101–150 | `unhealthy_for_sensitive_groups` — Unhealthy for Sensitive Groups | `#FF7E00` |
| 151–200 | `very_unhealthy` — Very Unhealthy | `#FF0000` |
| 201–300 | `acutely_unhealthy` — Acutely Unhealthy | `#8F3F97` |
| 301–500 | `emergency` — Emergency | `#7E0023` |

| Product input | 0–50 / 51–100 / 101–150 / 151–200 / 201–300 / 301–500 |
|---|---|
| PM2.5, completed 24 h, µg/m³ | 0–25 / 25.1–35.0 / 35.1–45.0 / 45.1–55 / 55.1–90 / 91+ |
| PM10, completed 24 h, µg/m³ | 0–54 / 55–154 / 155–254 / 255–354 / 355–424 / 425–504 |
| SO2, completed 24 h, ppm | .000–.034 / .035–.144 / .145–.224 / .225–.304 / .305–.604 / .605–.804 |
| O3, rolling 8 h, ppm | .000–.064 / .065–.084 / .085–.104 / .105–.124 / .125–.374 / use 1 h |
| O3, completed 1 h, ppm | undefined / undefined / .125–.164 / .165–.204 / .205–.404 / .405–.504 |
| CO, rolling 8 h, ppm | 0.0–4.4 / 4.5–9.4 / 9.5–12.4 / 12.5–15.4 / 15.5–30.4 / 30.5–40.4 |
| NO2, completed 1 h, ppm | undefined / undefined / undefined / undefined / .65–1.24 / 1.25–1.64 |

PM2.5 is truncated to one decimal and PM10 to an integer before band selection.
Gas concentrations are compared as exact decimals because the manual supplies no
gas truncation rule. Interpolation uses the manual equation and is quantized to
two decimal places with half-up ties. The latter tie rule is explicit CompassAQ
policy; the two-decimal precision follows the manual's PM10 (210 → 128.22) and
ozone (0.14 → 206.96) examples.

Published decimal gaps are unavailable (`published_breakpoint_gap`). NO2 below
0.65 ppm is unavailable (`subindex_not_defined_for_concentration`). Values above
a bounded highest table and PM2.5 at 91 µg/m³ or higher retain the official
Emergency category but have no numeric AQI (`category_only`,
`above_published_numeric_range`). No extrapolation or clamping is performed.
When 8-hour ozone exceeds 0.374 ppm, an eligible corresponding one-hour result is
mandatory; otherwise the result is `no_applicable_ozone_candidate`.

## Cautionary statements

The API stores methodology references but this release intentionally does not add
health-advisory UI. The full source statements remain locally traceable in
`CAUTIONARY_STATEMENTS_BY_POLLUTANT` in the Philippine domain module.

For PM2.5, PM10, SO2, ozone and NO2: Good and Fair have no statement. Unhealthy
for Sensitive Groups directs people with respiratory disease such as asthma to
limit outdoor exertion. Very Unhealthy advises pedestrians to avoid heavy traffic,
people with heart or respiratory disease to stay indoors and rest, postponement
of unnecessary trips, and voluntary vehicle-use restriction. Acutely Unhealthy
advises limiting outdoor exertion, staying indoors for heart or respiratory
disease, postponing trips, and possible restriction of vehicles and industry.
Emergency directs everyone indoors with doors and windows closed unless heat
stress is possible, prohibits non-emergency vehicle use, and curtails industry
except activity vital to public safety and health.

CO has distinct statements. Unhealthy for Sensitive Groups and Acutely Unhealthy
direct people with cardiovascular disease such as angina to limit heavy exertion
and avoid CO sources such as heavy traffic. Very Unhealthy directs smokers to
refrain from smoking. Emergency directs everyone to avoid exertion and CO sources
and to remain indoors and rest.

## Completeness and time

Source rule: a representative hour contains at least 45 valid minutes; an
8-hour mean contains at least six representative hours; a representative day
contains at least 18 representative hours, at least six in each Manila-time
block 00:00–08:00, 08:00–16:00 and 16:00–24:00, and no more than two consecutive
missing hours. Percentage values ending in .5 round upward for comparison.

CompassAQ policy: those representativeness rules are applied to the matching AQI
products because a separate AQI completeness chapter is not published. Verified
provider-hourly input qualifies one represented hour. Regular sub-hourly input
is assigned to provider-neutral expected positions; a documented two-minute
stream therefore requires 23 of 30 positions (46 minutes), while 22 positions
represent only 44 minutes. Duplicate, invalid, and off-frequency observations
remain in provenance and can prevent qualification when too few unambiguous
positions remain; ambiguous timestamp metadata blocks the stream. Missing values
are never substituted.

Completed days always run midnight-to-midnight in `Asia/Manila`. Ozone and CO use
rolling eight-hour windows ending at each completed Philippine clock hour. NO2
uses a completed Philippine clock hour. UTC boundaries are also returned.

## Units

Particulates normalize to µg/m³. `ug_m3` is exact and `mg_m3` multiplies by
1,000. Explicit normal-condition `ug_ncm` is not silently treated as ambient
µg/m³ because conversion requires temperature and pressure context. Gases
normalize to ppm: ppm is exact and ppb divides by 1,000. Gas mass units are
rejected. The dimensionally inconsistent ozone mass-conversion line in one
manual copy is not implemented.

## Products, limitations, and differences

The supported products are completed-day PM2.5, PM10 and SO2; latest rolling
8-hour ozone and CO; and latest completed-hour NO2. `dominant_pollutants` is
always empty. TSP is deferred because CompassAQ has no canonical TSP parameter.
The optional precautionary ozone-area maximum rule is deferred because no
authoritative area list was found. Operational EMB “hourly AQI” behavior and an
overall/site AQI are also deferred and would require new methodology/product
codes.

Unlike U.S. EPA AQI, this implementation has Philippine labels, breakpoints,
daily rules, ozone switching, and two-decimal output; it does not use NowCast.
Unlike European AQI, it is numeric and has no worst-category overall product.
Ordinary configured measurement aggregation remains separate from regulatory AQI
qualification.

## Manila frozen-data conformance

The immutable source fixtures are not modified. PurpleAir sensor 99177 supplies
PM2.5 and PM10 native two-minute values for two complete candidate Manila dates,
9 and 10 August 2026. OpenAQ location 4565934 supplies only provider-hourly PM2.5
from hardware identified as an AirGradient ONE Generation 9 owned by Manila
Observatory; OpenAQ is the transport provider. Neither source supplies Manila gas
pollutants, and OpenAQ supplies no PM10 sensor. Both devices are low-cost,
non-reference instruments, so results demonstrate deterministic processing only,
not regulatory-monitor conformance.

A new immutable expectation bundle must be produced by an independent derivation
that imports no production Philippine constants or services, reviewed through a
discrepancy report, and approved by an analyst before promotion. Approved tests
must require zero provider calls, unchanged source hashes, and reject
implementation-produced expectations. Existing Phase 2I bundles remain unchanged.

## Maintainer contracts

Current implementation contracts for maintenance; these additions do not report a new runtime acceptance run.

### Qualification and unavailable-state ownership

`philippines_denr_service.qualify_hour` retains rejected, duplicate and unassigned observations in provenance. They block qualification only when too few unambiguous expected positions remain. It does not redefine measurement duration or treat a burst of readings as temporal coverage.

`_unavailable_calculation` delegates result shape and unit/unavailable semantics to the pure `philippines_denr.calculate_component_aqi` contract before attaching service context. An internal sentinel call is not a substituted observation or issued numeric result. Preserve explicit reasons, published gaps, category-only results and the existing `denr_emb_aqi_2021` methodology; do not borrow EPA preprocessing or an EEA overall product.

Source ownership:

- [backend/services/air_quality_index/philippines_denr_service.py](../services/air_quality_index/philippines_denr_service.py) — `_unavailable_calculation`, `qualify_hour`

Existing regression coverage: [test_philippines_denr_aqi.py](../tests/test_philippines_denr_aqi.py). These tests were identified in source; P0 does not rerun application acceptance.
