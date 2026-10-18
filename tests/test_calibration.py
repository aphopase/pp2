import pytest

from plugins.calibration import ReferenceCalibrationPlugin, ReferencePoint


def test_reference_offset_requires_approval_then_corrects_value():
    plugin = ReferenceCalibrationPlugin()
    proposal = plugin.propose("org_demo", "sensor_1", 23.5, ReferencePoint(25.0, "degC"), "degC")
    assert proposal.offset == 1.5
    with pytest.raises(ValueError):
        plugin.apply(proposal)
    plugin.approve(proposal, "operator_1")
    plugin.apply(proposal)
    assert plugin.correct(23.5, proposal)["corrected_value"] == 25.0
    assert plugin.apply(proposal) is proposal


def test_invalid_unit_and_excessive_offset_are_rejected():
    plugin = ReferenceCalibrationPlugin()
    with pytest.raises(ValueError, match="unit"):
        plugin.propose("org_demo", "sensor_1", 23.5, ReferencePoint(25.0, "kPa"), "degC")
    with pytest.raises(ValueError, match="safety"):
        plugin.propose("org_demo", "sensor_1", 10.0, ReferencePoint(25.0, "degC"), "degC")
