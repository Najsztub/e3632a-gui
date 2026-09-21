"""
Threaded monitor worker for the E3632A.

Polls MEAS:VOLT? / MEAS:CURR? (+ output state) in a QThread at the
configured interval and emits live readings for the GUI, plot and CSV
logger. Two SCPI queries per cycle keep GPIB traffic modest.
"""

import time
from PyQt5.QtCore import QThread, pyqtSignal


class MonitorWorker(QThread):
    reading = pyqtSignal(float, float, float, object, object, object)  # t, V, I, out, Vset, Iset
    plot_data = pyqtSignal(list, list, list, list, list)  # ts, vs, is_, outs, modes
    protection = pyqtSignal(bool, bool)  # ovp_tripped, ocp_tripped
    error_occurred = pyqtSignal(str)
    status_message = pyqtSignal(str, str)

    def __init__(self, instrument, parent=None):
        super().__init__(parent)
        self._instrument = instrument
        self._running = False
        self._interval_ms = 500
        self._max_pts = 1200
        self._t0 = None
        self._ts, self._vs, self._is = [], [], []
        self._outs, self._modes = [], []

    def set_interval(self, ms):
        self._interval_ms = max(100, int(ms))

    def set_buffer_size(self, n):
        self._max_pts = max(60, int(n))

    def stop(self):
        self._running = False

    @property
    def is_running(self):
        return self._running

    def snapshot(self):
        return (list(self._ts), list(self._vs), list(self._is),
                list(self._outs), list(self._modes))

    def run(self):
        if not self._instrument or not self._instrument.connected:
            self.error_occurred.emit("No instrument connected")
            return
        self._running = True
        self._t0 = time.time()
        self._ts.clear(); self._vs.clear(); self._is.clear()
        self._outs.clear(); self._modes.clear()
        self.status_message.emit("Monitoring started", "ok")
        # Cache setpoints for CV/CC inference; refresh every cycle cheaply?
        # OUTP? every cycle doubles traffic — poll it every 5th cycle.
        out_on, v_set, i_set = False, None, None
        cycle = 0
        while self._running:
            t_start = time.time()
            try:
                v = self._instrument.measure_voltage()
                if not self._running:
                    break
                i = self._instrument.measure_current()
                if not self._running:
                    break
                cycle += 1
                if cycle % 5 == 1:
                    out_on = self._instrument.is_output_on()
                    appl = self._instrument.get_apply()
                    if appl:
                        v_set, i_set = appl
                if cycle % 10 == 1:
                    try:
                        self.protection.emit(
                            bool(self._instrument.ovp_tripped()),
                            bool(self._instrument.ocp_tripped()))
                    except Exception:
                        pass
                if v is None or i is None:
                    self.error_occurred.emit("Read failed (None)")
                    time.sleep(0.5)
                    continue
                elapsed = time.time() - self._t0
                mode = self._instrument.infer_mode(v_set, i_set, v, i)
                self._ts.append(elapsed); self._vs.append(v); self._is.append(i)
                self._outs.append(out_on); self._modes.append(mode)
                for buf in (self._ts, self._vs, self._is, self._outs, self._modes):
                    while len(buf) > self._max_pts:
                        buf.pop(0)
                self.reading.emit(elapsed, v, i, out_on, v_set, i_set)
                self.plot_data.emit(list(self._ts), list(self._vs),
                                    list(self._is), list(self._outs),
                                    list(self._modes))
            except Exception as e:  # noqa: BLE001 - keep worker alive
                self.error_occurred.emit(f"Monitor error: {e}")
                time.sleep(0.5)
            elapsed_ms = (time.time() - t_start) * 1000.0
            time.sleep(max(0.0, self._interval_ms - elapsed_ms) / 1000.0)
        self.status_message.emit("Monitoring stopped", "info")
