"""Deterministic simulator used until physical sensors are available."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterator

from shared.models import Telemetry


@dataclass
class SimulatorConfig:
    tenant_id: str = "org_demo"
    site_id: str = "site_demo"
    gateway_id: str = "gateway_demo"
    device_count: int = 2
    start_time: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc)


class SimulatorAdapter:
    """Emit stable measurements and a repeatable anomaly for tests and demos."""

    def __init__(self, config: SimulatorConfig | None = None) -> None:
        self.config = config or SimulatorConfig()
        self.sequence = 0
        self.tick = 0

    def readings(self, ticks: int = 1) -> Iterator[Telemetry]:
        for _ in range(ticks):
            event_time = self.config.start_time + timedelta(minutes=self.tick)
            for device_number in range(1, self.config.device_count + 1):
                device_id = f"motor_{device_number:02d}"
                # The second motor enters an abnormal high-power state at tick 3.
                power = 10.0 + device_number
                if device_number == 2 and self.tick >= 3:
                    power = 22.0
                yield self._telemetry(device_id, "power", power, "kW", event_time)
                yield self._telemetry(
                    device_id, "temperature", 38.0 + device_number, "degC", event_time
                )
            self.tick += 1

    def _telemetry(
        self,
        device_id: str,
        measurement: str,
        value: float,
        unit: str,
        event_time: datetime,
    ) -> Telemetry:
        self.sequence += 1
        timestamp = event_time.isoformat().replace("+00:00", "Z")
        return Telemetry(
            tenant_id=self.config.tenant_id,
            site_id=self.config.site_id,
            gateway_id=self.config.gateway_id,
            device_id=device_id,
            measurement=measurement,
            value=value,
            unit=unit,
            quality="good",
            event_time=timestamp,
            ingest_time=timestamp,
            gateway_sequence=self.sequence,
            metadata={"source_protocol": "simulator"},
        )
