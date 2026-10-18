"""Read-only Modbus calibration preview; physical writes are intentionally disabled."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from plugins.calibration import CalibrationProposal, ReferenceCalibrationPlugin, ReferencePoint


class ModbusTransport(Protocol):
    def read_holding_register(self, slave_id: int, address: int) -> int:
        """Read one holding register without changing device state."""


@dataclass(frozen=True)
class RegisterMap:
    slave_id: int
    measurement_register: int
    calibration_register: int
    unit: str
    scale: float = 0.1
    decode_offset: float = 0.0
    minimum_raw: int = -32768
    maximum_raw: int = 32767
    minimum_calibration: int = -500
    maximum_calibration: int = 500

    def __post_init__(self) -> None:
        if not 1 <= self.slave_id <= 247:
            raise ValueError("slave_id must be between 1 and 247")
        if not 0 <= self.measurement_register <= 65535:
            raise ValueError("measurement register is out of range")
        if not 0 <= self.calibration_register <= 65535:
            raise ValueError("calibration register is out of range")
        if self.scale == 0 or self.minimum_raw > self.maximum_raw:
            raise ValueError("invalid register scaling or raw range")
        if self.minimum_calibration > self.maximum_calibration:
            raise ValueError("invalid calibration range")


@dataclass(frozen=True)
class DryRunWritePlan:
    slave_id: int
    register: int
    original_raw_value: int
    proposed_raw_value: int
    reason: str = "dry-run only; no hardware write performed"


class InMemoryModbusTransport:
    """Deterministic read-only transport used for tests and development."""

    def __init__(self, registers: dict[tuple[int, int], int]) -> None:
        self._registers = dict(registers)

    def read_holding_register(self, slave_id: int, address: int) -> int:
        try:
            return self._registers[(slave_id, address)]
        except KeyError as error:
            raise ValueError("register was not found") from error

    def current_value(self, slave_id: int, address: int) -> int:
        return self.read_holding_register(slave_id, address)


class ModbusCalibrationAdapter:
    def __init__(self, transport: ModbusTransport, register_map: RegisterMap) -> None:
        self.transport = transport
        self.register_map = register_map
        self.plugin = ReferenceCalibrationPlugin()

    def read_value(self) -> float:
        raw = self.transport.read_holding_register(
            self.register_map.slave_id, self.register_map.measurement_register
        )
        if not self.register_map.minimum_raw <= raw <= self.register_map.maximum_raw:
            raise ValueError("measurement register value is out of range")
        return raw * self.register_map.scale + self.register_map.decode_offset

    def preview(self, tenant_id: str, device_id: str, reference: ReferencePoint) -> tuple[CalibrationProposal, DryRunWritePlan]:
        observed = self.read_value()
        proposal = self.plugin.propose(
            tenant_id=tenant_id,
            device_id=device_id,
            observed_value=observed,
            reference=reference,
            expected_unit=self.register_map.unit,
            max_offset=abs(self.register_map.maximum_calibration * self.register_map.scale),
        )
        raw_offset = round(proposal.offset / self.register_map.scale)
        proposed_raw = raw_offset
        if not self.register_map.minimum_calibration <= proposed_raw <= self.register_map.maximum_calibration:
            raise ValueError("proposed calibration register value is out of range")
        original = self.transport.read_holding_register(
            self.register_map.slave_id, self.register_map.calibration_register
        )
        return proposal, DryRunWritePlan(
            slave_id=self.register_map.slave_id,
            register=self.register_map.calibration_register,
            original_raw_value=original,
            proposed_raw_value=proposed_raw,
        )

    def write(self, _plan: DryRunWritePlan) -> None:
        raise RuntimeError("physical Modbus writes are disabled in dry-run mode")
