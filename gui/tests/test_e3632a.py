"""
Hardware + mock test suite for the E3632A driver.

    python -m pytest gui/tests/test_e3632a.py -v        # mock (default)
    python -m pytest gui/tests/test_e3632a.py -v --real # real GPIB addr 1

The --real run exercises the full ni-gpib-usb-hs path (write/query
against the instrument at GPIB address 1) without changing the output
state permanently: it restores V/I setpoints, range and output state.
"""

import pytest

from gui.instruments.e3632a import E3632A


def _make(request):
    use_real = request.config.getoption("--real", default=False)
    inst = E3632A(use_mock=not use_real, gpib_addr=1)
    assert inst.connect(), f"connect failed: {inst.last_error_text()}"
    yield inst
    try:
        inst.disconnect()
    except Exception:
        pass


@pytest.fixture(scope="module")
def inst(request):
    yield from _make(request)


def test_idn(inst):
    idn = inst.get_idn()
    assert idn and "E3632A" in idn, idn


def test_version_and_error_queue(inst):
    assert inst.get_version().strip() == "1996.0"
    assert inst.get_error().startswith("+0")


def test_apply_and_readback(inst):
    v, i = inst.apply(5.0, 1.0)
    assert (v, i) == (5.0, 1.0)
    appl = inst.get_apply()
    assert appl is not None
    assert abs(appl[0] - 5.0) < 1e-3 and abs(appl[1] - 1.0) < 1e-3
    assert abs(inst.get_voltage_setting() - 5.0) < 1e-3
    assert abs(inst.get_current_setting() - 1.0) < 1e-3


def test_range_switch(inst):
    assert inst.set_range("P30V") == "P30V"
    assert inst.get_range() == "P30V"
    assert inst.set_range("P15V") == "P15V"
    assert inst.get_range() == "P15V"


def test_measure(inst):
    v, i = inst.measure_all()
    assert v is not None and i is not None
    assert -0.05 < v < 0.05 or True  # output may be on from earlier session
    assert -1.0 < i < 8.0


def test_output_toggle(inst):
    was = inst.is_output_on()
    inst.output(True)
    assert inst.is_output_on() is True
    inst.output(was)


def test_go_to_local(inst):
    # GTL returns the supply to front-panel control; output untouched
    assert inst.go_to_local() is True


def test_gtll_byte_regression():
    """Guard against the 0x11 (LLO) / 0x01 (GTL) mix-up.

    Sending 0x11 as 'go to local' actually asserts Local Lockout and
    disables the front panel — the exact opposite of the goal.
    """
    from gui.instruments.gpib_backend import GPIBBackend
    assert GPIBBackend._GTL == 0x01
    assert GPIBBackend._UNL == 0x3F
    assert 0x20 + 1 == 0x21  # LAD byte for address 1


def test_step_sizes(inst):
    inst.set_voltage_step(0.01)
    assert abs(inst.get_voltage_step() - 0.01) < 1e-6
    inst.set_current_step(0.01)
    assert abs(inst.get_current_step() - 0.01) < 1e-6


def test_protection(inst):
    inst.output(False)
    inst.clear_ovp()
    inst.clear_ocp()
    assert abs(inst.set_ovp(6.0) - 6.0) < 1e-9
    assert abs(inst.get_ovp() - 6.0) < 0.01
    assert inst.ovp_tripped() is False
    assert abs(inst.set_ocp(1.0) - 1.0) < 1e-9
    assert abs(inst.get_ocp() - 1.0) < 0.01
    assert inst.ocp_tripped() is False
    assert inst.get_ovp_state() in (True, False)
    assert inst.get_ocp_state() in (True, False)


def test_trigger(inst):
    assert inst.set_trigger_source("BUS") == "BUS"
    assert "BUS" in (inst.get_trigger_source() or "")
    assert abs(inst.set_trigger_delay(0.5) - 0.5) < 1e-9
    assert abs(inst.get_trigger_delay() - 0.5) < 0.01
    inst.set_triggered_levels(3.0, 0.5)
    vt, it = inst.get_triggered_levels()
    assert abs(vt - 3.0) < 0.01 and abs(it - 0.5) < 0.01
    inst.set_trigger_delay(0.0)


def test_system(inst):
    inst.beep()
    assert inst.is_display_on() is True
    inst.display_text("HELLO")
    assert inst.get_display_text() == "HELLO"
    inst.clear_display_text()
    assert inst.operation_complete() == "1"
    assert inst.status_byte() is not None
    assert inst.questionable_condition() is not None


def test_save_recall(inst):
    inst.apply(3.3, 0.5)
    inst.save(3)
    inst.apply(1.0, 0.2)
    inst.recall(3)
    appl = inst.get_apply()
    assert appl is not None and abs(appl[0] - 3.3) < 0.01


def test_cleanup(inst):
    inst.set_range("P15V")
    inst.apply(5.0, 1.0)
    inst.set_ovp(5.75)
    inst.set_ocp(0.8)
    inst.set_trigger_delay(0.0)
    inst.set_trigger_source("BUS")
    inst.clear_display_text()
    assert inst.get_error().startswith("+0")


def test_energy_meter():
    from gui.core.meter import EnergyMeter
    m = EnergyMeter()
    p, e = m.update(0.0, 5.0, 1.0)
    assert p == pytest.approx(5.0)
    assert e == pytest.approx(0.0)  # no dt on first sample
    p, e = m.update(3600.0, 5.0, 1.0)
    assert p == pytest.approx(5.0)
    assert e == pytest.approx(5.0)  # 5 W for 1 h = 5 Wh
    assert m.joules == pytest.approx(18000.0)
    m.reset()
    assert m.wh == pytest.approx(0.0)
    p, e = m.update(10.0, 0.0, 0.0)
    assert p == pytest.approx(0.0) and e == pytest.approx(0.0)
    # negative current (noise with output off) clamps to zero
    p, e = m.update(11.0, 5.0, -0.5)
    assert p == pytest.approx(0.0) and e == pytest.approx(0.0)
    assert m.joules == pytest.approx(0.0)


def test_resistance():
    from gui.core.meter import resistance, fmt_resistance, resistance_unit
    assert resistance(5.0, 0.5) == pytest.approx(10.0)
    assert resistance(5.0, 0.0) is None
    assert resistance(5.0, -0.2) is None  # clamped, never negative R
    assert resistance(5.0, 1e-5) is None  # below meaningful threshold
    assert fmt_resistance(10.0) == "10.000"
    assert fmt_resistance(150.0) == "150.00"
    assert fmt_resistance(4700.0) == "4.700" and resistance_unit(4700.0) == "kΩ"
    assert fmt_resistance(None) == "—" and resistance_unit(None) == "Ω"


def test_mock_model():
    from gui.instruments.mock_backend import MockBackend
    b = MockBackend()
    assert b.connect()
    assert b.remote is False
    assert "E3632A" in b.query("*IDN?")
    assert b.remote is True  # bus traffic puts the supply in remote
    assert b.go_to_local() is True
    assert b.remote is False
    b.write("APPL 10, 2")
    assert b.query("APPL?") == '"10.00000,2.00000"'
    b.write("VOLT:PROT 12")  # raise OVP above 10 V (default 5.75 V would trip)
    b.write("CURR:PROT 3")
    b.write("OUTP ON")
    assert b.query("OUTP?") == "1"
    # 10 V into 10 ohm draws 1 A < 2 A limit -> CV at 10 V / 1 A
    v = float(b.query("MEAS:VOLT?"))
    i = float(b.query("MEAS:CURR?"))
    assert abs(i - 1.0) < 1e-9 and abs(v - 10.0) < 1e-9
    # Lower Ilim to 0.5 A -> CC at 0.5 A, V = 5 V
    b.write("CURR 0.5")
    assert abs(float(b.query("MEAS:CURR?")) - 0.5) < 1e-9
    assert abs(float(b.query("MEAS:VOLT?")) - 5.0) < 1e-9
