"""
Agilent E3632A unified driver.

High-level SCPI interface over either the real GPIB backend
(ni-gpib-usb-hs user-space driver for the NI GPIB-USB-HS adapter)
or the mock backend. All manual references are to the E3632A
User's Guide (manual.pdf, Chapter 4).
"""

import logging
import time

from .gpib_backend import GPIBBackend
from .mock_backend import MockBackend
from ..commands.e3632a_commands import (
    RANGES, range_of, clamp, valid_voltage, valid_current,
    OVP_MAX, OCP_MAX,
)

log = logging.getLogger(__name__)


def _parse_float(resp):
    if resp is None:
        return None
    try:
        return float(resp.strip().strip('"'))
    except (ValueError, AttributeError):
        return None


class E3632A:
    """Unified E3632A driver (GPIB real hardware or mock)."""

    def __init__(self, use_mock=False, gpib_addr: int = 1):
        self._use_mock = use_mock
        self._addr = int(gpib_addr)
        self._backend = None
        self.range = "P15V"  # cached selected range

    # -- connection -----------------------------------------------------
    @property
    def backend(self):
        return self._backend

    @property
    def connected(self) -> bool:
        return self._backend is not None and self._backend.connected

    @property
    def is_mock(self) -> bool:
        return self._use_mock

    def connect(self) -> bool:
        if self.connected:
            return True
        self._backend = MockBackend(self._addr) if self._use_mock \
            else GPIBBackend(self._addr)
        if self._backend.connect():
            if not self._use_mock:
                time.sleep(0.2)
                self.query("SYST:ERR?")
            self._refresh_range_cache()
            return True
        self._backend = None
        return False

    def disconnect(self):
        if self._backend:
            try:
                self._backend.disconnect()
            except Exception:
                pass
        self._backend = None

    def go_to_local(self) -> bool:
        """Return the supply to front-panel (local) control.

        Sends IEEE-488 GTL on real hardware; output settings are
        preserved (manual Ch. 3). Returns False when unsupported
        or the bus is dead — never raises.
        """
        backend = self._backend
        if backend is None or not backend.connected:
            return False
        fn = getattr(backend, "go_to_local", None)
        if fn is None:
            return False
        try:
            return bool(fn())
        except Exception as e:  # noqa: BLE001
            log.error("go_to_local failed: %s", e)
            return False

    # -- raw -------------------------------------------------------------
    def write(self, cmd: str):
        if self._backend:
            self._backend.write(cmd)

    def query(self, cmd: str) -> str | None:
        if self._backend:
            return self._backend.query(cmd)
        return None

    def read(self) -> str | None:
        if self._backend:
            return self._backend.read()
        return None

    def last_error_text(self) -> str:
        if self._backend and getattr(self._backend, "last_error", ""):
            return self._backend.last_error
        return ""

    # -- identification / system ------------------------------------------
    def get_idn(self):
        return self.query("*IDN?")

    def get_version(self):
        return self.query("SYST:VERS?")

    def get_error(self):
        """Next entry of the error queue, e.g. '+0,"No error"'."""
        return self.query("SYST:ERR?")

    def drain_errors(self, limit=20):
        errs = []
        for _ in range(limit):
            e = self.query("SYST:ERR?")
            if e is None:
                break
            errs.append(e)
            if e.startswith("+0"):
                break
        return errs

    def reset(self):
        self.write("*RST")
        time.sleep(0.3)
        self._refresh_range_cache()

    def selftest(self):
        return self.query("*TST?")

    def clear_status(self):
        self.write("*CLS")

    def beep(self):
        self.write("SYST:BEEP")

    def operation_complete(self):
        return self.query("*OPC?")

    def save(self, slot: int):
        self.write(f"*SAV {int(slot)}")

    def recall(self, slot: int):
        self.write(f"*RCL {int(slot)}")
        time.sleep(0.2)
        self._refresh_range_cache()

    # -- range --------------------------------------------------------------
    def _refresh_range_cache(self):
        r = self.query("VOLT:RANG?")
        if r:
            self.range = range_of(r)
        return self.range

    def get_range(self):
        return self._refresh_range_cache()

    def set_range(self, rng):
        rng = range_of(rng)
        self.write(f"VOLT:RANG {rng}")
        time.sleep(0.1)
        self._refresh_range_cache()
        return self.range

    def range_limits(self):
        return RANGES[self.range]

    # -- output setpoints ------------------------------------------------------
    def apply(self, voltage, current):
        """APPLy: set V and I in one command (manual p. 81)."""
        lim = self.range_limits()
        v = clamp(float(voltage), 0.0, lim["v_max"])
        i = clamp(float(current), 0.0, lim["i_max"])
        self.write(f"APPL {v:.5f}, {i:.5f}")
        return v, i

    def get_apply(self):
        """APPL? -> (V, I) tuple or None."""
        r = self.query("APPL?")
        if not r:
            return None
        try:
            v, i = r.strip().strip('"').split(",")
            return float(v), float(i)
        except (ValueError, AttributeError):
            return None

    def set_voltage(self, v):
        lim = self.range_limits()
        v = clamp(float(v), 0.0, lim["v_max"])
        self.write(f"VOLT {v:.5f}")
        return v

    def get_voltage_setting(self):
        return _parse_float(self.query("VOLT?"))

    def set_current(self, i):
        lim = self.range_limits()
        i = clamp(float(i), 0.0, lim["i_max"])
        self.write(f"CURR {i:.5f}")
        return i

    def get_current_setting(self):
        return _parse_float(self.query("CURR?"))

    def step_voltage(self, direction: int):
        self.write(f"VOLT {'UP' if direction > 0 else 'DOWN'}")

    def step_current(self, direction: int):
        self.write(f"CURR {'UP' if direction > 0 else 'DOWN'}")

    def set_voltage_step(self, step):
        self.write(f"VOLT:STEP {float(step):.6f}")

    def get_voltage_step(self):
        return _parse_float(self.query("VOLT:STEP?"))

    def set_current_step(self, step):
        self.write(f"CURR:STEP {float(step):.6f}")

    def get_current_step(self):
        return _parse_float(self.query("CURR:STEP?"))

    # -- output enable ------------------------------------------------------------
    def output(self, on: bool):
        self.write("OUTP ON" if on else "OUTP OFF")

    def is_output_on(self):
        r = self.query("OUTP?")
        return r is not None and r.strip() in ("1", "ON")

    # -- measurements ------------------------------------------------------------------
    def measure_voltage(self):
        return _parse_float(self.query("MEAS:VOLT?"))

    def measure_current(self):
        return _parse_float(self.query("MEAS:CURR?"))

    def measure_all(self):
        """Return (V_meas, I_meas); either may be None on comms failure."""
        return self.measure_voltage(), self.measure_current()

    @staticmethod
    def infer_mode(v_set, i_set, v_meas, i_meas):
        """Infer CV/CC since the E3632A exposes no CV/CC query.

        CC when the measured current sits at the current limit while the
        measured voltage is below the voltage setpoint.
        """
        if v_set is None or i_set is None or v_meas is None or i_meas is None:
            return "?"
        tol_i = max(0.002, abs(i_set) * 0.01)
        tol_v = max(0.01, abs(v_set) * 0.01)
        if i_set > 0.0005 and abs(i_meas - i_set) <= tol_i \
                and v_meas < v_set - tol_v:
            return "CC"
        return "CV"

    # -- protection -----------------------------------------------------------------------
    def get_ovp(self):
        return _parse_float(self.query("VOLT:PROT?"))

    def set_ovp(self, v):
        v = clamp(float(v), 0.0, OVP_MAX)
        self.write(f"VOLT:PROT {v:.3f}")
        return v

    def get_ovp_state(self):
        r = self.query("VOLT:PROT:STAT?")
        return r is not None and r.strip() in ("1", "ON")

    def set_ovp_state(self, on: bool):
        self.write(f"VOLT:PROT:STAT {'ON' if on else 'OFF'}")

    def ovp_tripped(self):
        r = self.query("VOLT:PROT:TRIP?")
        return r is not None and r.strip() == "1"

    def clear_ovp(self):
        self.write("VOLT:PROT:CLE")

    def get_ocp(self):
        return _parse_float(self.query("CURR:PROT?"))

    def set_ocp(self, i):
        i = clamp(float(i), 0.0, OCP_MAX)
        self.write(f"CURR:PROT {i:.4f}")
        return i

    def get_ocp_state(self):
        r = self.query("CURR:PROT:STAT?")
        return r is not None and r.strip() in ("1", "ON")

    def set_ocp_state(self, on: bool):
        self.write(f"CURR:PROT:STAT {'ON' if on else 'OFF'}")

    def ocp_tripped(self):
        r = self.query("CURR:PROT:TRIP?")
        return r is not None and r.strip() == "1"

    def clear_ocp(self):
        self.write("CURR:PROT:CLE")

    # -- trigger -------------------------------------------------------------------------------
    def set_trigger_source(self, src: str):
        src = "IMM" if str(src).upper().startswith("IMM") else "BUS"
        self.write(f"TRIG:SOUR {src}")
        return src

    def get_trigger_source(self):
        return self.query("TRIG:SOUR?")

    def set_trigger_delay(self, seconds):
        s = clamp(float(seconds), 0.0, 3600.0)
        self.write(f"TRIG:DEL {s:.3f}")
        return s

    def get_trigger_delay(self):
        return _parse_float(self.query("TRIG:DEL?"))

    def set_triggered_levels(self, v, i):
        lim = self.range_limits()
        v = clamp(float(v), 0.0, lim["v_max"])
        i = clamp(float(i), 0.0, lim["i_max"])
        self.write(f"VOLT:TRIG {v:.5f}")
        self.write(f"CURR:TRIG {i:.5f}")
        return v, i

    def get_triggered_levels(self):
        return (_parse_float(self.query("VOLT:TRIG?")),
                _parse_float(self.query("CURR:TRIG?")))

    def initiate(self):
        self.write("INIT")

    def bus_trigger(self):
        self.write("*TRG")

    # -- display / relay ------------------------------------------------------------------------------
    def display(self, on: bool):
        self.write("DISP ON" if on else "DISP OFF")

    def is_display_on(self):
        r = self.query("DISP?")
        return r is not None and r.strip() in ("1", "ON")

    def display_text(self, msg: str):
        self.write(f'DISP:TEXT "{str(msg)[:12]}"')

    def get_display_text(self):
        r = self.query("DISP:TEXT?")
        return r.strip().strip('"') if r else ""

    def clear_display_text(self):
        self.write("DISP:TEXT:CLE")

    def relay(self, on: bool):
        self.write(f"OUTP:REL {'ON' if on else 'OFF'}")

    def get_relay(self):
        r = self.query("OUTP:REL?")
        return r is not None and r.strip() in ("1", "ON")

    # -- status ----------------------------------------------------------------------------------------------
    def status_byte(self):
        return self.query("*STB?")

    def event_status(self):
        return self.query("*ESR?")

    def questionable_condition(self):
        return self.query("STAT:QUES:COND?")

    def questionable_event(self):
        return self.query("STAT:QUES:EVEN?")

    def calibration_count(self):
        return self.query("CAL:COUN?")
