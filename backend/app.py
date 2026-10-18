"""In-process backend core for the first IoT vertical slice."""
from dataclasses import dataclass, asdict
from typing import Any
from shared.models import Telemetry

@dataclass
class Rule:
    rule_id: str
    tenant_id: str
    site_id: str
    measurement: str
    operator: str
    threshold: float
    severity: str = "medium"

@dataclass
class Alert:
    alert_id: str
    rule_id: str
    tenant_id: str
    site_id: str
    device_id: str
    measurement: str
    value: float
    severity: str
    event_time: str
    status: str = "active"

class IoTCore:
    def __init__(self) -> None:
        self.telemetry: list[dict[str, Any]] = []
        self.seen_keys: set[str] = set()
        self.rules: dict[str, Rule] = {}
        self.alerts: dict[str, Alert] = {}

    def ingest(self, records: list[dict[str, Any]], tenant_id: str) -> dict[str, Any]:
        accepted, rejected = [], []
        for payload in records:
            try:
                item = Telemetry.from_dict(payload)
                if item.tenant_id != tenant_id:
                    raise ValueError("tenant scope mismatch")
                record = item.to_dict()
                key = record["idempotency_key"]
                if key not in self.seen_keys:
                    self.seen_keys.add(key)
                    self.telemetry.append(record)
                    self._evaluate(record)
                accepted.append(key)
            except (KeyError, TypeError, ValueError) as error:
                rejected.append({"reason": str(error)})
        return {"accepted": accepted, "rejected": rejected}

    def add_rule(self, rule: Rule) -> None:
        self.rules[rule.rule_id] = rule

    def query_telemetry(self, tenant_id: str, site_id: str | None = None) -> list[dict[str, Any]]:
        return [
            record for record in self.telemetry
            if record["tenant_id"] == tenant_id
            and (site_id is None or record["site_id"] == site_id)
        ]

    def active_alerts(self, tenant_id: str) -> list[dict[str, Any]]:
        return [asdict(alert) for alert in self.alerts.values()
                if alert.tenant_id == tenant_id and alert.status == "active"]

    def acknowledge_alert(self, alert_id: str, tenant_id: str) -> dict[str, Any]:
        alert = self.alerts[alert_id]
        if alert.tenant_id != tenant_id:
            raise PermissionError("tenant scope mismatch")
        alert.status = "acknowledged"
        return asdict(alert)

    def _evaluate(self, record: dict[str, Any]) -> None:
        checks = {">": lambda v, t: v > t, ">=": lambda v, t: v >= t,
                  "<": lambda v, t: v < t, "<=": lambda v, t: v <= t,
                  "==": lambda v, t: v == t}
        for rule in self.rules.values():
            if (rule.tenant_id, rule.site_id, rule.measurement) != (
                record["tenant_id"], record["site_id"], record["measurement"]):
                continue
            if not checks.get(rule.operator, lambda _v, _t: False)(record["value"], rule.threshold):
                continue
            alert_id = f"alert:{rule.rule_id}:{record['device_id']}"
            if alert_id not in self.alerts:
                self.alerts[alert_id] = Alert(
                    alert_id, rule.rule_id, record["tenant_id"], record["site_id"],
                    record["device_id"], record["measurement"], record["value"],
                    rule.severity, record["event_time"])
