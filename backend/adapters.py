"""Protocol-neutral SDK for sensor calibration adapters."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AdapterContext:
    sensor_id: str
    unit: str
    configuration: dict[str, Any]


@dataclass(frozen=True)
class Measurement:
    value: float
    unit: str
    quality: str = "good"


@dataclass(frozen=True)
class AdapterProposal:
    sensor_id: str
    observed_value: float
    reference_value: float
    offset: float
    unit: str


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    measured_value: float | None
    message: str = ""


class SensorAdapter(Protocol):
    def discover(self) -> list[str]: ...
    def connect(self, context: AdapterContext) -> None: ...
    def read(self, context: AdapterContext) -> Measurement: ...
    def propose(self, context: AdapterContext, reference: Measurement) -> AdapterProposal: ...
    def apply(self, context: AdapterContext, proposal: AdapterProposal) -> None: ...
    def verify(self, context: AdapterContext, proposal: AdapterProposal) -> VerificationResult: ...
    def close(self) -> None: ...


_ADAPTERS: dict[str, type] = {}


def register_adapter(name: str):
    if not name:
        raise ValueError("adapter name is required")

    def decorator(adapter_type: type) -> type:
        _ADAPTERS[name] = adapter_type
        return adapter_type

    return decorator


def get_adapter(name: str) -> type:
    try:
        return _ADAPTERS[name]
    except KeyError as error:
        raise KeyError(f"adapter not registered: {name}") from error


@register_adapter("simulator")
class SimulatorSensorAdapter:
    """Minimal SDK example; physical writes remain deliberately unsupported."""

    def discover(self) -> list[str]:
        return []

    def connect(self, _context: AdapterContext) -> None:
        return

    def read(self, context: AdapterContext) -> Measurement:
        return Measurement(float(context.configuration.get("observed_value", 23.5)), context.unit)

    def propose(self, context: AdapterContext, reference: Measurement) -> AdapterProposal:
        observed = self.read(context)
        if observed.unit != reference.unit:
            raise ValueError("measurement units do not match")
        return AdapterProposal(context.sensor_id, observed.value, reference.value, reference.value - observed.value, observed.unit)

    def apply(self, _context: AdapterContext, _proposal: AdapterProposal) -> None:
        raise RuntimeError("physical adapter writes are disabled")

    def verify(self, _context: AdapterContext, _proposal: AdapterProposal) -> VerificationResult:
        return VerificationResult(False, None, "physical verification is unavailable in simulator mode")

    def close(self) -> None:
        return


@register_adapter("modbus")
class ReadOnlyModbusAdapter(SimulatorSensorAdapter):
    """Registration boundary for future vendor-specific Modbus implementations."""

    def apply(self, _context: AdapterContext, _proposal: AdapterProposal) -> None:
        raise RuntimeError("physical Modbus writes are disabled")
