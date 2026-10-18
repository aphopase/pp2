import csv
import io
import json
from pathlib import Path

import pytest

from backend.adapters import AdapterContext, Measurement, get_adapter, register_adapter
from backend.exports import campaign_csv, campaign_json
from backend.storage import Repository, verify_secret
from backend.webhooks import RecordingWebhookTransport


def test_repository_persists_users_projects_models_profiles_and_keys(tmp_path: Path):
    db = tmp_path / "platform.db"
    repository = Repository(db)
    user = repository.create_user("owner@example.com", "correct horse")
    project = repository.create_project(user["id"], "Demo project")
    model = repository.create_model(project["id"], {"name": "Thermometer", "protocol": "simulator", "measurement": "temperature", "unit": "degC"})
    profile = repository.create_profile(project["id"], {"name": "Factory", "unit": "degC", "max_offset": 5.0, "tolerance": 0.2})
    key_info, raw_key = repository.create_api_key(project["id"], user["id"], "cli")
    assert repository.authenticate_user("owner@example.com", "correct horse")
    assert repository.models(project["id"])[0]["id"] == model["id"]
    assert repository.profiles(project["id"])[0]["id"] == profile["id"]
    assert repository.authenticate_key(raw_key)["project_id"] == project["id"]
    assert key_info["id"]
    repository.close()

    reopened = Repository(db)
    assert reopened.projects_for_user(user["id"])[0]["name"] == "Demo project"
    assert verify_secret(raw_key, reopened.connection.execute("SELECT key_hash FROM api_keys").fetchone()["key_hash"])
    reopened.close()


def test_storage_rejects_weak_password_and_invalid_profile(tmp_path: Path):
    repository = Repository(tmp_path / "platform.db")
    with pytest.raises(ValueError):
        repository.create_user("owner@example.com", "short")
    user = repository.create_user("owner@example.com", "long enough")
    project = repository.create_project(user["id"], "Demo")
    with pytest.raises(ValueError):
        repository.create_profile(project["id"], {"name": "bad", "unit": "degC", "max_offset": 0, "tolerance": 1})
    repository.close()


def test_adapter_registry_and_exports():
    @register_adapter("test_adapter")
    class TestAdapter(get_adapter("simulator")):
        pass

    adapter = get_adapter("test_adapter")()
    proposal = adapter.propose(AdapterContext("sensor_1", "degC", {"observed_value": 23.5}), Measurement(25.0, "degC"))
    assert proposal.offset == 1.5
    report = {"campaign_id": "c1", "attempts": [{"sensor_id": "sensor_1", "observed_value": 23.5, "reference_value": 25, "offset": 1.5, "status": "verified"}]}
    assert json.loads(campaign_json(report))["campaign_id"] == "c1"
    rows = list(csv.DictReader(io.StringIO(campaign_csv(report))))
    assert rows[0]["simulation_only"] == "true"


def test_webhook_signing_and_recording():
    transport = RecordingWebhookTransport()
    event = transport.publish("https://example.test/hook", "secret", "campaign.completed", {"id": "c1"})
    assert event.signature
    assert len(transport.events) == 1
