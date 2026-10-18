"""Load deterministic simulator data into the local backend core."""
from backend.app import IoTCore, Rule
from gateway.simulator import SimulatorAdapter


def build_demo_core() -> IoTCore:
    core = IoTCore()
    core.add_rule(Rule("high-power", "org_demo", "site_demo", "power", ">", 20))
    records = [item.to_dict() for item in SimulatorAdapter().readings(4)]
    core.ingest(records, "org_demo")
    return core


if __name__ == "__main__":
    core = build_demo_core()
    print(f"ingested={len(core.telemetry)} active_alerts={len(core.active_alerts('org_demo'))}")
