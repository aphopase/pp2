import hashlib
import hmac
import json
from pathlib import Path

from backend.billing import BillingService
from backend.storage import Repository


def test_billing_entitlements_and_idempotent_events(tmp_path: Path):
    repository = Repository(tmp_path / "billing.db")
    user = repository.create_user("owner@example.com", "correct horse")
    project = repository.create_project(user["id"], "Demo")
    billing = BillingService(repository, "billing-secret")

    assert billing.subscription(project["id"])["plan"] == "starter"
    billing.check_campaign(project["id"], 100)
    billing.record_campaign(project["id"], 100)
    assert billing.usage(project["id"])["campaigns"] == 1

    payload = json.dumps({"id": "evt_1", "type": "subscription.updated", "project_id": project["id"], "plan": "growth"}).encode()
    signature = hmac.new(b"billing-secret", payload, hashlib.sha256).hexdigest()
    assert billing.apply_webhook(payload, signature)["status"] == "processed"
    assert billing.apply_webhook(payload, signature)["status"] == "already_processed"
    assert billing.subscription(project["id"])["plan"] == "growth"
    repository.close()
