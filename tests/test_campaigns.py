import pytest

from backend.campaigns import CalibrationCampaignManager
from plugins.calibration import ReferencePoint


def test_campaign_calibrates_one_thousand_simulated_sensors():
    manager = CalibrationCampaignManager(max_workers=8)
    campaign = manager.create("org_demo", 1000, ReferencePoint(25.0, "degC"))

    manager.start("org_demo", campaign.campaign_id)
    summary = manager.summary(campaign)

    assert summary["status"] == "proposed"
    assert summary["sensor_count"] == 1000
    assert summary["counts"]["proposed"] == 1000
    assert summary["completed"] == 0

    manager.approve("org_demo", campaign.campaign_id)
    assert manager.summary(campaign)["counts"]["approved"] == 1000
    manager.apply("org_demo", campaign.campaign_id)
    assert manager.summary(campaign)["status"] == "applied"
    assert manager.summary(campaign)["counts"]["verified"] == 1000


def test_failures_are_isolated_and_operations_are_idempotent():
    manager = CalibrationCampaignManager(max_workers=4)
    campaign = manager.create(
        "org_demo", 10, ReferencePoint(25.0, "degC"), ["sensor_0003", "sensor_0007"]
    )

    manager.start("org_demo", campaign.campaign_id)
    summary = manager.summary(campaign)
    assert summary["counts"]["failed"] == 2
    assert summary["counts"]["proposed"] == 8
    manager.start("org_demo", campaign.campaign_id)
    manager.approve("org_demo", campaign.campaign_id)
    manager.approve("org_demo", campaign.campaign_id)
    manager.apply("org_demo", campaign.campaign_id)
    manager.apply("org_demo", campaign.campaign_id)
    assert manager.summary(campaign)["counts"]["verified"] == 8


def test_campaign_validation_and_tenant_isolation():
    manager = CalibrationCampaignManager()
    with pytest.raises(ValueError):
        manager.create("org_demo", 0, ReferencePoint(25.0, "degC"))
    with pytest.raises(ValueError):
        manager.create("org_demo", 1, ReferencePoint(float("nan"), "degC"))
    campaign = manager.create("org_demo", 1, ReferencePoint(25.0, "degC"))
    with pytest.raises(KeyError):
        manager.get("other_org", campaign.campaign_id)
    with pytest.raises(ValueError):
        manager.apply("org_demo", campaign.campaign_id)
