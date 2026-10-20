# CompassAQ `max_value` reference plugin

Max Value QC Check is CompassAQ's bundled reference implementation of a
deployment-installed QC plugin. This separately installable package implements
the real `max_value` check and is intentionally absent from CompassAQ's
built-in registry.

The package declares this entry point in `pyproject.toml`:

```toml
[project.entry-points."aq_platform.qaqc_plugins"]
max_value = "compassaq_max_value.plugin:plugin"
```

CompassAQ supplies one resolved effective policy per input record. The plugin
reads only `policy.evaluation_settings["max"]`; it does not query QC rules,
resolve precedence, convert units, choose a failure action, persist results, or
invalidate measurements. The host pipeline owns each of those responsibilities.
Its overview column, short `Maximum` label, deterministic order, unit-aware
summary, editor fields, Events name, email fallback, and provenance all come
from the same validated contract used by independently installed plugins.

If this package is absent, CompassAQ reports `plugin_unavailable`; it never
falls back to a core maximum-value implementation.

From `backend/`, install all backend dependencies (including this local package)
and run its focused tests:

```powershell
python -m pip install -r requirements.txt
python -m pytest tests/test_max_value.py tests/test_reference_max_value_plugin.py
```

Use this package's `pyproject.toml`, `src/` layout, metadata, and `plugin` object
as the starting structure for a new deployment-installed QC check. Change the
distribution, import package, entry-point name, check metadata, typed settings,
and evaluation logic for the new check.
