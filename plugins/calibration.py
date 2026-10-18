"""Safe reference-point calibration plugin for simulated sensors."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from uuid import uuid4


@dataclass(frozen=True)
class ReferencePoint:
    value: float
    unit: str


@dataclass
class CalibrationProposal:
    proposal_id: str
    tenant_id: str
    device_id: str
    observed_value: float
    reference_value: float
    unit: str
    offset: float
    max_offset: float
    status: str = "proposed"
    created_at: str = ""
    approved_by: str | None = None
    applied_at: str | None = None
    calibration_version: int | None = None

    @property
    def valid(self) -> bool:
        return self.status in {"proposed", "approved", "applied"}


class ReferenceCalibrationPlugin:
    """Calculate and apply an offset only after explicit approval."""

    plugin_id = "reference-offset-v1"

    def propose(
        self,
        tenant_id: str,
        device_id: str,
        observed_value: float,
        reference: ReferencePoint,
        expected_unit: str,
        max_offset: float = 5.0,
    ) -> CalibrationProposal:
        values = (observed_value, reference.value, max_offset)
        if not all(isfinite(value) for value in values):
            raise ValueError("calibration values must be finite")
        if not tenant_id or not device_id:
            raise ValueError("tenant_id and device_id are required")
        if reference.unit != expected_unit:
            raise ValueError("reference unit does not match sensor unit")
        if max_offset <= 0:
            raise ValueError("max_offset must be positive")
        offset = reference.value - observed_value
        if abs(offset) > max_offset:
            raise ValueError("calculated offset exceeds safety limit")
        return CalibrationProposal(
            proposal_id=f"cal:{uuid4().hex}",
            tenant_id=tenant_id,
            device_id=device_id,
            observed_value=observed_value,
            reference_value=reference.value,
            unit=expected_unit,
            offset=offset,
            max_offset=max_offset,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def approve(self, proposal: CalibrationProposal, actor: str) -> CalibrationProposal:
        if proposal.status == "applied":
            return proposal
        if proposal.status != "proposed":
            raise ValueError("only proposed calibrations can be approved")
        if not actor:
            raise ValueError("approval actor is required")
        proposal.status = "approved"
        proposal.approved_by = actor
        return proposal

    def apply(self, proposal: CalibrationProposal) -> CalibrationProposal:
        if proposal.status == "applied":
            return proposal
        if proposal.status != "approved":
            raise ValueError("calibration must be approved before applying")
        proposal.status = "applied"
        proposal.applied_at = datetime.now(timezone.utc).isoformat()
        proposal.calibration_version = 1
        return proposal

    def correct(self, raw_value: float, proposal: CalibrationProposal) -> dict[str, float | str | int]:
        if proposal.status != "applied":
            raise ValueError("only applied calibration can correct readings")
        if not isfinite(raw_value):
            raise ValueError("raw value must be finite")
        return {
            "raw_value": raw_value,
            "corrected_value": raw_value + proposal.offset,
            "unit": proposal.unit,
            "calibration_version": proposal.calibration_version or 1,
        }
