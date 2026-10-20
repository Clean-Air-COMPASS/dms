# AirGradient fixtures

`authenticated_place.json` and `authenticated_locations_current.json` are the
existing synthetic authenticated-endpoint fixtures.

`public_reference_identity_20260911.json` preserves three public responses
captured once on 2026-09-11 at about 05:34 UTC from
`https://api.airgradient.com/public/api/v1/world/locations/{locationId}/measures/current`.
The IDs were 58376, 175911, and 160791. No token was sent. The file is a dated
regression fixture, not a guarantee that a provider location will never move.
Runtime geographic validation remains necessary on every public import.

Data provided by [AirGradient](https://www.airgradient.com), under
[CC-BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
Contributor names supplied by the provider (raflima and Manila Observatory)
are retained in `publicContributorName`; the returned contributor URLs were
null. Observations, nulls, location metadata, and timestamps are unchanged.
