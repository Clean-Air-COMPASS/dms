Plugin SDK & quick example

This file gives a short example for data scientists on how to use the SDK
helpers in `backend/qaqc/sdk.py` to write a simple plugin.

Example: simple MaxValue plugin (pseudocode)

```python
from backend.qaqc.sdk import ApiClient, records_to_dataframe, ensure_numeric

# Build a tiny SDK-based plugin
class MaxValuePlugin:
    name = "MaxValuePlugin"
    required_access = "api-only"  # or db-read if you need a DB session

    def __init__(self, api_base: str = "http://localhost:8000"):
        self.api = ApiClient(api_base)

    def apply(self, records, context):
        # fetch rules via API
        rules = self.api.get_json("/admin/qc_rules")

        # pandas friendly
        df = records_to_dataframe(records)
        if hasattr(df, "value"):
            vals = ensure_numeric(df["value"])  # returns a Series or list
        else:
            vals = [r.get("value") for r in records]

        decisions = []
        for rec, v in zip(records, vals):
            if v is None:
                continue
            # pick the best rule for this rec (pseudo)
            applicable = [r for r in rules if r.get("config", {}).get("max_value") is not None]
            if not applicable:
                continue
            max_v = applicable[0]["config"]["max_value"]
            if float(v) > float(max_v):
                decisions.append({
                    "measurement_id": rec.get("measurement_id") or rec.get("id"),
                    "decision": "fail",
                    "reason": f"{v} > {max_v}",
                })
            else:
                decisions.append({
                    "measurement_id": rec.get("measurement_id") or rec.get("id"),
                    "decision": "pass",
                })
        return decisions
```

Notes
- Prefer `ApiClient` for portability between environments. Use `db-read` only when necessary.
- The SDK helpers aim to be tiny and easy to understand by non-engineers. Add to them only when multiple plugins need a common helper.
