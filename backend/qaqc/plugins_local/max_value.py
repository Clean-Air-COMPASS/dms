from qaqc.plugin import QCPlugin
from qaqc.registry import register
from qaqc.types import QCDecision, QCRecord

class MaxValuePlugin(QCPlugin):
    name = "max_value"
    display_name = "max_value"
    long_description = "Re-added max plugin"
    param_schema = {}                                       

    def apply(self, records, context):
        out = []
        for r in records:
            out.append(QCDecision(
                sensor_id=r.sensor_id,
                parameter_id=r.parameter_id,
                value=r.value,
                unit_id=r.unit_id,
                observed_at=r.observed_at,
                is_valid=True,
                flags=[],
                plugin_name=self.name,
            ))
        return out

plugin = MaxValuePlugin()
register(plugin)
