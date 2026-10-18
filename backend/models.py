"""Validated configuration models for sensor integrations."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

SUPPORTED_PROTOCOLS = {"simulator", "modbus", "ble", "mqtt", "custom"}


@dataclass(frozen=True)
class SensorModel:
    name: str
    protocol: str
    measurement: str
    unit: str
    config: dict

    def __post_init__(self) -> None:
        if not self.name or self.protocol not in SUPPORTED_PROTOCOLS:
            raise ValueError("sensor model name and supported protocol are required")
        if not self.measurement or not self.unit:
            raise ValueError("sensor model measurement and unit are required")


@dataclass(frozen=True)
class CalibrationProfile:
    name: str
    unit: str
    max_offset: float
    tolerance: float

    def __post_init__(self) -> None:
        if not self.name or not self.unit:
            raise ValueError("profile name and unit are required")
        if not all(isfinite(value) and value > 0 for value in (self.max_offset, self.tolerance)):
            raise ValueError("profile limits must be finite and positive")
