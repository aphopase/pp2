# Adapter SDK

Adapters implement the protocol-neutral contract in `backend.adapters.SensorAdapter`:

```python
from backend.adapters import AdapterContext, Measurement, SimulatorSensorAdapter, register_adapter

@register_adapter("my_sensor")
class MySensorAdapter(SimulatorSensorAdapter):
    def read(self, context: AdapterContext) -> Measurement:
        return Measurement(24.2, context.unit)
```

Use `get_adapter("my_sensor")` from campaign configuration. The SDK separates discovery, connection, reading, proposal, application, verification, and cleanup so a future gateway can replace the simulator without changing campaign orchestration.

Physical `apply()` methods must remain disabled until the device register map, safety limits, read-back, rollback, and hardware-in-the-loop test plan are approved.
