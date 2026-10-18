from pathlib import Path
import tempfile

from backend.app import IoTCore, Rule
from gateway.outbox import Outbox
from gateway.simulator import SimulatorAdapter


def test_offline_outbox_deduplicates_and_acknowledges():
    record = next(SimulatorAdapter().readings(1)).to_dict()
    outbox = Outbox(Path(tempfile.mkdtemp()) / "gateway.db")
    assert outbox.append(record) is True
    assert outbox.append(record) is False
    assert len(outbox.pending()) == 1
    outbox.acknowledge([record["idempotency_key"]])
    assert outbox.stats()["pending_count"] == 0


def test_ingestion_is_idempotent_and_creates_alert():
    core = IoTCore()
    core.add_rule(Rule("high-power", "org_demo", "site_demo", "power", ">", 20))
    records = [item.to_dict() for item in SimulatorAdapter().readings(4)]
    assert len(core.ingest(records, "org_demo")["accepted"]) == 16
    assert len(core.telemetry) == 16
    assert len(core.active_alerts("org_demo")) == 1
    core.ingest(records, "org_demo")
    assert len(core.telemetry) == 16


def test_cross_tenant_payload_is_rejected():
    core = IoTCore()
    payload = next(SimulatorAdapter().readings(1)).to_dict()
    result = core.ingest([payload], "other_org")
    assert result["accepted"] == []
    assert result["rejected"]
