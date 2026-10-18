import pytest

from plugins.calibration import ReferencePoint
from plugins.modbus_calibration import InMemoryModbusTransport, ModbusCalibrationAdapter, RegisterMap


def adapter(registers=None):
    transport = InMemoryModbusTransport(registers or {(1, 100): 235, (1, 200): 0})
    register_map = RegisterMap(1, 100, 200, "degC")
    return ModbusCalibrationAdapter(transport, register_map), transport


def test_preview_decodes_scaled_value_and_does_not_write():
    calibration, transport = adapter()
    proposal, plan = calibration.preview("org_demo", "modbus_sensor_1", ReferencePoint(25.0, "degC"))
    assert proposal.observed_value == 23.5
    assert proposal.offset == 1.5
    assert plan.register == 200
    assert plan.proposed_raw_value == 15
    assert transport.current_value(1, 200) == 0
    with pytest.raises(RuntimeError, match="disabled"):
        calibration.write(plan)


def test_invalid_map_and_read_are_rejected():
    with pytest.raises(ValueError, match="slave_id"):
        RegisterMap(0, 100, 200, "degC")
    calibration, _ = adapter({(1, 100): 40000, (1, 200): 0})
    with pytest.raises(ValueError, match="out of range"):
        calibration.preview("org_demo", "sensor", ReferencePoint(25.0, "degC"))


def test_unit_mismatch_is_rejected():
    calibration, _ = adapter()
    with pytest.raises(ValueError, match="unit"):
        calibration.preview("org_demo", "sensor", ReferencePoint(25.0, "kPa"))
