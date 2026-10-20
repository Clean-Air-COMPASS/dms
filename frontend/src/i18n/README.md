# CompassAQ internationalization

CompassAQ statically bundles English (`en`) and neutral Latin American Spanish (`es`) through i18next. English in `locales/en` is the semantic copy source of truth; `locales/es` has the same 13 namespaces and exact key, interpolation, and plural structure. No translation resources are downloaded at runtime.

## Resources and new UI copy

Namespaces are `common`, `landing`, `map`, `analytics`, `admin`, `devices`, `dataSources`, `qualityControl`, `events`, `users`, `auth`, `setup`, and `aq`. Put ordinary visible and accessibility copy in the most specific namespace, use semantic stable keys, and update English and Spanish together. Use i18next plural forms for counts and preserve every `{{interpolation}}` or rich-text placeholder.

To add a language, copy the complete English namespace tree, translate every non-empty leaf, register the static imports in `resources.ts`, add the code to the supported and enabled lists only after parity validation, and test preference resolution, `<html lang>`, formatting, and representative layouts.

## Terminology

Use consistent product terminology: *Fuente de datos*, *Dispositivo*, *Sensor*, *Medición/Mediciones*, *Resolución temporal*, *Agregación*, *Promedio móvil*, *Día completo*, *Regla(s) de control de calidad*, *Importación*, *Índice de calidad del aire*, *Monitor de referencia*, *Completitud*, and *Cobertura*.

U.S. EPA AQI categories use the established AirNow Spanish labels: *Bueno*, *Moderado*, *Insalubre para grupos sensibles*, *Insalubre*, *Muy insalubre*, and *Peligroso*. EEA category labels are neutral CompassAQ UI translations, not claimed official EEA Spanish terminology. Philippine DENR category and caution labels are likewise CompassAQ translations unless an authoritative Spanish DENR source is added. The stable standard, product, category, coverage, aggregation, and exclusion codes remain authoritative.

`NowCast` is a methodology/product name and remains untranslated. CompassAQ-authored explanatory copy must not be presented as official regulatory wording.

## Preference precedence

- Authenticated: user override, then system default, then English.
- Setup: explicit local preference, then enabled browser locale, then English. Setup completion explicitly persists the selected system default.
- Signed out: explicit local preference, then configured system default, then enabled browser locale, then English.

The anonymous preference key is `compassaq.language`. Selecting “Use system default” clears the authenticated user override. Browser detection is never persisted automatically. Invalid or unsupported locales fall back to English.

## Intentional exclusions

Do not translate provider or organization names, methodology IDs, product/provider codes, API/database identifiers, URLs, routes, filenames, machine-readable CSV headers or values, canonical units, parameter/scientific symbols, coordinate serialization, ISO timestamps, importer logs, job diagnostics, plugin output, stdout/stderr, or raw technical event messages. Use a reason-bearing `i18n-ignore` annotation only when such content would otherwise trigger validation.

Translations provide labels only. Breakpoints, calculations, completeness and coverage rules, colors, rounding, precision, timezone semantics, and canonical units remain in the existing scientific/domain implementation. Unknown stable codes use localized diagnostic copy that retains the raw code.

## Validation

Run `npm run i18n:check`, lint, the full frontend test suite, and the production build. The checker validates locale structure, interpolation and plural parity, static keys, and obvious hardcoded UI/accessibility strings. Visually inspect affected screens in every enabled language at representative desktop, tablet, and mobile widths; allow wrapping or wider controls and never reduce typography to fit a translation.
