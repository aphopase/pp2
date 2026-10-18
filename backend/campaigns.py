"""Deterministic parallel calibration campaigns for simulated sensors."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from math import isfinite
from threading import Lock
from typing import Any
from uuid import uuid4

from plugins.calibration import CalibrationProposal, ReferenceCalibrationPlugin, ReferencePoint

MAX_SENSORS_PER_CAMPAIGN = 1000


@dataclass
class SensorAttempt:
    sensor_id: str
    unit: str
    observed_value: float | None = None
    reference_value: float | None = None
    offset: float | None = None
    status: str = "pending"
    error: str | None = None
    proposal: CalibrationProposal | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["proposal"] = asdict(self.proposal) if self.proposal else None
        return result


@dataclass
class CalibrationCampaign:
    campaign_id: str
    tenant_id: str
    reference: ReferencePoint
    status: str = "created"
    attempts: dict[str, SensorAttempt] = field(default_factory=dict)
    failure_ids: set[str] = field(default_factory=set)


class SimulatedSensorInventory:
    """Generate stable sensor readings without opening a physical connection."""

    def __init__(self, sensor_count: int, unit: str, failure_ids: set[str]) -> None:
        self.sensor_count = sensor_count
        self.unit = unit
        self.failure_ids = failure_ids

    def create(self) -> dict[str, SensorAttempt]:
        return {
            f"sensor_{number:04d}": SensorAttempt(
                sensor_id=f"sensor_{number:04d}", unit=self.unit
            )
            for number in range(1, self.sensor_count + 1)
        }

    def read(self, sensor_id: str) -> float:
        if sensor_id in self.failure_ids:
            raise RuntimeError("simulated communication failure")
        number = int(sensor_id.rsplit("_", 1)[1])
        return 23.5 + ((number - 1) % 5) * 0.1


class CalibrationCampaignManager:
    """Coordinate bounded, approval-gated calibration work for one process."""

    def __init__(self, max_workers: int = 32) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self.max_workers = max_workers
        self._campaigns: dict[str, CalibrationCampaign] = {}
        self._lock = Lock()
        self._plugin = ReferenceCalibrationPlugin()

    def create(
        self,
        tenant_id: str,
        sensor_count: int,
        reference: ReferencePoint,
        failure_ids: list[str] | None = None,
    ) -> CalibrationCampaign:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if not isinstance(sensor_count, int) or isinstance(sensor_count, bool):
            raise ValueError("sensor_count must be an integer")
        if not 1 <= sensor_count <= MAX_SENSORS_PER_CAMPAIGN:
            raise ValueError(f"sensor_count must be between 1 and {MAX_SENSORS_PER_CAMPAIGN}")
        if not reference.unit:
            raise ValueError("reference unit is required")
        if not isfinite(reference.value):
            raise ValueError("reference value must be finite")
        failures = set(failure_ids or [])
        attempts = SimulatedSensorInventory(sensor_count, reference.unit, failures).create()
        unknown_failures = failures.difference(attempts)
        if unknown_failures:
            raise ValueError("failure_ids contain unknown sensors")
        campaign = CalibrationCampaign(
            campaign_id=f"campaign:{uuid4().hex}",
            tenant_id=tenant_id,
            reference=reference,
            attempts=attempts,
            failure_ids=failures,
        )
        with self._lock:
            self._campaigns[campaign.campaign_id] = campaign
        return campaign

    def get(self, tenant_id: str, campaign_id: str) -> CalibrationCampaign:
        with self._lock:
            campaign = self._campaigns.get(campaign_id)
            if campaign is None or campaign.tenant_id != tenant_id:
                raise KeyError("campaign not found")
            return campaign

    def list(self, tenant_id: str) -> list[CalibrationCampaign]:
        with self._lock:
            return [campaign for campaign in self._campaigns.values() if campaign.tenant_id == tenant_id]

    def start(self, tenant_id: str, campaign_id: str) -> CalibrationCampaign:
        campaign = self.get(tenant_id, campaign_id)
        with self._lock:
            if campaign.status in {"proposed", "approved", "applied"}:
                return campaign
            if campaign.status == "running":
                raise ValueError("campaign is already running")
            campaign.status = "running"
            pending_ids = [
                sensor_id for sensor_id, attempt in campaign.attempts.items()
                if attempt.status == "pending"
            ]

        inventory = SimulatedSensorInventory(
            len(campaign.attempts), campaign.reference.unit, campaign.failure_ids
        )
        with ThreadPoolExecutor(max_workers=min(self.max_workers, max(1, len(pending_ids)))) as workers:
            futures = {
                workers.submit(self._propose_one, campaign, inventory, sensor_id): sensor_id
                for sensor_id in pending_ids
            }
            for future in as_completed(futures):
                future.result()
        with self._lock:
            if any(attempt.status == "pending" or attempt.status == "running" for attempt in campaign.attempts.values()):
                campaign.status = "failed"
            else:
                campaign.status = "proposed"
        return campaign

    def _propose_one(
        self, campaign: CalibrationCampaign, inventory: SimulatedSensorInventory, sensor_id: str
    ) -> None:
        with self._lock:
            attempt = campaign.attempts[sensor_id]
            if attempt.status != "pending":
                return
            attempt.status = "running"
        try:
            observed = inventory.read(sensor_id)
            proposal = self._plugin.propose(
                tenant_id=campaign.tenant_id,
                device_id=sensor_id,
                observed_value=observed,
                reference=campaign.reference,
                expected_unit=campaign.reference.unit,
            )
            with self._lock:
                attempt.observed_value = observed
                attempt.reference_value = campaign.reference.value
                attempt.offset = proposal.offset
                attempt.proposal = proposal
                attempt.status = "proposed"
        except (TypeError, ValueError, RuntimeError) as error:
            with self._lock:
                attempt.status = "failed"
                attempt.error = str(error)

    def approve(self, tenant_id: str, campaign_id: str) -> CalibrationCampaign:
        campaign = self.get(tenant_id, campaign_id)
        with self._lock:
            if campaign.status == "created" or campaign.status == "running":
                raise ValueError("campaign must be started before approval")
            if campaign.status in {"approved", "applied"}:
                return campaign
            for attempt in campaign.attempts.values():
                if attempt.status == "proposed" and attempt.proposal is not None:
                    self._plugin.approve(attempt.proposal, "campaign_operator")
                    attempt.status = "approved"
            campaign.status = "approved"
        return campaign

    def apply(self, tenant_id: str, campaign_id: str) -> CalibrationCampaign:
        campaign = self.get(tenant_id, campaign_id)
        with self._lock:
            if campaign.status == "applied":
                return campaign
            if campaign.status != "approved":
                raise ValueError("campaign must be approved before applying")
            for attempt in campaign.attempts.values():
                if attempt.status == "approved" and attempt.proposal is not None:
                    self._plugin.apply(attempt.proposal)
                    attempt.status = "verified"
            campaign.status = "applied"
        return campaign

    @staticmethod
    def summary(campaign: CalibrationCampaign) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for attempt in campaign.attempts.values():
            counts[attempt.status] = counts.get(attempt.status, 0) + 1
        return {
            "campaign_id": campaign.campaign_id,
            "tenant_id": campaign.tenant_id,
            "status": campaign.status,
            "sensor_count": len(campaign.attempts),
            "reference": asdict(campaign.reference),
            "counts": counts,
            "completed": sum(counts.get(status, 0) for status in ("verified", "failed")),
        }

    def attempts(self, tenant_id: str, campaign_id: str) -> list[dict[str, Any]]:
        campaign = self.get(tenant_id, campaign_id)
        with self._lock:
            return [attempt.to_dict() for attempt in campaign.attempts.values()]

    def report(self, tenant_id: str, campaign_id: str) -> dict[str, Any]:
        campaign = self.get(tenant_id, campaign_id)
        result = self.summary(campaign)
        result["attempts"] = self.attempts(tenant_id, campaign_id)
        return result
