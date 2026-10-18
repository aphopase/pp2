"""Small custom adapter SDK example."""
from backend.adapters import AdapterContext, Measurement, SimulatorSensorAdapter, register_adapter


@register_adapter("example_sensor")
class ExampleSensorAdapter(SimulatorSensorAdapter):
    def read(self, context: AdapterContext) -> Measurement:
        return Measurement(24.2, context.unit)


if __name__ == "__main__":
    print("Registered custom adapter: example_sensor")
