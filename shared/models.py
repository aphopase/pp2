"""Canonical telemetry model shared by the gateway and backend."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
import hashlib
import json


SUPPORTED_QUALITY = {"good", "uncertain", "bad"}


@dataclass(frozen=True)
class Telemetry:
    tenant_id: str
    site_id: str
    gateway_id: str
    device_id: str
    measurement: str
    value: float
    unit: str
    quality: str
    event_time: str
    ingest_time: str
    gateway_sequence: int
    schema_version: int = 1
    idempotency_key: str = ""
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (
            self.tenant_id, self.site_id, self.gateway_id, self.device_id,
            self.measurement, self.unit, self.event_time, self.ingest_time,
        )):
            raise ValueError("telemetry identity and timestamps are required")
        if not isinstance(self.value, (int, float)) or isinstance(self.value, bool):
            raise ValueError("telemetry value must be numeric")
        if self.quality not in SUPPORTED_QUALITY:
            raise ValueError(f"quality must be one of {sorted(SUPPORTED_QUALITY)}")
        if self.gateway_sequence < 1:
            raise ValueError("gateway_sequence must be positive")
        if self.schema_version != 1:
            raise ValueError("unsupported telemetry schema version")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if not result["idempotency_key"]:
            result["idempotency_key"] = (
                f"{self.gateway_id}:{self.gateway_sequence}"
            )
        if result["metadata"] is None:
            result["metadata"] = {}
        return result

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Telemetry":
        if not isinstance(payload, dict):
            raise ValueError("telemetry payload must be an object")
        return cls(
            tenant_id=payload["tenant_id"],
            site_id=payload["site_id"],
            gateway_id=payload["gateway_id"],
            device_id=payload["device_id"],
            measurement=payload["measurement"],
            value=payload["value"],
            unit=payload["unit"],
            quality=payload["quality"],
            event_time=payload["event_time"],
            ingest_time=payload["ingest_time"],
            gateway_sequence=payload["gateway_sequence"],
            schema_version=payload.get("schema_version", 1),
            idempotency_key=payload.get("idempotency_key", ""),
            metadata=payload.get("metadata", {}),
        )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def batch_digest(records: list[dict[str, Any]]) -> str:
    return hashlib.sha256(stable_json({"records": records}).encode()).hexdigest()
