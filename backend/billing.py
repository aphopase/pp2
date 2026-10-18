"""Plan entitlements, metering, and provider-neutral billing events."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
from typing import Any


@dataclass(frozen=True)
class Plan:
    name: str
    monthly_sensor_limit: int
    monthly_campaign_limit: int
    member_limit: int
    site_limit: int
    api_rate_limit: int


PLANS = {
    "starter": Plan("starter", 100, 10, 3, 1, 60),
    "growth": Plan("growth", 1000, 100, 15, 5, 300),
    "professional": Plan("professional", 10000, 1000, 100, 25, 1200),
    "enterprise": Plan("enterprise", 1_000_000, 100_000, 10_000, 1_000, 10_000),
}


def current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


class BillingService:
    def __init__(self, repository, signing_secret: str = "") -> None:
        self.repository = repository
        self.signing_secret = signing_secret

    def plan(self, name: str) -> Plan:
        try:
            return PLANS[name]
        except KeyError as error:
            raise ValueError("unknown plan") from error

    def subscribe(self, project_id: str, plan_name: str = "starter") -> dict[str, Any]:
        plan = self.plan(plan_name)
        self.repository.create_subscription(project_id, plan.name)
        return {"project_id": project_id, "plan": plan.name, "status": "active"}

    def subscription(self, project_id: str) -> dict[str, Any]:
        row = self.repository.subscription(project_id)
        if row is None:
            return self.subscribe(project_id)
        return row

    def usage(self, project_id: str, period: str | None = None) -> dict[str, Any]:
        period = period or current_period()
        return self.repository.usage(project_id, period)

    def check_campaign(self, project_id: str, sensor_count: int) -> None:
        subscription = self.subscription(project_id)
        plan = self.plan(subscription["plan"])
        usage = self.usage(project_id)
        if sensor_count > plan.monthly_sensor_limit:
            raise PermissionError("campaign exceeds the plan sensor limit")
        if usage["campaigns"] >= plan.monthly_campaign_limit:
            raise PermissionError("monthly campaign limit reached")

    def record_campaign(self, project_id: str, sensor_count: int) -> None:
        self.repository.increment_usage(project_id, current_period(), "campaigns", 1)
        self.repository.increment_usage(project_id, current_period(), "sensor_operations", sensor_count)

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        if not self.signing_secret or not signature:
            return False
        expected = hmac.new(self.signing_secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def apply_webhook(self, payload: bytes, signature: str) -> dict[str, Any]:
        if not self.verify_webhook(payload, signature):
            raise PermissionError("invalid billing webhook signature")
        event = json.loads(payload)
        event_id = event.get("id")
        if not event_id:
            raise ValueError("billing webhook id is required")
        if not self.repository.record_billing_event(event_id, event):
            return {"status": "already_processed", "event_id": event_id}
        project_id = event.get("project_id")
        if project_id and event.get("type") == "subscription.updated":
            self.repository.create_subscription(project_id, event["plan"], event.get("status", "active"))
        return {"status": "processed", "event_id": event_id}
