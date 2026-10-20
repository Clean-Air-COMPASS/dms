# CompassAQ QC plugin contract

QC plugins are trusted, deployment-installed Python packages. Administrators
cannot upload, create, overwrite, or delete executable plugin source through
the web application.

## Canonical working example

Max Value QC Check is CompassAQ's bundled reference implementation of a
deployment-installed QC plugin. Its
separately installable package lives at
[`backend/plugins/max_value`](../plugins/max_value/). It is not imported or
registered by the built-in plugin module. Its `pyproject.toml` declares:

```toml
[project.entry-points."aq_platform.qaqc_plugins"]
max_value = "compassaq_max_value.plugin:plugin"
```

At startup, CompassAQ reads the `aq_platform.qaqc_plugins` entry-point group
from installed Python distribution metadata, loads the exported `plugin`
object, validates its contract, and atomically publishes the complete registry.
Advanced diagnostics report `max_value` with the `entry_point` origin and the
`compassaq-max-value` distribution. Ordinary policy APIs continue to present it
uniformly as a QC check.

Read
[`compassaq_max_value/plugin.py`](../plugins/max_value/src/compassaq_max_value/plugin.py)
as the canonical simple implementation. It retrieves each aligned effective
policy with `effective_policy_for_record`, reads the resolver-supplied `max`
setting, and returns exactly one `QCDecision` per measurement. It contains no
database access, QC-rule lookup, precedence, unit conversion, persistence, or
measurement invalidation logic.

## Execution model

CompassAQ owns policy resolution. Before invoking a plugin, it resolves:

- enabled state;
- failure action;
- inherited settings;
- policy and sensor units;
- safe unit conversion;
- property-level provenance.

A plugin only evaluates the aligned effective policy it receives in
`context["effective_policies"]`. It must not query `QCRule`, choose precedence,
invent fallback settings, invalidate a measurement, or persist QC results.

The pipeline interprets `QCDecision.is_valid` as the check outcome and applies
the policy's `flag_for_review` or `mark_invalid` failure action.

## Required metadata

```python
from qaqc.sdk import effective_policy_for_record, indeterminate_decision
from qaqc.types import QCDecision


class RateOfChangePlugin:
    name = "rate_of_change"
    version = "1.0.0"
    qc_api = 1
    required_access = "api-only"
    display_name = "Rate of change"
    description = "Detects changes larger than the configured rate"
    long_description = "Compares the current value with an aligned prior value."
    param_schema = {
        "maximum_change": {
            "type": "number",
            "label": "Maximum change",
            "help": "Largest accepted change in the policy unit",
            "required": True,
        }
    }
    unit_settings = ("maximum_change",)
    overview = {
        "visible": True,
        "label": "Rate of change",
        "order": 100,
        "summary_setting": "maximum_change",
    }

    def apply(self, records, context):
        decisions = []
        for index, record in enumerate(records):
            policy = effective_policy_for_record(context, index)
            if policy is None:
                decisions.append(
                    indeterminate_decision(
                        "missing_effective_policy",
                        "Rate-of-change policy was not supplied",
                    )
                )
                continue
            maximum_change = policy.evaluation_settings["maximum_change"]
            # Example only: obtain the prior value through an explicitly
            # declared mechanism before evaluating the real check.
            decisions.append(QCDecision(True, [], "info"))
        return decisions


plugin = RateOfChangePlugin()
```

`param_schema` setting types are `boolean`, `integer`, `number`, and `string`.
Every setting requires a human label and help text. `unit_settings` names the
numeric settings that CompassAQ must convert into the sensor's evaluation unit.

## Overview metadata and deterministic ordering

Every installed plugin participates in the same parameter overview and policy
editor discovery path. The optional `overview` object controls the compact
parameter-table presentation; it does not contain React components or other
rendering instructions.

| Field | Default | Meaning |
| --- | --- | --- |
| `visible` | `true` | Whether the check receives a column on the parameter overview. Set this to `false` only when a parameter-level summary is operationally misleading. |
| `label` | `display_name` | Short human-facing column label. Plugin names are supplied by the plugin and are not translated by CompassAQ. |
| `order` | `1000` | Integer sort position. Ties use `name`, so filesystem and import order never affect the UI. |
| `summary_setting` | `None` | One declared `param_schema` setting to show as the compact summary value. |

`summary_setting` must name a declared setting. When it also appears in
`unit_settings`, CompassAQ displays the configured value with its applicable
policy unit. A visible check without a summary setting displays `On` or `Off`.
The generic cell states are:

- configured summary value, with a unit when applicable;
- `On` for an enabled check without a scalar summary;
- `Off` for an explicitly disabled check;
- `Not configured` when no applicable policy exists; and
- `Unavailable` when a configured check's package is unavailable.

CompassAQ's current metadata uses order 10 for Minimum, 20 for Maximum, and 30
for Baseline Drift. A new plugin should choose a stable integer and must not
depend on entry-point enumeration order. The overview intentionally allows a
wide table as more checks are installed.

Baseline Drift has one documented host-side presentation adapter that adds
lower-scope enabled counts to its cell. That adapter is a UX enhancement only:
it is not needed for plugin discovery, a column, editing, execution, Events, or
provenance. Max Value uses the ordinary summary-setting renderer.

`required_access` is one of:

- `api-only`: the database session is omitted from plugin context;
- `db-read`: the session is supplied for checks that need measurement history;
- `db-write`: rejected unless the server operator explicitly sets
  `QC_ALLOW_DB_WRITE_PLUGINS=true`.

Database access is trusted code access. `db-read` communicates intent but is
not a SQL sandbox.

## Installation

Publish the plugin as a Python package with this entry point:

```toml
[project.entry-points."aq_platform.qaqc_plugins"]
rate_of_change = "my_compassaq_plugin:plugin"
```

Install the package in the backend environment and restart the backend. An
administrator may use `POST /admin/plugins/reload` to re-read already installed
entry points without restarting. Duplicate check codes, unsupported API
versions, malformed schemas, and unapproved database-write access are rejected
with diagnostics at `GET /admin/plugins`.

CompassAQ's normal backend dependency installation includes the reference
package through the repository-relative `./plugins/max_value` line in
`backend/requirements.txt`. The backend Dockerfile copies that package before
running `pip install`, so both the API and scheduler images contain the same
installed distribution. No plugin source is runtime-mounted or copied into a
writable plugin directory.

`POST /admin/plugins/reload` only re-enumerates packages already installed in
the running Python environment. It does not download, install, upgrade, or
remove a package. Deployment operators must install or remove package code by
rebuilding/redeploying the backend environment, then restart or reload
discovery as appropriate.

No frontend change is needed for a normal new QC check. After discovery:

1. `GET /admin/qc/checks` returns validated metadata;
2. the Quality Control overview creates the column from `overview`;
3. parameter, source+parameter, and sensor editors build fields from
   `param_schema` and `unit_settings`;
4. ingestion resolves policy and invokes the registered `apply` method;
5. failed or indeterminate results persist the check code, settings, policy
   provenance, and plugin version;
6. Admin Events uses `display_name`; and
7. Administrator Summary uses `display_name` with a generic failure sentence.

The email renderer has richer explanations for the known range and Baseline
Drift result schemas. An unknown plugin still receives a correct generic
sentence without a renderer change, such as: “3 PM2.5 measurements at Site A
were flagged for review by the Spike Detection QC Check.”

If a package is removed while policies remain, CompassAQ does not substitute a
core implementation. Policy remains traceable, ingest records an explicit
`plugin_unavailable` indeterminate result, configured editor cards show the
unavailable state, and persisted historical Events retain their recorded check
code and plugin version. A third-party overview column is present only while
its metadata is discoverable; CompassAQ-supplied default policy data keeps an
unavailable bundled reference check diagnosable.

To build a new plugin, copy the reference package structure and change its
distribution name, import package, entry point, check metadata, typed setting
schema, and evaluation logic. Do not copy a built-in implementation or add the
new check to `BUILT_IN_PLUGINS`.

From `backend/`, install and test the shipped reference package with:

```powershell
python -m pip install -r requirements.txt
python -m pytest tests/test_max_value.py tests/test_reference_max_value_plugin.py tests/test_reference_threshold_plugin.py
```

The second test module verifies the installed distribution's real entry point,
validated non-built-in origin, reload behavior, and check metadata. The shared
ingest acceptance and missing-plugin behavior are covered in
`tests/test_qc_ingest_policy.py`.

`tests/plugins/reference_threshold` is a true fourth, test-only package. Its
acceptance test exposes standard Python distribution metadata in an isolated
directory, lets the ordinary entry-point enumerator discover it, proves the
metadata/API/editor/execution/persistence/Events/email path, removes it, and
verifies explicit unavailable behavior. The package is not installed in clean
production deployments.

## Result contract

`apply(records, context)` must return exactly one `QCDecision` per input record.
Malformed or misaligned output becomes an `invalid_plugin_result`
indeterminate outcome. Exceptions become `plugin_error`. Neither outcome adds
a QC flag or invalidates the measurement.
